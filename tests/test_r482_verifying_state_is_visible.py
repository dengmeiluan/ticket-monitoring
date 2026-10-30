# -*- coding: utf-8 -*-
"""r482：验证窗口打开期间必须是「可见状态」，否则用户会重复点击。

实测缺口：点「去验证」后窗口要人操作最长 15 分钟，这期间面板仍显示
「需登录 / 去验证」——用户回来看不到任何变化，只能读成「点了没反应」，
于是再点一次。r481 的幂等拒绝只是在事后拦，人还是懵的。

三条契约：
  1) 后端在启动成功时写 scene.verify_open_at（窗口关闭即清除）；
  2) 行内标签改「验证中」并给出开始时间与超时上限，且**不再给可点的
     「去验证/去登录」**（换成 disabled 的「验证中…」）；
  3) 验证已通过且确实出数时，标签不得仍是「需登录」——否则左边催重登、
     右边写「验证后 ✓7 条」，自己否定自己的证据。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def _m():
    return io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                   newline="").read()


def test_backend_marks_window_open_and_clears_it():
    src = _m()
    i = src.index("def verify_channel(")
    seg = src[i:src.index('rt["verify_channel"]', i)]
    assert '"verify_open_at"' in seg, "启动成功未记录窗口开始时间"
    assert "verify_timeout_s" in seg, "未下发窗口超时上限"
    # 窗口关掉必须清除，否则一直显示「验证中」
    tail = seg[seg.index("def _run():"):]
    assert 'pop(\n                        "verify_open_at", None)' in tail \
        or '"verify_open_at", None' in tail, "_run 结束时未清除窗口标记"


def test_row_shows_verifying_and_disables_the_button():
    w = _w()
    assert "const _vo=(v.scene&&v.scene.verify_open_at)||null;" in w
    i = w.index("const _vo=(v.scene&&v.scene.verify_open_at)")
    seg = w[i:i + 600]
    assert "lab='验证中'" in seg, "行内标签未改「验证中」"
    assert "超时自动关闭" in seg, "未说明窗口超时上限"
    # 按钮区：验证中时不得再给「去验证/去登录」
    j = w.index("if(_vo){", w.index("const ac=[];"))
    btn = w[j:w.index("}else if(v.needs_login", j)]
    assert "disabled" in btn and "验证中…" in btn, "仍给可点的去验证按钮"
    assert "verifyNow(" not in btn and "srxGoLogin(" not in btn, \
        "验证中仍渲染可点的登录/验证按钮"


def test_verified_rows_do_not_keep_nagging():
    w = _w()
    i = w.index("if(vf&&vf.ok&&(parseInt(vf.rows)||0)>0)")
    seg = w[i:i + 160]
    assert "lab='验证已通过'" in seg and "tone='ok'" in seg


# ---------- r483：顶部入口与行内同源，验证中不再催去登录 ----------

def test_top_entry_skips_channels_with_an_open_window():
    """验证窗开着时，顶部不得再写「去登录」。

    实测缺口：行内已改「验证中」，顶部 `#hauthact` 仍按 advice.state==='login'
    亮「需处理 N 家会话失效 · 去登录」——用户从顶部再点一次，正好落进
    r481 才刚堵上的重复开窗路径。
    """
    w = _w()
    i = w.index("function healthLoginNudge(")
    seg = w[i:w.index("function healthSlotNote(", i)]
    assert "verify_open_at" in seg, "顶部入口未看窗口状态"
    assert "all.filter(k=>!_busy(k))" in seg, "仍在按原始 login 集合催人"
    assert "验证窗口已打开 · 去核对" in seg, "全部在验证中时未改文案"
    # 不得禁用入口：验证失败/超时后需要还能点得动
    assert "ha.disabled=true" not in seg, "禁用入口会让验证失败后无法再操作"
    # 混合情形要说清「另一家无需重复点击」
    assert "无需重复点击" in seg
