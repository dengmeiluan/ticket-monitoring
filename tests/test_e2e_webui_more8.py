# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r339_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import logging
import os
import pytest
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


# ---- merged from tests/test_r339_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False








def _to_cfg(pg):
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.locator("#navCfg").click()
    pg.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    pg.locator('.cnav[data-p="users"]').click()
    pg.wait_for_timeout(250)


def _open_rt_with_7(pg):
    """进配置 users 面板→展开 0:0→开往返→快速选 7 天（D1/D3 共同
    前置；折叠展开走真实点击路径）。"""
    _to_cfg(pg)
    pg.evaluate("""()=>{const h=document.querySelector('.rline[data-rk="0:0"] .rhead');
      if(h&&h.getAttribute('aria-expanded')==='false')h.click();}""")
    pg.wait_for_timeout(400)
    pg.evaluate("""()=>{const chip=[...document.querySelectorAll(
        '.rline[data-rk="0:0"] .schip')]
        .find(c=>c.textContent.indexOf('往返')>=0);
      /* 幂等开：toggleRT 是开合开关，前序测试残留开态时再点=关闭
         （n=1 实录）——chip.on 态才是真实语义位 */
      if(chip&&!chip.classList.contains('on'))chip.click();}""")
    pg.wait_for_timeout(400)
    pg.evaluate("""()=>{const inp=document.getElementById('rfrom-0-0');
      const row=inp&&inp.closest('.srow');
      const dt=row&&row.querySelector('.dline.dtools');
      /* ce35272 渐进披露：工具组折叠 display:none 后 D3 的裁切缘
         断言对零几何恒绿（死钉化）——先真实展开「＋ 添加」恢复牙齿 */
      if(dt&&!dt.classList.contains('open')){
        const t=row.querySelector('.dtools-t');if(t)t.click();}}""")
    pg.wait_for_timeout(300)
    pg.evaluate("""()=>{const q=[...document.querySelectorAll(
        '.rline[data-rk="0:0"] .schip')]
        .find(c=>c.textContent==='去程起7天');if(q)q.click();}""")
    pg.wait_for_timeout(500)


# ---- D1+D2：日期片 flex 排版 ----



# ---- D3：390 档行尾控件不越裁切缘 ----



# ---- D4：通路验证钮不出卡（390） ----



# ---- D5/D6：触控地板声明（源码钉，块归属断言） ----

def test_rthead_touch_floor_in_both_touch_blocks():
    mod = webui_full_src()
    needle = ".rthead{min-height:36px}"
    assert mod.count(needle) >= 2, "rthead 36 地板声明 <2（触控地板缺块）"
    # 按声明归属的最近 @media 条件定性（对子句换序/块重组免疫；
    # 固定窗/固定块序锚都会随合法增厚假红，LESSONS 卅一§3）。
    # 近似盲区备案：嵌套块结束后同层的基础规则会误归属到嵌套条件——
    # 方向安全（多报不漏报），声明迁移出触控块仍会被 any 断言抓住
    ctxs = []
    for m in re.finditer(re.escape(needle), mod):
        ctx = mod[:m.start()]
        i = ctx.rfind("@media")
        ctxs.append(ctx[i: ctx.find("{", i)] if i >= 0 else "")
    assert any("coarse" in c for c in ctxs), f"无 coarse 块承载 36 地板：{ctxs}"
    assert any("760" in c for c in ctxs), f"无 760 块承载 36 地板：{ctxs}"


def test_chhead_after_inset_reaches_36():
    mod = webui_full_src()
    assert ".chhead[role=button]::after{content:'';position:absolute;inset:-10px -8px}" in mod


# ---- D7：快速选 30 天截断+明示 ----



# ---- D9：重复加返程刷新 cfgmsg ----

