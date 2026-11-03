# 全链路爬取率作战手册

> 目标：**同样的轮次里拿到更多行数据，同时不把渠道推到「封」的那一档**。
>
> 配套文档：设备身份与登录态看 `docs/DEVICE_IDENTITY_PLAYBOOK.md`；
> 限流归因与阈值看 `docs/RATE_LIMIT_PLAYBOOK.md`。本文只讲**全链路怎么分工、
> 怎么量、怎么调**，不重复前三份的论证。

---

## 1. 一条采集链路的五段与三层

「风控」和「爬取率」不是两个目标，是**同一条流水线上游和下游**的关系：
上游被拦 → 下游没数。所以先看五段各自卡在哪。

| 段 | 典型渠道 | 风险点 | 产量瓶颈（和风控无关的那半） | 手段落点 |
|---|---|---|---|---|
| PC 列表 | 去哪儿 / 携程 / 同程 / 途牛 | 深链直入无 referer、无风控 cookie → 444 | 会话被自家锁抢走 → 整轮让位 | 预热 + `profile_wait_s` + 指纹自洽 |
| H5 列表 | 去哪儿 H5 / 飞猪 H5 | 移动 UA 与桌面指纹串味 | 视口/`use_mobile` 切换漏还原 | `STEALTH_JS` 两档互斥 + 还原守卫 |
| 直连 API | 去哪儿 POST / 途牛特价 | TLS/JA3 一眼是 Python | 会话过期后仍在打 | `curl_cffi` + 登录墙判据 |
| App | 携程 / 飞猪 / 去哪儿 / 同程 / 智行 | 设备身份跳变、root/模拟器痕迹 | **坐标点击在动画期间点空**、ANR、息屏 | 身份层 + 隐藏层 + **实例调优** |
| 日历 | 携程 / 智行日历 | 日历接口对「未预热会话」返回空 | 逐日循环里一处失败拖垮整段 | 预热 + 逐日记账隔离 |

**结论**：五段里只有 App 段有「完全与风控无关的产量损失」（动画/息屏/ANR），
PC/H5/API 段的产量损失几乎都来自**会话卫生**（锁、预热、cookie）。所以提产量
的第一优先级不是「更快」，而是「别丢轮次」。

---

## 2. 爬取率的构成（把它写成公式，才能知道该改哪项）

```
拿到行数 ≈ 轮次 × 渠道数 × 日期数 × (1 - 损失率) × 平均行数
损失率 = busy + stuck + blocked + login + timeout + parse_error + 真无票
```

现场量级（仓库既有归因，1997 次样本）：

| 损失类 | 占比 | 性质 | 处置 |
|---|---|---|---|
| 抢不到自家锁（SessionBusyError） | 38.9% | **自家** | `profile_wait_s`（本轮新增） |
| 444 / 202 软拒 | 38.4% | 会话没养熟 | 预热 + cookie 判据 |
| 挑战 / 登录墙 | 22.8% | 风控 | 停手 + 退避（`riskscore`） |
| 真 429 | **0.3%** | 风控（频率） | 降速 |

**前两项占 77%，都不是「对方在拦你」。** 这就是为什么「换 IP / 加代理」
对你的爬取率几乎没有帮助，而下面这三件小事帮助很大。

---

## 3. 本轮新增的四把扳手

### 3.1 `crawler.profile_wait_s`：别把整轮丢给一把锁

```yaml
crawler:
  profile_wait_s: 20      # 0=立刻让位（原行为）
```

同一个渠道只有一个 persistent profile，登录窗口 / 探针面板 / 定时采集抢同一把锁。
原来抢不到就抛 `SessionBusyError`，整轮放弃（历史 38.9% 的失败样本）。
现在**最多等 20 秒**：登录窗口通常 30–60s 内结束，等一下比丢一轮便宜。

- 等待发生在**持锁之前**，不违反「不持锁睡眠」那条教训；
- 等不到仍然抛 `SessionBusyError` → 上层照旧让位，语义不变；
- 默认 0，既有行为逐字不变。

### 3.2 `android.tuning`：把 App 段「与风控无关的报废」掐掉

```yaml
android:
  tuning:
    enabled: true
```

- 三档动画归零（`window/transition/animator_duration_scale=0`）：
  **坐标点击在动画期间会落到空处**，账本记成「设城市失败 / 页面认不出」，
  人看着像「这条通路时好时坏」；
- `svc power stayon true` + 屏幕超时置最大 + 关屏保：息屏后 `screencap` 拿黑图、
  `dump` 拿空层级，表现是 `no-ui`，健康检查看不到（它发生在「设备就绪」之后）；
- 预确认沉浸模式弹层：避免全屏页被系统弹层挡住；
- **刻意不动分辨率/DPI**：所有 App 坐标按现有竖屏写死，改了全渠道一起瘫。

### 3.3 停顿改成对数正态（`_sleep`）

页内间隔从「均匀分布」换成 **对数正态夹区间**：同样的均值下给出「多数短、
偶发长」的重尾形状。均匀间隔本身是最便宜的机器人特征之一，而区间语义
（`delay_min..delay_max`）一个字没改。

### 3.4 `crawler.geo`：让时区/语言和出口 IP 对上

```yaml
crawler:
  geo:
    locale: zh-CN            # 默认值，不写也行
    timezone: Asia/Shanghai
    # 也可按渠道覆盖：qunar: {timezone: Asia/Shanghai}
```

