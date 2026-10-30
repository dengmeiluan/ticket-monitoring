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
APP_CHANNELS = ("app_zhixing", "app_qunar")

# 显示名（中文）。App 渠道必须在这里，否则界面会露出裸 id（app_zhixing）。
CHANNEL_CN = {
    "ctrip": "携程", "qunar": "去哪儿", "fliggy": "飞猪",
    "tongcheng": "同程", "tuniu": "途牛",
    "app_zhixing": "智行 App", "app_qunar": "去哪儿 App",
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
    #   round_trip: ctrip/qunar 的 fetch 里有显式 "往返明细暂不支持" 分支
    #               → n；fliggy（tripType/backDate）、tongcheng（TT=RT/AD）
    #               有真实报文参数 → y；tuniu 无 ret_date 使用 → 未验证。
    #   multi_city: 五个 crawler 都**没有**多程实现 → 一律 n
    #               （宁可如实说没有，也不写一个不会工作的 y）。
    #   low_fare:   只有 qunar（lowFlight H5）与 fliggy（特价榜）有发现源，
    #               其余未接入 → 未验证。
    "ctrip":     {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "n", "multi_city": "n", "low_fare": ""},
    "qunar":     {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "n", "multi_city": "n", "low_fare": "y"},
    "fliggy":    {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "n", "low_fare": "y"},
    "tongcheng": {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "y", "multi_city": "n", "low_fare": ""},
    "tuniu":     {"domestic": "y", "intl": "y", "calendar": "y", "detail": "y",
                  "round_trip": "", "multi_city": "n", "low_fare": ""},
    # App 渠道（同 APP_PLAT_NAME 里的名字；与对应浏览器渠道逐项可比）
    #   intl: 两个 App 都有独立的国际档（智行「国际」标签页 / 去哪儿城市页
    #         「国际」tab + 搜索框），均已在真机跑通（2026-10-30）：
    #         智行 浦东→成田 日历价 + 7 条明细；去哪儿 浦东→成田
    #         11-20/11-24 各 4/3 条真实航班，与国内同一条链路。
    #   low_fare: 两个 App 的「低价机票」入口都没接入（tab 能点进去，
    #             但没有把它当作发现源采集）→ 留空，不写 y。
    "app_zhixing": {"domestic": "y", "intl": "y", "calendar": "y",
                    "detail": "y", "round_trip": "n", "multi_city": "n",
                    "low_fare": ""},
    "app_qunar":   {"domestic": "y", "intl": "y", "calendar": "y",
                    "detail": "y", "round_trip": "n", "multi_city": "n",
                    "low_fare": ""},
}

# App 渠道与哪个浏览器渠道同源（对齐基准）。新增 App 渠道必须在这里
# 指明基准，否则「对齐」无从判定。
APP_BROWSER_PEER = {
    "app_zhixing": "ctrip",     # 智行 = 携程系 App
    "app_qunar": "qunar",       # 去哪儿 App
}


def dim_state(plat: str, dim: str) -> str:
    """渠道在某维度上的声明（"y"/"n"/""）；未声明的渠道一律返回 ""。"""
    return (CHANNEL_DIMENSIONS.get(plat) or {}).get(dim, "")


def unsupported_dims(plat: str) -> tuple:
    """该渠道**明确不支持**的维度（用来做 unsupported 落账与界面说明）。"""
    return tuple(d for d in DIMENSIONS if dim_state(plat, d) == "n")


def app_alignment_gaps(plat: str) -> tuple:
    """App 渠道相对其浏览器基准**尚未对齐**的维度。

    只把「基准已支持、App 未验证/不支持」算缺口——App 比基准多出来的
    能力不是缺口（用户明确说过 App 信息更全）。
    """
    peer = APP_BROWSER_PEER.get(plat, "")
    if not peer:
        return ()
    base = CHANNEL_DIMENSIONS.get(peer) or {}
    return tuple(d for d in DIMENSIONS
                 if base.get(d) == "y" and dim_state(plat, d) != "y")


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
    # 登录是 App 渠道的硬前置（去哪儿尤其）
    "app-login": "App 登录",
    # 低价机票（发现源）：只出「每天一条最低价」，与明细分开记账
    "low-fare": "App 低价机票",
    "android-runtime": "模拟器运行时",
    "android-device": "模拟器设备",
    "snap-restore": "登录态快照恢复",
}


def path_cn(p: str) -> str:
    """通路 id → 显示名；未知通路原样返回（宁缺勿错，不编造名字）。"""
    return PATH_CN.get(p) or p

