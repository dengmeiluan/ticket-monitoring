# -*- coding: utf-8 -*-
"""r1063 T17：渠道健康行显示「哪条通路/哪个维度被降频」（通路作为一等作用域的 UI 面）。

目标原话要求通路（H5/API、PC、API…）算独立维度并**进面板**；策略面板行已在
T16 落地，这里补齐**渠道健康行**——否则用户在健康页看到「这行成功率低」，
却看不到「到底是哪条通路被压到几倍」。

数据同源：`/api/pacing` 的 `channels` 就是 `pacing.snapshot()`，行里的
`health_paths`/`health_dims` 由它直出，前端不另算（「一切统一状态」）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_health_row_renders_per_scope_penalty():
    """行内必须把 snapshot 的逐作用域倍数渲染出来（不是只下发不消费）。"""
    js = _js()
    seg = js[js.index("const _pen2=(()=>{"):]
    seg = seg[:1400]
    assert "v.health_paths" in seg and "v.health_dims" in seg, seg[:200]
    assert ".penalty" in seg
    # 只列 >1 的；没有降频时返回空串（不占位，几何不变）
    assert "if(p>1)" in seg and "return ''" in seg
    # 消费点真的在行模板里
    assert "'<i class=\"e2k\">降频</i>'+" in js, "行模板没挂降频读数"


def test_scope_readout_dedupes_dimension_when_path_exists():
    """同维度已有链路读数时不重复列维度（与策略面板同一去重规则）。"""
    js = _js()
    seg = js[js.index("const _pen2=(()=>{"):][:1400]
    assert "split('/')[0]===kk" in seg, "维度与链路会重复列同一件事"


def test_scope_readout_adds_no_new_css_or_tokens():
    """不新增样式：复用既有 .e2/.e2k（微信扁平铁律：禁止新视觉、新字号档）。"""
    js = _js()
    seg = js[js.index("const _pen2=(()=>{"):][:1400]
    for banned in ("#", "style=", "font-size", "border", "radius"):
        assert banned not in seg, ("_pen2 里出现了样式（%s）" % banned)
