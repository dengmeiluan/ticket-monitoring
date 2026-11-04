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

## 3.5 统一策略层：四本账只能有一个出口

散着判一定会打架。举个真实会发生的组合：熔断器说「停 40 分钟」，产量账说
「下界 0.95、可以 0.8× 加速」，登录账说「还能再试」——三个都对，合起来是错的，
而且谁赢取决于调用顺序。

`core/policy.py` 把这些收敂成**每渠道一个决定**，浏览器与 App 渠道读**同一个
引擎**（不是各写一份）：

| 字段 | 含义 |
|---|---|
| `state` | `healthy` / `rehab` / `watch` / `degraded` / `blocked` |
| `allow` | 本轮允不允许发请求 |
| `pace_factor` | 间隔倍率（0.8×–3.0×） |
| `need_warmup` | 下次是否必须先预热（会话没养熟别打深链） |
| `rotate` | 是否建议换设备身份（**只建议**） |

**分工是刻意的，也是本节最重要的一条**：

- **短时冷却归 `ChannelBreaker`**——它拿得到服务端 `Retry-After`，按真实配额退避；
- **长期姿态归策略层**——要不要停一整段、要不要换身份、倍率给多少；
- 两层都去拦会过度降温，产量白掉。所以策略层只在 `human`/`rotate` 档关闸，
  `pause` 档只把速度压到 3.0×。

**不会关闸的三件事**（关了就丢证据，比多打几次更危险）：

1. 登录退避（登录墙必须如实记 `login` 并继续跑，由人过完再采）；
2. 产量差（真无票、真冷门航线都会让成功率掉，与风控无关）；
3. 抢不到自家锁（那是自家冲突，不是渠道失败）。

**余温与恢复期**：一轮滑块的证据不会下一轮就忘——`watch` 留 30 分钟、
`degraded` 留 60 分钟（**沿用原到期时间，不续期**，否则每次查询都把窗口往后推，
等于永久降速）；`blocked` 到期后先进 `rehab`（1.5× + 强制预热），成功一次转正。

```
crawler:
  policy_gate: true      # 总开关；关掉=回到各部件各自判断，账本照记
```

状态落 `user_data/<profile>/policy_state.json`，删掉即「全部从头开始」。
`yield_report.py` 会把最终决定直接打在表里：

```
渠道        样本  成功   下界  间隔建议   倍率  状态
ctrip         12    11   0.62       30   1.5x  watch
tunari        40    38   0.83       45   1.0x  healthy
```

---

## 3.6 验证：先分级，再决定要不要动手

边界按**「题目是否机器可判」**划，不是按"能不能硬算"：

| 类别 | 判定输入 | 能不能自动化 | 本仓库的做法 |
|---|---|---|---|
| **简易算数** `3+7=?` | 题面是**结构化文本**，答案唯一可验算 | 能，且最可靠 | 纯文本解析（**不依赖 OCR**） |
| **简易文字** `请输入图中字符` | 单行印刷体，无扭曲、无轨迹采集 | 能 | 系统 OCR + cv2 预处理 |
| **几何滑块** | 判定落在**几何**上（缺口位置） | 能 | 边缘成对找缺口 + 拟人轨迹 |
| **点选** `按顺序点击图中文字` | 要理解**图像语义** | 不做 | 识别成 `click` 即停手 |
| **强人机**（极验 v4/天御/baxia/reCAPTCHA/人脸） | **你的行为分布**本身 | 越算越像机器 | 识别成 `strong` 即停手 |

判型函数 `captcha.classify_kind()` 全用字符串证据，不做"看起来像"的猜测；
同时命中多类时按**安全侧**排序：`click` → `strong` → `arithmetic` → `text` → `slider`。

### 3.6.1 算数题：不用 OCR，纯文本解析

这是"简易通用验证"里回报最高的一类——题面就在 DOM / UI 文本里，不需要看图：

```python
captcha.solve_arithmetic("3 + 7 = ?")     # 10
captcha.solve_arithmetic("计算：12*4=")     # 48
captcha.solve_arithmetic("三加七")          # 10   （中文数字/运算符）
```

两个刻意的处理（都是踩过的）：

1. **只看 `=` 左边**：OCR 常把题面的 `?` 认成 `0`，`3+7=?` 读成 `3+7=0`；
   若从整串找二元式就会把 `7=0` 甚至 `=0` 当算式 → 截断到第一个 `=` 之前；
2. **三元式不猜**：`1+2+3` 返回 `None`。简易验证码没有三元题，猜错比不答更糟。

求值**自己算四则，不用 `eval`**，所以不存在代码注入。

### 3.6.2 文字题：系统 OCR + cv2 预处理（零新依赖）

依赖策略：**不引入新依赖**。环境里已有 OpenCV 4.12 + numpy + PIL，加上项目
自带的 `core.android.ocr`（Windows.Media.Ocr）——"cv2 预处理 + 系统 OCR"
就是验证码识别最经典且零成本的一档。

```python
captcha.read_text(png)              # 原图与预处理图各读一次，取更长的
captcha.clean_answer("验证码：X7K9")  # 'X7K9'
```

**为什么必须"双读取更长"**（实测数据）：

| 图片 | 只读原图 | 只读预处理 | 取更长 |
|---|---|---|---|
| `AB12`（44px 粗体） | ✅ `AB12` | ❌ 空（二值化抹掉了细笔画） | ✅ |
| `X7K9` | ✅ | ✅ | ✅ |
| `3 + 7 = ?`（小字号） | ⚠️ 部分 | ✅ 读全 | ✅ |

所以预处理只做**低损伤**的两步：放大（INTER_CUBIC，保住笔画过渡）+ Otsu
二值化，**不做中值滤波**（滤波会把细笔画抹掉）。

**不装** `pytesseract` / `easyocr` / `ddddocr` 作为**硬依赖**：前者要额外装
Tesseract 二进制，后两个要拖 onnxruntime/torch 级依赖，会让打包体积涨几十 MB。

但**可选后端已经接好**（你说"Python 应该有很多现成的解码开源框架吧，可以试试"）：

```python
captcha.backend_name()      # 'ddddocr' / 'windows-ocr' / 'none'
captcha._read_with_ddddocr  # 装了 ddddocr 才用，没装返回空串
captcha.slide_match(png)    # ddddocr 的滑轨模型，给 find_gap 做可选增强
```

`read_text` 的选择逻辑：**谁读出的字符多就用谁**。ddddocr 对付字符验证码
通常明显强于系统 OCR；系统 OCR 对"无扭曲印刷体"更稳。两者互补。

装法（可选，不装也完全能用）：

```powershell
python -m pip install ddddocr     # 会带 onnxruntime，约 50–80MB
```

没装时 `backend_name()` 是 `windows-ocr`，行为与现在完全一致——
**这层是纯增量，零风险**。

### 3.6.3 开关与共账

```yaml
crawler:
  slider:
    auto: simple        # 滑块（"off" 则整条自动化都不挂）
    daily_cap: 3
    max_fails: 2
  captcha:
    arithmetic: true    # 算数题
    text: true          # 文字题（OCR）
    ocr_scale: 3.0      # OCR 前放大倍数
```

**预算与拉黑与滑块共用同一本账**（`slider_ledger.json`）。不同类别各记一套
会让"失败 2 次拉黑"互相抵消——比如滑块失败 2 次本该停手，算数又从头计数，
结果是永不停手。

