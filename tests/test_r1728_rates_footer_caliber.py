# -*- coding: utf-8 -*-
"""r1728：三率脚注的口径必须分段——零出数通路是本页补的，不在基线口径里。

上一轮（eb5fffe）把「只有尝试、没有成功」的通路补进 by_path，但脚注
仍写「与基线报表同源」——对那 14 条零产出通路不成立：基线 `by_path()`
只统计 `path_status in OK_STATUSES`，它们的 yield/risk 是 rates 自己算的。
口径不许冒充。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


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
