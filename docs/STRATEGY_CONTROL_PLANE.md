# 策略控制面使用说明

> 面向"三个月后的自己 / 接手的人"：一次读明白这套东西**管什么、在哪改、改了会怎样、风险边界在哪**。
> 目录与矩阵是机器校验的（`python -m core.strategy_contract --strict`），本文只解释**怎么用**和**为什么这样设计**。

## 1. 一句话

采集过程中的每一个"主动 / 被动 / 自动"调整动作，都登记成一条**策略**；
每条策略都有**中文名、位置、参数、作用域、开关、建议、统计**；
所有参数**改完立即生效**（不重启），并且可以按 **全局 / 渠道 / 维度 / 链路** 四级分别覆盖。

代码位置（就是全部，没有第二份真源）：

| 层 | 文件 | 作用 |
|---|---|---|
| 目录 | `core/strategy_contract.py` | 30 条策略的**声明**（中文名/族/触发/作用域/参数/接口），`audit()` 出 15 轴矩阵 |
| 参数层 | `core/strategy_params.py` | 唯一的求值入口 `resolve(pid, plat, dim, path)` + `switch_on()` + `clamp()` |
| 决策/执行 | `core/pacing.py`、`core/policy.py`、`crawlers/*` | 闸门、熔断、成功率保护、挑战处置、换道 |
| 暴露 | `webui.py`（策略面板 / 渠道健康 / 接口） | 只读视图 + 运行期干预 |

## 2. 策略按族速查（9 族 31 条）

| 族 | 条数 | 管什么 | 成员 |
|---|---|---|---|
| 节奏 | 5 | 多久采一次（TTL/邻近/节奏/静默窗/错峰） | ttl_tier, near_window, cadence, schedule_clock, quiet_window |
| 限速 | 5 | 多快打（最小间隔/每分上限/并发/渠道内档位/单次预算） | rate_min_gap, rate_per_minute, concurrency, channel_rate, budget |
| 熔断 | 5 | 什么情况停下来、停多久、被记住了怎么换档案 | breaker_switch, breaker_ladder, login_cooldown, challenge_cooldown, session_reset |
| 风险 | 4 | 风险分带、间隔倍率、阻断窗、策略闸门 | policy_gate, pace_factor, block_window, risk_bands |
| 健康 | 1 | 成功率低就自动降频（**可到链路级**） | health_penalty |
| 预热 | 1 | 会话预热与养号 | warmup |
| 身份 | 4 | 指纹一致性、请求头、出口、轮换建议 | stealth_humanize, identity_headers, proxy_route, rotate_advice |
| 挑战 | 3 | 滑块/点选自动尝试、失败拉黑、验证码识别 | slider_attempt, slider_guard, captcha_solve |
| 通路 | 3 | 先走哪条路、被拦就换道、退役通路 | app_fallback, path_fallback, retired_path |

要完整参数清单（含默认值/区间/来源）：跑 `python -m core.strategy_contract`，或看配置页「策略控制」分区（每行都可直接改）。

## 3. 四级作用域：怎么写、谁说了算

作用域串就是参数覆盖的键：

```
plat                  整家渠道      例：fliggy
plat/dim              某渠道的维度  例：fliggy/intl
plat/dim/path         某条链路      例：tongcheng/intl/H5/API
```

* 求值顺序 **链路 → 维度 → 渠道 → 全局 → 声明默认**（`core/strategy_params.py`）；
* 覆盖写在 `config.yaml` 的 `crawler.strategy_overrides`，形状 `{作用域: {参数 id: 值}}`；
* 界面上的「作用域」下拉就是这件事：选中链路后改的参数只影响那一条链路，**不会**落到全局（这条有门禁守着）；
* 关掉某族（`<族>.enabled=false`）的语义**逐族不同**，每条策略的 `effect` 里写明了。例：`channel_rate.enabled=false` 是"忽略定制、回到内置兜底"，**不是**"取消限速"。

### 一个可核对的承诺

**凡是声明了 `channel` / `dimension` / `path` 作用域的参数，消费方都真的按该作用域求值。**

这不是口号，是一条门禁：`tests/test_r1063_scoped_reads_all.py` 会遍历 31 条策略的
全部参数，要求每个"声明了渠道级作用域"的参数要么有按作用域求值的读点、要么在
`STRUCTURAL`（map/list 形状，键/元素本身就是渠道）里、要么在 `KNOWN_GAPS` 里带原因。
**`KNOWN_GAPS` 现在是空表**——意味着没有一条是装饰。

> 反面教材（都已修）：`ttl_tier.fast`、`near_window.*`、`identity_headers.*`、
> `health_penalty.*` 都曾经"界面能按渠道改、消费方读全局"，配了等于没配。

## 4. 常用操作

| 想做的事 | 在哪做 | 注意 |
|---|---|---|
| 改某个参数的全局值 | 配置页 → 策略控制 → 展开行 → 改 → 保存配置 | 越界会被夹到声明区间（界面显示的边界＝落盘的边界） |
| 只改某渠道/维度/链路 | 同上，先选「作用域」，再改 | 保存前会显示「作用域 X：已覆盖 N 项」 |
| 停手（整家 / 某维度 / 某链路） | 策略行 → 作用域下拉 → 「停 15 分钟」 | 停手是**运行期状态**，不写配置；到点自动恢复 |
| 恢复 | 同上「恢复」，或停手表里的恢复钮 | 只解人工停手；自动熔断归「解除」 |
| 中断本轮 | 接口 `POST /api/round/abort` | 递增轮次代际，worker 在下一个检查点收工 |
| 被强风控拦住后换 App 通路 | 不用手动：`app_fallback` 自动做（可关） | 有每日上限 + 冷却 + 就绪门；禁止来回横跳 |
| 备份 / 迁移 / 回滚配置 | 配置页「导出配置 / 导入配置」 | 导入只写进界面脏状态，**点保存才落盘**；导入前会预览差异 |
| 命令行同款能力 | `python -m core.cfg_snapshot export\|diff\|apply <config.yaml> [snapshot.json]` | 只含与默认不同的项；不含用户/凭证/停手 |
| 核对指纹自洽 | `python -m core.fp_audit` | 桌面档/移动档/App 机型池三段；只报能证明的矛盾 |

