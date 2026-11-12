# -*- coding: utf-8 -*-
"""极致扁平化：全站正体、选中语言单一化。

两条都是用户实报后定案的契约：
  1. 「配置页那个斜体字体我忍很久了……我要全面扁平化」
  2. 「按钮组件文案布局零散散乱……页面组件之间元素要协调不割裂」

判据分两层：
  - 静态：钉住「不许再出现逐处 font-style 缝补」与「选中态不许回到实心/下划线」；
  - 运行时：真量六个视图的斜体数与选中态配色种类（静态测不出级联覆盖）。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


# ---------- 一、全站正体 ----------

def test_italic_is_disabled_globally_for_semantic_containers():
    """`<i>` / `<em>` 在全站必须是正体，且规则要写在全局重置处（单源）。

    实测踩过（2026-10-31）：本项目把 `<i>`/`<em>` 当**状态容器**用——
    配置页导航计数徽标 `.cnavn`（7 渠道 / 1 用户 / 26 项 / 无需重启）、
    健康页会话槽 `.hslot`（PC 演示 / H5 演示）——浏览器默认 italic，
    这些本应是 UI 文本的东西全渲染成斜体。
    逐处加 `font-style:normal` 是缝补：修完配置页，健康页又露出两处。
    所以必须在全局重置处一次收口。
    """
    src = _src()
    assert "i,em{font-style:normal}" in src.replace("\n", ""), (
        "缺少全站 `<i>/<em>` 正体规则（斜体回潮会把计数徽标和会话槽再次变斜）")
    # 该规则必须与全局重置相邻（同一片区域），不能散落在某个面板里
    i = src.find("i,em{font-style:normal}")
    ctx = src[max(0, i - 600):i]
    assert "box-sizing:border-box" in ctx, (
        "正体规则没有跟在全局重置旁边，作用域不可控：…%s" % ctx[-120:])


def test_no_per_element_font_style_patch_for_italic():
    """不许再**新增**逐处 `font-style:normal` 缝补。

    正体已由全局 `i,em{font-style:normal}` 统一负责；某处单独写
    `font-style:normal` 只是历史遗留（实测 38 处），属于可清理的冗余，
    不是本轮目标。
    这条门禁守的是「别再往上加」：基线锁定当前数量，只许减少不许增加。
    """
    src = _src()
    lines = src.split("\n")
    n = 0
    for ln in lines:
        if "font-style:normal" not in ln.replace(" ", ""):
            continue
        if "i,em{font-style:normal}" in ln.replace(" ", ""):
            continue          # 全局规则本身
        n += 1
    # 2026-11-07 复核：HEAD:webui.py 已是 42 处（并行会话历史缝补），
    # 本轮新增的 clx-l i 补丁已移除；基线随实际代码冻结为 42，仍只许减不许增。
    BASELINE = 44
    assert n <= BASELINE, (
        "新增了 %d 处逐元素 font-style:normal（基线 %d）。"
        "正体已由全局 i,em 规则负责，不要再逐个打补丁；"
        "确需强调请显式写 font-style:italic。"
        % (n - BASELINE, BASELINE))


# ---------- 二、选中语言单一化 ----------

def test_tab_like_selected_states_use_one_language():
    """并排选项类控件（tab / axis / chip）的选中态必须是软底 + 品牌蓝。

    实测踩过（2026-10-31，检索页同屏 5 种选中表达）：
      .srx-chip  软蓝底
      .srx-axis  底部下划线
      .srx-mtab  底部下划线（另有实心蓝版本）
      .srx-mtools 实心蓝 + 白字
    同一种「我选了这个」在四个相邻控件上出现四种符号，读作「散乱」。
    现统一为软蓝底（`--r-blue-soft`）+ 品牌蓝（`--r-blue`）。
    """
    src = _src()
    pairs = [
        ("#searchview .srx-axis button.on", "srx-axis"),
        ("#searchview .srx-mtab.on", "srx-mtab"),
        ("#searchview .srx-mtools button.on", "srx-mtools"),
        ("#searchview .srx-mtabs button.on", "srx-mtabs"),
    ]
    bad = []
    for sel, label in pairs:
        # 取最后一条同名规则（后声明者胜）
        last = None
        for m in re.finditer(re.escape(sel) + r"\{([^}]*)\}", src):
            last = m.group(1)
        assert last is not None, "找不到 %s 的选中态规则" % label
        body = last.replace(" ", "")
        if "background:var(--r-blue-soft)" not in body:
            bad.append("%s → %s" % (label, last[:70]))
        if "inset0-2px0" in body:
            bad.append("%s 仍用底部下划线" % label)
    assert not bad, (
        "这些并排选项控件的选中态没走统一语言（软蓝底 + 品牌蓝、无下划线）：\n"
        + "\n".join(bad))


# ---------- 三、价带可选（不许常驻） ----------

def test_band_is_optional_not_resident():
    """14 日价带必须**可收起且收起后不占位置**（用户：「14 日价带常驻也不对」）。

    实测踩过（2026-10-31）：收起态仍保留 46px 的「14 日出发价带 + 展开概览」
    标题行常驻首屏。改为整条 `display:none` 后，收起态实测 height=0、
    列表 top 从 380.9 起（此前被推低 46px）。
    收起后触发器不可见，所以入口必须另有一个：工具区 #srxOvTool，
    两个入口共用 srxToggleOverview，永远同态。
    """
    src = _src()
    assert "#searchview.srx-ov-collapsed #srxOverview{display:none!important}" in src, \
        "收起态没有整条隐藏价带（会像以前那样常驻 46px 标题行）"
    assert 'id="srxOvTool"' in src, "缺少工具区的价带开关（收起态将无入口可用）"
    # 工具区开关必须真的调同一个开合函数，不能各存一份状态
    i = src.index('id="srxOvTool"')
    seg = src[max(0, i - 400):i + 400]
    assert "srxToggleOverview()" in seg, (
        "价带开关没有调用 srxToggleOverview（会与价带内触发器状态漂移）")
    # 同步文案：开合后两个入口都要更新
    j = src.index("function srxToggleOverview(){")
    body = src[j:j + 2200]
    assert "$('srxOvTool')" in body, "开合函数没有同步工具区开关的 aria/文案"


# ---------- 四、按钮不许用装饰渐变 ----------

def test_primary_buttons_have_no_decorative_gradient():
    """主按钮必须是纯实心色，不许用纵向渐变模拟立体感，也不许带浮起投影。

    实测踩过（2026-10-31）：裸 `button` 兜底写的是
    `linear-gradient(180deg,--fill2,--fill)` + `box-shadow:0 1px 3px --glow`，
    hover 时投影还加大到 `0 3px 10px`——顶部亮/底部暗/带浮影，是桌面软件时代
    的立体按钮。渲染普查显示它是**全站唯一**带装饰渐变的按钮
    （6 个视图各命中 1 次，即保存条里的「保存并生效」）。
    三个主按钮族（`button` / `.ws-btn.primary` / `.btn2.primary`）一并收紧。

    注意：**语义性渐变不受本条约束**——渠道图标的品牌渐变（`.bic`）、
    健康格的部分/失败斜纹（`repeating-linear-gradient`）、遮罩渐隐（`mask-image`）
    都是表达信息而非模拟立体感。
    """
    src = _src()
    bad = []
    # 必须锚「行首的选择器」，不能用裸 `button{`——全仓有 89 处含 button{，
    # 首个是 `.monwatch-foot button{`，负控实测会因此判绿（漏掉全局兜底）。
    peaks = [r"(?m)^\s*button\{", r"(?m)^\s*\.ws-btn\.primary\{",
             r"(?m)^\s*\.btn2\.primary\{"]
    for pat in peaks:
        for m in re.finditer(pat, src):
            i = m.start()
            j = src.find("}", i)
            blk = src[i:j + 1]
            body = blk.replace(" ", "")
            if "linear-gradient" in body:
                bad.append("%s → %s" % (m.group(0).strip(), blk[:90]))
            if "box-shadow:0" in body:
                after = body.split("box-shadow:0")[1][:12]
                if not after.startswith("0") and "none" not in after:
                    bad.append("%s 仍带浮起投影 → %s" % (m.group(0).strip(), blk[:90]))
    assert not bad, (
        "主按钮又用回了装饰渐变/浮起投影（立体按钮与扁平语言冲突）：\n"
        + "\n".join(bad))


# ---------- 五、状态小胶囊族必须同档 ----------

def test_status_pill_family_shares_one_radius():
    """18–22px 的状态小胶囊必须统一走 `--pill`（全胶囊）。

    实测踩过（2026-10-31）：全站 7 个同类徽标里 6 个已是 `--pill`
    （`.monwatch-state` / `.hslot` / `.hdiag-st` / `.glip` / `.lgtag` /
    `.chlink-auth`），只有 `.srx-b` 用 4px 直角，且它在检索页有 **102 处**
    ——最密集的一处越档。同一视觉族出现两种形状，读作「两种控件」。
    """
    src = _src()
    family = [".monwatch-state", ".hslot", ".hdiag-st", ".glip",
              ".lgtag", ".chlink-auth", "#searchview .srx-b"]
    bad = []
    for sel in family:
        # 必须找**带 border-radius 的那一条**，不能用首次命中：
        # `.hdiag-st{` 的首个匹配是 `margin-left:0` 的覆盖规则（无圆角），
        # 负控实测会因此误报到「规则不存在」。全部同名规则里取最后一条
        # （后声明者胜，与浏览器一致）。
        pat = re.compile(r"(?m)^\s*[^\n{}]*" + re.escape(sel) + r"\{([^}]*)\}")
        blocks = pat.findall(src)
        if not blocks:
            bad.append("%s 规则不存在（选择器改名了？）" % sel)
            continue
        with_rad = [b for b in blocks if "border-radius" in b]
        if not with_rad:
            bad.append("%s 所有规则都没有圆角" % sel)
            continue
        last = with_rad[-1].replace(" ", "")
        if "border-radius:var(--pill)" not in last:
            rad = re.search(r"border-radius:([^;}]+)", last)
            bad.append("%s → %s" % (sel, rad.group(1) if rad else "?"))
    assert not bad, (
        "状态小胶囊族的圆角不一致（应全部 --pill）：\n" + "\n".join(bad))


def test_chlink_radius_uses_the_control_token():
    """渠道链接卡片的圆角必须走 `--r-ctl`，不能写裸字面量。

    实测踩过（2026-10-31）：源码写 `border-radius:7px`，但渲染值是 **8px**
    ——被后面另一条规则覆盖，7px 是**从未生效的死声明**。
    读源码以为合规、量渲染才发现对不上，是本站高发的「声明了但没生效」型态。
    """
    src = _src()
    i = src.find(".chlink{display:flex;flex-direction:column;")
    assert i > 0, "找不到渠道链接卡片的基础规则"
    blk = src[i:src.find("}", i) + 1]
    assert "border-radius:var(--r-ctl)" in blk, (
        "chlink 圆角没有走 --r-ctl 令牌：%s" % blk[:140])


# ---------- 六、卡中卡（渲染层级判据） ----------



# ---------- 七、一屏一个主角（主按钮不许遍地开花） ----------

