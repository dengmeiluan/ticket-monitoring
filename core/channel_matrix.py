"""渠道 × 通路矩阵（r1063 T132）：`python -m core.channel_matrix`

一条命令看清"每家渠道的每条通路现在是什么状态、最后一次为什么"。

为什么需要它：面板上信息是分散的（健康卡、降级行、会话窗口、登录卡），
排查时要来回看；而这个矩阵把 `/api/pacing` 里已有的字段拼成一张表，
**不新增任何采集逻辑**，只是把已有事实按"渠道 × 通路"摆开。

用法：
```
python -m core.channel_matrix                 # 全部渠道
python -m core.channel_matrix --plat fliggy   # 只看一家
python -m core.channel_matrix --json          # 给脚本用
python -m core.channel_matrix --port 8000
```

输出示例（列含义）：
```
渠道            通路        状态        近24h            最后原因
fliggy         PC          ok          132 次/9920 行   sjipiao.fliggy.com 国际列表
app_fliggy     app-login   login       2 次/0 行        需登录（97 分钟内不再重试）
```
"""
from __future__ import annotations

import json
import urllib.request

DEFAULT_PORTS = (8765, 8000, 5000)
# 状态 → 中文（与面板一致；缺的走原样输出，不硬编）
STATUS_CN = {
    "ok": "成功",
    "calendar": "日历",
    "login": "需登录",
    "blocked": "被拦",
    "empty": "无数据",
    "timeout": "超时",
    "error": "错误",
    "unsupported": "不支持",
    "soft_reject": "软拒",
    "paced": "主动让位",
}


def _get(base: str, path: str, timeout: float = 25.0) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _derive_state(rate, why: str) -> str:
    """由成功率 + 原因推导一个**可读状态**（面板同源，不新造数据）。

    `/api/pacing` 的通路对象只有 `rate/attempts/why/last_ok_at`，没有状态串；
    直接摆 rate 对人不友好，所以按下面规则翻译：
      rate≈1 → 成功；0<rate<1 → 时好时坏；rate==0 → 看原因关键词。
    """
    try:
        r = float(rate) if rate is not None else None
    except (TypeError, ValueError):
        r = None
    if r is None:
        return "无数据"
    if r >= 0.99:
        return "成功"
    if r > 0:
        return "时好时坏"
    t = why or ""
    for kw, label in (("登录", "需登录"), ("login", "需登录"),
                      ("验证", "被拦"), ("风控", "被拦"), ("拒绝", "被拦"),
                      ("停服", "停服"), ("超时", "超时"), ("timeout", "超时"),
                      ("不支持", "不支持"), ("视野", "不支持"),
                      ("让位", "主动让位"), ("预算", "主动让位")):
        if kw in t:
            return label
    return "无数据"


def collect(port: int = 0) -> dict:
    """读运行中实例，返回 {ok, port, rows:[{plat,path,status,n,rows,why}]}。"""
    ports = [port] if port else list(DEFAULT_PORTS)
    last_err = ""
    for p in ports:
        base = "http://127.0.0.1:%d" % p
        try:
            pacing = _get(base, "/api/pacing")
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:50])
            continue
        rows = []
        for plat, ch in sorted((pacing.get("channels") or {}).items()):
            if not isinstance(ch, dict):
                continue
            for path, pv in sorted((ch.get("paths") or {}).items()):
                if not isinstance(pv, dict):
                    continue
                rate = pv.get("rate")
                why = str(pv.get("why") or pv.get("detail") or "")[:58]
                rows.append({
                    "plat": plat,
                    "path": path,
                    "rate": rate,
                    "n": int(pv.get("attempts") or 0),
                    "last_ok_at": str(pv.get("last_ok_at") or "")[:16],
                    "state": _derive_state(rate, why),
                    "why": why,
                })
        return {"ok": True, "port": p, "rows": rows,
                "degraded": list((pacing.get("degraded") or {}).keys())}
    return {"ok": False, "rows": [], "why": "连不上实例：" + last_err}


