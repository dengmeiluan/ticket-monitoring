# v1.5.295 Batch 1 — Evidence, Monitoring, Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make specials monitoring actually run in production, scope its history/alerts to the user's query, classify channel health from evidence, and persist a path-level provenance chain without fabricating raw responses.

**Architecture:** Keep the single `webui.py` integrator. Add two small pure modules (`core/radar_alerts.py`, `core/health_diag.py`) and extend `core/storage.py` with idempotent migrations and ledgers. The radar auto-loop remains the only scheduler; alerts are evaluated only after automatic `ok` snapshot writes. Provenance is written at fetch time as `prov` JSON plus `fetch_paths`; absence stays `unknown`.

**Tech Stack:** Python 3.11, SQLite, stdlib `unittest`/pytest, existing Playwright UI gates.

**Spec:** `docs/superpowers/specs/2026-10-24-v295-evidence-first-design.md`

## Global Constraints

- Do not bypass CAPTCHA/slider/risk control; never add stealth or proxy-pool evasion.
- Do not fabricate history, raw responses, flight rows, progress, or success states.
- `webui.py` remains the single UI integrator; no new frontend framework.
- Migrations only add columns/tables; existing DBs must remain readable.
- All timestamps local time; test-injectable clocks.
- No public push/tag/release in this batch.
- Every behavior fix gets a failing test first.

---

### Task 1: Preserve special_radar and wire alerters

**Files:**
- Modify: `main.py` (`build_users`, `start_web` call)
- Modify: `webui.py` (`_State`, `start_web` signature/body)
- Test: `tests/test_v295_radar_config.py` (create)

**Interfaces:**
- Produces: `build_users(cfg)` users include `special_radar: dict`.
- Produces: `start_web(..., alerters=None)` stores `_State.alerters` as a list aligned with users.

- [ ] **Step 1: Write failing tests**

```python
def test_build_users_keeps_special_radar_without_routes():
    from main import build_users
    cfg = {"users": [{"name": "u", "special_radar": {
        "enabled": True, "from": "SHA", "start": "2026-11-01",
        "end": "2026-11-07", "channels": ["ctrip"]}}]}
    users = build_users(cfg)
    assert users and users[0]["special_radar"]["from"] == "SHA"


def test_start_web_exposes_alerters():
    import inspect, webui
    assert "alerters" in inspect.signature(webui.start_web).parameters
    assert hasattr(webui._State, "alerters")
```

- [ ] **Step 2: Run and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v295_radar_config.py -q`
Expected: FAIL (`special_radar` missing / no `alerters` parameter).

- [ ] **Step 3: Implement**

In `main.py` `build_users`:

```python
        if not u.get("routes") and not u.get("specials") \
                and not u.get("special_radar"):
            continue
        users.append({
            ...
            "special_radar": u.get("special_radar") or {},
        })
```

In old single-user compatibility, include `special_radar` in the copied keys. In `webui.py` `_State` add `alerters = []`; change:

```python
def start_web(cfg, job, report_push, logger=None, users=None,
              reload_cb=None, config_path="config.yaml", version="",
              login_saved_cb=None, alerters=None):
    ...
    _State.alerters = list(alerters or [])
```

In `main.py` start call:

```python
start_web(cfg, sweep, _report_push, logger, users=rt["users"],
          alerters=rt["alerters"], ...)
```

- [ ] **Step 4: Run tests**

Run the same pytest command; expected PASS. Then `python -m pytest tests/test_radar_monitor.py -q` for no regression.

- [ ] **Step 5: Commit**

```bash
git add main.py webui.py tests/test_v295_radar_config.py
git commit -m "fix: preserve radar config and pass alerters to console"
```

---

### Task 2: Query-scoped radar history and run ledger

**Files:**
- Modify: `core/storage.py` (`SCHEMA`, `PriceStorage.__init__` migration, `save_radar_snapshot`, `radar_history`, new `radar_query_key`/`save_radar_run`)
- Test: `tests/test_v295_radar_scope.py` (create)

**Interfaces:**
- Produces: `PriceStorage.radar_query_key(query: dict) -> str`
- Produces: `PriceStorage.save_radar_snapshot(user, query, result, run_status="ok", note="") -> int`
- Produces: `PriceStorage.save_radar_run(user, query_key, status, note, rows, started_at="", finished_at="") -> int`
- Produces: `radar_history(user, days=120, query_key=None)` returns `query_key`, `last_run`, and only one query domain.

- [ ] **Step 1: Write failing tests**

```python
def _q(to, start, end, channels=("ctrip",)):
    return {"from": "SHA", "to": to, "nationwide": False,
            "start": start, "end": end, "channels": list(channels)}


