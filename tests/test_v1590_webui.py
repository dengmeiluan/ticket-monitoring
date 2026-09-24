# -*- coding: utf-8 -*-
"""WebUI 第 v1590 批回归（源码钉）：D 路审计 P1-1/P2×3 修复 +
agePolicy 词面扩「资格受限」语义三端同轮。

- P1-1 savebar 泄漏：800ms 巡检的视图早退在 savebar toggle 之前——
  cfg 弄脏后切监控视图，未保存浮条永久浮在监控页不回收。修法=
  toggle（及 saveTxt）提到早退之前（源码顺序钉）。
- P2-1 暗色 qual 行 .stl 子行对比度 4.48:1 擦线差 0.02：暗色单行
  提亮 #8ba0b4（限定 tr.qual .stl 单点，不动全局 --mut 影响面）。
- P2-2 .hc 触控热区高 35px 差 1px 达 36 基准：纵向 -10→-11px
  （横向 -1px 防串格纪律不动）。
- P2-3 header 三开关读屏播态：ntBtn/denBtn aria-pressed、themeBtn
  aria-label 带当前态名（三态件布尔 pressed 语义错）。
- agePolicy：会员专享资格价并入后 title「年龄受限」词面扩为
  「资格受限」通用语义（限青年·限携程会员 拼接形态同格承接）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1590_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(_BASE, "webui.py"), encoding="utf-8").read()


def test_savebar_toggle_before_view_early_return():
    """P1-1：savebar toggle 必须在 800ms 巡检的视图早退之前——
    cfg 弄脏切监控后浮条回收（泄漏钉；锚定 dirty 巡检段内顺序，
    全文件首个同款早退在别的函数属正常）。"""
    src = _src()
    seg = src.find("setInterval(()=>{\n  const dirty=cfgIsDirty()")
    assert seg != -1, "dirty 巡检段缺失"
    i_sb = src.find("const sb=$('savebar')", seg)
    i_ret = src.find("if(VIEW!=='cfg')return;", seg)
    assert i_sb != -1 and i_ret != -1, "savebar 巡检段缺失"
    assert i_sb < i_ret, "savebar toggle 仍在视图早退之后（浮条泄漏回归）"


def test_dark_qual_stl_contrast_lift():
    """P2-1：暗色 qual 行内 .stl 子行提亮单点规则在场（4.48→≥4.5）。"""
    assert 'html[data-theme="dark"] tr.qual .stl{color:#8ba0b4}' in _src()


def test_hc_touch_target_36px():
    """P2-2：.hc 热区纵向 -11px（35→37px 过触控基准；横向 -1px 防串格）。"""
    assert ".hc::after{content:'';position:absolute;inset:-11px -1px}" in _src()


def test_header_switches_screen_reader_state():
    """P2-3：三开关回设点各补读屏播态（ntBtn/denBtn 布尔 pressed、
    themeBtn 三态用 aria-label 带当前态名）。"""
    src = _src()
    assert "aria-pressed" in src
    assert "setAttribute('aria-pressed',NT.on?'true':'false')" in src, \
        "ntBtn 缺 aria-pressed 回设"
    assert "setAttribute('aria-label'" in src and "跟随系统" in src, \
        "themeBtn 缺带态 aria-label 回设"
    assert "setAttribute('aria-pressed',d==='compact'?'true':'false')" in src, \
        "denBtn 缺 aria-pressed 回设"


def test_age_policy_title_eligibility_wording():
    """agePolicy title 扩「资格受限」语义（会员/年龄合并词面同格）。"""
    src = _src()
    assert "资格受限专享价" in src, "title 未扩资格受限语义"
    assert "年龄受限专享价" not in src, "旧「年龄受限」词面残留"
