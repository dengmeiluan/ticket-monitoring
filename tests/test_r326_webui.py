# -*- coding: utf-8 -*-
"""r326 WebUI 国际配置面四案源码钉（审计立案 P0-1/P1-2/P1-3/P2-4）。

- P0-1 保存校验 _cnorm 查国际字典 INTLN（航线段放开、特价段保持国内域）；
- P1-2 城市面板国际热门节按码查名走 INTL.map（INTLN 是名→码，方向反即恒空）；
- P1-3 buildForm 初始渲染链应用 syncRouteHead（徽标首渲即正确，改字段才亮的
  形态禁复活）；
- P2-4 城市面板搜索过滤覆盖热门区（漏过滤=热门城与「无匹配」横幅同屏）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r326_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


def _page():
    return webui.PAGE


def test_save_norm_resolves_intl_name_route_scope():
    src = _page()
    # 航线段三参调用（intl 门开）：国际中文名命中 INTLN 即规范名
    assert "_cnorm(r.from_name,r.from,1)" in src
    assert "_cnorm(r.to_name,r.to,1)" in src
    # 特价段保持国内域（两参调用，intl 门缺省关——国内特价源不收国际名）
    assert "_cnorm(sp0.from_name,sp0.from)" in src
    # 码回写链：CITY 名映射缺席时走 INTLN 名→码（国际名落码而非中文名）
    # R50 竞速终局随修：归一链尾回退原码槽（INTL 表未就绪竞速期
    # _cnorm 按码放行的名字，表缺查不到码时落回存量码槽而非名字——
    # 调度按码取键，名字当码会静默监控错城）
    assert "r.from=CITY[_fn]||INTLN[_fn]||r.from||_fn" in src
    assert "r.to=CITY[_tn]||INTLN[_tn]||r.to||_tn" in src


def test_city_panel_intl_hot_by_code_map():
    src = _page()
    # R36 双 Tab 后：国际目的地按地区分组渲染（INTL.map 直查码→名，
    # data-c=码小写供搜索），仍是码→名正向方向（非反方向查表）
    assert "Object.entries(INTL.map||{})" in src
    # 禁复活：反方向查表（名→码表查码）曾是 33 城全空恒空节
    assert "const n=INTLN[c]" not in src


def test_buildform_initial_render_applies_sync_route_head():
    src = _page()
    # buildForm 初始渲染链对每条航线应用 syncRouteHead——存量国际航线
    # 打开配置页徽标即亮，不再依赖「改任一字段」触发
    assert ("CFG.forEach((u,_ui)=>(u.routes||[]).forEach(("
            "_r,_uj)=>syncRouteHead(_ui,_uj)));") in src


def test_city_panel_filter_covers_hot_section():
    src = _page()
    # 过滤器显式处理热门区（在 .cp-sec 之外的同级容器）
    assert "const hot=$('cpbody').querySelector('.cp-hot');" in src
    assert "hotAny" in src