def _table(rows: list, plat: str = "") -> str:
    if plat:
        rows = [r for r in rows if r["plat"] == plat]
    if not rows:
        return "（没有数据；可能该渠道本轮还没跑过）"
    w1 = max(len(r["plat"]) for r in rows + [{"plat": "渠道"}])
    w2 = max(len(r["path"]) for r in rows + [{"path": "通路"}])
    out = ["%-*s  %-*s  %-10s  %-10s  %s"
           % (w1, "渠道", w2, "通路", "状态", "成功率/尝试", "最后原因")]
    out.append("-" * (w1 + w2 + 58))
    for r in rows:
        rate = r.get("rate")
        pct = ("%d%%" % round(float(rate) * 100)) if rate is not None else "—"
        stat = "%s/%s 次" % (pct, r["n"])
        _ms = r.get("avg_ms")
        if _ms:
            # r1063 T228：通路级耗时（fetch_paths.elapsed_ms）——没有这列，
            # 判断"哪条通路慢"就只能靠相邻记录时间差（今天因此误判过一次）。
            stat += " · 均 %.1fs" % (float(_ms) / 1000.0)
        out.append("%-*s  %-*s  %-10s  %-10s  %s"
                   % (w1, r["plat"], w2, r["path"], r["state"], stat,
                      r["why"] or "-"))
    return "\n".join(out)



#: 通路 → 口径类别（r1063 T152）。日历类给的是**票面价**，未拆税；
#: 列表/接口类给的是含税价。混比会误导，所以界面上要标出来。
CALENDAR_PATHS = ("PC·周历", "窗历", "日历", "calendar", "低价日历")
LIST_PATHS = ("PC", "PC·国际", "H5", "H5/API", "航班明细", "app-form",
              "app-date", "往返")
API_PATHS = ("API", "QUERY")


def path_kind(path: str) -> str:
    """通路口径：calendar / list / api / other。"""
    p = str(path or "")
    if any(k in p for k in CALENDAR_PATHS):
        return "calendar"
    if any(k in p for k in LIST_PATHS):
        return "list"
    if any(k in p for k in API_PATHS):
        return "api"
    return "other"


def _db_path() -> str:
    """数据库路径：config.crawler.db_path > data/prices.db。"""
    try:
        import io as _io
        import re as _re
        txt = _io.open("config.yaml", encoding="utf-8").read()
        m = _re.search(r"(?m)^\s*db_path:\s*(\S+)", txt)
        if m:
            return m.group(1).strip("\"'")
    except Exception:
        pass
    return "data/prices.db"


def trend(hours: int = 6, db: str = "") -> dict:
    """近 N 小时：每小时 × 每渠道的出数（只算真出数：ok / calendar）。"""
    import sqlite3

    db = db or _db_path()
    hours = max(1, min(int(hours or 6), 72))
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    except Exception as e:
        return {"ok": False, "why": "读不到数据库 %s：%s" % (db, e)}
    try:
        rows = list(conn.execute(
            "select strftime('%%H', fetched_at) h, platform, "
            "sum(case when path_status in ('ok','calendar') then rows else 0 end) r, "
            "count(*) n from fetch_paths "
            "where fetched_at >= datetime('now','localtime','-%d hours') "
            "group by h, platform order by h" % hours))
    except Exception as e:
        return {"ok": False, "why": "查询失败：%s" % e}
    finally:
        conn.close()

    hours_sorted = sorted({str(h) for h, _, _, _ in rows})
    plats = sorted({p for _, p, _, _ in rows})
    grid = {p: {h: 0 for h in hours_sorted} for p in plats}
    attempts = {p: 0 for p in plats}
    for h, p, r, n in rows:
        grid[p][str(h)] += int(r or 0)
        attempts[p] += int(n or 0)
    return {"ok": True, "db": db, "hours": hours, "hours_sorted": hours_sorted,
            "plats": plats, "grid": grid, "attempts": attempts}