挂着异地/境外出口，页面却报 `Asia/Shanghai` + `zh-CN`，「IP 在 A 地、时区在
B 地」是最便宜的一条矛盾判定。默认不写 = 行为完全不变（`fingerprint()` 仍是
固定 9 键，geo 只改值、不加键）。

---

## 4. 度量闭环：先量，再改，再复测

```powershell
python scripts/yield_report.py                        # 人看
python scripts/yield_report.py --json                 # 机读，可接监控
python scripts/yield_report.py --profile 邓美鸾 --interval 30
```

输出三块：爬取率（Wilson 下界）、登录连击与下次可试时间、设备身份。

**口径（重要，别自己另算一套）**：

- 一次 `safe_fetch` = 一个样本；**只有 `rows>0` 才算成功**；
- `login / blocked / soft_reject / timeout / parse_error` 全算失败；
- **抢不到自家锁（SessionBusyError）不计入**渠道成功率——用自家冲突惩罚对方站点
  是双重错误；
- 建议间隔看 **Wilson 下界**，不看点估计：3/3 的下界只有 0.44，不会被误当成
  「100% 稳」而加速。

闭环节奏：

| 频率 | 动作 |
|---|---|
| 每轮 | 看日志里有没有 `风控评分`（不是 calm 就有事）与 `爬取率建议`（factor≠1） |
| 每天 | 跑一次 `yield_report.py`，看每渠道 `样本/成功/下界/间隔建议` |
| 每周 | 按建议改 `cadence.<渠道>` 或 `schedule.interval_minutes`，**一次只改一个**，48h 后复测 |

间隔建议阶梯（下界 → 倍率）：`≥0.90 → 0.8×`、`≥0.70 → 1.0×`、`≥0.40 → 1.5×`、
`<0.40 → 2.5×`、样本 <5 → 不判。**下界 <0.40 的时候先修因果链（预热/锁/登录），
不要靠继续降频解决。**

---

## 5. 三档参数（按你现在的实际状态选，不要跳档）

| 键 | 保守（刚被风控过） | 均衡（默认） | 激进（长期干净） |
|---|---|---|---|
| `schedule.interval_minutes` | 45 | 30 | 20 |
| `schedule.jitter_minutes` | 12 | 8 | 5 |
| `crawler.max_concurrency` | 1 | 2 | 2（**不建议再高**） |
| `crawler.rate.min_gap_s` | 6 | 3 | 2 |
| `crawler.profile_wait_s` | 30 | 20 | 10 |
| `crawler.humanize_rounds` | 3 | 2 | 1 |
| `crawler.breaker.base_s` | 600 | 300 | 300 |
| `android.keep_app_alive` | false | false | true |
| `cadence.tuniu` | 60 | 45 | 45 |

激进档的前提是 `yield_report` 的**下界 ≥0.80 且连续 3 天没有 `captcha`/`login`**。
不满足就退回均衡档——这条比任何参数都重要。

---

## 6. 五段各自的最后一公里

**PC 列表**：预热成功的唯一判据是**风控 cookie 是否落下**（qunar `QN1/QunarGlobal/
QN205/QN277`，ctrip `cticket/_bfa/MKT_CKID`）。没落下就重试深链是无用功。

**H5**：`use_mobile` 的每条退出路径都必须还原（仓库有 AST 守卫），否则
「同一会话里设备特征跳变」= 会话被接管，比不切更糟。

**直连 API**：`crawler.tls_impersonate` 保持 `chrome`；把它设空只用于排障。
会话过期后继续打 API 会被记成 `soft_reject`，不是「无票」。

**App**：三段硬化顺序固定——身份 → 隐藏 → 调优，全部在 `ensure_ready()` 里、
App 启动之前完成（`android.os.Build` 在 zygote 定型）。之后才是
`prepare_device()`（锁竖屏 → 快照 → 权限框 → 前台校验 → ANR）。

**日历**：逐日循环里单日失败必须只记该日（`note_date`），不许中断整段；
日历接口对未预热会话返回空，不是「当天没票」。

---

## 7. 明确不做（沿用仓库黑名单，只列与本文相关的）

1. 重试风暴——唯一能把「限你」升级成「封你」的动作。
2. 把换 IP / 住宅代理当常态——真 429 只占 0.3%，为它付 100% 成本；国内站配境外出口反而升档。
3. 用自家锁冲突惩罚对方站点。
4. 靠降速解决设备身份命中（设备规则与频率无关）。
5. 把 `ro.product.cpu.abi` 写成 arm64（会让加固 so 崩、ANR）。
6. 改分辨率/DPI 去「更像真机」（坐标全写死，改了全渠道瘫）。
7. 接打码平台 / 自动过验证。
8. 调高并发到 4+ 或 5 家同秒齐发。

---

## 8. 回滚矩阵

| 改动 | 关掉的方式 | 影响面 |
|---|---|---|
| 会话等待 | `crawler.profile_wait_s: 0` | 回到「立刻让位」 |
| 实例调优 | `android.tuning.enabled: false` | App 段回到动画/息屏原状 |
| 对数正态停顿 | 无开关（区间语义不变）；要复现旧行为可临时改 `crawlers/base.py::_sleep` | 仅间隔形状 |
| 地理一致 | 删掉 `crawler.geo` | 回到 zh-CN / Asia/Shanghai |
| 爬取率账本 | 删 `user_data/<profile>/yield_stats.json` 即清零；不影响采集 | 仅报表 |
| 登录退避 | 删 `user_data/<profile>/login_ledger.json` | 连击数归零 |
| 设备身份 | `android.identity.enabled: false`；彻底重置见设备手册 §10 | 不再写任何 props |
