# 设备身份与风控对抗手册

> 适用：本仓库在 MuMu 模拟器（App 渠道）+ Playwright（PC/H5 渠道）上采集携程 / 飞猪 /
> 去哪儿 / 同程 / 途牛时的「登录不上、频繁掉登录、被限流」问题。
>
> 本文只写**本仓库已经实现的东西**怎么用、怎么验、怎么回滚。设计动机都在模块 docstring 里
> （`core/android/fingerprint.py`、`core/android/stealth.py`、`crawlers/stealth_ext.py`、
> `crawlers/human.py`、`core/riskscore.py`），这里不重复论证。
>
> 产量侧（爬取率/会话/调度）看 `docs/YIELD_AND_SESSION_STRATEGY.md`；
> 限流归因与阈值看 `docs/RATE_LIMIT_PLAYBOOK.md`。

---

## 0. 一个前提：先分清三种「被风控」

现场最容易搞混的是这三件事，处置完全不同。**降速对第 1、3 类无效，换 IP 对第 1、2 类无效。**

| 现象 | 真实类别 | 判据（本仓库能看到的） | 有效手段 |
|---|---|---|---|
| 登录收不到短信 / 提交即「登录失败请稍后重试」/ 刚登录就被踢 | **设备身份类** | `path_note` 反复 `login`；`fingerprint.audit()` 分低；`ro.debuggable=1`、`ro.build.tags=test-keys` | 设备身份 + root/模拟器隐藏（本文 §2、§3） |
| 页面还在 200，但深链全 444 / 202 空体 | **会话类**（L1/L3） | `last_soft_reject`、预热后风控 cookie 没落下 | 预热 + 会话保活 + 少重登（§4） |
| 真 403 / 429 / 滑块弹出 | **频率/行为类** | 响应状态、`challenge.classify_text` | 降速 + 形状拟人 + 熔断停手（§5） |

仓库既有归因数据（1997 次失败样本）：真 429 只占 0.3%，而「自家链路顺序错乱」导致 63%。
**所以顺序永远是：先修设备与会话，最后才动频率。**

---

## 1. 三层模型

```
身份层（我是谁）        设备：android_id / 序列号 / Build 字段 / 机型     ← §2 §3
                       浏览器：UA / UA-CH / WebGL / Canvas / 屏幕 / WebRTC ← §6
会话层（我熟不熟）      cookie 预热、登录态快照、少冷启、失败退避        ← §4
行为层（我像不像人）    间隔分布、鼠标轨迹、滚动、停留、并发上限          ← §5
```

三层都要自洽：改了 UA 不改 WebGL 等于自报矛盾；换了 android_id 不清 App 里的
`utdid/umid` 缓存，服务端看到的是「新设备 + 旧设备 ID」，比不换更可疑。

---

## 2. 设备身份（App 侧，影响最大的一层）

### 2.1 它做什么

`core/android/fingerprint.py`：

1. 从**真实机型池**（`PHONE_POOL`，8 台 Android 12/13 常见机）里整台选一台——
   `ro.product.model/brand/manufacturer/device/board`、`ro.build.fingerprint`、
   `ro.build.id/display.id` 互相自洽，不做字段级拼缝；
2. 派生 `android_id`（16 位 hex）、`ro.serialno`、WLAN/BT MAC；
3. 身份落盘 `user_data/device/device_identity.json`——**进程重启、实例重建都是同一台设备**；
4. 按 boot_id 每启动周期只应用一次（快路径 = 一条 adb 读标记）；
5. `audit()` 如实报「还剩哪些特征没清」；ABI 单独走 §3.4b 的 canary 实测再决定要不要写。

### 2.2 开关

```yaml
android:
  identity:
    enabled: true      # 缺省=开（与 crawler.stealth 同一约定）
    use_root: null     # null=自动探测；false=只用 setprop（ro.* 改不动，会记 failed）
    reboot: zygote     # zygote|full|none —— Build 字段在 zygote 定型，改 props 必须重启框架
    force: false       # true=非模拟器也强行应用（真机别开）
```

