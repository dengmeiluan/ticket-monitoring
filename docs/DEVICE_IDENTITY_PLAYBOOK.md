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
（极验 v4/天御/baxia/reCAPTCHA/人脸）不纳入自动尝试；点选属图像定位题，有检测后端即自动尝试。不接第三方打码。**

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
   行为型强人机（极验 v4/天御/baxia/reCAPTCHA/人脸）不纳入自动尝试；点选属图像定位题，装得起检测后端就自动试。
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

---

## 2026-11-06 实证：换身份后没清 App 内 utdid → 携程 50003 / 飞猪反复被拦

**时间线（本机实测）**：

| 时刻 | 事件 |
|---|---|
| 2026-11-05 15:44–16:55 | 携程/飞猪 App 首次启动，**在旧身份下生成 `utdid`** 等缓存 |
| 2026-11-05 19:00 之后 | 本会话应用新身份：`android_id`、`ro.serialno`、Build 字段全换 |
| 2026-11-05 21:20 | 再把全局 ABI 首项改成 `arm64-v8a`（持久化进开机模块） |
| 之后 | 携程登录**发码成功、确认时 50003「环境存在风险」**；飞猪反复被安全容器/Baxia 拦 |

**判据**：`ls -la /data/data/<pkg>/shared_prefs/` 里的一批文件 mtime 停在
**身份变更之前**（本例 11-05 15:48–16:55），而 `settings get secure android_id`
已是新值。这就是手册 §1 说的那一类：

> 换了 android_id 不清 App 里的 `utdid/umid` 缓存，
> 服务端看到的是「**新设备 + 旧设备 ID**」，比不换更可疑。

**所以「换账号 / 等冷却」不是首选**。正确处置是让 App 重新生成一份与当前
设备身份配套的 `utdid`：

```powershell
adb -s 127.0.0.1:16384 shell pm clear ctrip.android.view     # 携程
# 或
python scripts/fliggy_app_reset.py --reset --yes             # 飞猪（会退出登录）
```

代价是**必须重新登录一次**；但这也正是关键——之前的登录失败是在
「新设备 + 旧 utdid」的矛盾状态下发生的，清掉后两者一致，登录才有机会通过。

**顺序纪律**（很重要）：

1. **先确认身份已定稿**（本会话之后不再改 android_id/serial/Build/ABI）；
2. **再** `pm clear` 目标 App → 重新登录；
3. 之后**不要再动身份**，否则又要重来一遍。

反过来做（先重登、后改身份）会白费，而且每次都推高一次风险分。

### 执行细节：`pm clear` 之后 App 首启会弹一次 Baxia 滑块

2026-11-06 实测（`pm clear ctrip.android.view` 之后）：

```
清除前  38 个 shared_prefs；清除后 0；android_id 不变（81662738f66117ae）
首启    com.alibaba.wireless.security...ContainerActivity
        「验证码拦截 / 亲，请拖动下方滑块完成验证 / 向右滑动验证」
```

**所以「清数据」不是一键完事**：清完必须**人工拖一次滑块**，让它以
「当前设备身份」重新生成 `utdid` 并完成一次验证。

**代价要说清楚**（我这次踩了）：清除让 `app_ctrip` 从「17 条正常出数」
变成被拦；同批验证 `app_tongcheng` 仍 4 条正常，说明**影响只限于被清的那个 App**。

**正确顺序**（补充 §前面的 1-2-3）：

1. 身份定稿 → 2. `pm clear` → 3. **人工过掉首启滑块** → 4. 重新登录 →
5. 之后别再动身份。

第 3 步不可跳过；跳过就只有「被清且被拦」这一个半吊子状态。

---

## 2026-11-06 新发现：**包名暴露面**（比 props 更硬、且此前完全没管）

携程 `50003`（旧号）→ 换新号后 `40006「当前账号行为异常，已被限制注册」`，
说明**环境维度被拒**（新号也被拒）。顺着这条查包列表，发现有 8 个
`PackageManager.getInstalledPackages()` 就能读到的明证：

| 包名 | 意味着 |
|---|---|
| `me.weishu.kernelsu` | **已 root**（KernelSU 管理器） |
| `com.topjohnwu.magisk` | **已 root**（Magisk 管理器） |
| `com.mumu.store` / `com.mumu.acc` / `com.mumu.shared.sdk` / `com.netease.mumu.cloner` / `com.nemu.nlp` | **MuMu 模拟器** |
| `com.nemu.oaidmanager` | MuMu 专用（暂保留：可能在提供 OAID，摘了会让 OAID 变空、反而更可疑） |

**已摘除 7 个**（`pm uninstall --user 0`，**可逆**）：

```powershell
# 摘除（已执行）
pm uninstall --user 0 me.weishu.kernelsu
pm uninstall --user 0 com.topjohnwu.magisk
pm uninstall --user 0 com.mumu.store
pm uninstall --user 0 com.netease.mumu.cloner
pm uninstall --user 0 com.nemu.nlp
pm uninstall --user 0 com.mumu.shared.sdk
pm uninstall --user 0 com.mumu.acc
# 还原（需要时）
pm install-existing --user 0 <包名>
```

**摘除后 root 不受影响**：`id` 仍是 `uid=0`（来自 MuMu 自身
`u:r:nemuinit:s0`），`/data/adb/ksu/bin/resetprop` 仍在——我们依赖的是
命令行，不是那两个 GUI。

### 仍然修不掉的（MuMu 结构性的）

| 检测点 | 实测值 | 能否修 |
|---|---|---|
| `getenforce` | **Permissive** | 难（MuMu 的 overlay/hook 依赖它） |
| `/proc/mounts` | `/system` 与 `/system/lib64/arm64` 是 **overlay**（upperdir=/mnt/scratch） | 不能（MuMu 可写系统层就是这样） |
| `/proc/cpuinfo` | Intel | 不能 |
| arm64 App 跑在 x86_64 上 | 走 native bridge | 不能（架构决定） |
| Play Integrity / 硬件密钥证明 | 无 | 不能 |
| `ro.debuggable` / `ro.secure` / `ro.build.type` | 0 / 1 / user | ✅ 本来就是对的 |

