# -*- coding: utf-8 -*-
"""r1652：停手渠道的建议只能是「停着·剩多久·怎么恢复」。

现场：携程/飞猪被人工停手 10 小时后，`/api/pacing` 的 advice 仍是
`stale → probe『点「立即扫描」』`、`path_degraded → route『已记录路径偏好』`，
页面会把用户推去做动作——而这两家是我们刚主动停掉的，两句话互相打脸。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_backend_overrides_advice_when_halted():
    s = _w()
    assert '"state": "halted"' in s, "没有 halted 建议状态"
    assert '"action": "resume"' in s, "停手时建议动作不是「恢复」"
    i = s.index('"state": "halted"')
    # 从 halted 赋值往后看 2500 字符（含理由/时长拼接）——必须出现 continue，
    # 且不能先撞上新的 advice 赋值（那说明又去算别的建议了 = 没短路）。
    seg = s[i:i + 2500]
    cut = seg.find('_ch["advice"] =', 10)
    if cut > 0:
        seg = seg[:cut]
    assert "continue" in seg, "停手时没有短路后续建议（会继续算 probe/route）"


def test_row_renders_halted_with_eta_from_payload():
    s = _w()
    assert "adv.state==='halted'" in s, "节流行没处理 halted"
    i = s.index("adv.state==='halted'")
    seg = s[i:i + 420]
    assert "adv.eta_s" in seg, "停手时长没有从载荷现算"
    assert "(_hlen" not in seg, (
        "引用了另一段作用域的 _hlen → ReferenceError，整行渲染会挂掉")


def test_live_pacing_halted_advice_is_consistent():
    """有服务在跑时顺带核对一次真实载荷（没有就跳过）。"""
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/pacing",
                               timeout=20).read())
    except Exception:
        return
    for p, row in (d.get("channels") or {}).items():
        if not (row or {}).get("halt"):
            continue
        adv = row.get("advice") or {}
        assert adv.get("state") == "halted", (
            "%s 停手中，建议却是 %r" % (p, adv.get("state")))
        assert adv.get("action") == "resume", (p, adv.get("action"))
        assert "立即扫描" not in (adv.get("hint") or ""), (p, adv.get("hint"))