**`reboot: zygote` 是默认且推荐的**：`stop; start` 8–15s，保留模拟器与 adb；
不重启框架的话，已在跑的 App 读到的还是旧 Build——等于没改。

### 2.3 什么时候换身份

```python
from core.android import fingerprint as fp_mod
rep = fp_mod.rotate(dev, cfg, logger, user_data_dir="user_data",
                    profile="device", vm=0)   # 换机型 + 换派生 ID
```

**只在下面三条同时成立时换**：`riskscore` 给到 `rotate` 档（设备项占分过半）、
`LoginLedger.should_rotate()` 为真（设备风险 ≥3 且连击 ≥2）、且你已经试过「停 30 分钟」。
换身份本身是一次「新设备登录」，会触发二次校验——**频繁换比不换更糟**。

换完必须清 App 侧缓存的旧设备 ID（否则组合矛盾）：

```python
from core.android import stealth as st
st.clear_app_identity(dev, packages=["ctrip", "fliggy"], dry_run=True)   # 先看会动哪些文件
st.clear_app_identity(dev, packages=["ctrip", "fliggy"], dry_run=False)  # 备份到 /data/local/tmp/tm_idbak-*
```

### 2.4 多开实例：别让两个实例是「同一台设备」

MuMu 多开若用**克隆**创建，`android_id` / 序列号会一起被复制——两个实例、两个账号，
服务端看到的是「同一台设备多账号登录」，这是比单账号高频更重的规则。

本层的派生 ID 带 `vm` 分量（`build(seed, vm=...)`）就是为了这件事，但**每个实例都要各跑一次**：

```yaml
android:
  vm_index: 0      # 实例 0 的配置；实例 1 要把整份配置复制一份、改成 1
```

验收：两个实例 `adb shell settings get secure android_id` 必须不同，且各自的
`user_data/device/device_identity.json` 里 `vm` 不同。

另外两条与「少重登」直接相关：

- **不要用 `pm clear` 清 App 数据来「刷新」**：清了就等于注销 + 新设备首启，
  一次清掉的是登录态 + 设备 ID + 风控 cookie 三样。要换身份用 §2.3 的 `rotate()`。
- `session_max_days: 14` 是会话年龄看门狗。调大不会更稳，只会让「早已失效的会话」
  继续被当成可用，多跑几轮空请求。

---

## 3. root / 模拟器痕迹隐藏

### 3.1 为什么不能「不要 root」

快照要读 `/data/data`（`core/android/snapshot.py` 硬依赖 root）。所以策略是
**root 只对我们可见**：Magisk DenyList 让目标 App 看不到 `su` 与 `/data/adb`，
同时把 App 本地判定的输入（`ro.debuggable` / `ro.secure` / `ro.build.tags`）清干净。

### 3.2 它做什么（`core/android/stealth.py`）

| 动作 | 具体内容 |
|---|---|
| root props | `ro.debuggable=0`、`ro.secure=1`、`ro.adb.secure=1`、`service.adb.root=0`、`ro.build.tags=release-keys`、`ro.build.type=user`、`ro.boot.verifiedbootstate=green`、`ro.boot.flash.locked=1`、`ro.boot.veritymode=enforcing` |
| 厂商 props | 含 `mumu/netease/nemu/vbox/goldfish/qemu/bluestacks/ldplayer/noxtn` 的键**整条删掉**（存在即证据） |
| Magisk | 确保 `zygisk=1`，把 `ctrip.android.view`、`com.taobao.trip`、`com.Qunar`、`com.tongcheng.android`、`cn.suanya.zhixing`、`com.tuniu.app` 加进 DenyList |
| 管理器 | 装了 `com.topjohnwu.magisk` 就 `pm disable-user`（包名本身就是一条证据） |
| 开发者选项 | `development_settings_enabled=0`（不影响 adb 本身） |

