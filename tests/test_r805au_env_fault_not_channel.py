# -*- coding: utf-8 -*-
"""r805au：本机环境故障不能记成「渠道抓取失败」。

真账本实证（2026-11-01，fliggy H5）：
    note = `Page.goto: net::ERR_PROXY_CONNECTION_FAILED at
            https://market.m.taobao.com/...`
健康卡却归成「抓取失败（原因待核对）」，动作写「打开原站核实
IP/风控/登录」——**把我们自己的代理故障指成渠道风控**。用户会去换网络、
重登、甚至换渠道，而问题在本机。这类归因错误比缺数据更糟：它主动误导。

修法：`classify_round` 在兜底前加一条**环境故障**分支（proxy / DNS /
连接被拒 / 浏览器进程被关），标签与动作都写明「不是该渠道的问题」。

判据：
  1. 真实那条 note 必须归成 `env`，标签含「本机」，动作含「不是该渠道」；
  2. 真正的限流/风控措辞**不许**被这条吞掉（保持原来的分类）；
  3. CSS 必须给 `.hdiag-card.env .hdiag-st` 配色——新 kind 没有样式时
     状态胶囊会变透明，卡片看起来像坏了。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _one(note, s="error"):
    from core.health_diag import classify_round
    cards = classify_round({"fliggy": {"s": s, "ok": 0, "tot": 0,
                                       "note": note, "detail": 0, "cal": 0}},
                           all_plats=("fliggy",))
    assert cards, "分类器没产出卡片"
    return cards[0]


def test_proxy_failure_is_environment_not_channel():
    note = ("Page.goto: net::ERR_PROXY_CONNECTION_FAILED at "
            "https://market.m.taobao.com/app/trip/rx-traffic-search/pages/index")
    c = _one(note)
    assert c["kind"] == "env", (
        "代理故障被归成 %r —— 会把本机问题指成渠道问题：%s"
        % (c["kind"], c))
    assert "本机" in c["label"], "标签里要写明是本机问题：%r" % c["label"]
    assert "不是该渠道" in c["action"], (
        "动作要明确「不是该渠道的问题」，否则用户会去换渠道/重登：%r"
        % c["action"])


def test_other_environment_faults_also_env():
    for note in ("net::ERR_NAME_NOT_RESOLVED",
                 "net::ERR_INTERNET_DISCONNECTED",
                 "TargetClosedError: Target page, context or browser "
                 "has been closed"):
        c = _one(note)
        assert c["kind"] == "env", "%r 没被判成环境故障：%s" % (note, c)


def test_rate_limit_and_risk_wall_are_not_swallowed():
    """反例：真正的限流/风控不能被「环境故障」这条吃掉。"""
    for note in ("H5 限流（mtop RGV587，冷却后自愈）",
                 "命中风控", "403 限流"):
        c = _one(note)
        assert c["kind"] != "env", (
            "把限流/风控误判成本机故障会让人不去等冷却：%r -> %s"
            % (note, c["kind"]))


def test_env_card_has_status_chip_style():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert ".hdiag-card.env .hdiag-st" in src, (
        "新 kind 没有状态胶囊配色，卡片会看起来像坏了（胶囊透明）")
