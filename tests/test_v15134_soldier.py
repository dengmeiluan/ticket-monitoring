# -*- coding: utf-8 -*-
"""r233 Soldier 审查遗留清零钉（_scratch/r233_soldier.md 收尾三案）：

- S-M-3  🔔 持续达标词面单源：multi 主路径（_kpi_block 邻位）与
         遗留单航线路径 desp.replace 各持一份裸字面量，语义统一后
         仍是两处裸表达式——同源词面残留计数钉（LESSONS 十六§3b：
         count==1 即只剩定义处），防后续改词面只改一处再分叉。
- S-M-1  pushLog 渠道小标：备2 落账 ch=urgent 后，推送记录里主推
         与强提醒两条同标题记录并排不可辨、健康面板显英文 raw key
         的兜底面复现——CN 通道映射提升全局 CH_CN 单源，pushLog
         条目渲染 ch 小标（与 renderPushChannels 同源消费）。
         demo 样例带 ch 字段供行为钉与呈现验证。
- 备4    _daily_ops_notes ds 死储：if missing: 内与其后各算一次
         （纯化妆冗余）——提升到分支前单次计算，行为钉由
         test_v15133_wd.test_daily_ops_notes_direct_missing_and_xphan
         护航（重构保绿，不另立行为钉）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15134_soldier.py -q
"""
import os
import sys

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
    src = _src("webui.py")
    assert src.count("const CH_CN=") == 1, (
        "CH_CN 通道映射必须全局唯一定义（renderPushChannels 与 "
        "pushLog 同源消费，局部双份=改名单只改一处再分叉）")
    assert "CH_CN[k]" in src, "健康面板未走全局 CH_CN（仍持局部映射）"
    assert "CH_CN[p.ch]" in src, (
        "pushLog 条目未渲染渠道小标——主推与强提醒同标题记录并排不可辨")
    # demo 样例带 ch 字段：行为钉与演示呈现的数据源
    assert '"ch": "dingtalk"' in src and '"ch": "email"' in src, (
        "demo pushlog 样例未带 ch 字段，渠道小标在演示态不可见")