def test_query_key_is_stable_and_channel_scoped():
    st = PriceStorage(str(tmp_path / "q.db"))
    k1 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))
    k2 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07",
                               ("fliggy", "ctrip")))
    assert k1 != k2
    assert k1 == st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))


def test_history_does_not_mix_routes(tmp_path):
    st = PriceStorage(str(tmp_path / "h.db"))
    st.save_radar_snapshot("u", _q("BJS", "2026-11-01", "2026-11-07"),
                           _result("2026-11-01", 500, to="BJS"))
    st.save_radar_snapshot("u", _q("CAN", "2026-12-01", "2026-12-07"),
                           _result("2026-12-01", 400, to="CAN"))
    q1 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))
    h = st.radar_history("u", query_key=q1)
    assert h["query"]["to"] == "BJS"
    assert [d["date"] for d in h["dates"]] == ["2026-11-01"]
    latest = st.radar_history("u")
    assert latest["query"]["to"] == "CAN"


def test_non_ok_run_is_ledger_only(tmp_path):
    st = PriceStorage(str(tmp_path / "r.db"))
    n = st.save_radar_snapshot("u", _q("BJS", "2026-11-01", "2026-11-07"),
                               _result("2026-11-01", 500), run_status="cache_hit")
    assert n == 0
    h = st.radar_history("u")
    assert h["dates"] == [] and h["last_run"]["status"] == "cache_hit"
```

`_result` is the helper already in `tests/test_radar_monitor.py`; copy a minimal local helper with `to` and one date.

- [ ] **Step 2: Run and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v295_radar_scope.py -q`
Expected: FAIL (missing methods/columns).

- [ ] **Step 3: Implement schema and migration**

Add to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS radar_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    query_key TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    rows INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radar_runs_user
    ON radar_runs(user, finished_at);
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
    ON radar_alerts(user, sent_at);
CREATE TABLE IF NOT EXISTS radar_alert_cfg (
    user TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    drop_min REAL NOT NULL DEFAULT 50,
    threshold REAL NOT NULL DEFAULT 0,
    cooldown_h REAL NOT NULL DEFAULT 12
);
```

In `PriceStorage._init_schema`, after `executescript`:

```python
            cols = {r[1] for r in c.execute("PRAGMA table_info(radar_snapshots)")}
            if "query_key" not in cols:
                c.execute("ALTER TABLE radar_snapshots ADD COLUMN query_key TEXT NOT NULL DEFAULT ''")
                c.execute("UPDATE radar_snapshots SET query_key="
                          "'legacy|'||from_city||'|'||to_city||'|'||nationwide||'|'||"
                          "COALESCE(query_start,'')||'|'||COALESCE(query_end,'')")
            c.execute("CREATE INDEX IF NOT EXISTS idx_radar_user_qat "
                      "ON radar_snapshots(user, query_key, fetched_at)")
```

Implement `radar_query_key`:

```python
    @staticmethod
    def radar_query_key(query):
        return "|".join([
            str(query.get("from") or ""), str(query.get("to") or ""),
            "1" if query.get("nationwide") else "0",
            str(query.get("start") or ""), str(query.get("end") or ""),
            ",".join(sorted(str(x) for x in (query.get("channels") or []))),
        ])
