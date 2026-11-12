# 能力与解封手册（2026-11-08）

> 一页说清：**现在每个渠道能不能采、卡在哪、证据是什么、谁才能解开、敲什么命令**。
> 所有结论都来自真机实测，文中数字可在 `data/prices.db`、`user_data/*/yield_stats.json`
> 与 `.superpowers/sdd/.../progress.md` 核对。

---

## 一、现状速览（2026-11-08 实测）

| 渠道 | 订阅 | 今日路径账 | 结论 | 卡点 |
|---|---|---|---|---|
| **fliggy（PC）** | ✅ | `PC ok=383` | **能采** | — |
| **tongcheng（PC/窗历）** | ✅ | `窗历 ok=421`、`PC ok=130` | **能采** | — |
| **tuniu（H5/API）** | ✅ | `H5/API ok=133` | **能采**（PC 不支持，走 H5） | — |
| **app_zhixing** | ✅ | `日历 ok=776`、`航班明细 ok` | **能采**（稳态 11.9s/条） | — |
| **app_qunar** | ✅ | `航班明细 ok=30` | **能采** | — |
| **app_ctrip** | ✅ | `航班明细 ok=23`（历史） | 需登录 | 手机验证码登录；登录常报 **50003** |
| **app_fliggy** | ✅ | 0（`app-block`/`app-form`） | 被阿里滑块拦 | 阿里 NC 轨迹风控 |
| ctrip（PC/H5） | — | `H5 ok=74`、`PC ok=65`（历史） | 需登录 | 站点强制登录（H5 直接跳登录页） |
| qunar（PC/H5） | — | — | **已正式停服** | 数据由 `app_qunar` 承担 |

**一句话**：现在真正卡人的只有两家 —— **携程要登录**、**飞猪被阿里滑块**。其余四家（含
两家 App 真机通路）都在正常出数。

---

## 二、两条卡点的证据与处置

### 1）携程：查询必须登录（不是设备被封）

真机证据链：

1. 设备脸修自洽后（见 §四），**携程 App 首页正常、点「机票」直接进搜索页**
   （单程/往返/多程、上海→北京、11月16日、添加乘机人都在）→ 说明**环境这一关过了**；
2. 一点「查询」就回「手机验证码登录」页 —— 账本 `login: 3`；
3. 浏览器通路：H5 深链返回的 HTML 标题就是 **「携程旅行-登录」**，PC 列表请求 0 包。

→ **只有"登录"能解**。50003 只在真正提交登录时出现，需要账号 + 短信验证码，程序侧无法代做。

#### 50003 的定性（仓库里早有实证，`docs/DEVICE_IDENTITY_PLAYBOOK.md`）

`50003` 的原文是 **「当前登录环境存在风险，已被限制登录」** —— 它属于**登录环节的
环境风控**，不是"账号被封"、也不是"MuMu 的 ID 被拉黑"。档案里记录的真机因果是：

> 换身份后没清 App 内 `utdid` → 服务端看到「**新设备 + 旧设备 ID**」→ 判环境存在风险 → 50003。

以及后续：旧号 50003 → 换新号 → `40006「当前账号行为异常，已被限制注册」`
—— 都指向**环境维度**被拒。

#### 今天（2026-11-08）按档案顺序实做了一遍

正确顺序是：**身份定稿 → `pm clear` 目标 App → 首启过滑块 → 重新登录 → 之后不要再动身份。**

我做完了前两步与验证：

```
身份定稿：Xiaomi 14 / SM8650 / Adreno 750（审计仅剩 1 处矛盾 = x86 ABI）
pm clear ctrip.android.view → Success
首启：通知权限（允许）→ 隐私（同意并继续）→ **直达首页**
      （无阿里 Baxia 滑块、无登录墙 —— 说明环境判定这一关过了）
点「查询」→ 仍回「手机验证码登录」页（账本 login: 5）
登录页本身**没有任何风控提示**，50003 只会出现在"提交登录"之后
```

**所以剩下的确实只有一步**：用你的账号提交登录。设备侧该做的都做完了，
而且现在是在"新设备 + 新 utdid"的**自洽状态**下登录（此前失败是矛盾状态下的失败）。

#### 包名暴露面（比 props 更硬的一条，今天实测）

