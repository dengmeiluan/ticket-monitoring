# -*- coding: utf-8 -*-
"""r708：渠道登录区装得下 7 家渠道（用户实报「智行 APP 名字不全」）。

缺陷事实（2026-10-31，1200 视口实测）：
  名字列写死 `grid-template-columns:170px`，是为 5 家浏览器渠道定的。
  加入「智行 App / 去哪儿 App + 真机徽标」后列宽不够：
    「智行 App」  sw=55 但 cw=48  → 被 text-overflow:clip 裁成「智行 ...」
    「去哪儿 App」 sw=68 但 cw=48  → 裁成「去哪...」
  用户看到的就是渠道名不全。

两处判据（都只看源码事实，不做字面 CSS 猜测）：
  1. 名字列必须是内容自适应（max-content 一类），不能是写死像素；
  2. 名字单元格不得出现会裁剪的 text-overflow（否则又是「装不下就切」）。

渲染层的真实测量见 `_scratch/_r708_login_name_clip.py`：修复后三档视口
（1500/1200/1024）下 7 行均为 52px 同高、名字 sw==cw。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        return f.read()


def _login_card_rule(src):
    """取**含 grid-template-columns** 的那条 #loginRows .lgcard 规则。

    同选择器在样式表里有多条（视觉态/间距态各一条），不能取第一条：
    第一条只管背景与边框，没有列定义。
    """
    for m in re.finditer(r"#loginRows \.lgcard\{([^}]*)\}", src):
        if "grid-template-columns" in m.group(1):
            return m.group(1)
    raise AssertionError("找不到定义列宽的 #loginRows .lgcard 规则")


def test_name_column_is_content_sized():
    """第一列不能写死像素：多渠道接入后最长名字会变。"""
    rule = _login_card_rule(_webui())
    m = re.search(r"grid-template-columns:([^;!]+)", rule)
    assert m, rule
    first = m.group(1).strip().split()[0]
    assert not re.match(r"^\d+px$", first), (
        "名字列写死成 %s —— 加第 6/7 家渠道（App + 真机徽标）就会裁字" % first)
    assert ("max-content" in first) or ("auto" in first), first


def test_name_column_never_clips():
    """名字单元格不能带 text-overflow:clip/ellipsis（等价于承认装不下）。"""
    src = _webui()
    for m in re.finditer(r"#loginRows[^{]*\.lgname[^{]*\{([^}]*)\}", src):
        body = m.group(1)
        assert "text-overflow" not in body, (
            "登录行名字被设了 text-overflow：%s" % body[:120])


def test_seven_channels_share_one_list():
    """七家渠道必须落在同一个列表/同一套行样式里。

    否则「只有 App 行走另一套布局」——正是用户说的「没把原来的渠道
    一起考虑」。判据：渲染行数由 APP 渠道 + 浏览器渠道共同决定，
    且没有第二份 #loginRows 之类的独立容器。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    assert len(APP_CHANNELS) + len(BROWSER_CHANNELS) >= 7
    src = _webui()
    assert src.count('id="loginRows"') == 1, "登录行容器不止一个"


def test_app_channel_names_come_from_single_source():
    """渠道显示名不得在登录区另抄一份（App 名要与 SRX_PLATS 同源）。

    判据只看**代码**：先把块注释/行注释剥掉，注释里提到「智行 App」
    是在解释历史缺陷，不算硬编码。
    """
    src = _webui()
    assert "APP_PLAT_NAME" in src, "App 渠道中文名应有单源表"
    m = re.search(r"function renderLoginCards[\s\S]{0,8000}", src)
    assert m, "找不到 renderLoginCards"
    body = m.group(0)
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    body = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.splitlines())
    assert "智行 App" not in body, (
        "renderLoginCards 代码里硬编码了 App 名，应走 APP_PLAT_NAME 单源")
