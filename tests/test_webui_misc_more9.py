# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r260_webui.py
- tests/test_v204_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import logging
import os
import pytest
import subprocess
import sys
import tempfile
import time
import urllib.request

from webui import PAGE


# ---- merged from tests/test_r260_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("t260w")


def _page_src():
    import webui
    return webui.PAGE


# ---------- U1: 状态 pill 状态符单源 ----------

def test_pill_state_calls_have_no_status_emoji():
    """pillState 全部调用实参零状态 emoji：词面侧退役、::before
    色档单源（达标 .pill.ok 绿脉冲 / 常态 --mut 灰点）。"""
    import re as _re
    src = _page_src()
    calls = _re.findall(r"pillState\(([^;]*?)\);", src)
    assert len(calls) >= 6, "pillState 调用面清零=API 漂移"
    for c in calls:
        for e in ("⚪", "🚨", "❌", "✅", "⚠"):
            assert e not in c, f"pill 词面内嵌状态 emoji {e!r}: {c.strip()[:60]}"


def test_pill_dot_carrier_intact():
    """状态点载体在位：.pill::before 圆点 + .pill.ok 绿脉冲（状态
    语言唯一出口），词面退役后不出现「无点无 emoji」的裸文案态。"""
    src = _page_src()
    assert ".pill::before{content:'';width:7px;height:7px;" in src
    assert ".pill.ok::before{background:var(--green);" in src


# ---------- U2: 健康卡时间窗词面统一 ----------

def test_health_window_wording_single_form():
    src = _page_src()
    assert "近 24 小时" not in src, "同卡「近 24 小时/近 24h」双词面"
    # 同族全收口：空态说明行（健康卡 ×2）与走势空态（48h）同律，
    # 钉面锁全族清零——只锁「近 」前缀形态会漏空态行
    assert "24 小时" not in src and "48 小时" not in src, (
        "「N 小时」词面残留（与控件/chip 的「48h」族双轨）")
    assert src.count("近 24h") >= 3, "seclab/计数行/推送通道段三处统一"


# ---------- U3: 日期分隔符统一 MM/DD ----------

def test_tg_pill_and_transfer_date_slash_form():
    src = _page_src()
    # 日期斜杠轨已收口 dSlash 单源（r261）：钉面随形态改写，
    # 语义担保保留——消费点必须走单源而非内联换装
    assert "function dSlash(" in src, "dSlash 日期短标单源缺失"
    # 改期胶囊：lo[0]（MM-DD）与全站惯例同形
    assert "${he(dSlash(lo[0]))}" in src, (
        ".tg 胶囊日期未走 dSlash 单源（MM-DD 形态与同格簇 mdat MM/DD 双分隔符）")
    # 二段起飞日期同族漏点：transGoDate 直出 MM-DD
    assert "dSlash(f.transGoDate)" in src, (
        "二段起飞日期未走 dSlash 单源（同族漏点）")


# ---------- U4: 时长词面归一 ----------

def test_dur_txt_defined_and_wired():
    src = _page_src()
    assert "function durTxt(" in src, "durTxt 单源缺失"
    assert "${he(durTxt(f.dur))||'—'}" in src, "dur 列未走 durTxt 归一"




# ---------- U5: 失败态词面去重 ----------

def test_failure_state_no_dup_wording():
    src = _page_src()
    assert "（服务未启动）" not in src, (
        "updated 槽与 pill 同屏双「服务未启动」")
    assert "$('updated').textContent='';_markStale();" in src, (
        "冷启动失败分支 updated 槽应改空（增量信息由 _markStale 骨架承载）")


# ---------- U6: 预览弹层焦点归还正面钉 ----------

def test_pv_focus_return_chain():
    src = _page_src()
    assert "_PV_RETURN=document.activeElement" in src, "开层记录缺失"
    assert "const ret=_PV_RETURN;_PV_RETURN=null;" in src, "关层取件缺失"
    assert "ret.focus()" in src, "归还调用缺失"


# ---------- playwright srv fixture（demo 实例，行为钉共用；r251 形态） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _srv_log_tail(logf):
    try:
        logf.flush()
        logf.seek(0)
        return logf.read()[-600:]
    except Exception:
        return "(日志不可读)"




# ---- merged from tests/test_v204_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _src():
    import webui as _w
    with io.StringIO(webui_full_src()) as fh:
        return fh.read()


# ---- carryon 三端（爬虫键见 test_v204_fields；此处白名单/渲染门） ----

def test_v204_carryon_payload():
    assert '"carryon": (f.get("carryon") or "").strip(),' in _src()