档案里说这条"此前完全没管"。今天实测这台机器：

```
pm list packages -3  → 只有 5 个目标 App + org.frknkrc44.hma_oss（隐藏工具）
grep magisk|kernelsu|weishu|topjohnwu|xposed|frida|vbox|qemu|genymotion  → 0 命中
仅存 com.nemu.oaidmanager（MuMu 提供 OAID 的服务，档案建议保留：摘了会影响 OAID）
```

**结论：包名这条已经不露了**（Magisk/KernelSU 管理器都没装到 guest 里）。

### 2）飞猪：阿里 NC 滑块（轨迹风控）

真机证据链：

1. 首页正常；点「机票」后出现
   `验证码拦截 / 亲，请拖动下方滑块完成验证 / 向右滑动验证`；
2. 用 `adb input swipe` 单段等速直线滑一次 → 页面回 **`请点我重试(error:x2VW8)`**
   （**轨迹被判机器**，不是位置不对）；
3. 改成变速轨迹（ease-out + y 抖动 + 端点微调）仍不过；
4. 我们用 OCR 在**截图**里能把轨道定位到像素级（y=1707 / x=151..1071，与 UI 树真值一致）
   —— 也就是说"看得见、能试"，但阿里就是不认。

→ 按用户口径（"非常强大的人机识别就没必要了"），**这条路不再硬刚**。
有效手段是让人机挑战消失：清 App 数据 → 登录淘宝账号 → 换出口 IP → 最后换实例。

#### 实测：清数据之后飞猪变成登录墙（2026-11-08 执行）

我按第一档真的执行了 `pm clear com.taobao.trip`，结果值得记住：

```
pm clear com.taobao.trip → Success
首次启动：隐私政策同意框（同意）→ 位置权限（允许）
→ 进入 App 直接是登录页：支付宝登录 / 验证码 / 账号密码
```

也就是说 **清数据不是"独立解"**——它把"阿里滑块"换成了"登录墙"。
完整因果是：`清数据 → 必须登录 → 登录后有一段时间可用（用户观察）→ 再被拦 → 换 IP/再清`。

好消息是采集侧的闭环完整（不用人盯）：
```
耗时 6.1s | 返回 0 条 | last_path=app-login | login_suspect=True
登录墙记忆：路径账记 login：飞猪要求登录（.login.v2.CustomUserLoginActivity）
```
识别 → 记账（带原因）→ 落记忆，**下一轮 0 秒**。对照撞滑块时每轮 58–69 秒。

---

## 三、命令清单（全部可复制执行）

### 采集与诊断

```bash
python main.py                       # 跑采集（网页控制台另开）
python -m core.setup_check --fix     # 环境自检并自动修（依赖/内核/模拟器/定位）
python -m core.android.appversion versions        # 各家 App 版本 + 是否升级
python -m core.android.appversion probe app_zhixing  # 升级后界面还认不认得（锚点命中率）
python -m core.strategy_contract --strict         # 策略控制面自检（当前 y429/n0/na36）
```

### 设备环境自洽审计（**怀疑被风控时先跑这个**）

```bash
python -m core.android.consistency            # 比对 MuMu设定/props/cpuinfo/GPU/ABI，列出矛盾
```

典型输出（本轮修复前后）：

```
修前：6 处矛盾（4 处高风险）
  ro.board.platform mt6897 ≠ MT6991 / ro.hardware 同 / GL_RENDERER Qualcomm Adreno 750
  （天玑 9400 应为 Mali）/ abilist 含 x86 / marketname 空 / soc.manufacturer 空
修后：1 处矛盾（只剩 abilist 含 x86 —— 这条改不了，见 §四）
```

### 换"设备脸"（从便宜到贵）

```bash
# ① 只清某个 App 的本地设备 ID（最轻，不动登录态，可回滚）
python -m core.android.rotate --apply --apps-only --apps app_ctrip

# ② 换设备身份（android_id/build/序列号；下次采集自动重建）
python -m core.android.rotate --apply
python -m core.android.rotate --restore        # 回滚身份

# ③ 身份按 GPU 家族对齐（MuMu 的 GPU 厂商前缀固定 Qualcomm，所以要对齐到骁龙机型）
python -m core.android.align            # 演练：会说切成哪台
python -m core.android.align --apply    # 真写，随后需重生成开机模块 + 重启实例

# ④ 看 / 换 MuMu 底层标识（imei / 品牌 / 机型 / 认证码）
python -m core.android.identity show
python -m core.android.identity rotate --apply     # 需重启实例生效
```

