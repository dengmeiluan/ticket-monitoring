# -*- coding: utf-8 -*-
"""渠道健康时间线：从 monitor.log 解析近 N 小时每渠道×每轮状态。

纯函数、零依赖。日志行格式（本项目 setup_logger 打出）：
    2026-09-09 14:00:17 [INFO] ticket-monitor: [qunar] 2026-10-05 最低价 ￥1926（…）

轮边界：`===== 开始一轮扫描 =====` / `===== 本轮扫描结束 =====`。
状态归并（每轮×每渠道）：
    ok 全部日期查询成功
    part 部分成功 / 限流后重试成功（琥珀，留痕）
    fail 全部失败（含未带日期的请求异常）
    maint 渠道维护模式（"进入维护模式"锁存，直到该渠道重新出价）
"""
import re
from datetime import datetime, timedelta

# 从单一事实源派生：新增 App 渠道时这里不必再改一次
# （写死清单会让新渠道的日志行被 _PLAT 静默丢弃，
# 表现为「采到了但健康卡整条渠道不存在」）。
from core.channels import APP_CHANNELS, BROWSER_CHANNELS  # noqa: E402

PLATFORMS = BROWSER_CHANNELS
_PLAT_ALT = "|".join(BROWSER_CHANNELS + APP_CHANNELS)

_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([A-Z]+)\] [\w.\-]+: (.*)$")
_PLAT = re.compile(
    r"^\[(" + _PLAT_ALT + r")\]\s*(.*)$")
# 哨兵告警行（可见性）：「[解析哨兵] qunar 字段 …」/「[解析哨兵]
# [连续N日] qunar …」——不匹配 _PLAT 的话控制台 01 PULSE/04 HEALTH
# 对哨兵告警零可见（仅日志里存在），故须单独收录
_SENT = re.compile(
    r"^\[解析哨兵\](?:\[[^\]]+\])?\s*"
    r"(" + _PLAT_ALT + r")\s*(.*)$")
_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")

# 真实出价三族同权：国内列表「最低价」、国际明细「最低含税价」、
# 国际日历「日历最低含税价」。旧单串只认国内列表，国际四渠道即使
# 每轮出价也被记 fail（r355 实锤：ctrip/fliggy/tuniu 连续 91 轮红）。
_OK_PRICE = re.compile(
    r"(?:日历最低含税价|最低含税价|最低价)\s*[￥¥]\s*([\d,]+)")
_DETAIL_COUNT = re.compile(r"明细\s*[1-9]\d*\s*条")
_FAIL_DATED = ("达到最大重试圈数", "未解析到价格", "未拿到真实价格",
               "未拿到日历价")
# 非法链接/会话门拒也可能来自签名、入口或业务校验，不能证明认证失效。
_AUTH_MARKS = ("未登录硬拒", "需登录", "请登录", "登录失效", "会话失效")
_GATE_MARKS = ("会话门拒", "非法链接", "请求环境拒绝")
_EXC_MARK = "请求异常"
_RETRY_MARKS = ("命中风控", "疑似限流", "后第")
# 原站明确“没有符合条件的航班”是空结果，不是抓取失败；1999 既可能
# 是登录墙也可能是无票，只有带这些消息词才归 empty。
_EMPTY_MARKS = ("没有查询到符合条件的航班", "未查询到符合条件的航班",
                "没有查询到", "未查询到", "无航班", "no flight")
