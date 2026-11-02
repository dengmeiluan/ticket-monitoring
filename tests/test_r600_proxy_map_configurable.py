# -*- coding: utf-8 -*-
"""r600：`crawler.proxy_map` 必须可在配置页配置（回读 → 控件 → 落盘）。

用户的硬要求是「配置页面不允许存在任何无法配置的项」。`proxy_map`
（按渠道绑出口）在 `crawlers/base.py` 真生效、`config.example.yaml` 也
有说明，但配置页既没有控件也不显示值——用户只能去改文件，而它的作用
恰恰是「一家被限流不牵连另一家」，是提高渠道成功率的关键旋钮。

三段缺一段等于配不上，逐段断言：
  1. GET /api/config 的 globals 要回读（否则控件只能显示空）
  2. 配置页要有 glbPm_<渠道> 控件并写 GLB.proxy_map
  3. POST 要把它落到 crawler.proxy_map（且与全局 proxy 同一套形态校验）
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATS = ["qunar", "fliggy", "ctrip", "tongcheng", "tuniu"]


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_backend_reads_back_proxy_map():
    w = _w()
    i = w.index('"proxy": str((cfg.get("crawler") or {}).get(')
    seg = w[i:i + 900]
    assert '"proxy_map"' in seg, "GET /api/config 没有回读 crawler.proxy_map"


def test_every_channel_has_a_proxy_map_control():
    w = _w()
    i = w.index("渠道出口 · 按渠道绑代理")
    seg = w[i:i + 1400]
    for p in PLATS:
        assert "'glbPm_'+p" in seg, "缺少 %s 的出口代理控件" % p
    assert "GLB.proxy_map=Object.assign(" in seg, "控件没有写回 GLB.proxy_map"


def test_post_persists_proxy_map_with_shape_validation():
    w = _w()
    i = w.index('if isinstance(glb.get("proxy_map"), dict):')
    seg = w[i:i + 300]
    assert '_crw["proxy_map"] = _proxy_map_clean(' in seg, (
        "没有落到 crawler.proxy_map")


def test_clean_helper_rejects_bad_and_empty_values():
    """真调用落盘用的清洗函数——这是 POST 分支唯一实际执行的那段。"""
    import sys
    sys.path.insert(0, ROOT)
    from webui import _proxy_map_clean
    got = _proxy_map_clean({
        "qunar": " http://127.0.0.1:7891 ",
        "ctrip": "127.0.0.1:7892",   # 漏 scheme
        "fliggy": "",
        "tongcheng": None,
        "tuniu": "socks5://127.0.0.1:7893",   # 非 http(s)
    })
    assert got == {"qunar": "http://127.0.0.1:7891"}, got


def test_clean_helper_keeps_every_valid_channel():
    import sys
    sys.path.insert(0, ROOT)
    from webui import _proxy_map_clean
    src = {p: "http://127.0.0.1:%d" % (7890 + i)
           for i, p in enumerate(PLATS)}
    assert _proxy_map_clean(src) == src, "合法值被误删"


def test_control_value_matches_backend_key():
    """控件写的键名必须与后端读的键名一致——写成 proxyMap 就会静默失效。"""
    w = _w()
    i = w.index("渠道出口 · 按渠道绑代理")
    seg = w[i:i + 1400]
    assert "GLB.proxy_map" in seg
    assert "GLB.proxyMap" not in seg, "前端写成 proxyMap，后端读不到"
