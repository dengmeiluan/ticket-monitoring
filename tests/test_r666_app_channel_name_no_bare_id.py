# -*- coding: utf-8 -*-
"""r666：App 渠道名不得以裸 id 出现在任何用户可见位置。

实测现场：接入去哪儿 App 后，概览卡出现
    `全线最低：app_qunar ￥320`
——同一页面其它地方显示「去哪儿 App」，只有这一句漏了。根因是
`Alerter.PLATFORM_CN.get(k, k)` 这类**绕过 plat_cn** 的取名调用：
PLATFORM_CN 只含 5 家浏览器渠道，App 渠道一进来就落到原样 id 上。

r651 只守了 core/alerter.py，这次把 webui.py / report.py 也纳入，
并改为扫**真实调用形态**（`PLATFORM_CN.get(` / `PLATFORM_CN[`），
不匹配注释里提到的表名。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8",
                   newline="").read()


def test_no_raw_platform_cn_lookup_in_ui_or_report():
    """webui / report 里不得再有绕过 plat_cn 的取名。

    允许的形态：`Alerter.plat_cn(...)`。禁止的是把 PLATFORM_CN 当
    「渠道名查询表」直接取（它是**默认渠道全集**，不含 App 渠道）。
    """
    bad = []
    for f in ("webui.py", "report.py"):
        src = _src(f)
        for i, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # 纯注释行里提到表名不算取名
            # 只认真正的取表调用；`PLATFORM_CN = {`、注释里提及不算
            if re.search(r"PLATFORM_CN\s*(?:\.get\(|\[)", line):
                bad.append("%s:%d %s" % (f, i, line.strip()[:90]))
    assert not bad, "仍有绕过 plat_cn 的渠道取名：\n" + "\n".join(bad[:6])


def test_plat_cn_covers_every_app_channel():
    """每个 App 渠道都要有中文名，且不能回落到裸 id。"""
    import sys
    sys.path.insert(0, ROOT)
    from core.alerter import Alerter
    from core.channels import APP_CHANNELS, plat_cn

    for p in APP_CHANNELS:
        assert plat_cn(p) == Alerter.plat_cn(p), (
            "%s 在 core.channels 与 Alerter 里的名字不一致" % p)
        assert plat_cn(p) != p, "%s 没有中文名（界面会露出裸 id）" % p


def test_app_channels_not_in_default_platform_set():
    """默认全集不能含 App 渠道——否则未启用者每轮收假缺勤告警。"""
    import sys
    sys.path.insert(0, ROOT)
    from core.alerter import Alerter
    from core.channels import APP_CHANNELS

    for p in APP_CHANNELS:
        assert p not in Alerter.PLATFORM_CN, (
            "%s 混进了默认渠道全集" % p)