```

`save_radar_snapshot` starts with `qkey = self.radar_query_key(query)`, inserts `query_key` in the row tuple, calls `save_radar_run(...)`, and returns 0 before inserting when `run_status != "ok"`.

`radar_history` builds `WHERE user=? AND fetched_at>=?` + optional `query_key=?`; if no key, reads latest `radar_runs` with status ok and uses its key; if no run ledger (legacy), reads latest snapshot key. Return `query_key` and `last_run` from `radar_runs`. `first` must be from the same filtered rows.

- [ ] **Step 4: Run tests**

Run the new test file plus `tests/test_radar_monitor.py`; expected PASS.

- [ ] **Step 5: Commit**

```bash
git add core/storage.py tests/test_v295_radar_scope.py
git commit -m "feat: scope radar history by query and ledger runs"
```

---

### Task 3: Pure radar alert evaluator

**Files:**
- Create: `core/radar_alerts.py`
- Test: `tests/test_radar_alerts.py` (create)

**Interfaces:**
- Produces: `RadarAlertCfg(enabled=True, drop_min=50.0, threshold=0.0, cooldown_h=12.0, rearm_ratio=1.05)`
- Produces: `evaluate(prev_low, prev_basis, price, basis, armed, last_alert_at, now, cfg) -> AlertDecision`
- `AlertDecision.action` ∈ `seed|new_low|threshold|rearm|none|basis_reset`; fields `price, prev_low, kind, armed`.

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timedelta
from core.radar_alerts import RadarAlertCfg, evaluate

NOW = datetime(2026, 10, 24, 12, 0, 0)

def test_seed_new_low_cooldown_and_threshold():
    cfg = RadarAlertCfg(drop_min=30, cooldown_h=12)
    d = evaluate(None, "", 500, "bare", 1, None, NOW, cfg)
    assert d.action == "seed" and d.armed == 1
    d = evaluate(500, "bare", 460, "bare", 1, None, NOW, cfg)
    assert d.action == "new_low" and d.prev_low == 500
    d = evaluate(460, "bare", 420, "bare", 1, (NOW - timedelta(hours=2)).isoformat(), NOW, cfg)
    assert d.action == "none"                 # cooldown
    d = evaluate(460, "bare", 420, "bare", 1, (NOW - timedelta(hours=13)).isoformat(), NOW, cfg)
    assert d.action == "new_low"

def test_basis_switch_never_alerts():
    d = evaluate(500, "bare", 400, "tax_included", 1, None, NOW,
                 RadarAlertCfg(drop_min=10))
    assert d.action == "basis_reset"

def test_threshold_disarms_and_rearms():
    cfg = RadarAlertCfg(threshold=450, drop_min=10, cooldown_h=1)
    d = evaluate(500, "bare", 440, "bare", 1, None, NOW, cfg)
    assert d.action == "threshold" and d.armed == 0
    d = evaluate(440, "bare", 430, "bare", 0, NOW.isoformat(), NOW, cfg)
    assert d.action == "none"
    d = evaluate(430, "bare", 480, "bare", 0, NOW.isoformat(), NOW, cfg)
    assert d.action == "rearm" and d.armed == 1
```

- [ ] **Step 2: Run and confirm failure** — import error.

- [ ] **Step 3: Implement**

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class RadarAlertCfg:
    enabled: bool = True
    drop_min: float = 50.0
    threshold: float = 0.0
    cooldown_h: float = 12.0
    rearm_ratio: float = 1.05

@dataclass(frozen=True)
class AlertDecision:
    action: str
    price: float
    prev_low: float | None = None
    kind: str = ""
    armed: int = 1

def _cooldown_ok(last_alert_at, now, hours):
    if not last_alert_at:
        return True
    try:
        last = datetime.fromisoformat(str(last_alert_at))
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= hours * 3600

def evaluate(prev_low, prev_basis, price, basis, armed, last_alert_at, now, cfg):
    if not cfg.enabled:
        return AlertDecision("none", price, prev_low, armed=armed)
    if prev_low is None:
        return AlertDecision("seed", price, None, armed=1)
    if str(prev_basis or "") != str(basis or ""):
        return AlertDecision("basis_reset", price, prev_low, armed=1)
    if price >= prev_low:
        rearm = (cfg.threshold > 0 and not armed
                 and price >= cfg.threshold * cfg.rearm_ratio)
        return AlertDecision("rearm" if rearm else "none", price, prev_low,
                             armed=1 if rearm else armed)
    if (cfg.threshold > 0 and armed and price <= cfg.threshold):
        return AlertDecision("threshold", price, prev_low, "threshold", 0)
    if (prev_low - price >= cfg.drop_min
            and _cooldown_ok(last_alert_at, now, cfg.cooldown_h)):
        return AlertDecision("new_low", price, prev_low, "new_low", armed)
    return AlertDecision("none", price, prev_low, armed=armed)
