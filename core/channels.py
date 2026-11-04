# -*- coding: utf-8 -*-
"""渠道清单的**零依赖单一事实源**。

为什么单独一个模块：
- `crawlers/__init__.py` 要 import 各 crawler，而那些 crawler 又 import
  core 的模块（models/pacing/…）。若 core 反过来 import crawlers 取
  App 渠道清单，就会 `core → crawlers → core` 循环导入。
- 于是这个清单曾在 `crawlers/__init__.py`、`core/pacing.py`、
  `core/health_diag.py` 各写一份。加第二个 App 渠道时必须三处同改，
  漏一处就是「渠道能采但不在节流表里 / 不进诊断卡」的静默缺陷。

本模块只放常量，不 import 任何项目内模块，因此谁都可以安全引用。
新增 App 渠道时**只改这里**（外加 REGISTRY 注册与 crawler 实现）。
"""
from __future__ import annotations

# 浏览器渠道（Playwright）
BROWSER_CHANNELS = ("ctrip", "fliggy", "qunar", "tongcheng", "tuniu")

# App 渠道（Android 模拟器 + adb）：需 android.enabled 且用户 platforms
# 显式列出才会被实例化。
APP_CHANNELS = ("app_zhixing", "app_qunar", "app_fliggy",
                "app_ctrip", "app_tongcheng")

# 显示名（中文）。App 渠道必须在这里，否则界面会露出裸 id（app_zhixing）。
CHANNEL_CN = {
    "ctrip": "携程", "qunar": "去哪儿", "fliggy": "飞猪",
    "tongcheng": "同程", "tuniu": "途牛",
    "app_zhixing": "智行 App", "app_qunar": "去哪儿 App",
    "app_fliggy": "飞猪 App",
    "app_ctrip": "携程 App", "app_tongcheng": "同程 App",
}


def plat_cn(p: str) -> str:
    """渠道 id → 显示名；未知渠道原样返回。"""
    return CHANNEL_CN.get(p) or p


# ---------------------------------------------------------------- 维度矩阵
#
# 用户要求「App 渠道信息更全，但 PC/H5 已有的**每个维度**都要对齐」。要能
# 核查这件事，能力就必须是**声明式的**（照 `specials.SPECIAL_CAPABILITY`
# 的先例），而不是散在代码里的 if。取值只允许三种，别的一律当没说过：
#
#   "y" 现役支持（有真机/真请求验证过）
#   "n" 明确不支持（会显式记 unsupported，绝不静默返回别的口径）
#   ""  尚未验证（**不得**当成支持；界面/文档都要按未知对待）
#
# 新增维度或渠道时只改这里；`tests/test_r677_channel_dimension_matrix.py`
# 会把「App 渠道必须与它的浏览器同名渠道逐维对齐」钉成门禁。
DIMENSIONS = ("domestic", "intl", "calendar", "detail", "round_trip",
              "multi_city", "low_fare")

