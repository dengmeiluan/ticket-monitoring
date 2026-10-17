"""SQLite 价格存储"""
import os
import sqlite3
from datetime import datetime
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

    def save(self, fp: FlightPrice):
        with self._conn() as c:
            c.execute(
                """INSERT INTO flight_prices
                (platform, from_city, to_city, depart_date, price,
                 airline, flight_no, depart_time, arrive_time, fetched_at, extra)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (fp.platform, fp.from_city, fp.to_city, fp.depart_date, fp.price,
                 fp.airline, fp.flight_no, fp.depart_time, fp.arrive_time,
                 fp.fetched_at, fp.extra),
            )

    def save_many(self, prices: List[FlightPrice]):
        if not prices:
            return
        # 单连接批量写：一轮 5 渠道 × N 航线的逐行开连接合并为一次提交
        with self._conn() as c:
            c.executemany(
                """INSERT INTO flight_prices
                (platform, from_city, to_city, depart_date, price,
                 airline, flight_no, depart_time, arrive_time, fetched_at, extra)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [(p.platform, p.from_city, p.to_city, p.depart_date, p.price,
                  p.airline, p.flight_no, p.depart_time, p.arrive_time,
                  p.fetched_at, p.extra) for p in prices],
            )

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
