"""SQLite 价格存储"""
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import List, Optional

from .models import CAL_PATH_FAMILY, FlightPrice


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
                "note TEXT, evidence_level TEXT,"
                "attempt_id TEXT NOT NULL DEFAULT '')")
            pcols = {r[1] for r in c.execute(
                "PRAGMA table_info(fetch_paths)")}
            if "attempt_id" not in pcols:
                c.execute("ALTER TABLE fetch_paths ADD COLUMN "
                          "attempt_id TEXT NOT NULL DEFAULT ''")
            # 干预账本：每次"解除/预热/自检/去验证/补采"一条，回答
            # "干预后有没有真的恢复"，且重启不丢（rt["scene"] 是内存态）。
            c.execute(
                "CREATE TABLE IF NOT EXISTS interventions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "at TEXT NOT NULL, platform TEXT NOT NULL,"
                "action TEXT NOT NULL, ok INTEGER NOT NULL DEFAULT 0,"
                "rows INTEGER DEFAULT 0, scope TEXT DEFAULT '',"
                "before TEXT DEFAULT '', after TEXT DEFAULT '',"
                "note TEXT DEFAULT '', ms INTEGER DEFAULT 0)")

    def save_intervention(self, platform, action, ok=False, rows=0,
                          scope="", before="", after="", note="", ms=0,
                          at=""):
        """记录一次干预及其结果（成功/失败、前后状态、耗时）。

        返回是否真的写进去了（r612）。所有调用点都是
        `try: save_intervention(...) except Exception: pass`——账本写失败
        （只读库、表缺失、锁超时）会**静默**消失，界面表现成「这次干预
        没发生过」，而干预恰恰是最需要事后可溯源的一类操作。
        这里不再让失败无声：异常照旧抛给调用方的 try/except（不改控制流），
        但先在日志里留一条，至少事后能查到「这次没记上」。
        """
        from datetime import datetime
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO interventions (at,platform,action,ok,rows,"
                    "scope,before,after,note,ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (str(at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                     str(platform or ""), str(action or ""), 1 if ok else 0,
                     int(rows or 0), str(scope or ""), str(before or "")[:400],
                     str(after or "")[:400], str(note or "")[:400],
                     int(ms or 0)))
            return True
        except Exception as e:
            try:
                import logging
                logging.getLogger("storage").warning(
                    "[干预账] 写入失败（这条干预不会出现在溯源里）："
                    "%s %s · %s: %s", platform, action, type(e).__name__, e)
            except Exception:
                pass
            raise

    def intervention_effect(self, platform, hours=24):
        """干预前后成功率对比：回答"干预到底有没有把渠道救回来"。

        以该渠道最近一次干预时间为分界：
          前 24h：干预前同窗口的路径成功率
          后 24h：干预后到现在的路径成功率（样本不足如实返回 None）

        分域对比（r512）：渠道级数字答不出「国际自检之后**国际通路**
        恢复没有」——国内正常、国际全挂时，渠道级 before/after 都接近
        1.0，看起来这次干预毫无意义。而自检按钮本来就是按域点的。
        因此当这次干预的 `scope` 是 dom/intl 时，额外给出该域的
        `scope_before/scope_after`（同一分界、同一窗口）。判别口径与
        `path_stats` 完全一致（`is_intl_route`），不另造一套。
        scope 不是域（如 relogin 的槽位名）时不返回该组字段——不猜。
        """
        with self._conn() as c:
            # 只用**人工干预**当分界：auto_trip 等自动事件现在也入账，
            # 拿它当分界会把用户上一次手动干预的前后对比冲掉——而
            # 「我手动救过之后好了没有」正是这个接口要回答的。
            iv = c.execute(
                "SELECT at, action, ok, scope FROM interventions "
                "WHERE platform=? "
                "AND substr(action,1,5) <> 'auto_' "
                "ORDER BY id DESC LIMIT 1", (str(platform),)).fetchone()
            if not iv:
                return {"ok": True, "platform": platform, "has": False}
            at = str(iv["at"] or "")
            sc = str(iv["scope"] or "").strip().lower()
            # 分域判定单源（r618）：趋势、scope_before/after 共用这一份，
            # 与 path_stats / intervention_success_rate 同一个函数。
            try:
                from core.intl import is_intl_route as _is_intl
            except Exception:
                _is_intl = lambda _a, _b: False

            def _rate(where, params):
                row = c.execute(
                    "SELECT SUM(CASE WHEN path_status IN ('ok','calendar') "
                    "THEN 1 ELSE 0 END) AS ok, COUNT(*) AS n "
                    "FROM fetch_paths WHERE platform=? AND " + where,
                    params).fetchone()
                n = int(row["n"] or 0)
                return (round(int(row["ok"] or 0) / n, 4) if n else None), n
            before, bn = _rate(
                "fetched_at < ? AND fetched_at >= datetime(?, ?)",
                (str(platform), at, at,
                 "-%d hours" % max(1, int(hours))))
            # 干预后也只取同样长的窗口（r610）：原先写 `fetched_at >= ?`
            # 一路统计到**现在**，干预越久样本越多——实测「干预后 24h 全成功、
            # 之后 8 天全失败」被算成 1/100=10%，读作「这次干预没用」，
            # 而它其实当场就生效了。两段必须同窗口才可比。
            after, an = _rate(
                "fetched_at >= ? AND fetched_at < datetime(?, ?)",
                (str(platform), at, at, "+%d hours" % max(1, int(hours))))
            # 一致性不是"一次性通了"，而是"之后还一直通"。给出
            # 干预后每 30 分钟窗口的成功率序列，供面板画小趋势/判断回落。
            # 分域口径（r618）：这次干预是针对 dom/intl 的，趋势就必须是
            # 那个域的——否则「本次干预针对：国际域 0%（4）→ 0%（4）」
            # 下面会挂着国内每窗 100% 的趋势，`regressed` 也跟着国内的
            # 好坏翻。与 r512 的 scope_before/scope_after 同一分域函数。
            want_intl = (sc == "intl") if sc in ("dom", "intl") else None
            trend = []
            try:
                rows2 = c.execute(
                    "SELECT (CAST(strftime('%s', fetched_at) AS INTEGER) - "
                    "CAST(strftime('%s', ?) AS INTEGER)) / 1800 AS bucket, "
                    "from_city, to_city, path_status "
                    "FROM fetch_paths WHERE platform=? AND fetched_at >= ? "
                    "ORDER BY fetched_at",
                    (at, str(platform), at)).fetchall()
                buckets = {}
                order = []
                for r in rows2:
                    if want_intl is not None:
                        try:
                            if bool(_is_intl(r["from_city"],
                                             r["to_city"])) != want_intl:
                                continue
                        except Exception:
                            continue
                    b = int(r["bucket"] or 0)
                    if b not in buckets:
                        buckets[b] = [0, 0]
                        order.append(b)
                    buckets[b][1] += 1
                    if str(r["path_status"] or "") in ("ok", "calendar"):
                        buckets[b][0] += 1
                for b in sorted(order):
                    ok2, n2 = buckets[b]
                    trend.append({
                        "bucket": b,
                        "rate": (round(ok2 / n2, 3) if n2 else None),
                        "n": n2})
                # 桶数上限与旧实现一致（D 段文档契约钉在 `LIMIT 16` 字面量上）。
                # 分域过滤发生在取数之后，SQL 无法直接表达 is_intl_route，
                # 所以截断放在这里；语义仍是「取最早的 16 个 30 分钟桶」。
                trend = trend[:16]
            except Exception:
                trend = []            # 回落判定：干预后曾有 ≥70% 的窗口，最后一个窗口 <40%
            regressed = False
            if trend:
                _seen_ok = any((t["rate"] or 0) >= 0.7 for t in trend)
                _last = trend[-1]["rate"]
                regressed = bool(_seen_ok and _last is not None
                                 and _last < 0.4)
            out = {"ok": True, "platform": platform, "has": True,
                   "at": at, "action": str(iv["action"] or ""),
                   "iv_ok": bool(iv["ok"]),
                   "before": before, "before_n": bn,
                   "after": after, "after_n": an,
                   "trend": trend, "regressed": regressed}
            # 采集是否已经停了（r514）：`after is None` 有两种完全不同的原因——
            # 「刚干预完，还没轮到采集」和「采集压根没在跑」。真实库 10-29
            # fliggy 重登 103 次、`after_n` 恒为 0，而当天 fetch_paths 一条
            # 都没有（最后一条停在 10-28 14:34）。面板只写「干预后还没有新
            # 样本」，读者会一直等一个不会来的样本，而不是去看采集为什么停。
            # 判据用**该渠道**最近一条样本的时间：整库暂停与单渠道停摆是
            # 两件事，只有前者才说明「整个采集挂了」。
            try:
                _last = c.execute(
                    "SELECT MAX(fetched_at) AS m FROM fetch_paths "
                    "WHERE platform=?", (str(platform),)).fetchone()
                _last_at = str((_last or {})["m"] or "") if _last else ""
            except Exception:
                _last_at = ""
            out["last_sample_at"] = _last_at
            # 时间解析复用 pacing 的那一份（同一格式、同一异常口径），
            # 不在这里再造一套 strptime。**不要在这里吞异常**（r514 踩过）：
            # 本模块原先没有 `import time`，`except Exception` 把 NameError
            # 一起吞掉，`_age_h` 恒为 0，`stalled` 永远是 False——功能上线
            # 即静默失效，而测试只看「字段存在」时会全绿。
            from core.pacing import _age_min as _am
            _age_h = ((_am(_last_at, time.time()) or 0.0) / 60.0
                      if _last_at else 0.0)
            # 「停摆」= 该渠道最近一条样本**早于这次干预**且已经过去 2 小时以上。
            # 用 `_last_at < at` 而不是 `after_n == 0`：后者在「干预后还没轮到
            # 采集」时也是 0，而那只是正常等待，不该报警。
            out["stalled"] = bool(
                _last_at and _last_at < at and _age_h >= 2)
            out["stalled_hours"] = (round(_age_h, 1)
                                    if out["stalled"] else None)
            # 分域前后对比（r512）：只在这次干预的 scope 确实是域时才给。
            # 判定用 is_intl_route —— 与 path_stats 的分域口径同源。
            if sc in ("dom", "intl"):
                want = (sc == "intl")
                # 取前窗下界到现在：一条查询覆盖 before/after 两段，
                # 再在 Python 里按 at 切分——与渠道级 _rate 的窗口一致。
                try:
                    from datetime import datetime as _dt
                    from datetime import timedelta as _td
                    _floor = (_dt.strptime(at, "%Y-%m-%d %H:%M:%S")
                              - _td(hours=max(1, int(hours)))
                              ).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    _floor = ""
                _rows = c.execute(
                    "SELECT from_city, to_city, fetched_at, path_status "
                    "FROM fetch_paths WHERE platform=? AND fetched_at >= ?",
                    (str(platform), _floor)).fetchall()
                _pairs = []
                for r in _rows:
                    try:
                        if bool(_is_intl(r["from_city"], r["to_city"])) != want:
                            continue
                    except Exception:
                        continue
                    _pairs.append((str(r["fetched_at"] or ""),
                                   str(r["path_status"] or "")))
                _fb = [(ts, st) for ts, st in _pairs if ts < at]
                _fa = [(ts, st) for ts, st in _pairs if ts >= at]
                _bok = sum(1 for _t2, s2 in _fb
                           if s2 in ("ok", "calendar"))
                _aok = sum(1 for _t2, s2 in _fa
                           if s2 in ("ok", "calendar"))
                out["scope"] = sc
                out["scope_before"] = (round(_bok / len(_fb), 4)
                                       if _fb else None)
                out["scope_before_n"] = len(_fb)
                out["scope_after"] = (round(_aok / len(_fa), 4)
                                      if _fa else None)
                out["scope_after_n"] = len(_fa)
            return out

    def intervention_success_rate(self, hours=24 * 7):
        """干预成功率：按动作统计「按了之后真的恢复出数」的比例。

        回答的是**选哪个按钮**，而不是「上一次干预效果如何」
        （后者由 intervention_effect 回答）。实测缺口：面板能说
        「上次自检 44%→100%」，但说不清「自检类干预一共 12 次，
        几次真的把渠道救回来了」——这正是决定优先按哪个钮的依据。

        判据（只用时间先后，不做语义猜测）：
          对每次人工干预 I（排除 auto_*），生效窗口为
          [I.at, 同渠道下一次人工干预) ∩ [I.at, I.at+N 小时]。窗口内出现
          ok/calendar 路径样本即记为有效（healed）。
          右界必须有 N 小时封顶（r611）：判定是 `any(ok)`，窗口越宽越容易
          命中某次偶然成功——实测「干预后 24h 全失败、20 天后偶然成功」
          被记为 healed=1 / rate=1.0，成功率被系统性高估。
        窗口内**一条路径样本都没有**时不计入分母：干预刚做完还没采集，
        不是失败，只是还不能判断——算成失败会把成功率压成噪声。

        但**也不能整条丢掉**（r506）：真实库 10-29 有 92 次重登、当天
        零条采集样本，旧实现直接把 relogin 从结果里抹掉——面板只剩
        「自检 / 解除」，用户无法区分「没按过重登」与「按了但还判不了」。
        这类窗口单独计入 `unjudged`，由界面明说「尚无采集样本」。

        作用域维度（r511）：账本早就分域记了 `scope`（实测 probe 有
        **intl 7 次 / dom 2 次**），但这里只按动作聚合，于是答不出
        「国际自检救回几次、国内自检救回几次」——而面板上的自检按钮
        恰恰是按域选的（自动/国内/国际），操作者需要知道该选哪一域。
        现在每个动作额外带 `scopes` 子表（**只收非空 scope**；空 scope
        只进总数，不编一个「全端」桶出来）。动作级字段口径**一字不变**，
        老消费方（脚本/推送）不受影响。
        """
        hours = max(1, min(24 * 90, int(hours or 24 * 7)))
        with self._conn() as c:
            ivs = c.execute(
                "SELECT id, at, platform, action, scope FROM interventions "
                "WHERE substr(action,1,5) <> 'auto_' "
                "AND at >= datetime('now','localtime', ?) "
                "ORDER BY platform, id", ("-%d hours" % hours,)).fetchall()
            if not ivs:
                return {}
            oldest = min(str(r["at"] or "") for r in ivs)
            samples = c.execute(
                "SELECT platform, from_city, to_city, fetched_at, "
                "path_status FROM fetch_paths "
                "WHERE fetched_at >= ? ORDER BY platform, fetched_at",
                (oldest,)).fetchall()
        by_plat = {}
        # 分域判定要的航线，按 (渠道, 采样时刻) 索引（r617）。同一渠道同一
        # 秒可能有多条不同航线，这里保留第一条即可：只用来判断「这条样本
        # 属国内还是国际」，而一次采样在分域上不会自相矛盾。
        route_of = {}
        for s in samples:
            plat_k = str(s["platform"] or "")
            ts_k = str(s["fetched_at"] or "")
            by_plat.setdefault(plat_k, []).append(
                (ts_k, str(s["path_status"] or "")))
            route_of.setdefault(
                (plat_k, ts_k),
                (str(s["from_city"] or ""), str(s["to_city"] or "")))
        # 与 path_stats / intervention_effect 同一个分域口径（r512 同源）。
        try:
            from core.intl import is_intl_route as _is_intl
        except Exception:
            _is_intl = lambda _a, _b: False

        # 每个渠道的下一次人工干预时刻，作为窗口右边界（不含）。
        # 不按 scope 拆边界：任何一次人工干预都会改动会话状态，前一窗
        # 必须在那一刻结束，否则「重登后的成功」会算到更早的自检头上。
        nxt = {}
        plat_ivs = {}
        for r in ivs:
            plat_ivs.setdefault(str(r["platform"] or ""), []).append(
                (str(r["at"] or ""), str(r["action"] or ""),
                 str(r["scope"] or "").strip()))
        for plat, seq in plat_ivs.items():
            for i, (at, _act, _sc) in enumerate(seq):
                nxt[(plat, i)] = seq[i + 1][0] if i + 1 < len(seq) else ""

        def _new():
            return {"n": 0, "healed": 0, "unhealed": 0, "unjudged": 0}

        def _new_with_scopes():
            d = _new()
            d["scopes"] = {}
            return d

        out = {}
        for plat, seq in plat_ivs.items():
            rows = by_plat.get(plat) or []
            for i, (at, act, scope) in enumerate(seq):
                end = nxt[(plat, i)]
                # 窗口右边界还有「干预后 N 小时」（r611）：原实现最后一次
                # 干预的 end 为空，窗口一路延伸到 now——而判定是
                # `any(ok)`，「窗口里有任意一次成功就算治好」。实测
                # 「干预后 24h 全失败、20 天后偶然成功一次」被记为
                # healed=1 / rate=1.0，成功率被系统性高估。
                # 有下一次干预时仍是「到下一次干预为止」（更早），
                # 没有时封顶在 N 小时，与 intervention_effect 同口径。
                cap = (datetime.strptime(at, "%Y-%m-%d %H:%M:%S")
                       + timedelta(hours=max(1, int(hours)))
                       ).strftime("%Y-%m-%d %H:%M:%S")
                right = min(end, cap) if end else cap
                win = [(ts, st) for ts, st in rows
                       if at <= ts < right]
                d = out.setdefault(act, _new_with_scopes())
                # 作用域子表（r617）：dom/intl 是**航线域**，判定必须只看
                # 该域的样本。原实现直接把渠道级的 win 记进子表，于是
                # 「国际自检」与「国内自检」拿到的是同一份数字——国内全绿、
                # 国际全红时两个域都报 100%，而面板正是靠这两个数决定
                # 该选哪一域自检。非域名（重登槽位名等）不做域过滤。
                srow = None
                if scope in ("dom", "intl"):
                    want = (scope == "intl")
                    srow = []
                    for ts, st in win:
                        pair = route_of.get((plat, ts))
                        if pair is None:
                            continue
                        try:
                            if bool(_is_intl(pair[0], pair[1])) != want:
                                continue
                        except Exception:
                            continue
                        srow.append((ts, st))
                # 作用域子表：只收非空 scope（空 scope 只进动作级总数）
                sd = (d["scopes"].setdefault(scope, _new())
                      if scope else None)
                if not win:
                    # 判不了 ≠ 没发生：只累加 unjudged，不进 n 的分母。
                    d["unjudged"] += 1
                    if sd is not None:
                        sd["unjudged"] += 1
                    continue
                healed = any(st in ("ok", "calendar") for _ts, st in win)
                d["n"] += 1
                d["healed" if healed else "unhealed"] += 1
                if sd is not None:
                    if srow is None:
                        # 非域名：与动作级同口径（渠道全部样本）
                        sd["n"] += 1
                        sd["healed" if healed else "unhealed"] += 1
                    elif not srow:
                        # 该域窗口内零样本：判不了，不能拿别的域顶替
                        sd["unjudged"] += 1
                    else:
                        s_healed = any(st in ("ok", "calendar")
                                       for _ts, st in srow)
                        sd["n"] += 1
                        sd["healed" if s_healed else "unhealed"] += 1

        def _finish(x):
            x["rate"] = (round(x["healed"] / x["n"], 4) if x["n"] else None)
            # 可靠性标记（r486）：n=1 时的 1.0 与 n=12 时的 1.0 不是一回事。
            # 面板已按 n<3 只说「样本不足」，但 API 直接吐 1.0 会让任何
            # 别的消费方（脚本/推送/二次开发）当真。这里显式标注，
            # 让「能不能引用这个比率」成为数据自带的事实，而不是调用方的约定。
            x["reliable"] = x["n"] >= 3

        for d in out.values():
            for sd in (d.get("scopes") or {}).values():
                _finish(sd)
            _finish(d)
        return out

    def interventions(self, platform="", limit=20):
        """最近 N 条干预，按时间倒序（可观测：干预是否真的有效）。"""
        limit = max(1, min(200, int(limit or 20)))
        with self._conn() as c:
            if platform:
                rows = c.execute(
                    "SELECT * FROM interventions WHERE platform=? "
                    "ORDER BY id DESC LIMIT ?", (str(platform), limit)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM interventions ORDER BY id DESC LIMIT ?",
                    (limit,)).fetchall()
        return [dict(r) for r in rows]

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
                        evidence_level="path", attempt_id=""):
        from datetime import datetime
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status,request_url,"
                "http_status,rows,note,evidence_level,attempt_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 str(platform or ""), str(from_city or ""),
                 str(to_city or ""), str(depart_date or ""),
                 str(entry_path or ""), str(path_status or ""),
                 str(request_url or ""), int(http_status or 0),
                 int(rows or 0), str(note or ""),
                 str(evidence_level or "path"), str(attempt_id or "")))
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

    def recent_paths(self, platform="", limit=10):
        """溯源：某渠道最近 N 条采集尝试（时间/入口/状态/证据）。"""
        limit = max(1, min(100, int(limit or 10)))
        plat = str(platform or "").strip()
        with self._conn() as c:
            if plat:
                rows = c.execute(
                    "SELECT * FROM fetch_paths WHERE platform=? "
                    "ORDER BY id DESC LIMIT ?", (plat, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM fetch_paths ORDER BY id DESC LIMIT ?",
                    (limit,)).fetchall()
        return [dict(r) for r in rows]

    def path_stats(self, hours=24):
        """路径账聚合：platform × 入口 × 域（国内/国际）→ 尝试/成功。

        - `rate` 是路径尝试口径（含日历）；`detail_rate` 只算真实明细；
        - `query_rate` 是「一次查询只要有一条路径出数就算成功」的查询口径，
          用于渠道级健康惩罚——H5 被拦、PC 兜底成功时不能把整家渠道判死；
        - `last_at` 是最近一次尝试，`last_ok_at` 才是数据新鲜度。
        """
        hours = max(1, min(24 * 90, int(hours or 24)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT platform, entry_path, path_status, from_city, "
                "to_city, depart_date, attempt_id, fetched_at "
                "FROM fetch_paths "
                "WHERE fetched_at >= datetime('now','localtime', ?) "
                "ORDER BY id", ("-%d hours" % hours,)).fetchall()
        try:
            from core.intl import is_intl_route
        except Exception:
            is_intl_route = lambda _a, _b: False

        def new_node():
            return {"paths": {}, "attempts": 0, "ok": 0, "detail_ok": 0,
                    "calendar_ok": 0, "blocked": 0, "soft": 0,
                    "empty": 0, "unsupported": 0, "login": 0, "error": 0,
                    "rate": 0.0, "detail_rate": 0.0, "rate_excl_empty": 0.0,
                    "query_attempts": 0, "query_ok": 0,
                    "query_detail_ok": 0, "query_calendar_only": 0,
                    "query_rate": 0.0, "last_at": "", "last_ok_at": "",
                    "last_login_at": "", "login_since_ok": 0}

        def new_path():
            return {"attempts": 0, "ok": 0, "detail_ok": 0, "calendar_ok": 0,
                    "blocked": 0, "soft": 0, "empty": 0, "unsupported": 0,
                    "login": 0, "error": 0,
                    "rate": 0.0, "rate_excl_empty": 0.0,
                    "detail_rate": 0.0, "last_at": "", "last_ok_at": "",
                    "last_login_at": "", "login_since_ok": 0}

        def bump(node, status, last):
            node["attempts"] += 1
            if status in ("ok", "calendar"):
                node["ok"] += 1
                # 出数即清零：之后若再被登录墙拦，才是「重登后又不通了」
                node["login_since_ok"] = 0
                if status == "ok":
                    node["detail_ok"] += 1
                else:
                    node["calendar_ok"] += 1
                if last > node["last_ok_at"]:
                    node["last_ok_at"] = last
            elif status == "blocked":
                node["blocked"] += 1
            elif status == "soft_reject":
                # 软拒不是"真无票"也不是"硬拒绝"：单列，避免污染
                # empty/error 两种语义，也不进熔断证据。
                node["soft"] += 1
            elif status == "empty":
                node["empty"] += 1
            elif status == "unsupported":
                # 能力边界（非法航线/超窗/往返无源）：既不是失败也不是
                # 无票，单列——并进 error 会让"渠道本来就不支持"永远像
                # 一条坏掉的路（往返航线会被反复判劣化）。
                node["unsupported"] = int(node.get("unsupported") or 0) + 1
            elif status == "login":
                # 登录墙单列（r397）：并进 error 会把"需要人工重登"混进
                # "网络/解析/超时失败"，而两者处置完全不同——重登能解，
                # 重试不能。实测同程 24h 53 条 444 历史 login 行让渠道
                # 错误率显示成 40%，而它根本没有网络故障。
                node["login"] = int(node.get("login") or 0) + 1
                node["login_since_ok"] = int(
                    node.get("login_since_ok") or 0) + 1
                # 最近一次登录墙时间（r479）：重登后要判断「这次墙是不是
                # 重登之前的旧账」。只按计数会永远停在 login（24h 窗口里
                # 的旧行不会消失），用户刚登完又被要求再登一次。
                if last > str(node.get("last_login_at") or ""):
                    node["last_login_at"] = last
            else:
                node["error"] += 1
            if last > node["last_at"]:
                node["last_at"] = last

        def finish(node):
            node["rate"] = (round(node["ok"] / node["attempts"], 4)
                            if node["attempts"] else 0.0)
            node["detail_rate"] = (round(node["detail_ok"] / node["attempts"], 4)
                                   if node["attempts"] else 0.0)
            # 售罄空结果不是"路径坏了"：分母里剔除 empty，避免把真无票
            # 误判成路径劣化，进而错误降频整家渠道。unsupported 同理
            # （渠道能力边界，不是失败）。
            _den = max(0, node["attempts"] - node["empty"]
                       - int(node.get("unsupported") or 0))
            # None = 没有有效样本（全是售罄空），不是 0% 失败
            node["rate_excl_empty"] = (round(node["ok"] / _den, 4)
                                       if _den else None)
            node["query_rate"] = (
                round(node["query_ok"] / node["query_attempts"], 4)
                if node["query_attempts"] else 0.0)
            for p in node["paths"].values():
                p["rate"] = (round(p["ok"] / p["attempts"], 4)
                             if p["attempts"] else 0.0)
                p["detail_rate"] = (
                    round(p["detail_ok"] / p["attempts"], 4)
                    if p["attempts"] else 0.0)
                _d2 = max(0, p["attempts"] - p["empty"]
                          - int(p.get("unsupported") or 0))
                p["rate_excl_empty"] = (round(p["ok"] / _d2, 4)
                                        if _d2 else None)

        out = {}
        queries = {}
        for r in rows:
            plat = str(r["platform"] or "")
            path = str(r["entry_path"] or "?")
            st = str(r["path_status"] or "")
            last = str(r["fetched_at"] or "")
            scope = ("intl" if is_intl_route(r["from_city"], r["to_city"])
                     else "dom")
            node = out.setdefault(plat, new_node())
            node.setdefault("scopes", {"dom": new_node(), "intl": new_node()})
            node["paths"].setdefault(path, new_path())
            node["scopes"][scope]["paths"].setdefault(path, new_path())
            bump(node, st, last)
            bump(node["paths"][path], st, last)
            bump(node["scopes"][scope], st, last)
            bump(node["scopes"][scope]["paths"][path], st, last)
            aid = str(r["attempt_id"] or "")
            if aid:
                q = queries.setdefault((plat, aid), {
                    "scope": scope, "ok": False, "detail": False,
                    "calendar": False, "paths": set()})
                q["ok"] = q["ok"] or st in ("ok", "calendar")
                q["detail"] = q["detail"] or st == "ok"
                q["calendar"] = q["calendar"] or st == "calendar"
                q["paths"].add(path)

        for (plat, _aid), q in queries.items():
            node = out.get(plat) or {}
            scope = (node.get("scopes") or {}).get(q["scope"])
            for target in (node, scope):
                if not target:
                    continue
                target["query_attempts"] += 1
                if q["ok"]:
                    target["query_ok"] += 1
                if q["detail"]:
                    target["query_detail_ok"] += 1
                elif q["calendar"]:
                    target["query_calendar_only"] += 1

        # 「在用路径」口径（r406）：退役的旧通路不该拖低渠道健康度。
        #
        # 背景：同程 r384 把国际通路从「日历」换成「窗历」后，旧「日历」
        # 恒 444 但 24h 窗口里仍留着 35 次历史查询（全部失败）。渠道查询
        # 成功率因此显示 63.5%，而**在用的两条路（窗历 54/54、H5 7/7）
        # 都是 100%**——一个已经不存在的入口，把一条健康的渠道说成了
        # 三分之二坏。
        #
        # 判据（只用时间先后 + 是否还有产出，不做语义猜测）：
        #   路径 P 已淘汰 ⇔ ① 窗口内 **一次都没成功**；
        #                  ② 存在另一条路 Q，Q 的最后尝试晚于 P；
        #                  ③ Q 在窗口内有过成功（确实接住了活）。
        #
        # ① 是关键：只要 P 还在出数，无论 Q 多新，P 都没退役。
        # 第一版漏了这条，把**携程 PC（24h 成功 129 次）**误判成淘汰——
        # 它只是最近一次尝试比 H5 早几分钟而已。
        def _retired_paths(paths):
            obs = {}
            for name, v in (paths or {}).items():
                la = str(v.get("last_at") or "")
                if not la:
                    continue
                obs[name] = (la, int(v.get("ok") or 0) > 0)
            dead = set()
            for name, (la, ok_a) in obs.items():
                if ok_a:
                    continue                      # ① 还在出数 → 不退役
                for other, (lb, ok_b) in obs.items():
                    if other != name and ok_b and lb > la:   # ②③
                        dead.add(name)
                        break
            return dead

        def _live(node):
            """按在用路径重算查询口径：只计"至少走过一条在用路径"的查询。

            一次查询可能同时留下多条路径的记录（H5 失败→API 兜底）。
            若该次查询走到的路径**全部**已淘汰，这次查询整体不计；否则
            算作一次在用查询（成功与否按原判定）。
            """
            dead = _retired_paths(node.get("paths") or {})
            if not dead:
                return None
            qa = qo = qd = qc = 0
            for (_p, _aid), q in _queries_by_plat.get(id(node), []):
                live_hit = bool(set(q["paths"]) - dead)
                if not live_hit:
                    continue
                qa += 1
                if q["ok"]:
                    qo += 1
                if q["detail"]:
                    qd += 1
                elif q["calendar"]:
                    qc += 1
            return {"query_attempts": qa, "query_ok": qo,
                    "query_detail_ok": qd, "query_calendar_only": qc,
                    "query_rate": (round(qo / qa, 4) if qa else None)}

        _queries_by_plat = {}
        for (plat, aid), q in queries.items():
            node = out.get(plat)
            if node is None:
                continue
            _queries_by_plat.setdefault(id(node), []).append(
                ((plat, aid), q))
            sc = (node.get("scopes") or {}).get(q["scope"])
            if sc is not None:
                _queries_by_plat.setdefault(id(sc), []).append(
                    ((plat, aid), q))

        for node in out.values():
            finish(node)
            for sc in (node.get("scopes") or {}).values():
                finish(sc)
            # 在用口径挂在节点上，供 UI/建议优先采用；原口径保留可对照。
            for target in [node] + list((node.get("scopes") or {}).values()):
                dead = _retired_paths(target.get("paths") or {})
                target["retired_paths"] = sorted(dead)
                live = _live(target) if dead else None
                target["query_rate_live"] = (
                    (live or {}).get("query_rate")
                    if live else target.get("query_rate"))
                target["query_attempts_live"] = (
                    (live or {}).get("query_attempts")
                    if live else target.get("query_attempts"))
        # 不限窗口的最近样本时刻（r516）：`last_at` 只统计窗口内的记录，
        # 当整个窗口为空（采集停了很久）时 out 甚至是**空 dict**——于是
        # 「采集停了」会被误判成「新装、还没有第一轮」。这里单独查一次
        # 全表 MAX，并**同时覆盖窗口内没有记录的渠道**（全红场景）。
        try:
            with self._conn() as c2:
                rows = c2.execute(
                    "SELECT platform, MAX(fetched_at) AS m FROM fetch_paths "
                    "GROUP BY platform").fetchall()
                seen = {str(r["platform"] or ""): str(r["m"] or "")
                        for r in rows}
            for plat in set(list(out.keys()) + list(seen.keys())):
                if plat not in out:
                    continue                 # 不认识的历史渠道不凭空造节点
                out[plat]["last_seen_at"] = seen.get(plat, "")
        except Exception:
            for plat in out.keys():
                out[plat].setdefault("last_seen_at", "")
        return out

    def failure_recurrence(self, hours=24, min_count=3):
        """同一渠道×入口×状态反复出现 → 可跟踪的"复发问题"。

        连续零数据告警要等 3 轮（可能 90 分钟）；而"同一类失败在 24h 里
        出现 N 次"能更早指出根因（如 444 反复、1999 反复）。
        只统计非成功状态，并按最近一次时间倒序。
        """
        hours = max(1, min(24 * 90, int(hours or 24)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT platform, entry_path, path_status, COUNT(*) n, "
                "MAX(fetched_at) last_at, "
                "MIN(fetched_at) first_at, "
                "from_city, to_city "
                "FROM fetch_paths "
                "WHERE fetched_at >= datetime('now','localtime', ?) "
                "AND path_status NOT IN ('ok','calendar') "
                "GROUP BY platform, entry_path, path_status, "
                "from_city, to_city "
                "HAVING COUNT(*) >= ? ORDER BY n DESC",
                ("-%d hours" % hours, int(min_count))).fetchall()
            # 每个复发组合附最近一条现场：证据可直接点开对照，不用再翻日志
            evidence = {}
            for r in rows:
                try:
                    er = c.execute(
                        "SELECT request_url, http_status, note, rows, "
                        "fetched_at FROM fetch_paths WHERE platform=? AND "
                        "entry_path=? AND path_status=? AND "
                        "COALESCE(from_city,'')=? AND COALESCE(to_city,'')=? "
                        "ORDER BY id DESC LIMIT 1",
                        (r["platform"], r["entry_path"], r["path_status"],
                         r["from_city"] or "", r["to_city"] or "")).fetchone()
                except Exception:
                    er = None
                if er:
                    evidence[(r["platform"], r["entry_path"],
                              r["path_status"], r["from_city"] or "",
                              r["to_city"] or "")] = dict(er)
        # 历史行用旧口径写进库（444 曾被记成 login）。证据自证：
        # note 含 444/非法链接/202 的 login 行实际是会话软拒，展示时按
        # soft 归类，避免"登录态失效×53，证据却是 code=444"的自相矛盾。
        # 同理"原站无符合条件的航班"在 r382 已判 empty（真无票不是登录
        # 失效），历史 login 行按 empty 展示——否则复发面板会把 40 次
        # 无票说成"登录失效（需人工）"，把用户推去做无用重登。
        _SOFT_NOTE = ("444", "非法链接", "202")
        _EMPTY_NOTE = ("无符合条件的航班", "未查询到", "没有查询到")
        # r385 受控 A/B 定谳：1999 单次是"间歇放行"，同会话未重登即自愈
        # ——历史 login 行证据写的是 1999 的，展示时按 soft 归类。否则面板
        # 一直挂"登录态失效（需人工）"催人去重登，而那条路 1.5 分钟自愈。
        _SOFT_1999 = ("1999",)
        out = []
        for r in rows:
            st = str(r["path_status"] or "")
            _fr = str(r["from_city"] or "")
            _to = str(r["to_city"] or "")
            _ev0 = evidence.get((r["platform"], r["entry_path"], st,
                                 _fr, _to)) or {}
            _nt = str(_ev0.get("note") or "")
            if st == "login" and any(k in _nt for k in _SOFT_NOTE):
                st = "soft_reject"
            elif st == "login" and any(k in _nt for k in _SOFT_1999):
                st = "soft_reject"
            elif st == "login" and any(k in _nt for k in _EMPTY_NOTE):
                st = "empty"
            out.append({
                "platform": str(r["platform"] or ""),
                "path": str(r["entry_path"] or ""),
                "route": ("%s→%s" % (_fr, _to)) if _fr or _to else "",
                "from_city": _fr,
                "to_city": _to,
                "status": st,
                "count": int(r["n"] or 0),
                "first_at": str(r["first_at"] or ""),
                "last_at": str(r["last_at"] or ""),
                "kind": ("soft" if st == "soft_reject" else
                         "login" if st == "login" else
                         "blocked" if st == "blocked" else
                         "empty" if st == "empty" else
                         "unsupported" if st == "unsupported" else
                         "error"),
                "evidence": _ev0,
            })
        # 归类改写发生在 SQL 分组**之后**，所以同一个（渠道×入口×航线）
        # 可能落下两组同类：改写前按 path_status 分成 login / empty 两组，
        # 改写后两组都叫 empty，界面上就成了两条一模一样的行
        # （实测 qunar API HAK→SHA「empty×4」与「empty×3」并列）。
        # 改写后必须再合并一次：计数相加、首末时间取极值、证据取最新。
        _merged = {}
        for o in out:
            _k = (o["platform"], o["path"], o["from_city"], o["to_city"],
                  o["status"])
            _prev = _merged.get(_k)
            if _prev is None:
                _merged[_k] = o
                continue
            _prev["count"] += o["count"]
            if o["first_at"] and (not _prev["first_at"]
                                  or o["first_at"] < _prev["first_at"]):
                _prev["first_at"] = o["first_at"]
            if o["last_at"] > _prev["last_at"]:
                _prev["last_at"] = o["last_at"]
                _prev["evidence"] = o["evidence"]
        out = sorted(_merged.values(), key=lambda o: (-o["count"],
                                                      o["last_at"]))
        # 失败后又成功 = 已恢复：复发账只说明"这毛病反复过"，不该在
        # 恢复后继续喊"需人工"。判据：同一渠道×入口×航线，最近一次
        # 真实成功行的 id 晚于最后一条**非成功且非空/非边界**的失败行。
        # - 必须带 from/to 限定：别的航线成功不能顶替本航线（H5 好了
        #   不代表这条线好了）。
        # - empty/unsupported 不算"仍在失败"：真无票与能力边界本来就
        #   不是故障，否则"登录墙→修好→连续几轮真无票"会永远显示需人工。
        # - 用 id 而非时间：一轮多行常落在同一秒，秒级分不出先后。
        # - **日历族按族匹配**（r395）：同程国际 r384 把通路从「日历」
        #   换成「窗历」（新入口名），按字面 entry_path 精确匹配时，旧
        #   「日历」的失败组永远等不到「窗历」的成功——4 条国际航线会
        #   永久挂「需人工」，而数据其实每轮都在。族内只认同一业务通路
        #   （日历/窗历都是"只出价不证明细"），不让 H5 成功去顶日历的账。
        with self._conn() as c:
            for o in out:
                plat, path = o["platform"], o["path"]
                _paths = (list(CAL_PATH_FAMILY) if path in CAL_PATH_FAMILY
                          else [path])
                _ph = ",".join("?" * len(_paths))
                fr = str(o.get("from_city") or "")
                to = str(o.get("to_city") or "")
                try:
                    row = c.execute(
                        "SELECT id, fetched_at FROM fetch_paths WHERE "
                        "platform=? AND entry_path IN (%s) AND from_city=? "
                        "AND to_city=? AND path_status IN ('ok','calendar') "
                        "ORDER BY id DESC LIMIT 1" % _ph,
                        (plat, *_paths, fr, to)).fetchone()
                    bad = c.execute(
                        "SELECT MAX(id) FROM fetch_paths WHERE platform=? "
                        "AND entry_path IN (%s) AND from_city=? AND "
                        "to_city=? AND path_status NOT IN "
                        "('ok','calendar','empty','unsupported')" % _ph,
                        (plat, *_paths, fr, to)).fetchone()
                except Exception:
                    row, bad = None, None
                last_ok = str((row or ["", ""])[1] or "")
                last_ok_id = int((row or [0])[0] or 0)
                last_bad_id = int((bad or [0])[0] or 0)
                o["last_ok_at"] = last_ok
                o["recovered"] = bool(last_ok and last_ok_id > last_bad_id)
        return out

    def latest_prices(self, hours=24 * 7):
        """每个 platform×航线×日期 最近一条「真实明细」价，用于重启续 TTL。

        只取有起飞/到达时刻的行：日历价不是航班明细，拿它当基线会让
        重启后的首轮误以为"明细已经采过"。
        """
        hours = max(1, min(24 * 90, int(hours or 24 * 7)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT p.platform, p.from_city, p.to_city, p.depart_date, "
                "p.price, p.fetched_at FROM flight_prices p "
                "JOIN (SELECT platform, from_city, to_city, depart_date, "
                "MAX(id) AS mid FROM flight_prices "
                "WHERE fetched_at >= datetime('now','localtime', ?) "
                "AND price > 0 AND COALESCE(depart_time,'') <> '' "
                "AND COALESCE(arrive_time,'') <> '' "
                "GROUP BY platform, from_city, to_city, depart_date) x "
                "ON p.id = x.mid ORDER BY p.id DESC",
                ("-%d hours" % hours,)).fetchall()
        return [dict(r) for r in rows]

    # 原始明细行的保留天数（r392）。所有读取方都在 168h（7 天）内：
    # `report._rounds(hours=168)` 走势、`latest_prices(24*7)` 重启 TTL
    # 基线、`recent_platform_flights(hours<=6)` 补位。更长的走势窗由
    # `price_daily` 日桶承载（400 天）。此前 purge 用 14 天，实测库里
    # 7–14 天区间积了 11843 行 / 184 MB 的 never-read `extra` 大 JSON
    # （全库 406 MB）。留 1 天余量防边界翻转。
    RAW_RETAIN_DAYS = 8

    def purge(self, days: int = 0) -> int:
        """删除 N 天前的价格明细（extra 大 JSON 是增长主体）与特价
        核实留痕；alert_state 保留（去抖状态）。price_daily 聚合桶
        不随 purge（半年走势窗的数据本体），其 400 天自清在
        daily_series 读时惰性执行。返回删除行数。

        days 缺省=RAW_RETAIN_DAYS（不再硬编码 14：14 天比任何读取方
        的需要都长，纯占盘）。"""
        days = int(days or self.RAW_RETAIN_DAYS)
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

    # SQLite 删除行不会缩小文件；不 VACUUM 的话「清理」只腾出内部空闲页，
    # 文件仍占满（实测 406 MB 库删掉 1.1 万行后体积不变）。VACUUM 会整库
    # 重写并短暂独占锁，所以只在「删得多 + 距上次够久 + 空间够」时做。
    VACUUM_MIN_FREE_MB = 400
    VACUUM_MIN_INTERVAL_H = 24 * 7

    def maybe_vacuum(self, deleted: int = 0, min_deleted: int = 2000) -> bool:
        """按条件回收磁盘；返回是否真的执行了 VACUUM。

        条件（全部满足才做）：
        - 本次 purge 删了 >= min_deleted 行（少量删除不值得重写整库）
        - 距上次 VACUUM >= VACUUM_MIN_INTERVAL_H 小时（标记文件在库旁）
        - 磁盘剩余 >= VACUUM_MIN_FREE_MB（重写期间需要同样大的空间）
        """
        import os as _os
        import shutil as _shutil
        import time as _time
        if int(deleted or 0) < int(min_deleted):
            return False
        stamp = _os.path.join(_os.path.dirname(self.db_path) or ".",
                              ".last_vacuum")
        try:
            if _os.path.isfile(stamp):
                age_h = (_time.time() - _os.path.getmtime(stamp)) / 3600.0
                if age_h < self.VACUUM_MIN_INTERVAL_H:
                    return False
        except OSError:
            pass
        try:
            _free_mb = _shutil.disk_usage(
                _os.path.dirname(self.db_path) or ".").free / 1048576.0
        except OSError:
            return False
        if _free_mb < self.VACUUM_MIN_FREE_MB:
            return False
        try:
            with self._conn() as c:
                c.execute("VACUUM")
        except Exception:
            return False
        try:
            open(stamp, "w", encoding="utf-8").write(
                _time.strftime("%Y-%m-%d %H:%M:%S"))
        except OSError:
            pass
        return True

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
            # `extra` 有两种形态，必须都吃：
            #   · 浏览器渠道 —— JSON **数组**，逐元素展开（每元素一个候选价）；
            #   · App 渠道   —— JSON **对象**（{"calendar":false,"source":…}），
            #     只是元数据，价格在 price 列。
            # 直接 `json_each(fp.extra)` 遇到对象会让整条 SQL 抛
            # `malformed JSON`，于是 App 采到的行一行都进不了日桶
            # ——采集正常、面板永远没数。这里按 json_type 分流。
            rows = c.execute(
                """SELECT CASE WHEN json_valid(fp.extra)
                                    AND json_type(fp.extra)='array'
                              THEN json_extract(je.value,'$.price')
                              ELSE fp.price END AS px,
                          CASE WHEN json_valid(fp.extra)
                                    AND json_type(fp.extra)='array'
                               THEN json_extract(je.value,'$.transCity')
                               ELSE NULL END AS tcity,
                          fp.fetched_at
                    FROM flight_prices fp
                    LEFT JOIN json_each(
                        CASE WHEN json_valid(fp.extra)
                                  AND json_type(fp.extra)='array'
                             THEN fp.extra ELSE '[]' END) je
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
            runs = [dict(r) for r in c.execute(
                "SELECT status,note,rows,started_at,finished_at "
                "FROM radar_runs WHERE user=? AND query_key=? "
                "ORDER BY finished_at DESC,id DESC LIMIT 8",
                (str(user or ""), query_key))]
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
                    "date_series": [], "channels_status": {},
                    "snapshots": 0, "last_at": "", "query": q,
                    "query_key": query_key, "last_run": last_run,
                    "runs": runs}
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
        # 每个出发日自己的监控曲线：只画全日期最低价会把“最低日切换”
        # 伪装成一次涨跌，且三两次快照会画成一条假平线。
        date_series = []
        for day in sorted(dates):
            pts = []
            for at in sorted(by_at):
                cands = [r for r in by_at[at]
                         if r["depart_date"] == day]
                if not cands:
                    continue
                b = min(cands, key=lambda r: float(r["price"]))
                ti = int(b["tax_included"])
                pts.append({
                    "at": at, "price": float(b["price"]),
                    "channel": b["channel"], "basis": b["basis"] or "",
                    "tax_included": None if ti < 0 else bool(ti),
                    "kind": b["kind"] or "", "to": b["to_city"],
                    "link": b["link"] or "",
                })
            if not pts:
                continue
            last = pts[-1]
            prevp = pts[-2] if len(pts) > 1 else None
            delta = (last["price"] - prevp["price"]) if prevp else None
            date_series.append({
                "date": day, "to": last["to"], "points": pts,
                "prev": prevp, "delta": delta,
                "delta_pct": (round(delta / prevp["price"] * 100, 1)
                              if prevp and prevp["price"] else None),
                "basis_changed": bool(
                    prevp and prevp["basis"] != last["basis"]),
            })
        channels_status = {}
        for r in rows:
            ch = r["channel"]
            st = channels_status.setdefault(
                ch, {"rows": 0, "days": set(), "last_at": "",
                     "bases": set()})
            st["rows"] += 1
            st["days"].add(r["depart_date"])
            st["last_at"] = max(st["last_at"], r["fetched_at"])
            if r["basis"]:
                st["bases"].add(r["basis"])
        channels_status = {
            ch: {"rows": st["rows"], "days": len(st["days"]),
                 "last_at": st["last_at"],
                 "bases": sorted(st["bases"])}
            for ch, st in channels_status.items()}
        low = min(date_rows, key=lambda r: r["price"]) if date_rows else None
        first = rows[0]
        return {
            "ok": True, "user": user, "dates": date_rows,
            "series": series, "date_series": date_series,
            "channels_status": channels_status, "lowest": low,
            "snapshots": len(by_at), "last_at": rows[-1]["fetched_at"],
            "query_key": query_key, "last_run": last_run, "runs": runs,
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