CHANNEL_DIMENSIONS = {
    # 浏览器五家。**逐项按代码证据填**，不按"看起来应该支持"填：
    #   round_trip: **按「真取到过渠道自算的往返总价」判 y，不是按参数判**。
    #               fliggy = y（仅国际）：cheapestCalendar 收
    #               tripType=1+backDate，返回行自带 backDate 且与请求回程日
    #               同值；国内列表页只有单程，已加闸门。
    #               tuniu = y（r769 国内 `listFlight` 两段 fare 即往返总价；
    #               r927 国际 H5 `queryFlight` 两段 segment 的
    #               productList.avgTotalPrice 即页面「往返 含税」，35 条
    #               ¥3010）。国内/国际都只采渠道总价，不做两段单程相加。
    #               ctrip / qunar / tongcheng = y（均按渠道自算的往返总价
    #               实测）：ctrip `round-…&containstax=1` 直出往返卡
    #               （国内「往返总价」/国际「往返含税价」）；qunar touch
    #               往返页去程卡给「往返总价 ¥N 起」（国际 H5 双列表
    #               1999/空栏，未出数）；tongcheng `book1/roundtrips`
    #               国内 atp 组合总价；国际登录后 book1 RT 页的
    #               `ts/list` 直出 tp 含税总价（2026-11-03 实测）。
    #               三家都只采渠道总价，未做两段单程相加。
    #   multi_city: ctrip PC **2 段已验证出数**（y，scope=仅 2 段）：配置卡/
    #               轮尾采集/概览整单卡/整单提醒/整单历史/CSV 导出，页面自报
    #               整单含税价，生产行 ¥1476（IJ004+MM304）；3+ 段实测无组合
    #               卡；缺口程 2 段实测有整单（¥2184，9C8515+MM079），慢页
    #               以「多程含税价」为就绪锚轮询。其余九家仍 ""（入口在、
    #               采集端未接）。
    #               不把"我们没做"伪装成"渠道没有"，也不把"仅 2 段"写成"全段支持"。
    #   low_fare:   **九家都有发现源**（10 家中飞猪 App 明确暂无可用源；
    #               r805z 三方对照 + 后续渠道核过）——来源以
    #               `core/specials.py::SPECIAL_CAPABILITY` 为单一事实源：
    #               ctrip 主题榜+低价日历 / qunar 官方 H5 低价日历 /
    #               fliggy PC 特价榜 / tongcheng H5 低价日历(90-180天) /
    #               tuniu 特价榜单 / 四个 App 真机「低价机票」
    #               （智行/去哪儿/携程/同程）。飞猪 App 在源表里是
    #               `sources=[]`，矩阵记空——两条表必须同口径。
    #               旧注释写「只有 qunar 与 fliggy」是过期结论（该表当时
    #               还没收敛），与矩阵取值自相矛盾。
    "ctrip":     {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "y", "low_fare": "y"},
    "qunar":     {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "", "low_fare": "y"},
    "fliggy":    {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "", "low_fare": "y"},
    "tongcheng": {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "", "low_fare": "y"},
    #   round_trip: r900 起显式 unsupported（与 ctrip 同律）→ 曾收敛为 n；
    #              r769 实测发现国内**接口原生支持**往返（两段 segment 的
    #              返回价即往返总价，判据见上），已接线 → 国内 y。
    #              国际 productList 是单段结构、未做两段实测 → 国际 unsupported。
    #   calendar: 途牛**有**官方 H5 单航线日历（r916 纠偏）——
    #             `crawlers/special.py::fetch_tuniu_calendar` 调
    #             `flight-api.tuniu.com/query/flight/v1/calendar`（type=1），
    #             与页面点日期控件同一 XHR；2026-11-03 真实 H5 搜索流
    #             点「查询/日历」后返回 125 个逐日价
    #             （2026-11-03..2027-08-25，¥360–1790，11-05 ¥420，裸价
    #             不含税）。r805z 只扫了 `crawlers/tuniu.py` 才误记 n；
    #             现在 `TuniuCrawler.calendar()` 复用同一接口并写
    #             `日历/calendar` 账本，特价雷达 `tuniucal` 源同源。
    #             国际该接口无日历，`DIMENSION_SCOPE` 记「仅国内」。
    "tuniu":     {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "", "low_fare": "y"},
    # App 渠道（同 APP_PLAT_NAME 里的名字；与对应浏览器渠道逐项可比）
    #   intl: 两个 App 都有独立的国际档（智行「国际」标签页 / 去哪儿城市页
    #         「国际」tab + 搜索框），均已在真机跑通（2026-10-30）：
    #         智行 浦东→成田 日历价 + 7 条明细；去哪儿 浦东→成田
    #         11-20/11-24 各 4/3 条真实航班，与国内同一条链路。
    #   low_fare: 去哪儿 App「低价机票」已接成特价发现源（真机 14 天
    #             窗口，每天一条最低价，含税·未减优惠）；智行 App 的
    #             「特价」档 2026-10-31 真机实测确认**也是逐天报价**
    #             （首页「特价」页签 → 设城市 + 日期区间 → 「搜索特价」→
    #             结果页 `02.16 周二 ¥1646` 逐天列出），已按同一 low_fare
    #             契约接入。此前记的「目的地低价榜、口径对不上」是把首页
    #             「省钱攻略」的推荐卡当成了「特价」档，**该结论已更正**。
    #   round_trip: 智行 App 真机 2026-10-31 跑通（去程/返程双列 + 往返
    #             总价；总价只在左列，右列是返程加价）。解析器
    #             `crawlers/app_zhixing_roundtrip.py`，门禁
    #             `tests/test_r700_zhixing_round_trip.py`；去哪儿 App 同日
    #             真机跑通（单程/往返/多程三档 → 左右双列 + 页脚「往返
    #             价格」，逐张去程读页脚拿真实总价，938/941/967 三组）。
    #             解析器 `crawlers/app_qunar_roundtrip.py`，门禁
    #             `tests/test_r701_qunar_round_trip.py`。
    "app_zhixing": {"domestic": "y", "intl": "y", "calendar": "y",
                    "detail": "y", "round_trip": "y", "multi_city": "",
                    "low_fare": "y"},
    #   calendar（app_qunar）: y（2026-11-02 真机、已登录）：低价机票页顶部
    #     6 天日期条带逐日价；点「日历」后整月（2026-11、2026-12、2027-01）
    #     每天都有 ¥ 价。`AppQunarCrawler.low_fare` 原生解析实测 BJS→SHA
    #     14 天 ¥408/359/…（41.2s，path low-fare ok），日历价与低价页同源。
    #   low_fare（app_qunar）: y（同上）：登录后「搜索低价机票」落
    #     QReactNativeActivity1 原生 RN 页，不是 H5 WebView；H5 分支仅在
    #     异常转场时兜底并记 unsupported。
    "app_qunar":   {"domestic": "y", "intl": "y", "calendar": "y",
                    "detail": "y", "round_trip": "y", "multi_city": "",
                    "low_fare": "y"},
    # 携程 App（2026-11-02 真机）：国内列表未登录可出完整明细，列表是
    # React Native 无障碍树（第XXX航班… 字段），解析器与采集器已落地；
    # 修复到达城市页「选择目的地」判据后连续两次端到端跑通
    # （SHA→CAN 11-18 32 行 ¥480 / 11-19 33 行 ¥490），domestic/detail 升 y。
    # 日历日格是自绘 View、dump 无文本；截图经 Windows OCR 可读逐日价，
    # 2026-11-02 真机 calendar() 连续两次 SHA→PEK 61 天 ¥380–420
    # （23:20/23:39，OCR 3.7/3.8s，全程 37.3/20.2s，app-calendar ok），
    # calendar/low_fare 升 y。
    # 国际档（2026-11-02/03 真机）：城市页「国际/中国港澳台」+ 中文搜索已通，
    # SHA→NRT 价格日历连续两次 54/53 天有价（11-03..12-26，¥864–1530；
    # 11-10 页面显示「查价」不计价，OCR 3.8/4.0s）；国际单程明细真机
    # 38 条、最低 ¥935（11-19，42.8s，列表不暴露航班号）。
    # 往返（2026-11-03 真机国际+国内）：双日期弹层 + 去/返双栏，去程卡价
    # 即页脚「往返总价」（点第 2 条去程后 2146→2189 实证）；SHA→NRT
    # 11-22/25 8 条 ¥2146，SHA→PEK 11-22/25 5 条 ¥760（返程 14:00→16:30
    # +¥0）；返程卡可能晚一帧渲染，解析前等 10s。
    "app_ctrip":  {"domestic": "y", "intl": "y", "calendar": "y",
                   "detail": "y", "round_trip": "y", "multi_city": "",
                   "low_fare": "y"},
    # 同程 App（2026-11-02 真机）：原生表单/城市/日历 + WebView 结果页；
    # CLI dump 卡 idle，用 uiautomator2 回退读到 6 行明细（SHA→PEK
    # 2026-11-16，MU5185 ¥336/¥373）。2026-11-03 国际价格日历真机
    # SHA→NRT 连续两次 14 天 ¥882–1495（app-calendar ok）；国际只走
    # 日历（两月视野）；国际单程明细真机 6 条 ¥875（11-16，7.9s）。
    # 国际往返（2026-11-03 真机）：双日期范围日历 + 去/返双栏，去程行
    # 「含税总价」即页面往返总价（上海⇌东京 11-16/19，7 条去程、最低
    # 9C8515 ¥2209，返程 9C6218 +¥0；返程栏 `+¥N` 是加价，不相加）。
    # 旧结论「查询落营销/示例页」是首访教学浮层遮挡导致的误判。
    # 国内往返另有边界（2026-11-03 真机）：国内档可填返程位、日期弹层也
    # 是同一范围日历（页脚 ￥785），但查询后落**单程去程列表**（¥774 起、
    # 无返程栏/无往返总价），不是往返总价页——国内往返未接，拿不到渠道
    # 自算总价就不产出，绝不把单程列表价当往返价。
    "app_tongcheng": {"domestic": "y", "intl": "y", "calendar": "y",
                      "detail": "y", "round_trip": "y", "multi_city": "",
                      "low_fare": "y"},
    # 飞猪 App（2026-11-02 真机）：Flutter 画布 + Windows OCR；
    # 固定竖屏后首页→机票→表单→城市/日期→结果页全链路连续两次跑通
    # （BJS→SHA 11-16 / SHA→PEK 11-17，各 3 行）。只做国内单程；
    # 日历只用于选日、不单独落价；国际/往返/多程/低价源未接。
    "app_fliggy": {"domestic": "y", "intl": "", "calendar": "",
                   "detail": "y", "round_trip": "", "multi_city": "",
                   "low_fare": ""},
}

