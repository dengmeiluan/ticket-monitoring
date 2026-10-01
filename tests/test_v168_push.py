# -*- coding: utf-8 -*-
"""推送回归钉：

 走势标注文字面中转线色换 C_TRANSFER_TX（标注白底块上 fill=a["c"]
把线色当文字填充——C_TRANSFER 对白卡 3.78:1 欠 AA； 
「文字/图形分离」的第三消费点：组头/胶囊之外的末值/最低点标注文字；
线体/珠点等图形消费保 C_TRANSFER 本体）；
 图挂兜底 bare 档硬保底恒 ≤40（code 缺码回落长航司名时裸拼
44/41 破保底——超预算逐字截码段收口，执行级钉）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v168_push.py -q
"""
import os

import report as _rep
from core.alerter import Alerter, _disp_dw


# ---- 标注文字面 AA ----------

def test_trend_label_text_uses_tx_token():
    """源码钉：标注文字填充对中转线色走 TX 令牌映射（白底块上过 AA）。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert 'fill=C_TRANSFER_TX if a["c"] == C_TRANSFER else a["c"])' in src


def test_trend_label_render_smoke(tmp_path):
    """中转序列真渲染出图（标注绘制路径整链走通，TX 映射行执行）。"""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 20, 8, 0, 0)
    d_vals = [2450, 2380, 2100, 1998, 1930, 1880, 1860, 1895, 1930]
    t_vals = [2600, 2520, 2350, 2260, 2140, 2050, 1720, 1690, 1688]
    qd = [False, False, False, False, False, True, True, True, False]
    ser = [(t0 + timedelta(minutes=30 * i), d_vals[i], t_vals[i],
            qd[i], i >= 6) for i in range(9)]
    out = str(tmp_path / "trend_v168.png")
    _rep.render_chart(ser, "v168 标注文字面", thresholds=(1900.0, 1700.0),
                      out_path=out)
    assert os.path.isfile(out)


# ---- bare 档硬保底 ----------

def test_bare_tier_hard_cap_40():
    """执行级钉：缺码+长航司名+角标全叠时 bare 档恒 ≤40 且保价格/时刻。"""
    f = {"name": "中国联合航空KN5807共享", "depTime": "14:00",
         "arrTime": "00:40", "price": 2898, "crossDayDesc": "次日",
         "_platform": "qunar", "_tie_n": 5}
    line = Alerter._fmt_flight_line(f, idx=3, mark="🔥")
    assert _disp_dw(line) <= 40
    assert "￥2898" in line and "14:00" in line and "00:40" in line


def test_bare_tier_normal_path_unchanged():
    """有码正常行不受截断影响（正常航班号完整保留）。"""
    f = {"code": "HU7849", "name": "海南航空HU7849", "depTime": "14:00",
         "arrTime": "00:40", "price": 2898, "_platform": "qunar"}
    line = Alerter._fmt_flight_line(f)
    assert "HU7849" in line
