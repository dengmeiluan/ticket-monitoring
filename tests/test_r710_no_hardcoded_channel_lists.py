# -*- coding: utf-8 -*-
"""r710：全站不得再出现「写死的 5 家浏览器渠道清单」。

r709 修了特价雷达入口一处（`['ctrip','qunar','fliggy','tongcheng','tuniu']`）。
但同类写法只要再出现一次，新渠道就会在某个页面悄悄消失——用户看到的
是「这个页面没有 App」，而不是报错。

判据：在 webui.py 里搜索**去掉注释后**仍存在的「五家连续字面量」
（ctrip 紧跟 qunar 紧跟 fliggy），一律判红，并指出行号。

允许的唯一形式是数据派生：`SRX_PLAT_KEYS` / `Object.keys(SRX_PLATS)` /
服务端注入的渠道表。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ctrip … qunar … fliggy 依次出现（中间允许任意非引号内容）
HARDCODED = re.compile(
    r"""['"]ctrip['"][^\n]{0,40}['"]qunar['"][^\n]{0,40}['"]fliggy['"]""")


def _strip_comments_keep_lines(src: str) -> str:
    """剥注释但**保留行号**：报出的行号必须能直接定位原文件。

    块注释整体替换成等量空行；行注释只清掉内容、留空行。
    """
    def _blank(m):
        return "\n" * m.group(0).count("\n")
    src = re.sub(r"/\*[\s\S]*?\*/", _blank, src)
    out = []
    for ln in src.splitlines():
        out.append(re.sub(r"//.*$", "", ln))
    return "\n".join(out)


def test_no_hardcoded_five_channel_list():
    """写死的五家清单只允许出现在**不决定「渲染哪些渠道」**的地方。

    白名单（逐条核对过语义）：
      * `SRX_PLAT_ORDER`  —— 只是展示/取数优先级，全集仍由 SRX_PLATS 决定；
      * 登录槽位 `order`（含 fliggy_h5）—— 槽位 ≠ 渠道，App 走 appSlots；
      * 登录卡无 slots 时的回退 —— 同上，只产出浏览器端槽位。
    其余任何位置出现五家连排，都意味着新渠道会在该处消失。
    """
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = _strip_comments_keep_lines(f.read())
    allow_marks = (
        "SRX_PLAT_ORDER",          # 只是优先级，全集由 SRX_PLATS 决定
        "const order=['ctrip'",    # 登录槽位顺序（含 fliggy_h5），槽位≠渠道
        "slots=['ctrip'",          # 无 slots 时回退的浏览器槽位
        "PLATFORM_PRIORITY",       # 探针资源顺序，不改结果
        "_plats = (",              # _cookie_states：已显式并上 APP_CHANNELS
        # 「需处理 N · 去登录」提醒的无 slots 回退：判据是 channelAuthView
        # 的 needsLogin，App 的登录态不走这条通路（走 /api/app-login/state），
        # 加进来只会误报。已知边界，非渲染渠道清单。
        "need=['ctrip'",
    )
    hits = []
    for i, ln in enumerate(src.splitlines(), 1):
        if not HARDCODED.search(ln):
            continue
        if any(m in ln for m in allow_marks):
            continue
        hits.append((i, ln.strip()[:110]))
    assert not hits, (
        "写死的五家渠道清单（新渠道会在这个页面消失）：%s\n"
        "应改为从 SRX_PLAT_KEYS 派生。" % hits[:6])


def test_channel_keys_cover_registry():
    """前端渠道表必须覆盖后端注册的全部渠道（含 App）。"""
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    for plat in list(BROWSER_CHANNELS) + list(APP_CHANNELS):
        assert ("%s:[" % plat) in src or ("'%s':" % plat) in src or \
               ('"%s":' % plat) in src, (
            "webui 的 SRX_PLATS 里没有 %s —— 该渠道在所有「按渠道渲染」的"
            "位置都会缺失" % plat)


def test_channel_links_channels_cover_apps():
    """渠道入口接口的 channels 列表必须包含 App（名字/会话要求）。

    cells/specials 只给浏览器渠道是对的（App 没有网页入口），但 channels
    决定「按渠道渲染」那一行能不能拿到中文名与会话说明；缺了它，渠道
    入口板里的 App 行只能显示裸 id。
    """
    from core.channel_links import channel_links
    from core.channels import APP_CHANNELS

    j = channel_links("BJS", "SHA", "2026-11-05")
    plats = [c["plat"] for c in j["channels"]]
    for p in APP_CHANNELS:
        assert p in plats, "channels 缺 %s：%s" % (p, plats)
    for c in j["channels"]:
        assert c["name"] and not c["name"].startswith("app_"), c
        assert c["session_label"], c
