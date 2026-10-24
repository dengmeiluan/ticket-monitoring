# -*- coding: utf-8 -*-
"""r238 WebUI 批（r237 挂账「href 双出口消毒不对称」本轮收口评估）：

- href 出口消毒统一：KPI 整卡 data-href 已挂 he()（r237 P2-2），
  但同链接族的属性直出形态三处未挂——numlink href="${brief.view}"
  （KPI 行1 价格链接）/ a.vw href="${x.view}"（同班比价展开行）/
  a.vw href="${f.view}"（明细行 ↗）。注入面=后端 _view_url 用
  config 城市名构造（自托管自配置、低危），收口价值在结构一致性：
  同一动态 URL 不应一半转义一半直出（形态演进时漏挂面翻倍）。
  he() 对合法 URL 是恒等变换（& → &amp; 浏览器 href 解析自动还原），
  零行为差异、防属性逃逸。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r238_webui.py -q
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_kpi_numlink_href_escaped():
    """KPI 行1 价格链接（numlink）href 挂 he()，与同卡 data-href 同律。"""
    src = _src()
    assert 'href="${he(brief.view)}"' in src, "numlink href 未挂 he()"
    assert 'href="${brief.view}"' not in src, "numlink href 直出旧形态残留"


def test_compare_row_vw_href_escaped():
    """同班比价展开行 a.vw href 挂 he()。"""
    src = _src()
    assert 'href="${he(x.view)}"' in src, "比价行 a.vw href 未挂 he()"
    assert 'href="${x.view}"' not in src, "比价行 href 直出旧形态残留"


def test_detail_row_vw_href_escaped():
    """明细行 ↗（a.vw）href 挂 he()。"""
    src = _src()
    assert 'href="${he(f.view)}"' in src, "明细行 a.vw href 未挂 he()"
    assert 'href="${f.view}"' not in src, "明细行 href 直出旧形态残留"


def test_demo_pushlog_titles_current_form():
    """DEMO pushlog 样例 title=现役可产出形态：达标/未达标锚点分支的
    尾段恒带「另监控」前缀（alerter._rest_seg 语义）——样例词面
    滞后会在烘焙演示站误导预览（审校 P3-2 同案）。"""
    src = _src()
    seg = src[src.index('"items": ['):src.index('"items": [') + 4000]
    assert seg.count("另监控") >= 2, "DEMO 样例 title 缺「另监控」段: %s" % seg[:600]
