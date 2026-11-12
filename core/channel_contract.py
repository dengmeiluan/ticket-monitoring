# -*- coding: utf-8 -*-
"""渠道平台能力契约：渠道 × 平台质量轴（N 维）的可求值事实表。

`core/channels.py` 的能力矩阵回答「这家渠道**能采什么**」（国内/国际/
日历/明细/往返/多程/低价）；本模块回答「这家渠道**在产品里是不是一等
公民**」——用户点名的十一条轴：

    可配置 configurable   可观测 observable   可干预 intervenable
    可见性 visible        可溯源 traceable    可识别 identifiable
    可区分 distinguishable 可幂等 idempotent   语义清晰 semantics
    可指导 actionable     可判断 judgeable

设计约束（别退化）：
1. **不写第二份名单**：每轴都去读真实登记点（REGISTRY / 健康卡 / 雷达 /
   告警 / 演示 / 前端表 / 图标 / 账本 / 门禁），改一处就能被这里量到。
2. **状态只有三种**：`y` 已接入、`n` 未接入（缺陷）、`na` 结构上不适用
   （例：App 渠道没有 PC/H5 端面）。`n` 一律带「缺什么、看哪里」的说明。
3. **新渠道的验收就是 audit() 无 n**：接渠道时漏接任一表，这里直接报，
   不靠人对照 HANDOFF 清单。门禁见
   `tests/test_r813_channel_platform_contract.py`，负控会造一个幽灵渠道
   证明判据不是恒真。

命令行走查（会议/发版前可用）：
    python -m core.channel_contract            # 打印矩阵
    python -m core.channel_contract --strict   # 有 n 则退出码 1
"""
from __future__ import annotations

import inspect
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Y, N, NA = "y", "n", "na"

# (id, 中文名, 这一轴在问什么)
AXES = (
    ("configurable", "可配置", "配置页能勾到，且勾上会被真的实例化"),
    ("observable", "可观测", "健康卡/诊断卡按渠道给读数，不会从界面消失"),
    ("intervenable", "可干预", "登录失效或被拦时，有该渠道的干预入口"),
    ("visible", "可见性", "检索/雷达/告警/演示/入口板等界面都认得它"),
    ("traceable", "可溯源", "每次采集按通路落账，能回放到哪一步失败"),
    ("identifiable", "可识别", "中文名与官方图标齐全且唯一"),
    ("distinguishable", "可区分", "PC/H5 端面分列；App 标明同源与无端面"),
    ("idempotent", "可幂等", "写入以渠道为键可重放，不产生重复行"),
    ("semantics", "语义清晰", "三态声明合法；不支持有显式分支与说明"),
    ("actionable", "可指导", "现状能翻成带动作和中文说明的建议"),
    ("judgeable", "可判断", "每条声明都有门禁覆盖，能被自动证伪"),
)
AXIS_IDS = tuple(a[0] for a in AXES)
AXIS_CN = {a[0]: a[1] for a in AXES}
AXIS_Q = {a[0]: a[2] for a in AXES}


@dataclass(frozen=True)
class Cell:
    state: str
    detail: str


