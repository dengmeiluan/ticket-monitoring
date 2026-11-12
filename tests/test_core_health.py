# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r415_health_scope_dimension.py
- tests/test_r485_health_thresholds_configurable.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import sys

from core.health import _evidence_scope, parse_health


# ---- merged from tests/test_r415_health_scope_dimension.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(fn):
    return open(os.path.join(ROOT, fn), encoding="utf-8").read()


def test_scope_from_explicit_tag():
    assert _evidence_scope("抓取完成，得到 23 条记录 · 国内") == "domestic"
    assert _evidence_scope("抓取完成，得到 1 条记录 · 国际") == "international"


def test_scope_from_nested_channel_tag():
    """`[tongcheng][intl]` 这类嵌套前缀此前认不出（只 match 行首）。"""
    assert _evidence_scope("[tongcheng][intl] 窗历命中 1/1 日") == "international"
    assert _evidence_scope("[qunar][intl] 1999 连续 2 次") == "international"


def test_scope_from_route_codes():
    """旧日志没有域标记时，用航线三字码兜底判域。"""
    assert _evidence_scope("开始抓取 SHA->HAK 日期=['2027-01-29']") == "domestic"
    assert _evidence_scope("开始抓取 SHA->LHR 日期=['2026-11-16']") == "international"


def test_scope_unknown_when_no_evidence():
    """没有任何域证据时保持 unknown，绝不默认成国内。"""
    assert _evidence_scope("抓取完成，得到 3 条记录") == "unknown"


def test_fetch_logs_carry_scope_tag():
    """采集端必须把域写进日志——日志是健康解析的唯一数据源。"""
    src = _src("crawlers/base.py")
    i = src.index("抓取完成，得到")
    block = src[max(0, i - 900):i + 200]
    assert "is_intl_route" in block, block[-400:]
    assert "· " in block


def test_mixed_round_not_dropped():
    """一轮里国内国际都跑过时，两侧都要有样本（曾整轮被丢弃）。"""
    src = _src("core/health.py")
    i = src.index("by_scope")
    block = src[i:i + 2200]
    assert "mixed" in block
    assert "domestic" in block and "international" in block


def test_parse_health_exposes_by_scope():
    """真实日志解析结果必须带 by_scope，且按厂商×域分组。"""
    logp = os.path.join(ROOT, "logs", "monitor.log")
    if not os.path.isfile(logp):
        return
    h = parse_health(open(logp, encoding="utf-8", errors="replace").read())
    assert "by_scope" in h
    bs = h["by_scope"]
    if not bs:
        return
    for plat, scopes in bs.items():
        assert set(scopes) <= {"domestic", "international"}, (plat, scopes)
        for sc, node in scopes.items():
            att = node["ok"] + node["part"] + node["fail"]
            assert 0.0 <= node["rate"] <= 1.0, (plat, sc, node)
            assert att >= 0


def test_ui_renders_scope_badge():
    """界面在两端都有样本时要显示「国内 X% · 国际 Y%」。"""
    src = webui_full_src()
    assert "hscope" in src
    assert "by_scope" in src
    assert "'国内 '" in src or "国内 " in src


# ── r416：通路维度（PC/H5/日历/窗历）也必须露出 ──────────────────────

def test_health_payload_carries_paths():
    """健康载荷要带分通路成功率与退役标记，否则面板只有一个厂商数。"""
    src = webui_full_src()
    i = src.index("def _health_decorate")
    # 取到函数结束，不用固定字符窗口：插一段别的维度就会把 path_stats
    # 挤出窗口，变成假红（r430 加会话维度时踩过）。
    j = src.index("\ndef ", i + 10)
    block = src[i:j]
    assert "path_stats" in block
    assert "retired_paths" in block or "retired" in block


def test_ui_renders_path_badge():
    """界面要把通路成功率与「退役」标出来。"""
    src = webui_full_src()
    assert "hpath" in src
    assert "退役" in src