def _trend_text(rep: dict) -> str:
    if not rep.get("ok"):
        return "✗ " + str(rep.get("why"))
    hs = rep["hours_sorted"]
    if not hs:
        return "（近 %s 小时没有采集记录）" % rep.get("hours")
    out = ["近 %s 小时每小时出数（只算真出数：ok/calendar）" % rep["hours"],
           "渠道          " + "".join("%6s" % h for h in hs) + "   合计"]
    for p in rep["plats"]:
        g = rep["grid"][p]
        tot = sum(g.values())
        out.append("%-13s" % p + "".join("%6d" % g[h] for h in hs)
                   + "%7d" % tot)
    all_tot = [sum(rep["grid"][p][h] for p in rep["plats"]) for h in hs]
    out.append("%-13s" % "合计" + "".join("%6d" % v for v in all_tot)
               + "%7d" % sum(all_tot))
    return "\n".join(out)



# 槽位状态 → 中文（缺的一律原样输出，不硬编）
SLOT_STATE_CN = {
    "saved": "已存待验",
    "available": "空闲",
    "page_ok": "页面正常",
    "login_required": "需登录",
    "challenge": "需验证",
    "error": "错误",
}


def login_slots(port: int = 0) -> dict:
    """读运行中实例的 /api/login-state，返回 9 格槽位的可读形态。"""
    ports = [port] if port else list(DEFAULT_PORTS)
    last = ""
    for p in ports:
        base = "http://127.0.0.1:%d" % p
        try:
            st = _get(base, "/api/login-state")
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:40])
            continue
        rows = []
        for key, v in (st.get("slots") or {}).items():
            if not isinstance(v, dict):
                continue
            blk = v.get("block") or {}
            try:
                from core.login_slots import slot_profile as _sp
                prof = _sp(key)
            except Exception:
                prof = key
            rows.append({
                "slot": key,
                "profile": prof,
                "surface": str(v.get("surface_label") or "-"),
                "status": str(v.get("status") or "-"),
                "needs": bool(v.get("needs_login")),
                "block": str(blk.get("kind") or "-"),
                "verified": str(v.get("verified_at") or "")[:16],
                "url": str(v.get("login_url") or "")[:38],
            })
        rows.sort(key=lambda r: r["slot"])
        return {"ok": True, "port": p, "rows": rows}
    return {"ok": False, "rows": [], "why": "连不上实例：" + last}


def _login_text(rep: dict) -> str:
    if not rep.get("ok"):
        return "✗ " + str(rep.get("why"))
    rows = rep["rows"]
    if not rows:
        return "（没有槽位数据）"
    w = max(len(r["slot"]) for r in rows + [{"slot": "槽位"}])
    wp = max(len(str(r.get("profile") or "-"))
             for r in rows + [{"profile": "profile"}])
    out = ["%-*s  %-*s  %-10s  %-8s  %-7s  %-6s  %s"
           % (w, "槽位", wp, "profile", "端", "状态", "要登录", "被拦", "登录入口")]
    out.append("-" * (w + wp + 62))
    for r in rows:
        st = SLOT_STATE_CN.get(r["status"], r["status"])
        out.append("%-*s  %-*s  %-10s  %-8s  %-7s  %-6s  %s"
                   % (w, r["slot"], wp, str(r.get("profile") or "-"),
                      r["surface"], st, "是" if r["needs"] else "否",
                      r["block"], r["url"] or "-"))
    need = [r["slot"] for r in rows if r["needs"]]
    out.append("")
    out.append("需要登录：%s" % ("、".join(need) if need else "无 ✓"))
    return "\n".join(out)