生效方式与滑块一致：`BaseCrawler.__init__` → `challenge.ensure_slider_handler()`
→ 挂 `captcha.SolverHandler`（超集，覆盖三类；挂不上才退回 `SliderHandler`）。

要在采集里真正生效，处理器必须**被注册**——现在这一步是自动的：
`BaseCrawler.__init__` 会调 `challenge.ensure_slider_handler()`，按
`crawler.slider.auto` 决定挂不挂（幂等、失败静默），所以不用改 main/webui。

> **踩过的坑**：`SliderHandler` 写好、配置也有了、UI 也有配置项，但
> **全仓没有一处生产代码调用 `register_handler`**（2026-11-03 搜过，只有
> challenge.py 的定义、slider.py 的文档、测试里的调用）。也就是功能是**死的**：
> 配置改了、界面勾了，跑起来一次都不会触发。这类"配了但没接线"的坑最难发现，
> 因为所有单元测试都是绿的。现在由 `ensure_slider_handler()` 兜住，并加了
> `tests/test_r923_slider_registration.py` 钉死开关语义与幂等性。

命中率怎么看（`yield_report.py` 的「滑块」列）：

```
渠道        样本  成功   下界  间隔建议   倍率  状态      滑块
ctrip         12    11   0.62       30   1.5x  watch     试 5 / 过 3（命中 60%）
```

账本落 `user_data/<profile>/slider_ledger.json`（`tries`/`fails`/`day_used`/
`blocked_until`）。**连续失败 2 次会拉黑 7 天**，所以命中率低时它会自己停手。

工程细节（这几条决定它是不是真能用）：

- **缺口检测**是纯图像的：灰度列差分 → 找"两条强竖直边 + 中间无纹理"的成对峰。
  不按单条边打分（实测会被背景纹理和滑块起始方块骗走），也不做模板匹配
  （各家缺口形状不同，模板要一家一份）。精度差几像素，靠"顺次试前 3 个候选"兜。
- **轨迹**三条性质：加速—巡航—减速（smoothstep）、中途一次成对回拉（净位移 0）、
  落点成对微调 + 松手前停留。终点**精确等于**目标距离（先算位置再算增量，
  避免逐段抖动累积漂移）。
- **预算与拉黑**落 `user_data/<profile>/slider_ledger.json`：连续失败 2 次停 7 天。
  理由很直接——滑块失败本身会被计入行为样本，硬试只会把渠道打成更高风险分。
- 不接任何第三方打码服务（那等于把账号交给陌生人）。

---

## 3.7 分辨率 / DPI 与 ABI：先能验证，再谈伪装

### 分辨率：默认走「身份对齐」，零风险

设备是 900×1600 / 320dpi，而身份池里那台 Redmi K50 声明 1080×2400 / 440dpi——
风控读一次 `DisplayMetrics` 就能看出「机型与屏幕不符」，这比不伪装更可疑。

```yaml
android:
  identity:
    align_display: true    # 默认开：把身份档案的 display/density 改成设备真实值
```

这条**只改身份档案、不动任何设备设置**，所以坐标一个字都不用改。做完之后
`display.audit()` 应该 `ok: true`。

真要**改屏幕**（`wm size` / `wm density`）也能做，但必须配坐标换算——用现成的
安全入口，别手改：

```powershell
python scripts\display_spoof.py                 # 看现状（只读，含"是否空闲"提示）
python scripts\display_spoof.py --scale 1.2     # 改到 1080x1920，density 同比 288
python scripts\display_spoof.py --restore       # 回滚到出厂
```

脚本强制三件事（缺一个都会让 App 渠道静默瘫掉）：

1. **改完立刻 `dev.set_design(900, 1600)`** —— 写死的常量仍指向正确位置；
2. **改完立刻 dump 一次**，确认「界面还在、不是白屏」，否则**自动回滚**；
3. `--restore` 一条命令回到 `wm size/density reset`。

原理与边界：

- `density` 与 `size` **同比例**变化时 dp 尺寸不变（界面布局不乱，只是更细）；
- `AdbDevice` 的 `tap/swipe` 会把设计坐标换算成设备坐标，`to_design()` 做反向；
- UI 树 `bounds` 读出来的是**设备坐标**，参与常量比较前要走 `to_design()`；
- `design` 默认 `None` = 完全不换算（现状逐字不变），所以这条开关不会误伤；
- `hardening` 每次会做**坐标基准体检**：设备分辨率 ≠ 900×1600 时明确告警
  「必须 set_design」，因为这种错在账本上只表现为「设城市失败」，很难追。

#### 实机验证（2026-11-03，MuMu / Android 15）

| 阶段 | 实测 |
|---|---|
| 改屏幕 | `1080×1920 @288`（override=True） |
| 界面检查 | 162 个节点，非白屏 |
| 换算 | `to_device(450,800)=(540,960)`，scale=**1.200** |
| **真实点击** | 设计 `(450,300)` → 设备 `(540,360)` → 携程**跳转新 Activity**（`CtripHomeActivity` → `AirportCarPlantHomeActivity`）✅ |
| 回滚 | `900×1600 @240`，override=False，scale 恢复 1.0 ✅ |

**顺带修掉一个会静默毁掉全部坐标的 bug**：`AdbDevice.window_size()` 原来用
`re.search(r"(\d+)x(\d+)")` 取**第一个**匹配 —— 而 `wm size` 的输出现有两行：

```
Physical size: 900x1600
Override size: 1080x1920
```

于是屏幕被改过之后，`window_size()` 永远返回**物理**尺寸 → `scale` 恒等于
1.0 → 写死的坐标按原值发出去 → 点击全偏，而账本上只表现成「设城市失败 /
页面认不出」，极难追。

现在改为**优先取 `Override size`**，读不到才退回 `Physical size`。

### ABI：写 arm64 能不能行，要看能不能验证——装置已经给你了

**结论先说**：技术上可以改（`resetprop` 写 `ro.product.cpu.abi/abilist*`），
但**不能盲改**。MuMu 是 `x86_64 + ARM 转译`，改完之后 PackageManager 会按 arm64
选 native so，加固 so（携程、去哪儿都带）可能走进转译层不支持的指令——仓库里
已经吃过一次：主线程 Blocked 在 `Runtime.load0`，ANR 120s+，点「等待」186s 也不恢复。

所以 `core/android/abi_canary.py` 提供的是**可行性实验装置**：

```
snapshot(原值) → apply(arm64) → 重启框架 → probe(包名) → 恢复原值 → 重启框架 → 落盘判定
```

- `probe` 判据是**三件事同时成立**：前台回到目标包、UI 树 ≥6 节点、logcat 无
  `UnsatisfiedLinkError / FATAL EXCEPTION / SIGSEGV / SIGILL / ANR in`；
- `try/finally` 保证**无论成功、失败还是抛异常都会恢复**（测试里专门钉了这条）；
- 恢复用的是**探测到的原值**，不是硬编码 x86（万一设备本来就在 arm 上）；
- 判定落 `user_data/device/abi_canary.json`，**7 天有效**（App 升级会换 so，
  昨天的结论不作数）。

跑一次：

