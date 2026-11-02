# -*- coding: utf-8 -*-
"""r834 门禁：配置页「渠道登录」tab 的一键收齐必须**真的收起来**。

实测缺陷（1512）：点「全部收齐」后面板高 1151→1151、可见元素 308→308、
文字长度 1163→1163，但按钮已翻成「全部展开」、aria 写成 false ——
又一个「报一个没发生的状态」。根因：该 tab 的两张卡卡头是 `.uhead`
（#sec-login / #sec-chlinks），不在 cfgFoldAll 认识的
grouplab / rline / chcard / uhead2 / subsec 任何一类里。

修后实测：1151→146，可见元素 308→17，文字 1163→136，两个卡头仍在，
再点一次完全恢复；切 tab 回来保持收齐（FOLD.uhead 存档回放）。
"""
import re

import webui

SRC = webui.PAGE


def test_fold_all_handles_uhead_cards():
    i = SRC.index("function cfgFoldAll()")
    seg = SRC[i:i + 9000]
    assert "_uheadBodies" in seg, (
        "cfgFoldAll 没有处理 .uhead 卡头——登录/渠道入口两张卡收不起来")
    assert "ucard>.uhead" in seg, seg[:200]
    # 判据（_anyOpen）也必须包含这一类，否则第二次点击会判成「还有敞着」
    assert "_uheadBodies(h).some(b=>b.style.display!=='none')" in seg


def test_fold_state_is_replayed_after_rebuild():
    i = SRC.index("function applyFolds()")
    seg = SRC[i:i + 2600]
    assert "FOLD.uhead" in seg, "重建后没有回放 .uhead 折叠存档"


def test_collapsed_uihead_keeps_its_head_visible():
    """收齐后卡头必须留在屏上（回到内容的入口），只收正文。"""
    i = SRC.index("panel.querySelectorAll('.ucard>.uhead').forEach(h=>{\n   const body=_uheadBodies(h);if(!body.length)return;")
    seg = SRC[i:i + 400]
    assert "_setFold(h,body,hide)" in seg, seg
