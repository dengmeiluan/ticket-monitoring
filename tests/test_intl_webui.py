# -*- coding: utf-8 -*-
"""r325 国际航班 WebUI 呈现面源码钉（INTL_DESIGN §3 高级便捷交互）。

- 城市面板「🌐 国际目的地」页签（全量字典按名排序）：码搜索 data-c +
  名称→码回填（INTLN）；
- 配置行头「国际」徽标：isIntlCode 凭 /api/config intl.mainland 全集
  自动判定（零配置语义的呈现面半边），syncRouteHead 同步翻转；
- /api/config 载荷带 intl（map/hot/mainland）双站点（demo+生产）；
- 明细行国际 tag（紫系 t-i）+「含税」词面 + 行级 intl/tax 字段透传。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


def _mod_src():
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_city_panel_intl_section():
    src = webui.PAGE
    # R36 双 Tab：国际 Tab 按地区分组渲染（data-l="INTL:${r}"），码搜索
    # data-c + 名称→码回填（INTLN）齐
    assert 'data-l="INTL:${r}"' in src
    assert 'data-c="${esc(String(c).toLowerCase())}"' in src
    assert "INTLN=Object.fromEntries" in src


def test_set_route_resolves_intl_name_to_code():
    src = webui.PAGE
    # 城市输入双向归一（r355）：中文名或三字码都必须同时回填身份码与展示名。
    assert "function cfgCityLookup(v)" in src
    assert "if(a.code){r.from=a.code;r.from_name=a.name}" in src
    assert "if(b.code){r.to=b.code;r.to_name=b.name}" in src
    assert "INTLN[n]||''" in src or "INTLN[n]" in src


def test_route_head_intl_badge_autodetect():
    src = webui.PAGE
    # 徽标元素初始态即按判定渲染（校准 R14 定谳：模板写死 display:none
    # 曾使首次 buildForm 后徽标恒隐，直到首次 setRoute 才被 syncRouteHead
    # 翻转）+ 同步翻转 + 判定单源（大陆码全集来自服务端下发）
    assert "display:${(isIntlCode(r.from)||isIntlCode(r.to))?'':'none'}" in src
    assert "isIntlCode(r.from)||isIntlCode(r.to)" in src
    assert "function isIntlCode(c)" in src
    assert "(INTL&&INTL.mainland)||[]" in src


def test_cfg_scope_tabs_wired():
    # R34 设计审计落地（对齐 ctrip/去哪儿 国内/国际双 Tab 习惯）：
    # 配置视图 scope 分 Tab 行 + 过滤函数 + buildForm 尾重渲保持
    src = webui.PAGE
    assert "cfgScopeSet" in src and "cfgScopeApply" in src
    assert "id=\"cfgScopeBar\"" in src
    # r348：范围/状态收进单行工具条——国际语义改挂在范围 chip 的
    # title 上，状态改下拉，避免两组「全部」同屏竞争
    assert 'aria-label="按航线范围筛选"' in src
    assert 'id="cfgStatusSel"' in src and "cfgStatusSet(this.value)" in src
    # buildForm 重渲尾保持当前 scope 过滤
    assert "cfgScopeApply();   /* scope 分 Tab：重渲后保持当前过滤（R34） */" in src


def test_city_panel_dual_tab_and_region():
    # R36 用户心智对齐（ctrip/去哪儿：先选国内/国际 Tab 再挑城市）：
    # 面板双 Tab 行 + intl Tab 地区分组渲染 + payload region 映射
    src = webui.PAGE
    assert "cityPanelTab('dom')" in src and "cityPanelTab('intl')" in src
    assert 'data-l="INTL:${r}"' in src          # 国际按地区分组渲染
    mod = _mod_src()
    assert '"region": INTL_REGION' in mod


def test_intl_region_complete_and_valid():
    from core.intl import INTL_CITY_NAME, INTL_REGION, INTL_REGIONS
    # 全量覆盖：177 目的地每城有地区
    unmapped = [c for c in INTL_CITY_NAME if c not in INTL_REGION]
    assert not unmapped, f"地区未覆盖: {unmapped}"
    assert "其他国际" in INTL_REGIONS
    # 抽样语义正确
    assert INTL_REGION["NRT"] == "日韩"
    assert INTL_REGION["LHR"] == "欧洲"
    assert INTL_REGION["HKG"] == "港澳台"
    assert INTL_REGION["JFK"] == "美洲"
    assert INTL_REGION["SYD"] == "大洋洲"
    assert INTL_REGION["CAI"] == "非洲"
    assert INTL_REGION["MLE"] == "南亚"


def test_intl_boot_fetch_before_cfg_view():
    # 校准 R14 定谳：INTL 装配曾只在 loadCfg（配置视图加载器）——
    # 监控引导态 INTL 恒 null → isIntlCode 对一切都真（纯国内用户
    # 每条航线常亮「国际」徽标）。启动一次性引导拉取必须存在
    src = webui.PAGE
    assert "INTL=j.intl||{map:{},hot:[],mainland:[]};" in src
    boot = src[src.index("let CFG=null,CITY={}"):]
    seg = boot[boot.index("(async function()"):boot.index("(async function()") + 320]
    assert "fetch('/api/config')" in seg and "INTLN=Object.fromEntries" in seg, \
        "INTL 启动引导拉取缺席（监控引导态徽标误亮回归）"


def test_config_payload_carries_intl_both_sites():
    # 双站点（demo/生产）都要带 intl 键——演示站漏键=首屏无国际页签
    # （载荷在 Python GET 处理器，读模块源非 PAGE 模板）
    assert _mod_src().count('"intl": _intl_payload()') >= 2


def test_detail_row_intl_tag_and_tax():
    src = webui.PAGE
    # 行头国际 tag（紫系第三色相）+ 次行含税词（前端模板；r326 A5
    # 起含税词面带 tooltip 消歧「含税总价口径下的税费构成」，防误读
    # 成含税总价）
    assert "f.intl?'<span class=\"tag t-i\"" in src
    assert ('f.intl?`<span title="国际行价格为含税总价口径，'
            '此为其中税费构成部分">含税${f.tax!=null?'
            "'￥'+he(String(f.tax)):''}</span>`:''") in src
    assert ".t-i{background:var(--fill-i)}" in src
    # 次行容器条件必须含 f.intl（校准 R10 定谳：飞猪日历行无舱位/
    # 时刻等任何触发键时容器整体不渲染，「含税」词段随之消失——
    # 真机走查抓到后补的条件槽）
    assert "||f.intl)?`<div class=\"stl\"" in src
    # 行级字段透传（Python 明细组装处，模块源）
    mod = _mod_src()
    assert '"intl": 1 if f.get("intl") else 0,' in mod
    assert '_num_or_none(f.get("tax"))' in mod


def test_intl_payload_shape():
    p = webui._intl_payload()
    assert p["map"]["NRT"] == "东京成田"
    assert "HKG" in p["hot"] and "NRT" in p["hot"]
    # 大陆码全集：SHA 在、HKG/TPE 不在（港台澳国际语义的判定根基）
    assert "SHA" in p["mainland"] and "PEK" in p["mainland"]
    assert "HKG" not in p["mainland"] and "TPE" not in p["mainland"]