# ---- merged from tests/test_r485_health_thresholds_configurable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pacing():
    from core.pacing import Pacing, parse_pacing
    return Pacing, parse_pacing


def _pen(cfg, plat="ctrip"):
    Pacing, _ = _pacing()
    p = Pacing(cfg)
    return p


def test_defaults_unchanged_from_previous_hardcoded_values():
    _, parse_pacing = _pacing()
    c = parse_pacing({})
    assert c["health_min_samples"] == 5
    assert c["health_ok_ratio"] == 0.7
    assert c["health_slow_ratio"] == 0.4
    assert c["health_slow_factor"] == 1.5
    assert c["health_slowest_factor"] == 3.0


def _penalty(cfg, rate, attempts):
    """cfg 是 crawler 段的键（与 health_penalty_enabled 同一层）。"""
    Pacing, _ = _pacing()
    p = Pacing({"crawler": dict(cfg or {})} if cfg else {})
    p.set_health("ctrip", rate, attempts)
    return p.snapshot()["channels"]["ctrip"]["health"]["penalty"]


def test_custom_thresholds_change_the_verdict():
    # 默认：0.65 → 轻降频（0.4 ≤ r < 0.7）
    assert _penalty({}, 0.65, 20) == 1.5
    # 把合格线降到 0.6 → 同一成功率不再降频
    assert _penalty({"health_ok_ratio": 0.6}, 0.65, 20) == 1.0
    # 把合格线抬到 0.8 且慢档线 0.75 → 同一个 0.65 变成重降频
    assert _penalty({"health_ok_ratio": 0.8,
                     "health_slow_ratio": 0.75}, 0.65, 20) == 3.0


def test_custom_factors_and_min_samples():
    assert _penalty({"health_slow_factor": 2.0}, 0.5, 20) == 2.0
    assert _penalty({"health_slowest_factor": 6.0}, 0.1, 20) == 6.0
    # 样本下限抬到 30 → 20 个样本不判
    assert _penalty({"health_min_samples": 30}, 0.1, 20) == 1.0


def test_ordering_invariants_are_clamped():
    from core.pacing import parse_pacing
    # 慢档线高于合格线 → 钳到合格线
    c = parse_pacing({"crawler": {"health_ok_ratio": 0.5,
                                  "health_slow_ratio": 0.9}})
    assert c["health_slow_ratio"] <= c["health_ok_ratio"], c
    # 最慢倍数低于慢档倍数 → 钳上去
    c2 = parse_pacing({"crawler": {"health_slow_factor": 3.0,
                                   "health_slowest_factor": 1.2}})
    assert c2["health_slowest_factor"] >= c2["health_slow_factor"], c2


def test_values_reach_the_config_page_and_the_panel():
    w = webui_full_src()
    for key, cid in (("health_ok_ratio", "glbHok"),
                     ("health_slow_ratio", "glbHslow"),
                     ("health_slow_factor", "glbHsf"),
                     ("health_slowest_factor", "glbHslf"),
                     ("health_min_samples", "glbHms")):
        assert ("GLB.%s=" % key) in w, "配置页缺 %s 的输入绑定" % key
        assert cid in w, "缺控件 %s" % cid
        assert '_crw["%s"]' % key in w or '_crw[_hk]' in w, \
            "%s 未写回配置" % key
    # 面板文案不能再写死 70/40/5
    assert "低于 70% 会自动拉长该渠道 TTL（低于 40% 拉 3 倍），样本不足 5 次不判" not in w, \
        "节流面板阈值文案仍写死"
    assert "_hint" in w, "面板未使用动态阈值文案"


def test_panel_wording_follows_config_not_hardcoded():
    """面板降频说明必须跟着配置走。

    实测：把合格线改成 0.85 后，界面仍写「低于 70%」——用户看不出
    自己的设置到底生效没有。渲染实测输出：
    「低于 85% 会自动拉长该渠道 TTL（低于 60% 拉 4 倍，60%~85% 拉 2 倍），
      样本不足 12 次不判」。
    """
    w = webui_full_src()
    i = w.index("const _hok=Math.round((cf.health_ok_ratio")
    seg = w[i:w.index("const _pen=Object.keys(ch)", i)]
    for tok in ("_hok", "_hsl", "_hsf", "_hms"):
        assert tok in seg, "面板阈值文案未使用配置值 %s" % tok
    assert "cf.health_ok_ratio" in seg and "cf.health_min_samples" in seg


