# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_distance_advice.py
- tests/test_r1063_distance_advice_jump.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import sqlite3
import sys

from core.advise import distance_advice


# ---- merged from tests/test_r1063_distance_advice.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _db(tmp_path, rows, name="x.db"):
    """rows: [(plat, depart_date, path_status, n)]"""
    p = os.path.join(str(tmp_path), name)
    c = sqlite3.connect(p)
    c.execute("""create table fetch_paths(
        platform text, depart_date text, path_status text, fetched_at text)""")
    for plat, dd, st, n in rows:
        for _ in range(n):
            c.execute("insert into fetch_paths values(?,?,?,datetime('now'))",
                      (plat, dd, st))
    c.commit()
    c.close()
    return p


def _d(offset, today=None):
    import datetime as dt
    return ((today or dt.date.today()) + dt.timedelta(days=offset)).isoformat()


def test_flags_near_good_far_bad(tmp_path):
    db = _db(tmp_path, [
        ("tuniu", _d(7), "ok", 10),
        ("tuniu", _d(80), "timeout", 10),
    ])
    got = distance_advice(24, db=db)
    assert len(got) == 1 and got[0]["plat"] == "tuniu", got
    assert got[0]["near_pct"] == 100 and got[0]["far_pct"] == 0
    assert "交浏览器" in got[0]["text"]


def test_ignores_platform_bad_on_both_ends(tmp_path):
    """近端也不行（<60%）→ 不是"远日期"问题，不许建议收窄。"""
    db = _db(tmp_path, [
        ("app_ctrip", _d(7), "timeout", 10),
        ("app_ctrip", _d(80), "timeout", 10),
    ])
    assert distance_advice(24, db=db) == []


def test_ignores_small_gap_and_small_samples(tmp_path):
    # 差距只有 10pp（近端 100% vs 远端 90%）
    db = _db(tmp_path, [("fliggy", _d(7), "ok", 20),
                        ("fliggy", _d(80), "ok", 18),
                        ("fliggy", _d(80), "timeout", 2)])
    assert distance_advice(24, db=db) == []
    # 远端样本不足
    db2 = _db(tmp_path, [("ctrip", _d(7), "ok", 20),
                         ("ctrip", _d(80), "timeout", 2)], name="x2.db")
    assert distance_advice(24, db=db2) == []


def test_panel_surfaces_it(tmp_path):
    import io
    w = webui_full_src()
    assert 'data["distance_advice"]' in w
    assert 'const _d=(j&&j.distance_advice)||[]' in w, \
        "前端要把距离建议拼进「建议」行（不加行，窄档才稳）"


# ---- merged from tests/test_r1063_distance_advice_jump.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_advice_renders_clickable_link():
    w = _w()
    assert "srxDistJump" in w
    i = w.index("const a2=a.concat(_d.map(")
    seg = w[i:i + 900]
    assert "srxDistJump" in seg, "距离建议项要带链接"
    assert "不会替你改配置" in seg, "title 要说清不会自动改配置"


def test_jump_opens_page_container_and_globals_tab():
    w = _w()
    i = w.index("function srxDistJump(")
    seg = w[i:i + 900]
    assert "document.getElementById('cfgview')" in seg, \
        "必须打开页级容器 #cfgview，否则看不见"
    assert "showCfgPanel('globals')" in seg, "要切到全局参数"
    assert "panel-globals" in seg, "字段定位容器改为 #panel-globals"


def test_jump_is_read_only():
    """跳转函数里不得出现任何配置写入。"""
    w = _w()
    i = w.index("function srxDistJump(")
    seg = w[i:w.index("/* 诊断视图（r1063 T266）")]
    for bad in ("/api/config", "fetch(", "app_date_horizon_days_map=",
                "localStorage.setItem"):
        assert bad not in seg, "跳转里不许出现 %s" % bad


def test_advice_line_escapes_plain_but_keeps_links():
    w = _w()
    i = w.index("const _parts=a2.map(")
    seg = w[i:i + 500]
    assert "indexOf('<a ')===-1?esc(t):t" in seg, \
        "普通建议仍要转义，只有带链接的项直出 HTML"