```yaml
android:
  stealth:
    enabled: true
    hide_dev_options: true
```

### 3.3 手工验收（不看代码也能判）

```powershell
$adb = "D:\Program Files\Netease\MuMu\nx_main\adb.exe"
& $adb connect 127.0.0.1:16384
& $adb -s 127.0.0.1:16384 shell getprop | Select-String -Pattern "mumu|netease|qemu|goldfish|test-keys"
& $adb -s 127.0.0.1:16384 shell getprop ro.debuggable      # 期望 0
& $adb -s 127.0.0.1:16384 shell getprop ro.secure          # 期望 1
& $adb -s 127.0.0.1:16384 shell settings get secure android_id   # 期望 16 位 hex，且每次重启都一样
& $adb -s 127.0.0.1:16384 shell "su -c 'magisk --denylist ls'"    # 期望含 ctrip.android.view 等
```

程序侧也可以直接读：

```python
from core.android import fingerprint as fp_mod, stealth as st
fp_mod.audit(dev)        # {'score': 76, 'leaks': [...], 'abi_note': '...'}
st.detect(dev)           # {'root': [...], 'emulator': [...], 'unfixable': [...]}
st.verify(dev)           # {'props_ok': True, 'denylisted': [...], 'missing': []}
```

`audit()` 的 `score` 100 = 已知特征全清。**`abi` / `sensors` / `kernel` /
`play_integrity` 一定会留在 `unfixable` 里**——这是事实，不是没做完：
把 `ro.product.cpu.abi` 写成 `arm64-v8a` 会让 PackageManager 选错 native so，
直接复现仓库里记过的 `Runtime.load0` 主线程死锁 / ANR 120s。

### 3.5 模拟器设置里要手动关的两处（props 改不掉）

`st.detect()` 会以 `shared:` 前缀报出来，这两条只能改模拟器设置：

1. **共享文件夹**：`/mnt/shared`、`/sdcard/MuMuSharedFolder` 默认存在，
   App 一个 `File.exists()` 就能判定「这是模拟器」。MuMu 设置中心 → 基本设置 →
   关闭「共享文件夹」/「文件共享」。
2. **开机自启 adb / 图形渲染特殊选项**：这类开关不做伪装处理即可，
   但别开「截图/录屏共享」之类会在 `/sdcard` 留厂商目录的项。

MuMu 12 若自带「手机型号」自定义，可以先用它打底（改成任意一台真机），
再由身份层覆盖剩余字段——两层都指向同一台机型时才自洽。

### 3.4 一个必须知道的顺序

`ensure_ready()` → `hardening.harden()` → 各 App 渠道 `prepare_device()`。
硬化五步的顺序由 `core/android/hardening.py` 统一编排，**不要再在别处写一遍**：

```
① 身份（props/序列号/android_id）       ← 必须最先，App 启动前生效
② 显示对齐（身份声明 vs 真实屏幕）       ← 依赖 ①，只改档案、不动 wm size
③ root/模拟器隐藏                       ← 与 ① 写同一批 props，值不冲突
④ 实例调优（动画/常亮/屏保）             ← 独立，随时可做
⑤ ABI 闸门（只有 canary 判定 ok 才写）    ← 必须最后
```

硬化发生在 **App 进程起来之前**，这是唯一能保证 `android.os.Build` 读到新值的时机。
副作用：**模拟器冷启后的第一轮会多 8–15s**（框架重启），其余轮次只有一两条 adb 的开销。

### 3.4b 屏幕与 ABI：默认只做零风险的那半

* **屏幕**：默认 `align_display: true` —— 把身份档案的 display/density 改成设备
  真实值（900×1600/320dpi），**不动 `wm size`**，所以坐标不受影响，只是让
  「机型声明」和「真实屏幕」不再自相矛盾。真要改屏幕见
  `docs/YIELD_AND_SESSION_STRATEGY.md` §3.7（要配 `dev.set_design()`）。