```powershell
python -c "from core.android import abi_canary, device; \
  d=device.AdbDevice(r'D:\Program Files\Netease\MuMu\nx_main\adb.exe','127.0.0.1:16384'); \
  print(abi_canary.run(d,'ctrip.android.view',{},print,restart_wait_s=60)['ok'])"
```

判定 ok 之后才允许长期启用：

```yaml
android:
  identity:
    spoof_abi: auto     # auto=必须有 ok 判定；true=无条件写（不推荐）；null/false=不动
```

判定 ok 之后才允许长期启用：

```yaml
android:
  identity:
    spoof_abi: auto     # auto=必须有 ok 判定；true=无条件写（不推荐）；null/false=不动
```

`auto` 的语义是「**只有这台实例 + 这个包被验证过，才写 ABI**」——比"文档说可以"
可靠得多，也是这条唯一负责的做法。

#### ✅ 实测结论（2026-11-03）：ABI 伪装**已跑通**，走的是 MuMu 官方 per-app 表

前一轮的结论是"三条路全堵"，这一轮继续挖，找到了 MuMu 官方的机制并**实证成功**。

**关键发现**：`/system/etc/mumu-configs/abi-select-android12.config` 是
MuMu 的「**包名正则 → ABI**」映射表，决定**每个 App 用哪套 ABI 启动**。

```
ctrip\.android\.view      arm64-v8a      # 携程
com\.taobao\.trip         arm64-v8a      # 飞猪
com\.Qunar                arm64-v8a      # 去哪儿
com\.tongcheng\.android   arm64-v8a      # 同程
cn\.suanya\.zhixing       arm64-v8a      # 智行
```

**验证结果（重启实例后）**：

| 项 | 实测 |
|---|---|
| 5 个包 `primaryCpuAbi` | 全部 **arm64-v8a** ✅ |
| 全局 `ro.product.cpu.abi` | 仍 **x86_64**（系统稳定，不受影响）✅ |
| 携程启动 | `CtripHomeActivity` 正常在前台 ✅ |
| logcat | 无 `UnsatisfiedLinkError` / `FATAL` / `SIGSEGV` ✅ |
| 采集 | 正常运行（tuniu 国际 92 条明细、app_qunar 继续）✅ |

**为什么这条路对、全局改 prop 不对**：

* App 视角是 arm64（风控读 `ApplicationInfo.primaryCpuAbi` 时看到的就是这个）；
* 系统仍跑 x86，ARM 转译层照常工作，稳定性不受影响；
* **只影响我们关心的 5 个包**，不碰系统其余部分；
* 历史那次 `Runtime.load0` ANR 的前提（x86 装 arm64 so）在这里不成立——
  这些包**本来就是 arm64 包**（实测 `primaryCpuAbi` 一直是 arm64-v8a）。

**顺带确认**：直接改 `/system/build.prop` 的 `ro.product.cpu.abi` **无效**——
即便系统盘已可写、文件确实改成了 `arm64-v8a`，重启后运行时 `getprop` 仍
`x86_64`（MuMu 的启动流程会用 `mumu-configs` 覆盖）。所以**别走 build.prop**。

对应实现 `core/android/vendor.py`：

```python
from core.android import vendor
vendor.read_abi_select(dev)        # 看现状：{pkg: abi}
vendor.set_app_abi(dev)            # 幂等写入 5 个票务包（自动备份原表）
vendor.revert_app_abi(dev)         # 从备份还原
```

前置条件只有一条：`system_disk_readonly=false`（已设）。

>`read_abi_select` 的坑：表里**第一列本身就是带 `\.` 转义的正则**，
> 用裸包名去匹配必然失败——实现里两边都去转义后再比。

#### 实测结论（2026-11-03，MuMu 实例 0 / Android 15）

先跑只读预检，结果如下：

| 项 | 实测值 | 含义 |
|---|---|---|
| `ro.product.cpu.abi` | `x86_64` | 这就是风控读的 `Build.CPU_ABI` |
| `abilist64` | `x86_64,arm64-v8a` | 系统**有** arm64 运行时 |
| `ro.dalvik.vm.native.bridge` | `libnb.so` | MuMu 自带 ARM 转译 |
| 5 个目标包 `primaryCpuAbi` | 全部 `arm64-v8a` | **它们本来就是 arm64 包** |
| `resetprop` | 无（未装 Magisk） | ro.* 改不了 |
| `setprop ro.*` | 返回 0 但**值不变** | 静默失败（最坑） |
| `mount -o remount,rw /` | `'/dev/block/sda6' is read-only` | 块设备只读，`touch` 失败 |

**当时的临时结论是"三条写入通道全堵、不可行"** —— 后来证明这个结论**只对
`ro.*` 全局改写成立**，而 ABI 伪装根本不需要走那条路：MuMu 有官方的
**per-app ABI 表**（见下一节，已实测跑通）。
（顺带纠正一个此前的担忧：因为目标包本来就是 arm64，改 ABI 选择
**不会**让它们去加载不存在的 so，历史那次 `Runtime.load0` ANR 的前提在此
配置下不成立。）

> 下面这段"装 Magisk"的路径**保留作参考**——它的价值是让 `ro.*` 全局可写
> （比如还想改 `ro.build.tags` 之类）。但**ABI 伪装不需要它**。

```powershell
python scripts/abi_preflight.py            # 应变成 risk=low
python scripts/abi_preflight.py --canary   # 真跑，自动回滚 + 落判定
```

`abi_canary.capabilities()` 会把上面三条通道各探一次并写进报告，所以下次不用
再手工试一遍——它会直接告诉你"是机器不支持"还是"包的 so 不匹配"。

#### 2026-11-03 追加：找到 ABI 的真正开关了（MuMu 官方键）

用 `MuMuManager.exe setting -v 0 --all` 枚举出 MuMu 的官方设置，其中一条是
**`system_disk_readonly: true`** —— 它就是"系统盘只读挂给虚拟机"的开关，
也是 `setprop`/`blockdev`/`remount` 全部静默无效的**最深层根因**。

```
MuMuManager.exe setting -v 0 -k system_disk_readonly -val false   # 已执行，读回 false
```

但它要**重启实例**才生效。所以 ABI 的推进路径变成：

```powershell
# 1) 等采集空窗（日志出现"本轮扫描结束"，或 01:00–07:00 静默窗）
# 2) 关系统盘只读（幂等，已设过也行）
& "D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe" setting -v 0 -k system_disk_readonly -val false
# 3) 重启实例（会中断采集，所以必须挑空窗）
& "D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe" control -v 0 restart
# 4) 重跑预检：能力闸应变成可写
python scripts\abi_preflight.py
# 5) 通过后跑 canary 实测（自动回滚），判定 ok 才填 auto
python scripts\abi_preflight.py --canary
```

**顺带发现更重要的一件事**：MuMu 还提供**官方的机型与屏幕接口**——

| 官方键 | 实测值 | 对应 Android prop |
|---|---|---|
| `phone_brand` | Samsung | `ro.product.brand` |
| `phone_model` | Galaxy A52 5G | `ro.product.model` |
| `phone_miit` | SM-A5260 | `ro.product.model`（实际值） |
| `phone_imei` | 865247046277134 | `gsm` 侧 |
| `resolution_width/height` | 1600 / 900 | `DisplayMetrics` |
| `resolution_dpi` | 240 | `densityDpi` |

