# -*- coding: utf-8 -*-
"""r647：样本不足时不得把空缺画成连续线。

用户原话：「走势一定不可以断档」「白白的折叠遮挡短点」。

实测缺陷：`PCHART.gaps([两点相隔 48h], gapMin=4h)` 返回 `[[2]]`——
两点时「间隔」样本只有 1 个，中位数就等于它本身，`×1.8` 后永远大于它，
于是 48 小时空缺被画成一条连续直线。修后返回 `[[1],[1]]`（如实断开）。

同时保证正常场景不变：
  三点 2h 均匀 + 一点在 48h 后 → [[3],[1]]
  四点 2h 均匀 → [[4]]
  单点 → [[1]]
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _gap_code():
    """只取 `const gap=` 那一行代码——注释里会引用旧写法做反例，不能算数。"""
    for line in _gaps_body().splitlines():
        st = line.strip()
        if st.startswith("const gap="):
            return st
    raise AssertionError("gap 判定行不见了")


def _gaps_body():
    src = _src()
    i = src.index("gaps(pts,gapMin){")
    j = src.index("segs.push(cur);return segs;},", i)
    return src[i:j]


def test_small_sample_falls_back_to_gap_min():
    body = _gaps_body()
    assert "iv.length>=3" in body, (
        "间隔样本不足时仍在用中位数判缺口——2 点会把 48h 空缺画成连续线：%s"
        % body[:200])
    assert "gapMin||Infinity" in body, body[:200]


def test_median_rule_kept_for_enough_samples():
    """样本足够时仍用「中位间隔 ×1.8」——不能为了修边界把正常断档改坏。"""
    body = _gaps_body()
    assert "med*1.8" in body, body[:200]


def test_gap_min_only_governs_small_samples():
    """gapMin 只用于**样本不足**时；样本足够时不许它主导判据。

    r647b：原先写 `Math.max(med*1.8, gapMin)`，航线图传 gapMin=分桶粒度
    （48h→144min）时会吃掉中位数判据，把真实 2h 采样的曲线判成逐点断开。
    现在：点数 ≥3 用中位数倍率，否则退回 gapMin。
    """
    code = _gap_code()
    assert "pts.length>=3&&med" in code, code
    assert "med*1.8:(gapMin||Infinity)" in code.replace(" ", ""), code
    assert "Math.max(med*1.8" not in code, "gapMin 又主导了中位数判据"


def test_sample_count_predicate_uses_points_not_intervals():
    """判据必须按**点数**——3 个点只有 2 个间隔，按间隔数判会误落入「样本不足」。

    实测：n3even（3 点、均匀 12h、gapMin=4h）曾被判成 [1,1,1]（整条线消失），
    应为 [3]。
    """
    code = _gap_code()
    assert "iv.length>=3" not in code, (
        "又用「间隔个数≥3」当样本量判据——3 个点只有 2 个间隔会误判")
