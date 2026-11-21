"""mkctl.py 的离线单元测试：全部用假的 HTTP 响应，不碰真面板。"""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

import mkctl

ENV = {"MINEKUAI_API_KEY": "mkc_test"}


class FakeResponse(io.BytesIO):
    """够 urllib 用的假响应：支持 with 和 read()。"""

    def __init__(self, payload: bytes, status: int = 200):
        super().__init__(payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def server_object(identifier="b7f93908", name="麦块公益实例", state="running", **resources):
    return {
        "object": "server",
        "attributes": {"identifier": identifier, "name": name, "status": None},
        "stats": {"attributes": {"current_state": state, "resources": resources}},
    }


def flat_server(identifier="b7f93908", name="麦块公益实例", state="running", **resources):
    return {
        "identifier": identifier,
        "name": name,
        "status": None,
        "stats": {
            "object": "stats",
            "attributes": {
                "current_state": state,
                "is_suspended": False,
                "resources": resources,
            },
        },
    }


class StatusTests(unittest.TestCase):
    def test_flat_response_is_parsed(self):
        payload = flat_server(memory_bytes=1024 ** 3, disk_bytes=2 * 1024 ** 3, uptime=60000).copy()
        payload["stats"]["attributes"]["current_state"] = "running"
        with mock.patch.dict(os.environ, ENV), mock.patch(
            "urllib.request.urlopen", return_value=FakeResponse(json.dumps(payload).encode())
        ):
            data = mkctl.info("b7f93908")
        self.assertEqual(data["state"], "running")
        self.assertEqual(data["name"], "麦块公益实例")
        self.assertEqual(data["resources"]["memory_bytes"], 1024 ** 3)

    def test_describe_line_shows_state_and_resources(self):
        data = {
            "identifier": "b7f93908",
            "name": "麦块公益实例",
            "state": "offline",
            "suspended": False,
            "resources": {"memory_bytes": 0, "disk_bytes": 1024 ** 3, "uptime": 0},
        }
        with mock.patch("builtins.print") as fake_print:
            mkctl.show(data)
        line = fake_print.call_args[0][0]
        self.assertIn("麦块公益实例", line)
        self.assertIn("状态 offline", line)
        self.assertIn("磁盘 1.00 GB", line)


class ListTests(unittest.TestCase):
    def test_pagination_is_followed(self):
        pages = {
            1: {"data": [server_object("aaaaaaa1")], "meta": {"pagination": {"total_pages": 2}}},
            2: {"data": [server_object("bbbbbbb2")], "meta": {"pagination": {"total_pages": 2}}},
        }

        def fake_urlopen(request, timeout=None):
            page = int(request.full_url.split("page=")[1].split("&")[0])
            return FakeResponse(json.dumps(pages[page]).encode())

        with mock.patch.dict(os.environ, ENV), mock.patch("urllib.request.urlopen", fake_urlopen):
            servers = mkctl.list_servers()
        self.assertEqual([s["identifier"] for s in servers], ["aaaaaaa1", "bbbbbbb2"])

    def test_single_server_is_auto_resolved(self):
        body = {"data": [server_object()], "meta": {"pagination": {"total_pages": 1}}}
        with mock.patch.dict(os.environ, ENV), mock.patch(
            "urllib.request.urlopen", return_value=FakeResponse(json.dumps(body).encode())
        ):
            self.assertEqual(mkctl.resolve_server(None), "b7f93908")
            self.assertEqual(mkctl.resolve_server("explicit"), "explicit")

    def test_multiple_servers_need_explicit_id(self):
        body = {
            "data": [server_object("aaaaaaa1", "一服"), server_object("bbbbbbb2", "二服")],
            "meta": {"pagination": {"total_pages": 1}},
        }
        with mock.patch.dict(os.environ, ENV), mock.patch(
            "urllib.request.urlopen", return_value=FakeResponse(json.dumps(body).encode())
        ):
            with self.assertRaises(mkctl.ApiError) as caught:
                mkctl.resolve_server(None)
        self.assertIn("aaaaaaa1", str(caught.exception))


class ErrorTests(unittest.TestCase):
    def test_missing_key_is_reported_before_any_request(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(mkctl.ApiError) as caught:
                mkctl._request("GET", "/servers")
        self.assertIn("MINEKUAI_API_KEY", str(caught.exception))

    def test_http_error_uses_panel_message(self):
        error = urllib.error.HTTPError(
            "https://api.minekuai.cn/panel/client-api/servers",
            401,
            "Unauthorized",
            {},
            io.BytesIO(json.dumps({"error": "密钥无效"}).encode()),
        )
        with mock.patch.dict(os.environ, ENV), mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(mkctl.ApiError) as caught:
                mkctl._request("GET", "/servers")
        self.assertEqual(str(caught.exception), "HTTP 401：密钥无效")


class WaitTests(unittest.TestCase):
    def test_wait_stops_when_target_reached(self):
        states = iter(["starting", "starting", "running"])

        def fake_info(identifier):
            return {"identifier": identifier, "name": "麦块公益实例", "state": next(states), "suspended": False, "resources": {}}

        with mock.patch.object(mkctl, "info", fake_info), mock.patch.object(mkctl.time, "sleep", lambda _: None):
            data = mkctl.wait_state("b7f93908", "running", timeout=60, interval=0)
        self.assertEqual(data["state"], "running")

    def test_wait_times_out_with_last_state(self):
        with mock.patch.object(mkctl, "info", lambda _: {"state": "offline", "resources": {}}), mock.patch.object(
            mkctl.time, "sleep", lambda _: None
        ):
            with self.assertRaises(mkctl.ApiError) as caught:
                mkctl.wait_state("b7f93908", "running", timeout=0, interval=0)
        self.assertIn("offline", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
