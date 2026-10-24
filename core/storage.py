"""SQLite 价格存储"""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import List, Optional

from .models import FlightPrice


SCHEMA = """
CREATE TABLE IF NOT EXISTS flight_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    price REAL NOT NULL,
    airline TEXT,
    flight_no TEXT,
    depart_time TEXT,
    arrive_time TEXT,
    fetched_at TEXT NOT NULL,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_route_date
    ON flight_prices (from_city, to_city, depart_date, platform);
CREATE INDEX IF NOT EXISTS idx_fetched_at
    ON flight_prices (fetched_at);

CREATE TABLE IF NOT EXISTS special_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    ret_date TEXT,
    ret_price REAL,
    src_price REAL NOT NULL,
    price REAL NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_special_deals_at
    ON special_deals (fetched_at);

-- 特价雷达监控快照：用户配置的航线/日期范围内，每次官方渠道低价
-- 日历/榜单的逐日价。用于日历走势、低价日与历史回放；不是飞行明细。
CREATE TABLE IF NOT EXISTS radar_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    nationwide INTEGER NOT NULL DEFAULT 0,
    depart_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    price REAL NOT NULL,
    tax_included INTEGER NOT NULL DEFAULT -1,
    basis TEXT,
    kind TEXT,
    link TEXT,
    query_start TEXT,
    query_end TEXT,
    query_key TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radar_user_at
    ON radar_snapshots (user, fetched_at);
CREATE INDEX IF NOT EXISTS idx_radar_user_date
    ON radar_snapshots (user, depart_date);

-- 每次雷达运行（含缓存/回退/失败）都留一条；价格快照只收 ok，
-- 失败不污染历史，也不重置提醒基线。
CREATE TABLE IF NOT EXISTS radar_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    query_key TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    rows INTEGER NOT NULL DEFAULT 0,
    query_json TEXT,
    started_at TEXT,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radar_runs_user
    ON radar_runs (user, finished_at);

CREATE TABLE IF NOT EXISTS radar_alert_state (
    user TEXT NOT NULL,
    query_key TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    low_price REAL NOT NULL,
    low_at TEXT,
    low_channel TEXT,
    low_basis TEXT,
    last_alert_price REAL,
    last_alert_at TEXT,
    armed INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user, query_key, depart_date)
);
CREATE TABLE IF NOT EXISTS radar_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    query_key TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    price REAL NOT NULL,
    prev_low REAL,
    channel TEXT,
    basis TEXT,
    kind TEXT,
    link TEXT,
    flights_json TEXT,
    status TEXT,
    err TEXT,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radar_alerts_user
    ON radar_alerts (user, sent_at);
CREATE TABLE IF NOT EXISTS radar_alert_cfg (
    user TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    drop_min REAL NOT NULL DEFAULT 50,
    threshold REAL NOT NULL DEFAULT 0,
    cooldown_h REAL NOT NULL DEFAULT 12
);

CREATE TABLE IF NOT EXISTS alert_state (
    route_key TEXT PRIMARY KEY, -- from-to-date 组合
    last_price REAL NOT NULL,
    last_sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_daily (
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    day TEXT NOT NULL,          -- 聚合日 YYYY-MM-DD（按 fetched_at 当日）
    kind TEXT NOT NULL,         -- d=直飞 / t=中转（extra.transCity 判）
    n INTEGER NOT NULL,
    lo REAL NOT NULL,
    hi REAL NOT NULL,
    open REAL NOT NULL,
    close REAL NOT NULL,
    avg REAL NOT NULL,
    fetched_max TEXT NOT NULL,
    PRIMARY KEY (from_city, to_city, depart_date, day, kind)
);
CREATE TABLE IF NOT EXISTS flight_daily (
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    flight_key TEXT NOT NULL,
    cabin TEXT NOT NULL DEFAULT '',
    day TEXT NOT NULL,
    platform TEXT NOT NULL,
    n INTEGER NOT NULL,
    lo REAL NOT NULL,
    hi REAL NOT NULL,
    open REAL NOT NULL,
    close REAL NOT NULL,
    fetched_max TEXT NOT NULL,
    PRIMARY KEY (from_city, to_city, depart_date, flight_key, cabin, day, platform)
);
CREATE INDEX IF NOT EXISTS idx_flight_daily_key
    ON flight_daily (from_city, to_city, depart_date, flight_key, cabin, day);
"""


