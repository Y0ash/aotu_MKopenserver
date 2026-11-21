# aotu_MKopenserver

用 GitHub Actions 定时把你**麦块（Minekuai）面板**上的 Minecraft 服务器开起来：
北京时间每天 **06:05** 和 **18:05** 各跑一次，服务器已经在跑就自动跳过，不重复启动。

- 只用 Python 标准库，不用装任何依赖
- API 密钥存在 GitHub Secrets 里，不进代码、不进日志
- 想手动跑、换时间、临时停服，都能在 Actions 页点按钮完成

## 它是怎么工作的

```
GitHub Actions（cron 到点）
        │  python mkctl.py start --wait
        ▼
麦块 API  https://api.minekuai.cn/panel/client-api
        │  POST /servers/{id}/power  {"signal": "start"}
        ▼
你的 MC 服务器（先查状态：running 就跳过）
```

`mkctl.py` 做的事：读实例状态 → 如果已经 `running` 就打印一句跳过 → 否则发 `start` →
轮询到状态真正变成 `running` 才退出（最多等 10 分钟）。任何一步失败都会以非 0 退出码结束，
Actions 里就是一片红，能第一时间发现。

## 部署（只需要三件事）

### 1. 加一个 Secret

仓库 → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
| --- | --- |
| `MINEKUAI_API_KEY` | 你的麦块 API 密钥（`mkc_` 开头那一整串） |

密钥在麦块面板的「API 密钥」页面里创建，权限跟你在面板上一致；泄露了就在那边删掉重建。

### 2. 定时时间已经配好了

`.github/workflows/minecraft.yml` 里：

```yaml
on:
  schedule:
    - cron: '5 22 * * *'   # 北京时间 06:05
    - cron: '5 10 * * *'   # 北京时间 18:05
```

GitHub 的 cron **只认 UTC**，所以北京时间要减 8 小时。想改成别的时间，照这个表换：

| 北京时间 | cron（UTC） |
| --- | --- |
| 06:05 | `5 22 * * *` |
| 08:00 | `0 0 * * *` |
| 12:30 | `30 4 * * *` |
| 18:05 | `5 10 * * *` |
| 23:00 | `0 15 * * *` |

> 想让它晚上自动关服？再加一条 `- cron: '0 14 * * *'`（北京 22:00），
> 然后把那条 job 的 `start` 换成 `stop` 就行。

### 3. （可选）填实例 ID

密钥下面只有一个实例的话，什么都不用填，脚本会自动认出来。有多个实例时，
在 workflow 的 `server` 输入框里填上实例的 identifier（8 位短 UUID，面板 URL 里能拿到，
比如 `b7f93908`），或者直接在仓库里加一个 Variable `MINEKUAI_SERVER_ID`。

## 手动触发

仓库 → **Actions → 麦块自动开服 → Run workflow**，可以选：

| action | 效果 |
| --- | --- |
| `start` | 启动（已在运行就跳过） |
| `stop` | 正常关服，等地到 `offline` |
| `restart` | 重启 |
| `status` | 只看状态，不动服务器 |

第一次部署完，建议先点一次 `status` 确认密钥通，再点一次 `start` 看开服流程。

## 本地用

```powershell
# Windows PowerShell
$env:MINEKUAI_API_KEY = "mkc_xxxxxxxx"
python mkctl.py status
python mkctl.py start --wait
python mkctl.py command "say 5 分钟后重启"
```

```bash
# Linux / macOS / GitHub Actions
export MINEKUAI_API_KEY="mkc_xxxxxxxx"
python mkctl.py status
python mkctl.py start --wait --timeout 900
```

命令一览：

| 命令 | 说明 |
| --- | --- |
| `status` | 名称、状态、内存/磁盘占用、已运行多久 |
| `start [--wait]` | 启动；`--wait` 等真正 running 再返回 |
| `stop [--wait]` | 正常关闭 |
| `restart [--wait]` | 重启 |
| `command "say hi"` | 往控制台发一条命令 |
| `--server <id>` | 指定实例，默认自动识别 |
| `--timeout <秒>` | 等待上限，默认 600 |
| `--interval <秒>` | 轮询间隔，默认 10 |

## 常见问题

**会不会重复开服？**
不会。`start` 先查状态，`running` 就直接跳过；Actions 那边还加了 `concurrency`，
同一时间只会有一个 job 在跑。

**到点了但没触发？**
GitHub 的 `schedule` 是「尽力而为」，高峰期可能延迟几分钟到几十分钟。
要求秒级准点的话，Actions 不适合，得用常驻的服务器跑 cron。

**公开仓库定时任务会不会被停？**
公开仓库 60 天没有任何提交活动时，GitHub 会暂停 `schedule`。随便提交一次就会恢复。

**密钥会不会泄露？**
代码里不写密钥，只在 `secrets.MINEKUAI_API_KEY` 里引用；日志里打印的是实例名和状态，
不含密钥。`mkctl.py` 也只从环境变量读。

**为什么用 UTC 不写 `timezone:`？**
`timezone` 字段是新特性，写法不对会让整个 workflow 校验失败；UTC 写法在所有环境下都稳。

## 实测记录（2026-11-21）

部署完在 Actions 页手动触发了三次，全部 success：

| run | 动作 | 结果 |
| --- | --- | --- |
| #1 | `status` | `麦块公益实例（b7f93908），状态 running` —— 密钥通了 |
| #2 | `stop` | `running` → `offline`，用时约 21 秒 |
| #3 | `start` | `offline` → `starting` → `running`，用时约 2 分钟 |

也就是说 cron 到点跑的那条 `start` 路径已经真机验证过：先查状态、再发 `start`、
轮询到 `running` 才退 0。

## 目录

```
.
├── mkctl.py                       # 面板 API 小工具（唯一需要维护的代码）
├── tests/test_mkctl.py            # 离线单元测试，不碰真面板
└── .github/workflows/minecraft.yml # 定时开服
```

跑测试：

```bash
python -m unittest discover -s tests -t .
```

## API 参考

面板 API 文档：基础地址 `https://api.minekuai.cn/panel/client-api`，
`Authorization: Bearer <key>`，限流 300 次/分钟。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/servers` | 实例列表（分页） |
| GET | `/servers/{id}` | 单个实例状态，读 `stats.attributes.current_state` |
| POST | `/servers/{id}/power` | `{"signal": "start\|stop\|restart\|kill"}` |
| POST | `/servers/{id}/command` | `{"command": "say hello"}` |
| GET | `/servers/{id}/startup` | 启动变量 |
| PUT | `/servers/{id}/startup/variable` | 改单个启动变量 |
| GET | `/servers/{id}/files/contents?file=/server.properties` | 读文件（≤1MB） |

## 许可

MIT，见 [LICENSE](LICENSE)。