def date_coverage(hours: int = 12, db: str = "") -> dict:
    """近 N 小时：渠道 × 出发日期 的出数（缺口一眼可见）。"""
    import sqlite3

    db = db or _db_path()
    hours = max(1, min(int(hours or 12), 168))
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    except Exception as e:
        return {"ok": False, "why": "读不到数据库 %s：%s" % (db, e)}
    try:
        rows = list(conn.execute(
            "select platform, depart_date, entry_path, "
            "sum(case when path_status in ('ok','calendar') then rows else 0 end) r, "
            "count(*) n from fetch_paths "
            "where fetched_at >= datetime('now','localtime','-%d hours') "
            "group by platform, depart_date, entry_path "
            "order by platform, depart_date"
            % hours))
    except Exception as e:
        return {"ok": False, "why": "查询失败：%s" % e}
    finally:
        conn.close()

    plats = sorted({r[0] for r in rows})
    dates = sorted({r[1] for r in rows if r[1]})
    grid = {p: {d: 0 for d in dates} for p in plats}
    tries = {p: {d: 0 for d in dates} for p in plats}
    cal_rows = {p: {d: 0 for d in dates} for p in plats}
    list_rows = {p: {d: 0 for d in dates} for p in plats}
    for p, d, path, r, n in rows:
        if not d:
            continue
        grid[p][d] += int(r or 0)
        tries[p][d] += int(n or 0)
        kind = path_kind(path)
        if kind == "calendar":
            cal_rows[p][d] += int(r or 0)
        elif kind in ("list", "api"):
            list_rows[p][d] += int(r or 0)
    return {"ok": True, "hours": hours, "plats": plats, "dates": dates,
            "grid": grid, "tries": tries,
            "cal": cal_rows, "list": list_rows}


def _dates_text(rep: dict) -> str:
    if not rep.get("ok"):
        return "✗ " + str(rep.get("why"))
    dates = rep["dates"]
    if not dates:
        return "（近 %s 小时没有采集记录）" % rep.get("hours")
    short = [d[5:] for d in dates]          # 只显示 MM-DD，保持扁平静默
    w = max(len(p) for p in rep["plats"] + ["渠道"])
    out = ["近 %s 小时：渠道 × 出发日期 出数（0 = 该日期没拿到任何价）" % rep["hours"],
           "%-*s" % (w, "渠道") + "".join("%8s" % d for d in short)]
    cal = rep.get("cal") or {}
    lst = rep.get("list") or {}
    for p in rep["plats"]:
        cells = []
        for d in dates:
            v = rep["grid"][p][d]
            t = rep["tries"][p][d]
            c = (cal.get(p) or {}).get(d, 0)
            l = (lst.get(p) or {}).get(d, 0)
            if not v:
                cells.append("%8s" % ("0" if t else "-"))
            elif c and not l:
                # 只有日历类出数 → 标 *（票面口径，未拆税）
                cells.append("%8s" % ("%d*" % v))
            else:
                cells.append("%8s" % v)
        out.append("%-*s" % (w, p) + "".join(cells))
    if any((cal.get(p) or {}).get(d) for p in rep["plats"] for d in dates):
        out.append("")
        out.append("* = 只有日历类通路出数（票面价，未拆税）；无 * 为列表/接口含税价")
    return "\n".join(out)



#: 滑块/验证码类别 → 中文（与 crawlers/slider.py 的 kind 对应）
SLIDER_KIND_CN = {
    "slider": "滑块",
    "arithmetic": "算数",
    "text": "文字",
    "unknown": "未分类",
}


def _slider_blocked_s(rec: dict, now: float = 0.0) -> float:
    """冷却还剩多少秒（0 = 没拉黑）。"""
    import time as _t
    until = float(rec.get("blocked_until") or 0)
    return max(0.0, until - (_t.time() if not now else now))


def slider_stats(root: str = "user_data") -> dict:
    """扫所有 profile 的 `slider_ledger.json`，汇总每渠道的验证尝试战果。"""
    import glob
    import json
    import os

    rows = []
    files = sorted(glob.glob(os.path.join(str(root), "*",
                                          "slider_ledger.json")))
    for path in files:
        profile = os.path.basename(os.path.dirname(path))
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for plat, rec in sorted(data.items()):
            if not isinstance(rec, dict):
                continue
            bk = rec.get("by_kind") if isinstance(rec.get("by_kind"), dict) else {}
            parts = []
            for kind, it in sorted(bk.items()):
                if not isinstance(it, dict):
                    continue
                ok = int(it.get("ok") or 0)
                fail = int(it.get("fail") or 0)
                parts.append("%s %d/%d" % (SLIDER_KIND_CN.get(kind, kind),
                                           ok, ok + fail))
            rows.append({
                "profile": profile,
                "plat": str(plat),
                "tries": int(rec.get("tries") or 0),
                "today": int(rec.get("day_used") or 0),
                "fails": int(rec.get("fails") or 0),
                "blocked_s": _slider_blocked_s(rec),
                "last_ok": str(rec.get("last_ok") or ""),
                "kinds": "；".join(parts),
            })
    return {"ok": True, "root": root, "rows": rows, "files": len(files)}


