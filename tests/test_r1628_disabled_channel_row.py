# -*- coding: utf-8 -*-
"""r1628：不在采集清单里的渠道，节流行要写「未在清单」，不能写「正常」。

现场：去哪儿 PC 停在 11-10 12:26（33 小时），健康卡写
「该渠道已 33 小时没有采集样本——不是『先跑一轮』，而是采集没在跑：
检查监控进程与扫描周期」；而行里仍写「正常」。
真相是它**不在 platforms 清单**（`/api/state` 的 platforms 里没有 qunar），
两句都把人往"查进程"上带，属于同一族的"账本说谎"。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w(name="webui.py"):
    return io.open(os.path.join(ROOT, name), encoding="utf-8", newline="").read()


def test_backend_advice_knows_enabled_list():
    s = _w("core/pacing.py")
    assert "enabled=None" in s, "advise 没有 enabled 参数"
    assert '"state": "disabled"' in s, "没有「不在清单」这个状态"
    assert "不在你的采集清单" in s, "没有对应的中文结论"


def test_webui_passes_enabled():
    s = _w()
    assert "enabled=_enabled_plats()" in s, "调用 advise 时没传采集清单"
    assert "def _enabled_plats(" in s, "缺少 _enabled_plats()"


def test_row_renders_disabled_state():
    s = _w()
    assert "adv.state==='disabled'" in s, \
        "节流行没处理 disabled：会落进默认分支写「正常」，与右侧 0% 自相矛盾"
    assert "未在清单" in s, "没有「未在清单」这个行文案"
