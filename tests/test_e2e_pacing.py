# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1058_pacing_channels_cap.py
- tests/test_r638_pacing_is_its_own_section.py
- tests/test_r660_pacing_reading_not_clipped.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1058_pacing_channels_cap.py ----

pytest.importorskip("playwright",
                    reason="节流清单裁量依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




SNAP = """(() => {
  const box=document.getElementById('paceBox');
  if(!box) return {exists:false};
  const list=box.querySelector('.pace-ch');
  const rows=list?[...list.querySelectorAll('.pace-row')]:[];
  const btn=box.querySelector('.pace-morebtn');
  const r=btn?btn.getBoundingClientRect():null;
  return {exists:true, n:rows.length,
    visible:rows.filter(x=>x.getBoundingClientRect().height>1).length,
    btnDisp:btn?getComputedStyle(btn).display:'none',
    txt:btn?(btn.textContent||'').trim():'',
    aria:btn?btn.getAttribute('aria-expanded'):null,
    box:r?[Math.round(r.left),Math.round(r.top+window.scrollY),Math.round(r.width)]:null,
    over:document.documentElement.scrollWidth>innerWidth+1};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1500)
    pg.evaluate("()=>{switchView('mon');showMonTab('health');"
                "const f=document.getElementById('hpaceFold');"
                "if(f)f.open=true;}")
    pg.wait_for_timeout(2600)
    # 节流面板的 10 行是异步二次渲染；固定等待在 xdist 并发下会量到 0 行。
    # r1460：同一模块里前一条用例（390 档）先跑完后，这一条在慢/负载高时
    # 12s 内等不到 10 行（本机实测「单跑绿、连跑红」）。等不到就自己驱动一次
    # loadPacing()（= 用户点刷新），再等；判据不变。
    COND = "()=>document.querySelectorAll('#paceBox .pace-row').length>=10"
    try:
        pg.wait_for_function(COND, timeout=12000)
    except Exception:
        pg.evaluate("()=>{try{loadPacing()}catch(e){}}")
        pg.wait_for_function(COND, timeout=20000)
    # 并行负载下「行已入 DOM」早于切换动画/面板可见；不等到真实高度会把
    # 桌面误读成 0 行。仍不可见则照常判红。
    pg.wait_for_function(
        "()=>{const r=document.querySelector('#paceBox .pace-ch .pace-row');"
        "return r&&r.getBoundingClientRect().height>1}", timeout=12000)


def _assert_box_stable(a, b, stage):
    """按钮自身不得位移；允许 ±2px 的亚像素/滚动条凑整抖动，
    但宽度必须一致（文案切换不能改按钮盒）。"""
    assert a is not None and b is not None, "%s时按钮丢失：%s -> %s" % (stage, a, b)
    assert a[2] == b[2], "%s时按钮宽度变了：%s -> %s" % (stage, a, b)
    assert abs(a[0] - b[0]) <= 2 and abs(a[1] - b[1]) <= 2, \
        "%s时按钮位置跳了：%s -> %s" % (stage, a, b)






# ---- merged from tests/test_r638_pacing_is_its_own_section.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 拆到新分区的控件 id（一个都不能留在全局参数里）
PACING_IDS = (
    "glbQs", "glbQe", "glbFast", "glbSlow", "glbNear", "glbStg", "glbGap",
    "glbRpm", "glbBrk", "glbHpen", "glbHok", "glbHslow", "glbHsf",
    "glbHslf", "glbHms", "glbBbs", "glbBcs", "glbWarm", "glbWarmP",
    "glbLcd", "glbNearD",
)


_CACHE = {}
















# ---- merged from tests/test_r660_pacing_reading_not_clipped.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FULL = ("近24h国内 30% · 国际 50% · App 航班列表 30%（需登录 12 · 软拒 3） · "
        "登录态快照恢复 ×1 · 模拟器运行时 0% · 日历 50% · 查询 30% · "
        "明细 0 / 日历 0 · 60 次")


def _payloads():
    scopes = {
        "dom": {"query_attempts": 40, "query_rate": 0.3,
                "query_rate_live": 0.3, "query_attempts_live": 40,
                "rate": 0.3,
                "paths": {
                    "app-list": {"attempts": 40, "ok": 12, "detail_ok": 8,
                                 "calendar_ok": 4, "rate": 0.3,
                                 "rate_excl_empty": 0.3, "login": 12,
                                 "soft": 3, "empty": 4, "unsupported": 0,
                                 "last_at": "10-30 05:20:00"},
                    "snap-restore": {"attempts": 9, "ok": 1, "detail_ok": 0,
                                     "calendar_ok": 1, "rate": 0.11,
                                     "rate_excl_empty": 0.11, "login": 0,
                                     "soft": 0, "empty": 0,
                                     "unsupported": 0,
                                     "last_at": "10-30 05:20:00"},
                    "android-runtime": {"attempts": 63, "ok": 0,
                                        "detail_ok": 0, "calendar_ok": 0,
                                        "rate": 0, "rate_excl_empty": 0,
                                        "login": 0, "soft": 0, "empty": 0,
                                        "unsupported": 0,
                                        "last_at": "10-30 05:20:00"}}},
        "intl": {"query_attempts": 20, "query_rate": 0.5,
                 "query_rate_live": 0.5, "query_attempts_live": 20,
                 "rate": 0.5,
                 "paths": {"日历": {"attempts": 20, "ok": 10, "detail_ok": 4,
                                    "calendar_ok": 6, "rate": 0.5,
                                    "rate_excl_empty": 0.5, "login": 0,
                                    "soft": 0, "empty": 0, "unsupported": 0,
                                    "last_at": "10-30 05:20:00"}}},
    }
    paths = {"paths": {k: dict(v) for k, v in {
        "app-list": {"attempts": 40, "ok": 12, "detail_ok": 8,
                     "calendar_ok": 4, "rate": 0.3, "rate_excl_empty": 0.3,
                     "login": 12, "soft": 3, "empty": 4, "unsupported": 0},
        "snap-restore": {"attempts": 9, "ok": 1, "detail_ok": 0,
                         "calendar_ok": 1, "rate": 0.11,
                         "rate_excl_empty": 0.11, "login": 0, "soft": 0,
                         "empty": 0, "unsupported": 0},
        "android-runtime": {"attempts": 63, "ok": 0, "detail_ok": 0,
                            "calendar_ok": 0, "rate": 0,
                            "rate_excl_empty": 0, "login": 0, "soft": 0,
                            "empty": 0, "unsupported": 0},
        "日历": {"attempts": 20, "ok": 10, "detail_ok": 4, "calendar_ok": 6,
                 "rate": 0.5, "rate_excl_empty": 0.5, "login": 0, "soft": 0,
                 "empty": 0, "unsupported": 0}}.items()},
        "retired": ["app-dump", "app-blocker"], "scopes": scopes,
        "query_rate_live": 0.3, "query_attempts_live": 60}
    pacing = {
        "ok": True, "quiet": {}, "last_round": {"trips": []},
        "cfg": {"min_gap_s": 0, "per_minute": 0}, "effect": {},
        "channels": {"app_zhixing": {
            "state": "path_degraded", "reason": "", "needs_login": False,
            "advice": {"state": "path_degraded", "action": "route",
                       "hint": "国内 近 24h 有效率 30%"}}}}
    return pacing, {"demo": False, "platforms": {"app_zhixing": paths}}








def test_css_keeps_both_halves_shrinkable():
    import io
    src = webui_full_src()
    i = src.index(".pace-row .ev .e2{")
    seg = src[i:i + 260]
    assert "flex:none" not in seg, "e2 又变成不可收缩，中档会被裁"
    assert "white-space:nowrap" not in seg, "e2 又禁止换行，中档会被裁"
    j = src.index(".pace-row .ev .e1{")
    assert "min-width:0" in src[j:j + 140], "e1 必须可收缩（省略号收口）"
