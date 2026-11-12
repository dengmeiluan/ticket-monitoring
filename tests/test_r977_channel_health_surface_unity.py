# -*- coding: utf-8 -*-
"""r977：渠道健康三张表（诊断 / 时间线 / 节流）必须同一渠道宇宙。

用户复报「所有渠道能力和展示没有覆盖辐射到全项目每个，例如渠道健康」：
- 诊断卡只取最近一轮 plats，最后一轮没有跑 App 渠道时，8~10 家的健康页
  里诊断卡只剩 5 家浏览器渠道；同屏三张表三个渠道集合。
- 节流面板与溯源是用户点名的重灾区：需要两栏布局、单行证据、可读表格。

本文件只钉「渠道集合同源」与「新结构真的存在」两条，视觉细节由 Playwright
栅格/溢出用例守。
"""
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui.PAGE


def test_diag_platforms_include_channels_seen_in_24h_stats():
    """诊断卡的渠道集合必须并入近 24h stats 出现过的渠道（含 App）。"""
    import webui
    body = inspect.getsource(webui._health_decorate)
    assert 'out.get("stats")' in body, "诊断卡又只看最近一轮 plats，App 渠道会从卡上消失"
    assert "_diag_platforms(_plats)" in body, "诊断卡没有把并集交给 _diag_platforms"
    # 负控：旧实现只写 `_diag_platforms(_plats)` 而 _plats 仅取 rounds[-1]
    assert "for _p, _st in (out.get(\"stats\") or {}).items()" in body, \
        "stats 并集循环不见了"


def test_classify_round_emits_a_card_for_every_registered_app_channel():
    from core.health_diag import classify_round
    plats = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu",
             "app_zhixing", "app_qunar", "app_fliggy", "app_ctrip", "app_tongcheng")
    cards = classify_round({}, all_plats=plats)
    assert [c["plat"] for c in cards] == list(plats)
    assert all(c.get("name") and c.get("label") for c in cards), \
        "有渠道卡缺中文名/状态，界面会露裸 id"


def test_pacing_uses_two_column_body_and_readable_trace_table():
    src = _src()
    assert 'class="pace-body"' in src, "节流面板又回到单列长墙"
    assert "Object.keys(PTH||{}).forEach" in src,         "重启后 App 渠道会从节流行消失；必须合并近 24h 分通路账"
    assert "v._no_round?'待首轮'" in src,         "合并进来的渠道不能冒充「正常」，必须标「待首轮」"
    assert "#paceBox .pace-body{display:grid" in src, "两栏布局规则不见了"
    assert "#paceBox .pace-tline>*{grid-area:auto!important}" in src, \
        "溯源表列又会被 grid-area 命名轨道顶乱"
    assert "#paceBox .pace-tline .u{grid-column:1/-1!important}" in src, \
        "URL 必须独占整行，不能挤进四列"


def test_filter_panel_has_one_collapse_entry_and_a_full_width_more_row():
    src = _src()
    # 面板头/尾不再各放一颗「收起/完成」，唯一收起入口是工具栏那颗
    head = src[src.index("const head='<div class=\"srf-head\""):]
    head = head[:head.index("const foot=")]
    assert 'data-srfclose="1"' not in head, "筛选面板头又出现第二颗收起"
    assert 'data-srfclose="1"' not in src[src.index("const foot='<div class=\"srf-foot\""):][:400], \
        "筛选面板底又出现「完成」第二颗收起"
    # 更多条件触发器独占整行、直接位于展开体之前
    i = src.index('id="srxMoreBtn"')
    j = src.index('id="srxFmore"')
    k = src.index('id="srxPlats"')
    assert k < i < j, "更多条件触发器应独占渠道行之后的一行"


def test_legacy_watch_channels_migrate_once_to_full_universe():
    """浏览器五家出厂默认的旧关注记录必须一次性升到全渠道。"""
    import webui
    full = list(webui._WATCH_PLATS)
    browser = [p for p in full if not str(p).startswith("app_")]
    assert len(full) > len(browser)
    assert webui._watch_channels(browser) == browser, "显式保存的浏览器五家不应被改写"
    assert set(webui._watch_channels(browser, migrate=True)) == set(full),         "旧关注记录没有迁移到 App 渠道，关注台覆盖仍是 /5"