> 换完身份/机型后必须：`python scripts/identity_boot_module.py` → 重启实例
> （`ro.*` 由开机模块在 zygote 之前写，运行时不写——运行期改会废掉 adb）。

### 清 App 数据（解封第一档，破坏性）

```bash
curl -X POST http://127.0.0.1:<port>/api/channel/reset-app \
     -H 'Content-Type: application/json' \
     -d '{"platform":"app_fliggy","confirm":true}'
```

三道闸：渠道存在性 → **仅 App 渠道** → 必须 `confirm: true`。
清完会**同时清登录墙记忆**（否则窗口期内不会重试，看起来像"清了没用"）。
代价：该 App 需重新登录。

### 网页登录（PC/H5 双端固定）

```bash
python main.py --login ctrip          # 弹有头浏览器登录（崩溃时也可用网页按钮）
python main.py --setup-login          # 顺序引导登录所有已启用渠道
```

槽位矩阵（每个端**固定**自己的登录入口，不会再"PC 弹成 H5"）：

| 槽位 | 端 | 登录入口 |
|---|---|---|
| ctrip | PC | passport.ctrip.com/user/login |
| ctrip_h5 | H5 | m.ctrip.com |
| fliggy | PC | www.fliggy.com |
| fliggy_h5 | H5 | market.m.taobao.com/… |
| tongcheng | PC | www.ly.com |
| tongcheng_h5 | H5 | m.ly.com |
| tuniu | PC | flight.tuniu.com |
| tuniu_h5 | H5 | m.tuniu.com/flight |
| qunar | 全端·已停服 | （说明位；数据走 app_qunar） |

---

> **2026-11-09 更新（r1063 T143-T157）**：这一节的**结论仍然成立**
> （App 侧登录在模拟器上解不开），但"到顶"只针对 App 通道本身。同期已经落地
> 的**兜底与替代通路**见文末「本会话新增能力」——远日期价格已能拿到、
> 渠道登录已双端独立、简单滑块已能自动尝试。**不要把本节读成"没救了"。**

## 三点六、App 侧登录已到顶（携程 50003 / 阿里滑块）——证据闭环

用户实测："错误一直都一样，一直都是 50003 和滑块点完就直接堵住"（**App 渠道**）。
这一轮把 App 侧还能查的都查完了：

| 判据 | 实测 | 能否改 |
|---|---|---|
| 设备脸（机型/平台/SoC/GPU/市场名） | **已自洽** | ✅ 已改好 |
| **ABI** `arm64-v8a,…,x86_64,x86` | 含 x86 | ⛔ `abi_canary` 实测：改 arm64 → **携程 SIGSEGV** |
| **电池电压** | `dumpsys` 读 0/3；`sysfs` 读 3300 mV（真机 3700–4400） | ⛔ `dumpsys battery set` 不支持 voltage，`su` 写 sysfs 也无效（内核只读） |
| 传感器 | 8 硬件 + 8 虚拟（真机量级） | ✅ 不是问题点 |
| 出口 IP | 家宽、非机房非代理 | ✅ 不是问题点 |

`python -m core.android.consistency` 现在会同时报这两条**改不掉的**：

```
[high] ro.product.cpu.abilist   现=arm64-v8a,…,x86_64,x86
[mid ] battery.voltage_now      现=0 mV   应=3700–4400 mV
```

**结论**：携程 App 的 50003（「当前登录环境存在风险」）与阿里滑块"点完就堵"，
在这个 MuMu 实例上属于**环境维度已经到顶**——剩下两条铁证改不掉，
换账号也没用（档案里记着：换新号变 `40006 账号行为异常`）。

**所以 App 侧只有两条路**：
1. **换真机 / 物理设备池**（唯一能同时消掉 ABI 与电池两条）；
2. **把这两家的重心挪到浏览器通路**——浏览器指纹走的是我们自己的 stealth
   （UA-CH/WebGL/时区/语言都对齐），**不经过 ABI 与电池检查**。
   实测：飞猪浏览器刚用真查询探针出过 1 条；携程浏览器登录后再探一次即可判定。