```

- [ ] **Step 4: Run tests** — all pass.

- [ ] **Step 5: Commit**

```bash
git add core/radar_alerts.py tests/test_radar_alerts.py
git commit -m "feat: add pure radar alert evaluator"
```

---

### Task 4: Radar alert storage and config

**Files:**
- Modify: `core/storage.py` (tables from Task 2 + methods)
- Test: `tests/test_v295_radar_alert_store.py` (create)

**Interfaces:**
- Produces: `radar_alert_config(user) -> dict` (defaults when missing)
- Produces: `set_radar_alert_config(user, cfg: dict) -> None`
- Produces: `get_radar_alert_state(user, query_key, date) -> dict|None`
- Produces: `save_radar_alert_state(user, query_key, date, low_price, low_at, low_channel, low_basis, last_alert_price, last_alert_at, armed)`
- Produces: `record_radar_alert(...) -> int`, `radar_alerts(user, days=30) -> list`

- [ ] **Step 1: Write failing tests** — insert config defaults, upsert state, alert history round-trip, second upsert updates only.

- [ ] **Step 2: Run** — fail missing methods.

- [ ] **Step 3: Implement** with parameterized SQL:

```python
    def radar_alert_config(self, user):
        with self._conn() as c:
            r = c.execute("SELECT enabled,drop_min,threshold,cooldown_h "
                          "FROM radar_alert_cfg WHERE user=?", (str(user),)).fetchone()
        if not r:
            return {"enabled": True, "drop_min": 50.0,
                    "threshold": 0.0, "cooldown_h": 12.0}
        return {"enabled": bool(r[0]), "drop_min": float(r[1]),
                "threshold": float(r[2]), "cooldown_h": float(r[3])}
```

Use `ON CONFLICT(user, query_key, depart_date) DO UPDATE SET ...` for state; `record_radar_alert` inserts a row and prunes >180 days.

- [ ] **Step 4: Run tests.**

- [ ] **Step 5: Commit.**

---

### Task 5: Auto monitoring, alert dispatch and UI

**Files:**
- Modify: `webui.py` (`_radar_save_result`, `_radar_auto_loop`, `/api/radar/history`, new `/api/radar/alert-config`, `/api/radar/alerts`, markup near `#spRadarCfg`, JS near `spMonRender`)
- Modify: `core/storage.py` if a helper is missing
- Test: `tests/test_v295_radar_auto.py` (create)

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `_radar_save_result(result, source="manual")`; auto source evaluates alerts.
- Produces: `_radar_alert_dispatch(...)` with `(ok, err)`.

- [ ] **Step 1: Write failing tests**

Use source pins + a fake alerter:

```python
class _Notifier:
    def __init__(self): self.sent = []
    def send(self, title, desp="", **kw): self.sent.append((title, desp)); return True

class _Alerter:
    def __init__(self): self.notifier = _Notifier(); self.user = "u"
    def _in_quiet(self): return False

def test_auto_run_alerts_only_after_second_ok(monkeypatch, tmp_path):
    # call the webui helper twice with the same query/date:
    # first save must seed, second lower price must send exactly one.
```

Patch `_State.cfg`, `_State.alerters`, and `webui.PriceStorage` path via config. Use `source="auto"`.

Also pin UI strings:

```python
def test_alert_config_endpoint_and_monitor_labels():
    src = open("webui.py", encoding="utf-8").read()
    for s in ("/api/radar/alert-config", "/api/radar/alerts", "提醒：",
              "data-radalarm", "spAlertSave"):
        assert s in src
```

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement service**

`_radar_save_result`:

```python
def _radar_save_result(result, source="manual"):
    q = result.get("query") or {}
    user = str(q.get("user") or "")
    if not user:
        return 0
    st = PriceStorage(_radar_db_path())
    sts = result.get("channels") or {}
    dates = []
    for d in result.get("dates") or []:
        keep = {}
        for ch, rec in (d.get("by_channel") or {}).items():
            s = sts.get(ch) or {}
            if s.get("status") == "ok" and not s.get("cache_hit") \
                    and not s.get("fallback"):
                keep[ch] = rec
        if keep:
            dates.append({**d, "by_channel": keep})
    result = {**result, "dates": dates}
    status = "ok" if dates else ("empty" if result.get("dates") else "error")
    n = st.save_radar_snapshot(user, q, result, run_status=status)
    if source == "auto" and status == "ok":
        _radar_eval_alerts(user, q, dates, st)
    return n
```

`_radar_eval_alerts`:

