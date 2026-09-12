# -*- coding: utf-8 -*-
"""渠道健康时间线：从 monitor.log 解析近 N 小时每渠道×每轮状态。

纯函数、零依赖。日志行格式（本项目 setup_logger 打出）：
    2026-09-09 14:00:17 [INFO] ticket-monitor: [qunar] 2026-10-05 最低价 ￥1926（…）

轮边界：`===== 开始一轮扫描 =====` / `===== 本轮扫描结束 =====`。
状态归并（每轮×每渠道）：
    ok    全部日期查询成功
    part  部分成功 / 限流后重试成功（琥珀，留痕）
    fail  全部失败（含未带日期的请求异常）
    maint 渠道维护模式（"进入维护模式"锁存，直到该渠道重新出价）
"""
import re
from datetime import datetime, timedelta

PLATFORMS = ("qunar", "fliggy", "ctrip", "tongcheng", "tuniu")

_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([A-Z]+)\] [\w.\-]+: (.*)$")
_PLAT = re.compile(r"^\[(qunar|fliggy|ctrip|tongcheng|tuniu)\]\s*(.*)$")
_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")

_OK_MARK = "最低价 ￥"
_FAIL_DATED = ("达到最大重试圈数", "未解析到价格", "未拿到真实价格")
_EXC_MARK = "请求异常"
_RETRY_MARKS = ("命中风控", "疑似限流", "后第")
_MAINT_MARK = "进入维护模式"
_ROUND_BEGIN = "开始一轮扫描"
_ROUND_END = "本轮扫描结束"

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def parse_health(log_text, now=None, hours=24):
    """解析日志 → {"rounds": [...], "stats": {...}}（按时间升序）。

    round: {"ts": "YYYY-MM-DD HH:MM",
            "plats": {plat: {"s": ok|part|fail|maint, "ok": n, "tot": n,
                             "note": "失败原因/备注"}}}
    stats: {plat: {"ok": n, "part": n, "fail": n, "maint": n,
                   "rate": ok/(ok+part+fail)}}
    """
    if isinstance(now, str):
        now = datetime.strptime(now, _TS_FMT)
    now = now or datetime.now()
    cutoff = now - timedelta(hours=hours)

    rounds = []
    cur = None        # {"ts": datetime, "events": {plat: ev}}
    maint = set()     # 维护锁存（跨轮）

    def _new_round(ts):
        return {"ts": ts, "events": {}}

    def _flush():
        nonlocal cur
        if cur is None:
            return
        plats = {}
        for plat, ev in cur["events"].items():
            ok_n, fail_n = len(ev["ok"]), len(ev["fail"])
            tot = ok_n + fail_n + ev["generic_fail"]
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
            else:
                s = "fail"
                note = note or "抓取失败"
            plats[plat] = {"s": s, "ok": ok_n, "tot": tot, "note": note}
        for plat in maint:
            if plat not in plats:
                plats[plat] = {"s": "maint", "ok": 0, "tot": 0,
                               "note": "渠道维护模式"}
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
            continue
        plat, rest = pm.group(1), pm.group(2)
        if cur is None:                  # 日志截断在轮中间，隐式开轮
            cur = _new_round(ts)
        ev = cur["events"].setdefault(plat, {
            "ok": set(), "fail": set(), "retry": 0,
            "generic_fail": 0, "note": ""})
        dm = _DATE.search(rest)
        d = dm.group(1) if dm else None
        if _MAINT_MARK in msg:
            maint.add(plat)
            ev["note"] = "渠道维护模式"
        elif _OK_MARK in msg and d:
            ev["ok"].add(d)
            maint.discard(plat)
        elif any(k in msg for k in _FAIL_DATED):
            if d:
                ev["fail"].add(d)
            else:
                ev["generic_fail"] += 1
            if not ev["note"]:
                ev["note"] = rest[:40]
        elif _EXC_MARK in msg:
            if d:
                ev["fail"].add(d)
            else:
                ev["generic_fail"] += 1
            if not ev["note"]:
                ev["note"] = rest[:40]
        elif any(k in msg for k in _RETRY_MARKS):
            ev["retry"] += 1
    _flush()

    stats = {}
    for r in rounds:
        for plat, p in r["plats"].items():
            st = stats.setdefault(
                plat, {"ok": 0, "part": 0, "fail": 0, "maint": 0,
                       "rate": 0.0})
            st[p["s"]] += 1
    for plat, st in stats.items():
        att = st["ok"] + st["part"] + st["fail"]
        st["rate"] = (st["ok"] / att) if att else 0.0
    return {"rounds": rounds, "stats": stats}