def test_config_fields_are_actually_rendered_and_visible():
    """五个阈值必须真的渲染成可编辑输入（不只是字符串存在）。"""
    import re as _re
    w = webui_full_src()
    for cid in ("glbHok", "glbHslow", "glbHsf", "glbHslf", "glbHms"):
        # glcell 生成输入框，id 作为第二参数
        assert _re.search(r"glcell\('[^']*','%s'" % cid, w), \
            "%s 未通过 glcell 渲染" % cid


def test_config_round_trip_write_save_reload():
    """改阈值 → 保存 → 重新读取，值必须原样回来。

    只写不回读是配置页最隐蔽的缺陷（r487 实测存在）：`/api/config` 的
    globals 只回读了 health_penalty_enabled，五个新阈值根本没发出去，
    配置页渲染的是默认值——用户改完再打开看到 0.7/0.4/5，随手再保存
    就把自己设的值覆盖回默认。
    """
    from core.pacing import parse_pacing
    keys = {"health_min_samples": 12, "health_ok_ratio": 0.85,
            "health_slow_ratio": 0.6, "health_slow_factor": 2,
            "health_slowest_factor": 4}
    # 段解析必须承认写进去的值
    got = {k: parse_pacing({"crawler": dict(keys)})[k] for k in keys}
    assert got == keys, got
    # /api/config 的 globals 必须把这五个键发回前端
    w = webui_full_src()
    i = w.index('"health_penalty_enabled": bool(')
    seg = w[i:i + 1800]
    for k in keys:
        assert '"%s"' % k in seg, "/api/config 未回读 %s（配置页会显示默认值）" % k


def test_every_config_page_key_is_read_back():
    """全量往返守卫：配置页绑定的每个 GLB 键都必须被 /api/config 回读。

    r487 只手工补了 5 个阈值；这条把它推广成规则——以后任何人新增一个
    `glcell(..., 'GLB.xxx=...')` 却忘记回读，这里会立刻报出来。
    只测写入侧的契约抓不到这类缺陷（写进去了，但重新打开显示默认值，
    用户再保存一次就把自己的设置覆盖回默认）。
    """
    import re as _re
    w = webui_full_src()
    keys = sorted(set(_re.findall(
        r"glcell\('[^']*','[^']*','GLB\.([a-z_]+)=", w)))
    assert len(keys) >= 30, "配置页键数量异常（%d），解析可能失效" % len(keys)
    # /api/config 的 globals 构造块：以最后一个 `"globals": {` 起点、配对的 `}` 为终点
    # （第 311 行还有一处 demo_cfg 的同名键，那里的 5 个键不是配置页的回读面）。
    # 原先用「health_penalty_enabled 前后固定 9000/6000 字符」取窗口——
    # 页面一长（r521 加了只读参数块）窗口就够不到块尾，`auto_verify` 被误判成
    # 「没有回读」。字符数窗口会随无关改动漂移，结构边界不会。
    i = w.rindex('"globals": {')
    depth = 0
    for j in range(i, len(w)):
        if w[j] == "{":
            depth += 1
        elif w[j] == "}":
            depth -= 1
            if depth == 0:
                break
    seg = w[i:j + 1]
    # 必须精确匹配 `"key":`（后面紧跟冒号）。只匹配 `"key"` 会被
    # `"key_INTERNAL"` 这类前缀骗过——负控实测：改名后守卫照样全绿。
    missing = [k for k in keys
               if ('"%s":' % k) not in seg]
    assert not missing, "以下配置项未回读，配置页会显示默认值：%s" % missing