## 三点五、出口 IP 定性（换 IP 之前先测，别白折腾）

```bash
python -m core.net_check          # 人读结论
python -m core.net_check --json   # 机读
```

本机实测（2026-11-08）：

```
出口 IP : 58.246.127.206
位置    : China Shanghai Shanghai
运营商  : CNC Group CHINA169 Shanghai Province Network（AS17621 上海联通）
代理标记: False | 数据中心: False | 蜂窝: False
判定    : residential —— 住宅/普通线路，IP 不是主要风险点
```

**结论**：解封阶梯里的"换出口 IP"这档**可以从清单上划掉**——
阿里系与携程都按 IP 段聚类，机房/代理 IP 才会显著加严，而当前是家宽。
真要换，也应在"账号+设备都验证过仍被拒"之后再考虑。

## 四、模拟器能过什么、什么必须真机

### 已经过掉的（靠"设备脸自洽"）

这台机器原来有 **6 处自相矛盾**（同机型两个芯片代号、GPU 与 SoC 不同家、
市场名为空、ABI 含 x86…）。修到 1 处后：

* **携程 App 从"强制登录墙"变成"可匿名浏览到搜索页"** —— 同一台机、同一个 IP，
  只是把矛盾修掉。这直接证明：**不是 ID 被封，是环境不自洽**。

### 过不掉的（模拟器硬伤）

| 项 | 现状 | 为什么改不了 |
|---|---|---|
| `ro.product.cpu.abilist` 含 `x86_64,x86` | 唯一剩余矛盾 | `abi_canary` 实测：改成 arm64 会让**携程 SIGSEGV**（加固 so 与 ABI 绑定） |
| GPU 厂商前缀 | 只能是 `Qualcomm` | MuMu 的 `gpu_model.custom` 只改型号串；强行填 Mali 会得到 `Qualcomm, Immortalis-G925`（高通不出 Mali，反而更假） |
| 阿里 NC 轨迹风控 | 滑块过不去 | 需要真实触摸/传感器数据，模拟器给不出可信轨迹 |

**结论**：模拟器足以过**大部分**风控（我们已经用它跑通 5 家渠道出数）；
只有"专盯 ABI/触摸真实性"的那一层过不去。**要彻底过那一层，才需要真机或物理设备池。**

---

## 五、速度账（同一条链路的演进）

| 阶段 | 智行单条耗时 | 关键改动 |
|---|---|---|
| 起点 | **100.3s** | — |
| 分段计时 + 收尾快路径 | 42.5s | `PhaseTimer`；一次 BACK 回首页（8–10s→5.5s） |
| **UI 取树提速** | **18.6s** | 优先 uiautomator2 并复用连接：单次 dump **2.1–3.1s → 0.07s** |
| **稳态（热进程）** | **11.9s** | `ensure_ready` 成功缓存 60s（运行时 2.3s → 0.0s） |

> 提醒：`前置·登录态` 那 7 秒是"停 App → 重启 → 等首屏"，**一个进程只做一次**。
> 用"每次新进程跑一条"的方式测会把它算进单次成本，容易误。

---

## 六、可配置开关（都在面板/配置里）

| 开关 | 位置 | 作用 |
|---|---|---|
| `android.ready_cache_s` | config | `ensure_ready` 成功缓存秒数（默认 60，0=不缓存） |
| `android.service_probe_s` | config | 停服记忆窗口（默认 6h，到期自动重探） |
| `android.login_probe_s` | config | 登录墙记忆窗口（默认 2h） |
| 31 条策略 × 15 轴 | 策略面板 | 全部可在页面改，`--strict` 自检 0 缺陷 |
| 通路维度（PC/H5/日历/窗历/API…） | 策略面板行 | 每条通路独立成功率与降频 |

---

## 七、下次遇到"又被拦了"的排查顺序

1. `python -m core.android.consistency` —— 先看设备脸有没有被改花（6→1 是基线）；
2. 看账本：`user_data/<渠道>/yield_stats.json` 的 `paths[*].why`
   （面板上把鼠标停在节流行也能看到同一句话）；
