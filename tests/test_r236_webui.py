# -*- coding: utf-8 -*-
"""r236 WebUI 批（UI 审计 _scratch/audit_r236_webui.md 落地）：

- P1-1 canvas 高度「取大」语义重落（r235 P2-5 的 min(38vh,28vw) 对
  名目标带零实效：1024-1919 宽短带 28vw 恒大于 38vh，min 恒取 38vh
  ——1440×700 实测画布仍 1246×266=4.68:1 与病灶逐字节同；且 min 在
  窄高窗反向变矮 760×900 342→240。max 语义：宽短带真正抬升、窄高窗
  复原 38vh、移动端回到 240 地板由 clamp 下限承载）。
- P2-1 /api/config 失败分支落点：loadCfg catch 原只写 cfgmsg+toast，
  #cfgglobals 静态「加载中…」永不到达（二十三§1 失败分支是静态骨架
  的第二主人）——catch 补错误态改写。
- P3-1 demo 态数据来源词面 ×3 过 s.demo 分支（十六§7：凡提及端口/
  服务/数据来源的文案都要过 demo 分支）：健康卡「解析自 monitor.log」
  /轮日志 pvFoot「完整日志见 logs/monitor.log」/推送记录 pvFoot
  「本地存档回放」——demo 全为合成数据，三处词面对演示用户失实。
- P3-3 montabs tablist 关联：tabAria 已有 role=tablist/tab/
  aria-selected，缺 aria-controls ↔ role=tabpanel 引用关联
  （WCAG 1.3.1 信息与关系）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r236_webui.py -q
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_canvas_height_max_semantics():
    """P1-1：高度式 min→max——宽短带（28vw>38vh）真正抬升，窄高窗
    复原 38vh 既有几何；min 旧式不得残留。"""
    src = _src()
    assert "clamp(240px,max(38vh,28vw),360px)" in src, \
        "canvas 高度式未按 max 语义重落"
    assert "min(38vh,28vw)" not in src, "min 旧式残留（对目标带零实效）"


def test_loadcfg_failure_lands_in_cfgglobals():
    """P2-1：loadCfg 失败分支必须改写 #cfgglobals 静态「加载中…」
    （catch 原只写 cfgmsg+toast，面板骨架永不到达）。"""
    src = _src()
    assert "cfgErr('配置读取失败: '+e)" in src, "loadCfg catch 锚点易位"
    assert "_cg=$('cfgglobals')" in src, "catch 未补 cfgglobals 错误态落点"


def test_demo_wording_health_source():
    """P3-1a：健康卡数据来源词面随 s.demo 切换（demo=合成数据）。"""
    src = _src()
    assert 'id="hsrcNote"' in src, "健康卡来源词面未提为 JS 可切节点"
    assert "s.demo?'演示合成数据':'解析自 monitor.log'" in src


def test_demo_wording_pvfoot_log():
    """P3-1b：轮日志弹层脚注 demo 分支（demo 无 logs/monitor.log）。"""
    src = _src()
    assert "(S&&S.demo)?'演示模式 · 合成轮日志回放'" in src


def test_demo_wording_pvfoot_push():
    """P3-1c：推送记录弹层脚注 demo 分支（demo 无本地存档）。"""
    src = _src()
    assert "(S&&S.demo)?'演示模式 · 合成推送记录回放'" in src


def test_montabs_aria_controls_tabpanel():
    """P3-3 退役改写（r275）：#montabs 混入多租户切换 chip（非 tab
    子件）后按 #tabs 同律降 button 形态——tab↔tabpanel 引用关联随
    tablist 形制退役（禁复活）；面板侧 role=tabpanel 静态在位与
    aria-label 可访问名回写保留（实效档）。"""
    src = _src()
    assert "setAttribute('aria-controls','montab-'" not in src, \
        "tab↔tabpanel 引用关联复活"
    assert src.count('role="tabpanel"') == 4, \
        "tabpanel 数量=%d 应为 4" % src.count('role="tabpanel"')
    assert "PNAME" in src and "montab-'" in src, \
        "面板 aria-label 回写缺席"
