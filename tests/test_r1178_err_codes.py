# -*- coding: utf-8 -*-
"""r1178：错误码表——每个码必须能翻成人话 + 恰好三个动作 + 指向真实出处。

用户原话：「一滑块就会报错请点击重试，有错误码，必须分析出来原因」。
现状：`50003` / `error:x2VW8` / `710114/needLogin` / `HTTP 202` 这些串只出现在
日志和账本里，页面上一句解释都没有。本文件守住这张表的**质量底线**：
不许编、不许只有一个动作、也不许把"停服"和"重试"混成一类。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import err_codes as EC  # noqa: E402


def test_self_check_is_clean():
    assert EC._self_check() is None, EC._self_check()


def test_every_entry_has_three_actions_and_kind():
    for it in EC.table():
        assert it["kind"] in EC.KINDS, it
        assert len(it["acts"]) == 3, it
        assert it["kind_cn"], it


def test_docs_point_at_real_files():
    """出处必须真的存在——否则"去文档看"就是骗人。"""
    for code, it in EC.ERR_CODES.items():
        doc = it["doc"]
        assert os.path.isfile(os.path.join(ROOT, doc)), \
            "码 %s 的出处不存在：%s" % (code, doc)


def test_recognizes_codes_inside_real_strings():
    """真实的现场串（含前后缀）都要认出来。"""
    cases = [
        ("请点击重试(error:x2VW8)", "x2VW8"),
        ("HTTP 50003 环境存在风险", "50003"),
        ("listFlight 710114/needLogin", "710114"),
        ("userBaseInfo ret=False errcode=22032", "22032"),
        ("HTTP 202 空壳", "202"),
        ("App 被切到 ContainerActivity 白屏", "安全容器"),
    ]
    for raw, want in cases:
        got = EC.explain(raw)
        assert got["code"] == want, (raw, got)


def test_22032_not_confused_with_202():
    """负控：22032 不能被短码 202 抢走。"""
    assert EC.explain("errcode=22032")["code"] == "22032"


def test_unknown_is_honest():
    """负控：没收录的码不许编一个解释出来。"""
    got = EC.explain("some weird error 987654")
    assert got["code"] is None
    assert got["kind"] == "unknown"
    assert len(got["acts"]) == 3
    assert "还没有人翻译过" in got["cn"]


def test_hard_block_is_not_a_retry_challenge():
    """50003 属硬风控：动作里必须出现"冷却/别重试"，不能在教用户连点。"""
    got = EC.explain("50003")
    joined = " ".join(got["acts"])
    assert got["kind"] == "hard_block"
    assert ("冷却" in joined) or ("别再" in joined), joined