3. 分流处置：`login` → 去登录；`blocked/captcha` → 清数据/换 IP；`unsupported` → 能力边界；
4. 只有"矛盾修完 + 登录做完"仍不通，才考虑换设备身份或重建实例。

### 登录相关的两个开关（r1063 T134）

| 配置 | 默认 | 作用 |
|---|---|---|
| `web.login_reprobe` | `true` | 登录成功后**立刻在后台复探**同厂商的通路（浏览器 + App），不用等下一轮调度；置 `false` 关闭 |
| `android.app_gone_s` | `7200` | App **自行退出**（风控自杀）后的熔断窗口（秒），窗口内该渠道直接跳过并记「App 风控」 |
| `web.login_split_profiles` | `true` | 双端登录各用独立 profile；置 `false` 退回旧的「一份 profile」行为（r1063 T143） |
| `ctrip_week_calendar` / `fliggy_week_calendar` / `tuniu_week_calendar` | `false` | 跨日期低价条兜底（记 `PC·周历`，票面价未拆税）；代码默认关，本项目 config.yaml 已打开（r1063 T154） |

排查顺序建议：面板「降级」行看是哪一类 → python -m core.channel_matrix 看每家每条通路
→ POST /api/channel/clear-wall 立刻重试 → 仍不通则 POST /api/channel/probe 取真实原因。

### 双端登录（r1063 T143/T144，2026-11-08 起）

**所有渠道统一 PC + H5 各一格、各端独立 profile**（与飞猪同款，消除歧义）：

| 槽位 | profile 目录 | 登录入口 |
|---|---|---|
| `ctrip` / `ctrip_h5` | `user_data/ctrip` / `user_data/ctrip_h5` | passport.ctrip.com / m.ctrip.com |
| `fliggy` / `fliggy_h5` | `user_data/fliggy` / `user_data/fliggy_h5` | www.fliggy.com / market.m.taobao.com |
| `tongcheng` / `tongcheng_h5` | 同命名规则 | www.ly.com / m.ly.com |
| `tuniu` / `tuniu_h5` | 同命名规则 | passport.tuniu.com / m.tuniu.com |

* 首次切换时会把厂商 PC profile 的会话**自动继承**到 H5 profile（不丢已登录态）；
* 采集侧：H5 通路用 `using_surface("h5")` 主动切到 H5 profile；
* 想退回"一份 profile"旧行为：`web.login_split_profiles: false`；
* 命令行自查：`python -m core.channel_matrix --login`（含 profile 列）。

---

## 本会话新增能力（r1063 T143-T157，2026-11-09）

这些是**新长出来的手脚**，与"App 侧登录到顶"并不矛盾——它们的价值正是
"App 通道解不开时，别在它身上吊死"。

| 能力 | 命令 / 接口 | 作用 |
|---|---|---|
| 双端登录各端独立 profile | `channel_matrix --login` | PC/H5 各一格、各自 `user_data/<槽位>`，登录一次清同厂商全部墙 |
| 登录即自动复探 | 自动（`web.login_reprobe`） | 登完立刻后台验一次，不用等下一轮调度 |
| 一键清墙 | `POST /api/channel/clear-wall` | 换 IP/重启实例后立刻重试，非破坏性 |
| App 自杀/连败熔断 | 自动（`app_gone` / `app_stall`） | 省下每轮 80–150 秒白等设备时间 |
| 途牛国际 PC 通路 | 自动（`PC·国际`） | 绕开 H5 接口的 710114 登录门，实测出数 |
| 跨日期低价条兜底 | `PC·周历`（配置开关） | "列表空≠没价"：列表无航班时仍能拿到当日最低价 |
| 渠道 × 通路矩阵 | `channel_matrix` | 每家每条通路状态/成功率/最后原因 |
| 每小时产出趋势 | `channel_matrix --trend` | 改完到底有没有变好，一眼可验 |
| 按日期覆盖 | `channel_matrix --dates` | 哪个日期没拿到价、是列表类还是日历类（`*`=票面价） |
| 验证战果 | `channel_matrix --slider` | 滑块/算数/文字类尝试次数、连败、冷却、分类成功率 |
| 该登哪一格 | `channel_matrix --login` | 端、状态、登录入口、是否要登录 |
| 一键引导 | `python -m core.bootstrap` | 装依赖/内核/配置/目录一条命令（`--start` 顺带起服务） |