**这比改 props 好得多**：不需要 root、不需要 Magisk、可持久化、写失败会报错
（而不是静默无效）。所以本项目的分层原则定为：

> **能让 MuMu 官方做的，就别去改 props。**
> props 那条路（`fingerprint`）只补官方不提供的部分（序列号、android_id、gsm）。

对应实现 `core/android/vendor.py`，白名单只放设备外观与系统盘开关
（性能/网络键一律拒写——改错会让采集变慢或断网），写后**读回校验**，
需要重启的键标 `restart_required` 并**不替你重启**：

```yaml
android:
  vendor:
    apply: false          # 默认只读；写配置要重启实例，属于操作员的决定
    # brand: Samsung
    # model: Galaxy A52 5G
    # miit: SM-A5260
    # width: 900
    # height: 1600
    # dpi: 240
    # unlock_system_disk: false
```

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

### 6.1 单日隔离（2026-11-03 落地）

App 渠道的日期循环原本是「一抛异常整个 `fetch` 结束」：

```python
for date in dates:
    got = self._one_date(dev, ..., date)   # ← 第 2 天设备抖一下，第 3/4/5 天全丢
    if got: out.append(got)
```

账本上表现为**整条航线 timeout**，而实际可能只有 1 天有问题——这是纯粹的
产量损失，与风控无关。现在统一走 `AppCrawler.date_guard()`：

```python
got = self.date_guard(date, self._one_date, dev, fc, tc, date)
```

- 异常只死这一天，其余日期照常出数；
- 该日记 `timeout` 并写明异常类型，**绝不记 `empty`**（账本红线）；
- 返回元组的渠道（智行 `(rows, blocked)`）用 `_default=([], None)` 保持契约。

已接入：携程、同程、飞猪、智行。**去哪儿原本就有**（内部 try/except + 记账），
没有重复改。

### 6.2 预热时序：等 cookie，不等秒数（2026-11-03 落地）

日历/深链的价值不在「停留了几秒」，而在「服务端把会话 cookie 发下来了」。
固定 `wait_for_timeout(4000)` 有两种失败模式：cookie 还没下来就去打 → 被当
新会话 → 444/202 软拒；cookie 早下来了却还在等 → 白等。

`BaseCrawler.wait_risk_cookies(ctx, timeout_s=12)` 改成**轮询命中即返回**：

- 命中 → 立刻继续（比固定等待更快）；
- 超时未命中 → 返回空，并由调用方记「预热未生效」。

携程国际日历已接入，并把记账口径接上：预热没落下 cookie 且无价时记
`soft_reject`，**不是** `empty`——"会话没养熟"不能写成"没有航班"。

---

## 6.3 一次真实事故复盘：调度自锁停摆 10 小时（2026-11-04）

这是到目前为止**最大的单次产量损失**，而且与风控无关——值得整节写下来。

真实日志：

```
23:30:16  [app_qunar] 开始抓取 SHA->BKK
23:45:07  [并发] qunar 路由级超时(900s)，按断供记健康时间线
23:45:07  [并发] app_qunar 路由级超时(900s)
00:00:07  apscheduler … skipped: maximum number of running instances reached (1)
…         此后每 30 分钟都 skipped，连续 10 小时一条数都没采到
```

机制（两层叠加）：

1. `_collect_route_futures()` 超时只是「**不再等** future」，`ThreadPoolExecutor`
   的 worker **不可取消**——它仍在跑，并继续占着模块级 `_DEVICE_LOCK`；
2. 之后每轮每个 App 渠道都要白等 `device_lock(timeout=600)` 才放弃，
   6 个渠道 × 600s 远超 30 分钟间隔 → apscheduler 的 `max_instances=1` 永久积压。

**最要命的是查不动**：日志里只有「路由级超时」和「skipped」，
**看不出是谁占着锁**。所以这次修复的重点不是"防死锁"（超时本来就有），
而是**让占用可观测**：

```python
with rt.device_lock(owner=self.name):    # 9 处 App 渠道全部带 owner
    ...
rt.lock_state()        # {'owner': 'app_qunar', 'since': ...}
```

现在等不到锁时会直接打：

```
[android] 设备锁等待 600s 超时；当前持有者=app_qunar（已持有 3000s）
```

单次持有超过 2 分钟也会留痕（正常 App 一轮采集在 60s 内）：

```
[android] 设备锁被 app_qunar 持有 187s（偏长，留意是否卡住）
```

**排查顺序**（下次同样现象直接照这个走）：

1. `grep "设备锁" logs/monitor.log` → 看是谁占着、多久；
2. 该渠道在跑什么 → 上一轮的「开始抓取 …」那行；
3. `adb shell dumpsys activity activities | grep topResumed` → App 是不是卡在某个页面；
4. 手工 `am force-stop <pkg>` 释放，或直接重启实例。

### 6.3.1 正解：协作式截止时间（2026-11-04 落地）

"让占用可观测"只能帮你事后查；**要让卡死自己结束**，得让 worker 主动退出。

路由级超时做不到这件事——`ThreadPoolExecutor` 的 worker **不可取消**，
`wait(timeout)` 只是"不再等 future"，线程仍在跑、仍占着锁。

所以改成**协作式截止**：拿到设备锁时给设备一个预算，超时后 worker 在
**下一个 adb 调用**处主动放弃（卡死都发生在 adb 上），于是几毫秒内退回、
`finally` 里释放锁。

```yaml
android:
  fetch_budget_s: 540    # 0 = 不限制（回到旧行为）
```

**为什么是 540 而不是 900**：必须**小于**路由级超时（900s）。要让 worker
先退出、路由后放弃；反过来就是这次事故——路由等不到人，整轮被拖住。

实机等价的验证（假设备模拟"卡住的采集"）：

```
结果: aborted（20 次 adb）耗时 1.0s
[android] app_qunar 采集超出预算 1s，已主动放弃（1 次 adb 被拦），锁已释放
锁状态: owner=''（已释放）
```

对应实现：

* `AdbDevice.set_deadline(budget_s)` / `deadline_left()` / `_expired()`
  —— 守卫放在 `_sh()` **最前面**，所有 adb 指令（dump/tap/screencap）都走它；
* `AndroidRuntime.device_lock()` —— 拿到锁就 arm、`finally` 里解除，
  **一处改动覆盖全部 6 个 App 渠道**（不用改渠道代码）；
* 预算耗尽时打 warning：`XX 采集超出预算 540s，已主动放弃（N 次 adb 被拦），锁已释放`
  —— 与"设备掉线"区分开，不会被误判成硬件问题。

> 测试注意：单测里若直接 `device_lock()` 抢**模块级真锁**，而同一测试进程里
> 还有采集线程持锁，就会真的等 600s（2026-11-04 实测把一批单测拖到超时）。
> `test_r925/r927/r667` 已加 `_isolated_lock` fixture 把锁换掉，测试互不影响。

**观测面上屏（r959）**：`/api/health` 新增 `device_lock` 字段，健康诊断卡
标题行直接显示「设备锁 app_qunar 持有 187s，预算耗尽 2 次」；空闲时显示
「设备锁空闲」，Android 关闭时不占位。`_device_lock_view()` 每次请求实时读，
不跟随健康数据的 30s 缓存——卡死现场几秒内就能在页面上看到是谁占着。
门禁 `tests/test_r959_device_lock_visibility.py`（字段形状 + 真渲染 + 负控）。

