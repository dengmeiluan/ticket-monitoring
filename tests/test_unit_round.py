# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r772_round_trip_scope_hint.py
- tests/test_r781_round_trip_evidence_discipline.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import pytest
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


# ---- merged from tests/test_r772_round_trip_scope_hint.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READ_TITLES = """() => Array.from(document.querySelectorAll(
  '[onclick*=toggleRT]')).map(e=>{
    const rk = e.closest('.rline') ? e.closest('.rline').dataset.rk : '';
    let intl = false;
    try {
      const ij = (rk||'').split(':').map(Number);
      const r = (typeof CFG!=='undefined' && CFG[ij[0]]
        && CFG[ij[0]].routes) ? CFG[ij[0]].routes[ij[1]] : null;
      intl = !!(r && typeof isIntlCode==='function'
        && isIntlCode(r.to || ''));
    } catch(_){}
    return {title:e.getAttribute('title')||'', intl:intl};
  })"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p












# ---- merged from tests/test_r781_round_trip_evidence_discipline.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "INTL_DESIGN.md")

# 能证明「这条 n 是结论而非故障」的证据词
POSITIVE = ("单程出数", "单程能正常出数", "单程正常", "仪器有效",
            "前端直接丢弃", "恒 444", "只有去程", "无航线",
            "请求体确为双段", "单程正控")
# 明确「测不出」的自述（允许写 n 但必须标注不可判定）
UNDECIDED = ("测不出", "不可判定", "无法判定", "通路本身不可用",
             "正控不成立")


def _doc():
    if not os.path.exists(DOC):
        pytest.skip("INTL_DESIGN 已删（W7 docs 二次精简），本门禁失去检查对象")
    return io.open(DOC, encoding="utf-8").read()


def test_round_trip_n_rows_state_their_evidence():
    """判 n 的行要能说清「为什么是 n」；判通的不用。

    只挑**否定结论**的行：出现「不支持 / 取不到 / 暂不支持 / 仍 unsupported」
    而**没有**「实测接通 / 支持（」这类正面字样的行。
    """
    txt = _doc()
    rows = [ln for ln in txt.splitlines()
            if ln.startswith("|") and "往返" in ln]
    assert rows, "参数表里找不到任何往返相关行"
    NEGATIVE = ("不支持", "取不到", "暂不支持", "仍 unsupported", "仍为不支持")
    SUPPORTED = ("实测接通", "真报文")
    bad = []
    for ln in rows:
        if not any(w in ln for w in NEGATIVE):
            continue
        if any(w in ln for w in SUPPORTED):
            continue          # 判通的行不在此列
        if any(w in ln for w in POSITIVE) or any(w in ln for w in UNDECIDED):
            continue
        bad.append(ln[:110])
    assert not bad, (
        "这些行判了往返不行，却没给证据（单程可用/请求层拒绝）也没标"
        "「测不出」：%s" % bad)


def test_soft_reject_signature_is_named_as_soft_reject():
    """飞猪那条必须写明「软频控」，否则下次又被读成能力缺失。"""
    txt = _doc()
    assert "软频控" in txt or "success\":false" in txt, (
        "没把飞猪的 65B success:false 体标成软频控——会被误读成不支持")


def test_no_bare_unsupported_without_positive_control():
    """反向守：文档里出现「测不出」时，必须同时出现「正控」这个词。

    避免「测不出」被当成一个可以随手打的标签——它是有前提的：
    必须先试过单程。
    """
    txt = _doc()
    if "测不出" in txt:
        assert "正控" in txt, (
            "写了「测不出」却没提「正控」——判据纪律不完整，"
            "读者不知道测不出的前提是单程也失败")