**简单滑块/算数/文字类验证**：`crawlers/slider.py` 已实现缺口识别（含
`ddddocr`）、拟人轨迹、每日上限与"连败 2 次拉黑 7 天"；战果用
`channel_matrix --slider` 查。**强人机验证（阿里 NC 等）仍不硬刚**——
这是用户明确要求的边界，不是能力缺失。

### 夜间静默窗是**运营决定**（2026-11-09 用户拍板）

`01:00–07:00` 期间**采集与推送一起停**（`quiet_window`）。这是用户明确选择的
取舍：**宁可少 6 小时覆盖，也不要深夜请求量与打扰**。

* 代码位置：`main.py` 每轮入口 `if not force and pac.quiet_now(): 跳过本轮`；
  开关 `quiet_window.enabled`（策略面板可关，关掉后整条链路（含调度重排）
  自动不再静默——判据只有一处）；
* **不要"优化"成"夜里继续采、只静默推送"**：那是另一个取舍，
  2026-11-09 已问过用户，答复是**保持现状**。要改先问，别替用户决定；
* 面板/命令行看到「当前在夜间静默窗」不代表故障；`立即扫描`（force）是唯一的
  夜间手动补采入口。

### 简单滑块的自动解：**端到端已验证通过**（2026-11-09）

以前只有"代码里有这条链路"，没有一次跑通的证据。本轮用**合成滑块页**做回归载体
（`tests/test_r1063_slider_solver_e2e.py`），实测：

```
① 分级：Tier simple 0.90        ← classify 认出是简单拼图滑块
② find_gap → 224（造图缺口左缘 200，中心口径，容差内）
③ attempt_page → True
④ 合成页判定：通过（手柄落在缺口上）
日志：[demo] 简单滑块已通过（偏移 224px）
```

链路：`classify → find_gap（numpy 边缘 + ddddocr 双算法）→ trajectory 拟人轨迹
→ apply_trajectory 拖拽 → _slider_gone 复核`，一步不落。

**不碰真实渠道**：失败两次会被拉黑 7 天，这种实验不拿生产渠道做。

前提：`ddddocr` 已装（`python -m core.setup_check` 有「识别后端」一行，
`core.bootstrap` 会自动装）。强人机验证（阿里 NC 等）仍然只记证据、不硬刚。

### App 日历：**整窗收割**（2026-11-09 真机验证）

`app_zhixing` 的「选择日期」弹层一次会渲染 **61–70 格、其中 53–63 格带价**，
而旧实现只保留我们**订阅的那几天**，其余原位丢弃。

开启整窗收割后（`crawler.app_calendar_harvest_all`，默认 True；
`app_calendar_harvest_cap` 默认 62 格/次）：

```
16:09:37  app_zhixing  日历 calendar  rows=62
          「长窗口日历 62 天 / 已渲染 70 格（有价 63）· 另含 62 格非订阅日期」
16:09:36  flight_prices 写入 2026-11-22 … 2027-01-22 共 62 个不同日期
```

今日各平台的**日期覆盖**对比（这比行数更能说明问题）：

| 平台 | 行数 | 日期数 |
|---|---|---|
| **app_zhixing** | 71 | **63** |
| tongcheng / fliggy / ctrip / tuniu / app_qunar | 58–151 | 4 |

浏览器渠道每家只覆盖**配置的 4 个日期**；智行一次抓取覆盖 **62 个连续日期**，
而**请求数与风控暴露完全不变**（同一屏已经渲染好的数据）。

配套：App 日期视野**可配置**（`crawler.app_date_horizon_days` 与
`crawler.app_date_horizon_days_map.{plat}`，默认仍 62 天保持既有行为）。
62 天是 2026-11-05 的实测结论，但 2026-11-09 用户截图显示智行/携程能显示更远，
因此把它变成"实测可调"的参数，而不是写死在代码里。

边界：日历价 = 每天最低价、无航班号，`detail` 里如实标注
"另含 N 格非订阅日期（日历价，非明细）"。
