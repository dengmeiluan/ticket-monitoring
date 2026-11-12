# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r364_honesty_a11y.py
- tests/test_v293_honesty_regressions.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import sys
import webui

from core.models import FlightPrice
from core.storage import PriceStorage
from datetime import date, datetime, timedelta

# 活数据日期：防「日期已过」校验随日历腐化（长窗历史锚=写作日-6）
_FUTURE = (date.today() + timedelta(days=7)).isoformat()
_PAST6 = (date.today() - timedelta(days=6)).isoformat()
from report import _rounds


# ---- merged from tests/test_r364_honesty_a11y.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui.PAGE


def _source():
    return webui_full_src()


def test_cabin_channel_word_beats_sale_code():
    s = _src()
    i = s.index('function cabinOf(f){')
    block = s[i:i + 1800]
    assert "/头等/.test(t)" in block
    assert "/经济/.test(t)" in block
    # 词面判定必须在订座码映射 M 之前
    assert block.index("/经济/.test(t)") < block.index("const M={Y:'经济'")


def test_health_badge_uses_all_attempts_and_swr():
    s = _src()
    assert "const detAll=att?Math.round(detOk/att*100):null" in s
    assert "useDet?'航班级 '+detOk+'/'+att" in s
    s = _source()
    i = s.index('def _health_state(hours: int = 24) -> dict:')
    block = s[i:i + 3200]
    assert 'name="health-rebuild"' in block
    assert '_HEALTH_CACHE["busy"]' in block
    assert 'time.time() - _HEALTH_CACHE["at"] >= 2' in block


def test_trend_kline_note_discloses_calendar():
    s = _src()
    assert '日K=真实航班当日最低价（不含日历价 · 开/收=当日首末价）' in s
    assert '日K=行情池当日最低价（含日历价 · 开/收=当日首末价）' in s


def test_qual_kpi_counts_flights_and_rows():
    s = _src()
    assert "const qualUniq=new Set(real.filter(f=>f.qual).map(f=>_flightUid(f))).size" in s
    assert "qualUniq+' 个航班 · '+qual+' 条报价 · 真达标'" in s


def test_slash_cannot_steal_focus_from_layer():
    s = _src()
    i = s.index("document.addEventListener('keydown',ev=>{\n const tag=(document.activeElement")
    block = s[i:i + 1800]
    assert "if(srxTopLayer())return;" in block
    assert block.index("if(srxTopLayer())return;") < block.index("if(ev.key==='/')")


def test_detail_tab_restore_scoped_to_tablist():
    s = _src()
    i = s.index('function srxRenderDetail(preserve){')
    block = s[i:i + 700]
    assert "closest('.srx-dtabs')?'.srx-dtabs '" in block


def test_city_panel_trap_and_tab_aria():
    s = _src()
    i = s.index("$('citypanel').addEventListener('keydown',e=>{\n if(e.key!=='Tab')")
    block = s[i:i + 700]
    assert 'const i=f.indexOf(document.activeElement);' in block
    assert 'i===-1||i>=f.length-1' in block
    assert "addEventListener('focusin'" in block
    assert 'aria-selected="true"' in s and 'aria-selected="false"' in s
    assert "if(el.getAttribute('role')!=='tab')el.setAttribute('role','button');" in s
    assert "['ArrowRight','ArrowLeft','Home','End']" in s


def test_matrix_cell_hierarchy_and_hint():
    s = _src()
    i = s.index('#searchview .srx-mx .mcell{')
    block = s[i:i + 500]
    assert 'background:var(--card);color:var(--tx)' in block
    assert '_mh.style.display=_mx.scrollWidth>_mx.clientWidth+1' in s


def test_mobile_320_identity_and_first_screen():
    s = _src()
    # r386：320 档价格列由 auto 改固定 72px（行间价格左缘参差 17px）
    assert '#searchview .srx-row{grid-template-columns:24px minmax(0,1fr) 72px 75px;gap:4px}' in s
    assert 'grid-template-columns:repeat(2,36px)' in s
    assert '#searchview .srx-hero-act{display:flex;flex-wrap:nowrap;overflow-x:auto' in s
    assert '#chartRoutes{flex-wrap:nowrap;overflow-x:auto' in s
    assert '#searchview .srx-galrail,#searchview .srx-galview{position:static!important;top:auto!important}' in s
    assert 'id="srxViewBtnM"' in s
    assert "vm.textContent=SRX.view==='matrix'?'列表':'矩阵'" in s