class _Ctx:
    """一次审计内复用的只读上下文（webui 4.6MB，别每格重读）。"""

    def __init__(self):
        self._webui = None
        self._front = None
        self._icons = None
        self._tests = None
        self._modsrc = {}

    @property
    def webui(self) -> str:
        if self._webui is None:
            with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
                self._webui = f.read()
        return self._webui

    def front_keys(self) -> set:
        """前端渠道表（SRX_PLATS ∪ APP_PLAT_NAME）里的键。"""
        if self._front is None:
            keys = _js_keys(self.webui, "SRX_PLATS")
            keys |= _js_keys(self.webui, "APP_PLAT_NAME")
            self._front = keys
        return self._front

    def icon_keys(self) -> set:
        if self._icons is None:
            keys = _js_quoted_keys(self.webui, "SRX_BRAND_IMG")
            # App 渠道可复用同品牌浏览器渠道的官方图标（运行时
            # `srxPlatIcon` 走 `SRX_BRAND_ALIAS`）。不解析别名会把
            # 「有图标」误判成缺图，逼着为一模一样的图复制 base64。
            m = re.search(r"const SRX_BRAND_ALIAS=\{([^}]*)\}", self.webui)
            if m:
                for alias, target in re.findall(
                        r"([a-z_]+)\s*:\s*'([a-z_]+)'", m.group(1)):
                    if target in keys:
                        keys.add(alias)
            self._icons = keys
        return self._icons

    def tests_hitting(self, plat: str) -> Tuple[int, Tuple[str, ...]]:
        """引用该渠道 id 的门禁文件数与样例（判断「有门禁覆盖」）。"""
        if self._tests is None:
            idx = {}
            tdir = os.path.join(ROOT, "tests")
            for fn in sorted(os.listdir(tdir)):
                if not fn.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(tdir, fn), encoding="utf-8") as f:
                        body = f.read()
                except OSError:
                    continue
                for p in _all_channels():
                    if p in body:
                        idx.setdefault(p, []).append(fn)
            self._tests = idx
        got = self._tests.get(plat) or []
        return len(got), tuple(got[:3])

    def module_source(self, plat: str) -> str:
        """该渠道 crawler 类所在模块 + 各父类的源码（含继承的落账调用）。"""
        if plat not in self._modsrc:
            from crawlers import REGISTRY
            cls = REGISTRY.get(plat)
            parts = []
            if cls is not None:
                seen = set()
                for c in cls.__mro__:
                    try:
                        fn = inspect.getsourcefile(c)
                    except TypeError:
                        continue
                    if fn and fn.endswith(".py") and fn not in seen:
                        seen.add(fn)
                        with open(fn, encoding="utf-8") as f:
                            parts.append(f.read())
            self._modsrc[plat] = "\n".join(parts)
        return self._modsrc[plat]


def _all_channels() -> Tuple[str, ...]:
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    return tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)


