#!/usr/bin/env python3
"""麦块（Minekuai）面板远程开关服小工具。

只依赖 Python 标准库，方便丢进 GitHub Actions 定时跑。

用法：
    python mkctl.py status
    python mkctl.py start --wait
    python mkctl.py stop --wait
    python mkctl.py restart --wait
    python mkctl.py command "say 5 分钟后重启"

密钥从环境变量 MINEKUAI_API_KEY 读（GitHub Actions 里放 secret，别写进代码）。
实例从 --server 或环境变量 MINEKUAI_SERVER_ID 读；密钥下只有一个实例时可以留空自动识别。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("MINEKUAI_BASE_URL", "https://api.minekuai.cn/panel/client-api").rstrip("/")
TIMEOUT = 30
USER_AGENT = "mkctl/1.0 (+https://github.com/Y0ash/aotu_MKopenserver)"


class ApiError(RuntimeError):
    """面板返回非 2xx，或者请求压根没发出去。"""


def _request(method: str, path: str, payload: dict | None = None, params: dict | None = None):
    """发一个请求，返回解析后的 JSON（空响应返回 None）。"""
    key = os.environ.get("MINEKUAI_API_KEY", "").strip()
    if not key:
        raise ApiError("没有密钥：设置环境变量 MINEKUAI_API_KEY")

    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error") or detail
        except ValueError:
            pass
        raise ApiError(f"HTTP {error.code}：{detail[:300]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ApiError(f"连不上面板：{error}") from None

    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError:
        raise ApiError(f"面板返回的不是 JSON：{body[:200]}") from None


def list_servers() -> list[dict]:
    """把分页的实例列表拉全。"""
    servers: list[dict] = []
    page = 1
    while True:
        data = _request("GET", "/servers", params={"page": page, "per_page": 50}) or {}
        for item in data.get("data") or []:
            servers.append(item.get("attributes", item))
        pagination = (data.get("meta") or {}).get("pagination") or {}
        total_pages = int(pagination.get("total_pages") or 1)
        if page >= total_pages:
            return servers
        page += 1


def resolve_server(explicit: str | None) -> str:
    """决定操作哪个实例：命令行 > 环境变量 > 密钥下唯一的那个。"""
    if explicit and explicit.strip():
        return explicit.strip()
    env = os.environ.get("MINEKUAI_SERVER_ID", "").strip()
    if env:
        return env

    servers = list_servers()
    if len(servers) == 1:
        return str(servers[0].get("identifier"))
    if not servers:
        raise ApiError("这个密钥下面没有任何实例")
    choices = "、".join(f"{s.get('name')}（{s.get('identifier')}）" for s in servers)
    raise ApiError(f"密钥下有多个实例，请用 --server 指定：{choices}")


def info(identifier: str) -> dict:
    """读单个实例的状态，统一成扁平结构。"""
    data = _request("GET", f"/servers/{identifier}") or {}
    stats = (data.get("stats") or {}).get("attributes") or {}
    return {
        "identifier": data.get("identifier") or identifier,
        "name": data.get("name") or "?",
        "state": stats.get("current_state") or data.get("status") or "unknown",
        "suspended": bool(stats.get("is_suspended") or data.get("is_suspended")),
        "resources": stats.get("resources") or {},
    }


def power(identifier: str, signal: str) -> None:
    _request("POST", f"/servers/{identifier}/power", payload={"signal": signal})


def wait_state(identifier: str, target: str, timeout: int, interval: int) -> dict:
    """等到实例进入目标状态；超时抛错（延迟和状态名都写进错误里）。"""
    deadline = time.time() + timeout
    last = None
    while True:
        current = info(identifier)
        if current["state"] != last:
            print(f"[mkctl] 状态：{current['state']}", flush=True)
            last = current["state"]
        if current["state"] == target:
            return current
        if time.time() >= deadline:
            raise ApiError(f"等了 {timeout} 秒还没到 {target}，最后状态是 {last}")
        time.sleep(interval)


def show(data: dict) -> None:
    """打印一行状态信息。"""
    resources = data.get("resources") or {}
    parts = [f"{data['name']}（{data['identifier']}）", f"状态 {data['state']}"]
    if data.get("suspended"):
        parts.append("已被暂停")
    if resources:
        memory_gb = (resources.get("memory_bytes") or 0) / 1024 ** 3
        disk_gb = (resources.get("disk_bytes") or 0) / 1024 ** 3
        parts.append(f"内存 {memory_gb:.2f} GB，磁盘 {disk_gb:.2f} GB")
        uptime = (resources.get("uptime") or 0) / 1000
        if uptime:
            parts.append(f"已运行 {uptime / 60:.0f} 分钟")
    print("[mkctl] " + "，".join(parts))


def cmd_status(args: argparse.Namespace) -> int:
    data = info(resolve_server(args.server))
    show(data)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    identifier = resolve_server(args.server)
    data = info(identifier)
    show(data)
    if data["state"] == "running":
        print("[mkctl] 已经在运行，跳过启动")
        return 0
    if data["suspended"]:
        raise ApiError("实例被暂停了，得先在面板里处理")
    power(identifier, "start")
    print("[mkctl] 已发送启动指令")
    if args.wait:
        data = wait_state(identifier, "running", args.timeout, args.interval)
        show(data)
        print("[mkctl] 启动完成")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    identifier = resolve_server(args.server)
    data = info(identifier)
    show(data)
    if data["state"] == "offline":
        print("[mkctl] 已经是离线状态，跳过")
        return 0
    power(identifier, "stop")
    print("[mkctl] 已发送停服指令")
    if args.wait:
        data = wait_state(identifier, "offline", args.timeout, args.interval)
        show(data)
        print("[mkctl] 已停服")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    identifier = resolve_server(args.server)
    show(info(identifier))
    power(identifier, "restart")
    print("[mkctl] 已发送重启指令")
    if args.wait:
        time.sleep(5)  # 刚发完重启时状态可能还停在 running，先让面板转起来
        show(wait_state(identifier, "running", args.timeout, args.interval))
        print("[mkctl] 重启完成")
    return 0


def cmd_command(args: argparse.Namespace) -> int:
    identifier = resolve_server(args.server)
    _request("POST", f"/servers/{identifier}/command", payload={"command": args.text})
    print(f"[mkctl] 已发送控制台命令：{args.text}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mkctl.py",
        description="麦块面板远程开关服：status / start / stop / restart / command",
    )
    parser.add_argument("--version", action="version", version="mkctl 1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser, waiting: bool = True) -> None:
        sp.add_argument("--server", default=None, help="实例 identifier（8 位短 UUID），留空自动识别")
        if waiting:
            sp.add_argument("--wait", action="store_true", help="等到真正到达目标状态再退出")
            sp.add_argument("--timeout", type=int, default=600, help="最多等多少秒，默认 600")
            sp.add_argument("--interval", type=int, default=10, help="每隔多少秒查一次，默认 10")

    add_common(sub.add_parser("status", help="看当前状态"), waiting=False)
    add_common(sub.add_parser("start", help="启动（已在运行就跳过）"))
    add_common(sub.add_parser("stop", help="正常关闭（已离线就跳过）"))
    add_common(sub.add_parser("restart", help="重启"))
    send = sub.add_parser("command", help="往控制台发一条命令")
    add_common(send, waiting=False)
    send.add_argument("text", help="要发送的命令，比如 \"say hello\"")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # Windows 终端 GBK 时别因为个别字符崩掉
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    handlers = {
        "status": cmd_status,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "command": cmd_command,
    }
    try:
        return handlers[args.command](args)
    except ApiError as error:
        print(f"[mkctl] 失败了：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