_MAINT_MARK = "进入维护模式"
_ROUND_BEGIN = "开始一轮扫描"
_ROUND_END = "本轮扫描结束"

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _evidence_scope(message):
    # 历史国内日志常无标签；缺范围时保留 unknown，不能当作国内证据。
    # 渠道前缀可嵌套（[tongcheng][intl]、[qunar][intl]），所以不能只在
    # 行首 match，用 search 找任意位置的方括号标记。
    if (re.search(r"\[(?:intl|international|国际)\]", message)
            or re.search(r"(?:^|\s)国际(?!机场)", message)
            or "· 国际" in message):
        return "international"
    if (re.search(r"\[(?:domestic|国内)\]", message)
            or re.search(r"(?:^|\s)国内", message)
            or "· 国内" in message):
        return "domestic"
    # 兜底：日志行里常有航线三字码（"开始抓取 SHA->HAK"）。用航线判域，
    # 让历史日志也能分端——否则分域面板只有国际一侧有数，国内永远空白。
    m = re.search(r"(?<![A-Z])([A-Z]{3})\s*(?:->|→)\s*([A-Z]{3})(?![A-Z])",
                  message)
    if m:
        try:
            from .intl import is_intl_route
            return ("international" if is_intl_route(m.group(1), m.group(2))
                    else "domestic")
        except Exception:
            pass
    return "unknown"


