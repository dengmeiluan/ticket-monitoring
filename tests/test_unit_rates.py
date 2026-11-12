# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1183_rates_page.py
- tests/test_r1728_rates_footer_caliber.py
- tests/test_r1731_rates_halt_mark.py
- tests/test_r1833_rates_caliber_ui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import sys
import urllib.request


# ---- merged from tests/test_r1183_rates_page.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_endpoint_exists():
    assert '"/api/three-rates"' in WEBUI
    assert "from core import rates as _rt" in WEBUI


def test_card_exists_and_is_collapsed():
    assert 'id="ratesCard"' in WEBUI
    assert "function loadRates(" in WEBUI and "function toggleRates(" in WEBUI
    i = WEBUI.find('id="ratesBody"')
    assert 'display:none' in WEBUI[i:i + 60], "三率表默认必须收起"


def test_page_does_not_recompute_rates():
    """负控：页面里不许出现自己算爬取率/风险的分母。"""
    i = WEBUI.find("function loadRates(")
    seg = WEBUI[i:i + 2600]
    assert "attempts*" not in seg and "/attempts" not in seg, "页面在自己算爬取率"
    assert "fetch_paths" not in seg, "页面直接查库了（应该只读接口）"
    assert "/api/three-rates" in seg, "页面没有读接口"


def test_no_second_sql_first_class_citizen():
    """`core/rates.py` 不许再写一份 `path_status in ('ok','calendar')` 的字面量。"""
    src = io.open(os.path.join(ROOT, "core", "rates.py"), encoding="utf-8").read()
    assert "baseline.by_path(" in src, "rates 没有复用 baseline.by_path（口径会漂）"
    assert '"ok","calendar"' not in src.replace(" ", ""), "rates 里出现了第二份状态字面量"


# ---- merged from tests/test_r1728_rates_footer_caliber.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_footer_separates_two_calibers():
    s = _w()
    i = s.index("口径：爬取率=出数次数")
    seg = s[i:i + 420]
    assert "与基线报表同源" in seg, "脚注丢了基线口径说明"
    assert "零出数通路" in seg, "脚注没说明零出数通路是本页补的"
    assert "由本页补出" in seg, "没说清哪一部分不是基线口径"
    assert "基线只统计成功状态" in seg, "没说明基线为何缺这些行"


def test_footer_no_longer_claims_blanket_same_source():
    s = _w()
    i = s.index("口径：爬取率=出数次数")
    seg = s[i:i + 300]
    # 旧的整句（把零出数行也算作基线口径）必须已经拆开
    assert "；与基线报表同源。</div>" not in seg, \
        "仍是「所有行都与基线同源」的旧写法"


# ---- merged from tests/test_r1731_rates_halt_mark.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_backend_attaches_halts():
    s = _w()
    i = s.index('self.path.split("?")[0] == "/api/three-rates"')
    seg = s[i:i + 2200]
    assert '_sn3["halts"]' in seg, "three-rates 载荷没有 halts"
    assert "read_halt" in seg, "没有读真实停手表"


def test_table_marks_halted_plats():
    s = _w()
    assert "rt-halt" in s, "三率表没有停手标记样式/类"
    # JS 用法（不是第一条 CSS 命中）
    i = s.index("RATES.halts")
    seg = s[max(0, i - 400):i + 500]
    assert "rt-halt" in seg, "读了 halts 但没渲染停手标记"
    assert "停手" in seg, "没有「停手」字样"


def test_live_halts_shape():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/three-rates",
                               timeout=25).read())
    except Exception:
        return
    assert "halts" in d, "载荷缺 halts 字段"
    for p, h in (d.get("halts") or {}).items():
        assert h.get("left_s", 0) > 0, (p, h)


# ---- merged from tests/test_r1833_rates_caliber_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_footer_reports_skipped_count():
    s = _w()
    assert "未计入分母" in s, "页脚没有说剔掉多少条"
    assert "t.skipped_n" in s, "没有用载荷里的 skipped_n"
    assert "能力边界与主动跳过不计入分母" in s, "口径说明没跟上"


def test_waste_excludes_halted():
    s = _w()
    i = s.index("let _waste=null")
    seg = s[i:i + 400]
    assert "_halts[k]" in seg, "空转最贵没有排除停手渠道"
    assert "return" in seg, "排除没生效（缺 continue/return）"


def test_payload_has_skipped_n():
    import json
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/three-rates",
                               timeout=25).read())
    except Exception:
        return
    t = d.get("totals") or {}
    assert "skipped_n" in t, "totals 缺 skipped_n：%s" % list(t)[:8]
