# -*- coding: utf-8 -*-
"""r805ar：字段健康审计必须覆盖 App 渠道。

`_srx_health` 是「字段健康」面板的数据源：按航线/日期读每个渠道最近 3 条
成功 raw extra，统计各字段的 key 可得率。它原先固定遍历
`Alerter.PLATFORM_CN`——**浏览器五家**。于是 App 渠道的字段覆盖率从不被
审计，界面上看起来是「没有这件事」，而不是「覆盖率为 0」；而这两者对
读者的含义完全不同（前者像不存在，后者是可核查的事实）。

修法不是简单地把 App 加进 `PLATFORM_CN`（那张表同时是「默认渠道全集」，
加了会让没启用 App 的用户每轮被记缺勤），而是：
  · 覆盖面 = `_diag_platforms(该航线/日期在库里真出现过的渠道)`
    —— 默认五家 ∪ 用户启用的 App ∪ 库里真有数据的渠道；
  · 名字用合并表 `PLATFORM_CN ∪ PLATFORM_CN_EXTRA`。

「库里真出现过」要自己查 SQL，不能只靠 `_State.users`：历史上采过、
后来被停用的渠道否则会从审计里消失，等于把已存在的问题藏起来。

判据（对生产库真跑，无数据时 skip）：
  1. 有 App 行的航线/日期，审计结果里必须出现该 App 渠道；
  2. 它的 `rows > 0`，且字段率不是 None（有分母才算得出率）；
  3. 名字是中文，不是裸 id。
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "data", "prices.db")


def _route_with_app():
    if not os.path.isfile(DB):
        return None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"),
                               uri=True)
        try:
            row = conn.execute(
                "SELECT from_city, to_city, depart_date FROM flight_prices "
                "WHERE platform LIKE 'app%' AND extra!='' "
                "GROUP BY 1,2,3 ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        # CI/并行用例可能刚建了一个空/半建库：无表=无样本，按 skip 处理，
        # 不把「没有账本」记成产品红。
        return None
    return row


def test_field_health_audits_app_channels():
    import pytest
    route = _route_with_app()
    if not route:
        pytest.skip("账本里没有 App 渠道的明细行，本判据无样本")
    fc, tc, date = route

    import webui
    # 用城市码直接调用（_probe_city_code 需要完整 cfg；这里绕过解析）
    # ——`_srx_health` 的城市解析在真实请求里已由上游完成。
    from core.citydata import CODE_NAME
    frm = CODE_NAME.get(fc, fc)
    to = CODE_NAME.get(tc, tc)
    out = webui._srx_health(frm, to, date, db=DB)
    chans = {c["key"]: c for c in out.get("channels") or []}
    assert chans, "审计结果为空，判据失去锚点"

    app_rows = [c for c in chans.values() if str(c["key"]).startswith("app")]
    assert app_rows, (
        "该航线/日期明明有 App 渠道数据（%s→%s %s），审计结果里却没有"
        " App 渠道——字段覆盖率从不被检查：%s"
        % (fc, tc, date, list(chans)))
    for c in app_rows:
        assert int(c["rows"]) > 0, (
            "%s 有数据但审计读成 0 行：%s" % (c["key"], c))
        assert not str(c["name"]).startswith("app_"), (
            "%s 的名字是裸 id，应显示中文名：%r" % (c["key"], c["name"]))
        # 有分母才谈得上「覆盖率」
        rates = [v.get("rate") for v in (c.get("fields") or {}).values()
                 if v.get("rate") is not None]
        assert rates, "%s 的字段率全是 None（没有分母）" % c["key"]


def test_browser_channels_still_audited():
    """扩展覆盖面不能把原来的五家挤掉。"""
    import pytest
    route = _route_with_app()
    if not route:
        pytest.skip("账本里没有样本")
    fc, tc, date = route
    import webui
    from core.citydata import CODE_NAME
    out = webui._srx_health(CODE_NAME.get(fc, fc), CODE_NAME.get(tc, tc),
                            date, db=DB)
    keys = {c["key"] for c in out.get("channels") or []}
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert p in keys, "浏览器渠道 %s 从审计里消失了" % p