> 顺带一条不该忘的：**`blocked` 在 `pacing` 里一律归 `captcha`（冷却 300s）**。
> 这是刻意设计（结构化状态优先），所以采集器**绝不能**把"页面没打开"
> 记成 `blocked`——智行那 22 次「命中captcha」里绝大多数是导航失败被记成了
> 拦截。现在 `pacing.classify_evidence()` 会把判定证据（`status=blocked` /
> `note~=安全验证`）记进快照，下次能直接看出是哪条证据判的。

---

## 6.4 谁在拖后腿：按**结果**算，不要按症状算（2026-11-04）

教训先说：我一开始盯着「soft 149 次」想去改软拒退避，但一算**结果**就发现
那是错的方向——149 次里大部分是"同一轮内多条航线各自 soft"，而 soft 不冷却
是**刻意设计**（软拒≠被封）。真正该看的是**每轮到底有没有拿到数**。

最近三天（11-02~04）实测：

| 渠道 | 轮数 | 成功率 | 零结果 |
|---|---|---|---|
| ctrip | 235 | **100%** | 0 |
| 同程 | 178 | **100%** | 0 |
| 飞猪 | 82 | **100%** | 0 |
| 途牛 | 135 | 98% | 2 |
| app_zhixing | 192 | 81% | 36 |
| qunar（H5） | 234 | **50%** | 117 |
| **app_qunar（App）** | 170 | **26%** | **125** |

**两个 qunar 贡献了 280 次零结果里的 86%**，整体成功率被它们从 ~99% 拖到 77%。

### app_qunar 26% 的真因：档位跨轮残留

失败现场 `debug/scene/*_setcity-timeout-arr.txt` 清一色是这样：

```
选择目的地 / 搜索国家/城市/景点等 / 国内·港澳台 | 国际
atom_flight_tab_item_tv  国内/港澳台   180,257,310,292
atom_flight_tab_item_tv  国际         671,257,719,292
atom_flight_tab_item_line             677,296,713,301   ← 下划线在「国际」下
qd_city_rlTab2                                        ← 国际档内容
[app_qunar] 设到达城市失败：海口                        ← 国内城市
```

上一轮跑完**国际航线**后城市页停在「国际」档，下一轮国内航线搜"海口"时
国际列表里根本没有它 → 等满 45s/12 帧 → 记 `setcity-timeout-arr`。

代码里原来写着「**不需要碰档位**」——一半对：**无条件**点档位确实有害
（22:06 直接回首页、22:08 落到特价页），所以修复刻意做成**有条件**：

* 只在「**已经输入过、却一条结果都没有**」时切一次档位；
* `_tab_tried` 保证**只切一次**，切完重新搜；
* 档位判断 `_looks_intl_city()` 走 `core.citydata` 的国内城市表
  （机场码先归一，`NRT`=国际、`PEK`=国内）；
* 选中态 `_tab_is_selected()` 认两种表达（`selected="true"` 属性 /
  下划线位置）——注意 `_nodes()` 会丢掉 `selected` 属性，必须在原始 XML 上判。

> **方法论**：先按结果排序（哪家真没出数），再看症状（为什么）。反过来做
> 很容易去优化一个不痛的地方——soft 149 次看着吓人，改它却没用。

---

## 6.5 慢机判死：固定秒数等页面必然失败（2026-11-04）

真实日志（11-03，14 次一模一样）：

`
[app_zhixing] 前台是 com.Qunar，先切回 cn.suanya.zhixing（上一渠道未退出）
[app_zhixing] 设置航线失败：首页未就绪（等待 60s 并回退 4 级仍找不到「机票查询」）
`

看着像"App 打不开"，其实是**预算算错了**：

| 场景 | 单帧 dump 耗时 | 60s 能取几帧 |
|---|---|---|
| 空载 | 2–3s | 20 帧（够） |
| **5 个浏览器渠道同时占 CPU** | **~20s** | **3 帧（不够）** |

而"连续两帧都是首页"最少要 **6 帧**（中间任一帧是残留日历弹层就重置计数）。
慢机上**必然超时**，文案却说"App 没打开"——把人往错方向引。

修法（统一抽象 + 单点实现）：

1. crawlers/app_base.py::wait_ready() —— 共享的"等页面就绪"：
   **按帧数预算 + 首帧慢则自适应放宽总时长**，返回 (ok, xml, why)；
2. pp_zhixing_nav.set_flight_route() 改成 14 帧 / 90s（慢机放宽 150s），
   BACK 回退 4 级 → **6 级**（两层弹层时差一步）；
3. 失败文案改为报**实际帧数与耗时**（等 N 帧 / 约 Ms）——下次才能判断
   是"慢"还是"真打不开"。

> 别再各渠道各写一套固定秒数（deadline = time.time() + 60 这类散落 10+ 处）。
> 新代码一律用 wait_ready()；老代码改动时顺手替换。

---

## 6.6 `¥` 前缀丢掉整页价格（2026-11-04）

`app_qunar` 修好档位残留后，失败模式变成：

```
[app_qunar] 2026-11-16 列表 1 行、带价 0 行（再等一拍仍无可用价）
```

现场落盘 `debug/scene/*_nopriced-*.txt` 一看就明白了——**价格全在**：

```
| ¥5711 | flight_search_rn|QunarFlightInterRoundMixList|ItemPrice |  | 662,366,723,399
| ¥4999 | flight_search_rn|QunarFlightInterRoundMixList|ItemPrice |  | 653,505,723,538
| 20:55 | flight_search_rn|QunarFlightInterRoundMixList|ItemDepTime |  | 18,366,80,399
| 00:45 | flight_search_rn|QunarFlightInterRoundMixList|ItemArrTime |  | 301,366,366,399
```

但取 `ItemPrice` 时要求 text 是**纯 2–5 位数字**：

```python
if not re.fullmatch(r"\d{2,5}", val):   # "¥5711" → 不匹配 → 丢掉
```

于是国际**中转混合列表**（`QunarFlightInterRoundMixList`）整页价格被丢光，
上层只看到"有航班行、带价 0 行"，记 `no-priced-rows`。

修法：先剥货币符号与千分位再校验。**用同一份真实现场对照**：

| | 解析行数 | 带价行数 |
|---|---|---|
| 修前 | 6 | **0** |
| 修后 | 6 | **6**（5711/4999/5455/5465/8418/8418） |

> 排查时踩了个坑值得记：现场文本是 `| text | desc | desc2 | bounds`，而
> **desc 自身含 `|`**（`flight_search_rn|Qunar...|ItemPrice`）。按 `split("|")`
> 取列会把 desc 切碎成多段，`parts[2]` 只剩 `flight_search_rn` → 诊断脚本
> 误判成"价格取不到"。正确做法是先用正则剥掉尾部 bounds，再把中间列拼回。

---

## 6.7 脏价比缺数据更糟：`¥20` 当票价进了库（2026-11-04）

在验证 `¥` 价格修复时顺手查了库，发现 `app_qunar` 的历史行**全是 `￥20.0`**：

```
SHA->HAK 2027-01-29 ￥20.0  2026-11-03 22:52:43
SHA->NRT 2026-11-16 ￥20.0  2026-11-03 22:47:43
SHA->BKK 2026-11-16 ￥20.0  2026-11-03 16:40:01
```

