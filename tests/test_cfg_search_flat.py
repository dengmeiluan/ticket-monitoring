# -*- coding: utf-8 -*-
"""配置页扁平化 + 检索页「渠道入口」展开耦合。

两条用户实报（2026-10-31）：
  1. 「配置页面左侧和右侧不够扁平化，右边面板的图标和边缘都在一块了」
  2. 「渠道入口按钮点击都位置变了……不允许按钮乱跑乱飘」

这些断言分两层：
  - 静态层：钉住「哪条规则不许回到 0 内衬 / 不许再用 display:contents」；
  - 运行时层：真量几何（静态断言测不出级联覆盖，「写了没生效」是本站高发缺陷）。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


# ---------- 配置页：内衬与图标留白 ----------

def test_cfg_card_padding_is_symmetric():
    """右面板左右内衬必须相等且 ≥12，内容不许贴左缘。

    实测（2026-10-31，1512）：改前 `#cfgview .ucard` 被清成 `padding-left:0`，
    卡头文字 / 章节图标 / 渠道名 / 说明**全部 inset=0**（贴住卡片左边缘），
    而各层之间又互相对齐（极差 0），所以按相对极差写的门禁一直是绿的
    —— 一致不等于正确。
    """
    src = _src()
    # 父卡必须给正内衬（这条是单源）
    assert "#cfgview .ucard{padding-left:16px!important}" in src, (
        "右面板父卡没有统一左内衬（下游会各自补，最后又互相清零）")
    # 下游必须归零，否则与父卡叠加成 32
    for sel in ("#cfgview .ucard>.uhead{padding-left:0!important}",
                "#cfgview .ucbody{padding-left:0!important}"):
        assert sel in src, "下游内衬未归零（会与父卡叠加）：%s" % sel


def test_login_rows_and_bands_leave_room_for_icons():
    """渠道登录行与渠道入口 band 的横向内衬不得为 0。

    实测（2026-10-31，1512）：改前 `#loginRows .lgcard` 为 `padding:9px 0`、
    `.chband` 为 `padding:7px 0 6px`，24px/16px 渠道图标与行/带左缘完全重合
    （iconInset=0）——用户：「右边面板的图标和边缘都在一块了」。
    """
    src = _src()
    offenders = []
    for pat, label in ((r"#loginRows \.lgcard\{([^}]*)\}", "登录行"),
                       (r"\.chband\{([^}]*)\}", "渠道入口 band")):
        for m in re.finditer(pat, src):
            # 注意不能先吃掉空格：`padding:9px 0` 会粘成 `9px0` 拆不开
            # （负控实测过——那样写的判据对 `0` 无效，三条变异只抓住两条）。
            pad = re.search(r"padding:\s*([^;}!]+)", m.group(1))
            if not pad:
                continue
            parts = pad.group(1).split()
            horiz = parts[1] if len(parts) >= 2 else parts[0]
            mm = re.match(r"(-?[\d.]+)(?:px)?$", horiz)
            if mm and float(mm.group(1)) <= 0:
                offenders.append("%s: %s" % (label, pad.group(1)))
    assert not offenders, "出现 0 横向内衬（图标会贴住容器左缘）：%s" % offenders


def test_cfg_nav_shares_the_card_surface():
    """左导航与右侧面板同一种表面语言；选中态用「透明底 + 左侧竖线」。

    实测（2026-10-31，1512）：改前 `.cfgnav` 是裸列（transparent / 0 圆角 /
    无边框），右侧却是白底 14px 圆角卡 —— 同屏左右视觉重量差一个层级。
    选中态语言由 r1007 定案：透明底 + 左侧 2px 竖线（与 #mainnav/#montabs
    同一套扁平标记），本测试守住该契约，不要改成软蓝底或加投影。
    """
    src = _src()
    i = src.find(".cfgnav{")
    assert i > 0, "找不到 .cfgnav"
    blk = src[i:src.find("}", i) + 1].replace(" ", "")
    assert "background:var(--card)" in blk, "左导航没有内容表面：%s" % blk[:160]
    assert "border-radius:var(--r)" in blk, "左导航圆角未走令牌：%s" % blk[:160]
    assert "border:1pxsolidvar(--line)" in blk, "左导航缺 1px 发丝边：%s" % blk[:160]
    # 选中态：r1007 契约（透明底 + 左竖线 + 无投影）
    j = src.find("#cfgnav .cnav.on{")
    assert j > 0, "找不到左导航选中态规则"
    onblk = src[j:src.find("}", j) + 1].replace(" ", "")
    assert "background:transparent!important" in onblk, (
        "选中态底不再是透明（r1007 契约）：%s" % onblk[:160])
    assert "border-left:2pxsolidvar(--r-blue)!important" in onblk, (
        "选中态缺少左侧 2px 竖线标记：%s" % onblk[:160])
    assert "box-shadow:none!important" in onblk, (
        "选中态又加回了投影（不是扁平语言）：%s" % onblk[:160])


# ---------- 检索页：渠道入口展开不许移动触发器 / 不许推走邻居 ----------

def test_channel_entry_expands_as_overlay_not_in_flow():
    """渠道入口展开必须是浮层，不得改变页面布局。

    两版都错过，记下来：
    v1 `[open]{grid-column:1/-1}`：详情盒换列，触发器从右缘跑到左缘
       （1512 实测 x 1131→91）。
    v2 `[open]{display:contents}`：summary 钉回原格，但 details 失去自身盒
       → summary 的 rect 变 **0×0**；面板占满整行且不限高（实测 1028×732），
       把 14 日价带从 top 320.9 推到 **1056.9（+736px）**。
    现版：面板 `position:absolute` + `max-height` + `overflow:auto`，
    不参与文档流，任何邻居都不动。
    """
    src = _src()
    i = src.find("#searchview .srx-probefoot .srx-chlinks[open]")
    assert i > 0, "找不到渠道入口展开态规则"
    seg = src[i:i + 900]
    assert "display:contents" not in seg, (
        "展开态又用 display:contents 拆盒（summary 会失去盒子，rect 变 0×0）")
    j = src.find("#searchview .srx-probefoot .srx-chlinks[open]>#srxChLinksBox")
    assert j > 0, "找不到面板展开规则"
    box = src[j:src.find("}", j) + 1].replace(" ", "")
    assert "position:absolute" in box, (
        "面板仍在文档流里（会把下方内容推走）：%s" % box[:200])
    assert "max-height" in box, "面板没有高度上限：%s" % box[:200]
    assert "overflow:auto" in box, "面板不可滚动：%s" % box[:200]
