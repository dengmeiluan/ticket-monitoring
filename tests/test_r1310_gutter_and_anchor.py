# -*- coding: utf-8 -*-
"""r1310：把「留边」和「弹层跟按钮」两条约束钉成门禁。

来源都是用户明确要求：
* 「正常应该有留边的啊」→ 检索/配置页必须与监控页同几何（有左右留边、居中）；
* 「更新弹出位置不跟按钮位置，违反我前端约束」→ 弹层必须按触发按钮定位，
  不允许写死 `right/bottom` 贴在视口角落。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_all_three_views_share_one_wrap():
    """三视图必须**在同一个 `.wrap` 里**——留白与页头吸顶都由此而来。

    用户原话：「正常应该有留边的啊」「都得跟监控页面一样对齐，左边是有留白的」。

    r1404：之前 searchview/cfgview 曾被一个多余的 `</div>` 挤出 `.wrap`，
    于是它们既没留白、页头 sticky 也没有行程（配置页一滚页头就消失）。
    当时的补救是**各自复制一份外壳样式**（max-width+padding+margin auto），
    那是补丁：断点一抄错就差 6–11px。现在改成结构正确 + 单一外壳：
      · 三个视图同父（.wrap）；
      · 不允许再给 #searchview/#cfgview 单独写 max-width/padding 外壳
        （否则等于承认它们又跑到 wrap 外面去了）。
    """
    # 1) 源码层：三视图的 div 深度必须相同（同父）
    LINES = SRC.splitlines()
    wrap_i = next(i for i, ln in enumerate(LINES) if 'class="wrap"' in ln)

    def _depth_of(needle):
        depth = 0
        for ln in LINES[wrap_i:]:
            depth += ln.count("<div") - ln.count("</div>")
            if needle in ln:
                return depth
            if depth <= 0:
                return -1
        return -1

    d_mon = _depth_of('id="monview"')
    d_search = _depth_of('id="searchview"')
    d_cfg = _depth_of('id="cfgview"')
    assert d_mon == d_search == d_cfg == 2, (
        "三视图不在同一个 .wrap 里：monview=%s searchview=%s cfgview=%s"
        "（多/少一个 </div> 就会把后两个挤出外壳）" % (d_mon, d_search, d_cfg))

    # 2) 不许再有各写一份的外壳
    assert "#searchview,#cfgview{max-width" not in SRC, \
        "又给检索/配置页单独复制了一份外壳（应当在 .wrap 里统一）"


def test_popover_has_no_fixed_corner_pin():
    """弹层不许写死 right/bottom 贴视口角落（那就是"不跟按钮"）。"""
    i = SRC.find("#updPop{position:fixed")
    assert i > 0, "找不到弹层基础样式"
    seg = SRC[i:i + 300]
    assert "right:16px" not in seg and "bottom:64px" not in seg, seg


def test_popover_places_itself_from_trigger():
    assert "function _placeUpdPop()" in SRC, "没有按按钮定位的函数"
    i = SRC.find("function _placeUpdPop()")
    seg = SRC[i:i + 900]
    assert "verChip" in seg, "定位没读触发按钮"
    assert "getBoundingClientRect" in seg
    assert "'--ax'" in seg or '"--ax"' in seg, "没有小尖角锚点"


def test_popover_repositions_after_async_fill():
    """内容异步填充会改高度 → 必须二次定位，否则离按钮很远。"""
    i = SRC.find("setTimeout(_placeUpdPop")
    assert i > 0, "没有二次定位"
    assert SRC.count("_placeUpdPop") >= 3


def test_stale_tab_detection_uses_build():
    assert 'const PGBUILD=' in SRC and '_build_stamp()' in SRC


def test_app_entry_row_has_no_middle_void():
    """渠道入口的 App 行不许再用 space-between 把两个动作拉到两端。

    用户实测圈出中间那片空白问「排版坏了？」——它不是坏（App 没有 PC/H5 入口），
    但读作空洞。改为相邻靠左 + 固定 18px 间距，左侧空档留给行尾。
    作用域必须限定 `:not(.special)`：特价雷达那块窄板有自己的排布。
    """
    i = SRC.find(".chboard:not(.special) .chband-approw{")
    assert i > 0, "App 行的排布覆盖不见了（会退回 space-between 的中间空腔）"
    seg = SRC[i:i + 220]
    assert "justify-content:flex-start" in seg, seg
    assert "space-between" not in seg, "又变回两端对齐了"
    assert "gap:18px" in seg, seg