# App 渠道与哪个浏览器渠道**同源**（产地/账号体系）。这只是「谁和谁是
# 同一家」，**不是**对齐基准——用它判对齐会自证：携程自己 round_trip=n，
# 于是「智行 <-> 携程」永远算不出往返缺口，可网页端飞猪/同程明明支持。
APP_BROWSER_PEER = {
    "app_zhixing": "ctrip",     # 智行 = 携程系 App
    "app_qunar": "qunar",       # 去哪儿 App
    "app_fliggy": "fliggy",     # 飞猪 App
    "app_ctrip": "ctrip",       # 携程 App
    "app_tongcheng": "tongcheng",  # 同程 App
}


def dim_state(plat: str, dim: str) -> str:
    """渠道在某维度上的声明（"y"/"n"/""）；未声明的渠道一律返回 ""。"""
    return (CHANNEL_DIMENSIONS.get(plat) or {}).get(dim, "")


# ---------------------------------------------------------------- 端面（PC/H5）
#
# 用户原话要求「PC 和 H5 两端都要重点检查」。只按维度表态是不够的：
# 同一家渠道常常**只有一端能真出数**，而矩阵一格看不见这件事。
#
# 取值沿用同一套三态语义：
#   "y" 该端有通路且**账本里真出过数**
#   "n" 该端没有可用通路（停服 / 未实现），会显式落账而不是静默降级
#   ""  未验证（不得当成支持）
#
# 依据（2026-11-01 账本普查，`fetch_paths` 按端面聚合）：
#   ctrip   PC 28 次/出数 27/3639 行；H5 20 次/出数 20/765 行 → 两端都有
#   qunar   H5 49 次/出数 46/3217 行；**PC 无任何记录**，代码注释记明
#           「PC 版单程列表 2026-10-10 起已停服，仅保留显式复活探测」→ pc=n
#   fliggy  PC 43 次/出数 37/3153 行；H5 2026-11-01 r795 走**真实入口**
#           `FliggyCrawler.fetch`（PC 段人为留空以触发兜底）实测出数：
#           `path='H5' status='ok' rows=1`（SHA→CAN 9C8929 ¥400）。
#           但这是**探针**拿到的 `c.paths`，没进生产库 ——
#           `test_declared_y_surface_has_ledger_evidence` 只认 `fetch_paths`
#           表，所以本表仍保持 ""，等生产跑出第一轮再改。
#           （探针跑通≠可以写 y：这条门禁就是防"凭感觉写声明"。）
#           **H5 长期 0 行不是"这条通路不存在"**：是表单操作与风控识别
#           三处 bug（r794）叠加 mtop 限流（RGV587「被挤爆啦,请稍后重试」；
#           r795 冷却 50 分钟后同一请求 4 条响应全 SUCCESS 并出数——
#           之前那条 blocked 是我探测过密自己打爆的配额，不是验证墙）。
#           限流记 soft_reject（等一会自愈）、验证墙才记 blocked（要人
#           去看），两者不许混，否则用户会被引导去解一个不存在的验证。
#   tongcheng 国内 **PC 已接通（r805，2026-10-31 实测）**：新增
#           `_fetch_pc_dom`，开 `www.ly.com/flights/itinerary/oneway/…`
#           收站点自己发的 `getflightlist`。旧结论「国内没有 PC 实现」
#           来自 `docs/LESSONS.md` 的「无头下列表**卡片**不渲染」——那
#           说的是渲染层（虚拟列表），接口一直是好的（debug/tc_pc_list.json
#           那份 14 条就是接口原文）。真浏览器实测：页面 200、返回 64 条
#           航班、页面可见价与 `productPrices` 逐条相等（515/515、
#           650/650，cot=40 不进价）。端到端跑通：13.7s、rows=64、
#           最低 ¥493、path 落 `PC` 且 `mobile:false`。
#           两个坑：(a) 必须临时切**桌面身份**——手机 UA 打 PC 站会被
#           按移动端渲染、不发 getflightlist；(b) 记账要在切档期间做，
#           否则 `mobile` 标志会把桌面通路标成手机。
#           → **2026-11-01 17:45 生产首条 PC 出数**（换了含 PC 通路的进程、
#           且监控里有了国内航线上海→海口）：账本
#           `PC ok SHA→HAK 2027-01-29 rows=5`，日志
#           「[tongcheng][pc] 2027-01-29 明细 5 条 · 最低 ￥2110」→ 记 y。
#           此前「探针出数但账本 0 条」保持 "" 的那段时间是对的：
#           探针跑通≠生产在跑，写成 y 会让读者以为定时任务在用这条端面。
#   tuniu   H5/API 41 次/出数 34/3171 行（48h 账本）。PC **有实现**
#           （`_fetch_pc_dom` 抓 domestic/list 的 SSR items，解析契约也已
#           修好：到达时刻 `+0/+1` 跨天后缀），但**生产账本里一条 `PC`
#           记录都没有**（48h 全表核对：只有 `H5/API`）。
#           r796 探针直接调 `_fetch_pc_dom` 连测两次都落在滑块验证页
#           （`path='PC' blocked`，url 是真实列表页）——但那是探针内的
#           `c.paths`，没进库，所以**不能**说「生产里被风控挡着」。
#           **2026-11-01 20:42/20:46 生产已跑过两次**（SHA→HAK 01-29/01-30），
#           账本都是 `PC blocked`、note「人机验证页（滑块），需在渠道登录
#           窗口完成验证」——所以事实更新为：代码在、通路被滑块拦住、要人工
#           过一次验证。仍记 ""（测不出），但悬停文案必须写清「不是没实现」。
#           与同程的区别：同程当初是没有代码，途牛是代码在、被风控拦住。
#
# 只对**浏览器渠道**有意义：App 渠道没有 PC/H5 端面之分。
CHANNEL_SURFACES = {
    "ctrip":     {"pc": "y", "h5": "y"},
    "qunar":     {"pc": "n", "h5": "y"},
    "fliggy":    {"pc": "y", "h5": ""},
    "tongcheng": {"pc": "y",  "h5": "y"},
    "tuniu":     {"pc": "",  "h5": "y"},
}
SURFACES = ("pc", "h5")

