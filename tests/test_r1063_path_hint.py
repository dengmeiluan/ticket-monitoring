# -*- coding: utf-8 -*-
"""r1063 T271：通路口径提示——`App 登录 0%` 不是"账号未登录"。

用户原话："APP 三家已经登录了……但是你页面没变"。
面板上写的是 `App 登录 单次 0%（179 次）`，读起来像"没登录"；
而这条通路测的是**登录墙探测**（每次搜索有没有被要求登录）——
携程 App 搜索强制手机验证码时它就是 0%，与账号登录态无关。

不改标签名（`PATH_CN` 被 r658 门禁逐字对账，改名会连累一批用例），
改为**在通路小标里附口径**。本用例钉住：提示存在、接进 `_note`、且不误伤其它通路。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_hint_map_has_the_ambiguous_paths():
    w = _w()
    i = w.index("const PATH_HINT={")
    seg = w[i:i + 700]
    for k in ("app-login", "app-date", "app-list", "low-fare"):
        assert "'%s'" % k in seg, "缺 %s 的口径" % k
    assert "不是账号状态" in seg, "app-login 的口径必须点明与账号状态无关"


def test_hint_is_wired_into_note():
    w = _w()
    i = w.index("const _note=[_fx.join(")
    seg = w[i:i + 400]
    assert "(PATH_HINT[_k]||'')" in seg, "提示必须进 _note 才会显示"
    assert "].filter(Boolean).join(' · ');" in seg


def test_hint_only_applies_to_listed_paths():
    """未列出的通路不该被加提示（避免全站长文案）。"""
    w = _w()
    i = w.index("const PATH_HINT={")
    seg = w[i:w.index("};", i)]
    assert "'日历'" not in seg and "'航班明细'" not in seg, \
        "正常通路不加口径，避免噪音"
