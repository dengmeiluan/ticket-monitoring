# 渠道状态与「哪个面说哪句话」

> 目的：同一件事（某家渠道现在为什么不动）必须在**节流行 / 诊断卡 / 三率表**
> 三个面上说同一句话。这份表是单一真源：新增状态时三处都要填，
> `tests/test_r1734_state_vocabulary.py` 会检查它和代码没漂。

## 六个"不在正常采集"的状态

| 状态 | 判据（唯一真源） | 载荷字段 | 节流行 | 诊断卡 | 三率表 |
|---|---|---|---|---|---|
| **停手** | `user_data/<plat>/strategy_halt.json`（`core.policy.read_halt`） | `/api/pacing.channels[p].halt`、`/api/three-rates.halts[p]` | `停手 Nh` / `停手 Nm`，ev 行「人工停手中，剩 N 分钟」 | `人工停手 Nh` + 「恢复」按钮 | 渠道名后 `· 停手`（title 给原因与剩余） |
| **停服** | 账本最后一条 `path_status=unsupported` 且 note 含「停服」（`_retired_reason`） | `/api/pacing.advice.state="retired"`、`/api/health.diag[].retired` | `网页已停服` | `网页已停服`，**不渲染任何按钮**（勾了也不会采） | 渠道不在采集清单，故无行 |
| **未在清单** | `cfg.users[].platforms`（`_enabled_plats`） | `/api/pacing.advice.state="disabled"`、`/api/health.diag[].no_plan` | `未在清单` | `未在清单` + 「去启用」按钮 | — |
| **冷却中** | breaker `until`（`core.pacing.ChannelBreaker`） | `/api/pacing.channels[p].state/reason/remain_s` | `冷却中`，ev「剩 N 分钟自动解除」 | 卡 kind `ip`/`captcha`/`timeout` → 对应按钮 | 行内 `· 全失败` 或正常成绩 |
| **夜间静默** | `pacing.cfg.scan_quiet_start/end`（`quiet_now()`） | `/api/pacing.quiet`、`/api/pulse.quiet` | 建议文案带「当前在夜间静默窗（01:00–07:00）」 | — | — （页面顶部一条 `🌙 夜间静默中…`） |
| **零出数** | `rates.snapshot()` 补出的 `no_ok` 行（基线只统计成功状态） | `/api/three-rates.by_path[].no_ok` | — | — | `· 全失败`（琥珀）+ 合计行「其中 N 条通路 0 出数」 |

## 三条不许退化的规矩

1. **状态先于动作**：停手/停服/未在清单时，不给「立即扫描」「打开登录」
   「自检」这类动作——那会让人去做无效操作（r1639/r1652）。
2. **建议必须有按钮**：文案让人做的事，界面上必须真有一个按钮
   （r905 / r1726）。唯一例外是「停服」：没有可做的动作，所以**零按钮**。
3. **口径不许冒充**：基线只统计成功状态；零出数通路由三率页补出，
   脚注必须分段说明（r1728）。

## 颜色语义

| 颜色 | 含义 | 例子 |
|---|---|---|
| 绿色 | 成功/正常 | `ok`、`验证已通过` |
| 琥珀 | 需人处理或等一会 | `全失败`、`冷却中`、`cookie_expired` |
| 红色 | 真故障 | `采集停了`、`ip` 拦截 |
| 中性灰 | 我们主动为之 | `停手`、`未在清单`、`夜间静默` |