def test_detail_flex_footer_visible():
    s = _src()
    assert '#searchview .srx-detail.open{display:flex;flex-direction:column' in s
    assert '#searchview .srx-detail.open .srx-dsec{flex:1 1 auto;min-height:0;overflow:auto' in s


def test_calendar_cache_and_head_vary():
    s = _source()
    i = s.index('def _srx_calendar(frm, to, date, days=14, axis="both"):')
    block = s[i:i + 1600]
    assert '_CAL_CACHE' in block and '_CAL_LOCK' in block
    assert 'now - _CAL_CACHE["at"] < 30' in block
    assert 'def do_HEAD(self):' in s
    assert 'self.send_error(405)' in s
    j = s.index('def do_GET(self):')
    k = s.index('def _do_GET_impl(self):') if 'def _do_GET_impl(self):' in s else j
    assert 'self.send_header("Vary", "Accept-Encoding")' in (s[j:j + 1900] + s[k:k + 3200])


# ---- merged from tests/test_v293_honesty_regressions.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _user(**route):
    base = {"from": "SHA", "to": "BJS", "dates": [_FUTURE]}
    base.update(route)
    return {"name": "u", "routes": [base]}


def _entry(**kw):
    e = {"from": "SHA", "to": "BJS", "date": _FUTURE,
         "code": "MU541", "depTime": "09:55", "arrTime": "11:40",
         "trans": "", "cross": "", "stop": False, "cabin": "经济",
         "airline": "东方航空", "channels": ["ctrip"]}
    e.update(kw)
    return e


def test_watch_route_allows_enforces_parent_conditions():
    ok, _ = webui._watch_route_allows(_entry(), {"from": "SHA", "to": "BJS"})
    assert ok is True
    ok, why = webui._watch_route_allows(
        _entry(trans="PVG"), {"direct_only": True})
    assert ok is False and "直飞" in why
    ok, why = webui._watch_route_allows(
        _entry(depTime="23:30"), {"dep_time_max": "20:00"})
    assert ok is False and "出发时段" in why
    ok, why = webui._watch_route_allows(
        _entry(channels=["ctrip"]), {"channels": ["qunar"]})
    assert ok is False and "渠道" in why
    ok, why = webui._watch_route_allows(
        _entry(code="9C6217", airline="春秋航空"), {"no_lcc": True})
    assert ok is True  # no_lcc needs an explicit lcc flag, not inference
    ok, why = webui._watch_route_allows(
        _entry(code="MU541", airline="东方航空"), {"airlines": "!MU"})
    assert ok is False and "排除" in why


def test_watch_scope_flags_entry_outside_parent_filters(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [_user(direct_only=True)])
    in_scope, reason, state = webui._watch_scope_detail(
        _entry(trans="PVG"), "u")
    assert in_scope is False
    assert state == "route_filtered"
    assert "直飞" in reason


def test_watch_entry_rejects_identity_outside_parent_filters(monkeypatch):
    monkeypatch.setattr(webui._State, "users", [_user(direct_only=True)])
    payload = {"from": "SHA", "to": "BJS", "date": _FUTURE,
               "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
               "trans": "PVG", "cross": "", "stop": False, "cabin": "经济舱"}
    try:
        webui._watch_entry(payload, user="u")
        assert False, "must reject a transfer flight under direct_only"
    except ValueError as e:
        assert "父航线适用条件" in str(e)


class _Storage:
    def __init__(self):
        self.state = {}

    def get_alert_state(self, key):
        return self.state.get(key)

    def set_alert_state(self, key, value):
        self.state[key] = value


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, desp="", **kw):
        self.sent.append((title, desp))
        return True


def _alert(monkeypatch, price, eff):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    monkeypatch.setattr(webui, "_watch_list", lambda user: {"watches": [{
        "id": "w1", "code": "MU541", "from": "SHA", "to": "BJS",
        "date": "2099-01-01", "depTime": "09:55", "active": True,
        "notify": True, "target": 1020, "inScope": True,
        "channels": ["ctrip"]}]})
    monkeypatch.setattr(webui, "_watch_trend", lambda user, wid, days=2: {
        "current": {"price": price, "eff": eff, "platform": "ctrip", "at": now}})
    monkeypatch.setattr(webui, "_watch_parent_route", lambda w, u: None)
    monkeypatch.setattr(webui, "_watch_user_index", lambda u: 0)
    import logging
    st, n = _Storage(), _Notifier()
    sent = webui._watch_alert_round(
        "u", n, st, logging.getLogger("v293-test"), base_url="")
    return sent, n