def _slider_text(rep: dict) -> str:
    if not rep.get("ok"):
        return "✗ " + str(rep.get("why"))
    rows = rep["rows"]
    if not rows:
        return ("（没有验证尝试记录：%s 下没有 slider_ledger.json）\n"
                "说明：简单滑块/算数/文字类会自动尝试；NC 这类强人机验证"
                "只记账不硬刚。" % rep.get("root"))
    out = ["验证尝试战果（只统计简单滑块/算数/文字类；强人机验证不硬刚）",
           "%-14s %-11s %-6s %-6s %-6s %-9s %s"
           % ("profile", "渠道", "总次数", "今日", "当前连败", "冷却", "分类战绩")]
    out.append("-" * 78)
    for r in rows:
        cool = ("%.0f 分钟" % (r["blocked_s"] / 60.0)) if r["blocked_s"] > 0 else "-"
        out.append("%-14s %-11s %-6s %-6s %-6s %-9s %s"
                   % (r["profile"][:14], r["plat"][:11], r["tries"],
                      r["today"], r["fails"], cool, r["kinds"] or "-"))
    return "\n".join(out)


def ms_table(hours: int = 24, limit: int = 20, db: str = "") -> str:
    """通路耗时视图（`fetch_paths.elapsed_ms`）。

    单独一个视图而不塞进 `path_stats()`：那条链已经有 rate/detail_rate/
    query_rate 三套口径，再加展示字段容易把"健康判定"和"观测"搅在一起。
    """
    import os as _os
    import sqlite3 as _sq
    db = db or _os.path.join("data", "prices.db")
    if not _os.path.isfile(db):
        return "（找不到数据库 %s）" % db
    hours = max(1, min(int(hours or 24), 168))
    try:
        conn = _sq.connect("file:%s?mode=ro" % db, uri=True)
    except Exception as e:
        return "（读不到数据库：%s）" % e
    try:
        rows = list(conn.execute(
            "select platform, entry_path, count(*) n, "
            "round(avg(elapsed_ms)) avg_ms, max(elapsed_ms) max_ms "
            "from fetch_paths "
            "where elapsed_ms > 0 "
            "and fetched_at >= datetime('now','localtime', '-%d hours') "
            "group by platform, entry_path order by avg_ms desc limit %d"
            % (hours, int(limit))))
    except Exception as e:
        return "（查询失败：%s）" % e
    finally:
        conn.close()
    if not rows:
        return ("近 %d 小时还没有耗时样本（新口径从写入 elapsed_ms 之后开始统计；"
                "跑一轮或一次自检即可看到）" % hours)
    out = ["近 %d 小时 通路耗时（按平均耗时降序）" % hours,
           "%-12s %-10s %-6s %-8s %s" % ("渠道", "通路", "次数", "平均", "最慢")]
    out.append("-" * 56)
    for plat, path, n, avg_ms, max_ms in rows:
        out.append("%-12s %-10s %-6s %-8s %s"
                   % (plat, path, n, "%.1fs" % ((avg_ms or 0) / 1000.0),
                      "%.1fs" % ((max_ms or 0) / 1000.0)))
    return "\n".join(out)