def _js_keys(src: str, name: str) -> set:
    """取 JS 对象字面量的顶层键（值可以是数组/长字符串）。"""
    m = re.search(r"(?:const|var)\s+%s\s*=\s*\{" % re.escape(name), src)
    if not m:
        return set()
    i = src.index("{", m.start())
    depth = 0
    end = i
    for j in range(i, min(len(src), i + 2_000_000)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = j
                break
    body = src[i + 1:end]
    return set(re.findall(r"(?:^|[,{])\s*([a-z_][a-z0-9_]*)\s*:", body, re.M))


def _js_quoted_keys(src: str, name: str) -> set:
    m = re.search(r"%s\s*=\s*\{" % re.escape(name), src)
    if not m:
        return set()
    i = src.index("{", m.start())
    seg = src[i:i + 600_000]
    j = seg.find("};")
    body = seg[:j if j > 0 else len(seg)]
    # base64 不含引号，所以「"id":」只会出现在键位
    return set(re.findall(r'"([a-z_][a-z0-9_]*)"\s*:', body))


# ---------------------------------------------------------------- 各轴探针

def _configurable(plat: str, ctx: _Ctx) -> Cell:
    missing = []
    try:
        from crawlers import REGISTRY
        if plat not in REGISTRY:
            missing.append("REGISTRY")
    except Exception as ex:  # pragma: no cover - 依赖环境
        return Cell(N, "无法读 crawlers.REGISTRY：%s" % ex)
    from core.channels import APP_CHANNELS
    from core.pacing import PLATFORMS
    if plat not in set(PLATFORMS) | set(APP_CHANNELS):
        missing.append("pacing 节奏表")
    if plat not in ctx.front_keys():
        missing.append("前端渠道表")
    if missing:
        return Cell(N, "配置链路缺：%s" % "、".join(missing))
    return Cell(Y, "REGISTRY + pacing 节奏表 + 前端渠道表")


def _observable(plat: str, ctx: _Ctx) -> Cell:
    import core.health as H
    import core.health_diag as D
    h = plat in set(H.PLATFORMS) | set(H.APP_CHANNELS)
    d = plat in set(D.PLATFORMS) | set(D.APP_CHANNELS)
    if h and d:
        return Cell(Y, "健康卡 + 诊断卡（可按渠道给失败类型/建议）")
    miss = "、".join([x for x, ok in (("健康卡", h), ("诊断卡", d))
                     if not ok])
    return Cell(N, "缺：%s——采到了界面也看不见" % miss)


def _intervenable(plat: str, ctx: _Ctx) -> Cell:
    from core.channels import APP_CHANNELS
    from core.login_slots import LOGIN_SLOTS
    if plat in LOGIN_SLOTS:
        return Cell(Y, "浏览器登录槽位（重登/验证走同一会话）")
    if plat in APP_CHANNELS:
        api = os.path.join(ROOT, "core", "android", "login_api.py")
        ok = os.path.exists(api) and "/api/app-login" in ctx.webui
        if ok:
            return Cell(Y, "App 登录面（/api/app-login）+ 重登入干预账")
        return Cell(N, "App 渠道没有登录面接线（login_api / 前端入口）")
    return Cell(N, "没有登录/干预入口")


def _probe_picker_covers(src: str, channels) -> Tuple[bool, str]:
    """主动探针的渠道选择器是否覆盖全部渠道。

    检索页的 `#srxPlatPick` 是静态 HTML（不是从 SRX_PLATS 渲染），
    曾只写 5 个浏览器 chip，导致后端支持 App、界面上却选不到。
    """
    m = re.search(r'id="srxPlatPick"([\s\S]{0,4000}?)</div>', src)
    if not m:
        return False, "找不到探针渠道选择器 #srxPlatPick"
    body = m.group(1)
    found = set(re.findall(r'data-p="([a-z_]+)"', body))
    missing = [p for p in channels if p not in found]
    if missing:
        return False, "探针 picker 缺：%s" % "、".join(missing)
    return True, "探针 picker %d chip" % len(found)


def _visible(plat: str, ctx: _Ctx) -> Cell:
    import core.health as H
    import core.health_diag as D
    import core.special_radar as R
    from core.alerter import Alerter
    from core.channels import APP_CHANNELS
    from core.channel_links import PLATS as LINK_PLATS
    from core.demo import DEMO_SCAN_PLATS
    from core.specials import SPECIAL_CAPABILITY
    _all = _all_channels()
    _probe_ok, _probe_detail = _probe_picker_covers(ctx.webui, _all)
    surfaces = {
        "健康卡": plat in set(H.PLATFORMS) | set(H.APP_CHANNELS),
        "诊断卡": plat in set(D.PLATFORMS) | set(D.APP_CHANNELS),
        "特价雷达": plat in R._CHANNELS,
        "能力声明": plat in SPECIAL_CAPABILITY,
        "入口板": plat in LINK_PLATS or plat in APP_CHANNELS,
        "告警名": plat in Alerter.PLATFORM_CN
                  or plat in Alerter.PLATFORM_CN_EXTRA,
        "演示站": plat in DEMO_SCAN_PLATS,
        "前端渠道表": plat in ctx.front_keys(),
        "主动探针": _probe_ok,
    }
    miss = [k for k, ok in surfaces.items() if not ok]
    if miss:
        detail = "这些界面里没有它：%s" % "、".join(miss)
        if not _probe_ok:
            detail += "（%s）" % _probe_detail
        return Cell(N, detail)
    return Cell(Y, "9 个可见面齐全：" + "、".join(surfaces)
                + "（%s）" % _probe_detail)


def _traceable(plat: str, ctx: _Ctx) -> Cell:
    from core.channels import PATH_CN
    src = ctx.module_source(plat)
    n = src.count("path_note(")
    if not n:
        return Cell(N, "crawler 没有 path_note：失败会变成「原因待核对」")
    if not PATH_CN:
        return Cell(N, "PATH_CN 通路名表为空：界面会露裸 id")
    return Cell(Y, "path_note ×%d + PATH_CN %d 条通路名" % (n, len(PATH_CN)))


def _identifiable(plat: str, ctx: _Ctx) -> Cell:
    from core.channels import CHANNEL_CN
    name = CHANNEL_CN.get(plat) or ""
    icons = ctx.icon_keys()
    dups = [p for p, n2 in CHANNEL_CN.items() if n2 == name and p != plat]
    miss = []
    if not name or name == plat:
        miss.append("中文名")
    if plat not in icons:
        miss.append("官方图标")
    if dups:
        miss.append("名字与 %s 重复" % "、".join(dups))
    if miss:
        return Cell(N, "缺：%s" % "、".join(miss))
    return Cell(Y, "%s + 官方图标（%d 家图标表）" % (name, len(icons)))


def _distinguishable(plat: str, ctx: _Ctx) -> Cell:
    from core.channels import (APP_BROWSER_PEER, APP_CHANNELS,
                               BROWSER_CHANNELS, CHANNEL_SURFACES,
                               SURFACE_NOTES, SURFACES)
    if plat in BROWSER_CHANNELS:
        row = CHANNEL_SURFACES.get(plat) or {}
        miss = []
        if set(row) != set(SURFACES):
            miss.append("PC/H5 未分列")
        bad = [k for k, v in row.items() if v not in ("y", "n", "")]
        if bad:
            miss.append("端面取值非法：" + "、".join(bad))
        no_note = [k for k in SURFACES if (plat, k) not in SURFACE_NOTES]
        if no_note:
            miss.append("端面缺说明：" + "、".join(no_note))
        if miss:
            return Cell(N, "；".join(miss))
        return Cell(Y, "PC=%s / H5=%s，两端各有说明"
                    % (row.get("pc", ""), row.get("h5", "")))
    if plat in APP_CHANNELS:
        peer = APP_BROWSER_PEER.get(plat)
        if plat in CHANNEL_SURFACES:
            return Cell(N, "App 渠道不该有 PC/H5 端面（会被读成未验证）")
        if peer not in BROWSER_CHANNELS:
            return Cell(N, "缺同源浏览器渠道（APP_BROWSER_PEER）")
        return Cell(Y, "无端面（画「—」），同源=%s" % peer)
    return Cell(N, "既不是浏览器也不是已登记 App 渠道")


def _idempotent(plat: str, ctx: _Ctx) -> Cell:
    if plat not in _all_channels():
        return Cell(N, "渠道未登记：写入契约无从谈起")
    path = os.path.join(ROOT, "core", "storage.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    key = "PRIMARY KEY (from_city, to_city, depart_date, flight_key, cabin, day, platform)"
    if key not in src:
        return Cell(N, "flight_daily 主键不含 platform：不同渠道会互相覆盖")
    if "INSERT OR REPLACE INTO flight_daily" not in src:
        return Cell(N, "flight_daily 不是 upsert：重放会产生重复行")
    return Cell(Y, "flight_daily 主键含 platform + INSERT OR REPLACE")


def _semantics(plat: str, ctx: _Ctx) -> Cell:
    from core.channels import (APP_CHANNELS, CHANNEL_DIMENSIONS,
                               CHANNEL_SURFACES, DIMENSION_NOTES,
                               DIMENSION_SCOPE, DIMENSIONS, SURFACE_NOTES)
    if plat not in CHANNEL_DIMENSIONS:
        return Cell(N, "能力矩阵没有这一行（r677 会拦）")
    row = CHANNEL_DIMENSIONS[plat]
    miss = []
    absent = [d for d in DIMENSIONS if d not in row]
    bad = [d for d in DIMENSIONS if row.get(d, "") not in ("y", "n", "")]
    if absent:
        miss.append("缺维度：" + "、".join(absent))
    if bad:
        miss.append("取值非法：" + "、".join(bad))
    if plat not in APP_CHANNELS:
        declared = [d for d in DIMENSIONS if row.get(d) == "n"]
        if declared and "unsupported" not in ctx.module_source(plat):
            miss.append("有 n 维度但没有 unsupported 分支")
    else:
        declared = [d for d in DIMENSIONS if row.get(d) == "n"]
        if declared and "unsupported" not in ctx.module_source(plat):
            miss.append("有 n 维度但没有 unsupported 分支")
    # 空 = 产品支持但采集端未实现/当前风控未出数；它和 n 一样必须有说明，
    # 但不再要求每个渠道至少有一个 n（全 y/空的渠道是合法的）。
    pending = [d for d in DIMENSIONS if row.get(d, "") == ""]
    for d in pending:
        if (plat, d) not in DIMENSION_NOTES:
            miss.append("%s 未验证但无说明" % d)
    if plat not in APP_CHANNELS:
        cells = CHANNEL_SURFACES.get(plat) or {}
        for surface, v in cells.items():
            if v in ("y", "n") and (plat, surface) not in SURFACE_NOTES:
                miss.append("端面 %s 无说明" % surface)
    for dim in DIMENSION_SCOPE:
        if dim[0] == plat and dim not in DIMENSION_NOTES:
            miss.append("%s 有范围标签但无说明" % (dim[1],))
    if miss:
        return Cell(N, "；".join(miss))
    return Cell(Y, "三态合法；%d 个 n + %d 个未验证均有说明"
                % (len(declared), len(pending)))


def _actionable(plat: str, ctx: _Ctx) -> Cell:
    import time
    from core.pacing import advise
    now = time.time()
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60))
    route_paths = {"H5": {"attempts": 10, "ok": 1, "rate": 0.1,
                          "rate_excl_empty": 0.1, "last_at": last}}
    watch_paths = {"H5": {"attempts": 10, "ok": 4, "rate": 0.4,
                          "rate_excl_empty": 0.4, "last_at": last}}
    cases = (
        ("登录失效", {"ch": {"needs_login": True}}),
        ("冷却中", {"ch": {"state": "cooldown", "reason": "ip",
                           "remain_s": 90}}),
        ("无样本", {"ch": {}}),
        ("路径劣化", {"ch": {}, "paths": route_paths,
                     "node": {"scopes": {"dom": {"paths": route_paths}}}}),
        ("成功率低", {"ch": {}, "paths": watch_paths,
                     "node": {"scopes": {"dom": {"paths": watch_paths}}}}),
    )
    labels = {"relogin": "重登", "wait": "冷却", "scan": "扫描",
              "probe": "自检", "route": "路径劣化",
              "watch": "成功率低", "none": ""}
    bad = []
    seen = []
    for label, kwargs in cases:
        r = advise(plat, now=now, **kwargs)
        act = str(r.get("action") or "")
        hint = str(r.get("hint") or "")
        seen.append("%s→%s" % (label, act or "?"))
        if not act or not re.search(r"[\u4e00-\u9fff]", hint):
            bad.append("%s 没给出动作或中文说明" % label)
            continue
        need = labels.get(act)
        if need and need not in ctx.webui:
            bad.append("动作 %s 在界面没有中文落点" % act)
    if bad:
        return Cell(N, "；".join(bad))
    return Cell(Y, "五态均有动作+中文说明（%s）" % "，".join(seen))


