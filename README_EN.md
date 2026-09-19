# ✈️ ticket-monitoring

> Self-hosted multi-channel flight price monitoring: 5-platform fare collection →
> rich DingTalk group reports → 4-layer urgent alerts when your target price hits.
> Your data stays on your machine. Everything is configured in the browser. Free & open source.

[![Live Demo](https://img.shields.io/badge/🎪_Live_Demo-click_to_play-brightgreen)](https://dengmeiluan.github.io/ticket-monitoring/site/)
[![Release](https://img.shields.io/github/v/release/dengmeiluan/ticket-monitoring)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![CI](https://github.com/dengmeiluan/ticket-monitoring/actions/workflows/ci.yml/badge.svg)](https://github.com/dengmeiluan/ticket-monitoring/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**[🎪 Live demo (zero install)](https://dengmeiluan.github.io/ticket-monitoring/site/)** · [中文文档](README.md) · [Windows releases](https://github.com/dengmeiluan/ticket-monitoring/releases)

![Overview workspace (light)](docs/screenshots/console-light.png)

![Trend & calendar (dark)](docs/screenshots/console-dark.png)

<details>
<summary>More screenshots: panel-based settings / global config center / flight details / K-line / push preview / mobile</summary>

![Panel-based settings](docs/screenshots/console-config.png)

![Global config center](docs/screenshots/console-globals.png)

![Flight details](docs/screenshots/console-details.png)

![K-line trend](docs/screenshots/console-kline.png)

![Push preview](docs/screenshots/console-preview.png)

![Mobile](docs/screenshots/console-mobile.png)

</details>

## What it does

- **Collects** flight details (price, flight no., times, transfers, duration) from five Chinese travel platforms: Qunar, Fliggy, Ctrip, Tongcheng, Tuniu.
- **Watches** your routes with per-route thresholds (direct / transfer), arrival-time constraints and departure-time windows. Each route can watch **multiple departure dates at once** (date chips with auto year-completion — every date gets its own collection, push section, trend chart and calendar), and **cloning a route** copies the whole config in one click (the copy starts disabled: fix the cities, then switch on). Every route has an **enable/disable switch** — pausing keeps the whole config and exempts the route from scheduling, pushes and details everywhere; no more delete-to-stop. A **daily report** lands at your configured hour (default 09:00) with per-route KPIs and trend images.
- **Pushes** one aggregated DingTalk message per round: per-route KPI sections in a **three-tier semantic layout** (price as a direct link / flight body / decision fields in a grey quote tier) with **semantic tier dots** (🎯 hit · 🟩 below line · 🟨 within 10% — "above line" is the default state and carries no dot), one-line action advice, 7-day trend, smoothed price charts with **hit/borderline point rings** (solid green = truly actionable hit, hollow green = market broke the line, amber = within 10%), a merged detail table image (with cross-channel price comparison for the same flight — the table image is the single carrier, nothing truncated), and per-channel jump links on hit rows. Every text line is width-guarded for phone screens (degrades gracefully, always keeping price/flight/criteria). Quiet hours (e.g. 23:00–07:00) silence routine heartbeats/storms/phone calls while hit alerts still get through; every send is archived for in-console replay.
- **Escalates** on target hits: 🚨 title, @your phone in group, storm re-push, optional ntfy phone popup + ringtone (DND-piercing), optional Aliyun phone call/SMS. Debounced (2h / further ¥50 drop). If an escalation channel itself fails, the next DingTalk push says so — an alerting system must surface its own outages.

## The console

A zero-dependency single-page console served on `127.0.0.1:8765`, designed like an airline dispatch board: monospace digits, numbered section labels, hairline dividers.

**Main view = tabbed workspace** (Overview / Trend·Calendar / Flight details / Channel health — one screen per session, remembers your last tab). The trend tab carries a **14-day price calendar** (cheapest day badged 「▼ 最低」, every other day shows a +￥ delta) plus 7-day insights. **Settings = panel-based** (left rail switches between Channel login / Users & routes / Global params — one panel at a time, no endless scrolling).

Run pulse: per-round per-channel row counts & latency in a ring buffer — a 4-cell mono statline plus stacked pulse bars (red cap = some channel failed), so collection health is visible at a glance. DingTalk pushes carry a "full details" link; on Windows, target-hit toasts jump straight to the same single-alert page. Keyboard: `1`/`2` switch console/settings, `Ctrl/⌘+S` save settings, `R` run a sweep now (press twice to confirm), `/` focus search, `Esc` close overlays.

**All settings hot-reload on save — no restart, ever**: routes, thresholds, notifiers (DingTalk / ntfy / Aliyun / ServerChan, each with a one-click test button — the Windows toast test fires a real local notification), scan interval & jitter, console port (rebound in place), headless mode, crawler timeouts & pacing, user-agent, debug dumps, daily-report hour, image host. The **Global config center** groups schedule / crawler / general with 🔥 hot badges, and startup-only paths (database, log, browser profile) are honestly marked ♻ read-only. Settings also support field-level search, `Ctrl/⌘+S` save, and export/import of the whole config as JSON.

## Quick start (Windows, no Python needed)

1. Download the latest `ticket-monitoring-vX.Y.Z-win64.zip` from [Releases](https://github.com/dengmeiluan/ticket-monitoring/releases).
2. Unzip anywhere and run `TicketMonitor\TicketMonitor.exe`.
3. Open `http://127.0.0.1:8765` → ⚙️ Settings: add routes (Chinese city names with autocomplete), target prices, and your DingTalk robot Webhook + signing secret. Hit 「🔔 测试推送」 to verify.
4. Save — monitoring starts immediately.

> Ctrip requires one QR-code login: `TicketMonitor.exe --login ctrip` (the other four channels work out of the box).

## From source

```bash
git clone https://github.com/dengmeiluan/ticket-monitoring.git
cd ticket-monitoring
pip install -r requirements.txt
playwright install chromium
python main.py            # without config.yaml, writes an empty skeleton and guides you to the web UI
```

Prefer a Q&A wizard for the first config? `python main.py --setup` (Chinese, Enter-through defaults). Zero-config demo data: `python webui.py --demo`.

## Architecture

```
main.py            orchestration: route dedup → per-channel thread pool → multi-user aggregation → 4-layer alerts
crawlers/          five channels: qunar(browser-DOM fallback) / ctrip / tongcheng(XHR intercept)
                   / fliggy(PC SSR read) / tuniu(httpx reverse)
core/alerter.py    one aggregated push per round; _digest_payload pure builder (reused by console preview)
core/pulse.py      scan pulse recorder: per-round rows/latency ring buffer → /api/pulse
core/health.py     channel health timeline (parsed from monitor.log, maintenance latched)
core/demo.py       demo data (real-schema temp DB, deterministic seed)
webui.py           embedded single-page console (pure stdlib; workspace + panel settings; hot-reload everything)
report.py          trend chart / detail table PNG (Pillow) → image host
docs/              uitest self-test / screenshot generator / demo site baking / LESSONS
```

## DingTalk robot setup

1. In your DingTalk group: Group Settings → Bots → Add robot → **Custom** (Webhook).
2. Choose **Sign** security mode and copy the secret (starts with `SEC`).
3. Paste the Webhook URL into the settings page and hit 「🔔 测试推送」 to verify.

## Deployment (Windows)

Three PowerShell scripts live at the repo root:

```powershell
.\start.ps1    # start in background (PID in .monitor.pid, logs in logs/)
.\status.ps1   # process / port / last-round status
.\stop.ps1     # stop
```

Auto-start on login: Task Scheduler → Create Basic Task → trigger "At log on" → action runs `start.ps1`.

## Packaging

```bash
pip install pyinstaller
pyinstaller TicketMonitor.spec --noconfirm
# dist/TicketMonitor/ is the complete distributable (Playwright runtime included;
# the Chromium browser itself downloads on first launch, ~120MB)
```

## Development

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q   # full suite: 154 tests (incl. 5 tuniu-cabin / sentinel / fliggy-phantom-price regressions) + push-pipeline dry run (35 checks) + link-provenance gate (3) + version gate
python docs/uitest.py             # full UI self-test (108 assertions, self-hosted demo)
python docs/screenshot.py         # regenerate README screenshots (start the demo first: python webui.py --demo --port 8799)
python docs/demo_build.py         # rebake the static demo site (docs/site)
```

## FAQ

**Q: Does leaving the page open cost much?**
A: Polling uses a signature cache + ETag/304 — zero recomputation server-side and zero download browser-side when nothing changed; the page pauses polling when hidden and refreshes once on return.

**Q: Pushes fail with -1 "system busy"?**
A: That's DingTalk's "ghost delivery" — it errors but the message usually did land in the group. Policy is single-send, never retry; losses are naturally covered next round (phone escalation is an independent channel for hits).

**Q: Why is Fliggy consistently cheaper by 50-100?**
A: Fliggy PC shows tax-exclusive fares while others show tax-inclusive prices. The system adds a **+100 tax pad** to Fliggy quotes for hit qualification (display price untouched, labelled "税前") — a below-threshold Fliggy price not triggering a hit is expected, not a miss.

**Q: Ctrip shows "no data this round"?**
A: Login expired — run `--login ctrip` once and re-scan the QR code.

**Q: Do I need to restart after changing settings?**
A: No. Routes/thresholds/notifiers/interval/jitter/port/headless/timeouts/pacing/report hour/image host all hot-reload on save; only the database and log paths are startup-level.

**Q: Will my credentials leak?**
A: They live only in the local, git-ignored `config.yaml`. Demo mode and the online demo use synthetic data and never read back real credentials.

Hard-earned lessons (anti-bot, DingTalk quirks, engineering pitfalls): [docs/LESSONS.md](docs/LESSONS.md). Before filing PRs, read [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md).

## License

Apache-2.0. For personal learning and research only — please respect each platform's terms of service.