def test_v204_carryon_csv():
    assert ",'直挂','托运额','手提额','经停'," in PAGE
    assert ("(f.bagState==='direct'?'是':(f.bagState==='recheck'?'需转运':''))"
            ",f.baggage||'',f.carryon||'',"
            "f.stop?('是'+(f.stopWin?'('+f.stopWin+')':'')):''") in PAGE


def test_v204_carryon_title():
    # title 悬停承载（baggage 同款分隔符链：前文有无判'｜'，
    # carryon 与前后段的分隔条件同步扩，防粘连/孤立分隔符）
    assert "(f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null)" in PAGE
    assert ("(f.baggage?he(f.baggage):'')"
            "+((f.labels||f.labelNote||f.baggage)&&f.carryon?'｜':'')"
            "+(f.carryon?he(f.carryon):'')") in PAGE
    assert ("((f.labels||f.labelNote||f.baggage||f.carryon)"
            "&&f.bizPrice!=null?'｜':'')") in PAGE
    assert ("(f.labels||f.labelNote||f.bizPrice!=null||f.baggage||f.carryon"
            ")?'｜':'')") in PAGE


# ---- P1-1：sticky 可达（.tw 放开内滚）+ 三条内滚路径重接线 ----

def test_v204_tw_maxheight_released_in_540_block():
    # ≤540 块内、sticky 规则之后追加 .tw{max-height:none}（同块置尾，
    # 置尾纪律：媒体块内同特异性后者胜）。窗口取块边界（下一个
    # @media）而非固定字符数——块内合法增厚（r326 chips 横滚档）
    # 会把目标推出固定窗，卅一§3 窗口截断钉判例
    i540 = PAGE.index("@media(max-width:540px)")
    j540 = PAGE.find("@media", i540 + 10)
    block = PAGE[i540:j540 if j540 > 0 else i540 + 20000]
    assert "#montab-details .tabs{position:sticky;" in block
    assert ".tw{max-height:none}" in block
    assert block.index("position:sticky") < block.index(".tw{max-height:none}")


def test_v204_window_scroll_append_gate():
    # 页面滚动续载（≤760 窄档）：窗口监听 + 动态宽度门（旋转跨档即时
    # 生效，媒体特性动态查询放 handler 内）；宽度族随 541-760 带
    # .tw 放开跟页滚扩带 540→760（明细吸顶可达的结构前提）
    assert "window.addEventListener('scroll',function()" in PAGE
    assert "if(window.innerWidth>760)return;" in PAGE
    assert "window.innerHeight+window.scrollY>document.documentElement.scrollHeight-600" in PAGE


def test_v204_tw_listener_desktop_gate():
    # .tw 监听桌面档互斥门：≤760 窄档 .tw 无纵向内滚（scrollHeight==
    # clientHeight），水平滚动的 scroll 事件会伪真触发近底条件补片
    # （宽度族随 541-760 带放开扩带 540→760）
    assert "if(window.innerWidth<=760)return;" in PAGE


def test_v204_jump_bottom_page_branch():
    # End 跳底 ≤540 分支：页面滚动到底（.tw.scrollTop 在无内滚容器
    # 上是 no-op）
    assert "window.scrollTo(0,document.documentElement.scrollHeight)" in PAGE


def test_v204_rebuild_page_scroll_restore():
    # ≤540 重建滚动位恢复：内容高塌缩先被浏览器钳位，须先补齐切片
    # 至原落点再 scrollTo 回设（原 tw.scrollTop 快照模式对页滚无效）
    assert "window.scrollTo(0,wy)" in PAGE


# ---- P2-1：脏态三色统一（token 单源）----

def test_v204_dirty_state_single_color():
    # navDirty 在 header 底上：--warn 4.42:1 欠 AA（r248 W2）→
    # --warn-deep（.hbadge.mid/.upill.warn 同底同改家族）；cfgDirty/
    # savebar dot 衬 card 底维持 --warn——各按衬底取达标令牌，
    # 语义仍是「每处脏态点一个令牌不漂移」
    assert 'id="navDirty" style="display:none;color:var(--warn-deep)' in PAGE
    assert 'id="cfgDirty" role="status" aria-live="polite"' in PAGE
    assert ".cfgchrome .cc-chip.warn{color:var(--warn-deep)" in PAGE
    assert (".savebar .dot{width:8px;height:8px;border-radius:50%;"
            "background:var(--warn)") in PAGE


# ---- P2-2：页脚/demoBar 链接触控热区外扩 ----

def test_v204_touch_hotspot_expansion():
    assert "#foot a,.demoBar a,.verbar a{position:relative}" in PAGE
    assert ("#foot a::after,.demoBar a::after,.verbar a::after"
            "{content:'';position:absolute;inset:-10px -4px}") in PAGE
