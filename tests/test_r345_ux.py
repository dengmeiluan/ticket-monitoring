# -*- coding: utf-8 -*-
"""r345 心智模型与审计收口：日期模式条/渠道如实态/明细筛选与 KPI/迁移透明化。

这些钉锁的是「用户一次只操作一种日期录入方式」「假绿通道如实标待完善」
以及本轮 5 路审计的 P0/P1 修复，防止后续视觉迭代把语义改回旧形态。
"""
import os
import sys

import webui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui.PAGE


# ---- 日期：模式互斥 + 双草稿保留 + 加入=合并去重 ----

def test_date_mode_switch_single_editor():
    s = _src()
    assert "function _dateRowHTML(" in s
    assert 'data-dm="range"' in s and 'data-dm="single"' in s
    assert "function setDateMode(" in s
    assert "function dateTabKey(" in s
    assert ".dpanel[hidden]{display:none}" in s
    # 旧双卡常显与工具行彻底退役
    assert ".dline.dtools" not in s
    assert "dtools-t" not in s
    assert "class=\"dtool\"" not in s
    # 两模式面板同体：固定一行输入 + 共享快捷/应用脚
    assert ".dpanel-row{display:grid" in s
    assert ".dcompose-foot{display:flex" in s


def test_date_apply_merges_not_replaces():
    s = _src()
    assert "function _mergeDates(" in s and "function _commitDates(" in s
    assert "rs.dates=u.dates" in s
    assert "_commitDates('d',i,j,ds,'未来'+days+'天')" in s
    assert "_commitDates('d',i,j,ds,'区间 '+a+' 至 '+b)" in s
    # 单日显式加入，不再 change 即写模型
    assert 'onchange="if(this.value)addDate' not in s
    assert 'onchange="if(this.value)retAdd' not in s
    assert "if(_commitDates('r',i,j,[v],'已加入返程 '+v))_focusDateInput" in s


def test_date_mode_has_aria_and_keyboard():
    s = _src()
    assert 'role="tablist"' in s
    assert 'aria-controls="dpan-${p}-${i}-${j}-range"' in s
    assert "ArrowLeft" in s and "Home" in s and "End" in s
    assert "aria-label=\"${title}添加方式\"" in s


# ---- 渠道：开关×必需凭据=已启用，否则如实「待完善」 ----

def test_channel_readiness_is_honest():
    s = _src()
    assert "function _chReady(" in s
    assert "function _chLbl(" in s
    assert "x.enabled&&s(x.webhook)" in s
    assert "x.enabled&&s(x.send_key)" in s
    assert "em.enabled&&s(em.user)&&s(em.password)&&s(em.to)" in s
    assert ".chcard.todo{" in s and ".lgdot.mid{" in s
    assert "推送已就绪" in s and "推送待完善" in s


def test_email_add_focus_and_secret_masked():
    s = _src()
    assert "input[placeholder^=\"you@\"]" in s
    assert "if(inp)setTimeout(()=>inp.focus({preventScroll:true}),160)" in s
    assert 'id="dtsecret-${i}" type="password"' in s
    assert "function togglePw(" in s


def test_confirm_focus_cancel_and_trap():
    s = _src()
    assert "const b=$('cmCancel');if(b)b.focus" in s
    assert "e.key==='Tab'" in s and "last.focus()" in s
    assert 'aria-describedby="cmText"' in s


# ---- 明细：筛选语义与计数口径 ----

def test_detail_free_baggage_excludes_negative_text():
    s = _src()
    assert "function _hasFreeBag(" in s
    assert "(?:无|不含|需另购|另购|收费)(?:免费)?(?:托运|行李)" in s
    assert "FLT.bag&&!_hasFreeBag(f)" in s


def test_detail_reset_clears_bagkg_wb_and_chips():
    s = _src()
    assert "FLT.bagkg=0;FLT.wb=false;" in s
    assert "saveUI();buildChips();buildDateChips();buildRouteChips();table()" in s


def test_detail_search_group_not_coupled_to_price():
    s = _src()
    assert "out.push({g:'q',label:'搜索「'+FLT.q+'」'})" in s
    assert "else if(g==='q'){FLT.q='';syncFltInputs();}" in s


def test_detail_kpi_quote_and_flight_units():
    s = _src()
    assert "function _flightUid(" in s
    assert "条报价 / '+_qn+' 班" in s
    assert "!f.xphan" in s


def test_detail_safe_and_few_cover_words():
    s = _src()
    assert "f.lurePrice!=null||f.ticketRisk" in s
    assert "f.fewTicket||(f.leftTickets>0&&f.leftTickets<10)" in s


def test_detail_compare_current_row_savings():
    s = _src()
    assert "function xrowHtml(u,k,open,grp,curPrice)" in s
    assert "（本行已是同班最低）" in s
    assert "（换最低渠道可省 ￥${save}）" in s
    assert "xrowHtml(u,k,EXP===k,fp(f),f.price)" in s


def test_detail_mobile_overflow_and_touch_fixes():
    s = _src()
    assert ".attrgrid .ag-wide .attrq{flex:0 0 104px;width:104px;min-width:0" in s
    assert "#alchips{flex:1 1 0;min-width:0}" in s
    assert ".chiplab{font-size:12px;color:var(--mut);flex:none;white-space:nowrap}" in s
    assert "@media(max-width:900px) and (pointer:coarse){\n   .fltpreset{min-height:36px" in s
    assert ".tw.xend::after{opacity:0}" in s


# ---- 全局：路径待创建/启动项/运行时透明化 ----

def test_path_meta_creatable_under_missing_parent(tmp_path):
    m = webui._path_meta("ud", str(tmp_path / "notyet" / "user_data"), {})
    assert m["ok"] is True
    assert m["exists"] is False
    assert m["parent_exists"] is False
    assert m["creatable"] is True
    assert m["ancestor_writable"] is True


def test_storage_target_status_and_writable_labels():
    s = _src()
    assert "当前 · " in s and "目标 · " in s
    assert "可写 · 待创建" in s
    assert "父目录尚不存在，重启时自动创建" in s
    assert "最近的可写祖先不存在，无法创建" in s


def test_startup_keys_include_host_and_run_on_start():
    s = _src()
    assert "'db_path','log_path','user_data_dir','browser_dir','host','run_on_start'" in s
    vals = webui._startup_vals(
        {"web": {"host": "0.0.0.0"}, "schedule": {"run_on_start": False}})
    assert vals["host"] == "0.0.0.0"
    assert vals["run_on_start"] is False


def test_runtime_identity_fields():
    s = _src()
    for token in ("listen", "started_at", "tz", "argv", "copyText(", "监听 "):
        assert token in s, token


def test_restart_center_non_path_rows():
    s = _src()
    assert "labels={db_path:'数据库'" in s and "host:'控制台监听地址'" in s
    assert "非路径启动项：保存后需重启进程生效，无文件搬迁。" in s


def test_version_bumped():
    text = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert '__version__ = "1.5.295"' in text
