# -*- coding: utf-8 -*-
"""本轮 WebUI 层源码钉（D 审计 M-1/M-2 + 增强③）：

1. M-1 联动跳转 hash 丢用户段：pickUser 写 #tab/uN 后，任何
   showMonTab 切 tab 把 hash 覆写成裸 #tab——多用户分享链接落错
   人。showMonTab 尾部 replaceState 统一带 /uN（U 恒 >=0，restoreUI
   钳制兜底）；hashchange 消费端本就解析 #tab/uN 双段，零改动。
2. M-2 跳明细重置筛选静默：jumpCalDate（日历格/走势点两入口共用
   jumpTrendDetail→jumpCalDate）resetFlt 清用户筛选无告知——同族
   jumpQual/mchip 均有 toast，1 行收口对齐。
3. expCsv 导出成功反馈：exportCfg/importCfg 均有成功 toast，CSV
   导出静默同律收口（行数随行）。

行为钉（hash 形态/toast 现身）在 docs/uitest.py 同轮补齐——源码钉
只证声明在场，行为钉证真实生效。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15113_webui.py -q
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_showmontab_hash_keeps_user_segment():
    """showMonTab 的 URL 深链同步带 /uN：tab 写点不再覆写掉
    pickUser 落下的用户段（M-1）；且写点带 !silent 门——silent 档
    （启动恢复唯一调用点）不写 hash，防未恢复的 U=0 污染深链用户段
    与回访者 localStorage 态（Soldier P0）。"""
    src = _src()
    assert re.search(
        r"if\(!silent\)\{try\{history\.replaceState\(null,'','#'\+t\+'/u'\+U\)",
        src), "showMonTab 尾部 replaceState 未带 /uN 用户段或缺 !silent 门"


def test_startup_restore_parses_user_segment():
    """启动块解析 #tab/uN 双段：tab 段跟深链（P2-①，此前只认裸 tab、
    深链 tab 落空）；且仅当 hash 本身无合法 tab（localStorage 回退档）
    才补写裸 tab hash——有合法 tab 时保持原 hash 零污染。"""
    src = _src()
    i1 = src.index("启动恢复：URL 深链优先于 localStorage")
    i2 = src.index("hashchange 消费")
    body = src[i1:i2]
    assert re.search(r"indexOf\('/u'\)", body), "启动块未解析 /u 段"
    assert re.search(r"indexOf\(_ht\)<0", body), \
        "启动块裸 tab 补写缺少「hash 无合法 tab」条件门"


def test_pickuser_hash_write_intact():
    """pickUser 自身写点形态不受扰动（#tab/uN 原样）。"""
    src = _src()
    assert re.search(
        r"replaceState\(null,'','#'\+MONTAB\+'/u'\+i\)", src)


def test_jumpcaldate_reset_toast():
    """jumpCalDate 内 resetFlt 后有重置告知 toast（M-2；与 jumpQual/
    mchip 同族词面「已重置现有筛选」）。"""
    src = _src()
    i1 = src.index("function jumpCalDate")
    i2 = src.index("function jumpTrendDetail")
    body = src[i1:i2]
    assert "resetFlt()" in body
    assert "已重置现有筛选" in body, "jumpCalDate 缺重置筛选告知 toast"


def test_expcsv_success_toast():
    """expCsv 成功路径有 toast（增强③，与 exportCfg 成功反馈同律，
    行数随行）。"""
    src = _src()
    i1 = src.index("function expCsv")
    i2 = src.index("let _ROWS")
    body = src[i1:i2]
    assert "a.click()" in body
    assert "已导出" in body, "expCsv 缺导出成功 toast"


def test_agepolicy_title_enumeration_covers_word_family():
    """agePolicy ⚠ title 枚举覆盖现役词族（含协议/成团人数）：
    词面透传型字段的读屏解释口径随词族演进（Soldier P2-2）。"""
    src = _src()
    assert "航司协议/成团人数" in src
    assert "资格受限专享价" in src