# 端面格子的**人话说明**（悬停用）。声明是 y/n/"" 三态，但读者要能分清
# 「这个端根本没做」和「做了但被风控挡住/没验证过」——两者在格子里都不是
# y，混在一起会把一次风控拦截读成产品缺失。文案跟声明同源，改声明时一起改。
SURFACE_NOTES = {
    ("ctrip", "pc"): "H5 页的 XHR 拦截，桌面试口",
    ("ctrip", "h5"): "H5 页的 XHR 拦截，移动视口",
    ("qunar", "pc"): "PC 版单程列表 2026-10-10 起已停服（302 回促销聚合），只留显式复活探测",
    ("qunar", "h5"): "m.flight 列表页，登录态出全量明细",
    ("fliggy", "pc"): "sjipiao.fliggy.com SSR 直读",
    ("fliggy", "h5"): "淘宝 H5 会话（market.m.taobao.com）走 mtop listingsearch；"
                      "2026-11-02 00:45 直接调用 H5 采集器真实出数"
                      "（SHA→CAN ¥400 / 9C8929，17.9s，账本外探针），"
                      "通路本身已验证可用；当前 RGV587 限流、生产账本暂无"
                      " H5 ok（定时任务走 PC 主路）——矩阵记未验证，"
                      "不是渠道没有",
    ("tongcheng", "pc"): "www.ly.com 列表页的 getflightlist（需切桌面身份）；"
                         "2026-11-01 17:45 生产首条 PC 出数（SHA→HAK 5 条/¥2110）",
    ("tongcheng", "h5"): "m.ly.com/ft/touch/book1，XHR 拦截；"
                         "2026-10-31~11-01 生产 35 次 ok / 1224 行，"
                         "最近一次 11-01 17:07；2026-11-03 手工 UI 复验"
                         "国内/国际价格日历可用；定时任务近期走 PC/窗历，"
                         "H5 不按天跑，端面记已验证（近 30 天账本口径），"
                         "不是渠道没有",
    ("tuniu", "pc"): "flight.tuniu.com/domestic/list 的 SSR 列表；通路已实现，"
                     "不是没有做。2026-11-01 20:42/20:46 生产被滑块拦住"
                     "（账本 blocked）；2026-11-02 03:55 窗口显示已登录列表、"
                     "无滑块，但 03:58 保存会话后真机重取仍 blocked。"
                     "2026-11-02 06:40 用户实测：重新搜索时滑块出现，"
                     "人工通过后仍搜不到数据（站点软风控/空结果）。"
                     "生产从未有 PC ok，矩阵记未验证（不是渠道没有）；"
                     "PC 只查今天起 30 天内，远日期直接走 H5/API（降低软风控）；"
                     "H5/API 仍是当前可信出数通路",
    ("tuniu", "h5"): "listFlight 接口（两段 segment 支持国内往返）",
}


def surface_state(plat: str, surface: str) -> str:
    """渠道在某端面的声明（"y"/"n"/""）；无声明一律 ""。"""
    return (CHANNEL_SURFACES.get(plat) or {}).get(surface, "")