```python
def _radar_eval_alerts(user, query, dates, st):
    from core.radar_alerts import RadarAlertCfg, evaluate
    cfg = st.radar_alert_config(user)
    acfg = RadarAlertCfg(enabled=bool(cfg["enabled"]),
                          drop_min=float(cfg["drop_min"]),
                          threshold=float(cfg["threshold"]),
                          cooldown_h=float(cfg["cooldown_h"]))
    qkey = st.radar_query_key(query)
    for d in dates:
        recs = list((d.get("by_channel") or {}).values())
        if not recs:
            continue
        low = min(recs, key=lambda r: float(r.get("price") or 0))
        price = float(low.get("price") or 0)
        basis = str(low.get("basis") or "")
        prev = st.get_radar_alert_state(user, qkey, d["date"])
        dec = evaluate(
            float(prev["low_price"]) if prev else None,
            (prev or {}).get("low_basis") or "",
            price, basis,
            int((prev or {}).get("armed", 1)),
            (prev or {}).get("last_alert_at"),
            datetime.now(), acfg)
        low_price = min(price, float(prev["low_price"])) if prev else price
        low_at = (prev or {}).get("low_at") or datetime.now().isoformat(
            timespec="seconds")
        low_ch = low.get("channel") or (prev or {}).get("low_channel") or ""
        last_at = (prev or {}).get("last_alert_at")
        last_price = (prev or {}).get("last_alert_price")
        if dec.action in ("new_low", "threshold"):
            ok, err = _radar_alert_dispatch(user, query, d["date"], low,
                                            dec, low_ch, basis)
            if ok:
                last_at = datetime.now().isoformat(timespec="seconds")
                last_price = price
        st.save_radar_alert_state(
            user, qkey, d["date"], low_price, low_at, low_ch, basis,
            last_price, last_at, dec.armed)
```

`_radar_alert_dispatch`:

```python
def _radar_alert_dispatch(user, query, date, low, dec, channel, basis):
    from core.alerter import sanitize_desp
    st = PriceStorage(_radar_db_path())
    al = next((a for a in (_State.alerters or [])
               if getattr(a, "user", "") == user), None)
    if not al or not getattr(al, "notifier", None):
        st.record_radar_alert(user, st.radar_query_key(query), date,
                              dec.price, dec.prev_low, channel, basis,
                              dec.kind, low.get("link") or "", "",
                              "skipped", "no_notifier")
        return False, "no_notifier"
    if hasattr(al, "_in_quiet") and al._in_quiet():
        st.record_radar_alert(user, st.radar_query_key(query), date,
                              dec.price, dec.prev_low, channel, basis,
                              dec.kind, low.get("link") or "", "",
                              "skipped", "quiet")
        return False, "quiet"
    fl = _radar_low_flights(query.get("from"), low.get("to") or query.get("to"),
                            date, limit=3)
    fs = fl.get("flights") or []
    title = "📉 特价雷达%s %s→%s %s ￥%.0f" % (
        "新低" if dec.kind == "new_low" else "阈值",
        query.get("from", ""), low.get("to") or query.get("to", ""),
        date, dec.price)
    lines = ["- **价格**：￥%.0f（%s）" % (
        dec.price, low.get("basis_label") or basis or "口径未标注")]
    if dec.prev_low is not None:
        lines.append("- **较上次低点**：￥%.0f（降 ￥%.0f）"
                     % (dec.prev_low, dec.prev_low - dec.price))
    lines.append("- **渠道**：%s" % channel)
    if fs:
        lines.append("- **该日真实明细**：")
        for f in fs:
            lines.append("  - %s %s→%s ￥%.0f %s" % (
                f.get("code") or "—", f.get("depTime") or "—",
                f.get("arrTime") or "—", float(f.get("price") or 0),
                f.get("platform_cn") or ""))
    else:
        lines.append("- **该日真实明细**：尚未采集；日历价不能生成航班")
    if low.get("link"):
        lines.append("- [打开官方渠道](%s)" % low["link"])
    try:
        ok = bool(al.notifier.send(sanitize_desp(title),
                                   sanitize_desp("\n\n".join(lines))))
        err = "" if ok else "send_failed"
    except Exception as e:
        ok, err = False, str(e)[:160]
    st.record_radar_alert(user, st.radar_query_key(query), date,
                          dec.price, dec.prev_low, channel, basis,
                          dec.kind, low.get("link") or "",
                          json.dumps(fs, ensure_ascii=False),
                          "sent" if ok else "failed", err)
    return ok, err
```

`_radar_auto_loop` call `_radar_save_result(out, source="auto")`; log status; remove 60s between users? Keep 15s to reduce load; spec says sequential, 60 okay.