`20` 不是票价——它是现场里这个：

```
| 全程下单可减 |  | 573,853,675,877
| ¥           |  | 689,854,698,877
| 20          |  | 698,853,717,877     ← 「全程下单可减 ¥20」
```

`_to_prices()` 取**最低价**做行头，而 20 永远最小 → 每一条都选中它。
于是一条"实际 ¥4999"的航线，账上写着 ¥20。

**为什么这比"没数据"更糟**：低价提醒会照 ¥20 触发，用户点进去发现 4999；
走势图也被这群 20 拉平，看不出真实波动。缺数据只是"这轮没值"，
脏数据是"给了一个错的值"，后者会让人做错决策。

三层防线（都已就位）：

1. **`core.price.parse_price()`** —— 价格文本归一唯一实现，`4??` 遮罩返回
   `None`、`¥` 单符号返回 `None`、绝不返回 0；
2. **`PRICE_MIN = 100`**（`core.models`）—— `parse_flight_rows` 里
   「低于价格带下限的『价格』不是票价」，置 `price=None`；
   无航班号且越界的整行跳过；
3. **`price_band_ok()`** 在落库前再过滤一次（`crawlers/base.py`）。

实测确认：`PRICE_MIN` 上线后，`2026-11-04` 全天各平台**没有一条 `price<100`**；
同一条 SHA→BKK 在修复后入库 **￥4999.0**（正是现场六个价之一）。

历史脏数据已清（先备份 `data/prices.db.bak_<时间戳>` 再 `DELETE`，11 行）。

> 教训：修好"解析不到价"之后**一定要回头看入库值**。解析通了不等于值对——
> 从"0 行"变成"全是 20"也算"通了"，但那是更坏的结局。

---

## 6.8 中转行没有航班号、价格被当航班号（2026-11-04）

修好 `¥` 价格后，`app_qunar` 从"0 行"变成"6 行有价"，但入库的 `flight_no`
是空；同时还看到一行 `flight_no='11022'`、`price=11022`。

两个问题叠在一起：

**① 中转行的身份只在 `content-desc` 里。**

```
|  | flight_search_rn|QunarFlightInterList|FlightsRound_OD617|PVG-KUL
   |2026-11-16/OD528|KUL-DMK|2026-11-16 |  | 0,481,
```

`text` 是空的，而 `_nodes()` 只收"有文字的节点"，于是整条被过滤掉。
下游只看得到"这天有个 ¥5711"，看不出是哪一班。

**② 纯数字被误判成航班号。**

`_FLIGHT_RE = ([A-Z0-9]{2}\d{3,4})` 把价格 `11022` 匹配成 `11` + `022`
→ 入库 `flight_no='11022'`。一个看着像航班号的数字，其实是这一天的票价。

修法：

1. **`_desc_flight_marks()`** —— 从 `content-desc` 的 `FlightsRound_` 段取航班号；
   两段（真中转）用 `+` 连成 `OD617+OD528`（单程号会让"到底是哪班"含糊）；
2. 卡片内 `code` 为空时用它兜底，`text` 里有则优先用 `text`；
3. **`_FLIGHT_RE` 要求前缀至少一个字母** —— `11022` 不再匹配，
   而 `3U8889` / `9C7293` 这类"数字开头"的真实航司码仍然认得出。

真实现场（`2026-11-04 10:49` SHA→HAK，7 张卡片）对照：

| | 解析行数 | 有航司码 | 纯数字假码 |
|---|---|---|---|
| 修前 | 7 | 0 | 1（`11022`） |
| 修后 | 7 | **7**（MU3686/MU3748/CZ8757/CZ3516/CZ6686/CZ6766/CA8573） | 0 |

> 顺带纠正一个容易误读的点：这些行来自 `QunarFlightInterRoundMixList`
> （中转混合列表**组件**），但每段只有一个航班号（desc 里没有 `/` 第二段），
> 所以它们**确实是直飞**，`trans_city` 为空是对的。
> **组件名叫 RoundMix，不代表里面每行都是中转**——判中转要看页面上有没有
> 「转 XX / 停 X 时」文案，不能看容器名。

---

## 6.9 判据假设了"只有一种写法"：日期入口永远找不到（2026-11-04）

重启后第一轮（11:28）智行又 0 条：

```
[app_zhixing] 长窗口日历未打开：找不到日期入口
[app_zhixing] 明细页没解析出带价航班：2026-11-16
[app_zhixing] 抓取完成，得到 0 条记录
```

`open_date_dialog()` 找日期入口的判据是：

```python
if re.fullmatch(r"\d{1,2}月\d{1,2}日", n.text or ""):
```

但智行的日期文案有**两种**，而真实 fixture
（`tests/fixtures/zhixing_list_dump.xml`，真机 dump）里**只有横线那种**：

```
中文格式节点: []                                    ← 一个都没有
横线格式节点: ['10-29', '10-30', '10-31', '11-01', ...]
```

也就是说在这份真实页面上，旧判据**必然**返回「找不到日期入口」——
长窗口日历打不开，明细页自然没有带价航班。

修法：两种格式都认，**优先中文**（它才是"打开日历"的那一行），
没有再退回横线格子。

> **这类 bug 的共同点：判据假设了"只有一种写法"。**
> 修的时候要拿真实 fixture 验一遍「旧判据在这份数据上能不能命中」——
> 能命中才说明判据成立；命中不了就是判据错，不是数据错。
> 本仓库已有这个习惯（fixtures + 现场落盘），照做就能一次到位。

同一轮还顺手修了第二个同族问题：`_await_home()` 仍是纯秒数（默认 30s），
慢机（5 个浏览器渠道同时占 CPU，单帧 ~20s）只够 1–2 帧，于是报
「没取到首页（dump 连续为空）」——看着像 uiautomator 挂了，其实只是慢。
现在也改成帧预算（10 帧），与 `set_flight_route` 同一策略。

---

## 6.10 认不出页面时不落现场 —— 同一个失败连查几轮还在猜（2026-11-04）

账本（`fetch_paths`）把原因说得很清楚，可那两条**等于没说**：

```
app_qunar    航班明细  timeout  | 未取到可用结果：no-list-page
app_zhixing  app-list  timeout  | 无法识别的页面状态（可能是 App 改版）
```

列表页为什么没出现？当时到底停在哪一屏？——**没有证据**。
而两次 `no-list-page` 各花了 **154s / 170s** 设备时间，只能下一轮再猜。

对比就很刺眼：`no-priced-rows` 分支**有**落现场（`nopriced-<date>`），
所以那个问题几轮就查清了（`¥` 前缀那次的现场正是从这儿来的）。

**结论：越"认不出"的失败越需要现场，而它偏偏没落盘。**

修法（统一抽象）：

1. **`app_base.save_scene()`** —— 通用落盘，任何 App 渠道都能用。
   只留前 150 条带文案/id/desc 的节点（真机 dump 常 200KB，不宜整份存）；
   `TICKET_SCENE_DIR` 作为测试隔离锚，避免合成现场混进生产目录。
   （原来只有 `app_qunar` 自己写了一份私有的 `_save_fail_scene`，
   其它渠道出问题时**完全没有证据**。）
