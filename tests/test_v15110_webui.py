# -*- coding: utf-8 -*-
"""本轮 WebUI 层源码钉（前轮挂账三备案收口 + 预览对齐）：

1. KPI 按日期 delta（审计 Minor-2 备案）：dgroup 分支传 delta_by_date，
   后端 _delta_vs_prev 按 routes_arr date 精确匹配（单航线多日期时
   brief.route 为空串，label 匹配会错配到首日期序列）。
2. 移动端日期排序入口（审计 Minor-3 备案）：≤760 日期列隐藏后表头
   sortCol 入口消失，日期 chips 行尾补「⇅日期」chip 与 sortCol
   单源；箭头 data-dir 属性驱动 CSS content（点击路径零 childList
   变更——扩展 MutationObserver 免疫预置律）。
3. 预览器多日期拆条（推送审校备案）：_preview_payload 逐日期独立
   成 entry，对齐生产 main.py 按查询日期逐条喂条的形状。

钉面分层：JS/CSS 断言走 webui.PAGE（内嵌 SPA 字符串）；Python
后端断言读模块源文件（PAGE 不含 Python 段）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15110_webui.py -q
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_delta_by_date_payload_built():
    """载荷带 delta_by_date：按日期匹配 routes_arr（date 参数路径）。"""
    assert '"delta_by_date"' in _src()
    assert '_delta_vs_prev(b, "direct", d)' in _src()


def test_delta_vs_prev_date_match_precedes_label():
    """date 精确匹配先于 label 匹配：单航线多日期 route='' 时
    不得错配 routes_arr[0] 的序列。"""
    src = _src()
    i_date = src.find('if r.get("date") == date')
    i_label = src.find('if r["label"] == brief["route"]')
    assert i_date != -1 and i_label != -1 and i_date < i_label


def test_dgroup_kpi_passes_delta_by_date():
    """前端 dgroup 分支传 dDl[d]/dTl[d]（恒 null 曾让多日期概览
    无任何涨跌信息）；demo/旧快照无字段时安全退化。"""
    import webui
    assert "(x.delta_by_date||{}).direct||{}" in webui.PAGE
    assert "kpiCard('d',dd,dth,'直飞最低',dDl[d],d)" in webui.PAGE


def test_srtchip_single_source_sortcol():
    """「⇅日期」chip 点击走 sortCol('date') 单源（与表头同一
    SORT 状态机），箭头 data-dir 属性驱动。"""
    import webui
    assert "function dateSortChip(el){sortCol('date');" in webui.PAGE
    assert '.srtchip[data-dir="asc"] .arr::after{content:"↑"}' \
        in webui.PAGE


def test_srtchip_visible_only_le760():
    """chip 默认隐藏（桌面表头入口在），≤760 媒体块显示（日期列
    隐藏的对称补偿）——两处声明各自在其媒体语境生效。"""
    import webui
    assert " .srtchip{display:none}" in webui.PAGE
    assert "  .srtchip{display:inline-block}" in webui.PAGE


def test_preview_payload_splits_per_date():
    """预览逐日期独立成 entry（与生产逐日期喂条形状对齐）；
    Route 构造保持在日期循环外（_digest_payload 的 hit_routes
    id 恒等依赖，推送审校预演护栏）。"""
    src = _src()
    assert 'for d in rv["dates"]:' in src
    assert "prices = [FlightPrice(" in src
    i_route = src.find("route = Route(")
    i_loop = src.find('for d in rv["dates"]:', max(0, i_route - 400))
    assert i_route != -1 and i_loop != -1 and i_route < i_loop


def test_top_best_delta_carries_date():
    """顶层 best 卡 delta 按所属日期精确匹配（单航线多日期 route
    为空串时 label 回退会错配首日期序列——既有潜伏同轮收口）。"""
    src = _src()
    assert '"date": (f.get("depDate") or "")}' in src
    assert '(bd_brief or {}).get("date")' in src
    assert '(xt_brief or {}).get("date")' in src


def test_zero_childlist_sort_chip_path():
    """排序 chip 就地更新只走 classList/setAttribute/dataset
    （零 childList）；函数体（至下一函数边界）内不得出现
    innerHTML/textContent 重建。"""
    import webui
    i = webui.PAGE.find("function dateSortChip(el){")
    assert i != -1
    j = webui.PAGE.find("\nfunction togDate", i)
    assert j != -1
    seg = webui.PAGE[i:j]
    assert "innerHTML" not in seg and "textContent" not in seg


# ---- EN-3 航线维度 URL 深链（#tab/uN） ----

def test_hash_user_deep_link_write():
    """pickUser 写 #tab/uN 深链（曾只有 tab 级，航线选择不可分享）。"""
    import webui
    assert "history.replaceState(null,'','#'+MONTAB+'/u'+i)" in webui.PAGE


def test_hash_user_restore_after_restoreui():
    """启动恢复在 restoreUI 之后（否则 localStorage U 覆盖 hash）。"""
    import webui
    src = webui.PAGE
    i_restore = src.find("restoreUI();mkactAll();")
    i_hash_u = src.find("深链用户段恢复")
    assert i_restore != -1 and i_hash_u != -1 and i_restore < i_hash_u


def test_hashchange_user_seg_parse():
    """hashchange 活页解析 /uN 段：越界忽略（不钳 0 乱切）。"""
    import webui
    assert "_un<S.users.length)pickUser(_un)" in webui.PAGE


# ---- EN-4 行展开态持久化 ----

def test_expand_state_persisted():
    """EXP/TGOPEN 入 saveUI 序列化 + restoreUI 类型守卫回填。"""
    import webui
    assert "chr:CHR,exp:EXP,tg:TGOPEN}" in webui.PAGE
    assert "if(typeof j.exp==='string')EXP=j.exp;" in webui.PAGE
    assert "if(typeof j.tg==='string')TGOPEN=j.tg;" in webui.PAGE


def test_expand_state_all_exit_paths_persist():
    """持久化全出口对称（Soldier P2-2）：开（togRow/togGo 主路）、
    收（各自 toggle 回同键分支）、Esc 级联清（键盘 Esc 分支）三条
    退出路径全部落盘——收起不落盘则 localStorage 残旧键、刷新复开。
    r220 affordance 轮：各收路同轮补 _ariaOff() 态回写（落盘语义不变）。"""
    import webui
    assert "if(EXP===k){EXP=null;if(cur)cur.style.display='none';_ariaOff();saveUI();return;}" \
        in webui.PAGE
    assert "if(TGOPEN===k){TGOPEN=null;if(tg)tg.style.display='none';saveUI();return;}" \
        in webui.PAGE
    assert "if(EXP){EXP=null;_hideXrows();_ariaOff();saveUI();}" in webui.PAGE
    assert "if(TGOPEN){TGOPEN=null;_hideXrows();saveUI();}" in webui.PAGE