def parse_health(log_text, now=None, hours=24):
    """解析日志 → {"rounds": [...], "stats": {...}, "evidence": {...}}。

    round: {"ts": "YYYY-MM-DD HH:MM",
            "plats": {plat: {"s": ok|part|fail|maint, "ok": n, "tot": n,
                             "cal": n, "detail": n, "need_login": bool,
                             "note": "失败原因/备注"}}}
    stats: {plat: {"ok": n, "part": n, "fail": n, "maint": n,
                   "cal": n, "detail": n, "auth": n,
                   "rate": ok/(ok+part+fail)}}}
    evidence: {plat: {scope: {"auth_at": "YYYY-MM-DD HH:MM:SS" 或 "",
                             "detail_at": 同式, "auth_reason": 安全摘要}}}
    证据按事件时间独立截窗、跨轮取最新，scope 为 domestic/international/
    unknown。明细出数是业务证据，不等同于认证验证；日历出数不计明细证据。
    """
    if isinstance(now, str):
        now = datetime.strptime(now, _TS_FMT)
    now = now or datetime.now()
    cutoff = now - timedelta(hours=hours)

    rounds = []
    evidence = {}
    cur = None        # {"ts": datetime, "events": {plat: ev}}
    maint = set()     # 维护锁存（跨轮）

    def _record_evidence(plat, scope, ts, field, reason=""):
        if not cutoff <= ts <= now:
            return
        item = evidence.setdefault(plat, {}).setdefault(
            scope, {"auth_at": "", "detail_at": "", "auth_reason": ""})
        at = ts.strftime(_TS_FMT)
        if at >= item[field]:
            item[field] = at
            if field == "auth_at":
                item["auth_reason"] = reason

    def _new_round(ts):
        return {"ts": ts, "events": {}}

    def _flush():
        nonlocal cur
        if cur is None:
            return
        plats = {}
        for plat, ev in cur["events"].items():
            ok_n, fail_n = len(ev["ok"]), len(ev["fail"])
            empty_n = int(ev.get("empty", 0))
            tot = ok_n + fail_n + ev["generic_fail"]
            cal_n = sum(1 for k in ev["kinds"].values() if k == "cal")
            detail_n = ok_n - cal_n
            need_login = bool(ev["auth"])
            note = ev["note"]
            if plat in maint and not ok_n:
                s, note = "maint", "渠道维护模式"
            elif ok_n and (fail_n or ev["generic_fail"]):
                s = "part"
                note = note or "部分日期查询失败（%d/%d 成功）" % (
                    ok_n, ok_n + fail_n + ev["generic_fail"])
            elif ok_n and ev["retry"]:
                s, note = "part", note or "限流后重试成功"
            elif ok_n:
                s = "ok"
                if cal_n and not detail_n:
                    note = note or "日历价 %d（无航班明细）" % cal_n
                elif cal_n and detail_n:
                    note = note or "航班级 %d · 日历 %d" % (detail_n, cal_n)
            elif empty_n and not need_login:
                s = "empty"
                note = note or "无符合条件的航班"
            else:
                s = "fail"
                note = note or ("需登录 · 会话失效" if need_login
                                else "抓取失败")
            _scs = sorted(ev.get("scopes") or ())
            plats[plat] = {"s": s, "ok": ok_n, "tot": tot, "note": note,
                           "empty": empty_n,
                           "cal": cal_n, "detail": detail_n,
                           "cal_only": bool(cal_n and not detail_n),
                           "need_login": need_login,
                           # 单域轮直接给域名；两端都有（罕见）给 mixed；
                           # 旧日志无标记给 unknown，绝不默认成国内。
                           "scope": (_scs[0] if len(_scs) == 1
                                     else ("mixed" if _scs else "unknown"))}
        for plat in maint:
            if plat not in plats:
                plats[plat] = {"s": "maint", "ok": 0, "tot": 0,
                               "note": "渠道维护模式", "cal": 0, "detail": 0,
                               "need_login": False, "scope": "unknown"}
        if cur["ts"] >= cutoff:
            rounds.append({"ts": cur["ts"].strftime("%Y-%m-%d %H:%M"),
                           "plats": plats})
        cur = None

    for line in (log_text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), _TS_FMT)
        except ValueError:
            continue
        msg = m.group(3)
        if _ROUND_BEGIN in msg:
            if cur is not None:          # 上一轮缺结束标记，容错收尾
                _flush()
            cur = _new_round(ts)
            continue
        if _ROUND_END in msg:
            _flush()
            continue
        pm = _PLAT.match(msg)
        if not pm:
            sm = _SENT.match(msg)
            if sm:
                # 哨兵行只挂 note 不动 ok/fail 计数（字段覆盖率告警≠抓取
                # 失败）；该平台本轮无任何抓取事件时建事件兜底可见
                plat = sm.group(1)
                if cur is None:
                    cur = _new_round(ts)
                ev = cur["events"].setdefault(plat, {
                    "ok": set(), "fail": set(), "retry": 0,
                    "generic_fail": 0, "empty": 0, "note": "",
                    "kinds": {}, "auth": False, "scopes": set()})
                if not ev["note"]:
                    ev["note"] = ("哨兵: " + sm.group(2))[:60]
            continue
        plat, rest = pm.group(1), pm.group(2)
        if cur is None:                  # 日志截断在轮中间，隐式开轮
            cur = _new_round(ts)
        ev = cur["events"].setdefault(plat, {
            "ok": set(), "fail": set(), "retry": 0,
            "generic_fail": 0, "empty": 0, "note": "", "kinds": {},
            "auth": False, "scopes": set()})
        # 该行日志属于哪个域（国内/国际）：厂商级健康会把两端混成一个数，
        # 而国际日历门拒会让整家渠道看起来「坏了」，国内其实全绿。
        _sc = _evidence_scope(rest)
        if _sc != "unknown":
            ev["scopes"].add(_sc)
        dm = _DATE.search(rest)
        d = dm.group(1) if dm else None
        okm = _OK_PRICE.search(msg)
        auth_reason = next((k for k in _AUTH_MARKS if k in msg), "")
        if _MAINT_MARK in msg:
            maint.add(plat)
            ev["note"] = "渠道维护模式"
        elif okm and d:
            ev["ok"].add(d)
            # 同日先后出现日历与明细时以明细为准（明细信息量更高），
            # 不重复计数——kinds 按日期唯一归档。
            kind = ("cal" if "日历" in msg
                    else "detail")
            if ev["kinds"].get(d) != "detail":
                ev["kinds"][d] = kind
            if kind == "detail" and _DETAIL_COUNT.search(rest):
                _record_evidence(plat, _evidence_scope(rest), ts, "detail_at")
            maint.discard(plat)
        elif auth_reason:
            if d:
                ev["fail"].add(d)
            else:
                ev["generic_fail"] += 1
            ev["auth"] = True
            ev["note"] = "需登录 · 会话失效"
            _record_evidence(plat, _evidence_scope(rest), ts, "auth_at", auth_reason)
        elif any(k in msg for k in _GATE_MARKS):
            if d:
                ev["fail"].add(d)
            else:
                ev["generic_fail"] += 1
            if not ev["note"]:
                ev["note"] = "请求被拒（认证状态未确认）"
        elif any(k in msg for k in _EMPTY_MARKS):
            ev["empty"] += 1
            if not ev["note"]:
                ev["note"] = "无符合条件的航班"
        elif any(k in msg for k in _FAIL_DATED):
            if d:
                ev["fail"].add(d)
            else:
                ev["generic_fail"] += 1
            if not ev["note"]:
                ev["note"] = rest[:160]
        elif _EXC_MARK in msg:
            if d:
                ev["fail"].add(d)
            else:
                ev["generic_fail"] += 1
            if not ev["note"]:
                ev["note"] = rest[:160]
        elif any(k in msg for k in _RETRY_MARKS):
            ev["retry"] += 1
    _flush()

    stats = {}
    for r in rounds:
        for plat, p in r["plats"].items():
            st = stats.setdefault(
                plat, {"ok": 0, "part": 0, "fail": 0, "maint": 0,
                       "empty": 0, "rate": 0.0, "detail_rate": 0.0,
                       "detail_ok": 0, "cal_only": 0,
                       "cal": 0, "detail": 0, "auth": 0})
            st[p["s"]] += 1
            st["cal"] += p.get("cal", 0)
            st["detail"] += p.get("detail", 0)
            if p.get("detail", 0) > 0:
                st["detail_ok"] += 1
            if p.get("cal_only"):
                st["cal_only"] += 1
            if p.get("need_login"):
                st["auth"] += 1
    # 厂商 × 域：同一家渠道国内与国际走不同入口/登录墙，混成一个数会
    # 掩盖「哪一端坏了」。空表（旧日志无域标记）时上层按未知处理。
    by_scope = {}
    for r in rounds:
        for plat, p in r["plats"].items():
            sc = str(p.get("scope") or "unknown")
            if sc == "unknown":
                continue
            # 一轮里国内与国际都跑过（mixed）不能整轮丢弃——那会让分端
            # 统计只剩"纯单端"的轮次，同程国内样本正是这样消失的。
            # 按该轮实际产出的日期数分账：明细/日历来自哪端无法再拆，
            # 就如实两边各记一笔并标注，宁可双侧近似也不凭空丢样本。
            _scopes = ([sc] if sc != "mixed"
                       else ["domestic", "international"])
            for _sc in _scopes:
                node = (by_scope.setdefault(plat, {})
                        .setdefault(_sc, {"ok": 0, "part": 0, "fail": 0,
                                          "maint": 0, "empty": 0, "rate": 0.0,
                                          "detail_ok": 0, "cal_only": 0,
                                          "detail": 0, "mixed_src": 0}))
                node[p["s"]] = node.get(p["s"], 0) + 1
                node["detail"] += p.get("detail", 0)
                if p.get("detail", 0) > 0:
                    node["detail_ok"] += 1
                if p.get("cal_only"):
                    node["cal_only"] += 1
                if sc == "mixed":
                    node["mixed_src"] = node.get("mixed_src", 0) + 1
    for _pl, scopes in by_scope.items():
        for _sc, node in scopes.items():
            _att = node["ok"] + node["part"] + node["fail"]
            node["rate"] = (node["ok"] / _att) if _att else 0.0

    for plat, st in stats.items():
        att = st["ok"] + st["part"] + st["fail"]
        st["rate"] = (st["ok"] / att) if att else 0.0
        # 明细成功率只在「有机会出航班明细」的轮次里算：仅日历轮
        # 永远不可能有航班级明细，放进分母会把 16/18 压成 16/96
        det_att = att - st["cal_only"]
        st["detail_rate"] = (st["detail_ok"] / det_att) if det_att else 0.0
    return {"rounds": rounds, "stats": stats, "evidence": evidence,
            "by_scope": by_scope}