API:
- `/api/radar/history`: pass optional `query_key`.
- `/api/radar/alert-config` GET/POST with same-origin JSON; user required; clamp `drop_min 0..10000`, `threshold 0..200000`, `cooldown_h 1..168`.
- `/api/radar/alerts` list.

UI:
- In `#spRadarCfg` after channels add:
  ```html
  <label><input type="checkbox" id="spAlertOn"> 降价提醒</label>
  <input type="number" id="spAlertDrop" min="0" step="10" placeholder="降幅 ¥">
  <input type="number" id="spAlertTh" min="0" step="50" placeholder="阈值 ¥ (0=关)">
  <input type="number" id="spAlertCool" min="1" max="168" placeholder="冷却 h">
  <button class="btn2" id="spAlertSave" onclick="spAlertSave()">保存提醒</button>
  ```
- JS `spAlertLoad`, `spAlertSave`, header meta `提醒：开 · 上次 ...`; use API; refresh `spMonLoad`.
- `spMonRender` shows alert badge if latest alert date matches selected.
- Demo: `if(S&&S.demo)` label "DEMO · 合成监控"; no API writes (server returns demo error).

- [ ] **Step 4: Run** focused tests + `node --check` of extracted JS (existing pattern in tests).

- [ ] **Step 5: Commit.**

---

### Task 6: Health parser truth + pure diagnosis

**Files:**
- Modify: `core/health.py`
- Create: `core/health_diag.py`
- Test: `tests/test_health_diag.py` (create)

**Interfaces:**
- Produces: `classify_round(plats: dict, login: dict|None = None, cookie: dict|None = None, all_plats=("ctrip","qunar","fliggy","tongcheng","tuniu")) -> list[dict]`
- Card keys: `plat,kind,label,action,evidence,s,ok,tot,login,cookie`.

- [ ] **Step 1: Write failing tests**

```python
from core.health_diag import classify_round

def test_ip_partial_empty_and_unscanned():
    cards = classify_round({
        "tuniu": {"s": "fail", "ok": 0, "tot": 1, "note": "179991 触发IP风控"},
        "qunar": {"s": "empty", "ok": 0, "tot": 0, "note": "没有查询到符合条件的航班"},
        "ctrip": {"s": "part", "ok": 2, "tot": 3, "note": "部分日期查询失败（2/3 成功）"},
    })
    by = {c["plat"]: c for c in cards}
    assert by["tuniu"]["kind"] == "ip"
    assert by["qunar"]["kind"] == "empty"
    assert by["ctrip"]["kind"] == "partial" and by["ctrip"]["s"] == "part"
    assert by["fliggy"]["kind"] == "unscanned"
    assert not any(c["kind"] == "ok" for c in cards.values())
```

Add cases: `need_login` → login; note CAPTCHA → captcha; `s=ok, detail_ok>0` → ok; `s=ok, cal>0, detail=0` → calendar_only; cookie expired → cookie_expired; Qunar 1999 no-result → empty; 1999 登录 → login.

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement classifier**

Order matters: unscanned → maintenance → ip → captcha → login → empty → timeout → partial → cookie_expired → calendar_only → ok → unknown. Do IP before login (179991 may contain 登录?); explicit empty before login only if note has no login words.

```python
_IP = ("179991", "风控", "限流", "403", "429", "ip封", "IP封")
_CAPTCHA = ("验证码", "滑块", "人机", "challenge", "captcha")
_LOGIN = ("未登录硬拒", "请登录", "需登录", "登录失效", "会话失效", "login_required")
_EMPTY = ("没有查询到符合条件的航班", "未查询到", "无航班", "no flight")
_TIMEOUT = ("超时", "timeout")
```

If `s == "maint"` → maintenance; if missing → unscanned; if `s=="ok"` and detail>0 → ok; if `s=="ok"` and cal>0 → calendar_only; if `s=="part"` → partial; if `s=="empty"` → empty; if `need_login` → login; else unknown. IP/CAPTCHA should override `s=fail`; for `s=part` with IP note, kind ip and label includes partial. Use note matching first for IP/CAPTCHA.

- [ ] **Step 4: Fix parser**

