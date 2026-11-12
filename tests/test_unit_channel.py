# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r409_all_channels_success_url.py
- tests/test_r615_channel_name_single_source.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import re
import sys


# ---- merged from tests/test_r409_all_channels_success_url.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _read(fn):
    return open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()


def _block(src, anchor, before=0, after=400):
    i = src.index(anchor)
    return src[max(0, i - before):i + after]


def test_ctrip_pc_and_h5_record_url():
    s = _read("ctrip.py")
    for anchor in ('"PC", "ok", rows=len(flights)',
                   '"H5", "ok", rows=len(flights)'):
        assert "url=" in _block(s, anchor), anchor


def test_fliggy_intl_pc_records_url():
    s = _read("fliggy.py")
    assert "url=" in _block(s, '"PC", "ok" if rows'), "国际 PC 未记地址"


def test_fliggy_domestic_pc_records_url():
    s = _read("fliggy.py")
    assert "_last_list_url" in s, "国内 PC 未记录列表页地址"
    assert "url=_pg_url" in s, "国内 PC 未把地址传进 path_note"


def test_tuniu_both_success_paths_record_url():
    s = _read("tuniu.py")
    i1 = s.index('"国际列表接口"')
    assert "url=" in s[i1 - 400:i1], "途牛国际未记地址"
    i2 = s.index('"m.tuniu.com 列表接口"')
    assert "url=" in s[i2 - 400:i2], "途牛国内未记地址"


def test_qunar_intl_success_records_url():
    s = _read("qunar.py")
    i = s.index('"touch.qunar.com 国际列表"')
    assert "url=" in s[i - 500:i], "去哪儿国际未记地址"


def test_tongcheng_window_and_h5list_record_url():
    s = _read("tongcheng.py")
    i = s.index('self.path_note("窗历", "calendar"')
    assert "url=" in s[max(0, i - 700):i + 400]
    j = s.index('"H5列表", "ok"')
    assert "url=" in s[j:j + 400]


# ---- merged from tests/test_r615_channel_name_single_source.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 5 家浏览器渠道的中文名——只允许出现在 Object.assign 的第一参里
_FIVE = "{'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'}"


def _w():
    return webui_full_src()


def test_no_standalone_five_platform_name_table():
    """不允许存在「只有 5 家、且没并入 APP_PLAT_NAME」的独立名单。"""
    w = _w()
    bad = []
    # 只查「以 5 家渠道 id 为键」的正查表；`PK`/`PKEY` 那类
    # 「中文名 → id」的反查表方向相反，不受这条约束。
    for m in re.finditer(
            r"const\s+(\w+)\s*=\s*\{[^}]*'qunar'\s*:[^}]*\};", w):
        name, stmt = m.group(1), m.group(0)
        if "APP_PLAT_NAME" not in stmt:
            bad.append(name)
    assert not bad, (
        "这些渠道名表只列了 5 家、没并入 APP_PLAT_NAME（新渠道会漏）：%s" % bad)


def test_all_three_tables_merge_the_single_source():
    w = _w()
    assert w.count("(typeof APP_PLAT_NAME!=='undefined')?APP_PLAT_NAME:{}") >= 3, (
        "并入 APP_PLAT_NAME 的表少于 3 张（健康卡/节流面板/脉冲条）")


def test_filter_chip_uses_the_name_table():
    """筛选 chip 不能直接打原始渠道 id。"""
    w = _w()
    i = w.index("onclick=\"togChip(this)\"")
    seg = w[i:i + 220]
    assert "CN[p]" in seg, "筛选 chip 仍直接显示原始 id：%s" % seg[:120]


def test_pulse_tooltip_table_merges_app_names():
    """PCN（脉冲条 tooltip 的唯一名源）必须并入 APP_PLAT_NAME。

    这里只做静态断言：`PCN` 定义在概览渲染的作用域内，不是全局变量，
    真渲染探针读不到它（实测 `PCN` 未定义 → 页面评估超时）。
    三张表都走同一个 `Object.assign`，静态判据已足够——动态部分由
    r614 的健康卡渲染断言覆盖（那张表在全局作用域）。
    """
    w = _w()
    i = w.index("const PCN=")
    seg = w[i:i + 260]
    assert "APP_PLAT_NAME" in seg, "PCN 没有并入 APP_PLAT_NAME：%s" % seg[:140]
    assert "'qunar'" in seg and "tuniu" in seg, seg