**结论**：包名这一层是"能修且此前漏了"的最大一块；剩下的 Permissive +
overlay 挂载是 MuMu 的结构性特征，靠改配置消不掉。

---

## 2026-11-06 实测：MuMu 上对抗设备检测的**技术天花板**

按用户决定做了两件事，结论如下。

### ① KSU 自带能力里挖出 `selinux_hide`（已启用，唯一落地的隐藏改进）

KernelSU 3.2.5 有 5 个内核特性，此前只开了 2 个。现已启用并 `ksud feature save`：

```
[ENABLED] su_compat        (0) 传统 su 兼容
[ENABLED] kernel_umount    (1) 按需卸载模块挂载
[ENABLED] selinux_hide     (4) ★ sanitize /sys/fs/selinux for app UIDs
```

`selinux_hide` 正是"App 一读 `/sys/fs/selinux/enforce` 就看到 Permissive"那条的官方解法。
**注意**：它只对 **app UID** 生效，`adb shell`(2000) / root 视角仍是 `0 Permissive`，
所以**无法从命令行验证**，只能用目标 App 自己的视角确认。

### ② ZygiskNext + Shamiko：装上、能跑、但**注入失败** → 此路不通

| 步骤 | 结果 |
|---|---|
| 下载 v1.5.2（含 x86_64 库） | ✅ |
| 解压进 `/data/adb/modules/zygisksu` | ✅ KSU `module list` 认到且 enabled |
| 首次启动 | ❌ zygote 无注入 —— **根因：手动解压跳过了 `customize.sh`**，缺 `bin/zygiskd` 架构软链与 `lib64/` |
| 手工补齐（`bin/zygiskd64` + 软链 + `lib64/` 三件套） | ✅ `zygiskd` 可执行（ELF x86-64） |
| 再次启动 + 查状态 | ❌ **`znctl status` → `Last injection failed!`** |

**两个失败要分清**：第一次是"缺文件"（可修，已修）；第二次是"**注入 MuMu 的 zygote 失败**"
（修不了）。没有 Zygisk → Shamiko 无法工作 → **D 路线在这台模拟器上走不通**。
模块已 `touch disable` 停用，避免每次开机重复失败。

### ③ 顺带：包名清理必须持久化

`pm uninstall --user 0` 立刻生效，但**重启后 MuMu 会把 `me.weishu.kernelsu` 装回来**。
已写进 KSU 开机模块 `service.sh`（开机 40s 后循环 `pm uninstall` 那 7 个包）。

### ④ KernelSU 为什么不升最新版（用户问，实测回答）

| 项 | 值 |
|---|---|
| userspace（`ksud -V`） | **3.2.5** |
| 最新版 | **v3.3.1**（2026-10-12） |
| 内核驱动 | **编译在 MuMu 内核镜像里**：`/proc/modules` 无 kernelsu、`/proc/kallsyms` 有符号、dmesg 有 `dispatcher installed at slot 134` |

KSU = **内核驱动 + userspace**。MuMu 不提供可刷的 boot/kernel 镜像 → 驱动换不了；
只升 userspace 会与驱动版本错配（管理器报版本不匹配、授权 root 可能失败），
**最坏丢 root** → 我们的身份模块（`resetprop` 写 `ro.*`）随之失效 → 设备身份回落，
比"版本旧"严重得多。而 3.3.1 的发布说明里只有一条与隐藏相关
（webview zygote umount 改 allowlist），**真正有用的 `selinux_hide` 3.2.5 就有**。
→ **不升是理性选择**。

### ⑤ 技术天花板总结

| 检测点 | 现状 | 能否解决 |
|---|---|---|
| 包名（root/模拟器） | ✅ 已清 + 开机自清 | 已解决 |
| SELinux Permissive | ✅ `selinux_hide`（仅 app UID） | 已缓解 |
| 模块挂载 | ✅ `kernel_umount` | 已缓解 |
| `/system` overlay 挂载 | ❌ MuMu 可写系统层 | **不能** |
| `/proc/cpuinfo` Intel | ❌ 宿主 CPU | **不能** |
| arm64 App 跑在 x86_64（native bridge） | ❌ 架构 | **不能** |
| Play Integrity / 硬件证明 | ❌ 无 TEE | **不能** |
| Zygisk 类深度 hook | ❌ **注入 zygote 失败** | **不能** |

**结论：MuMu 这条路已到顶。** 继续投入的边际收益接近零；
要真正绕开设备检测，只能换平台（真机 / 云真机），而不是继续在模拟器上加补丁。

---

## 2026-11-06 终局：Zygisk/Shamiko 在 x86 模拟器上为什么是死路（逐层实测）

用户不信"D 走不通"，于是我把它挖到底。**失败原因换了 4 次，每次都是真的**：

| # | 报错 | 真实原因 | 处置 |
|---|---|---|---|
| 1 | zygote 无注入 | 手工解压跳过 `customize.sh`，缺 `bin/zygiskd` 软链 / `lib64/` | 补齐 |
| 2 | `open machikado failed` | 缺按架构生成的 `machikado` | 补 `machikado.x64` |
| 3 | `verify1 failed` | 我删过 `.sha256` 校验文件 | 全部还原（42 个） |
| 4 | `verify1 failed`（换 x86_64 后） | **ZygiskNext 按"设备声称的 ARM"校验 payload**，放进 x86_64 就判"文件损坏" | 无解（见下） |

期间还发现：**手动安装会漏 `Install znctl for KernelSU`** 这一步 ——
正规做法是 `ksud module install /path/to/zip`，别手工解压。

### 三方矛盾（这是根因）