2. `app_qunar` 的 `no-list-page` 分支落 `nolist-<date>`，并**一行说清**
   命中了哪些已知标记：

   ```
   [app_qunar] 2026-11-16 列表页未出现（4832 字，命中：首页/城市页），已落现场 nolist
   ```

   不用打开 8KB 的 dump 就知道"卡在城市页没进去"。
3. `app_zhixing` 的「无法识别的页面状态」落 `unknown-page`，同样打标记命中。

> **给以后的人**：新增一条"失败返回"分支时，先问自己
> **"下一轮的人靠这行字能定位吗？"** 不能就 `save_scene()` 一份。
> 这不是为了好看——`¥` 前缀、档位残留、航班号丢失三个 bug 全靠现场破的，
> 没有现场的那几个（日期入口、`no-list-page`）都是猜了两轮以上。

---

## 6.11 `soft_reject` 被记成"被拦"：57/62 份 block 现场其实是限流（2026-11-04）

清点 `debug/scene/*_block.txt`：

```
国际列表 interlist     57
其他                    5
合计                   62
```

而 `block:` 那行全部带 `_gogokid=12`（去哪儿的风控指纹参数），
读起来像"**被风控拦了 62 次**"。实际主要来源是**国际列表 1999 间歇放行**
——那是 `soft_reject`（发了、对方软拒/限流），不是风控拦截（`blocked`）。

根因在 `BaseCrawler.path_note()`：

```python
if rec["status"] in ("blocked", "login", "soft_reject"):   # ← soft 也进来了
    ... self.last_block_url = purl ...
```

后果：

* `debug/scene/*_block.txt` 每轮国际限流都留一份，越堆越多；
* **真拦截（人机验证）淹没在限流现场里**，翻日志看不出哪个才是真的；
* 文件名 tag 是 `block`，读起来就是"这次被拦了"。

账本里 status **已经**区分 `blocked` / `soft_reject`，现场留证也该一致。
现在改成只对 `blocked` / `login` 留 "被拦" 现场。

顺带把 57 份误导性现场移到 `debug/scene_backup_<时间戳>/`（不删，
留着还能查限流历史），让 `debug/scene` 重新变成"真问题现场"。

> 判断口径统一的做法：**账本里怎么区分，现场留证就怎么区分**。
> 一边分三档、另一边混成一档，等于白分了——而且会把真信号埋掉。

---

## 6.12 "重试"重试了一个注定失败的动作（2026-11-04）

`r934` 给「点了日期但弹层没关」加了 BACK + 重试。上线后第一次真机跑：

```
[app_zhixing] 明细前置选日期失败：点了日期但弹层没关（重试时找不到格子）
```

看着像"重试也失败了"，其实是**重试本身写错了**：

```python
gone, _ = dismiss_until_gone(dev, "Search_Calendar_Dialog", tries=1)
if attempt < 4:
    cell2 = _calendar_cell(dev.dump() or "", ymd)     # ← 这一步注定 None
    if cell2 is not None and dev.tap(*cell2): ...
    else:
        return False, "点了日期但弹层没关（重试时找不到格子）"
```

`dismiss_until_gone()` 的职责**就是把弹层关掉**。关掉之后，
`_calendar_cell()` 当然找不到格子——"重试"等于白做，
只是把文案从「弹层没关」换成「重试时找不到格子」。

正确顺序是**重建前提 → 再做动作**：

```python
reopened, why = open_date_dialog(dev)      # 弹层已经关了，先重新打开
if not reopened:
    return False, "点了日期但弹层没关（重开弹层失败：%s）" % why
return _tap_calendar_cell(dev, dev.dump() or "", ymd)   # 走完整的滚动+查找
```

次数由外层 `attempt` 上限（5 次）兜住，不会无限递归。

> **通用教训**：写"重试"之前先问一句
> **"上一步是不是把重试需要的前提给破坏掉了？"**
> 关弹层→找格子、退页面→找控件、清输入→读旧值，都是这一类。
> 好的重试结构是「重建前提 → 再做动作」，不是「把动作再做一遍」。

---

## 6.13 档位残留不止「往返」，还有「多程」——34 次 `no-list-page` 的真因

上一轮埋的落现场钩子，这一轮第一份 `nolist-*` 就把病根摆在桌上：

```
选择航班
抱歉未找到符合条件的多程航班
建议修改搜索条件或分开预订
第一程   上海 → 伦敦   11月16日 出发
第二程   海口 → 东京   2月17日 出发
```

App 停在**多程**档（上一轮留下的），而本轮要查的是**单程 SHA→LHR**。

而 `_switch_to_single()` 的判据只有一条：

```python
if _ID_BACK_DATE_LL not in (xml or ""):   # atom_flight_ll_back_date
    return xml                            # 认为"已是单程"
```

**多程页没有返程日期位**（它是「第一程 / 第二程」两段），于是判据不命中
→ 认为已是单程 → 不切档 → 直接搜索 → 落到多程结果页 → `detect_state`
拿不到"起降时刻对" → 记 `no-list-page`。

账本实证（近两天 `fetch_paths`，`app_qunar`）：

| 次数 | 状态 | 说明 |
|---|---|---|
| **34** | timeout | `no-list-page` ← **83% 的失败** |
| 11 | ok | 1 条真实航班/时刻/价格 |
| 5 | timeout | `no-priced-rows` |
| 5 | timeout | `pick-date-failed` |
| 2 | timeout | 没能打开机票首页 |

修法：判据加上多程特征（`第一程` + `第二程` 同现），并在多程**结果页**
（无档位切换控件）时先 `BACK` 退回表单再找。

> **这是第三次栽在"档位/状态残留"上**：
> ① qunar 城市页的「国内/国际」档（r928）；
> ② 往返档残留（代码里早就修过）；
> ③ 多程档残留（本轮）。
> 共同点：**判据只覆盖了自己见过的那一种残留**。
> 以后再处理"切回默认状态"，先问：**这个界面一共有几个状态？我覆盖了几个？**

---

## 6.14 多程退栈不止一层 + 让门禁认 commit SHA（2026-11-04）

### 多程退栈要循环

r939 的修法是「多程结果页按 BACK 退回表单再点单程」。但**只 BACK 一次**
是不够稳的——退栈路径不保证永远一层（结果页 → 查询中间页 → 表单 也可能）。
只按一次，等于把"退不干净"变成新的 `no-list-page` 来源。

现在改成**循环退栈，最多 3 层**，并在退到机票首页表单（有城市位）却还没
看到「单程」时多给一帧渲染机会。

> 又一次印证同一句话：**先问"这个界面一共有几个状态/几层"，再写切换逻辑。**

### 门禁：commit SHA 也算时间限定

`test_spec_historical_run_notes_are_time_bound` 三天内抓了**三次**同样的问题：
并行会话新写的「门禁：tracked collect **6643**；干净克隆 `1c0b8c4` 全量
**6597 passed**」缺时间限定，读起来像现状。

每次都靠人工补「（2026-11-04 当时快照）」——**不可靠**。
而那段话里的 `1c0b8c4`（短 SHA）本身就等于"这是那个提交上的快照"，
和日期是同一类时点证据。

所以把 `TIME_MARK` 扩展为也认长度 ≥7 的全十六进制串：

```python
TIME_MARK = re.compile(
    r"20\d\d-\d\d-\d\d|\d{1,2}:\d{2}|第\s*[一二三四五六七八九十\d]+\s*次|"
    r"r\d{3,}|当时|那轮|\b[0-9a-f]{7,40}\b")
```

