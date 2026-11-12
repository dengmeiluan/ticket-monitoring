# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v15274_ui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys
import webui


# ---- merged from tests/test_v15274_ui.py ----

SRC = webui_full_src()

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
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






def _boot(pg):
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")




def test_source_contracts():
    assert "let x0=Math.max(win,first), x1=Math.min(now,last+_obs*.02)" in SRC
    assert "grid-template-areas:\"price price price\" \"flight flight flight\" \"dep arr arr\"" in SRC
    assert "#tablecard .tw{overflow:visible" in SRC
    # ≤1100 的横滚渐隐同特异性后置，必须显式 !important 收口
    assert "@media(max-width:900px){#tablecard .tw{-webkit-mask-image:none!important" in SRC










def test_palette_single_source_and_control_baseline():
    assert "qunar:['去哪儿','var(--c-qunar)']" in SRC
    assert "--c-qunar:#0f9aa9" in SRC
    assert "--c-ctrip:#2f6fe4" in SRC
    assert 'style="--pc:var(--c-qunar)"' in SRC
    assert "#opscard .opsbtns>button{height:32px;padding:0 13px" in SRC
    assert "#searchview .srx-probeform>label input," in SRC


def test_config_mobile_rules_are_scoped():
    """防 v1.5.274 回归：页脚三等分必须留在 ≤700 媒体块内，
    块外泄漏会把桌面保存条也撑成全宽。"""
    i = SRC.index("@media(max-width:700px){.cwf-targetrow")
    j = SRC.index("@media(max-width:540px){.cwf-cands", i)
    seg = SRC[i:j]
    assert ".cwf-foot .btn2{min-width:0;height:38px" in seg
    assert ".cwf-chip{min-height:36px}" in seg
    assert SRC.count("@media(max-width:700px){.cwf-targetrow") == 1


def test_city_picker_offers_full_list():
    assert "data-cwshowall" in SRC
    assert "浏览全部 '+list.length+' 个城市" in SRC
    assert "const RR={'国内':0" in SRC
    assert "delete inp.dataset.cwall" in SRC


def test_data_honesty_pins():
    # 移动卡补时效与衔接；CSV 补仅观察；日历不落 near/brk；
    # 关注卡 DB 端点过 6h 时效门；镜像 +1 不再双加号
    assert 'class="mdat stale"' in SRC
    assert "f.layoverT?' · 衔接'" in SRC
    assert "f.cal?'日历价不参与'" in SRC
    assert "not qual and not is_cal and not f.get(\"_stale_h\")" in SRC
    assert "if(h>6)q.stale=Math.max(1,Math.round(h))" in SRC
    assert "['到达',(f.arrTime||'—')+he(f.cross?String(f.cross)" in SRC
    assert "['到达',(f.arrTime||'—')+he(f.cross?String(f.cross).replace(/\\s*天/g,'').trim():'')]" in SRC