* **ABI**：**已跑通**（2026-11-03 实机验证），走 MuMu 官方的 **per-app ABI 表**，
  不改全局 props：

  ```
  /system/etc/mumu-configs/abi-select-android12.config
      ctrip\.android\.view      arm64-v8a      # 携程
      com\.taobao\.trip         arm64-v8a      # 飞猪
      …
  ```

  重启实例后实测：5 个包 `primaryCpuAbi=arm64-v8a`、全局 `ro.product.cpu.abi`
  仍 `x86_64`（系统稳）、携程正常启动、logcat 无 `UnsatisfiedLinkError`。

  ```python
  from core.android import vendor
  vendor.read_abi_select(dev)   # 现状
  vendor.set_app_abi(dev)       # 幂等写入 5 个票务包（自动备份）
  vendor.revert_app_abi(dev)    # 回滚
  ```

  前置：`system_disk_readonly=false`（已设，需重启生效）。
  **不要**去改 `/system/build.prop` —— 改了也会被 MuMu 启动流程覆盖
  （实测：文件确实变成 `arm64-v8a`，但重启后运行时 `getprop` 仍是 `x86_64`）。

  ```powershell
  python scripts\abi_preflight.py            # 只读预检（随时可跑，含能力探测）
  python scripts\abi_preflight.py --canary   # 全局 ro.* 路线（需 Magisk/可写系统盘）
  ```

  **2026-11-03 追加：找到根因了。** MuMu 官方设置里有
  `system_disk_readonly: true`——系统盘以只读方式挂给虚拟机，这就是
  `setprop ro.*` / `blockdev --setrw` / `remount rw` 全部「返回 0 但静默无效」
  的最深层原因。已设为 `false`（读回确认），**重启实例后生效**：

  ```powershell
  & "D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe" setting -v 0 -k system_disk_readonly -val false
  & "D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe" control -v 0 restart   # 挑采集空窗
  python scripts\abi_preflight.py            # 能力闸应变可写
  python scripts\abi_preflight.py --canary   # 再跑实测，ok 才填 auto
  ```

* **机型与屏幕优先走 MuMu 官方键**（`core/android/vendor.py`）：
  `phone_brand` / `phone_model` / `phone_miit` / `resolution_*` 都是官方设置，
  不需要 root、可持久化、写失败会报错。**能官方做的就别改 props**——props
  那条路只补官方不提供的（序列号/android_id/gsm）。默认 `vendor.apply: false`
  只读；写配置要重启实例，属于操作员的决定。

* **身份的唯一来源是官方**（2026-11-03 实测后定）：本机 MuMu 官方
  `phone_brand=Samsung` / `phone_miit=SM-A5260`，设备里 `ro.product.brand/model`
  就是 **Samsung / SM-A5260**；而我们 `setprop ro.product.model <池里的机型>`
  静默无效。所以 `fingerprint.ensure()` 生成身份时**先读官方**（`prefer_vendor`,
  默认开），机型池只兜底。否则会出现"档案说 Redmi、设备是 Samsung"——
  报告骗自己，风控读到的却是另一套。

  同时统一了写 props 的实现：`fingerprint.apply()` 现在委托给
  `abi_canary.apply_props()`（写前快照 + 写后读回）。原因：`setprop ro.*`
  在只读系统盘上**返回 0 但值不变**，只按返回码判会得出"9 条生效"的假结论。
  现在报告里 `verified`（读回真的变了）才是可信数，实测本机
  `verified = 1`（只有 `android_id` 那条走 `settings put` 真生效）、
  `ro.*` 全进 `mismatch`。

### 3.6 MuMu 会注入 `nemud.*`：这是比机型更硬的暴露面

