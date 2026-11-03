# -*- coding: utf-8 -*-
"""r677：渠道 × 维度矩阵——把「PC/H5 每个维度都要对齐」钉成门禁。

用户要求：App 渠道信息可以更全，但 **PC/H5 已有的每个维度的能力都要有**。
要能核查，能力就必须声明化（照 `specials.SPECIAL_CAPABILITY` 的先例），
而不是散在各 crawler 的 if 里。

取值只有三种：`y` 现役支持 / `n` 明确不支持 / `""` 尚未验证。
`""` **不得**当成支持——界面与文档都要按未知对待。

这里钉住三条不变式：
  1. 每个已注册渠道、每个维度都必须有声明（缺项 = 没人想过这件事）；
  2. 声明必须与代码行为一致（声明 `n` 的维度，代码里必须真有不支持分支）；
  3. App 渠道必须以同名浏览器渠道为基准，缺口清单可枚举（不是"看着挺全"）。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers
from core.channels import (APP_BROWSER_PEER, APP_CHANNELS, BROWSER_CHANNELS,
                           CHANNEL_DIMENSIONS, DIMENSIONS, DIMENSION_SCOPE,
                           app_alignment_gaps, dim_state, unsupported_dims)


def test_every_registered_channel_has_every_dimension():
    """注册了渠道就必须对每个维度表态——缺项就是没人想过。"""
    missing = []
    for plat in crawlers.REGISTRY:
        row = CHANNEL_DIMENSIONS.get(plat)
        if row is None:
            missing.append((plat, "整行缺失"))
            continue
        for d in DIMENSIONS:
            if d not in row:
                missing.append((plat, d))
            elif row[d] not in ("y", "n", ""):
                missing.append((plat, d, "非法取值 %r" % row[d]))
    assert not missing, "渠道维度矩阵有缺项：%s" % missing[:8]


def test_dimension_states_are_only_three_values():
    for plat, row in CHANNEL_DIMENSIONS.items():
        for d, v in row.items():
            assert v in ("y", "n", ""), (plat, d, v)


def test_app_channels_declare_browser_peer():
    """没有基准就没法谈「对齐」。"""
    for p in APP_CHANNELS:
        assert p in APP_BROWSER_PEER, "%s 没声明对齐基准" % p
        assert APP_BROWSER_PEER[p] in BROWSER_CHANNELS, APP_BROWSER_PEER[p]


def test_round_trip_declared_unsupported_matches_code():
    """声明 `n` 的维度，代码里必须真的有不支持分支。

    反向也成立：基类默认 `supports_round_trip=False`，声明 y 却走默认值
    就是**声明与行为打架**——用户会看到「支持」却永远拿不到数据。
    """
    for plat in APP_CHANNELS:
        if dim_state(plat, "round_trip") == "n":
            cls = crawlers.REGISTRY[plat]
            assert getattr(cls, "supports_round_trip", False) is False, \
                "%s 声明不支持往返，但类属性说支持" % plat
        elif dim_state(plat, "round_trip") == "y":
            cls = crawlers.REGISTRY[plat]
            assert getattr(cls, "supports_round_trip", False) is True, \
                "%s 声明支持往返，但类属性仍是默认 False（会静默 unsupported）" % plat
    # 基类这道闸门本身要在（声明式能力的执行点）
    from crawlers.app_base import AppCrawler
    src = inspect.getsource(AppCrawler.safe_fetch)
    assert "supports_round_trip" in src, src[:300]


def test_unsupported_dims_is_derived_not_handwritten():
    """明确不支持的维度是**推导**出来的，不是手写清单。"""
    # 两家 App 的往返都已真机跑通（2026-10-31），不再是 unsupported
    assert "round_trip" not in unsupported_dims("app_qunar"), \
        unsupported_dims("app_qunar")
    assert "round_trip" not in unsupported_dims("app_zhixing"), \
        unsupported_dims("app_zhixing")
    # 渠道产品有往返/多程，但本仓库采集端未实现/未出数 → 未验证（""），
    # 不是“不支持”：矩阵的 n 只留给渠道真没有的能力。
    assert "round_trip" not in unsupported_dims("qunar")
    assert "multi_city" not in unsupported_dims("app_qunar")
    assert "multi_city" not in unsupported_dims("app_zhixing")


def test_alignment_gaps_are_enumerable_not_vague():
    """缺口必须是可枚举的清单，能直接当待办用。

    基准是「**任一**浏览器渠道已具备该维度」（用户原话：PC/H5 渠道拥有的
    能力 App 都要对齐有），不是「某一家同源友商有」——按单个同行判会
    自证：携程自己 round_trip 未验证，于是「智行 ↔ 携程」永远算不出往返
    缺口，而网页端飞猪/同程明明支持。as of 2026-11-02 晚：智行与去哪儿
    App 国内/国际/日历/明细/往返/低价机票**全部落地**；2026-11-03 ctrip PC
    多程 2 段升 y 后，App 端未接多程，缺口清单应**精确为** `("multi_city",)`。
    """
    assert app_alignment_gaps("app_qunar") == ("multi_city",), (
        "去哪儿 App 仅剩多程缺口：%r" % (app_alignment_gaps("app_qunar"),))
    assert app_alignment_gaps("app_zhixing") == ("multi_city",)
    # 缺口是空集合时，上面的 all(...) 会恒真——所以下面另造一个非空场景
    # 验证函数真的会报缺口（见 try 块），这里就不再写恒真式。
    # 函数本身不能因为「都对齐了」就退化成恒空：造一个「基准有、App 无」
    # 的临时场景，它必须把那一维报出来（否则这层门禁就成了摆设）。
    from core.channels import APP_BROWSER_PEER, CHANNEL_DIMENSIONS
    # 造「浏览器端有、App 没有」的临时场景：浏览器 qunar 的 low_fare 置 y，
    # app_qunar 置 ""（未验证），缺口必须出现；finally 里还原**保存值**。
    saved = {p2: (CHANNEL_DIMENSIONS[p2] or {}).get("low_fare", "")
             for p2 in CHANNEL_DIMENSIONS}
    try:
        CHANNEL_DIMENSIONS["qunar"]["low_fare"] = "y"
        CHANNEL_DIMENSIONS["app_qunar"]["low_fare"] = ""
        gaps = app_alignment_gaps("app_qunar")
        assert "low_fare" in gaps, gaps
    finally:
        for p2, val in saved.items():
            CHANNEL_DIMENSIONS[p2]["low_fare"] = val
    assert APP_BROWSER_PEER["app_qunar"] == "qunar"


def test_app_is_allowed_to_exceed_peer():
    """App 比浏览器端**多**出来的能力不算缺口（用户明确说 App 信息更全）。

    判据方向：缺口只来自「浏览器端有 y、App 不是 y」，App 为 y 而浏览器
    端没有的维度绝不能出现在缺口里（否则「更全」反被判成待办）。
    """
    from core.channels import CHANNEL_DIMENSIONS as M
    peer_union = {d for p in BROWSER_CHANNELS for d in DIMENSIONS
                  if (M.get(p) or {}).get(d) == "y"}
    for plat in APP_CHANNELS:
        gaps = app_alignment_gaps(plat)
        assert set(gaps) <= peer_union, (
            "%s 的缺口里出现了浏览器端并不具备的维度：%s" % (plat, gaps))
        extra = {d for d in DIMENSIONS
                 if dim_state(plat, d) == "y" and d not in peer_union}
        assert not (extra & set(gaps)), (
            "%s 比浏览器端多出来的能力被算成了缺口：%s" % (plat, extra))


def test_unknown_dimension_is_not_treated_as_supported():
    """未验证（`""`）绝不能被读成「支持」。

    注意别把**已接入**的维度写死成 `""` 来守这条：r732 把智行「特价」
    接入后（真机确认它也是逐天报价），原来那句
    `dim_state("app_zhixing","low_fare") == ""` 就变成了「守旧事实」，
    红灯只说明接入成功而不是判据坏了。这里改用**真正没接过**的东西：
    不存在的渠道 / 不存在的维度，必须一律返回 `""`。
    """
    assert dim_state("app_zhixing", "low_fare") == "y", (
        "智行「特价」已按 low_fare 接入（r732）；若退回未接入请同步改这里")
    assert dim_state("no_such_plat", "domestic") == ""
    assert dim_state("app_qunar", "no_such_dim") == ""
    assert dim_state("ctrip", "no_such_dim") == ""


# ---------- 恢复快照的两种失败要分得开 ----------
def test_login_wall_detection_is_per_channel():
    """各渠道登录墙形态不同：去哪儿是手机号表单，智行是「立即登录」文案。"""
    from crawlers.app_qunar import AppQunarCrawler
    from crawlers.app_zhixing import AppZhixingCrawler

    qunar_wall = ('<hierarchy><node text="请输入手机号" bounds="[0,0][1,1]" />'
                  '</hierarchy>')
    zx_wall = ('<hierarchy><node text="立即登录" bounds="[0,0][1,1]" />'
               '</hierarchy>')
    home = ('<hierarchy><node text="单程" bounds="[0,0][1,1]" />'
            '<node text="搜索" bounds="[0,0][1,1]" /></hierarchy>')

    q = AppQunarCrawler.__new__(AppQunarCrawler)
    z = AppZhixingCrawler.__new__(AppZhixingCrawler)
    assert q.is_login_wall(qunar_wall) is True
    assert q.is_login_wall(home) is False
    assert z.is_login_wall(zx_wall) is True


def test_expired_snapshot_is_reported_not_silent():
    """恢复了快照却仍在登录墙 → 账本要写「快照已失效」，别只留一句 login。

    这跟「恢复失败」是两件事：前者该重新登录，后者该查文件。
    """
    import inspect
    from crawlers.app_base import AppCrawler
    src = inspect.getsource(AppCrawler.restore_login_snapshot)
    assert "is_login_wall" in src, "恢复流程没校验登录墙"
    assert "快照已失效" in src, "失效快照没有可读结论"


# ---------- 声明必须有代码证据（防"看起来应该支持"） ----------
def test_multi_city_y_only_for_verified_ctrip_two_segments():
    """只有 ctrip PC 2 段可声明 y，且必须带「仅 2 段」scope。

    2026-11-03 生产行 ¥1476（IJ004+MM304）证明 2 段整单链路可用；
    3+ 段实测无组合卡、缺口程未验。其余渠道仍未接，不得声明 y。
    """
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for plat in BROWSER_CHANNELS + APP_CHANNELS:
        if plat == "ctrip":
            assert dim_state(plat, "multi_city") == "y", \
                "ctrip 已有 2 段生产整单行，矩阵却未声明 y"
            assert DIMENSION_SCOPE.get((plat, "multi_city")) == "仅 2 段", \
                "ctrip 多程只验证 2 段，scope 必须写明"
        else:
            assert dim_state(plat, "multi_city") != "y", \
                "%s 声明支持多程，但代码里没有实现" % plat
    ctrip = io.open(os.path.join(root, "crawlers", "ctrip.py"),
                    encoding="utf-8", newline="").read()
    assert "def fetch_multi(" in ctrip, "ctrip 声明 y 但没有 fetch_multi"
    for f in ("qunar.py", "fliggy.py", "tongcheng.py", "tuniu.py"):
        src = io.open(os.path.join(root, "crawlers", f),
                      encoding="utf-8", newline="").read()
        assert "multi_city" not in src and "多程查询" not in src, f


def test_browser_round_trip_y_or_explicit_intl_gap():
    """浏览器渠道国内往返已全部接通；国际未验证的必须有显式分支。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for plat in ("ctrip", "qunar"):
        assert dim_state(plat, "round_trip") == "y", plat
    qsrc = io.open(os.path.join(root, "crawlers", "qunar.py"),
                   encoding="utf-8", newline="").read()
    assert "国际往返暂不支持" in qsrc, \
        "qunar 国际往返未验证，必须在源码里显式拒绝"
    csrc = io.open(os.path.join(root, "crawlers", "ctrip.py"),
                   encoding="utf-8", newline="").read()
    assert "_fetch_rt" in csrc and "containstax=1" in csrc