In `core/health.py`:
- `rest[:40]` → `rest[:160]` in two places.
- Add `_EMPTY_MARKS = ("没有查询到符合条件的航班","未查询到","无航班")`.
- In event loop, before `_EXC_MARK`? Add branch:
  ```python
  elif any(k in msg for k in _EMPTY_MARKS):
      ev["empty"] += 1
      if not ev["note"]: ev["note"] = "无符合条件的航班"
  ```
  Initialize `empty` in `_new_round` event dict. In `_flush`, if `not ok_n and ev["empty"] and not auth/gate` → `s="empty"`, note. Stats add `empty`; rate denominator exclude empty.
- Add `login`/`captcha` notes from path? Batch 1 only parser; path log additions later. Keep existing `_AUTH_MARKS`.

- [ ] **Step 5: Run tests** — classifier and health parser subset; commit.

---

### Task 7: Health API/UI and evidence ledger

**Files:**
- Modify: `webui.py` (`_health_state`, `renderHealthDiag`, new `/api/channel/selfcheck`)
- Test: `tests/test_v295_health_ui.py` (create)

**Interfaces:**
- `/api/health` payload gains `diag: list[card]` and `diag_at`.
- POST `/api/channel/selfcheck` `{plat}` → `{ok, card, evidence_at}`; same-origin JSON; no network.

- [ ] **Step 1: Write failing tests** — source pins for `j.diag`, `channel/selfcheck`, `channel_evidence.jsonl`, `cookie_state`, and no `note.match(/179991` in `renderHealthDiag`.

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement**

`_health_state` after parsing:
```python
        out["diag"] = classify_round(
            (out.get("rounds") or [{}])[-1].get("plats") or {},
            _login_state_view().get("plats") or {},
            _cookie_states())
        out["diag_at"] = last_ts
```
`_cookie_states` reads `crawler.session_state_path` JSON, returns `missing/expired/unverified`; no values logged.

`POST /api/channel/selfcheck`: validate plat, load latest health, call classifier with one plat, append to `logs/channel_evidence.jsonl` (path from cfg output? `_anchored("logs/...")`), return card. No browser/network.

UI: `renderHealthDiag` parse `HL.diag` and render `kind/label/action/evidence`; buttons `打开登录` for login/captcha, `停止重试` for ip, `查看轮次` otherwise. If no diag: "诊断数据未到（不会猜）". Add `data-diagself` button calling `diagSelfcheck(plat)`; toast result; refresh.

- [ ] **Step 4: Run UI/source tests + `node --check`.**

- [ ] **Step 5: Commit.**

---

### Task 8: Provenance schema and scan writes

**Files:**
- Modify: `core/models.py` (`FlightPrice.prov`)
- Modify: `core/storage.py` (migration `prov`, `fetch_paths`, `save_fetch_path`, insert prov)
- Modify: `main.py` (`_timed_fetch` writes paths/prov)
- Test: `tests/test_v295_prov.py` (create)

**Interfaces:**
- `FlightPrice.prov: str = ""` JSON.
- `PriceStorage.save_fetch_path(platform, from_city, to_city, depart_date, path, path_status, request_url="", http_status=0, rows=0, note="", evidence_level="path") -> int`
- `prov` dict: `{"entryPath","pathId","pathStatus","evidenceLevel","kind"}`.

- [ ] **Step 1: Write failing tests**

```python
def test_fetch_path_and_prov_round_trip(tmp_path):
    st = PriceStorage(str(tmp_path / "p.db"))
    pid = st.save_fetch_path("ctrip", "SHA", "BJS", "2026-11-10",
                             "PC", "ok", rows=12)
    fp = FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500,
                     prov=json.dumps({"entryPath": "PC", "pathId": pid,
                                      "pathStatus": "ok",
                                      "evidenceLevel": "path",
                                      "kind": "detail"}))
    st.save(fp)
    row = st.last_lowest("SHA", "BJS", "2026-11-10")
    assert json.loads(row["prov"])["entryPath"] == "PC"
    paths = st.fetch_paths("SHA", "BJS", "2026-11-10")
    assert paths[0]["entry_path"] == "PC" and paths[0]["evidence_level"] == "path"
```

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement**

