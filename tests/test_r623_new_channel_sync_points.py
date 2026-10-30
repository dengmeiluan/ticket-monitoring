# -*- coding: utf-8 -*-
"""r623：新增渠道必须同步到「日志解析」与「告警名表」。

`core/health.py` 的两条正则和 `core/channel_alert.py` 的 `CN` 都把渠道名
**硬编码**在源码里。新增一个渠道时（如智行 App），只要漏掉其中任一处：

- `_PLAT` / `_SENT` 漏了 → 该渠道的日志行解析不出来，健康卡上直接**没有它**，
  看起来像「这个渠道没在跑」，而不是「解析规则没跟上」；
- `CN` 漏了 → 告警文案里露出 `app_xxx` 原始 id。

这两处漏配都是**静默**的：没有报错、没有空态提示，只是数据凭空少了。
r613 的注释里写了「新增渠道要同步三处」，这份文件把第四、五处也钉住。

判据：`crawlers.REGISTRY` 的每个键都必须出现在上述三处。
负控：从正则里删掉 `app_zhixing` 即红。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


def _alt_list(src, anchor):
    """取某个 `re.compile(` 调用里所有 r"..." 片段中的渠道名。

    正则可能跨行书写（`_SENT` 就是两段拼接），所以先把该 compile 调用
    的整段参数取出来（到匹配的右括号），再收集其中所有原始字符串。
    """
    i = src.index(anchor)
    # 从 anchor 起找配对的右括号
    j = src.index("(", i + len(anchor) - 1)
    depth = 0
    k = j
    while k < len(src):
        ch = src[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        k += 1
    body = src[j:k]
    names = set()
    for part in re.findall(r'r"([^"]*)"', body):
        names.update(p for p in re.split(r"[|()\\\[\]^$]+", part)
                     if re.fullmatch(r"[a-z_][a-z0-9_]*", p))
    return names


def test_health_log_regex_covers_every_registered_channel():
    """正则必须**真的**认得出每个已注册渠道的日志行。

    判据从「源码里有没有这个字面量」改成「喂一行日志进去能不能匹配」：
    `core/health.py` 现在由 `core.channels.BROWSER_CHANNELS +
    APP_CHANNELS` 拼出 `_PLAT_ALT`（单一事实源），字面量已不在正则体内。
    再扫 `_PLAT = re.compile(` 里的 r"..." 片段就永远解析不到，
    变成「代码更对了、门禁却红了」的假红（本文件 r665 实况）。
    """
    from crawlers import REGISTRY
    import core.health as health

    missing = []
    for plat in REGISTRY:
        line = "[%s] 最低价 ￥1200" % plat
        if not health._PLAT.match(line):
            missing.append(("_PLAT", plat))
        sent = "[解析哨兵] %s 字段缺失" % plat
        if not health._SENT.match(sent):
            missing.append(("_SENT", plat))
    assert not missing, (
        "这些渠道的日志行解析不出来（健康卡上像「没在跑」）：%s" % missing)


def test_alert_name_table_covers_every_registered_channel():
    """告警文案里的渠道名表必须覆盖每个已注册渠道，且不多出死条目。

    `core/channel_alert.py` 现在是 `from core.channels import CHANNEL_CN as CN`
    （r665 起的单一事实源），文件里没有内联 `CN = {...}`。这里直接导入运行时
    的 `CN` 对账，不再要求源码里存在某个字面量形状。
    """
    from crawlers import REGISTRY
    from core.channel_alert import CN

    missing = sorted(set(REGISTRY) - set(CN))
    assert not missing, (
        "告警名表 CN 漏了这些渠道（告警里会露原始 id）：%s" % missing)
    ghost = sorted(set(CN) - set(REGISTRY))
    assert not ghost, "告警名表里有 REGISTRY 中不存在的渠道：%s" % ghost
