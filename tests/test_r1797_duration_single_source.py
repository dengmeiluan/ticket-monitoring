# -*- coding: utf-8 -*-
"""r1797：时长只有一处写法（durCN / durShort）+ 停手卡片优先于登录/失败。

用户决定搁置两个 App 渠道后，界面上不允许再出现「去登录」这类动作——
所以停手必须**优先于** kind=login / kind=unknown 的卡片渲染。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_duration_helpers_exist_and_are_used():
    w = _w()
    assert "function durCN(sec)" in w and "function durShort(sec)" in w
    assert "const _durm=(h)=>durCN(" in w, "诊断卡还在自己拼 h/m"
    assert "lab='停手 '+durShort(" in w, "建议行还在自己拼 h/m"
    assert "'停手 '+durShort(_haltNow.left_s||0)" in w, "状态列还在自己拼 h/m"
    assert "+durCN(left*60)+" in w, "策略条芯片还在写「N 分钟」"
    assert "剩 '+durCN(_haltNow.left_s||0)" in w, "tooltip 还在写分钟"


def test_no_legacy_hour_minute_snippets_left():
    w = _w()
    for bad in ("Math.round(h.left_s/3600)+'h'",
                "(_hm>=60?(Math.floor(_hm/60)+'h')",
                "(_hlen>=1?(_hlen+'h')",
                "+left+' 分钟</button>'"):
        assert bad not in w, "仍有旧写法：" + bad


def test_halt_card_wins_over_login_and_fail():
    w = _w()
    i = w.index("j.diag.forEach(c=>{")
    seg = w[i:i + 400]
    assert "if(c.halt)" in seg, "诊断卡没有把 halt 放在最前"
    j = seg.index("if(c.halt)")
    after = seg[j:j + 200]
    assert "c.kind='halt'" in after
    assert "去登录" not in after and "登录内嵌" not in after, \
        "停手卡片仍在引导去登录"
