# -*- coding: utf-8 -*-
"""r346 真实高频场景审计收口：同班比价身份、路径/监听自锁、移动端底栏遮挡。"""
import os

import webui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui.PAGE


# ---- 同班比价：身份必须含日期/航线/航班号，不能把不同航班串成一组 ----

def test_same_flight_fingerprint_includes_identity():
    s = _src()
    assert "const fp=f=>((f.cal?'cal':'')+'|'+(f.date||'')+'|'+(f.route||'')+'|'+(f.code||f.flightNo||f.name||'')" in s
    assert "（本行已是同班最低）" in s
    assert "xrowHtml(u,k,EXP===k,fp(f),f.price)" in s


def test_kpi_flights_include_date_and_exclude_calendar():
    s = _src()
    # r365：班次去重与 srxFlightKey 同源（航班号+日期+时刻+中转/跨天/经停）
    assert "function _flightUid(f)" in s and "srxFlightKey(f)" in s
    assert "flightNo||f.name" not in s[s.index("function _flightUid"):][:900]
    assert "rows.filter(f=>!f.cal).map(f=>_flightUid(f))" in s


# ---- Server酱：装配器不得漏 logger（旧路径 TypeError 后整通道静默失效） ----

def test_serverchan_build_passes_logger():
    text = open(os.path.join(ROOT, "core", "notifier.py"),
                encoding="utf-8").read()
    seg = text.split("primary = ServerChanNotifier(", 1)[1][:260]
    assert "logger=logger" in seg


# ---- 路径/监听：保存前拦截 Windows 非法名与不可绑定的 host ----

def test_bad_path_reason_rejects_windows_invalid():
    assert webui._bad_path_reason("D:/ok/prices.db") == ""
    assert "不允许的字符" in webui._bad_path_reason("D:/bad<x>/prices.db")
    assert "保留名" in webui._bad_path_reason("D:/tmp/CON.txt")
    assert "空格或句点" in webui._bad_path_reason("D:/tmp/abc. ")


def test_path_meta_marks_invalid():
    m = webui._path_meta("db", "D:/bad<x>/prices.db", {})
    assert m["invalid"] and "不允许的字符" in m["invalid"]
    assert m["writable"] is True  # 可写不代表合法，valid 由 invalid 先否决


def test_path_check_rejects_duplicate_storage_target():
    s = open(webui.__file__, encoding="utf-8").read()
    assert '与「%s」路径相同，请换一个位置' in s
    assert 'elif valid and meta.get("exists") and not meta.get("writable")' in s


def test_host_save_has_bind_preflight():
    s = open(webui.__file__, encoding="utf-8").read()
    assert "_probe.bind((_h, 0))" in s
    assert "监听地址不可用（本机没有该地址" in s
    assert "function setHost(el)" in _src() and "只支持 IPv4 或主机名" in _src()


# ---- 日期：两面板提示各说各的话；清空走确认层 ----

def test_date_hints_are_mode_specific():
    s = _src()
    assert "const rangeHint=" in s and "const singleHint=" in s
    assert '<span class="dquickhint">${rangeHint}</span>' in s
    assert '<span class="dquickhint">${singleHint}</span>' in s


def test_clear_dates_confirms_before_wipe():
    s = _src()
    assert "function clearDates(prefix,i,j,force)" in s
    assert "清空全部出发日期？" in s and "清空日期" in s
    assert "clearDates(prefix,i,j,true)" in s


# ---- 移动端：保存条不挡、toast 不吞点击、筛选有出口 ----

def test_savebar_left_dock_and_single_row_mobile():
    s = _src()
    assert ".savebar{left:18px;right:auto}" in s
    assert "flex-wrap:nowrap;gap:8px;padding:8px 10px" in s
    assert "#toasts{top:calc(var(--hdh,54px) + 12px)" in s


def test_mobile_filter_has_result_exit():
    s = _src()
    assert 'id="fdrawerCta"' in s and "function closeFltShow()" in s
    assert "body:has(.fbar.open) .fdrawer-cta{display:flex" in s
    assert "const _fd=document.getElementById('fdCount');if(_fd)_fd.textContent=rows.length;" in s


def test_email_title_ellipsis_and_start_scroll():
    s = _src()
    assert '<span class="ch-title">邮件·' in s
    assert ".chhead .ch-title{flex:1 1 0;width:0;min-width:0;overflow:hidden" in s
    assert "scrollIntoView({block:'start',behavior:'smooth'})" in s


# ---- 重启/保存：差量确认层 + 待重启文案不再谎称全部热生效 ----

def test_restart_uses_confirm_and_lists_diff():
    s = _src()
    assert "function doRestart(b)" in s and "async function doRestartNow(b)" in s
    assert "本次差量：\\n" in s
    assert "openConfirm('重启监控进程？'" in s


def test_save_feedback_respects_restart_required():
    s = _src()
    assert "项启动级配置需重启生效" in s
    assert "try{renderRestartCenter();}catch(e){}" in s


def test_route_summary_counts_semantic_terms():
    s = _src()
    assert "if(r.direct_only)n++;" in s
    assert "out.push('只要直飞')" in s
    assert "out.push('次日≤'+r.transfer_arrival_max)" in s
    assert ".rthead .rfsum{flex:1 1 auto;min-width:0" in s


def test_route_toggle_feedback_and_action_gap():
    s = _src()
    assert "航线已停用：保留全部配置" in s
    assert ".rhead .rop{gap:8px;row-gap:6px}" in s


def test_invalid_preview_never_claims_migration():
    s = _src()
    assert "if(!j.valid)bits.push('目标不可用：请先修正后再保存/重启')" in s
    assert "if(j.valid===false){" in s and '<span class="warn">' in s


def test_bad_host_border_global():
    s = _src()
    # 全档规则在媒体块外（桌面/窄档同红边）
    assert " .glcell input.bad,.pathcard input.bad{border-color:var(--red)!important" in s


def test_storage_save_error_rejects_bad_and_duplicate():
    bad = {"output": {"db_path": "D:/bad<x>/prices.db",
                      "log_path": "logs/monitor.log"},
           "crawler": {"user_data_dir": "user_data", "browser_dir": ""}}
    assert "不允许的字符" in webui._storage_save_error(bad)
    dup = {"output": {"db_path": "data/prices.db",
                      "log_path": "data/prices.db"},
           "crawler": {"user_data_dir": "user_data", "browser_dir": ""}}
    assert "不能使用同一路径" in webui._storage_save_error(dup)
    ok = {"output": {"db_path": "data/prices.db",
                     "log_path": "logs/monitor.log"},
          "crawler": {"user_data_dir": "user_data", "browser_dir": ""}}
    assert webui._storage_save_error(ok) == ""


def test_restart_invalid_path_no_migration_claim():
    s = _src()
    assert "if(j.valid===false){el.innerHTML='<span class=\"warn\">目标不可用：" in s
    assert "（不会搬迁/不会生效）" in s
    assert "const _pending=new Set([..._schg,...((RESTART&&RESTART.changed)||[])])" in s
