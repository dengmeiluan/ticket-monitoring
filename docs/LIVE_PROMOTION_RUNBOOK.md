# Live 切换 Runbook（主树 10 渠道 → 8765）

> 状态：**已于 2026-11-03 08:58 执行**（由并行发版会话/用户授权）；现场复核
> 2026-11-03 09:20。本文保留切换与回滚记录。
> **执行结果**：live PID **47952**，cwd `D:\idea_project\_release_ab04`，启动
> 08:58:06；`/api/channel-dims` **10 家**、`webui.py` sha12 `6c85a00f14c1`、
> config 与主树 diff=0；`enabled_platforms` 6、诊断卡 7（5 浏览器 + 2 个已启用 App）。
> Release 当前为 `v1.0` → `e65cee1`（2026-11-03 09:54 由 `ab04c22` 重指，ghcr `latest` 同 digest）；live 树 `ab04c22` 正文 10 渠道，四资产 digest 4/4。该树**不含**
> r933–r953（多程数据层/采集/只读 API/配置卡/概览整单卡/来源页/整单历史/CSV 导出/日桶守卫等），仍待下一次发版。

## 0. 现场事实（切换前复核，不要凭本文直接操作）

| 项 | 实测 |
|---|---|
| live 进程 | PID **47952**，cwd `D:\idea_project\_release_ab04`，启动 08:58:06 |
| live 启动命令 | `python main.py --restart-delay 3` |
| live 配置 | `_release_ab04/config.yaml` 与主树 `config.yaml` **diff=0** |
| 数据/日志/登录态 | live 树的 `data`、`logs`、`user_data` 都是**主树的符号链接**（同一份文件） |
| live 当前能力 | **10 渠道代码**（live 树 `ab04c22`，webui sha12 `6c85a00f14c1`）；`/api/channel-dims` 10 家；`enabled_platforms` 6（配置未变） |
| 主树候选 | 10 渠道 + App/浏览器国际往返；tracked collect **6643**；干净克隆 `1c0b8c4` 全量 **6597 passed / 46 skipped / 0 failed**（6643 口径）；UI **670/670**；四平台 `release-build` 从本次文档提交重建后回填资产 SHA256 |

因为数据/日志/登录态共享，切换**不需要迁移数据库、日志或登录快照**；旧 live 树保留作回滚。

> **2026-11-03 13:14 待发版增量**：r933–r956 已入库/落盘（至 `c116273` + r956
> 矩阵；多程数据层/配置形状/实际渠道错峰/日桶下限守卫/携程多程解析与 `fetch_multi`/
> 轮尾采集/只读 API/配置卡/概览整单卡/来源页/过期首段不提醒/整单历史 sparkline/
> CSV 导出/矩阵 ✓ 仅 2 段）；live `_release_ab04` 仍停在 `ab04c22`，下一次发版必须
> 按最终树重建四平台包；当前候选
> `0c4cc2aa4da3966a0628044ae3bf84ffe4b8144d0ed35ab8c468c75c8064bab4`
> （117,001,794 bytes / 1027 entries，源码 `318a70d`，含 cv2/numpy 与 App 锁 WIP）
> 只是当前快照；冻结后若树再变必须重算。
> **计数陷阱**：README/EN 的 tracked 计数必须按干净 HEAD 实收同步；当前 tracked
> **6212**（旧 6168 已过期）。`release_align_check --local` 必须 **25/25**；当前实测
> **25/25 PASS**（14:50），静态站已按当前树重烘（站点戳 `code:eac4fcd5bcf9`）。
> 站点尚未发布，推送后 Pages 才更新。
> 脏树若因未提交文档/测试不同步显示 <25，先分清「值变了」和「设计坏了」，不要为了
> 让门禁变绿改测试。

## 1. 切换前检查（只读）

```bash
cd /d/idea_project/ticket-monitoring
date
netstat -ano | grep ':8765' | grep LISTENING
cat ../_release_final_72d/.monitor.pid
tail -30 logs/monitor.log     # 确认下一轮扫描时间/是否正在扫描
```

同时用 `psutil` 或 PowerShell 核对 PID 的命令行/cwd/启动时间：

```python
import psutil, datetime
p = psutil.Process(68044)
print(p.cmdline(), p.cwd(), datetime.datetime.fromtimestamp(p.create_time()))
```

必须满足：

- 只有一个 `main.py` 监听 8765；
- 不在扫描轮中间（避免停进程打断采集/设备）；
- 主树连续 ≥5 分钟无写入（并行会话停手）；
- 主树配置仍是预期：`fliggy` 不在 `users[].platforms` 与 `crawler.warmup.platforms`；
- 已知会改变的行为：主树把 10 渠道能力/新 App 模块带进 live；App 渠道仍需 `android.enabled=true` 且显式写入 `users[].platforms` 才会跑。

