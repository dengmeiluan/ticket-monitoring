# -*- coding: utf-8 -*-
"""r1806：域级登录墙建议也分口径（App 说"去手机上登录"，浏览器说"去登录"）。

真实载荷（app_qunar）：改前「…点「去登录」重存该渠道会话」——对 App 是错的动作。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pacing():
    return io.open(os.path.join(ROOT, "core", "pacing.py"),
                   encoding="utf-8").read()


def test_domain_login_branch_is_app_aware():
    s = _pacing()
    i = s.index("_act_txt")   # 注释里也有「被登录墙拦」，改用代码锚点
    seg = s[max(0, i - 500):i + 900]
    assert "_is_app" in seg, "域级登录墙没有按渠道类型分支"
    assert "_APP_CN.get(plat" in seg, "没有取 App 中文名"
    assert "手机上打开「%s」" in seg, "App 口径文案不在"
    assert "点「去登录」重存该渠道会话" in seg, "浏览器口径被弄丢了"


def test_needs_login_branch_is_app_aware():
    s = _pacing()
    i = s.index('ch.get("needs_login")')
    seg = s[i:i + 900]
    assert 'startswith("app_")' in seg
    assert "验证码需你本人填" in seg