# 维度格子的**分域说明**（悬停用）。声明是 y/n/"" 三态，但同一格里
# 「国内有明细、国际只有日历价」这类差异表达不了——读者看到 intl=y
# 会以为国际也能出航班级明细。文案跟声明同源，改声明时一起改。
#
# 依据（r805ad，账本全历史，统计「带起降时刻的真实航班元素」）：
#   ctrip 765/3829 · qunar 1569/1766 · fliggy 533/2674
#   tongcheng **481/0** · tuniu 77/2956 · app_zhixing 80/100
#   app_qunar 45/**0**
# 同程与去哪儿 App 的国际端只有日历价（tongcheng 全走 `窗历`，
# source=tc_window_calendar；app_qunar 国际样本 0 行），所以 intl 记 y
# （确实有国际报价）但要点明「仅日历价，无航班号/机型」。
DIMENSION_NOTES = {
    ("tongcheng", "intl"): "国际只走「窗历」（日历族）：出的是逐日最低价，"
                           "没有航班号/机型/时刻（日历本身不含航班级信息）",
    ("tuniu", "intl"): "国际走 H5/API（`m.tuniu.com/flight/` 页内切国际）："
                       "2026-11-01 账本 H5/API 32 次 ok、2985 行；PC 有实现但"
                       "被滑块拦住，按「测不出」记空，不记 n。远期日期查询受限，"
                       ">30 天优先走 H5/API",
    ("app_qunar", "intl"): "国际列表卡带航班号/时刻/价格（2026-11-01 实测 "
                           "CA847 ¥3305 / MU213 / BA168）；国际没有独立日历通路",
    ("app_qunar", "round_trip"): "国内往返真机跑通（左右两列去/返 + 页脚往返"
                                 "总价）；国际档设了返程日仍出单程列表"
                                 "（2026-11-01 实测），国际往返不产出",
    # n 的往返格必须写清「为什么」，否则矩阵只显示「不支持」，读者会以为
    # 渠道没有这个产品——携程明明有往返，是**结果页不给往返总价**。
    # 项目红线：不许把两段单程价相加冒充往返总价（与渠道自算口径不同，
    # 混进同一池子会让走势图出现凭空的价差）。
    ("ctrip", "round_trip"): "国内/国际同一 PC 入口：`online/list/round-"
                             "…&containstax=1` 直出产品往返总价卡片"
                             "（国际写「往返含税价」、国内写「往返总价」；"
                             "2026-11-02 实测上海→东京 6 条 ¥2404…¥2682、"
                             "上海→北京 6 条 ¥1002…¥1049）。只采渠道自己的"
                             "往返组合总价，未做两段单程相加；H5 `adate` "
                             "结果页仍只有去程一列，不走那条",
    ("qunar", "round_trip"): "国内 touch 往返页去程卡直接给产品「往返"
                             "总价 ¥N 起」（2026-11-02 实测 北京→上海 "
                             "¥808…¥2546，71 条）；返程卡的「补 ¥N」是"
                             "加价，不落；国际往返匿名请求返回 1999 软拒"
                             "（2026-11-03，touchDoubleInnerList data=null、"
                             "页面 ¥0 空栏），带产品档案走同一 H5 双列表"
                             "也未解析到往返总价（26s），仍显式拒绝，"
                             "矩阵 y 指国内。未做两段单程相加",
    ("tongcheng", "round_trip"): "国内往返走 frbook1 的 book1/roundtrips"
                                 "（atp 组合总价，2026-11-02 真报文 210/210）；"
                                 "国际往返走登录档案下 book1 RT 页的 "
                                 "miflightapi/ts/list：每条 res 的 tp 是"
                                 "「含税总价」，lng 带去/返两段（2026-11-03 "
                                 "真机 SHA→HKG 11-20/23，41 条、最低 "
                                 "HX231+HX0234 ¥1463）。只采渠道总价，"
                                 "不做两段单程相加；国际未登录会跳 passport，"
                                 "如实记 login",
    # 多程同理：浏览器站点**产品上都有**多程入口，是采集端没做（选多段 →
    # 逐段出价 → 合并口径是一整条独立链路）。写 n 不解释，读者会以为
    # 渠道没有多程产品。
    ("ctrip", "multi_city"): "站点有多程入口；2 段已生产验证（¥1476，"
                             "IJ004+MM304）——配置卡/轮尾采集/概览/来源/提醒/"
                             "历史/CSV 齐全，矩阵 ✓ 仅 2 段；缺口程 2 段已实测"
                             "整单 ¥2184（9C8515+MM079）；3+ 段实测无组合卡，"
                             "不是渠道没有",
    ("qunar", "multi_city"): "站点有多程入口；采集端未实现，矩阵记未验证，"
                             "不是渠道没有",
    ("fliggy", "multi_city"): "站点有多程入口；采集端未实现，矩阵记未验证，"
                              "不是渠道没有",
    ("tongcheng", "multi_city"): "站点有多程入口；采集端未实现，矩阵记未验证，"
                                 "不是渠道没有",
    ("tuniu", "multi_city"): "站点有多程入口；采集端未实现，矩阵记未验证，"
                             "不是渠道没有",
    ("app_zhixing", "multi_city"): "App 采集端未接多程；矩阵记未验证，"
                                   "不是渠道没有",
    ("app_qunar", "multi_city"): "App 有「单程/往返/多程」三档入口；采集端"
                                 "只接了前两档，矩阵记未验证，不是渠道没有",
    ("tuniu", "calendar"): "官方 H5 单航线日历（与页面点日期控件同一 "
                           "`query/flight/v1/calendar` XHR）；2026-11-03 "
                           "H5 选上海→北京后点 `.date-selector`，页面真实 "
                           "XHR 即此端点（type=1），弹层逐日价 11-03 ¥1680 / "
                           "11-04 ¥420 / 11-05 ¥430 / 11-06 ¥699 / "
                           "11-07 ¥410…；另一次搜索流实测 125 个逐日价"
                           "（2026-11-03..2027-08-25，¥360–1790，11-05 ¥420），"
                           "裸价不含税；特价雷达 `tuniucal` 同源。PC 入口"
                           "2026-11-03 探针弹滑块（未绕过），故日历证据"
                           "取 H5 官方接口，PC 端面仍记未验证；国际该接口"
                           "无日历，矩阵 y 指国内",
    ("tongcheng", "calendar"): "窗历 `queryCalendarLowestPrice`（一次 90/180 天，"
                               "含税总价）；2026-11-03 H5 点日期控件复验："
                               "页面 XHR `mihawkapi/calendar/lowestPrice` 与"
                               "采集端窗历返回同一批 180 天逐日价（11-03 ¥520 /"
                               "11-04 ¥350 / 11-05 ¥360…），同源可溯源；"
                               "国际同样：SHA→BKK 11-04 ¥1102 / 11-05 ¥1156 /"
                               "11-06 ¥1169 / 11-07 ¥883 / 11-08 ¥715，与采集端"
                               " 90 天窗历逐日一致；`ts/calendar` 需页内签名，"
                               "仅作详情/国际备选",
    ("qunar", "detail"): "有航班号/时刻/价格；机型与舱位覆盖率低"
                         "（机型 17%、舱位 1%），不是每家都带",
    ("fliggy", "detail"): "PC 列表有完整航班号/时刻；国际日历行无航班号"
                          "（日历结构性无航班级信息，不是解析漏项）",
    ("app_qunar", "calendar"): "登录后「低价机票」→「日历」：整月"
                               "（2026-11/2026-12…）每天都有 ¥ 价；"
                               "日格 `content-desc=q_flight_calendarDayItem#"
                               "YYYY-MM-DD`，子树内含价格，`parse_full_calendar`"
                               " 按日期精确解析并写 `path_note(\"日历\","
                               "\"calendar\")`（2026-11-02 真机 BJS→SHA "
                               "一次 60 天/2 个月，2026-11-02..12-31）。"
                               "**不使用顶部 6 天/14 天日期带冒充日历**",
    ("app_qunar", "low_fare"): "登录后点「搜索低价机票」落原生 RN 页"
                               "（QReactNativeActivity1），不是 H5 WebView；"
                               "真机 2026-11-02 BJS→SHA 14 天逐日最低价"
                               "¥408/359/450…（41.2s，path low-fare ok）。"
                               "H5 WebView 分支仅在异常转场时兜底并记 "
                               "unsupported，不拿 timeout 冒充风控/无航班",
    ("app_zhixing", "low_fare"): "App「特价」页按请求**驱动**航线与日期区间后逐天报价"                                 "（真机 2026-11-02：北京→广州 11/10-12 三天 ¥520、"
                                 "上海→新加坡三天 ¥843/843/743；同一表单再跑 18s）。"
                                 "驱动覆盖：出发单选弹层、到达多选弹层（先清旧 chip）、"
                                 "区间长日历（月份标题+日格，向下翻更早月份）。"
                                 "仍是发现源：每天一条最低价、无航班号；驱动失败或"
                                 "日期不在特价窗口时记空并写明原因，不拿旧页面报价冒充",
    ("app_ctrip", "domestic"): "2026-11-02 真机：修复到达城市页标题判据"
                                "（「选择目的地」）后，SHA→CAN 连续两次："
                                "11-18 32 行 ¥480/79.8s、11-19 33 行 ¥490/71.3s；"
                                "此前 SHA→PEK 也已连续两次 31 行",
    ("app_ctrip", "detail"): "结果列表字段齐全：航班号/时刻/机场/航司/价格；"
                             "解析器只认 `第XXX航班出发时间/到达时间/价格/"
                             "机场/航司`；修复城市页判据后连续两次 32/33 行复验",
    ("app_ctrip", "intl"): "国际档价格日历连续两次 SHA→NRT 54/53 天"
                           " ¥864–1530（OCR 3.8/4.0s；11-10 页面「查价」"
                           "不计价）；国际单程明细真机 38 条、最低 ¥935"
                           "（11-19，42.8s；列表不暴露航班号，不编造）；"
                           "日历两月视野，12-27 之后未滚动",
    ("app_ctrip", "calendar"): "2026-11-02 真机 calendar() 连续两次 SHA→PEK "
                               "61 天（11-03..次年 01-02，¥380–420；23:20/23:39，"
                               "OCR 3.7/3.8s，全程 37.3/20.2s，"
                               "`app-calendar ok`）；日格自绘、dump 无文本，"
                               "价格由 Windows OCR 截图解析"
                               "（`app_ctrip_calendar.py`）",
    ("app_ctrip", "low_fare"): "价格日历即逐日最低价源，已接特价雷达 "
                               "`_app_ctrip_deals`；页面未标含税/优惠口径，"
                               "雷达行标「口径未标注」，不假设含税；"
                               "覆盖今天起 62 天",
    ("app_ctrip", "round_trip"): "国内/国际往返真机端到端：去程卡价即页脚"
                                 "「往返总价」（点第 2 条去程后页脚 "
                                 "2146→2189 实证）；国际 SHA→NRT "
                                 "11-22/25 8 条 ¥2146，国内 SHA→PEK "
                                 "11-22/25 5 条 ¥760（返程 14:00→16:30 "
                                 "+¥0）；返程小卡是差价，绝不相加",
    ("app_ctrip", "multi_city"): "App 有多程入口；采集端未实现，矩阵记未验证，"
                                 "不是渠道没有",
    ("app_tongcheng", "domestic"): "2026-11-02 干净表单真机 SHA→PEK "
                                   "2026-11-16 6 行（MU5185 ¥336/¥373、5.9s）；"
                                   "城市页支持中文搜索（海口实测可选）；"
                                   "连续复用/状态漂移后城市位可能打不开，"
                                   "生产启用前先单跑复验；>60 天交浏览器 H5/PC",
    ("app_tongcheng", "detail"): "国内/国际单程明细均已覆盖：结果页 "
                                 "WebView 经 uiautomator2 读取，航班号/航司/"
                                 "时刻/机场/舱位/机型/价格齐全；国内已验证"
                                 "近期热门城市，国际 SHA→NRT 11-16 真机 6 条、"
                                 "最低 ¥875（7.9s，实付价取最低）；"
                                 "远期日期交浏览器",
    ("app_tongcheng", "intl"): "国际档价格日历连续两次 14 天 ¥882–1495"
                               "（`app-calendar ok`，1.7/2.1s）；国际单程明细"
                               "真机 6 条、最低 ¥875（7.9s；实付价取最低，"
                               "保留划线列表价）；国际往返见 round_trip",
    ("app_tongcheng", "calendar"): "2026-11-02 真机 SHA→PEK 打开日期弹层，"
                                   "一次读到 2026-11/12 两月逐日价"
                                   "（日格 content-desc `5\\n¥360`）；"
                                   "`calendar()`/`low_fare()` 已接同一数据面，"
                                   "最多读今天起 60 天，更远交浏览器 H5/PC",
    ("app_tongcheng", "round_trip"): "国际往返已接（2026-11-03 真机 上海⇌东京 "
                                     "11-16/19）：范围日历选去/返日，结果页"
                                     "去程行是「含税总价」即页面往返总价"
                                     "（7 条去程、最低 9C8515 ¥2209），返程栏"
                                     "`+¥N` 是加价（9C6218 +¥0、IJ005 +¥72），"
                                     "整单总价取页脚「已选…」；首访教学浮层"
                                     "「去程 + 返程 = 往返总价」点下一步即过。"
                                     "端到端 fetch 复验 11-17/22：9 条、最低 ¥2420"
                                     "（GK036；返程 MM877 +¥0，retLoaded=true，20.9s）。"
                                     "返程栏异步渲染，最多等 30s；等不到仍按去程行"
                                     "总价落账并标 retLoaded=false。"
                                     "旧结论「落营销/示例页」是浮层遮挡误判。"
                                     "国内往返：表单可填返程位、日期弹层有"
                                     "「去程/返程/往返总价 ￥785」，但查询落单程"
                                     "去程列表（¥774 起、无返程栏/总价），未接；"
                                     "不把单程列表价当往返价。"
                                     "国内档可填返程位，采集端同流程，尚未真机复验",
    ("app_tongcheng", "multi_city"): "App 有多程入口；采集端未实现，矩阵记未验证，"
                                     "不是渠道没有",
    ("app_tongcheng", "low_fare"): "价格日历即逐日最低价源（同程 App 原生弹层，"
                                   "不是另做的一条通路）；已接特价雷达 "
                                   "`_app_tongcheng_deals`。页面未标含税/优惠口径，"
                                   "雷达行标「口径未标注」，不假设含税；"
                                   "只覆盖今天起 60 天",
    ("app_fliggy", "domestic"): "2026-11-02 固定竖屏+OCR 全链路连续两次："
                                "北京→上海 11-16、上海→北京 11-17 各 3 行，"
                                "同日双日期 11-17/11-18 也跑通；航班/时刻/"
                                "机场/价格可读；「限特定乘客」低价不当普通最低价。"
                                "**只验证当月**；次月/更远显式 "
                                "unsupported 交浏览器（不拿未验证路径冒充）。"
                                "日历会记忆手动滚动位置，滚到次月后需人工回当月；"
                                "连续自动化会触发「访问被拒绝」安全页，"
                                "采集端记 blocked 停手，需人工恢复",
    ("app_fliggy", "detail"): "结果页是 Flutter 画布，uiautomator 读不到；"
                              "Windows OCR 读支付价/时刻/机场/航班号，"
                              "解析器 `crawlers/app_fliggy_parse.py`",
    ("app_fliggy", "intl"): "App 有国际机票入口；国际结果面尚未真机复验，"
                            "不写 y",
    ("app_fliggy", "calendar"): "日期弹层有逐日价，但采集端只用它选日，"
                                "未单独落日历价",
    ("app_fliggy", "round_trip"): "表单有单程/往返/多程；采集端只做单程，"
                                  "未接往返总价，不拿单程价冒充",
    ("app_fliggy", "multi_city"): "App 有多程入口；采集端未实现，矩阵记未验证，"
                                  "不是渠道没有",
    ("app_fliggy", "low_fare"): "App 有低价/特价入口；采集端未接逐日低价源，"
                                "不写 y",
    ("fliggy", "round_trip"): "只有国际能出往返总价（cheapestCalendar 带 "
                              "backDate）；国内列表页是单程结构，已加闸门"
                              "拒绝而不是拿单程价冒充",
    ("tuniu", "round_trip"): "国内 listFlight 两段 segment 的 fare 即"
                             "往返总价（209 个航班 202 个满足 "
                             "B = A + L_ret，r769）；国际走 H5 RT 列表页 + "
                             "queryFlight 两段 segment，productList."
                             "avgTotalPrice 是页面「往返 含税」总价"
                             "（2026-11-03 SHA→NRT 11-05/08，35 条、"
                             "最低 ¥3010，3.8s）。国内/国际都只采渠道"
                             "自算总价，不做两段单程相加",
}

