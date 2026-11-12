# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r666_app_channel_name_no_bare_id.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import re


# ---- merged from tests/test_r666_app_channel_name_no_bare_id.py ----

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