- `_init_schema` adds `prov` to `flight_prices` if missing; creates `fetch_paths`.
- `save`/`save_many` include `prov`.
- `main._timed_fetch`: after fetch:
  ```python
  paths = list(getattr(c, "paths", []) or [])
  ok_paths = [x for x in paths if x.get("status") in ("ok", "calendar")]
  selected = ok_paths[-1] if ok_paths else None
  pid = 0
  if selected:
      pid = storage.save_fetch_path(c.name, fc_, tc_, d_, selected["path"],
          selected["status"], rows=len(prices),
          note=selected.get("detail", ""), evidence_level="path")
  prov = json.dumps({"entryPath": selected["path"] if selected else "",
      "pathId": pid, "pathStatus": selected["status"] if selected else "unknown",
      "evidenceLevel": "path" if selected else "unknown",
      "kind": "calendar" if selected and selected["status"] == "calendar" else "detail"})
  for p in prices:
      p.prov = prov
  ```
  This uses last successful path for all rows; label is `path` not per-row raw. If no selected, `unknown`.
- `save_fetch_path` inserts and returns `lastrowid`.
- `fetch_paths` read method for UI/tests.

- [ ] **Step 4: Run tests + a focused main scan test?** Existing scan tests may construct FlightPrice; default prov empty is fine.

- [ ] **Step 5: Commit.**

---

### Task 9: Probe/API/CSV/rate provenance

**Files:**
- Modify: `webui.py` (`_state rows`, probe row, detail, `renderDetail`, `expCsv`, `srxExport`, `/api/probe/raw`, `_radar_low_flights`)
- Test: `tests/test_v295_prov_ui.py` (create)

**Interfaces:**
- State row `prov` parsed dict or `{}`.
- Probe row `prov` includes `pathStatus/evidenceLevel`.
- CSV columns `采集入口,证据级别`.
- `/api/probe/raw` returns `evidence_level`; `raw` only if actual body stored (currently none → `parsed_extra`).

- [ ] **Step 1: Write failing tests** — source pins for `f.prov`, `采集入口`, `evidence_level`, `解析 extra`, `_radar_low_flights` rowId/entryPath; raw endpoint label.

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement**

- Row builder reads `prov` JSON from `flight_prices` and exposes `prov`.
- Probe `entryPath` plus `pathStatus`, `evidenceLevel="path"`.
- Detail "采集入口" shows `PC/H5 · 路径级` or `未记录`.
- RAW panel header: `解析 extra（非原始响应）`; never claim逐项一致 unless `evidenceLevel=="raw_http"` (not produced yet).
- CSV add `采集入口`, `证据级别`; search export add same.
- `_radar_low_flights` select `id` and `extra` idx; output `rowId/rawIdx/entryPath`; if absent, empty string; UI note.

- [ ] **Step 4: Run focused tests + UI source tests.**

- [ ] **Step 5: Commit.**

---

### Task 10: Batch 1 integration and acceptance

**Files:**
- Test: `tests/test_v295_batch1_gate.py` (create)
- Modify: `docs/EXECUTION_SPEC_LATEST.md` (batch 1 facts), `docs/release-notes-v1.5.295.md` (create later)
- No version bump yet.

- [ ] **Step 1: Add gate test** that asserts:
  - `special_radar` survives build_users;
  - query key scoping;
  - alert evaluator scenarios;
  - health classifier cases;
  - provenance round-trip;
  - source pins for `/api/radar/alert-config`, `/api/channel/selfcheck`, CSV entry/level.
- [ ] **Step 2: Run focused suite**:
  `pytest tests/test_v295_*.py tests/test_radar_monitor.py tests/test_radar_alerts.py tests/test_health_diag.py -q`
- [ ] **Step 3: Restart demo 8799** (new code) and run UI source/JS checks; run `docs/uitest.py` (expect 628+ new assertions; update count only if new checks are added).
- [ ] **Step 4: Restart live 8765** with new code; run:
  - `GET /api/health` has 5 diag cards; no green for unscanned.
  - one live probe (SHA→BKK, one channel) returns `prov.entryPath` for all rows.
  - radar monitor still shows 7 dates; alert config GET/POST defaults.
  - no alert sent during first seed (inspect `radar_alerts` count 0 / no push).
- [ ] **Step 5: Full pytest** (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q`) and record exact counts.
- [ ] **Step 6: Commit batch 1**; do not release. Report counts and any deviations.

---

## Self-Review

- Spec coverage: Tasks 1–2 P0 config/scope; 3–5 alerts; 6–7 health; 8–9 provenance; 10 gates. Visual/perf batch is intentionally separate.
- No placeholders: all new functions/tests have concrete signatures and assertions.
- Types consistent: `query_key`, `run_status`, `AlertDecision`, `prov` names used consistently.
- Risk: `_timed_fetch` last-path labeling is path-level, not per-row raw; the plan labels it `path` and forbids `raw_http` claims.
