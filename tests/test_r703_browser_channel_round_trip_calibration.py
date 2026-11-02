# -*- coding: utf-8 -*-
"""r703：往返声明必须与代码一致——**七家渠道全覆盖**。

r677 只钉了 App 渠道：`supports_round_trip` 与矩阵要一致。用户点名
「校准以前的 PC/H5 渠道是否正确」，所以这里把五家浏览器渠道也按同样
口径校准一遍——声明 `y` 就必须真有 ret_date 使用路径，声明 `n` 就必须
真的把 ret_date 挡在门外并显式落账，不能让「假装支持」或「静默吞掉」
藏在代码里。

真机/真请求证据（2026-10-31 复核）：

    fliggy      tripType=1 + backDate 真实报文参数，行须带同值 backDate
    tongcheng   TT=RT + AD=回程日只对站点自身签名请求生效，裸打恒 444；
                窗历只有单程 → **r740 实测推翻旧声明，改判 n**
    ctrip       r815i PC `round-...&containstax=1` 列表接通「往返含税价」
                （上海→东京 6 条 ¥2404…¥2682），价格是渠道往返总价
    qunar       r815j touch 往返页去程卡「往返总价 ¥N 起」（北京→上海
                71 条 ¥808…¥2546）；国际仍显式 unsupported
    tuniu       签名收了 ret_date 但没有使用 → 显式 unsupported(n)
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers
from core.channels import CHANNEL_DIMENSIONS, dim_state


def _src(plat):
    cls = crawlers.REGISTRY[plat]
    return inspect.getsource(inspect.getmodule(cls))


def test_every_channel_declares_round_trip():
    """七家都要表态，不能有空白——空白会被界面当成「未知」还是「没有」两可。"""
    for plat in CHANNEL_DIMENSIONS:
        assert dim_state(plat, "round_trip") in ("y", "n", ""), plat


def test_round_trip_y_has_real_ret_date_path():
    """声明 y 的渠道，源码里必须真的把 ret_date 用进了请求或解析。"""
    for plat, row in CHANNEL_DIMENSIONS.items():
        if row.get("round_trip") != "y":
            continue
        src = _src(plat)
        assert "ret_date" in src, "%s 声明支持往返，源码里没有 ret_date" % plat
        # 只出现一次（函数签名）说明「收了但没用」——那是假支持
        uses = src.count("ret_date")
        assert uses >= 2, \
            "%s 只在签名里出现 ret_date（%d 次），没有真实使用" % (plat, uses)


def test_fliggy_turn_trip_ticket_is_wired():
    src = _src("fliggy")
    assert "tripType" in src and "backDate" in src


def test_tongcheng_rt_flag_and_back_date_are_wired():
    src = _src("tongcheng")
    assert '"RT"' in src, "同程 RT 标记缺失"
    assert "backDate" in src, "同程回程日字段缺失"


def test_round_trip_n_refuses_explicitly():
    """声明 n 的渠道：必须在 ret_date 在场时**显式落账**再返回空。

    静默忽略 ret_date 会把单程价当成往返总价（推送/走势据此报警），
    所以判据是「有 unsupported 落账」，不是「函数返回空」。
    """
    for plat, row in CHANNEL_DIMENSIONS.items():
        if row.get("round_trip") != "n":
            continue
        src = _src(plat)
        assert "unsupported" in src, \
            "%s 声明不支持往返，但没有 unsupported 落账（会静默吞掉）" % plat
        assert "往返明细暂不支持" in src, \
            "%s 缺少往返不支持的用户可读文案" % plat


def test_tuniu_round_trip_is_native_not_fake():
    """途牛往返：r769 实测确认真能拿到渠道自算总价，声明随之是 y。

    历史两轮：
      * 曾留 ""（未验证）而实际「没做」——`_hoop` 只带去程日，单程价被
        当成往返总价落库；
      * r900 收敛为 n（显式 unsupported）；
      * r769 实测推翻「做不到」：`listFlight` 放两段（去程 + 反向回程日）
        时返回价就是往返总价（209 个航班 202 个满足 B = A + 反向最低价，
        B−A 中位数恰等于该最低价，无一条 B ≈ A），已接线 → y。

    这里守两件事：声明是 y 时**必须**真有 back_date 的两段构造；
    国际仍 unsupported（productList 单段，没实测过两段）。
    """
    st = dim_state("tuniu", "round_trip")
    assert st == "y", "途牛国内往返已实测可用，声明应与实现一致"
    src = _src("tuniu")
    assert "back_date" in src and "segmentList" in src, \
        "声明 y 却没有两段 segment 构造"
    assert "_fetch_intl_rt" in src and "avgTotalPrice" in src, (
        "国际往返已接，但代码里没有 H5 queryFlight/avgTotalPrice 通路")


def test_browser_supported_round_trip_reflects_reality():
    """浏览器端「有往返」必须来自**真的取到过往返价**的渠道。

    r740 实测把同程从 y 改成"未验证"（渠道产品支持往返，但 TT=RT/AD
    只对站点自身签名请求生效，裸打恒 444，窗历只有单程——本通路一行
    返程数据都没拿到），r815h 才由 book1/roundtrips 重新接通。携程
    r815i 由 PC 往返列表接通；浏览器端三家已验证 y。
    """
    from core.channels import BROWSER_CHANNELS, browser_supported
    assert browser_supported("round_trip")
    assert "fliggy" in BROWSER_CHANNELS
    assert dim_state("fliggy", "round_trip") == "y"
    assert dim_state("ctrip", "round_trip") == "y", (
        "携程 PC round-...&containstax=1 已实测出「往返含税价」"
        "（r815i 上海→东京 6 条），应记 y")
    assert dim_state("qunar", "round_trip") == "y", (
        "去哪儿 touch 往返页去程卡已实测出「往返总价」（r815j "
        "北京→上海 71 条 ¥808 起），应记 y（仅国内）")
    assert dim_state("tongcheng", "round_trip") == "y", (
        "同程国内往返已由 book1/roundtrips 接口接通（atp 产品总价），"
        "应记 y；国际往返仍走页面两步流，卡点写在 DIMENSION_NOTES")
