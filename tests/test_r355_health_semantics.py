# -*- coding: utf-8 -*-
"""r355 渠道健康语义：日历价成功 / 明细成功 / 登录失效分档。

契约：
- 任意真实出价（国内列表、国际明细、国际日历）都算该日期成功；
- 成功行携带 cal/detail 计数，界面据此区分「日历价」与「航班级明细」；
- 未登录硬拒不是普通抓取失败，need_login=True 且 note 可执行；
- 统计面同步累加 cal/detail/auth，供健康页与外部观测消费。
"""


def _hl(ts, lvl, name, msg):
    return f"{ts} [{lvl}] {name}: {msg}"


def _round(lines):
    return "\n".join([
        _hl("2026-10-21 22:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        *lines,
        _hl("2026-10-21 22:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])


def test_calendar_price_is_available_not_failure():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "INFO", "t",
            "[ctrip][intl] 2026-11-16 日历最低含税价 ￥719（1 行）"),
        _hl("2026-10-21 22:00:20", "INFO", "t",
            "[fliggy][intl] 2026-11-16 日历最低含税价 ￥719（税 569）"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    r = out["rounds"][0]["plats"]
    for p in ("ctrip", "fliggy"):
        assert r[p]["s"] == "ok", r[p]
        assert r[p]["ok"] == 1 and r[p]["tot"] == 1
        assert r[p]["cal"] == 1 and r[p]["detail"] == 0
        assert "日历" in r[p]["note"]
    assert out["stats"]["ctrip"]["cal"] == 1
    assert out["stats"]["ctrip"]["detail"] == 0


def test_detail_success_reports_detail_kind():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "INFO", "t",
            "[tuniu][intl] 2026-11-16 最低含税价 ￥739 "
            "(ZH9516/ZH305)（明细 150 条：直飞 27 / 中转 123）"),
        _hl("2026-10-21 22:00:20", "INFO", "t",
            "[qunar] 2026-11-16 最低价 ￥1526（航班明细 70 条：直飞 44 / 中转 26）"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    r = out["rounds"][0]["plats"]
    for p in ("tuniu", "qunar"):
        assert r[p]["s"] == "ok", r[p]
        assert r[p]["detail"] == 1 and r[p]["cal"] == 0
    assert out["stats"]["tuniu"]["detail"] == 1


def test_login_rejection_is_actionable():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "WARNING", "t",
            "[qunar][intl] 2026-11-16 未登录硬拒（1999/8）"
            "——请在配置页「渠道登录」重登 qunar；本轮放弃不压制"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["qunar"]
    assert p["s"] == "fail"
    assert p["need_login"] is True
    assert "需登录" in p["note"]
    assert out["stats"]["qunar"]["auth"] == 1


def test_invalid_link_444_is_risk_evidence_not_login_rejection():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "WARNING", "t",
            "[tongcheng][intl] 2026-11-16 会话门拒（code=444 非法链接，"
            "body 55B）——请在配置页「渠道登录」重登 tongcheng"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["tongcheng"]
    assert p["s"] == "fail"
    assert p["need_login"] is False
    assert p["note"] and "重登" not in p["note"] and "需登录" not in p["note"]
    assert out["stats"]["tongcheng"]["auth"] == 0


def test_calendar_plus_failure_is_partial_and_counts_calendar():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "INFO", "t",
            "[ctrip][intl] 2026-11-16 日历最低含税价 ￥719（1 行）"),
        _hl("2026-10-21 22:00:20", "WARNING", "t",
            "[ctrip][intl] 2026-11-17 未拿到日历价"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["ctrip"]
    assert p["s"] == "part"
    assert p["ok"] == 1 and p["tot"] == 2
    assert p["cal"] == 1
    assert "未拿到日历价" in p["note"]


def test_calendar_empty_body_note_is_preserved():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "WARNING", "t",
            "[tongcheng][intl] 2026-11-16 未拿到日历价（body 55B）"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["tongcheng"]
    assert p["s"] == "fail"
    assert "未拿到日历价" in p["note"]


def test_demo_health_carries_semantic_counts():
    from core.demo import demo_health
    out = demo_health(hours=2)
    for plat, st in out["stats"].items():
        assert "cal" in st and "detail" in st and "auth" in st, plat
    assert out["stats"]["fliggy"]["cal"] > 0


def test_search_kpi_separates_fallback_from_anomaly():
    src = open("webui.py", encoding="utf-8").read()
    start = src.index("function srxRenderKpis(){")
    end = src.index("function srxRenderChips(){", start)
    block = src[start:end]
    # 补位/异常降为 KPI 次级行，不再各占一张零值主卡。
    assert "补位 " in block and "fallback" in block and "bad" in block
    assert "k('异常'" not in block
    assert "srx-kpi-sub" in block and "本次明细" in block


def test_read_log_tail_keeps_oldest_line_beyond_2mb_tail(tmp_path, monkeypatch):
    """5MiB 轮转文件必须整读：旧的 2MiB 尾读会静默丢掉窗口最早轮次。"""
    import webui
    log = tmp_path / "monitor.log"
    old = "2026-10-22 09:00:00 [INFO] t: ===== 开始一轮扫描 =====\n"
    (tmp_path / "monitor.log.1").write_text(
        old + "x" * 2_300_000 + "\n", encoding="utf-8")
    log.write_text("2026-10-22 10:00:00 [INFO] t: latest\n", encoding="utf-8")
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"log_path": str(log)}})
    text = webui._read_log_tail(max_age_h=48)
    assert old.strip() in text
    assert "latest" in text


def test_read_log_tail_never_glues_rotated_boundary_lines(tmp_path, monkeypatch):
    import webui
    log = tmp_path / "monitor.log"
    (tmp_path / "monitor.log.1").write_text(
        "2026-10-22 09:00:00 [INFO] t: 旧文件末行", encoding="utf-8")
    log.write_text("2026-10-22 10:00:00 [INFO] t: 新文件首行\n",
                   encoding="utf-8")
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"log_path": str(log)}})
    text = webui._read_log_tail(max_age_h=48)
    assert "旧文件末行\n2026-10-22 10:00:00" in text


# 当前认证按钮和国际能力条由 test_channel_ui_status 的真实脚本行为
# 覆盖：历史失败不可生成当前登录动作，明确新拒绝才跨页面显示同一动作。
