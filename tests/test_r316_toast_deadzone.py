# -*- coding: utf-8 -*-
"""连败弹窗死区修复（r316 审校 P2-1）：弹窗检查点原只挂 send() 失败
分支，心跳退避稳态下（连败 ≥6 后心跳跳过、每 4 轮放行 1 探）send
落点 streak 序列 10+4k 与 %8==0 代数不相交、首个 8 倍点恰落跳过轮
——纯钉钉拓扑（生产实况）120 轮连败 0 弹窗，「告警系统自身的故障
必须被看见」的设计宣称未兑现（B1 观测互证：钉-1 连败 6 天用户零
感知）。修复=检查点位移：退避跳过轮就地补检查（_streak_due 单源
判定 + _streak_skip_toast 钩子），钉钉/ServerChan 两通道同批。

红线：弹窗是本机浮出不是重发——send 调用次数不因弹窗检查增加
（单发零重试终局裁决不受影响）。"""
import logging

import core.notifier as _n


def _mk_ding(monkeypatch):
    toasts = []
    monkeypatch.setattr(_n, "_channel_streak_toast",
                        lambda lg, ch, body: toasts.append((ch, body)))
    d = _n.DingTalkNotifier("https://oapi.dingtalk.com/robot/send?"
                            "access_token=x", logging.getLogger("t"))
    return d, toasts


def test_streak_due_single_source():
    """8 倍点判定单源：≥8 且 %8==0；7/10/12/15 全 False。"""
    for n, want in ((7, False), (8, True), (10, False), (12, False),
                    (15, False), (16, True), (24, True)):
        assert _n._streak_due(n) is want, n


def test_backoff_skip_rounds_now_reach_toast(monkeypatch):
    """死区复现+修复实效：心跳退避稳态下，跳过轮 streak 递增路径
    落 8 倍点必须弹窗（修复前 120 轮连败 0 弹窗的死区位）。"""
    d, toasts = _mk_ding(monkeypatch)
    d._fail_streak = 6          # 退避起点：6 轮连败已过 HB_BACKOFF_AFTER
    # 纯跳过序列（生产心跳稳态：探测轮放行 send、其余跳过）——
    # 模拟 60 个心跳轮：每 4 轮 1 探（send 失败 streak+1+检查）、
    # 3 轮跳过（streak+1+检查[修复位]）
    for _ in range(60):         # 60 个心跳轮（≈15 小时）
        if d.heartbeat_allow():
            d._fail_streak += 1          # send 失败分支的 streak 推进
            d._streak_check_current()    # send 失败分支尾的检查点
        # 跳过轮的检查点由 heartbeat_allow 内部位移承载（r316 P2-1
        # 修复位）——修复前 due 点落跳过轮即无人检查=死区
    streaks = list(range(7, 67))
    due = [n for n in streaks if _n._streak_due(n)]
    assert due == [8, 16, 24, 32, 40, 48, 56, 64]
    assert len(toasts) == len(due), (toasts, due)
    assert all("钉钉" in ch for ch, _ in toasts)


def test_send_failure_branch_uses_same_gate(monkeypatch):
    """send 失败分支与跳过分支共用 _streak_due 门：8 倍点弹一次、
    非 8 倍点不弹（与旧行为等价，单源防双门漂移）。"""
    d, toasts = _mk_ding(monkeypatch)
    d._fail_streak = 8
    d._streak_check_current()     # 8 落点（send 失败分支形态）
    d._fail_streak = 10
    d._streak_check_current()     # 非倍点
    assert len(toasts) == 1, toasts
    assert "8 轮失败" in toasts[0][1] or "8" in toasts[0][1]


def test_serverchan_skip_branch_same_fix(monkeypatch):
    """ServerChan 同构检查点同批（C1 立案批注）：退避跳过轮落 8 倍
    点同样弹窗。"""
    toasts = []
    monkeypatch.setattr(_n, "_channel_streak_toast",
                        lambda lg, ch, body: toasts.append((ch, body)))
    s = _n.ServerChanNotifier("sckey", logging.getLogger("t"))
    s._fail_streak = 7
    s.heartbeat_allow()           # 跳过轮：streak→8 就地检查
    assert len(toasts) == 1, toasts
    assert "Server酱" in toasts[0][0]


def test_toast_is_not_a_resend(monkeypatch):
    """红线：弹窗路径零网络 send——检查点触发的轮不产生任何额外
    httpx 调用（单发零重试终局裁决不受影响）。"""
    calls = []
    monkeypatch.setattr(_n.httpx, "post",
                        lambda *a, **k: calls.append(a))
    d, toasts = _mk_ding(monkeypatch)
    d._fail_streak = 7
    d.heartbeat_allow()           # 跳过轮→streak 8→弹窗检查
    assert toasts
    assert calls == [], calls     # 零网络调用
