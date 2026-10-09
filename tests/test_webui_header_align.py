# -*- coding: utf-8 -*-
"""WebUI ≤390 带 header 内容左缘齐线（r270 审计 P3-1）。

≤390 带三件：header{margin:0 -10px} 负外扩对齐卡片外缘 + .wrap{padding:0 10px}
→ header 盒左缘落视口 0；但 header 水平 padding 12px 使内容左缘落在 12px，
比卡片区内容（10px）右缩 2px——全站唯一破「左缘成线」的带（实测
W=360/389/390 header 内容 12px vs 正文 10px；≥391 各带 18px 严格齐线）。
修法：水平 padding 12→10，内容左缘与 wrap 内容左缘同线（右缘对称同收）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_webui_header_align.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
                encoding="utf-8").read()


def test_header_narrow_band_content_aligns():
    src = _src()
    # 实效档：≤390 块内 header 水平 padding 与 .wrap 水平 padding 同值 10px，
    # 配合 margin:0 -10px 内容左缘与卡片左缘同线
    assert "header{padding:10px 10px}" in src
    # 禁复活：破线形态（水平 12px 使内容比卡片区右缩 2px）——
    # 口径为 webui.py 内零命中；docs/site/index.html 烘焙产物历轮
    # 不随轮重烘，旧形态由下次 demo_build 自然消除，不入钉面
    assert "header{padding:10px 12px}" not in src
