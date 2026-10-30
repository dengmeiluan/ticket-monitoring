# -*- coding: utf-8 -*-
"""r298 WebUI 三案（TDD 先行；立案 _scratch/r298_webui/report.md）：

P1-1 qunar 用户侧跳转链接=触屏 H5 列表页（crawlers/qunar.py URL_TPL
同参同源）：PC 列表页对真人浏览器 302 回首页（搜索上下文全丢=页壳
死），爬虫取数亦由 H5 兜底承载——链接与取数同源（渠道 PC 化挂羊头
判例 LESSONS 十四§6 的反向回退面：只按正向执行过会漏反向回退）。

P1-2 概览红帽徽标 ovAlert 结构性零宽：空 <i> 内联元素 width 不参与
布局，点亮态实际盒 0×16px、任意主题从未渲染出形状——CSS 补
inline-block 形状 + 卡色描边（激活蓝底上红点对比 1.02/1.60:1 双欠
WCAG 3:1，卡色描边才是辨识主体）。

P2-1 航线摘要词面 _routes_txt 单源：同城市对聚合一段、日期随组——
逐航线直拼曾产出「上海→海口、上海→海口、海口→上海」同对重复观感
且日期缺席（停用卡带日期、在役卡不然的双口径并存）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r298_webui.py -q
"""
import sys
import os
import logging
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

from core.models import Route            # noqa: E402
from core.alerter import Alerter         # noqa: E402
import webui                             # noqa: E402


def _route():
    return Route(from_code="SHA", from_name="上海", to_code="HAK",
                 to_name="海口", dates=["2027-01-29"])


def test_qunar_view_url_h5_listpage():
    """2026-10-10 起 qunar PC 单程页 302 回官网首页（断供）；
    用户链接改指 m.flight H5 列表页，与爬虫 URL_TPL 同参。
    其余渠道出口不回归。"""
    a = Alerter(logging.getLogger("t"), storage=None)
    u = a._build_view_url(_route(), "2027-01-29", "qunar")
    assert "m.flight.qunar.com/ncs/page/flightlist" in u, u
    assert "flight.qunar.com/site/oneway_list.htm" not in u, u
    assert ("depCity=" + quote("上海")) in u, u
    assert ("arrCity=" + quote("海口")) in u, u
    assert "goDate=2027-01-29" in u, u
    from crawlers.qunar import QunarCrawler as QC
    for kv in QC.URL_TPL.split("?", 1)[1].split("&"):
        key = kv.split("=")[0]
        assert (key + "=") in u, (key, u)
    # 其余渠道出口不回归
    assert "m.ctrip.com" in a._build_view_url(_route(), "2027-01-29", "ctrip")
    assert "m.ly.com" in a._build_view_url(_route(), "2027-01-29", "tongcheng")
    assert "m.tuniu.com" in a._build_view_url(_route(), "2027-01-29", "tuniu")
    assert "sjipiao.fliggy.com" in a._build_view_url(
        _route(), "2027-01-29", "fliggy")


def test_no_dead_pc_list_link_in_page():
    """2026-10-10 起 qunar PC 单程页 302 回 www.qunar.com 促销聚合，
    `flight.qunar.com/site/oneway_list.htm` 是死链；webui.py 与
    docs/site 烘焙产物统一改指 m.flight H5 列表页。"""
    import os
    with open(webui.__file__, encoding="utf-8") as f:
        assert "flight.qunar.com/site/oneway_list.htm" not in f.read(),             "webui 残留 PC 死链形态"
    site = os.path.join(os.path.dirname(webui.__file__),
                        "site", "index.html")
    if os.path.isfile(site):
        with open(site, encoding="utf-8") as f:
            assert "flight.qunar.com/site/oneway_list.htm" not in f.read(),                 "烘焙态残留 PC 死链（删 demo .statecache 后重烘）"


def test_routes_txt_grouping():
    """P2-1：同城市对聚合一段、日期随组（MM-DD 短形）；跨条目同对
    日期并档；空日期组回退裸对；段内不出现分隔符「、」（前端按「、」
    切段逐段 nowrap）。"""
    routes = [
        {"from_name": "上海", "to_name": "海口",
         "dates": ["2027-01-29", "2027-01-30"]},
        {"from_name": "上海", "to_name": "海口", "dates": ["2027-02-13"]},
        {"from_name": "海口", "to_name": "上海", "dates": ["2027-02-14"]},
    ]
    t = webui._routes_txt(routes)
    assert t == "上海→海口 01-29/01-30/02-13、海口→上海 02-14", t
    assert webui._routes_txt([]) == ""
    assert webui._routes_txt([{"from_name": "上海", "to_name": "海口",
                               "dates": []}]) == "上海→海口"
    for seg in t.split("、"):
        assert "、" not in seg


def test_routes_txt_cap_three_entries():
    """P2-1：截前面 [:3] 语义维持（条目级截断，分组在其后）。"""
    routes = [{"from_name": f"城{i}", "to_name": "目标",
               "dates": ["2027-01-29"]} for i in range(5)]
    t = webui._routes_txt(routes)
    assert t.count("、") == 2, t
    assert "城3" not in t and "城4" not in t, t


def test_routes_txt_in_group_dedup():
    """P2-1：组内日期去重（同对跨条目重复日期只出现一次—— Soldier
    变异「去重去除」的存活缺口补钉；重复配置条目是现实可达形态）。"""
    routes = [
        {"from_name": "上海", "to_name": "海口",
         "dates": ["2027-01-29", "2027-01-30"]},
        {"from_name": "上海", "to_name": "海口",
         "dates": ["2027-01-30", "2027-02-13"]},
    ]
    t = webui._routes_txt(routes)
    assert t == "上海→海口 01-29/01-30/02-13", t
    assert t.count("01-30") == 1, t


def test_suspended_users_routes_txt_same_source():
    """P2-1 停用卡同源：分组词面与在役卡一致（双口径漂移防线）。"""
    out = webui._suspended_users([{"name": "张三"}], [{
        "name": "张三",
        "routes": [
            {"from": "SHA", "from_name": "上海", "to": "HAK",
             "to_name": "海口", "dates": ["2027-01-29"], "enabled": False},
            {"from": "HAK", "from_name": "海口", "to": "SHA",
             "to_name": "上海", "dates": ["2027-02-14"], "enabled": False},
        ]}])
    assert len(out) == 1 and out[0]["n"] == 2, out
    assert out[0]["routesTxt"] == "上海→海口 01-29、海口→上海 02-14", out


def test_ovalert_css_shape_rule():
    """P1-2：红点形状单源——inline-block 使 width 参与布局（内联盒
    定律：空 <i> 的 7px 宽曾是死档），卡色描边在激活蓝底上以描边对比
    达 3:1 辨识（红点本身对激活底 1.02/1.60:1 双欠）。"""
    src = webui.PAGE
    assert "#ovAlert{display:inline-block" in src, "形状规则缺席"
    rule = [ln for ln in src.splitlines() if "#ovAlert{display:inline-block" in ln]
    assert rule and "box-shadow" in rule[0] and "var(--card)" in rule[0], rule
