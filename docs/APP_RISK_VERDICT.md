# App 侧风控最终结论（携程 50003 / 飞猪自重启）

日期：2026-11-08 · 依据：两台不同模拟器设备的实测对照

## 一、两次对照实验（同一账号、同一出口 IP）

| 维度 | Android 15 台（实例 0） | Android 12 台（实例 1） |
|---|---|---|
| 机型指纹 | Xiaomi 14 / SM8650 / Xiaomi 23127PN0CC | Samsung SM-A5260 / Android 12 |
| 设备身份 | 一套（IMEI/序列号/AndroidID 已对齐） | **另一套全新** |
| root 状态 | ❌ 藏不住（镜像 native-bridge v2 vs 系统 v3 → Zygisk 全灭） | ✅ **真的藏住了**（`magiskhide=1`，App mountinfo 里 `magisk / /data/adb` 均 0 行） |
| Zygisk / 模块 | 全灭（Shamiko/Vector/HMA/goldfish 都不跑） | ✅ Magisk Kitsune + NeoZygisk + Vector + HMA 全在跑 |
| 携程登录 | **50003** | **50003** |
| 飞猪机票页 | 弹 NC 滑块，人手拖也 `error…` | **一点查询就程序退出** |

## 二、结论（逐条对应证据）

1. **账号不是原因**：用户用同一账号在 PC 浏览器正常登录；我们的浏览器通路也能出数。
2. **IP 不是原因**：同一 IP 下浏览器正常；Android 12 上携程**匿名可浏览一段时间**。
3. **设备指纹不是（唯一）原因**：换到完全不同的机型/系统/身份，结果一样（50003）。
4. **`50003` 的实质**：携程对「账号 × 设备」这一对做画像。只要设备在风控眼里
   仍属"异常设备类"（x86 + ARM 翻译层的模拟器），登录环节就拒。
   **换设备身份 ≠ 换设备类别**——这是关键区别。
5. **飞猪"一点就重启"**：不是崩溃（无 tombstone、无 SIGSEGV），是 App **主动退出**
   ——阿里检测到环境异常后自杀，比弹滑块更硬的处置。

## 三、我们试过、且确认无效的方案（省得再试）

| 方案 | 结果 |
|---|---|
| 设备身份全面对齐（机型/SoC/GPU/电池/传感器/市场名） | 通过一致性审计（仅剩 x86 ABI 一处），**仍 50003** |
| 隐藏 maps 里的 `houdini/nemu`（LD_PRELOAD 符号插桩，Android 15 实测生效：App 自视角归零） | 有效但**让 App 启动不稳定**；且只影响"读 maps"这一路 |
| 隐藏 root 痕迹（`su`/`magisk`/`/data/adb`） | Android 15：LD_PRELOAD 可藏；Android 12：MagiskHide 真藏住 → **仍 50003** |
| seccomp 系统调用代理（自己写的 Zygisk 模块，只拦 `openat` 洗 maps） | 过滤器能装、能跑，**App 立刻主动退出**（疑似检测 `Seccomp:` 字段） |
| 换 Zygisk 提供者（NeoZygisk v2.4 / Zygisk Next v1.5.3） | Android 15 上均无法注入（native-bridge API v2 vs v3，镜像缺陷） |
| 换 Android 版本（12） | Zygisk 生态可用、root 真藏住，**但 50003 不变** |

**唯一没排除的变量：ARM 翻译层（`libhoudini.so` / `libnb.so`）——真机没有它。**
在模拟器上想擦掉它，只能改 App 读 maps 的结果；而我们两次实测都表明：
**一改，风控 App 就主动退出**。

## 四、因此的采集策略（当前生效）

**浏览器通路是主力**（今天实测全部出数）：

```
fliggy   PC  26s  rows=1   sjipiao.fliggy.com 国际列表
ctrip    PC  14s  rows=1   flights.ctrip.com 国际列表
tongcheng PC  0s  rows=1   同程低价日历 90 天窗口
tuniu    PC  21s  rows=1   国际列表接口
```

* 订阅已加 `ctrip`（此前漏订阅，实测它现在能匿名出数）；
* App 通路（app_zhixing / app_fliggy / app_qunar / app_ctrip）保留为 best-effort：
  能出数就采，被登录墙/风控拦住时按"通路停服/需登录"记账，**不再为它牺牲稳定性**；
* 登录：`渠道健康 → 渠道登录` 的**双端槽位**（携程/飞猪/同程/途牛 各 PC+H5 九格），
  登录态失效时面板会显示「需登录 · 去登录」，且 `session` 字段会给出"能用多久"。

## 五、如果一定要 App 侧数据

只剩两条路，且都不是软件能解决的：

1. **真机**（唯一没有翻译层的方案）——把本仓的工具链迁过去即可：
   `core.android.align`（身份对齐）、`core.android.consistency`（审计）、
   `tm_identity` 模块、`core.android.hide`（隐藏层体检）。
2. **云真机/设备池**（同性质，按小时计费）。

## 六、日常验收命令

```bash
python -m core.setup_check                 # 装机自检（含「设备环境」「运行实例」）
python -m core.android.hide status         # 隐藏层：模块开关 / DenyList / 注入点
python -m core.android.consistency         # 设备脸自洽审计（改身份后必跑）
python -m core.live_check                  # 线上抽查：版本/槽位/session/why/降级
python -m core.session_window              # 登录后"能用多久"曲线
```

## 七之补：**首页显示已登录 ≠ 搜索可用**（2026-11-09 设备实证）

用户反馈"App 三家已经登录了，但面板没变"。我们用项目自己的设备层 dump 了四家首页：

```
app_zhixing  首页有「会员」        → 已登录
app_ctrip    首页有「会员 / 积分」  → 已登录
app_qunar    首页无登录/会员标记    → 未判定
app_fliggy   dump 仅 1755 字       → 页面没渲染出来（与"一点就重启"一致）
```

但携程 App **一进入航班搜索**，屏幕上出现的是（失败瞬间的 dump，已落盘
`user_data/app_ctrip/app_login_fail_20261109_113852_航班明细.xml`）：

```
遇到问题 | 手机验证码登录 | 未注册手机验证后即可完成注册
+86 | 请输入手机号 | 获取验证码 | 账号密码登录 | 境外手机密码登录
```

**结论**：

1. 携程 App 在**搜索环节**强制再做一次「手机验证码登录」，与首页会员态无关；
2. 这一步正是 `50003 / errorap9U8` 出现的地方——账号×设备在这一刻被判风险；
3. 因此"首页已登录"不能作为 App 通道可用的判据；账本记 `login` 是对的，
   **不是我们误判**；
4. 想在模拟器上过这一步 = 要在搜索弹出的登录页里完成手机+短信验证，
   且仍要面对 50003 的评分——这就是 `docs/APP_RISK_VERDICT.md` 早就写下的天花板。

**给运维的正确操作**：点「去验证」后，不要停在首页，要**跟着搜索流程走到
"手机验证码登录"页再登录**；登录成功后关闭面板（现在关窗即保存）。