2026-11-04 实机枚举到的（App 一个 `getprop` 就能读到）：

```
nemud.player_engine        = MUMU15      ← 直接自报"我是 MuMu 15"
nemud.player_architecture  = x86_64
nemud.device.id            = 865247046277134
nemud.player_channel       = apinochannel
nemud.display_init_rotation= 90
```

**这类键不是 `ro.*`，`setprop` 可以把值写成空**（实测：`setprop nemud.fps_limit ''`
后读回 `[]`）。风控 SDK 判的是"值里有没有内容"，所以**清空就够了**，
不必纠结"键还在"。`stealth.hide()` 已经这么做（无 Magisk 时走 `setprop 'k' ''`，
有 Magisk 走 `resetprop --delete`），实测一次清掉 **41 条**。

残留说明：`ro.nemu=1`、`ro.build.version.nemux=true` 是 `ro.*`，**没有 Magisk 删不掉**
——`detect()` 会如实报出来，这是真残留，不是误报。

### 3.7 自检分数必须是真的：`ls` 会骗你（2026-11-04 修）

之前日志里出现 `自检 0 分（剩余：fs:acct, fs:adb_keys, fs:apex, fs:bin, …）`，
看起来像"隐藏彻底失败"。实际是**误报**：

```python
ls /system/bin/su /system/xbin/su /sbin/su   # 某个参数是目录/符号链接时…
```

`ls` 会把那个参数的**内容**列出来——于是整个根目录（`acct/bin/cache/…`）
被当成 17 条 root 残留，`-6×17` 把分数扣到 0。

`stealth.detect()` 和 `fingerprint.audit()` **两处同源 bug**，都修成
`test -e <path>` 逐路径判存在。修完实测：

| 项 | 修前 | 修后 |
|---|---|---|
| `stealth.detect()` | 0 分（37 条假残留） | **92 分**（剩 `ro.nemu=1` 两条真痕迹） |
| `fingerprint.audit()` | 0 分（17 条假残留） | **88 分**（剩 ABI x86 两条，已知且刻意） |

为什么必须修：谎报会让操作员**去修一个不存在的问题**（反复重装 Magisk、
改 props），而不是看真实残留。而且它把真痕迹（`ro.nemu=1`）淹没在噪声里。


## 4. 会话层：把「重登次数」压下去

掉登录的头号原因不是频率，而是**设备身份跳变**（§2 已解决）+ **每次采集都拿旧快照盖新会话**。
后者仓库早已修过（`docs/APP_CHANNELS.md:205-212`），这里只补三条新的：

### 4.1 登录失败要退避，不能按节奏硬打

`core/riskscore.py::LoginLedger` 落 `user_data/<profile>/login_ledger.json`，
按连击数上阶梯：`0 → 90s → 300s → 900s → 1800s → 3600s → 7200s`。

为什么必须有：程序按 30 分钟一轮跑、经常重启，内存里的连击数一重启就清零，
于是「今天已经失败 5 次」被忘掉，第 6 次照常去打——**这就是「越重登越登不上」的机制**。

```python
from core.riskscore import default_ledger, assess
led = default_ledger("user_data", "ctrip")
if led.allow("ctrip"):
    led.note_attempt("ctrip")
    ...   # 走登录
    led.note_result("ctrip", ok=ok, device_risk=hit_login_or_captcha)
rep = assess("ctrip", ledger=led, captcha=False, login_wall=True)
print(rep["score"], rep["level"], rep["advice"]["text"], rep["login_wait_s"])
```

App 渠道已自动记账（`AppCrawler.safe_fetch` 的 `finally` 里 `_note_round_risk()`），
风险档位不是 `calm` 时会打一条 warning，形如：

```
[ctrip] 风控评分 72（pause）：停 30–60 分钟再跑，别再喂失败样本；建议 登录墙（会话已失效）／登录连续失败 2 次（+12）
```

### 4.2 少冷启（可选，默认关）