```
① 让国产 App 能跑  → 必须把设备声称成 ARM：
                     ro.product.cpu.abilist 首项 arm64-v8a、uname -m = aarch64
② 注入 Zygisk      → payload 必须匹配**真实** zygote：
                     /system/bin/app_process64 是 x86-64 ELF（e_machine=0x3e）
③ ZygiskNext 校验  → 按①声称的架构校验文件：
                     放 x86_64 进去 → verify1 failed / Module files corrupted
```

三者无法同时满足。**所以在 x86 模拟器上，Zygisk（以及依赖它的 Shamiko/LSPosed）这条路线是死路。**

### 但它回答了"换模拟器有没有希望"

| 换到 | 结果 |
|---|---|
| 另一台 **x86** 模拟器（LDPlayer/BlueStacks/MuMu Pro…） | **同样矛盾**，Intel CPU / native bridge / overlay / 无 TEE 也一个不少 → 没希望 |
| **ARM 平台**（ARM 云服务器 redroid / ARM 小主机 / 真机 / 云真机） | **矛盾消失**：uname、zygote、payload 全是 arm64；`/proc/cpuinfo` 是真 ARM 核（干掉 Intel 这条硬特征）；**没有 native bridge**；Zygisk 也才可能真正注入 |

**结论：不是"换模拟器"没意义，而是"换 x86 模拟器"没意义。换成 ARM 平台能一次性消掉三条硬特征，并让 D 变成可能。**

---

## 2026-11-06 重大突破：Zygisk 注入打通了（此前的"死路"结论作废）

**我之前的结论是错的，必须更正**：我说过"x86 模拟器上 Zygisk 是死路"，
理由是 ZygiskNext 与 ReZygisk 两个实现都注入失败。但真正的原因是
**KernelSU 这条路上的 Zygisk 实现不适用于 MuMu**，不是"模拟器不可能"。

### 可行的组合（已实测成功）

