# -*- coding: utf-8 -*-
"""r793：能力矩阵必须有「端面（PC/H5）」一轴。

用户原话：「主要原⑤渠道的 pc 和 h5 都要重点检查」。
但矩阵只有维度一轴——**每家每维全绿**，看不出「这家只有 H5 能真出数」。
2026-11-01 账本普查（`fetch_paths` 按端面聚合）的事实是：

    ctrip   PC 27 次出数 3639 行 / H5 20 次出数 765 行（两端都行）
    qunar   H5 46 次出数 3217 行 / **PC 无任何记录**（2026-10-10 起停服）
    fliggy  PC 37 次出数 3153 行 / **H5 仅 1 次且 error（0 行）**
    tongcheng H5 13 次出数 447 行 / **PC 无记录**
    tuniu   H5/API 32 次出数 2985 行 / **PC 无出数记录**

这些差异以前只存在于代码注释与账本里，界面上一格都看不见。

判据：
  1. `CHANNEL_SURFACES` 必须覆盖全部浏览器渠道，且只含 pc/h5 两端；
  2. 取值只能是 y/n/""（与维度同一套三态语义）；
  3. `/api/channel-dims` 必须把 `surface_cells` 下发（否则界面无从渲染）；
  4. 声明 n 的端面，源码里必须有对应的停服/未实现证据或账本从未出数——
     这里用最小可验证版本：n 的渠道在该端的 `entry_path` 账本里，
     **不允许出现过 rows>0 的记录**（真出过数就不能说 n）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from core.channels import (BROWSER_CHANNELS, CHANNEL_SURFACES, SURFACES,
                           surface_state)
from ledger_fixture import groups as _ledger_groups

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _surface_of(path):
    p = str(path or "")
    if p.startswith("PC"):
        return "pc"
    if "H5" in p or "API" in p:
        return "h5"
    return ""


def _ok_runs_by_surface(recent=False):
    """{(platform, surface): ok 轮次}；只数真正出过数的 ok/calendar。"""
    agg = {}
    for plat, path, st, runs, rows in _ledger_groups(recent=recent):
        surf = _surface_of(path)
        if not surf:
            continue
        d = agg.setdefault((plat, surf), {"ok": 0, "rows": 0})
        if st in ("ok", "calendar") and (rows or 0) > 0:
            d["ok"] += runs or 0
            d["rows"] += rows or 0
    return agg


def _has_positive_rows(platform, surface):
    for plat, path, _st, _runs, rows in _ledger_groups():
        if plat == platform and _surface_of(path) == surface and (rows or 0) > 0:
            return True
    return False


def test_every_browser_channel_declares_both_surfaces():
    for p in BROWSER_CHANNELS:
        row = CHANNEL_SURFACES.get(p)
        assert row is not None, "%s 没有端面声明" % p
        assert set(row) == set(SURFACES), (p, row)


def test_surface_values_are_only_three_states():
    for p, row in CHANNEL_SURFACES.items():
        for s, v in row.items():
            assert v in ("y", "n", ""), (p, s, v)


def test_surface_state_accessor():
    assert surface_state("ctrip", "pc") == "y"
    assert surface_state("qunar", "pc") == "n"
    assert surface_state("nonexistent", "pc") == ""


def _channels_src():
    return io.open(os.path.join(ROOT, "core", "channels.py"),
                   encoding="utf-8").read()


def _webui_src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_api_exposes_surface_cells():
    src = _channels_src()
    assert "surface_cells" in src, (
        "channel_dims_payload 没下发端面声明，界面无从渲染")
    assert "surface_state(p, s)" in src, (
        "载荷没走 surface_state 取值，端面事实源不唯一")
    assert "channel_dims_payload()" in _webui_src(), (
        "接口没走单一矩阵载荷（channel_dims_payload）")


def test_every_surface_cell_has_a_human_note():
    """每个端面格子都要有说明：n 与 "" 在格子里都不是 y，
    但「根本没做」和「做了被风控挡住」对用户的行动建议完全不同。
    没有说明时，读者会把一次验证拦截读成产品缺失。
    """
    from core.channels import SURFACE_NOTES
    for p in BROWSER_CHANNELS:
        for s in SURFACES:
            note = SURFACE_NOTES.get((p, s), "")
            assert note.strip(), "%s.%s 没有说明文案" % (p, s)
            # 说明里不许出现版本号/轮次号之类会腐烂的锚
            assert "r7" not in note and "r8" not in note and "r9" not in note, (
                "%s.%s 说明里写了轮次号，会随时间腐烂" % (p, s))


def test_api_passes_surface_notes_through():
    src = _channels_src()
    assert "surface_notes" in src, "载荷没有下发端面说明"
    assert "SURFACE_NOTES" in src, "说明没引用单一事实源"


def test_app_channels_never_get_surface_cells():
    """App 渠道不能下发 surface_cells —— 否则那两格画成「?」未验证。

    前端判据是 `hasOwnProperty(surface_cells, s)`：只要键在就走 dimCell，
    "" 会渲染成「? 未验证」。实测（r796，隔离 DOM 里喂两种载荷）：
      旧载荷（App 也给 {'pc':'','h5':''}）→ PC/H5 行上「—」0 个，全是 ?
      新载荷（App 不给这个键）        → 「—」各 2 个，title=「App 渠道无端面之分」
    「智行的 PC 端没验证过」和「智行没有端面概念」是完全不同的两句话。
    """
    from core.channels import APP_CHANNELS, CHANNEL_SURFACES
    for p in APP_CHANNELS:
        assert p not in CHANNEL_SURFACES, (
            "%s 是 App 渠道，不该有端面声明" % p)
    src = _channels_src()
    # 走访问器而不是直接读字典：has_surface 才是「有没有端面」的单一入口
    assert "has_surface(p)" in src
    assert "surface_state(p, s)" in src, "取值没走 surface_state"
    assert "if not has_surface(p):" in src, (
        "没有对「无端面声明」做分流，App 会被渲成 ? 未验证")
    assert "CHANNEL_SURFACES.get(p)" not in src, (
        "载荷又直接读字典了，绕过了 has_surface 单一入口")


def test_has_surface_separates_no_surface_from_unknown():
    """`has_surface` 与 `surface_state` 必须回答两个不同的问题。

    surface_state 对「没有端面」和「端面未验证」都返回 ""，
    单看值分不出二者；界面画 "—" 还是 "?" 取决于 has_surface。
    """
    from core.channels import (APP_CHANNELS, BROWSER_CHANNELS, has_surface,
                               surface_state)
    for p in BROWSER_CHANNELS:
        assert has_surface(p) is True, p
    for p in APP_CHANNELS:
        assert has_surface(p) is False, p
    # 同为空串，含义不同
    assert surface_state("fliggy", "h5") == ""      # 有端面，只是未验证
    assert has_surface("fliggy") is True
    assert surface_state("app_zhixing", "h5") == ""  # 没有端面
    assert has_surface("app_zhixing") is False


def test_login_card_buttons_share_one_column():
    """七张登录卡的「弹窗登录」必须同列同高，不随状态文案长短漂移。

    用户原话：「登录按钮看起来会飘，当状态不一致的时候，会显示不是同一行！」
    2026-11-01 实测（1440/1024/540/390 四档 × 默认与超长状态文案）：
    btn_x 各档分别恒为 1219/865/394、宽度恒 96、卡内 dy 恒 9~10、
    卡高各档恒 52/71、`.lgsub` 溢出 0 —— 三列布局 + 定宽按钮把关。
    这条钉住的是「三列结构」与「按钮定宽」，不是某个像素值。
    """
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    # 按钮必须是卡片的直接子级（第三列），否则列会塌、按钮被文案挤下去
    assert '`<div class="lgact">' in src, "lgact 结构变了，重核三列布局"
    # 状态文案在 .lgsub，必须与操作列分离
    assert 'class="lgsub"' in src
    # 卡片是三列网格（名字 | 说明+槽位 | 操作）
    assert ".lgcard{" in src
    import re
    m = re.search(r"\.lgcard\{([^}]*)\}", src)
    assert m, "找不到 .lgcard 规则"
    body = m.group(1)
    # 只认 display 的**取值**：`flex-direction:` 里也含 "flex" 字样，
    # 用 `"flex" in body` 会在 display:block 时仍判真（负控打不中，
    # 2026-11-01 实测踩过）。必须按属性精确匹配。
    disp = re.search(r"display\s*:\s*([a-z-]+)", body)
    assert disp, ".lgcard 没有 display 声明：%s" % body
    assert disp.group(1) in ("flex", "grid"), (
        ".lgcard 的 display 是 %r（需要 flex/grid 三列），按钮会被文案挤到第二行"
        % disp.group(1))


def test_tongcheng_pc_declaration_matches_implementation():
    """同程国内 PC 的声明必须与**代码事实 + 账本事实**同时一致。

    r805（2026-10-31）：新增 `_fetch_pc_dom` 开
    `www.ly.com/flights/itinerary/oneway/…` 收站点自己发的
    `getflightlist`；真浏览器跑通 64 条 / 最低 ¥493 / path 落 `PC`
    / `mobile:false`。

    **生产账本已有同程 PC 出数**（2026-11-01 17:45，SHA→HAK，5 行/¥2110），
    所以声明是 y。CI 会在测试过程中生成临时 `data/prices.db`（没有生产
    证据）；本测试在生产证据缺失时跳过，不拿临时库改判声明。

    判据守两个方向：
      * 代码在 → 不许记 n（那是「没实现」，与事实不符）；
      * 生产账本有 PC 出数 → 必须是 y（否则漏报能力）。
    """
    from core.channels import CHANNEL_SURFACES
    src = io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                  encoding="utf-8").read()
    import re as _re
    has_def = _re.search(r"^\s*def _fetch_pc_dom\(", src, _re.M) is not None
    has_call = _re.search(r"self\._fetch_pc_dom\(", src) is not None
    has_impl = (has_def and has_call and "getflightlist" in src
                and "URL_TPL_PC" in src)
    assert has_impl, (
        "同程 PC 实现不见了（_fetch_pc_dom / getflightlist / URL_TPL_PC）")
    declared = CHANNEL_SURFACES["tongcheng"]["pc"]
    assert declared != "n", "代码在却记 n：等于告诉用户这个端没有"
    assert _has_positive_rows("tongcheng", "pc"), (
        "账本证据（含快照）里查不到同程 PC 出数，声明 y 失去依据")
    assert declared == "y", (
        "账本已有同程 PC 出数，声明应保持 y（当前 %r）" % declared)
    # 记账点必须在，否则账本永远等不到那一条
    assert any('"PC"' in ln for ln in src.splitlines()), (
        "PC 通路没有记账点：出了数也不会进账本")
    # 途牛判据不变（有实现但被风控挡住 = 测不出）
    assert CHANNEL_SURFACES["tuniu"]["pc"] == "", (
        "途牛 PC 有实现、只是被风控挡住 —— 那是测不出，不是不支持")


def test_tuniu_pc_is_implemented_so_must_not_be_n():
    """途牛 PC 有实现（只是被滑块拦住）→ 必须记 ""（测不出），不能记 n。

    记 n 等于告诉用户「这个端没有」，而事实是「有，但要先去验证」。
    """
    from core.channels import CHANNEL_SURFACES
    assert CHANNEL_SURFACES["tuniu"]["pc"] == "", (
        "途牛 PC 有 _fetch_pc_dom 实现，被风控挡住属测不出，不是不支持")
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    assert "def _fetch_pc_dom" in src, "前提变了：途牛 PC 实现没了，重核本钉"


def test_declared_n_surface_never_produced_rows():
    """声明 n 的端面，账本里不许有出数记录——出过数就不能说 n。"""
    agg = _ok_runs_by_surface(recent=False)
    bad = []
    for p, row in CHANNEL_SURFACES.items():
        for s, v in row.items():
            if v != "n":
                continue
            n = (agg.get((p, s)) or {}).get("ok", 0)
            if n:
                bad.append((p, s, n))
    assert not bad, (
        "这些端面声明 n，但账本里有出数记录（声明与事实矛盾）：%s" % bad)


def test_declared_y_surface_has_ledger_evidence():
    """反向：声明 y 的端面，账本里必须真出过数（不允许凭感觉写 y）。"""
    agg = _ok_runs_by_surface(recent=False)
    bad = []
    for p, row in CHANNEL_SURFACES.items():
        for s, v in row.items():
            if v != "y":
                continue
            n = (agg.get((p, s)) or {}).get("ok", 0)
            if not n:
                bad.append((p, s))
    assert not bad, (
        "这些端面声明 y，但账本里查不到出数记录（应为 \"\" 未验证）：%s"
        % bad)


def test_blocked_surface_is_explained_in_note():
    """账本里被风控（blocked）拦住的端面，悬停必须写明「需人工验证」。

    2026-11-01 20:42/20:46 途牛 PC 生产跑了两次、都被滑块拦住（账本 blocked）。
    声明仍记 ""（测不出，不是不支持），但读者看到"?"必须能知道**下一步做什么**——
    悬停里只写「未验证」等于让人以为"再试试可能行"。
    """
    from core.channels import SURFACE_NOTES
    blocked = []
    for plat, path, st, _runs, rows in _ledger_groups():
        if st == "blocked" and (rows or 0) == 0 and _surface_of(path) == "pc":
            blocked.append(plat)
    for plat in sorted(set(blocked)):
        note = SURFACE_NOTES.get((plat, "pc")) or ""
        assert note, "%s PC 有 blocked 记录，却没有悬停说明" % plat
        assert ("验证" in note or "滑块" in note), (
            "%s PC 被风控拦住，说明必须点出「需人工验证」：%r"
            % (plat, note))


def test_channel_filter_resolves_app_ids_not_just_names():
    """检索页渠道筛选必须认 App 渠道 id，不能只认浏览器渠道中文名。

    `srxPlatKey` 先用 `SRX_PLATS` 查 id（App 走这条），再退回中文名。
    **2026-11-01 修正**：原来的兜底是一张只列 5 家浏览器渠道的写死表，
    App 行的 `f.plat` 是中文名（「智行 App」）→ 返回 `''` → 图标丢失。
    现在兜底也由 `SRX_PLATS` 派生（`SRX_PLATS[k][0]===t`），全仓只剩
    一份名字表。本判据守两件事：① id 优先；② 不再有第二份名字表。
    """
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index("function srxPlatKey(")
    body = src[i:src.index("\n}", i)]
    # 先按 id 命中
    assert "if(SRX_PLATS[t])return t;" in body, (
        "srxPlatKey 不再优先按 id 命中，App 渠道会被中文表漏掉")
    # 兜底必须同样来自 SRX_PLATS（单一来源），而不是另写一张 5 家表
    assert "SRX_PLATS[k][0]===t" in body or "SRX_PLATS[k][0]=== t" in body, (
        "中文名兜底没有从 SRX_PLATS 派生——又出现第二份名字表，"
        "App 渠道会再次映射成空 key")
    assert "const m={'去哪儿'" not in body, (
        "srxPlatKey 里仍有只列 5 家的写死中文名表")
    # SRX_PLATS 必须含两个 App（否则两道判定都认不出）
    from core.channels import APP_CHANNELS
    seg = src[src.index("const SRX_PLATS={"):src.index("const SRX_PLAT_ORDER")]
    for p in APP_CHANNELS:
        assert p in seg, "SRX_PLATS 缺 App 渠道 %s，筛选 chip 与行归属都会错" % p
    # SRX_PLATS 必须含两个 App（否则第一道判定也认不出）
    from core.channels import APP_CHANNELS
    seg = src[src.index("const SRX_PLATS={"):src.index("const SRX_PLAT_ORDER")]
    for p in APP_CHANNELS:
        assert p in seg, "SRX_PLATS 缺 App 渠道 %s，筛选 chip 与行归属都会错" % p


def test_capability_matrix_header_carries_official_icon():
    """能力矩阵表头必须带官方图标，与其余表面一致。

    用户要求「保持使用官方渠道图标作为精致质感的标准，继续扫盲统一」。
    2026-11-01 r801 实测（遍历 4 视图找「含渠道中文名但祖先链无图标」的
    可见叶子）只在下表头命中 8 处——检索页/健康卡/关注卡/登录卡全都带图，
    只有这张矩阵表是裸 `<b>名字</b>`。补图标后四处归零。
    """
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index("function renderDimMatrix(")
    seg = src[i:src.index("async function loadChannelDims(")]
    # 表头必须走 srxPlatIcon 这个全站单源
    j = seg.index("const head=")
    head = seg[j:seg.index("const surfs=", j)]
    assert "srxPlatIcon(c.plat)" in head, (
        "能力矩阵表头没有官方图标（其余表面都有，这里会显得掉档）")
    # 图标与名字必须相邻，中间不能插别的结构
    assert head.index("srxPlatIcon(c.plat)") < head.index("'<b>'+he(c.name)"), (
        "图标出现在名字之后，视觉顺序不对")


def test_surface_declaration_matches_30d_ledger():
    """端面声明必须与**近 30 天账本事实**一致——r802 的核对口径，
    2026-11-03 由 48h 放宽为 30 天：H5/PC 不是每天都被定时任务走到，
    48h 会把「近期没跑」误判成「没验证」（同程 H5 有 35 次 ok/1224 行，
    最近 11-01，仍被降级）。30 天覆盖一个正常调度周期，悬停里另写
    最近成功时间与当前主路。

      y  → 30 天内该端必须真出过数（否则是未验证，写成 y 就是吹）
      n  → 30 天内该端必须没有出数记录（出过数就不能说「没有通路」）
      "" → 允许无记录（测不出）

    整理口径：`recent=True` 只统计抓取时近 30 天的组（本机生产库实时算，
    干净克隆回放 2026-11-04 快照）。y/n 的 30 天窗口语义不变。
    """
    agg = _ok_runs_by_surface(recent=True)
    bad = []
    for plat, row in CHANNEL_SURFACES.items():
        for s, v in row.items():
            n = (agg.get((plat, s)) or {}).get("ok", 0)
            if v == "y" and n == 0:
                bad.append("%s.%s 声明 y 但 30 天内 0 次出数" % (plat, s))
            if v == "n" and n > 0:
                bad.append("%s.%s 声明 n 但 30 天内出过 %d 次" % (plat, s, n))
    assert not bad, "端面声明与账本矛盾：%s" % bad


def test_snapshot_alone_supports_every_declaration():
    """不读本机库、只回放快照，也必须满足同一套声明。

    干净克隆走的就是这条路径；若快照过期/造错，上面几条会在 CI 里
    变成无源之水。这里直接禁用本机库，重跑 y/n/blocked/30 天四组判据。
    """
    import ledger_fixture as lf
    saved = lf.DB
    lf.DB = os.path.join(ROOT, "no-such-ledger.db")
    try:
        all_time = _ok_runs_by_surface(recent=False)
        recent = _ok_runs_by_surface(recent=True)
        for plat, row in CHANNEL_SURFACES.items():
            for s, v in row.items():
                if v == "y":
                    assert (all_time.get((plat, s)) or {}).get("ok", 0), (
                        "快照里 %s.%s 没有出数，y 无据" % (plat, s))
                    assert (recent.get((plat, s)) or {}).get("ok", 0), (
                        "快照里 %s.%s 近 30 天无出数，y 无据" % (plat, s))
                elif v == "n":
                    assert not (all_time.get((plat, s)) or {}).get("ok", 0), (
                        "快照里 %s.%s 出过数，不能记 n" % (plat, s))
        blocked = {(p, _surface_of(path)) for p, path, st, _r, rows
                   in _ledger_groups() if st == "blocked" and not rows}
        assert ("tuniu", "pc") in blocked, (
            "快照丢了途牛 PC blocked 证据，悬停说明的门禁失去靶子")
    finally:
        lf.DB = saved


def test_login_modal_opens_fast_and_switch_rewrites_title():
    """登录弹窗必须瞬间打开；App↔App 切换必须改写**标题句**。

    用户原话：「弹窗好像有点问题，弹得比较慢」「内嵌画面切换 app 的时候
    没有正确切换」。2026-11-01 r803 实测（demo，点击→`.open` 轮询）：
      浏览器 ctrip 弹窗  7~8ms
      App 智行 appLoginOpen 6~7ms
      App 智行 → App 去哪儿 4ms，标题句变成「去哪儿 App 登录 …」

    **判据陷阱**（踩过）：正文里有一个「切换渠道」控件同时列着两个 App
    名，用「正文含 B 且不含 A」永远不成立，会把成功切换读成失败。
    只能看正文开头的标题句。
    """
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    # App 弹窗与浏览器弹窗必须是两条路径（App 没有可弹的浏览器窗）
    assert "function appLoginOpen(" in src, "App 登录入口没了"
    i = src.index("function appLoginOpen(")
    body = src[i:src.index("\nfunction ", i + 10)]
    # App 路径必须**自己**标归属：`data-kind` 在别处也出现（lgRefreshFliggy
    # 等），用「全文含 data-kind」判定恒真，负控打不中（实测踩过）。
    # 只认 appLoginOpen 函数体内的那一处赋值。
    assert "m.dataset.kind='app'" in body, (
        "appLoginOpen 没标 data-kind='app'，浏览器弹窗会覆盖 App 画面"
        "（共用 #lgModal）")
    # 打开动作里不能有 await/网络请求：本地 DOM 展开才是「瞬间」
    assert "await" not in body.split("}")[0][:400], (
        "appLoginOpen 里出现 await，弹窗会被网络往返拖慢")


def test_radar_capability_matches_low_fare_dimension():
    """特价雷达渠道能力必须与维度表 `low_fare` 同口径。

    用户原话：「特价雷达可能是个很典型特殊的，每个渠道可能特价雷达的
    能力都不同，但是我们提供的是统一监控」。同一件事现在有两张表：
      core/channels.py  CHANNEL_DIMENSIONS[p]['low_fare']  → 维度矩阵那一格
      core/specials.py  SPECIAL_CAPABILITY[p]['sources']   → 雷达实际发现源
    两张表互相矛盾时，矩阵说「支持」而雷达没源（或反之），读者必被误导。
    2026-11-01 r804 交叉核对：7/7 一致，矛盾项 0。
    """
    from core.channels import CHANNEL_DIMENSIONS
    from core.specials import SPECIAL_CAPABILITY
    bad = []
    for p, dims in CHANNEL_DIMENSIONS.items():
        lf = (dims or {}).get("low_fare", "")
        cap = SPECIAL_CAPABILITY.get(p)
        srcs = (cap or {}).get("sources")
        if cap is None:
            bad.append("%s 有维度声明但雷达表里没有它" % p)
        elif lf == "y" and not srcs:
            bad.append("%s low_fare=y 但雷达没有发现源" % p)
        elif lf != "y" and srcs:
            bad.append("%s low_fare=%r 但雷达有源 %s" % (p, lf, srcs))
    assert not bad, "雷达能力与维度声明打架：%s" % bad
    # 每家都得写清楚「这个源是什么口径」，不能只给个 id
    for p, cap in SPECIAL_CAPABILITY.items():
        assert (cap.get("note") or "").strip(), (
            "%s 的雷达能力没写说明（读者不知道这个源是什么口径）" % p)


def test_radar_sources_row_also_lists_capabilities():
    """特价雷达的「来源」行只列本次有数据的渠道，必须另有能力清单。

    用户原话：「特价雷达可能是个很典型特殊的，每个渠道可能特价雷达的
    能力都不同，但是我们提供的是统一监控」。
    2026-11-01 r804 实测：上排「来源」只显示携程/飞猪/同程（本轮有数），
    途牛/去哪儿/两个 App 根本不出现——读者会以为「7 家都在跑、只是没供」。
    补 `<div class="spmon-cap">` 后 7 家全在，各标「本轮有数 / 未供」，
    悬停给出口径说明（SPECIAL_CAPABILITY[].note）。

    另：`srxSpLoad/srxSpecialEntryHTML` 那条路径依赖 `#srxSpBody`，
    而该容器在 HTML 里不存在（全文件仅 1 处取值、0 处定义）——是死代码，
    雷达真正的入口是监控台 specials 页签 + `#spMonSources`。
    """
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index("const src=$('spMonSources')")
    seg = src[i:src.index("const hn=$('spMonHistN')", i)]
    assert "spmon-cap" in seg, (
        "雷达来源区没有能力清单，7 家里没接入的渠道完全不可见")
    assert "SPMON.caps" in seg, "能力清单没读接口下发的 capabilities"
    # 能力数据必须在加载时取，否则读取端永远拿到 undefined
    li = src.index("async function spMonLoad(")
    load = src[li:src.index("\nfunction ", li)]
    assert "/api/specials" in load, (
        "spMonLoad 没取 /api/specials，SPMON.caps 永远是 undefined")


def test_watch_plats_include_app_channels():
    """关注航班的可选渠道白名单必须含 App 渠道。

    `_watch_plats()` 是 `_watch_channels()` 的**硬白名单**：不在里面的
    渠道会被静默丢弃（不报错、不提示）。2026-11-01 r805 实测：它只有
    5 家浏览器渠道，于是「把智行 App 加进关注航班」填得进去、存不下来
    ——与「控件能填≠保存侧接受」是同一类缺陷。
    """
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    seg = src[src.index("_WATCH_PLATS = _watch_plats()"):
              src.index("_DEMO_WATCH_PATH = None")]
    assert "APP_CHANNELS" in src[src.index("def _watch_plats()"):
                                 src.index("_WATCH_PLATS = _watch_plats()")], (
        "_watch_plats 没从 APP_CHANNELS 派生，新增 App 渠道仍会被静默丢弃")
    assert "_WATCH_PLATS = _watch_plats()" in seg
    # 参数化守卫：真跑一遍，确认 App 渠道在白名单里
    import webui as _w
    for p in ("app_zhixing", "app_qunar"):
        assert p in _w._WATCH_PLATS, (
            "关注航班白名单缺 %s：用户加进去会被静默丢弃" % p)
    # 浏览器 5 家不能被派生逻辑挤掉
    for p in ("qunar", "ctrip", "tuniu", "fliggy", "tongcheng"):
        assert p in _w._WATCH_PLATS, p


def test_demo_config_platforms_cover_every_scanned_channel():
    """演示站 `/api/config` 的 `users[0].platforms` 必须覆盖全部演示渠道。

    配置页「监控渠道」的勾选态**只**读 `u.platforms`（webui.py buildForm
    里 `(u.platforms||[]).includes(p)`）。该字段原先写死 5 家浏览器渠道，
    于是演示站上 7 个 chip 渲染出来了、只有 5 个是勾中的——用户看不出
    「智行 App / 去哪儿 App 到底参不参与监控」。

    这里不查源码字符串（`platforms` 在别处也出现，容易假绿），而是真
    调 `_demo_config_payload()` 并与演示库真实扫描的渠道集合对账。
    """
    from core.demo import DEMO_SCAN_PLATS
    import webui as _w
    u = _w._demo_config_payload()["users"][0]
    got = list(u.get("platforms") or [])
    # 对账基准用真实渠道表（REGISTRY），不是演示自己的常量——否则新增
    # 一家渠道时，演示常量与 config 载荷可以一起漏掉、测试仍然全绿。
    from crawlers import REGISTRY
    want = set(REGISTRY)
    assert set(got) == want, (
        "演示 /api/config 的 platforms=%s 与真实渠道表 %s 不一致；"
        "配置页勾选区会少勾/多勾" % (sorted(got), sorted(want)))
    assert set(DEMO_SCAN_PLATS) == want, (
        "DEMO_SCAN_PLATS 与 REGISTRY 脱节：%s"
        % sorted(set(DEMO_SCAN_PLATS) ^ want))
    # 反例守卫：不能退化成「只要有 platforms 键就算过」
    assert len(got) > 5, "platforms 退回 5 家浏览器渠道了"