# `round_trip=y` 但**只覆盖一端**的渠道，短标签（检索页「往返票」chip 用，
# 拼在渠道名后读作「飞猪仅国际」）。与 DIMENSION_NOTES 同源：改一端必须
# 改另一端，`test_r805ae` 把「有 scope 必有 note」钉住。
DIMENSION_SCOPE = {
    ("ctrip", "multi_city"): "仅 2 段",
    ("fliggy", "round_trip"): "仅国际",
    ("qunar", "round_trip"): "仅国内",
    ("app_qunar", "round_trip"): "仅国内",
    ("app_tongcheng", "round_trip"): "仅国际",
    ("tuniu", "calendar"): "仅国内",
}


def has_surface(plat: str) -> bool:
    """该渠道**有没有端面概念**（只有浏览器渠道有）。

    与 `surface_state` 的区别是「没声明这个端」vs「声明了但值未知」：
    App 渠道走全端采集，没有 PC/H5 之分——界面必须画「—」，
    不能画成「? 未验证」，否则读者会以为「它的 PC 端还没验证过」。
    """
    return plat in CHANNEL_SURFACES


def unsupported_dims(plat: str) -> tuple:
    """该渠道**明确不支持**的维度（用来做 unsupported 落账与界面说明）。"""
    return tuple(d for d in DIMENSIONS if dim_state(plat, d) == "n")


