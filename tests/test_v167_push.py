# -*- coding: utf-8 -*-
"""推送/渲染回归钉：

 中转组头/类别胶囊文字面换 C_TRANSFER_TX（C_TRANSFER 对浅橙胶囊底
3.47:1 欠 AA、全图最低文本对——文字/图形分离：色条与描边保 C_TRANSFER
本体，与 webui --orange 同值纪律不破）；
 破线空心绿价描边 1→2（2x 缩回后 ~1px，0.4x 手机缩放模拟实证四档
色中断档最弱）；
 走势标注候选位对档位环加罚（ring_pts：环是档位语义载体，密集角落
白底块曾把真达标实心环裁 60%——压普通点候选须优先于压环候选）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v167_push.py -q
"""
import os

import report as _rep


# ---- 中转文字面 AA ----------

def test_ct_transfer_tx_token():
    """中转文字面深橙令牌与图形本体分离（对浅橙底 4.95:1 过 AA）。"""
    assert _rep.C_TRANSFER_TX == (166, 84, 8)
    assert _rep.C_TRANSFER_TX != _rep.C_TRANSFER


def test_transfer_text_faces_use_tx_token():
    """源码钉：组头/胶囊文字面走 TX 令牌，左色条/描边保 C_TRANSFER 本体。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "C_TRANSFER_TX = (166, 84, 8)" in src
    assert 'fill=tx_c, anchor="lm")' in src          # 组头 19px 文字
    assert "fill=cap_tx, anchor=\"mm\")" in src      # 胶囊 12px 文字
    assert "outline=cap_c," in src                   # 胶囊描边=本体
    assert "fill=color)   # 左色条" in src           # 左色条=本体


# ---- 破线空心绿描边 ----------

def test_hollow_price_stroke_width_2():
    """源码钉：破线空心绿价描边 2px（1px 在 2x 缩回+手机缩放下断档最弱）。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "stroke_width=2, stroke_fill=C_QUAL)" in src


# ---- 标注避让对档位环加罚 ----------

def test_chart_ring_penalty_smoke(tmp_path):
    """带档位环+▼回落+双最低点标注的合成序列真渲染出图（ring_pts 罚分
    路径整链走通）。"""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 20, 8, 0, 0)
    d_vals = [2450, 2380, 2100, 1998, 1930, 1880, 1860, 1895, 1930]
    t_vals = [2600, 2520, 2350, 2260, 2140, 2050, 1720, 1690, 1688]
    qd = [False, False, False, False, False, True, True, True, False]
    ser = [(t0 + timedelta(minutes=30 * i), d_vals[i], t_vals[i],
            qd[i], i >= 6) for i in range(9)]
    out = str(tmp_path / "trend.png")
    _rep.render_chart(ser, "环标/回落合成", thresholds=(1900.0, 1700.0),
                      out_path=out)
    assert os.path.isfile(out)
