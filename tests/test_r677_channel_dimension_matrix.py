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
                           CHANNEL_DIMENSIONS, DIMENSIONS, app_alignment_gaps,
                           dim_state, unsupported_dims)


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
    assert "round_trip" in unsupported_dims("app_qunar"), \
        unsupported_dims("app_qunar")
    # 去哪儿浏览器渠道自己也不支持往返，App 与它一致
    assert "round_trip" in unsupported_dims("qunar")
    # 多程全渠道都没有实现，两家 App 都必须如实标注
    assert "multi_city" in unsupported_dims("app_qunar")
    assert "multi_city" in unsupported_dims("app_zhixing")


def test_alignment_gaps_are_enumerable_not_vague():
    """缺口必须是可枚举的清单，能直接当待办用。"""
    gaps = app_alignment_gaps("app_qunar")
    # 国内/国际/日历/明细都已真机跑通（2026-10-30）；低价机票未接入
    # → 必须出现在缺口里。国际从「未验证」变成 y 后，缺口只剩它。
    assert "domestic" not in gaps and "calendar" not in gaps
    assert "detail" not in gaps and "intl" not in gaps
    assert "low_fare" in gaps, gaps


def test_app_is_allowed_to_exceed_peer():
    """App 比基准多出来的能力不算缺口（用户明确说 App 信息更全）。"""
    from core.channels import CHANNEL_DIMENSIONS as M
    # 造一个「App 多一项」的临时场景，验证判定方向
    peer = M["qunar"]
    assert app_alignment_gaps("app_qunar") == tuple(
        d for d in DIMENSIONS if peer.get(d) == "y"
        and dim_state("app_qunar", d) != "y")


def test_unknown_dimension_is_not_treated_as_supported():
    """未验证（`""`）绝不能被读成「支持」。"""
    # 低价机票仍未接入：留空即「未验证」，绝不能被读成支持
    assert dim_state("app_qunar", "low_fare") == ""
    assert dim_state("no_such_plat", "domestic") == ""
    assert dim_state("app_qunar", "no_such_dim") == ""


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
def test_multi_city_has_no_implementation_anywhere():
    """五个 crawler 都没有多程实现 → 谁都不许声明 y。

    这条是负向守卫：将来真做了多程，把实现连同矩阵一起改；
    在此之前写 y 就是给用户一个不会工作的能力。
    """
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for plat in BROWSER_CHANNELS + APP_CHANNELS:
        assert dim_state(plat, "multi_city") != "y",             "%s 声明支持多程，但代码里没有实现" % plat
    for f in ("ctrip.py", "qunar.py", "fliggy.py", "tongcheng.py", "tuniu.py"):
        src = io.open(os.path.join(root, "crawlers", f),
                      encoding="utf-8", newline="").read()
        assert "multi_city" not in src and "多程查询" not in src, f


def test_unsupported_round_trip_declared_only_where_code_says_so():
    """声明 n 的浏览器渠道，代码里必须有「暂不支持」分支。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for plat in ("ctrip", "qunar"):
        assert dim_state(plat, "round_trip") == "n", plat
        src = io.open(os.path.join(root, "crawlers", plat + ".py"),
                      encoding="utf-8", newline="").read()
        assert "往返明细暂不支持" in src,             "%s 声明不支持往返，但代码里没有对应的显式分支" % plat