def browser_supported(dim: str) -> bool:
    """**任一**浏览器渠道已具备该维度（App 对齐的真正基准）。

    用户的原始要求是「PC/H5 渠道拥有的各个维度的能力都要对齐有」——
    基准是"浏览器端有这个东西"，不是"某一家友商有"。按单个同行判，
    同行自己缺这一维时缺口会恒为空（携程 round_trip=n 就是这么自证的）。
    """
    return any(dim_state(p, dim) == "y" for p in BROWSER_CHANNELS)


def app_alignment_gaps(plat: str) -> tuple:
    """App 渠道相对**浏览器端整体能力**尚未对齐的维度。

    - 基准 = 任一浏览器渠道为 y 的维度（`browser_supported`）；
    - App 为 y 才算对齐；`n`/"" 都算缺口（`n` 是真缺，`""` 是没验证）；
    - App 比基准多出来的能力不是缺口（用户明确说过 App 信息更全）。
    """
    if plat not in APP_CHANNELS:
        return ()
    return tuple(d for d in DIMENSIONS
                 if browser_supported(d) and dim_state(plat, d) != "y")


# 采集通路（fetch_paths.entry_path）→ 显示名。
#
# 账本里这张表的值是各 crawler 自己写的字面量：浏览器渠道大多已是中文
# （日历/H5/PC/窗历/往返/H5·API），App 渠道却是英文 id（app-list /
# android-runtime / snap-restore …）。健康卡的「分通路」小标和
# core.pacing 的路径劣化提示都直接把这些键名打到屏幕上，读者看到
# 「android-runtime 无有效样本」根本不知道是哪一步卡住。
#
# 键必须与 path_note() 的实参逐字一致（test_r658 会扫源码对账）：
# 新增通路时这里不同步，界面就退回裸 id。
PATH_CN = {
    # 浏览器渠道
    "H5": "H5",                 # 已是行业通用写法，保留
    "PC": "PC",
    "H5/API": "H5 · API",
    "日历": "日历",
    "窗历": "窗历",
    "往返": "往返",
    "多程": "多程",
    "航班明细": "航班明细",
    "PC可见": "PC 可见",
    # 其余散落在单个 crawler 里的通路名（r658 门禁扫 path_note 字面量
    # 对账时补出，此前没人意识到它们也会上屏）
    "H5列表": "H5 列表",
    "API": "API 直连",
    "QUERY": "查询请求",
    "TRIP": "往返查询",
    # App 渠道（智行 / 去哪儿）：这条真机链路分段入账，每段都可能成为瓶颈
    "app-route": "App 设航线",
    "app-list": "App 航班列表",
    "app-blocker": "App 拦路弹窗",
    "app-dump": "App 界面快照",
    "app-error": "App 解析",
    # 点「搜索」这一步单独记一段（r691/r694：点下去没反应时，健康卡要
    # 说得出是「搜索没响应」而不是笼统的 App 错误）
    "app-search": "App 点搜索",
    # 搜索前发现表单停在多程档（r941：App 会记住上次搜索模式）
    "app-mode": "App 搜索档位",
    # 登录是 App 渠道的硬前置（去哪儿尤其）
    "app-login": "App 登录",
    # 往返档切换与双日期选择是独立的一段（r923+ 同程 App 往返接入）
    "app-roundtrip": "App 往返",
    # 低价机票（发现源）：只出「每天一条最低价」，与明细分开记账
    "low-fare": "App 低价机票",
    "android-runtime": "模拟器运行时",
    "android-device": "模拟器设备",
    "android-ocr": "系统 OCR",
    "android-u2": "u2 界面快照",
    "snap-restore": "登录态快照恢复",
    # 飞猪/同程/携程 App 的分段（r658 扫 path_note 字面量补出）
    "app-form": "App 机票表单",
    "app-city": "App 设城市",
    "app-city-dep": "App 设出发城市",
    "app-city-arr": "App 设到达城市",
    "app-city-%s": "App 设城市",
    "app-date": "App 选日期",
    "app-calendar": "App 价格日历",
    "app-block": "App 风控拦截",
}