def _judgeable(plat: str, ctx: _Ctx) -> Cell:
    n, examples = ctx.tests_hitting(plat)
    if n < 1:
        return Cell(N, "没有任何门禁文件引用该渠道 id")
    return Cell(Y, "%d 个门禁文件（如 %s）" % (n, examples[0] if examples else ""))


PROBES: Dict[str, Callable[[str, _Ctx], Cell]] = {
    "configurable": _configurable,
    "observable": _observable,
    "intervenable": _intervenable,
    "visible": _visible,
    "traceable": _traceable,
    "identifiable": _identifiable,
    "distinguishable": _distinguishable,
    "idempotent": _idempotent,
    "semantics": _semantics,
    "actionable": _actionable,
    "judgeable": _judgeable,
}


def audit(plat: str, ctx: _Ctx = None) -> Dict[str, Cell]:
    """渠道 → 每轴一格。未知渠道不会抛异常，整行按「缺登记」报 n。"""
    ctx = ctx or _Ctx()
    return {axis: PROBES[axis](plat, ctx) for axis in AXIS_IDS}


def audit_all(ctx: _Ctx = None) -> Dict[str, Dict[str, Cell]]:
    ctx = ctx or _Ctx()
    return {p: audit(p, ctx) for p in _all_channels()}


def gaps(matrix: Dict[str, Dict[str, Cell]] = None) -> list:
    matrix = matrix if matrix is not None else audit_all()
    out = []
    for plat, row in matrix.items():
        for axis in AXIS_IDS:
            cell = row.get(axis) or Cell(N, "未求值")
            if cell.state == N:
                out.append((plat, axis, cell.detail))
    return out


def render_text(matrix: Dict[str, Dict[str, Cell]] = None) -> str:
    matrix = matrix if matrix is not None else audit_all()
    head = "渠道".ljust(14) + " ".join(AXIS_CN[a][:4].rjust(4) for a in AXIS_IDS)
    lines = [head, "-" * len(head)]
    glyph = {Y: "√", N: "×", NA: "—"}
    for plat, row in matrix.items():
        cells = " ".join(glyph.get(row[a].state, "?").rjust(4) for a in AXIS_IDS)
        lines.append(plat.ljust(14) + cells)
    g = gaps(matrix)
    lines.append("")
    if not g:
        lines.append("全部 %d 家 × %d 轴：无缺口" % (len(matrix), len(AXIS_IDS)))
    else:
        lines.append("缺口 %d 处：" % len(g))
        for plat, axis, detail in g:
            lines.append("  [%s] %s：%s" % (AXIS_CN[axis], plat, detail))
    return "\n".join(lines)


def main() -> int:
    import sys
    text = render_text()
    print(text)
    if "--strict" in sys.argv:
        return 1 if gaps() else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
