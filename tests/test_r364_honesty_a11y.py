# -*- coding: utf-8 -*-
"""r364 六路审计收口（只钉本轮新增语义，行为在 8765 实测）：

D1 渠道明示舱别优先于订座码（Ctrip A 码曾是「头等」，与详情/RAW/CSV
   的经济舱三处打脸）；D2 健康徽标分母回到全部尝试轮（36 轮仅日历
   时不再亮「明细 100%」）；D3 日 K 注记补「含日历价」；D4 达标 KPI
   同时给航班数与报价行数；A1 检索层打开时 `/` 不再拉背景焦点；
A2 详情页签回焦限定 `.srx-dtabs`；A3 城市面板 Tab 索引回绕 + 焦点
   兜底 + 真 tab 角色/方向键；M1 320 动作列 2×36 网格让出航班列；
M2 首屏动作横滚、320 航线 chip 横滚；M4 校准册轨道移动端不粘顶；
M5 移动端工具条直接给矩阵入口；P1 健康 SWR/日历 60s 缓存；P2 HEAD。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r364_honesty_a11y.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui.PAGE


def _source():
    return open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


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
    assert '#searchview .srx-row{grid-template-columns:24px minmax(0,1fr) auto 75px;gap:4px}' in s
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
    assert 'self.send_header("Vary", "Accept-Encoding")' in s[j:j + 1900]
