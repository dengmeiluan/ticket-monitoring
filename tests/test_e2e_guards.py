# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r616_no_page_errors_across_views.py
- tests/test_r707_no_stretched_card_tail_gap.py

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
import threading
import time
import urllib.request


# ---- merged from tests/test_r616_no_page_errors_across_views.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 三个视图 + 监控页六个子页签 + 配置页三个子页签
_VIEWS = [
    ("mon", "overview"), ("mon", "specials"), ("mon", "trend"),
    ("mon", "watch"), ("mon", "details"), ("mon", "health"),
    ("search", None),
    ("cfg", "login"), ("cfg", "users"), ("cfg", "globals"),
]






def test_app_plat_name_declared_at_top_level():
    """静态旁证：声明行的缩进必须为 0（顶层不是函数体）。

    运行时判据在主测试；这条只防「缩进 0 却仍在函数里」之外的常见笔误，
    并给出比 pageerror 更容易定位的报错。
    """
    import io
    import re
    w = webui_full_src()
    m = re.search(r"^(\s*)const APP_PLAT_NAME=", w, re.M)
    assert m, "找不到 APP_PLAT_NAME 声明"
    assert m.group(1) == "", (
        "APP_PLAT_NAME 声明有 %d 个空格缩进——顶层 const 应顶格"
        % len(m.group(1)))


# ---- merged from tests/test_r707_no_stretched_card_tail_gap.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JS = r"""() => {
  const out=[];
  document.querySelectorAll('body *').forEach(e=>{
    const s=getComputedStyle(e);
    if(s.display!=='flex'||s.flexDirection!=='column')return;
    if(s.visibility==='hidden'||e.offsetHeight<90||e.offsetWidth<120)return;
    const r=e.getBoundingClientRect();
    const kids=[...e.children].filter(k=>k.getBoundingClientRect().height>1);
    if(kids.length<2)return;
    const last=kids[kids.length-1].getBoundingClientRect();
    const tail=r.bottom-last.bottom;
    if(tail<=40)return;
    out.push(((e.id?'#'+e.id:'')+'.'+(e.className||'').toString().split(/\s+/)[0])
             +' h='+Math.round(r.height)+' tail='+Math.round(tail));
  });
  return out;
}"""