```yaml
android:
  keep_app_alive: true
```

省掉每次航线前的 `force-stop + 冷启`（=少一轮设备校验与首屏埋点）。
**代价**：仓库已实证「复用上一轮残留界面」会让后续航线卡在设城市（广告/子页吞点击），
所以默认是关的。什么时候开：设备身份刚换过、携程/飞猪在冷启时反复触发环境校验，
且你愿意盯着账本看 `set-city-dep` 有没有变多。

### 4.3 携程 App 登录失败的具体处置顺序

按这个顺序试，每步之间**至少隔一个退避周期**（别连打）：

1. `fp_mod.audit()` + `st.verify()` 看设备侧是否干净 → 不干净先修（这步占 80% 命中率）；
2. `reboot: zygote` 让 App 真正读到新 Build，然后 `pm clear` 清掉 App 侧旧设备 ID 缓存
   （`st.clear_app_identity(..., dry_run=False)`，会先备份）；
3. 清完**先手动登录一次**（网页内嵌画面），登录前让 App 在前台停 30–60s、翻两个页面
   （`crawlers/human.py` 的动作序列就是干这个的）；
4. 仍然失败 → `fp_mod.rotate()` 换一台机型（相当于「换手机」），再走第 3 步；
5. 换过两台机型仍失败 → 停手。此时是账号侧规则（短信次数/实名/风控人工标记），
   继续试只会加深标记。**边界：几何滑块可以开 `slider.auto` 自己解；强人机
（极验 v4/天御/baxia/点选/人脸）交人工；不接第三方打码。**

### 4.4 携程/去哪儿 H5 掉登录

- 深链直入必然掉（无 referer、无风控 cookie）。预热是治本手段，且预热成功的判据是
  **风控 cookie 是否落下**（qunar `QN1/QunarGlobal/QN205/QN277`、ctrip
  `cticket/_bfa/MKT_CKID`）——没落下就是软拒，重试无用，先修会话。
- `session_max_days: 14` 是会话年龄看门狗，别调太大；超期强制预热续期。
- 掉登录时**不要**立刻重登：先按 §4.1 退避，再用同一个 persistent profile 打开首页
  确认是否已经有登录态（仓库的「设备已登录就完全不恢复」那条规矩）。

---

## 5. 行为层：形状比频率更像人

### 5.1 拟人化（`crawlers/human.py`，默认开）

```yaml
crawler:
  humanize: true
  humanize_rounds: 2     # 约 4–8s/渠道/轮
```

- 鼠标走**二次贝塞尔**轨迹（法向随机偏移 + 每点 ±1.2px 抖动 + 落点 1–3px 修正），
  按下前停 80–260ms，按住 60–140ms 再松；
- 滚动是**一串 wheel**（90–260px/次 + 惯性尾），不是一次滚一大截；
- 打字逐字，间隔对数正态，8% 概率插入 300–600ms 的「想一下」；
- 页内间隔用 `human_delay()`：**对数正态夹区间**，不是均匀分布——均匀分布本身就是特征。

只在 `warmup()`（预热）里调用。采集主路径不插动作：那里每次多余点击都可能点错控件。

### 5.2 频率与并发（沿用既有结论，别调高）

| 键 | 建议 | 为什么 |
|---|---|---|
| `schedule.interval_minutes` + `jitter_minutes` | 30 + 8 | 16 分钟固定周期、σ<0.4 是最强机器指纹 |
| `crawler.max_concurrency` | 2 | 5 家同秒齐发 = 「同一来源多路机器人」 |
| `crawler.rate.min_gap_s` | 3（qunar 内部另有 8s） | 令牌桶 |
| `crawler.breaker.*` | 300 / 3600 / 900 | 熔断阶梯与登录固定冷却 |
| `schedule.stagger_seconds` | 25 | 同轮各渠道错峰 |

### 5.3 看到验证码怎么办