def test_watch_alert_uses_eff_not_raw_list_price(monkeypatch):
    # 裸价 1000 低于目标，但达标口径 eff=1050 未达标：不得推送
    sent, n = _alert(monkeypatch, 1000, 1050)
    assert sent == 0 and n.sent == []
    # eff 低于目标才推送
    sent, n = _alert(monkeypatch, 1000, 990)
    assert sent == 1 and len(n.sent) == 1


def test_probe_result_status_keeps_typed_failures():
    assert webui._probe_result_status([], [{"status": "unsupported"}]) == "unsupported"
    assert webui._probe_result_status([], [{"status": "parse_error"}]) == "parse_error"
    assert webui._probe_result_status([], [{"status": "session_busy"}]) == "session_busy"
    assert webui._probe_result_status([], [{"status": "timeout"}]) == "timeout"
    assert webui._probe_result_status([], [{"status": "empty"}]) == "empty"


def test_long_window_trend_applies_route_conditions(tmp_path):
    """30/90/180 天长窗日桶也必须套用直飞/航司/时段/价格/渠道条件。"""
    dbp = str(tmp_path / "trendlong.db")
    st = PriceStorage(dbp)
    day = datetime.now().strftime("%Y-%m-%d")
    rows = [
        ("MU5101", "09:00", "11:00", "", "", False, 1200),   # only survivor
        ("MU5102", "09:00", "11:00", "", "", True, 1100),    # stop
        ("CA5103", "09:00", "11:00", "", "", False, 1000),   # airline
        ("MU5104", "09:00", "11:00", "PVG", "", False, 900),  # transfer
        ("MU5105", "09:00", "11:00", "", "+1天", False, 1300),  # cross
        ("MU5106", "23:00", "23:59", "", "", False, 1400),   # dep window
        ("MU5107", "09:00", "11:00", "", "", False, 1600),   # price max
    ]
    with st._conn() as c:
        for code, dep, arr, trans, cross, stop, price in rows:
            key = webui._srx_flight_key({
                "from": "SHA", "to": "BJS", "date": _PAST6,
                "code": code, "depTime": dep, "arrTime": arr,
                "trans": trans, "cross": cross, "stop": stop})
            c.execute(
                "INSERT INTO flight_daily (from_city,to_city,depart_date,"
                "flight_key,cabin,day,platform,n,lo,hi,open,close,fetched_max)"
                " VALUES ('SHA','BJS','" + _PAST6 + "',?,'经济',?,'ctrip',1,?,?,?,?,?)",
                (key, day, price, price, price, price, day + " 10:00:00"))
    out = webui._trend_from_flights(
        st, "SHA", "BJS", _PAST6, 90,
        route={"direct_only": True, "exclude_stop": True, "no_cross": True,
               "airlines": "MU", "price_max": 1500,
               "dep_time_min": "06:00", "dep_time_max": "20:00",
               "channels": ["ctrip"]})
    assert out is not None
    assert out["direct"] == [[day, 1200.0, 0, 1200.0, 1200.0, 1200.0]]
    assert out["transfer"] == []


def test_rounds_respects_direct_only_route(tmp_path):
    dbp = str(tmp_path / "rounds.db")
    st = PriceStorage(dbp)
    extra = [
        {"code": "MU5101", "price": 1000, "depTime": "09:00",
         "arrTime": "11:00", "totalDuration": "2时"},
        {"code": "MU5102", "price": 800, "depTime": "08:00",
         "arrTime": "20:00", "transCity": "PVG",
         "totalDuration": "12时", "transitServiceLabel": "行李直挂"},
    ]
    st.save(FlightPrice("ctrip", "SHA", "BJS", _FUTURE, 1000,
                        extra=json.dumps(extra, ensure_ascii=False)))
    plain = _rounds(dbp, "SHA", "BJS", _FUTURE, "23:59", hours=48)
    gated = _rounds(dbp, "SHA", "BJS", _FUTURE, "23:59", hours=48,
                    rc={"direct_only": True})
    assert any(r[1] is not None for r in plain)
    assert any(r[2] is not None for r in plain)
    assert all(r[1] is not None for r in gated)
    assert all(r[2] is None for r in gated)
