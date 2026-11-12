# -*- coding: utf-8 -*-
"""r1726：诊断卡的每种 kind 都要能区分（有色）且该有动作的要有按钮。

现场：`core.health_diag` 产出 13 种 kind，前端只给 9 种配色、只给
login/captcha 配动作按钮。`cookie_expired` 的文案写"要重新登录"，
按钮却只有「自检」——建议让人做的事必须真有个按钮（r905 规矩）。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kinds():
    hd = io.open(os.path.join(ROOT, "core", "health_diag.py"),
                 encoding="utf-8").read()
    return sorted(set(re.findall(r'_card\(\s*\w+\s*,\s*"([a-z_]+)"', hd)))


def _webui():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_every_kind_has_a_tone():
    w = _webui()
    missing = [k for k in _kinds() if (".hdiag-card.%s .hdiag-st" % k) not in w]
    assert not missing, "这些 kind 没有配色（会与「未知」同色）：%s" % missing


def test_cookie_expired_offers_login_button():
    w = _webui()
    # 按钮条件现在是多行形态：`const btn=(c.kind==='login'||c.kind==='captcha'
    #   ||c.kind==='cookie_expired')`，按 const btn= 定位再检查。
    i = w.index("const btn=")
    seg = w[i:i + 260]
    assert "cookie_expired" in seg, \
        "cookie 过期的卡没有「打开登录」按钮——文案让人重登，按钮却只有自检"
    assert "data-diaglogin" in w[i:i + 900], "登录按钮没有接到 srxGoLogin"


def test_known_kinds_all_styled():
    kinds = _kinds()
    assert "cookie_expired" in kinds and "maintenance" in kinds, kinds
