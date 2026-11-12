# 看门狗：让"监控进程死了"这件事被看见

> 2026-11-12 事故：一次错误的探活把主服务打死，**没有任何机制发现或拉起它**，
> 二十多分钟后才被人工察觉。监控程序最坏的失败模式，就是它自己停了却没人知道。

## 心跳

`main.py` 每 30 秒原子写一次 `data/.heartbeat`：

```json
{"pid": 81528, "ts": 1794431895, "at": "2026-11-12 05:18:15"}
```

- 写失败一律静默（心跳绝不能影响采集主流程）；
- 原子替换（先写 `.tmp` 再 `os.replace`），避免读到半截文件被误判成"卡死"。

## 看门狗

```bash
python tools/watchdog.py               # 前台守护，Ctrl+C 退出
python tools/watchdog.py --stale 240   # 心跳超过 240 秒视为卡死
python tools/watchdog.py --once        # 只查一次（可挂计划任务）
python tools/watchdog.py --dry-run     # 只判定，不动手
```

三态判定（`decide()` 是纯函数，单测覆盖）：

| 心跳 | 进程 | 动作 |
|---|---|---|
| ≤ stale | 在 | `ok`，什么都不做 |
| 陈旧/缺失 | 在 | `kill_restart`（卡住：先杀再起） |
| 陈旧/缺失 | 不在 | `restart`（已退出：直接起） |

事件写 `logs/watchdog.log`。

## 两条硬约束

1. **不要用 `os.kill(pid, 0)` 探活**——Windows 上它对任意信号都走
   `TerminateProcess`，探一下就把目标杀了（本仓库真实事故）。Windows 走
   `tasklist /FI "PID eq N" /NH`，POSIX 才用 `os.kill(pid, 0)`。
2. **测试只杀替身进程**：`test_r1755_watchdog.py` 里真起一个 `sleep 120`
   的假进程验证 `kill_pid`，绝不对主服务动手。

## 开机自启（Windows，可选）

```powershell
# 每天登录时拉起看门狗（它自己会常驻）
schtasks /Create /TN "tm-watchdog" /TR "cmd /c cd /d D:\idea_project\ticket-monitoring && python tools\watchdog.py" /SC ONLOGON /RL LIMITED
```