## 5. 观测口径（面板与接口同源）

`GET /api/strategy` 的几段（数据都来自 `pacing.snapshot()` 与目录，不另算）：

* `strategies[].params[]`：每个参数的**生效值 + 来源**（`default`/`global`/`channel`/`dimension`/`path`）；
* `health`：渠道级 / 维度级 / 链路级的成功率保护倍数；
* `failover`：`preloads`（本轮预置）· `switches`（换道次数）· `rows`（回采条数）· `reasons`（归因：不可用/未配置/被节流/也被拦/无票/被挡）；
* `fingerprint`：桌面档 / 移动档 / App 机型池三段的核账结论（0 处 = 已知矛盾全清）。

`GET /api/pacing`（渠道健康页）另外给：

* 每渠道 `waited_s`：这家本轮**等**了多少秒（闸门睡眠 + 渠道内部限速/退避）；
* `timing`：`wall`（墙钟）· `work`（有效工作）· `gate`（其中限速等待）· `fetch`（真抓取）· `idle_ratio`（空等占比）· `timed_out`（超时渠道数）。

### 读数清单（健康页每一处数字的**唯一**含义）

| 位置 | 读数 | 含义 | 什么时候为空 |
|---|---|---|---|
| 渠道行 `.e2` | `等待 等 210s` | 这家**单渠道**本轮在等的秒数（闸门睡眠 + 渠道内部限速/退避） | 为 0 时不显示 |
| 渠道行 `.e2` | `降频 intl/H5/API ×2` | 成功率保护把某条**链路/维度**压到几倍间隔 | 没有 >1 的项时 |
| 渠道行 `.e2` | `会话 已重建 2 次` | 这家换过几次干净档案；悬停列出判据链 | 从未重建时 |
| 右栏 | `本轮覆盖率 / 本轮计划` | 本轮实发占比、排期总数（快档/慢档/TTL 跳过在图例） | 一条没发时覆盖率显示「—」而不是 0% |
| 右栏 | `本轮换道：预置 · 换道 · 回采` | **本轮**换道动作与救回条数；悬停看每家预算/冷却/上次结果 | 本轮没换道时整行为空 |
| 右栏 | `近 7 天：换道 N 次…救回 M 条` | **跨进程**账本（重启不丢） | 这段时间没记录时不出 |
| 右栏 | `本轮耗时：墙钟 · 有效工作 · 空等% · 闸门等待%` | 墙钟＝提交到收齐；有效工作＝各任务耗时之和；**闸门等待＝我方限速睡眠占墙钟** | 没有耗时样本时整行为空 |

两条**术语纪律**（相混过一次，已拆开）：

* **闸门等待**（占比，全局） ≠ **等待**（秒数，单渠道）。前者回答"我方限速吃了多少时间"，
  后者回答"这一家在等什么"；
* 同一个数字只报一处：`节流跳过` 只在配额轨图例里出现（写作「主动未发」），耗时行不再重复。

**怎么用这两个数**：`gate_ratio` 高 → 慢在等我方限速（调 `channel_rate.*` 是风控代价换速度）；`fetch` 高 → 真的在抓，去优化链路或减少查询条数。

## 6. 风险边界（这些是**范围决定**，不是缺功能）

1. **行为型强风控（极验 v4 / 天御 / reCAPTCHA / 人脸）不自动解**：判的是行为分布与环境指纹，通用开源方案拿不到稳定通过，硬解会把风控分推高。遇到它就记账 → 停手 → 界面给「去验证 / 去登录」。
2. **图像型（几何滑块 / 拼图 / 文字 / 算数 / 点选）自动尝试**：点选需要 ddddocr 检测模型；没有后端就**不尝试**（宁可不动，也不瞎点）。
3. **换道不无限**：每日上限 + 冷却 + 就绪门；失败也占预算，防"PC 被拦 → App 被拦 → PC 再试"的横跳。
4. **降频/限速调快 = 风控代价**：`channel_rate.*`、`rate_min_gap` 等调小会更快，也更容易撞限流。调之前先看 `waited_s` 与 `gate_ratio`。
5. **会话重建会丢登录态**：它把该渠道的浏览器档案整目录改名备份、换一份干净的；
   阈值/冷却/每日上限都在策略面板上调，旧档案随时可还原（`/api/session/restore`）。
6. **鉴权/登录态判不了就不猜**：就绪度只判配置与注册表（`android.enabled`、渠道是否注册），登录态交给试错 + 归因。

## 7. 自检清单（改完配置建议跑一遍）

```bash
python -m core.strategy_contract --strict      # 30 条 × 15 轴：必须 0 缺陷、退出码 0
python -m core.fp_audit                        # 指纹三段：应为「已知矛盾全清」
python -m core.cfg_snapshot diff config.yaml strategy_snapshot.json   # 配置漂移对照
```

回归门禁（本仓约定：设 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）：

```bash
python -m pytest tests/test_r1063_params_all_hot.py tests/test_r1063_strategy_contract.py \
  tests/test_r1063_hot_reload.py tests/test_r1063_strategy_panel.py -q
```
