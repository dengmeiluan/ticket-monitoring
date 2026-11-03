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