仓库口径不变：**识别 → 记账 → 停手 → 人工在可见窗口过**（`crawlers/challenge.py` 的处置接缝）。
`riskscore` 只是把「该停多久」量化了（`pause` = 30–60min，`human` = 停手等人工）。

---

## 6. PC/H5 侧的补齐（`crawlers/stealth_ext.py`）

`STEALTH_JS` 已有五面（webdriver/chrome/languages/platform/cores/mem/WebGL/Canvas），
新增的是五个高熵缺口，**拼进同一个 init script**（「stealth 开时恰好 1 个脚本」是既有契约）：

| 补齐项 | 为什么 |
|---|---|
| **WebRTC ICE 候选过滤** | 挂代理时页面能拿到本机 `192.168.x.x`，出口 IP 却在另一个省——这是「代理/多账号」最硬的一条证据。同时加 `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` 从源头掐断 |
| **AudioContext 微扰** | headless 的 `OfflineAudioContext` 输出跨 session 完全一致，是最佳追踪锚点；给 seed 派生的固定微扰 = 「这台假设备」的稳定指纹 |
| **`enumerateDevices`** | headless 常返回 0 个设备，真机至少有一套扬声器/麦克风 |
| **`chrome.app/csi/loadTimes`** | 只有 `{runtime:{}}` 的假对象在 `Object.keys` 下就露 |
| **`screen.orientation` / `outerWidth`** | headless 的 `outerWidth == innerWidth`（没有浏览器边框），真机差 70–90px |
| **native `toString`** | 被 JS 改写的 getter 直接 `toString()` 会打印源码 |

另加一个可选开关：

```yaml
crawler:
  browser_channel: ''    # 空=自带 Chromium；chrome=系统真 Chrome（改了重启生效）
```

自带 Chromium 与真 Chrome 在字体/编解码/`sec-ch-ua` 全版本串上仍有差异，
风控拿「Chromium 特征 + Chrome UA」就能配成一条矛盾。装了 Chrome 就建议开。

---

## 7. 分渠道清单

| 渠道 | 症状 | 本仓库对应手段 | 注意 |
|---|---|---|---|
| **携程 App** | 登录不上/收不到短信 | §2 身份 + §3 隐藏 + §4.3 顺序；`prepare_device` 里的 `cticket/_bfa` | 连续自动化启动/切换会触发环境校验（`docs/APP_CHANNELS.md:37`）。登录窗打开前先让 App 在前台停 30–60s |
| **飞猪 App** | 被风控限流 / 「亲，访问被拒绝」 | §2 §3；飞猪是 Flutter 画布，靠 OCR 取词 | 碰到安全容器页记 `blocked` 停手，**不要连点**（`docs/APP_CHANNELS.md:73`） |
| **去哪儿 App** | 未登录什么都拿不到 | §4.1 退避 + 「设备已登录就不恢复快照」 | 深链 `qunarphone://flight` 可绕首屏登录页 |
| **去哪儿 PC/H5** | 时不时掉登录 | §4.4 预热（判据=风控 cookie）+ 会话年龄看门狗 | 444/202 是软拒，不是「没票」，别记成 empty |
| **同程 App** | 多轮冷启/切渠道后失效 | §4.2 `keep_app_alive` 可试（少冷启） | 裸打 `TT=RT/AD` 恒 444，只对站点自身签名请求生效 |
| **途牛 PC** | 已被风控 | ①降速到 `cadence.tuniu: 45–60`；②`humanize: true`；③必要时切 `m.tuniu.com`（另一套 cookie 家族）；④**别装途牛 App** | 模拟器上途牛 App 的 `libtuniudns.so` 会 SIGSEGV（ARM 转译不兼容），不是登录问题 |

---

## 8. 验收：怎么确认真的生效了