## 2. 切换（需授权后执行）

```bash
# 2.1 停 live（先走 PID 文件；不要直接 kill 未知进程）
cd /d/idea_project/_release_final_72d
powershell -ExecutionPolicy Bypass -File stop.ps1
# 确认端口已释放、进程已退出
netstat -ano | grep ':8765' | grep LISTENING || true

# 2.2 从主树启动（保持 live 原参数）
cd /d/idea_project/ticket-monitoring
powershell -ExecutionPolicy Bypass -File start.ps1
# 或保持原参数直接后台启动：
# python main.py --restart-delay 3
```

说明：`start.ps1` 会写主树 `.monitor.pid` 与 `logs/monitor.out.log`；若使用原命令手动启动，也由 `main.py` 维护 `.monitor.pid`。不要同时启动两棵树。

## 3. 切换后验收（真实接口 + 真实渲染）

```bash
python - <<'PY'
import json, urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for u in ("http://127.0.0.1:8765/api/channel-dims",
          "http://127.0.0.1:8765/api/health",
          "http://127.0.0.1:8765/api/login-state"):
    try:
        j = json.load(op.open(u, timeout=8))
        if "channels" in j:
            print(u, [c["plat"] for c in j["channels"]])
        else:
            print(u, "enabled=", j.get("enabled_platforms"),
                  "platforms=", sorted((j.get("platforms") or {}).keys()))
    except Exception as e:
        print(u, "ERR", e)
PY
```

必须满足：

- `/api/channel-dims` **10 个渠道**（5 浏览器 + 5 App）；
- `enabled_platforms` 仍是预期集合（当前无 fliggy；App 渠道只在配置显式启用时出现）；
- `/api/login-state` 无误报 `needs_login`（飞猪不要求恢复）；
- 配置页矩阵 10 列、App 缺口条正确、`console-dims` 内容与截图同源；
- 首轮真实采集有日志、无重复调度、无端口双进程；
- 8765 PID 的 cwd 已是 `_release_ab04`（不是旧的 `_release_final_72d`）。

## 4. 回滚（任一验收失败）

```bash
# 4.1 停主树进程
cd /d/idea_project/ticket-monitoring
powershell -ExecutionPolicy Bypass -File stop.ps1
# 4.2 从旧 live 树按原参数启动
cd /d/idea_project/_release_final_72d
powershell -ExecutionPolicy Bypass -File start.ps1
```

回滚不需要恢复 data/logs/user_data（三者仍是指向主树的同一份符号链接）；配置两树一致。旧 live 树在切换后**不要删除**，直至主树 live 稳定。

## 4.5 GitHub Release 正文同步（发布时必须，正文不是 Live 开关）

名称与叙事保持「初版式」不变，但**渠道/矩阵/轴计数必须来自最终树**。
线上 Release 已于 **2026-11-03 01:54Z** 更新为 10 渠道正文（当前源码 `e65cee1`；
00:57Z 时点为 `ab04c22`；两轮四资产 digest 均与正文 SHA 一致）；下一次发版仍以 `docs/RELEASE_BODY.md`
为 canonical 源，替换 `{{…}}` 占位符后发布；`tests/test_release_body_source.py`
会拦旧计数/漏渠道/多程不实。

- 名称恒定「机票监控台 · 初版（滚动更新）」；`v1.0` 最后移到**实际构建**的 SHA。
- 必改计数：`7 家渠道` → `10 家渠道（5 浏览器 + 5 App）`；
  `7×7 能力矩阵` → `10 渠道 × 7 维度`；`7 家 × 11 轴` → `10 家 × 11 轴`。
- 渠道表补齐 **携程 App / 同程 App / 飞猪 App**；往返范围按
  `core/channels.py::DIMENSION_SCOPE` 生成（含「同程 PC 国际」「途牛 H5 国际」
  「同程 App 仅国际」等），不手写第二份。
- 多程写「携程 PC 2 段已生产验证（¥1476），矩阵 ✓ 仅 2 段；3+ 段/缺口程未验；其余九家 `""`」；不得宣称全段可用。
- 正文里的测试/UI/树/资产数字只用**冻结后**的门禁与真实包；版本号/SHA 与
  tag、资产一致；发布后用 API 回读 name/body/tag/assets 四者一致。

## 5. 红线

- 不允许两棵树同时监听 8765 或同时驱动 MuMu；先停后起。
- 不复制/覆盖 `data`、`logs`、`user_data` 符号链接；不删除旧 live 树。
- 不在扫描轮中间切换；不在并行会话写入主树时切换。
- 发布/推送/tag/Release/Pages/live 切换均需用户明确授权。
- 飞猪继续暂停；不要把 `fliggy` 加回 platforms 或 warmup。
