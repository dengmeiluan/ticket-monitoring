# -*- coding: utf-8 -*-
"""r365 审计收口钉：舱位语义、KPI 同班键、健康分母与关注身份可编。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "webui.py").read_text(encoding="utf-8")


def test_qunar_cabin_class_never_aircraft_or_discount():
    from core.flightnorm import cabin_class
    assert cabin_class("空客320(中)") == ""
    assert cabin_class("10折") == ""
    assert cabin_class("Y") == "经济舱"
    assert cabin_class("经济舱") == "经济舱"


def test_state_emits_real_cabin_not_description():
    assert "_cab_real = _ccl(_cc(" in SRC
    assert '"cabinT": _ct(f), "cabin": _cab_real,' in SRC
    assert "_STATE_SCHEMA = \"probe-r365-1\"" in SRC
    # 明细/三方对齐/CSV 的舱位列只消费真实舱位
    assert "['舱位',f.cabin||'—']" in SRC
    assert "['舱位',f.cabin||f.cabinCode||'—']" in SRC
    assert "(f.cabin||'').replace(/<[^>]*>/g,'')" in SRC
    assert "f.dur||'',f.cabin||''" in SRC
    # 舱位档与舱位片优先真实舱位；描述串只进 title
    assert "f.cabin||f.cabinT||f.cabinCode" in SRC
    assert '舱位描述：' in SRC


def test_kpi_unique_uses_canonical_flight_key():
    start = SRC.index("function _flightUid")
    body = SRC[start:start + 900]
    assert "srxFlightKey(f)" in body
    assert "flightNo||f.name" not in body


def test_health_badge_title_denominator_matches_badge():
    assert "${detOk}/${att}" in SRC
    assert "${detOk}/${detAtt}" not in SRC
    assert "计入分母，不计成功" in SRC


def test_watch_identity_editable_end_to_end():
    assert "function cfgWatchIdentityEditable()" in SRC
    assert "cfgWatchLockIdentity" not in SRC
    assert "可改航线/日期/航班/舱位/渠道/目标" in SRC
    # 提交 patch 携带身份字段，服务端按新身份重建 entry/id
    assert "trans:(($('cwTrans')||{}).value||'').trim(),cross:" in SRC
    assert '"trans", "cross", "stop", "cabin"' in SRC
    assert "目标航班已在关注清单，请直接编辑该条" in SRC
    # 关注台跳配置不再因清单未加载而静默 no-op
    assert "CFG_WATCH.list=[w];open()" in SRC


def test_config_nav_has_visible_focus_ring():
    assert "#cfgview .cnav:focus-visible{outline:2px solid var(--blue)" in SRC