> 一条门禁如果**反复靠人工补**，说明判据缺了一类合法证据，该修的是门禁
> 本身，不是每次去补。这也是本轮唯一一次"改测试而不是改代码"。

---

## 6.15 国际配额被第一条航线独吞：qunar 只有 23% 的算术原因（2026-11-04）

今日账本（`fetch_paths`，qunar 30 次）：

```
 7×  H5     ok          | touch.qunar.com H5 列表
 6×  QUERY  soft_reject | 国际查询让位：上一条国际查询软空/限流
 5×  H5     soft_reject | 1999/8 连续 2 次（Cookie 在场 → 按限流退避）
 5×  H5     soft_reject | 1999/8 间歇放行（单次）
 1×  H5     soft_reject | 1999/8 连续 3 次
 1×  H5     soft_reject | 1999/8 连续 4 次
```

拆开看：成功 7、限流 12、让位 6——**没有一条是"被风控拦"**，全是配额。

国际列表限额**约 5 分钟/次、与航线无关**，而配置里有 **4 条国际航线**
（NRT / BKK / SIN / LHR）。让位窗口内**所有**国际航线一律跳过，而采集每轮
都从配置里第一条（SHA→NRT）开始：

```
NRT 拿配额 → BKK/SIN/LHR 全让位 → 下一轮又从 NRT 开始
⇒ NRT 天天成功，其余三条永远饿不到
```

**这就是 23% 的算术来源**：4 条国际里只有 1 条能吃到配额。

修法：让位窗口只挡「**刚查过的**」，给「**一直没轮到的**」留一个口子——
**每个让位窗口最多绕过一次**。绕过的那条立刻记时间戳，下个窗口轮到下一条。

为什么是"每窗口一次"而不是"全都放行"：4 条同时打会连撞 4 次 1999，
把限流坐实，比现在更糟。

> 写这段时踩了个自己的坑值得记：第一版判据写的是
> `if _last_try and _starved` —— 「从没查过」的航线 `_last_try == 0`，
> 于是 `_last_try and ...` 恒为 False ⇒ **永远让位、永远轮不到**。
> 正好把要修的问题原样复现了一遍。测试里的
> `test_never_tried_route_bypasses_once` 就是钉这个的。

---

## 6.16 轮转其实被"重启"废掉了 / 多程结果页退不出去（2026-11-04）

### ① 轮转状态放内存 = 每重启一次就从头开始

r940 的轮转用 `_intl_route_seen` 记"每条国际航线上次轮到的时间"。
**但它只在内存里**，进程一重启就清空，而配置里第一条永远是 SHA→NRT：

```
重启 → 全清 → 又轮到 NRT → 重启 → 又轮到 NRT …
```

当天我为了加载新代码重启了 **6 次**——等于亲手把轮转钉在第一条上，
把刚修好的公平轮转废掉了。落盘之后（`user_data/qunar/intl_rotation.json`）：

| 轮次（每轮都重启） | 放行的航线 |
|---|---|
| 第 1 轮 | NRT |
| 第 2 轮 | **BKK** |
| 第 3 轮 | **SIN** |
| 第 4 轮 | **LHR** |

> **教训**：任何"记住上次做到哪"的状态，**都要问一句会不会被重启清掉**。
> 尤其在这种"每加一个修复就重启一次"的开发节奏下，内存态等于没有。

### ② 多程结果页：没有「单程」控件，BACK 也退不出去

第二轮现场（12:45）还是多程页，但这次看清了：**它连「单程」控件都没有**。

```
选择航班 / 抱歉未找到符合条件的多程航班
第一程 上海→伦敦 / 第二程 海口→东京
多程 ✓   单程 ✗   往返 ✗
atom_flight_search_panel ✗        ← 压根不在首页
```

说明：
* 只认「第一程+第二程」不够——多程**结果页**可能只带「多程」文案；
* 这种页面**不在正常导航栈里**，BACK 退不回表单。

修法两层：
1. 判据放宽到「**出现「多程」即需处理**」；
2. `_switch_to_single` 尽力后仍看到「多程」→ **force-stop + 深链重建**
   （`_ensure_home` 自带这套），重建后再切一次；
3. 重建也失败则如实记 `多程档残留：切单程与重建均未成功`，
   **不假装在单程页上继续跑**。

---

## 7. 别做的事（只看会真吃亏的）
1. 重试风暴——唯一能把「限你」升级成「封你」的动作。
2. 把换 IP / 住宅代理当常态——真 429 只占 0.3%，为它付 100% 成本；国内站配境外出口反而升档。
3. 用自家锁冲突惩罚对方站点。
4. 靠降速解决设备身份命中（设备规则与频率无关）。
5. **没验证就写 `ro.product.cpu.abi=arm64`**——先跑 `abi_canary.run()` 拿判定，
   再 `identity.spoof_abi: auto`（见 §3.7）。
6. **直接改 `wm size` 却不开 `dev.set_design()`**——坐标会按比例偏；要么只做
   §3.7 的身份对齐（推荐），要么连坐标换算一起开。
7. **接第三方打码服务**（把账号交给陌生人）；**在强人机上硬试**（极验 v4/天御/
   baxia/点选/人脸的行为判定越试越像机器）。几何滑块自己解，强人机交人工。
8. 调高并发到 4+ 或 5 家同秒齐发。
9. 在模拟器上装途牛 App（`libtuniudns.so` SIGSEGV，与登录无关）。

---

## 8. 回滚矩阵

| 改动 | 关掉的方式 | 影响面 |
|---|---|---|
| 统一策略层 | `crawler.policy_gate: false` | 回到各部件各自判断；账本/报表照旧 |
| 策略状态 | 删 `user_data/<profile>/policy_state.json` | 停手/余温全部清零 |
| 滑块自动尝试 | `crawler.slider.auto: off`（默认 `off`；已开为 `simple`） | 回到"识别→记账→停手" |
| 单日隔离 | 无需开关（异常日只记该日 `timeout`） | 想回旧行为需改渠道循环 |
| 滑块拉黑 | 删 `user_data/<profile>/slider_ledger.json` | 预算/拉黑清零 |
| 身份屏幕对齐 | `android.identity.align_display: false` | 身份声明保持池里的原值 |
| 屏幕伪装 | `display.reset(dev)`（或 `adb shell wm size reset`） | 回到物理分辨率 |
| ABI 伪装 | `android.identity.spoof_abi: null`；或删 `user_data/device/abi_canary.json` | 不再写 ABI props |
| 会话等待 | `crawler.profile_wait_s: 0` | 回到「立刻让位」 |
| 实例调优 | `android.tuning.enabled: false` | App 段回到动画/息屏原状 |
| 对数正态停顿 | 无开关（区间语义不变）；要复现旧行为可临时改 `crawlers/base.py::_sleep` | 仅间隔形状 |
| 地理一致 | 删掉 `crawler.geo` | 回到 zh-CN / Asia/Shanghai |
| 爬取率账本 | 删 `user_data/<profile>/yield_stats.json` 即清零；不影响采集 | 仅报表 |
| 登录退避 | 删 `user_data/<profile>/login_ledger.json` | 连击数归零 |
| 设备身份 | `android.identity.enabled: false`；彻底重置见设备手册 §10 | 不再写任何 props |