def path_cn(p: str) -> str:
    """通路 id → 显示名；未知通路原样返回（宁缺勿错，不编造名字）。"""
    return PATH_CN.get(p) or p


def channel_dims_payload() -> dict:
    """`/api/channel-dims` 与静态演示烘焙共用的一份矩阵载荷。

    以前接口和 `docs/demo_build.py` 各拼一份；演示站没烘这个接口，
    配置页的能力矩阵在公开站上一直显示「加载失败」。这里收敛成单源。
    """
    def _surf(p: str) -> dict:
        # 只有浏览器渠道有端面。App 渠道若也下发 surface_cells，前端
        # hasOwnProperty 恒真会把「没有端面」画成「? 未验证」。
        if not has_surface(p):
            return {}
        return {
            "surface_cells": {s: surface_state(p, s) for s in SURFACES},
            "surface_notes": {s: SURFACE_NOTES.get((p, s), "")
                              for s in SURFACES},
        }
    return {
        "ok": True, "dims": list(DIMENSIONS), "surfaces": list(SURFACES),
        "channels": [
            dict({"plat": p, "name": CHANNEL_CN.get(p, p),
                  "cells": {d: dim_state(p, d) for d in DIMENSIONS},
                  "dim_notes": {d: DIMENSION_NOTES.get((p, d), "")
                                for d in DIMENSIONS},
                  "dim_scopes": {d: DIMENSION_SCOPE.get((p, d), "")
                                 for d in DIMENSIONS}},
                 **_surf(p),
                 peer=APP_BROWSER_PEER.get(p, ""),
                 gaps=list(app_alignment_gaps(p)))
            for p in CHANNEL_DIMENSIONS],
    }