```powershell
# 1) 设备侧（身份 + 隐藏 + 调优 三份报告）
python scripts\yield_report.py --json      # 顺带看设备身份是否已落盘
python -c "from core.android import fingerprint as f, stealth as s; from core.android.device import AdbDevice; d=AdbDevice(r'D:\Program Files\Netease\MuMu\nx_main\adb.exe','127.0.0.1:16384'); print(f.audit(d)['score']); print(s.verify(d))"

# 2) 单测（新增的与既有契约）
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest tests/test_r910_device_identity_stealth.py tests/test_r911_web_stealth_human_risk.py tests/test_r912_yield_tuning_and_pacing.py -q
python -m pytest tests/test_qunar_honesty.py tests/test_stealth_fingerprint_coherence.py tests/test_r394_concurrency_fingerprint.py -q

# 3) 跑一轮完整采集，读日志里的四条线
Select-String -Path logs\monitor.log -Pattern "身份已应用|root/模拟器隐藏|实例调优|风控评分|预热拟人化" | Select-Object -Last 20
```

期望：

- `身份已应用 id-xxxx-00：N 条生效 / M 条失败`，`M` 里只剩 `ro.*`（无 Magisk 时的正常现象）；
- `root/模拟器隐藏：K 条动作，自检 8x 分`；
- `实例调优：动画关 ok，常亮生效 ok`；
- `预热拟人化：移动 3 / 滚动 3 / 6.2s`（humanize 开着才有）；
- `风控评分` 通常不出现；出现就要按档位处理（`slow` 别硬跑，`rotate` 别立刻换）。

---

## 9. 明确不要做的事（仓库既有黑名单，勿重犯）

1. **重试风暴**：唯一能把「限你」升级成「封你」的动作。有退避就用退避。
2. **把换 IP / 住宅代理当常态**：真 429 只占 0.3%，为 0.3% 的问题付 100% 成本；
   国内站配境外出口反而升档。
3. **靠降速解决设备身份命中**：设备规则与频率无关，降速无效，只能改身份。
4. **没验证就写 `ro.product.cpu.abi=arm64-v8a`**：PackageManager 会按 arm64 选 so，
   加固 so 可能直接 ANR 死锁。要写就先跑 `abi_canary.run()` 拿 ok 判定，
   再设 `identity.spoof_abi: auto`（判定 7 天有效）。
5. **每次采集无条件恢复登录快照**：用旧副本盖新会话 = 每轮把用户踢下线。
6. **换身份不清 App 内 `utdid/umid/c_guid` 缓存**：新设备 + 旧 ID，比不换更可疑。
7. **接第三方打码服务**：那等于把账号交给陌生人。简单滑块用 `slider.py` 自己解，
   强人机（极验 v4/天御/baxia/reCAPTCHA/点选/人脸）交人工。
8. **在模拟器上装途牛 App**：`libtuniudns.so` SIGSEGV。
9. **调高并发 / 让 5 家同秒齐发**：2 路是实测较稳的档。
10. **改完就宣布「已经不会被风控」**：风控是动态对抗，验收只看**账本数字**
    （成功率、`login` 次数、`soft_reject` 次数），不看单次是否成功。

---

## 10. 回滚

全部改动都是**开关式**的，任何一项都能单独关：

```yaml
crawler:
  humanize: false          # 关拟人化
  browser_channel: ''      # 回自带 Chromium
  stealth: false           # 关 Web 侧全部注入（含新增扩展片段）
android:
  identity:
    enabled: false         # 关设备身份（不写任何 props）
  stealth:
    enabled: false         # 关 root/模拟器隐藏
  keep_app_alive: false    # 回到每轮冷启
```

彻底恢复模拟器出厂身份：删 `user_data/device/device_identity.json`，
`adb shell` 下手动把 `ro.product.model` 等改回 MuMu 原值（或直接重建模拟器实例），
再 `adb shell rm -f /data/local/tmp/tm_ident_*.ok /data/local/tmp/tm_stealth_*.ok`。
