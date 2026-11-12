# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v15134_soldier.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import sys


# ---- merged from tests/test_v15134_soldier.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*rel):
    with open(os.path.join(_ROOT, *rel), encoding="utf-8") as f:
        return f.read()


def test_sustain_bell_note_single_source():
    """S-M-3：🔔 持续达标正文头词面全文件只允许出现 1 次（定义处）。"""
    src = _src("core", "alerter.py")
    assert src.count("🔔 持续达标（电话已提醒过）") == 1, (
        "持续达标词面残留多处裸字面量（改词面只改一处再分叉的温床）")
    assert "_SUSTAIN_HEAD = " in src, "单源常量 _SUSTAIN_HEAD 未定义"


def test_pushlog_channel_badge_single_source():
    """S-M-1：通道名映射全局单源 + pushLog 条目渲染 ch 小标。"""
    src = webui_full_src()
    assert src.count("const CH_CN=") == 1, (
        "CH_CN 通道映射必须全局唯一定义（renderPushChannels 与 "
        "pushLog 同源消费，局部双份=改名单只改一处再分叉）")
    assert "CH_CN[k]" in src, "健康面板未走全局 CH_CN（仍持局部映射）"
    assert "CH_CN[p.ch]" in src, (
        "pushLog 条目未渲染渠道小标——主推与强提醒同标题记录并排不可辨")
    # demo 样例带 ch 字段：行为钉与演示呈现的数据源
    assert '"ch": "dingtalk"' in src and '"ch": "email"' in src, (
        "demo pushlog 样例未带 ch 字段，渠道小标在演示态不可见")
