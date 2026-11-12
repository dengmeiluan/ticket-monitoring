# -*- coding: utf-8 -*-
"""r805ao：Python 侧「只列 5 家浏览器渠道」的副本必须各自站得住。

这一类缺陷已复发 6 次（前端 5 处 + `core/health.py` 的 `_OK_PRICE`）。
每修一次都在下一处再踩——因为没有一条判据管「这份 5 家名单合不合理」。

做法不是禁止字面量（`BROWSER_CHANNELS` 本身就得是这 5 家），而是**枚举 +
逐份表态**：全仓扫描 `("ctrip", ..., "tuniu")` 形态的字面量，要求每一处
都落进下面已知的合理清单；**新增一处就红**，逼作者在这里写清楚它为什么
只该有浏览器渠道，或者干脆改去 import `core.channels`。

已知的 6 处（2026-11-01 实测枚举）：
  · `core/channels.py`  BROWSER_CHANNELS —— 定义本身，单一事实源
  · `core/channel_links.py` PLATS —— **渠道入口卡**（页面上能点开的入口）；
    App 渠道没有网页入口，故只列浏览器是对的
  · `core/health_diag.py` PLATFORMS —— `classify_round` 的默认兜底，
    调用方（`_health_decorate`）会传 `all_plats` 覆盖成含 App 的实际清单
  · `core/pacing.py` PLATFORMS —— 决定**偏移顺序**；App 走 crc32 兜底偏移，
    且 `snapshot` 有 `for p in self._st` 兜底把 App 也返回
  · `webui.py` PLATFORM_PRIORITY —— 明细排序优先级；未列出的渠道排在后面，
    不是「不支持」
  · `webui.py` 1 处字面量已显式 `+ tuple(_APP_PLATS)` 拼上 App，属正确写法
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LITERAL = re.compile(
    r'\(\s*"ctrip"\s*,\s*"fliggy"\s*,\s*"qunar"\s*,\s*"tongcheng"\s*,\s*"tuniu"\s*\)'
    r'|\(\s*"ctrip"\s*,\s*"qunar"\s*,\s*"fliggy"\s*,\s*"tongcheng"\s*,\s*"tuniu"\s*\)')

# 允许存在的「只列浏览器」副本：路径 → 为什么它只该有浏览器渠道
KNOWN = {
    "core/channels.py": "BROWSER_CHANNELS 定义本身（单一事实源）",
    "core/channel_links.py": "渠道入口卡：App 没有网页入口，只列浏览器是对的",
    "core/health_diag.py": "classify_round 的默认兜底，调用方会传 all_plats 覆盖",
    "core/pacing.py": "偏移顺序；App 走 crc32 兜底，snapshot 有 _st 兜底",
    "webui.py": "排序优先级 / 已显式 + _APP_PLATS",
}


def _scan():
    hits = {}
    targets = ["core", "crawlers"]
    for d in targets:
        base = os.path.join(ROOT, d)
        for dirpath, _, files in os.walk(base):
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(dirpath, f)
                    rel = os.path.relpath(p, ROOT).replace("\\", "/")
                    try:
                        src = io.open(p, encoding="utf-8").read()
                    except Exception:
                        continue
                    for m in LITERAL.finditer(src):
                        ln = src[:m.start()].count("\n") + 1
                        hits.setdefault(rel, []).append(ln)
    for f in ("main.py", "report.py", "webui.py"):
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p):
            continue
        src = io.open(p, encoding="utf-8", errors="replace").read()
        for m in LITERAL.finditer(src):
            ln = src[:m.start()].count("\n") + 1
            hits.setdefault(f, []).append(ln)
    return hits


def test_every_browser_only_channel_list_is_accounted_for():
    hits = _scan()
    assert hits, "一个都没扫到，判据失去锚点（正则或目录变了）"
    unknown = {k: v for k, v in hits.items() if k not in KNOWN}
    assert not unknown, (
        "这些文件里又出现「只列 5 家浏览器渠道」的字面量，但没有说明为什么：%s\n"
        "要么改成 import core.channels，要么在 test_r805ao 的 KNOWN 里写清理由。"
        % unknown)


def test_known_copies_really_handle_app_channels():
    """光「允许存在」不够——每一份都得真的不挡 App 的路。"""
    # health_diag 的默认兜底必须能被调用方覆盖
    src = io.open(os.path.join(ROOT, "core", "health_diag.py"),
                  encoding="utf-8").read()
    assert "all_plats=PLATFORMS" in src, (
        "classify_round 的默认清单不再是可覆盖参数，App 会被漏掉")
    # pacing 的 snapshot 必须有「其余已记录渠道」的兜底分支
    src = io.open(os.path.join(ROOT, "core", "pacing.py"),
                  encoding="utf-8").read()
    i = src.index("def snapshot(self, now=None):", src.index("class ChannelBreaker"))
    seg = src[i:i + 2000]
    # 断言的是**行为**：`snapshot()` 遍历的是 `self._st`（所有已记账的渠道，
    # 含 App），不是只有 `PLATFORMS`。r1063 T7（`3601295`）为了让
    # `渠道|链路` 复合键折叠回渠道，把 `for p in self._st:` 换成了
    # `for key, st in self._st.items():`——键空间仍是同一个 `self._st`，
    # 折叠由 `_book_base(key)` 完成，App 渠道照旧一个不漏。
    # 所以这里钉的是「遍历 self._st」这个形状特征，而不是某一行字面量：
    # 换一种解包写法（哪怕只是改名）不该红，**但** `self._st` 一旦被换成
    # `PLATFORMS`，App 渠道熔断了面板就看不见——那才是要拦的回归。
    assert re.search(r"for \w+(?:\s*,\s*\w+)?\s+in\s+self\._st"
                     r"(?:\.items\(\))?\s*:", seg), (
        "ChannelBreaker.snapshot 只遍历 PLATFORMS，App 渠道熔断了也看不见")
    # channel_links 必须能从 core.channels 取到 App 的中文名（入口卡文案）
    src = io.open(os.path.join(ROOT, "core", "channel_links.py"),
                  encoding="utf-8").read()
    assert "from core.channels import" in src and "plat_cn" in src, (
        "channel_links 没有从单一事实源取渠道名，加渠道会露裸 id")
