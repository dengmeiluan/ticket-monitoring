# -*- coding: utf-8 -*-
"""r1063 T269：距离建议**可点**（跳到调整位置），但绝不擅自改配置。

"一切可干预"要求建议能落到动作上；但建议里自动改配置风险不对等
（一次误点就改了别人的采集范围）。所以做成"精准跳转 + 高亮字段"：

* 链接存在，指向 `srxDistJump(plat)`；
* 跳转必须**同时**打开页级容器 `#cfgview`（`showCfgPanel` 只切内部 tab，
  真机复验时踩到"跳过去了但什么也看不见"）；
* 只读：不得写 `app_date_horizon_days_map` 之类的配置。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


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
