# -*- coding: utf-8 -*-
"""r612：干预账写入失败不能无声。

所有 `save_intervention()` 调用点都是

    try: storage.save_intervention(...)
    except Exception: pass

这个写法本身是对的——账本故障不该拖垮采集。但它让**干预记录静默消失**：
只读库、表缺失、锁超时（实测抛 `OperationalError: attempt to write a
readonly database`）之后，界面表现成「这次干预没发生过」——溯源面板里
找不到，干预成功率也不会把它算进去。而干预恰恰是最需要事后可溯源的一类操作。

修法只做一件小事：异常照旧向上抛（**不改控制流**，调用方的 try/except
继续生效），但抛之前在日志里留一条「这条干预不会出现在溯源里」。
同时返回值从 None 改成 True，便于将来调用方按需判断。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _storage():
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "iv.db")
    return PriceStorage(db), db


def test_successful_write_returns_true():
    st, _ = _storage()
    assert st.save_intervention("ctrip", "warmup") is True


def test_failed_write_logs_and_still_raises(caplog):
    """失败必须 ① 留日志 ② 仍抛异常（调用方的 try/except 语义不变）。"""
    import logging
    st, db = _storage()
    st.save_intervention("ctrip", "warmup")
    os.chmod(db, 0o444)
    raised = False
    with caplog.at_level(logging.WARNING):
        try:
            st.save_intervention("ctrip", "verify")
        except Exception:
            raised = True
    assert raised, "写入失败没有抛出——调用方的 try/except 语义被改了"
    txt = "\n".join(r.message for r in caplog.records
                    if hasattr(r, "message"))
    if not txt:  # 某些环境 caplog 抓不到子 logger，退回看 getMessage
        txt = "\n".join(r.getMessage() for r in caplog.records)
    assert "写入失败" in txt and "溯源" in txt, (
        "写入失败没有留下可检索的告警：%r" % txt)


def test_rollback_does_not_leave_partial_rows():
    """失败后不得留下半条记录（溯源里不能出现「有干预无内容」的行）。"""
    st, db = _storage()
    st.save_intervention("ctrip", "warmup")
    before = len(st.interventions(platform="ctrip", limit=50))
    os.chmod(db, 0o444)
    try:
        st.save_intervention("ctrip", "verify")
    except Exception:
        pass
    after = len(st.interventions(platform="ctrip", limit=50))
    assert after == before, "写入失败却留下了记录：%d -> %d" % (before, after)