def dist_table(hours: int = 24, db: str = "") -> str:
    """渠道 × 距今天数 的成功率（判断"日期太远"最快的视角）。"""
    import datetime as _dt
    import os as _os
    import sqlite3 as _sq

    db = db or _os.path.join("data", "prices.db")
    if not _os.path.isfile(db):
        return "（找不到数据库 %s）" % db
    hours = max(1, min(int(hours or 24), 168))
    try:
        conn = _sq.connect("file:%s?mode=ro" % db, uri=True)
    except Exception as e:
        return "（读不到数据库：%s）" % e
    try:
        rows = list(conn.execute(
            "select platform, depart_date, path_status, count(*) n "
            "from fetch_paths where fetched_at >= datetime("
            "'now','localtime','-%d hours') and depart_date != '' "
            "group by platform, depart_date, path_status" % hours))
    except Exception as e:
        return "（查询失败：%s）" % e
    finally:
        conn.close()

    today = _dt.date.today()
    buckets = {}
    for plat, dd, st, n in rows:
        try:
            dist = (_dt.date.fromisoformat(str(dd)) - today).days
        except Exception:
            continue
        if dist <= 30:
            rng = "<=30天"
        elif dist <= 60:
            rng = "31-60天"
        elif dist <= 90:
            rng = "61-90天"
        else:
            rng = ">90天"
        key = (plat, rng)
        ok, tot = buckets.get(key, (0, 0))
        buckets[key] = (ok + (n if st in ("ok", "calendar") else 0), tot + n)
    if not buckets:
        return "近 %d 小时没有可分析样本" % hours

    out = ["近 %d 小时 渠道 x 距今天数 的成功率（判断日期远近最好的视角）" % hours,
           "%-12s %-8s %-6s %s" % ("渠道", "距离", "样本", "成功率")]
    out.append("-" * 44)
    for (plat, rng), (ok, tot) in sorted(buckets.items()):
        out.append("%-12s %-8s %-6s %.0f%%"
                   % (plat, rng, tot, ok * 100.0 / max(1, tot)))
    return "\n".join(out)


def _main(argv=None):                              # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    port, plat, hours, want_trend = 0, "", 6, False
    want_login = "--login" in argv
    want_slider = "--slider" in argv
    want_dates = "--dates" in argv
    want_ms = "--ms" in argv
    want_dist = "--dist" in argv
    if "--trend" in argv:
        want_trend = True
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        if a == "--plat" and i + 1 < len(argv):
            plat = argv[i + 1]
        if a == "--hours" and i + 1 < len(argv):
            hours = int(argv[i + 1])
    if want_slider:
        srep = slider_stats()
        if "--json" in argv:
            print(json.dumps(srep, ensure_ascii=False, indent=1))
            return 0 if srep.get("ok") else 1
        print(_slider_text(srep))
        return 0 if srep.get("ok") else 1
    if want_dist:
        print(dist_table(hours))
        return 0
    if want_ms:
        print(ms_table(hours))
        return 0
    if want_dates:
        drep = date_coverage(hours)
        if "--json" in argv:
            print(json.dumps(drep, ensure_ascii=False, indent=1))
            return 0 if drep.get("ok") else 1
        print(_dates_text(drep))
        return 0 if drep.get("ok") else 1
    if want_login:
        lrep = login_slots(port)
        if "--json" in argv:
            print(json.dumps(lrep, ensure_ascii=False, indent=1))
            return 0 if lrep.get("ok") else 1
        print(_login_text(lrep))
        return 0 if lrep.get("ok") else 1
    if want_trend:
        trep = trend(hours)
        if "--json" in argv:
            print(json.dumps(trep, ensure_ascii=False, indent=1))
        else:
            print(_trend_text(trep))
        return 0 if trep.get("ok") else 1
    rep = collect(port)
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep.get("ok") else 1
    if not rep.get("ok"):
        print("✗", rep.get("why"))
        return 1
    print("实例 127.0.0.1:%s" % rep["port"])
    print(_table(rep["rows"], plat))
    if rep.get("degraded"):
        print("\n降级项：%s" % "、".join(rep["degraded"]))
    return 0

if __name__ == "__main__":                         # pragma: no cover
    raise SystemExit(_main())
