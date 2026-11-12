"""基线快照：`python -m core.baseline [--out 文件]`（r1063 T164）

为什么要有：判断"改动到底有没有让爬取率变好"，必须能**同一口径复测**。
以前每次都是我临时写 SQL（散在会话里，下次没人找得到）。这个命令把
「今日各渠道出数 / 各通路效率 / 失败面构成 / 登录槽位 / 降级项 / 最近一轮计时」
一次性写成 Markdown，随时复跑、随时对比。

口径铁律：**只算真出数**（`ok`/`calendar`）的行数；失败面单独列，
绝不把"尝试次数"混进"产出"。对比看 **行/次**（产出效率），不看总行数
（总行数受轮次与日期影响）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request

DEFAULT_PORTS = (8765, 8000, 5000)

#: 「真出数」的唯一定义（r1182：报表与 `core.rates` 共用，禁止各写一份）。
OK_STATUSES = ("ok", "calendar")


def _has_elapsed_ms(conn) -> bool:
    """`elapsed_ms` 是 2026-11-09 才加的列：老库/测试库可能没有，不能因此挂掉。"""
    try:
        return "elapsed_ms" in {r[1] for r in conn.execute(
            "PRAGMA table_info(fetch_paths)")}
    except Exception:
        return False


def by_path(conn, hours: int = 12) -> list:
    """各通路近 N 小时的取数结果（**唯一口径**）。

    返回每项：`plat / path / n（次数）/ rows（行数）/ dates（独立日期数）/
    avg_ms（平均耗时，无样本为 None）/ eff（行/次）`。

    为什么抽出来：`render()` 的 Markdown 与 `core.rates.snapshot()` 的数字必须
    永远是同一个算法，否则页面上写的"效率"和基线报告对不上，谁都不敢信。
    """
    ms_sql = ("avg(case when elapsed_ms>0 then elapsed_ms end) "
              if _has_elapsed_ms(conn) else "NULL ")
    ok_list = ",".join("'%s'" % s for s in OK_STATUSES)
    q = ("select platform, entry_path, count(*), sum(rows), "
         "count(distinct depart_date), " + ms_sql +
         # 平均耗时只统计**有耗时样本**的行（老行为 0）。三维一起看才判得准：
         # 覆盖（独立日期数）× 产出（行/次）× 成本（平均耗时）。
         "from fetch_paths where fetched_at >= "
         "datetime('now','localtime','-%d hours') "
         "and path_status in (%s) "
         "group by platform, entry_path "
         "order by sum(rows)*1.0/count(*) desc" % (int(hours), ok_list))
    out = []
    for plat, path, n, rows, nd, avg_ms in conn.execute(q):
        out.append({"plat": plat, "path": path, "n": int(n or 0),
                    "rows": int(rows or 0), "dates": int(nd or 0),
                    "avg_ms": (float(avg_ms) if avg_ms else None),
                    "eff": (rows or 0) / float(n or 1)})
    return out


def _get(base: str, path: str, timeout: float = 20.0) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _base(port: int = 0) -> str:
    for p in ([port] if port else list(DEFAULT_PORTS)):
        try:
            _get("http://127.0.0.1:%d" % p, "/api/pacing", timeout=8)
            return "http://127.0.0.1:%d" % p
        except Exception:
            continue
    return ""


def _db_path() -> str:
    try:
        import re
        txt = open("config.yaml", encoding="utf-8").read()
        m = re.search(r"(?m)^\s*db_path:\s*(\S+)", txt)
        if m:
            return m.group(1).strip("\"'")
    except Exception:
        pass
    return "data/prices.db"


def render(hours: int = 12, db: str = "", port: int = 0) -> str:
    """生成整份 Markdown（纯函数：只读库 + 实例）。"""
    db = db or _db_path()
    base = _base(port)
    today = time.strftime("%Y-%m-%d")
    L = ["# 基线快照（%s）" % today, "",
         "> 用途：任何改动前后用同一口径复测对比。数据来自本机 `%s` 与 `%s`，"
         "不估算。" % (db, base or "（实例未运行）"), ""]

    conn = None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    except Exception as e:
        L.append("（读不到数据库：%s）" % str(e)[:80])

    if conn is not None:
        L += ["## 一、今日各渠道出数（只算真出数 ok/calendar）", "",
              "| 渠道 | 次数 | 行数 | 行/次 |", "|---|---|---|---|"]
        for plat, n, rows in conn.execute(
                "select platform, count(*), sum(rows) from fetch_paths "
                "where fetched_at >= date('now','localtime') "
                "and path_status in ('ok','calendar') "
                "group by platform order by sum(rows) desc"):
            L.append("| %s | %d | %d | %.1f |"
                     % (plat, n, rows or 0, (rows or 0) / float(n or 1)))

        L += ["", "## 二、各通路效率 + **通路分工**（近 %d 小时，按行/次降序）" % hours,
              "",
              "| 渠道 | 通路 | 次数 | 行数 | 行/次 | 独立日期数 | 平均耗时 |",
              "|---|---|---|---|---|---|---|"]
        # r1182：数字走 `by_path()`（与 /api/three-rates 同一口径），这里只负责排版。
        for _r in by_path(conn, hours=hours):
            _ms = ("%.1fs" % (_r["avg_ms"] / 1000.0)) if _r["avg_ms"] else "—"
            L.append("| %s | %s | %d | %d | %.1f | %d | %s |"
                     % (_r["plat"], _r["path"], _r["n"], _r["rows"],
                        _r["eff"], _r["dates"], _ms))
        L += ["",
              "> **读这一节的前提**：`行/次` 只在『分工相同』时可比。新增/调整通路后，"
              "有的通路会先吃掉好采的日期，其余通路只剩缺口——比值下降不等于变差。"
              "判断办法：看 `独立日期数`（分工变了，这个数也会变），并对照第三节"
              "**失败面构成**。",
              "",
              "> **`独立日期数` 的口径**：本表数的是 **`fetch_paths` 里请求过的日期**，"
              "**不等于实际覆盖的日期**——整窗收割（如智行 App 一次 62 天）把额外日期"
              "写进 `flight_prices`，不在这张表里。真实覆盖请看 "
              "`python -m core.channel_matrix --dates`，或面板的「日历覆盖」一行。"]

        L += ["", "## 三、失败面构成（近 %d 小时，前 12 项）" % hours, "",
              "| 渠道 | 通路 | 状态 | 次数 |", "|---|---|---|---|"]
        for plat, path, st, n in conn.execute(
                "select platform, entry_path, path_status, count(*) "
                "from fetch_paths where fetched_at >= "
                "datetime('now','localtime','-%d hours') "
                "and path_status not in ('ok','calendar') "
                "group by platform, entry_path, path_status "
                "order by count(*) desc limit 12" % int(hours)):
            L.append("| %s | %s | %s | %d |" % (plat, path, st, n))
        conn.close()

    if base:
        try:
            slots = (_get(base, "/api/login-state") or {}).get("slots") or {}
            if slots:
                L += ["", "## 四、登录槽位（各端独立 profile）", "",
                      "| 槽位 | 端 | 状态 | 需登录 |", "|---|---|---|---|"]
                for key in sorted(slots):
                    v = slots[key] or {}
                    L.append("| %s | %s | %s | %s |"
                             % (key, v.get("surface_label") or "-",
                                v.get("status") or "-",
                                "是" if v.get("needs_login") else "否"))
        except Exception:
            pass
        try:
            pc = _get(base, "/api/pacing") or {}
            dg = pc.get("degraded") or {}
            if dg:
                L += ["", "## 五、降级项", "", "| 项 | 次数 | 最近原因 |",
                      "|---|---|---|"]
                for k, v in dg.items():
                    L.append("| %s | %s | %s |"
                             % (k, (v or {}).get("n"),
                                str((v or {}).get("last"))[:70].replace("|", "/")))
            tm = pc.get("timing") or {}
            if tm:
                L += ["", "## 六、最近一轮计时", "", "| 项 | 值 |", "|---|---|"]
                for k in ("n", "wall", "work", "idle_ratio", "gate_ratio",
                          "timed_out"):
                    if k in tm:
                        L.append("| %s | %s |" % (k, tm.get(k)))
        except Exception:
            pass

    L += ["", "## 复测方法", "", "```bash",
          "python -m core.baseline --out /tmp/after.md",
          "python -m core.channel_matrix",
          "python -m core.channel_matrix --trend --hours 6",
          "python -m core.advise", "```", "",
          "**对比看 `行/次`（产出效率）与失败面构成**，不要只看总行数"
          "（总行数受轮次与日期影响）。"]
    return "\n".join(L) + "\n"


def main(argv=None):                                     # pragma: no cover
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    out, hours, port = "", 12, 0
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
        if a == "--hours" and i + 1 < len(argv):
            hours = int(argv[i + 1])
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    text = render(hours=hours, port=port)
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("已写 %s（%d 行）" % (out, len(text.splitlines())))
    else:
        print(text)
    return 0


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())