class PriceStorage:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute(
                "PRAGMA table_info(radar_snapshots)")}
            if "query_key" not in cols:
                c.execute("ALTER TABLE radar_snapshots ADD COLUMN "
                          "query_key TEXT NOT NULL DEFAULT ''")
                c.execute(
                    "UPDATE radar_snapshots SET query_key="
                    "'legacy|'||from_city||'|'||to_city||'|'||nationwide||'|'||"
                    "COALESCE(query_start,'')||'|'||COALESCE(query_end,'')")
            c.execute("CREATE INDEX IF NOT EXISTS idx_radar_user_qat "
                      "ON radar_snapshots(user, query_key, fetched_at)")
            fcols = {r[1] for r in c.execute(
                "PRAGMA table_info(flight_prices)")}
            if "prov" not in fcols:
                c.execute("ALTER TABLE flight_prices ADD COLUMN "
                          "prov TEXT NOT NULL DEFAULT ''")
            c.execute(
                "CREATE TABLE IF NOT EXISTS fetch_paths ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "fetched_at TEXT NOT NULL, platform TEXT NOT NULL,"
                "from_city TEXT NOT NULL, to_city TEXT NOT NULL,"
                "depart_date TEXT NOT NULL, entry_path TEXT,"
                "path_status TEXT, request_url TEXT,"
                "http_status INTEGER DEFAULT 0, rows INTEGER DEFAULT 0,"
                "note TEXT, evidence_level TEXT)")

    @staticmethod
    def radar_query_key(query):
        return "|".join([
            str(query.get("from") or ""), str(query.get("to") or ""),
            "1" if query.get("nationwide") else "0",
            str(query.get("start") or ""), str(query.get("end") or ""),
            ",".join(sorted(str(x) for x in (query.get("channels") or []))),
        ])

    def save(self, fp: FlightPrice):
        with self._conn() as c:
            c.execute(
                """INSERT INTO flight_prices
                (platform, from_city, to_city, depart_date, price,
                 airline, flight_no, depart_time, arrive_time, fetched_at,
                 extra, prov)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fp.platform, fp.from_city, fp.to_city, fp.depart_date,
                 fp.price, fp.airline, fp.flight_no, fp.depart_time,
                 fp.arrive_time, fp.fetched_at, fp.extra,
                 getattr(fp, "prov", "") or ""),
            )

    def save_many(self, prices: List[FlightPrice]):
        if not prices:
            return
        # 单连接批量写：一轮 5 渠道 × N 航线的逐行开连接合并为一次提交
        with self._conn() as c:
            c.executemany(
                """INSERT INTO flight_prices
                (platform, from_city, to_city, depart_date, price,
                 airline, flight_no, depart_time, arrive_time, fetched_at,
                 extra, prov)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(p.platform, p.from_city, p.to_city, p.depart_date,
                  p.price, p.airline, p.flight_no, p.depart_time,
                  p.arrive_time, p.fetched_at, p.extra,
                  getattr(p, "prov", "") or "") for p in prices],
            )

    def save_fetch_path(self, platform, from_city, to_city, depart_date,
                        entry_path, path_status, request_url="",
                        http_status=0, rows=0, note="",
                        evidence_level="path"):
        from datetime import datetime
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status,request_url,"
                "http_status,rows,note,evidence_level) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 str(platform or ""), str(from_city or ""),
                 str(to_city or ""), str(depart_date or ""),
                 str(entry_path or ""), str(path_status or ""),
                 str(request_url or ""), int(http_status or 0),
                 int(rows or 0), str(note or ""),
                 str(evidence_level or "path")))
            c.execute("DELETE FROM fetch_paths WHERE fetched_at < "
                      "datetime('now','localtime','-90 days')")
            return int(cur.lastrowid)

    def fetch_paths(self, from_city, to_city, depart_date, limit=100):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM fetch_paths WHERE from_city=? AND to_city=? "
                "AND depart_date=? ORDER BY id DESC LIMIT ?",
                (str(from_city or ""), str(to_city or ""),
                 str(depart_date or ""), int(limit))).fetchall()
        return [dict(r) for r in rows]

    def purge(self, days: int = 14) -> int:
        """删除 N 天前的价格明细（extra 大 JSON 是增长主体）与特价
        核实留痕；alert_state 保留（去抖状态）。price_daily 聚合桶
        不随 purge（半年走势窗的数据本体），其 400 天自清在
        daily_series 读时惰性执行。返回删除行数。"""
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM flight_prices WHERE fetched_at < "
                "datetime('now', 'localtime', ?)",
                (f"-{int(days)} days",))
            c.execute(
                "DELETE FROM special_deals WHERE fetched_at < "
                "datetime('now', 'localtime', ?)",
                (f"-{int(days)} days",))
            return cur.rowcount

    def refresh_daily(self, from_city: str, to_city: str,
                      depart_date: str, day: str = "") -> None:
        """重算某 (航线, 出发日期) 在聚合日 day（缺省=今日，按本地
        fetched_at 当日）的直飞/中转日桶并 upsert（幂等——重扫修正
        语义：同日多轮反复重算桶而非累加）。分桶粒度=元素级：行=
        渠道×查询、extra 元素=航班明细（全库 7,372 行混装直中并存，
        行级判转不良定义），每元素按自身 transCity 归桶、元素 price
        参与聚合，行价列不参与（`$.transCity` 根路径对数组恒 NULL 的
        首代缺陷与「any 元素判转整行」的第二代缺陷皆在此收口）；
        extra='' 直飞桶。概览口径备案：桶不做中转衔接/到达窗细约束
        （明细删净后判定口径不可重放，长窗=纯趋势概览）。"""
        day = day or datetime.now().strftime("%Y-%m-%d")
        with self._conn() as c:
            c.execute(
                "DELETE FROM price_daily WHERE from_city=? AND to_city=? "
                "AND depart_date=? AND day=?",
                (from_city, to_city, depart_date, day))
            # 元素展开聚合（每桶读当日明细行×元素，量级=当日元素数，
            # 万级以内）；桶内序=fetched_at→行→元素位（open/close 语义）
            rows = c.execute(
                """SELECT json_extract(je.value,'$.price'),
                          json_extract(je.value,'$.transCity'),
                          fp.fetched_at
                    FROM flight_prices fp, json_each(fp.extra) je
                    WHERE fp.from_city=? AND fp.to_city=? AND fp.depart_date=?
                      AND fp.fetched_at>=? AND fp.fetched_at<? AND fp.extra!=''
                    ORDER BY fp.fetched_at, fp.id, je.key""",
                (from_city, to_city, depart_date,
                 f"{day} 00:00:00", f"{day} 23:59:59")).fetchall()
            buckets = {}
            for raw_price, trans_city, ts in rows:
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    continue   # 元素缺合法 price 不参与聚合（宁缺勿错）
                # truthy 门（NULL 与 "" 同归直飞）：生产元素两态并存
                # ——键缺席（无值不落键构造器）与恒写空串键（62,413
                # 元素实证），空串绝不可能是真中转城市
                k = "t" if trans_city else "d"
                buckets.setdefault(k, []).append((price, ts))
            for k, g in buckets.items():
                prices = [p for p, _ in g]
                c.execute(
                    """INSERT OR REPLACE INTO price_daily
                    (from_city,to_city,depart_date,day,kind,n,lo,hi,
                     open,close,avg,fetched_max)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (from_city, to_city, depart_date, day, k,
                     len(prices), min(prices), max(prices),
                     prices[0], prices[-1],
                     round(sum(prices) / len(prices), 2),
                     max(ts for _, ts in g)))

    def refresh_flight_daily(self, from_city: str, to_city: str,
                             depart_date: str, day: str = "") -> None:
        """把某 (航线, 出发日期, 聚合日) 的全量采集行展开为航班日桶。

        航线采集天然包含全部航班；此表不依赖关注配置，所有被采到的
        航班都落一份日 OHLC（按平台/舱位/航班身份），raw 明细 purged
        后长窗仍可回放。重扫同日先删后建，幂等修正。
        """
        from .flighthist import key_from_raw
        day = day or datetime.now().strftime("%Y-%m-%d")
        try:
            nxt = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)
                   ).strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError("day 必须为 YYYY-MM-DD")
        buckets = {}
        with self._conn() as c:
            rows = c.execute(
                """SELECT platform, extra, fetched_at FROM flight_prices
                   WHERE from_city=? AND to_city=? AND depart_date=?
                     AND extra!='' AND fetched_at>=? AND fetched_at<?
                   ORDER BY fetched_at, id""",
                (from_city, to_city, depart_date,
                 day + " 00:00:00", nxt + " 00:00:00")).fetchall()
            if not rows:
                return
            for r in rows:
                try:
                    obj = json.loads(r["extra"] or "[]")
                except ValueError:
                    continue
                items = obj if isinstance(obj, list) else (
                    [obj] if isinstance(obj, dict) else [])
                for raw in items:
                    got = key_from_raw(from_city, to_city, depart_date,
                                       raw, r["platform"])
                    if not got:
                        continue
                    _g, key, cabin, price = got
                    b = buckets.setdefault((key, cabin, r["platform"]),
                                           {"p": [], "at": []})
                    b["p"].append(price)
                    b["at"].append(str(r["fetched_at"] or ""))
            c.execute(
                "DELETE FROM flight_daily WHERE from_city=? AND to_city=? "
                "AND depart_date=? AND day=?",
                (from_city, to_city, depart_date, day))
            for (key, cabin, platform), b in buckets.items():
                prices = b["p"]
                if not prices:
                    continue
                c.execute(
                    """INSERT OR REPLACE INTO flight_daily
                    (from_city,to_city,depart_date,flight_key,cabin,day,
                     platform,n,lo,hi,open,close,fetched_max)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (from_city, to_city, depart_date, key, cabin, day,
                     platform, len(prices), min(prices), max(prices),
                     prices[0], prices[-1], max(b["at"])))
            # 航班日桶长期留存（400 天），避免只增不减
            c.execute("DELETE FROM flight_daily WHERE day < "
                      "date('now','localtime','-400 days')")

    def flight_history(self, from_city: str, to_city: str, depart_date: str,
                       flight_key: str, cabin: str, channels: list,
                       days: int) -> list:
        """航班日桶（升序）：[{day,platform,n,lo,hi,open,close,fetched_max}]。"""
        chans = [str(x) for x in (channels or []) if str(x)]
        if not chans:
            return []
        marks = ",".join("?" for _ in chans)
        sql = ("SELECT day,platform,n,lo,hi,open,close,fetched_max "
               "FROM flight_daily WHERE from_city=? AND to_city=? "
               "AND depart_date=? AND flight_key=? AND day>=date('now','localtime',?) "
               "AND platform IN (%s)" % marks)
        args = [from_city, to_city, depart_date, flight_key,
                "-%d days" % max(1, int(days))] + chans
        if cabin:
            sql += " AND cabin=?"
            args.append(cabin)
        sql += " ORDER BY day, platform"
        with self._conn() as c:
            c.execute("DELETE FROM flight_daily WHERE day < "
                      "date('now','localtime','-400 days')")
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def backfill_flight_daily(self, days: int = 14) -> int:
        """从现存 raw 明细回填航班日桶（一次性迁移/补历史）。"""
        with self._conn() as c:
            rows = c.execute(
                """SELECT DISTINCT from_city,to_city,depart_date,
                          substr(fetched_at,1,10) AS day
                   FROM flight_prices WHERE extra!='' AND fetched_at>=
                   datetime('now','localtime',?)""",
                ("-%d days" % max(1, int(days)),)).fetchall()
        for r in rows:
            try:
                self.refresh_flight_daily(r["from_city"], r["to_city"],
                                          r["depart_date"], r["day"])
            except Exception:
                continue
        return len(rows)

    def daily_series(self, from_city: str, to_city: str,
                     depart_date: str, days: int, th_d: float = 0.0,
                     kind: str = "d") -> list:
        """日桶序列（升序）：[{day:'MM-DD',n,lo,hi,open,close,avg,flag}]。
        flag 长窗值域 {2,-1,0}（口径备案见 refresh_daily；lo≤th=可
        出手日、th<lo≤th×1.1=擦边、线外=0，与全站档位色同语言——
        NEAR_RATIO 0.10 同值律）。读时惰性清 400 天外桶防膨胀。"""
        import datetime as _dt
        with self._conn() as c:
            c.execute(
                "DELETE FROM price_daily WHERE "
                "day < date('now','localtime','-400 days')")
            rows = c.execute(
                """SELECT day,n,lo,hi,open,close,avg FROM price_daily
                    WHERE from_city=? AND to_city=? AND depart_date=?
                      AND kind=? AND day>=date('now','localtime',?)
                    ORDER BY day""",
                (from_city, to_city, depart_date, kind,
                 f"-{int(days)} days")).fetchall()
        out = []
        near = 1.1
        for day, n, lo, hi, op, cl, avg in rows:
            if th_d and lo <= th_d:
                flag = 2
            elif th_d and th_d < lo <= th_d * near:
                flag = -1
            else:
                flag = 0
            out.append({"day": day[5:].replace("-", "-"), "n": n,
                        "lo": lo, "hi": hi, "open": op, "close": cl,
                        "avg": avg, "flag": flag})
        return out

    def save_special_deal(self, src: str, from_city: str, to_city: str,
                          depart_date: str, price: float, src_price: float,
                          ret_date: str = "", ret_price: float = 0.0):
        """特价核实留痕（控制台概览「特价雷达」卡数据源）：核实通过
        即记（含免打扰/无通道顺延形态——控制台可见性与推送正交）。"""
        from datetime import datetime
        with self._conn() as c:
            c.execute(
                """INSERT INTO special_deals
                (src,from_city,to_city,depart_date,ret_date,ret_price,
                 src_price,price,fetched_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (src, from_city, to_city, depart_date, ret_date or "",
                 ret_price or 0.0, src_price, price,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def recent_specials(self, limit: int = 10) -> list:
        """最近核实的特价（id 倒序=时间倒序；same-key 降价重推自然
        成多条，控制台按条展示真实时间线）。"""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT src,from_city,to_city,depart_date,ret_date,"
                "ret_price,src_price,price,fetched_at FROM special_deals "
                "ORDER BY id DESC LIMIT ?", (int(limit),))]

    def save_radar_run(self, user, query_key, status, note="", rows=0,
                       query=None, started_at="", finished_at=""):
        from datetime import datetime
        ts = finished_at or datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S")
        with self._conn() as c:
            c.execute(
                "INSERT INTO radar_runs (user,query_key,status,note,rows,"
                "query_json,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(user or ""), str(query_key or ""), str(status or ""),
                 str(note or ""), int(rows or 0),
                 json.dumps(query or {}, ensure_ascii=False),
                 str(started_at or ""), ts))
            c.execute("DELETE FROM radar_runs WHERE finished_at < "
                      "datetime('now','localtime','-400 days')")

    def save_radar_snapshot(self, user: str, query: dict, result: dict,
                            run_status: str = "ok", note: str = ""):
        """Persist one successful radar run; failures only hit radar_runs."""
        from datetime import datetime
        # 毫秒级：连续两次监控不能因同一秒而合并成一条走势点
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        qkey = self.radar_query_key(query)
        rows = []
        if run_status == "ok":
            for d in result.get("dates") or []:
                day = str(d.get("date") or "")[:10]
                if not day:
                    continue
                for ch, rec in (d.get("by_channel") or {}).items():
                    try:
                        price = float(rec.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if price <= 0:
                        continue
                    ti = rec.get("tax_included")
                    rows.append((
                        str(user or ""), str(query.get("from") or ""),
                        str(rec.get("to") or query.get("to") or ""),
                        1 if query.get("nationwide") else 0,
                        day, str(ch), price,
                        -1 if ti is None else (1 if ti else 0),
                        str(rec.get("basis") or ""),
                        str(rec.get("kind") or ""),
                        str(rec.get("link") or ""),
                        str(query.get("start") or ""),
                        str(query.get("end") or ""), qkey, now))
        self.save_radar_run(user, qkey, run_status, note,
                            len(rows), query=query, finished_at=now)
        if not rows:
            return 0
        with self._conn() as c:
            c.executemany(
                "INSERT INTO radar_snapshots (user,from_city,to_city,"
                "nationwide,depart_date,channel,price,tax_included,basis,"
                "kind,link,query_start,query_end,query_key,fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.execute("DELETE FROM radar_snapshots WHERE fetched_at < "
                      "datetime('now','localtime','-180 days')")
        return len(rows)

    def radar_history(self, user: str, days: int = 120,
                      query_key: str = "") -> dict:
        """Latest calendar + trend inside one query domain."""
        days = max(1, min(int(days or 120), 180))
        with self._conn() as c:
            if not query_key:
                r = c.execute(
                    "SELECT query_key FROM radar_runs WHERE user=? AND "
                    "status='ok' ORDER BY finished_at DESC,id DESC LIMIT 1",
                    (str(user or ""),)).fetchone()
                query_key = r[0] if r else ""
            if not query_key:
                r = c.execute(
                    "SELECT query_key FROM radar_snapshots WHERE user=? "
                    "AND query_key!='' ORDER BY fetched_at DESC,id DESC "
                    "LIMIT 1", (str(user or ""),)).fetchone()
                query_key = r[0] if r else ""
            if not query_key:
                r = c.execute(
                    "SELECT query_key FROM radar_runs WHERE user=? "
                    "ORDER BY finished_at DESC,id DESC LIMIT 1",
                    (str(user or ""),)).fetchone()
                query_key = r[0] if r else ""
            run = c.execute(
                "SELECT status,note,rows,query_json,finished_at "
                "FROM radar_runs WHERE user=? AND query_key=? "
                "ORDER BY finished_at DESC,id DESC LIMIT 1",
                (str(user or ""), query_key)).fetchone()
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM radar_snapshots WHERE user=? AND query_key=? "
                "AND fetched_at >= datetime('now','localtime',?) "
                "ORDER BY fetched_at, id",
                (str(user or ""), query_key, "-%d days" % days))]
        last_run = (dict(run) if run else None)
        if last_run and last_run.get("query_json"):
            try:
                last_run["query"] = json.loads(last_run["query_json"])
            except ValueError:
                last_run["query"] = {}
        if not rows:
            q = (last_run or {}).get("query") or {}
            return {"ok": True, "user": user, "dates": [], "series": [],
                    "snapshots": 0, "last_at": "", "query": q,
                    "query_key": query_key, "last_run": last_run}
        by_at = {}
        for r in rows:
            by_at.setdefault(r["fetched_at"], []).append(r)
        latest = {}
        prev = {}
        for at in sorted(by_at):
            for r in by_at[at]:
                key = (r["depart_date"], r["channel"])
                if key in latest:
                    prev[key] = latest[key]
                latest[key] = r
        dates = {}
        for (day, _ch), r in latest.items():
            cur = dates.get(day)
            if cur is None or float(r["price"]) < float(cur["price"]):
                dates[day] = r
        date_rows = []
        for day in sorted(dates):
            r = dates[day]
            _p = prev.get((day, r["channel"]))
            date_rows.append({
                "date": day, "price": float(r["price"]),
                "prev_price": (float(_p["price"]) if _p else None),
                "channel": r["channel"], "to": r["to_city"],
                "nationwide": bool(r["nationwide"]),
                "tax_included": (None if int(r["tax_included"]) < 0
                                 else bool(r["tax_included"])),
                "basis": r["basis"] or "", "kind": r["kind"] or "",
                "link": r["link"] or "", "fetched_at": r["fetched_at"]})
        series = []
        for at in sorted(by_at):
            best = min(by_at[at], key=lambda r: float(r["price"]))
            series.append({"at": at, "price": float(best["price"]),
                           "date": best["depart_date"],
                           "channel": best["channel"]})
        low = min(date_rows, key=lambda r: r["price"]) if date_rows else None
        first = rows[0]
        return {
            "ok": True, "user": user, "dates": date_rows,
            "series": series, "lowest": low,
            "snapshots": len(by_at), "last_at": rows[-1]["fetched_at"],
            "query_key": query_key, "last_run": last_run,
            "query": {"from": first["from_city"], "to": first["to_city"],
                      "nationwide": bool(first["nationwide"]),
                      "start": first["query_start"],
                      "end": first["query_end"],
                      "channels": sorted({r["channel"] for r in rows})},
        }

    def radar_alert_config(self, user):
        with self._conn() as c:
            r = c.execute(
                "SELECT enabled,drop_min,threshold,cooldown_h "
                "FROM radar_alert_cfg WHERE user=?", (str(user or ""),)
            ).fetchone()
        if not r:
            # 提醒是主动推送，默认关闭；用户在监控条件区显式开启。
            return {"enabled": False, "drop_min": 50.0,
                    "threshold": 0.0, "cooldown_h": 12.0}
        return {"enabled": bool(r[0]), "drop_min": float(r[1]),
                "threshold": float(r[2]), "cooldown_h": float(r[3])}

    def set_radar_alert_config(self, user, cfg):
        with self._conn() as c:
            c.execute(
                "INSERT INTO radar_alert_cfg "
                "(user,enabled,drop_min,threshold,cooldown_h) "
                "VALUES (?,?,?,?,?) ON CONFLICT(user) DO UPDATE SET "
                "enabled=excluded.enabled,drop_min=excluded.drop_min,"
                "threshold=excluded.threshold,cooldown_h=excluded.cooldown_h",
                (str(user or ""), 1 if cfg.get("enabled") else 0,
                 float(cfg.get("drop_min") or 0),
                 float(cfg.get("threshold") or 0),
                 float(cfg.get("cooldown_h") or 12)))

    def get_radar_alert_state(self, user, query_key, depart_date):
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM radar_alert_state WHERE user=? AND "
                "query_key=? AND depart_date=?",
                (str(user or ""), str(query_key or ""),
                 str(depart_date or ""))).fetchone()
        return dict(r) if r else None

    def save_radar_alert_state(self, user, query_key, depart_date,
                               low_price, low_at, low_channel, low_basis,
                               last_alert_price=None, last_alert_at="",
                               armed=1):
        with self._conn() as c:
            c.execute(
                "INSERT INTO radar_alert_state "
                "(user,query_key,depart_date,low_price,low_at,low_channel,"
                "low_basis,last_alert_price,last_alert_at,armed) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT"
                "(user,query_key,depart_date) DO UPDATE SET "
                "low_price=excluded.low_price,low_at=excluded.low_at,"
                "low_channel=excluded.low_channel,"
                "low_basis=excluded.low_basis,"
                "last_alert_price=excluded.last_alert_price,"
                "last_alert_at=excluded.last_alert_at,"
                "armed=excluded.armed",
                (str(user or ""), str(query_key or ""),
                 str(depart_date or ""), float(low_price),
                 str(low_at or ""), str(low_channel or ""),
                 str(low_basis or ""),
                 (None if last_alert_price is None
                  else float(last_alert_price)),
                 str(last_alert_at or ""), 1 if armed else 0))

    def record_radar_alert(self, user, query_key, depart_date, price,
                           prev_low, channel, basis, kind, link,
                           flights_json, status, err=""):
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO radar_alerts (user,query_key,depart_date,price,"
                "prev_low,channel,basis,kind,link,flights_json,status,err,"
                "sent_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(user or ""), str(query_key or ""),
                 str(depart_date or ""), float(price),
                 (None if prev_low is None else float(prev_low)),
                 str(channel or ""), str(basis or ""), str(kind or ""),
                 str(link or ""), str(flights_json or ""),
                 str(status or ""), str(err or ""), now))
            c.execute("DELETE FROM radar_alerts WHERE sent_at < "
                      "datetime('now','localtime','-180 days')")
            return int(cur.lastrowid)

    def radar_alerts(self, user, days=30):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM radar_alerts WHERE user=? AND sent_at >= "
                "datetime('now','localtime',?) ORDER BY id DESC",
                (str(user or ""), "-%d days" % max(1, int(days)))).fetchall()
        return [dict(r) for r in rows]

    def last_lowest(self, from_city: str, to_city: str, depart_date: str,
                    platform: Optional[str] = None) -> Optional[sqlite3.Row]:
        sql = ("SELECT * FROM flight_prices WHERE from_city=? AND to_city=? "
               "AND depart_date=?")
        args = [from_city, to_city, depart_date]
        if platform:
            sql += " AND platform=?"
            args.append(platform)
        sql += " ORDER BY price ASC LIMIT 1"
        with self._conn() as c:
            return c.execute(sql, args).fetchone()

    # ---- alert_state: 记录上次已推送价格，用于去抖 ----
    def get_alert_state(self, route_key: str) -> Optional[float]:
        with self._conn() as c:
            row = c.execute(
                "SELECT last_price FROM alert_state WHERE route_key=?",
                (route_key,),
            ).fetchone()
            return float(row["last_price"]) if row else None

    def set_alert_state(self, route_key: str, price: float):
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as c:
            c.execute(
                "INSERT INTO alert_state (route_key, last_price, last_sent_at) "
                "VALUES (?,?,?) ON CONFLICT(route_key) DO UPDATE SET "
                "last_price=excluded.last_price, last_sent_at=excluded.last_sent_at",
                (route_key, price, now),
            )

    def clear_alert_state(self, route_key: str):
        with self._conn() as c:
            c.execute("DELETE FROM alert_state WHERE route_key=?", (route_key,))