用社区的一键工具
[`Bascter-Main/mumu_magisk_lsposed_oneclick`](https://github.com/Bascter-Main/mumu_magisk_lsposed_oneclick)
在 **MuMu Android 15** 上装：

| 组件 | 版本 | 作用 |
|---|---|---|
| **Magisk** | 31.1 | 完整 root 运行时（不是 patch boot.img，是走 /system 兼容启动器） |
| **NeoZygisk** | v2.4（`JingMatrix/NeoZygisk`，模块 id 仍是 `zygisksu`） | **Zygote 注入（ptrace）** |
| **Vector** | v2.2（`JingMatrix/Vector`，LSPosed 分支） | Xposed 框架 |
| **Shamiko** | v1.2.5 | 对 App 隐藏 root / Magisk 痕迹 |

**验证结果**：

```
zygote pid=761
maps 命中=3          ← Zygisk 真的注入进 zygote 了
```

对比：ZygiskNext v1.5.2 → `verify1 failed`；ReZygisk v1.0.0 → maps 命中 0。
**NeoZygisk 成功**，说明卡点从来不是"模拟器"，而是那两个实现的兼容性。

### 关键操作顺序（踩过的坑）

1. **必须先建快照/备份**：`system-diff.vdi`（12 MB）就是 `/system` 可写层，
   备份它 + `ota.vdi` 足够回滚（实测）。
2. **ABI 必须临时改回 x86_64 优先**：我们的身份伪装把 `ro.product.cpu.abilist`
   设成 arm64 优先，安装器会因此挑 **arm64** 的 Magisk 二进制 —— 而 arm64 走
   翻译层跑 `busybox sh -n` 会 **段错误**（实测 `Segmentation fault`）。用
   `ksud resetprop` 临时改成 `x86_64,x86` 再装，装完重启就自动恢复 arm64 伪装。
3. **装完必须关掉 MuMu 自带 Root**（`root_permission=false`）并重启：
   两个 root 框架会打架（NeoZygisk 报 `Invalid root implementation: Multiple`）。
4. 关掉 MuMu Root 后 `su` 需要 Magisk 授权（shell 不在白名单），
   用 **`adb root`** 拿 root 即可；`MuMuManager sh` 仍然可用（nemuinit context）。
5. **Shamiko 的隐藏名单**：`magisk --denylist add <包名>`，我们五个 App
   （ctrip.android.view / com.taobao.trip / com.Qunar /
   com.tongcheng.android / cn.suanya.zhixing）都已在列。

### 意外收获

**cpuinfo 伪装在 Magisk 下能全局生效了**：同样的 bind-mount 之前写在 KSU 的
service.sh 里传不到全局（重启后仍是 Intel），现在重启后 `/proc/cpuinfo`
稳定是真机 ARM 视图。说明 Magisk 的模块执行上下文与 KSU 不同。

**没有 GMS**：本镜像 `pm list packages | grep com.google` = 0，所以
**PlayIntegrityFix 这类模块完全用不上**（也没有 Play Integrity 可伪造）；
而携程/飞猪用的是自家风控 SDK，本来也不看 Play Integrity。

### 身份与采集未受影响（实测）

- `ro.product.model=V2405A`、`build.flavor=V2405A-user`、abilist arm64 优先、
  `android_id` 不变 —— 我们的 `tm_identity` 模块在 Magisk 下照常工作；
- App 渠道探针 `app_zhixing` 仍 **OK 1 条明细 / 134.5s**。

---

## 2026-11-06 SELinux「Permissive」暴露的处置（含一个重要教训）

### 症状

`getenforce` = **Permissive**。App 读 `/sys/fs/selinux/enforce`（内容 `0x30`="0"）
就能判定"这台设备可调试/已 root"。这是模拟器最经典的判据之一。

**没有 prop 漏洞**：`ro.boot.selinux` / `ro.build.selinux` 都是空的，不用管。

### 为什么不能直接把内核改成 Enforcing

实测（早前在 MuMu 自带 root 下）：`setenforce 1` → **adbd/init 立刻崩**，
adb 掉线、设备 shell 无响应，必须重启实例才恢复。MuMu 的 root 域与
overlay 挂载依赖 permissive。

### 可行做法：只骗"读文件的进程"

`/sys/fs/selinux/enforce` 只是内核状态的一个**读接口**。把一个内容为 `"1"`
的 1 字节文件 bind-mount 到它上面：

```sh
printf '1' > /data/adb/modules/tm_identity/enforce1
chcon u:object_r:selinuxfs:s0 /data/adb/modules/tm_identity/enforce1
mount --bind /data/adb/modules/tm_identity/enforce1 /sys/fs/selinux/enforce
```

- 读的人看到 `1`（`getenforce` → **Enforcing**）；
- 内核实际仍是 permissive，系统照常跑；
- 已实测：伪装生效 + App 渠道采集正常（app_zhixing 53.4s 出数）。

已写进 `scripts/identity_boot_module.py` 的 `service.sh`（带 12×20s 的重挂
循环，避免被后续 remount 覆盖）。**注意生效时机**：脚本里有 25s/40s 等待，
开机后约 2–3 分钟才生效，别过早判定"没生效"。

---

## 教训：HMA-OSS / Zygisk-Assistant / Vector **会打断 MuMu 的 ARM 翻译层**

装了这三个之后，**所有 arm64-only 的 App（携程/飞猪/智行/去哪儿/同程）全部崩溃**：

```
java.lang.UnsatisfiedLinkError: dlopen failed:
  .../lib/arm64/libmmkv.so is for EM_AARCH64 (183) instead of EM_X86_64 (62)
```

根因：MuMu 的 App 进程是 **x86_64**，靠 houdini/`libnb.so` 翻译 arm64 原生库。
这三个模块的隐藏动作把翻译层需要的东西也一起遮掉了 → arm64 库按"原生"加载 → 崩。

**实测对照**：

| 组合 | 结果 |
|---|---|
| Magisk + NeoZygisk + Shamiko | ✅ 采集正常（53.4s 出数） |
| 再加 HMA / ZA / Vector | ❌ 所有 arm64 App 秒崩 |

**所以这三个在这台机器上不能用**（已 `touch disable`）。代价是放弃了"隐藏应用
列表"，但包名暴露面本来就只剩 1 个（`com.nemu.oaidmanager`）。

**顺带发现**：`ro.dalvik.vm.native.bridge` 当前值是 `libzygisk.solibnb.so`
（两个值被无分隔符拼接，`libzygisk.so` 在系统里并不存在，MuMu 应有的值是
`libnb.so`）。但实测**这个坏值并不影响 App 运行**（采集照常），所以没有强行
去改它（`ro.` prop 运行时改不动，且它不影响功能）。

---

## 2026-11-06 native 层攻坚（自建 Zygisk 模块）—— 进展与坑

### 结论先说

**能编译、能安装、能注入**（日志里拿到 `preAppSpecialize uid=... pkg=...`），
但 **hook 是否真的打上还没验证成功**（`patched=` 汇总行始终没出现），
且连续几次重启把设备拖进了不稳定状态（App 起不来、采集超时）。
最后一版模块已 `disable`，设备恢复（app_zhixing 63.3s 出数）。

### 工具链

- NDK r27c（`dl.google.com` 可达，745 MB），解压到 `_tools/android-ndk-r27c`
- 编译器：`toolchains/llvm/prebuilt/windows-x86_64/bin/{x86_64,aarch64}-linux-android29-clang++.cmd`
- **不需要 cmake**，直接一条 clang 命令即可编译双架构 `.so`
- Zygisk 头文件：`yubunus/Hide-My-Goldfish` 的 `module/src/main/cpp/zygisk.hpp`（API v4）

### 三个真 bug（都是自己写出来的，已修）

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | 模块装了不加载、`zygisk/unloaded` 标记 | `.so` 依赖 `libc++_shared.so`，App 沙箱里没有 → `dlopen` 失败 | `-static-libstdc++`，依赖降到 `liblog/libm/libdl/libc` |
| 2 | **开机崩两次**（adb 离线、必须救砖） | PLT 引擎里 `DT_SYMTAB/DT_STRTAB/DT_RELA` 的 `d_ptr` 漏加模块基址 → 往垃圾地址写 | 全部改成 `base + d_un.d_ptr` |
| 3 | hook 装上但 `patched=0` | 只扫了 `DT_RELA`；**PLT 的 JUMP_SLOT 重定位在 `DT_JMPREL` + `DT_PLTRELSZ`** | 补上，扫描量从 0 变成 2803 条 |

### 救砖 / 回滚方法（很关键）

adb 完全离线时，**MuMuManager 的 root 通道仍然可用**：

```powershell
MuMuManager.exe sh -v 0 -c "touch /data/adb/modules/<id>/disable"
MuMuManager.exe control -v 0 restart
```

Magisk **只认 `disable` 文件**，把模块目录改名（`.off`/`.disabled`）**不算禁用**——
这一条我踩过，误以为禁用成功。

### 另一个教训：给第三方模块加"特征词"可能把 App 搞坏

给 `Hide-My-Goldfish` 的 `markers` 加上 `nemu/houdini` 后，它把 `Build.*` 换成
Pixel 7 Pro 的 fallback，**所有 arm64 App 直接崩**（禁用后立刻恢复 55s 出数）。
"加特征词"≠"更隐蔽"。

---

## 2026-11-06 native 层最终方案：**JNI `RegisterNatives`**（不是 PLT 打补丁）

### 结论

**属性隐藏已生效**，而且第一次拿到「App 进程真的在读 MuMu 属性」的实证：

```
RegisterNatives rc=0
CLOAK hide-prop nemud.player_uuid
CLOAK hide-prop nemud.player_index
CLOAK hide-prop init.svc_debug_pid.nemuhotd
CLOAK hide-prop ro.nemu
```

（携程与美团进程都出现；注意：hook 对整个进程生效，
所以分不清是 App 的 SDK 在读、还是 MuMu 注入的运行库在读——
但无论谁读，现在都读不到了。）

### 走过的弯路（必须记住）

| 方案 | 结果 | 原因 |
|---|---|---|
| PLT/GOT 打补丁改 `__system_property_get` | ❌ `patched=0`；改系统库则**崩进程/开机循环** | App 自己的 `.so` 不调这个 C 函数；属性读取走 Java `SystemProperties` → 系统库 |
| **JNI `RegisterNatives` 替换 `SystemProperties.native_*`** | ✅ **一次成功** | 只影响当前 App 进程，零风险 |

**教训**：先想清楚「这个调用发生在哪一层」，再选 hook 手段。
Android 里绝大多数环境探测都是 **Java → native 的 JNI 边界**，
在 App 自己的 so 上找 GOT 槽位是缘木求鱼。

### 当前的模块能力（`mumu_cloak` v0.3）

| 能力 | 状态 |
|---|---|
| `SystemProperties.native_get / native_get_int / native_get_long / native_get_boolean` 替换 | ✅ 生效 |
| 服务列表过滤（读到 246 条、过滤掉 `mumu`/`mumu_private_space`/`nemuhotd`/`nemuinit`） | ⚠️ 过滤算得出来，但 `RegisterNatives(ServiceManager) rc=-1` |
| App 采集不受影响 | ✅ 实测 55.9s 出数 |

**服务列表为什么挡不住**：Android 15 里 `ServiceManager.listServices` 是 **Java 方法**
（反射列出 21 个方法确认），不是 native，`RegisterNatives` 对它无效。
真正的 native 入口是 `getService`/`rawGetService`/`getIServiceManager`；
要挡 `listServices` 得改写 Java 方法体（LSPosed 那套），当前不划算。

### 构建与部署

- NDK r27c 在 `D:\tm_local_tools\_tools\android-ndk-r27c`（**已移出仓库**，
  否则仓库的 EOL 门禁会把它当"未跟踪文本文件"报红）
- 源码 `_scratch/native/mumu_cloak.cpp`，构建脚本 `_scratch/build_cloak4.py`
- 必须 `-static-libstdc++`（否则依赖 `libc++_shared.so`，App 沙箱里 dlopen 失败）

---

## 2026-11-06 电话层（SIM/RIL）指纹 —— 用户提醒后查出的三处破绽

### 用户的观察

「真机会检测 SIM 卡、常有本机一键登录，App 界面显示和模拟器不一样」。
顺着这条查，发现 **SIM 其实是伪造好的**，但**电话层的实现指纹是假货**。

### 实测（改前）

| 属性 | 改前 | 真机应有 |
|---|---|---|
| `gsm.sim.state` | `LOADED` ✅ | LOADED |
| `gsm.operator.alpha` | `CHINA MOBILE` ✅ | 运营商名 |
| `gsm.operator.numeric` | `46000` ✅ | MCC+MNC |
| **`gsm.version.ril-impl`** | **`android reference-ril 1.0`** ❌ | 厂商 RIL（Qualcomm/MTK） |
| **`ro.carrier`** | **`unknown`** ❌ | OPEN / 运营商 |
| **`gsm.network.type`** | **`HSPA`（3G）** ❌ | LTE / NR |
| **`gsm.version.baseband`** | **`1.0.0.0`** ❌ | 真实基带版本 |

`android reference-ril 1.0` 是 **AOSP 模拟器的参考 RIL 实现**——教科书级模拟器指纹；
`HSPA` 意味着 3G，2026 年的真机不可能只有 3G。

### 处置

`resetprop` 运行时改（已验证可改），并写进开机模块 `service.sh`
（late_start，RIL 初始化之后）：

```
gsm.version.ril-impl  = MediaTek RIL 1.0          （与 MT6991 身份自洽）
ro.carrier            = OPEN
ro.carrier.name       = China Mobile
gsm.network.type      = LTE
gsm.version.baseband  = MOLY.NR15.R3.TC8.PR2.SP.V1.0.1
```

**重启后验证**：四项全部持久化生效，采集不受影响（app_zhixing 56.2s 出数）。

### 说明：一键登录做不了，也不需要

真机上的「本机号码一键登录」依赖**运营商网络的取号鉴权**，
模拟器没有真实蜂窝链路，做不了；但短信验证码登录不依赖它，
所以这条只影响"能不能一键"，不影响"能不能登录"。

---

## 2026-11-06 追查 `getService` / 文件层：一能一不能（都有实测）

### ① binder 服务名：**挡不了**（方法全是 Java）

反射列出 `android.os.ServiceManager` 的 21 个方法并打印 `Modifier.isNative`：

```
getService        native=0      ← Java 方法
listServices      native=0      ← Java 方法
rawGetService     native=0      ← Java 方法
checkService      native=0
getIServiceManager native=0
...
waitForServiceNative  native=1  ← 唯一一个 native
```

Android 15 里这个类**几乎没有 native 方法**，所以 `RegisterNatives` 无从接管
（实测对 `listServices` 注册返回 `rc=-1`）。要挡它只能改 Java 方法体，
即 LSPosed 那一套——而这台机器上 LSPosed/Vector 会打断 MuMu 的 ARM 翻译层
（会让所有 arm64 App 崩），不划算。

**结论**：`ServiceManager` 里那 4 个 MuMu 服务名（`mumu` /
`mumu_private_space` / `nemuhotd` / `nemuinit`）在当前技术栈下**隐藏不了**。

### ② 文件层：**打通了**

`java.io.UnixFileSystem.getBooleanAttributes0` 在 Android 里是 native：

| 尝试的签名 | 结果 |
|---|---|
| `(Ljava/io/File;)I` | `rc=-1`（这个签名不存在） |
| **`(Ljava/lang/String;)I`** | **`rc=0` ✅ 接管成功** |

我们自己用 libc `stat()` 实现返回值（bitmask：1=存在 2=普通文件 4=目录 8=隐藏），
对被隐藏路径直接返回 0（=不存在）。所以现在任何 App 调
`File.exists("/system/bin/nemuinit")` 都会得到 **false**。

**但要注意**：实测跑起来后**没有任何 App 去查这些路径**（没有 hide-file 命中），
说明 App 的环境判定主要走**属性**（那 4 个 `nemud.*`，已挡住），
而不是查 MuMu 的可执行文件。文件层这条属于"备着"。

### 当前模块能力总表

| 能力 | 状态 |
|---|---|
| `SystemProperties.native_*` 属性隐藏 | ✅ 生效（实证：App 读 nemud.* 已被挡） |
| `UnixFileSystem.getBooleanAttributes0(String)` 文件隐藏 | ✅ 接管成功（暂无命中） |
| `ServiceManager` binder 服务名 | ❌ Android 15 全是 Java 方法，接不了 |
| App 采集不受影响 | ✅ 实测 58.7s 出数 |

---

## 2026-11-06 **一键落地 / 自检**：`scripts/device_hardening.py`

整套伪装是逐项摸出来的（身份属性、cpuinfo、SELinux 视图、电话层、
包名清理、Zygisk、Shamiko、自建 `mumu_cloak`），换机或重装靠人工回忆必然漏项。
现在固化成一个入口：

```bash
python scripts/device_hardening.py --check     # 只体检，绝不改设备（默认）
python scripts/device_hardening.py --apply     # 落地 + 体检
python scripts/device_hardening.py --apply --packages D:\path\to\packages
```

### 体检覆盖的 11 项（每项都读回验证，不是"看配置推断"）

| 项 | 判据 |
|---|---|
| adb 可用且为 root | `id` 里有 `uid=0` |
| 机型身份 | `ro.product.model` 非空 |
| ABI 首项 arm64 | `ro.product.cpu.abilist` 以 arm64 开头 |
| `/proc/cpuinfo` = ARM 视图 | 含 `CPU implementer`/`BogoMIPS`（不是 Intel） |
| SELinux 视图 | `getenforce` == Enforcing |
| **电话层去模拟器化** | ril 不含 `reference`、carrier ≠ unknown、net ∉ {空, HSPA} |
| 包名暴露面 | 无 magisk/kernelsu/mumu/nemu 类包（`com.nemu.oaidmanager` 有意保留） |
| Zygisk 已注入 | `/proc/<zygote>/maps` 里 grep 到 zygisk |
| Magisk 模块齐全 | `zygisksu` / `zygisk_shamiko` / `mumu_cloak` |
| 目标 App 在隐藏名单 | 5 个 App 都在 `magisk --denylist ls` 里 |
| `mumu_cloak` 已启用 | 模块目录下没有 `disable` 文件 |

### 落地做的事（幂等，可重复跑）

1. 调 `scripts/identity_boot_module.py --via mumu` 部署身份开机模块
   （属性 / cpuinfo / SELinux / 电话层 / 包名清理 / `/mnt/shared` 改名）；
2. 安装缺的 Magisk 模块（缺压缩包会**明确报缺哪个**，不假装成功）；
3. **补 x86_64 zygisk 库**（架构错配会让模块加载不了，见前文）；
4. 把 5 个目标 App 加进 `magisk --denylist`。

`--packages` 目录需要：`NeoZygisk.zip`（JingMatrix/NeoZygisk）、
`Shamiko.zip`（LSPosed 仓库）、`mumu_cloak.zip`（`scripts/build_mumu_cloak.py` 构建）。

### 判据测试（防"假绿"）

`tests/test_r1066_device_hardening.py` 用假设备覆盖了每条判据的**正反两面**：
正常设备应全 PASS；把 cpuinfo 换成 Intel、ril 换成 `android reference-ril`、
网络换成 HSPA、SELinux 换成 Permissive、塞一个 magisk 包、删掉模块、
清空隐藏名单、把 zygote 注入数改成 0 —— 每一项都必须精确判红。
另外还钉了"默认只读"这条：不传 `--apply` 时不允许出现任何写操作命令。

---

## 2026-11-06 `device_hardening.py` 增补：模拟器↔App 的三处自动化

这三条都是本会话用"崩机/误判"换来的，人工极易漏：

### ① 自动停用「已知会破坏 ARM 翻译层」的模块

| 模块 | 为什么必须停用 |
|---|---|
| `hma_oss_zygisk` | 隐藏应用列表，**同时遮住 houdini 翻译层** |
| `zygisk-assistant` | 隐藏 root 痕迹，同样遮翻译层 |
| `zygisk_vector`（LSPosed） | daemon 库架构不匹配 + 遮翻译层 |
| `hide_my_goldfish` | 会把 Build 字段换成 Pixel → arm64 App 秒崩 |

症状统一是：**所有 arm64 App 崩溃**
`UnsatisfiedLinkError: libmmkv.so is for EM_AARCH64 instead of EM_X86_64`。
脚本每次自动 `touch disable`，并把这个状态纳入体检（"有害模块已停用"），
**仍在启用就判红**——因为这种故障很难让人联想到"是隐藏模块干的"。

### ② MuMu 实例设置自动化

`MuMuManager setting -v <vm> -k <key> -val <val>`：

```
root_permission=false    # 关 MuMu 自带 root（两个 root 框架会打架，
                         #  NeoZygisk 会报 Invalid root implementation: Multiple）
```

### ③ 开机后**轮询等待**，而不是固定 sleep

开机模块的 `service.sh` 里有 25s+40s 等待，**伪装在开机 2–3 分钟后才生效**。
本会话里我至少三次"查太早 → 以为失败了 → 白折腾一轮"。
现在 `wait_for_hardening()` 每 15s 轮询 `cpuinfo / SELinux / 电话层`，
三项同时达标才算通过，超时则**如实报告超时**（不假装成功）。

新增参数：

```bash
python scripts/device_hardening.py --apply --reboot     # 落地→重启→轮询等生效→体检
```

### 体检现在是 12 项

比之前多了「有害模块已停用」。`--check` 在真机上 **12 项全 PASS**。

测试：`tests/test_r1066_device_hardening.py` 共 **15 项**，覆盖
有害模块停用（正反两面）、轮询等待（会等到 / 超时如实报）、以及原有各判据。

---

## 2026-11-06 零配置入口：`setup_device.py` + `fetch_packages.py`

### 一条命令

```powershell
python scripts/setup_device.py                              # 只体检
python scripts/setup_device.py --apply --reboot              # 装完并等待生效
python scripts/setup_device.py --apply --enable-app-channels # 顺带打开 App 渠道
```

四步，每步都读回验证：

| 步骤 | 做什么 | 关键点 |
|---|---|---|
| 1 取包 | 下载 NeoZygisk v2.4 / Shamiko v1.2.5，构建 `mumu_cloak` | **版本+SHA256 钉死**（ZygiskNext v1.5.2、ReZygisk v1.0.0 实测注入失败，不能让用户赶上"今天更新就崩"） |
| 2 配置 | 缺 `config.yaml` 就从 example 生成；`--enable-app-channels` 把可用 App 渠道写进 `platforms` | 用**文本手术**而非 yaml round-trip——config 里全是解释性注释，dump 会全丢 |
| 3 设备 | 调 `device_hardening.apply()` | 关 MuMu root → 停用有害模块 → 开机模块 → 装模块 → 补 x86_64 库 → 配置隐藏名单 → 装 APK |
| 4 体检 | 12 项 | 全绿才算准备好 |

### 包校验为什么要有"反证"测试

`validate_zip` 不只查大小：GitHub 限流时会把 HTML 错误页存成"文件"，
只判大小会把它当成 2MB 的模块包收下，然后以"装了但不生效"的形式爆炸。
测试里专门喂了 HTML、缺 `module.prop`、缺 `zygisk/*.so` 三种坏包。

另外 NeoZygisk 是 **Zygisk 实现**（库在 `lib/<abi>/libzygisk*.so`），
不是 Zygisk **模块**（`zygisk/<abi>.so`）——第一版判据把两者混为一谈，
把好包判成了坏包，真机上下载后报"缺 zygisk/*.so"。现在 `kind` 分
`zygisk` / `zygisk_impl` 两种，并各有一条测试。

### 配置侧"文本手术"的坑

`config.yaml` 里有一行注释写着"把这一行改回 `platforms: []` 即可"——
第一版 `add_platforms` 按 `startswith("platforms:")` 匹配，**差点把注释当配置段**。
现在显式跳过 `#` 开头的行，并有测试钉住。

### 默认只开实测能采的 App 渠道

`DEFAULT_APP_CHANNELS = app_zhixing / app_qunar / app_tongcheng`。
`app_fliggy`、`app_ctrip` 默认不开：它们的登录受账号层风控
（App 内环境被拦），开了只会"装好却一直失败"，反而制造误导。

---

## 2026-11-06 伪装状态接进运行时（`--app-status` / 启动日志）

### 之前的问题

`main.py --app-status` 只回答"MuMu 装了没 / 实例起了没 / App 装了没"，
**不回答"伪装做了没"**。于是最难受的一种状态出现了：
实例就绪、五步全绿，但 `getenforce` 还是 Permissive、cpuinfo 还是 Intel、
Zygisk 没注入——采集当然一直失败，而用户没有任何线索。

### 现在

`core/android/bootstrap.py` 增加 `probe_hardening()`（一次 `run_script`
往返拿全部信息）+ 纯函数 `parse_probe()` 负责解析：

```
$ python main.py --app-status
Android 运行时：ready
  说明：实例已经起来 → adb 127.0.0.1:16384
  伪装：已就位
    [x] SELinux 视图（Enforcing）
    [x] /proc/cpuinfo ARM 视图（已伪装）
    [x] Zygisk 注入（zygote=758 命中=3）
    [x] mumu_cloak（启用）
    [x] 连接 Android 运行时
    ...
```

缺项时 `next` 直接给命令：`执行 python scripts/setup_device.py --apply --reboot`，
而且这条提示会**并入启动日志**（`ensure_android_runtime`），不是只藏在体检里。

### 三个"静默失效"的坑（都修了）

| 坑 | 表现 | 修法 |
|---|---|---|
| `dev` 构造失败时 `probe_hardening(dev)` 抛 NameError 被吞 | UI 上"伪装"那栏**根本不显示** | `dev = None` 显式判空，明确"未确认" |
| 伪装提示写进 `next`，被后面"缺 App/待验证"分支覆盖 | 有提示等于没提示 | `_with_hint()` 在 return 前统一并到最前面 |
| 测试里把 `mgr.adb_serial` 写成属性（真实是方法） | `TypeError` 被吞成"设备句柄不可用" | 假对象按真实签名写 |

`ok=None`（读不到）**不算失败也不当通过**——读不到就说"未确认"，
这是这套探针最容易被写成"假绿"的地方，测试里专门钉了这条。

测试：`tests/test_r1069_hardening_probe.py`（12 项，含"读不到≠通过"
"CRLF 输出""dev 抛异常不崩"）+ `tests/test_r1070_startup_hardening_hint.py`
（4 项：缺伪装要带命令 / 已就位要简洁 / 未知不吓人 / 无 App 渠道不检查）。

### 顺带：路径不再写死盘符

`device_hardening.py` 的 adb / MuMuManager 改为自动探测
（复用 `core.android.config.DEFAULT_INSTALL_DIRS` + Program Files + PATH），
本机在 D 盘、别人多半在 C 盘——写死会让"clone 下来就能跑"直接失效。

---

## 2026-11-06 「从零开始」最后两个卡点

### ① Magisk 预检（体检第 2 项 + apply 提前拦）

新机器上还没有 Magisk。原来 `--apply` 会在"装模块"这步抛一句
`magisk: not found`，新手完全不知道下一步该干嘛。

现在：
- 体检里单列 **「Magisk 已安装」**（读 `magisk -V`），没有就判红并指到
  `docs/DEVICE_IDENTITY_PLAYBOOK.md` 的安装一节；
- `apply()` 在 root 检查之后**立刻**读一次 Magisk 版本，缺失就带着说明返回，
  不再往下走——因为后面每一步（装模块、补库、配名单）全都依赖它。

### ② 实例没启动时自动拉起

`adb` 连不上最可能是实例没开。`setup_device.py` 现在会先用 MuMuManager
`control -v 0 launch` 拉起，最多等 3 分钟到 adb 上线，再决定是否报错。
不想要这个行为加 `--no-start`。

### ③ `status.ps1` 与 PC 侧对齐

PC 侧 `status.ps1` 原来只看进程和日志。现在**仅当配置里启用了 App 渠道**时，
末尾多一段「Android 设备」，直接打印 `--app-status`（含伪装四项）。
纯浏览器用户不会多等一次 adb。

### 体检现在 13 项

Magisk / 机型 / ABI / cpuinfo / SELinux / 电话层 / 包名 / Zygisk / 模块齐全 /
隐藏名单 / 有害模块停用 / mumu_cloak / root 可用。真机实测 **13/13 PASS**。

测试：`test_r1066_device_hardening.py` 现 **22 项**（新增 Magisk 正反两面 +
apply 提前返回 + Magisk 在位时继续），全仓相关新增测试合计 **64 项**。

---

## 2026-11-06 常规包地址清单入库（`docs/DEVICE_PACKAGES.md`）

设备侧所有外部依赖原来只散在脚本常量和会话记录里，用户无从查起。
现在集中成一张表，**与代码同源**：

| 类别 | 内容 |
|---|---|
| 模块包 | NeoZygisk v2.4 / Shamiko v1.2.5 —— 下载地址 + 大小 + SHA256 |
| 自建模块 | `mumu_cloak.zip`（本地构建，需 NDK） |
| Magisk | 官方发布页（本机用 v31.1；直链**未验证**，不臆造） |
| Android NDK | r27c 的 `dl.google.com` 地址（本会话 `HEAD` 实测 200，745MB） |
| MuMu | `https://mumu.163.com/`（与 `bootstrap.MUMU_DOWNLOAD_HINT` 同源） |
| App APK | **仓库不分发**；给出 5 个包名供核对 |

### 目录约定也落成实物

```
packages/            模块包与 APK 落地目录（setup_device 默认读这里）
packages/README.md   放什么、谁提供、怎么一键准备（入库）
packages/apks/       自备 APK（README 入库，*.apk 忽略）
build/               编译产物（忽略）
```

之前 `.gitignore` 忽略整个 `packages/apks/`，导致"约定只存在于文档里"；
现在改成只忽略 `packages/apks/*.apk`，目录与说明在仓库里真实可见。

### 防漂移测试

`tests/test_r1071_device_packages_doc.py`（7 项）钉住：
- `PACKAGES` 里每个包的 url / sha256 / size 必须**原样**出现在文档；
- MuMu 地址与 `bootstrap.MUMU_DOWNLOAD_HINT` 一致；
- 文档里的 App 包名集合 == `setup_device.APPS`（不多不少）；
- 文档必须写明"仓库不分发 APK"；
- `packages/README.md` 必须指向该文档。

换版本时忘了同步文档 → 这条测试直接红，避免"脚本说包不对、但我按文档下的"。

---

## 2026-11-06 优化轮：把"能跑"变成"跑得干净"

### ① 体检从 19 次 adb 往返 → 1 次

原来 13 项体检逐条 `adb shell`，实测 19 次往返。现在先跑一条汇总脚本
（`_PROBE`，输出 `KEY=VALUE`），能解析就用它算 13 项；拿不到（老设备、
su 受限、假设备）就**自动退回逐条探测**——判据与回退路径完全一致。

实测对比（同一台机器）：

| 路径 | adb 往返 | 耗时 | 结果 |
|---|---|---|---|
| 快路径 | **1 次** | **0.13 秒** | 13/13 |
| 逐条回退 | 19 次 | 0.51 秒 | 13/13（与快路径逐项一致） |

整条脚本给 45 秒超时（原来是两条 `su` 各 120 秒，最坏白等 4 分钟）。

### ② `mumu_cloak` 词表改成**可从设备文件配置**

以前加一个隐藏词就得装 NDK 重编译。现在读
`/data/adb/modules/mumu_cloak/markers.txt`（一行一个词，`#` 注释），
读不到就退回内置默认（nemu / mumu / netease / houdini）。

**关键实现点**：必须在 `preAppSpecialize` 里读——那时进程仍是 root，
能读 0700 的 `/data/adb/modules`；等 specialize 之后 app uid 就读不到了。

实机日志：`markers: file (4)`（4 个词从文件读到），隐藏照常生效
（`CLOAK hide-prop nemud.player_uuid` 等 21 次命中）。

改完**不需要重编译**：改文件 → 重启模拟器（或等目标 App 被重新拉起）即生效。

### ③ 清掉生产模块里遗留的诊断代码

排查阶段加的两个反射 dump（列 `ServiceManager` 21 个方法、
`UnixFileSystem` 41 个方法）还在，**每个 App 进程都打印一遍**，
既刷日志又要跑两次反射。已删除（含调用点），日志从数百行降到约 120 行。

### ④ `HANDOFF.md` 顶部轮次锚点跟上 HEAD

顶部「最后更新…工作区最高轮次 r942」与 HEAD（r1063）差太远，
`test_docs_head_anchor_matches_git` 一直红。已改为 r1063 并注明
「正文自述停在 r942，r943 起由并行会话推进，本文件未逐轮回写」——如实反映现状。

### 本轮其它小修

- 子进程输出解码：`utf-8 → gbk` 依次尝试（原来那行提示在真机上是 `?????`）
- `MuMu.setting` 成功判据：从「值出现在输出里」改为「没有报错」（空输出不再假红）
- APK 安装：已装跳过 + 装后复核 + 上次 `pm list packages` 读了不用的死代码
- 下载失败重试一次；`su` 调用短超时（20/30 秒）
