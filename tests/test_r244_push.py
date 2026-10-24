# -*- coding: utf-8 -*-
"""r244 推送层：图顶 summary/运维注「等N条」尾注单源（P-1 + Soldier P0 收口）。

P-1（r244 推送审校 P3-1）：图顶 summary 行预算逐条取，装不下的条数
静默丢弃无留痕——多航线×多日期 8 bits 只显约 3 bits 时「图脱离消息
上下文判档」对未入位航线缺失。

Soldier P0 判例（首版实现被抓）：「等N条」标记若以同分隔符混入
_summary_join 返回段，调用端按 `_rest[count(" ｜ ")+1:]` 的余量切片
会把标记当数据位多跳一条——为消灭静默丢失的改动在同一语义面重新
引入静默丢失。终局形态：join 恒纯函数（标记永不入被切片段），
_summary_lines 单源承载「预算循环+尾注留痕」，summary/ops 两路共用
（三十§3 能力对称）；尾注装得下并回尾行、装不下独立成行（P2-1
不可达分支顺手收口：尾注在任何预算下都有落点）。

度量用伪像素回调（len×系数），零字体依赖 CI 可跑。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r244_push.py -q
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report as _rep  # noqa: E402


def _m(t):
    return len(t)


# ---- _summary_lines：消费契约钉 ----

def test_lines_all_fit_no_tail():
    """全容：单行装下全部 bits，无尾注。"""
    out = _rep._summary_lines(_m, ["aaaa"] * 8, 100000)
    assert len(out) == 1 and "等" not in out[0], out


def test_lines_overflow_tail_merged():
    """超容并入形：4 宽位 25 条预算 45 → 3 行×6 条（39）余 7，
    尾注「 ｜ 等7条」恰 45 并回尾行；渲染段=前 18 条原序。"""
    bits = ["b%02dx" % i for i in range(25)]
    out = _rep._summary_lines(_m, bits, 45)
    assert len(out) == 3, out
    assert out[-1].endswith("等7条"), out
    got = out[0].split(" ｜ ") + out[1].split(" ｜ ") \
        + out[2].split(" ｜ ")[:-1]
    assert got == bits[:18], (got, bits[:18])


def test_lines_overflow_tail_own_line():
    """超容独立形：尾注并回超预算（5 宽位行恰满 45，+尾注 51>45）
    → 尾注独立成行，尾注行被调用端渲染不参与切片。"""
    out = _rep._summary_lines(_m, ["aaaaa"] * 25, 45)
    assert out[-1] == "等7条", out
    assert len(out) == 4, out
    got = [s for ln in out[:3] for s in ln.split(" ｜ ")]
    assert got == ["aaaaa"] * 18, got


def test_lines_empty_items():
    """空 items → 无行（调用端 elif 分支语义不变）。"""
    assert _rep._summary_lines(_m, [], 880) == []


def test_lines_max_three_lines_cap():
    """数据行上限 3（尾注行是额外落点不计入）：溢出位全部进尾注
    计数——接受丢弃但留痕，渲染+尾注计数守恒。"""
    bits = ["b%02dx" % i for i in range(40)]
    out = _rep._summary_lines(_m, bits, 45)
    assert out[-1] == "等22条", out                 # 尾注独立成行
    assert len(out) == 4 and len(out[:-1]) <= 3, out  # 数据行 ≤3
    n_rendered = sum(len(ln.split(" ｜ ")) for ln in out[:-1])
    assert n_rendered + 22 == len(bits), (n_rendered, out)


# ---- 结构钉：join 恒纯 + 两路单源 ----

def test_summary_join_stays_pure():
    """join 函数体（docstring 剔除）禁出现「等」标记逻辑（r244 P0
    判例锁面：标记混入 join 即污染按分隔符切片的调用端）。"""
    import ast
    tree = ast.parse(inspect.getsource(_rep._summary_join))
    fn = tree.body[0]
    body = fn.body
    if body and isinstance(body[0], ast.Expr) \
            and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    code = ast.unparse(ast.Module(body=body, type_ignores=[]))
    assert "等" not in code, "标记混入 _summary_join"


def test_summary_lines_single_source_wiring():
    """summary/ops 两路必须同走 _summary_lines 单源（定义+2 调用点）。"""
    src = open(_rep.__file__, encoding="utf-8").read()
    assert src.count("_summary_lines(") >= 3, \
        "summary/ops 未同走单源 helper"
