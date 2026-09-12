# ✈️ ticket-monitoring

> Self-hosted multi-channel flight price monitoring: 5-platform fare collection →
> rich DingTalk group reports → 4-layer urgent alerts when your target price hits.
> Your data stays on your machine. Everything is configured in the browser. Free & open source.

[![Live Demo](https://img.shields.io/badge/🎪_Live_Demo-click_to_play-brightgreen)](https://dengmeiluan.github.io/ticket-monitoring/site/)
[![Release](https://img.shields.io/github/v/release/dengmeiluan/ticket-monitoring)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**[🎪 Live demo (zero install)](https://dengmeiluan.github.io/ticket-monitoring/site/)** · [中文文档](README.md) · [Windows releases](https://github.com/dengmeiluan/ticket-monitoring/releases)

## What it does

- **Collects** flight details (price, flight no., times, transfers, duration) from five Chinese travel platforms: Qunar, Fliggy, Ctrip, Tongcheng, Tuniu.
- **Watches** your routes with per-route thresholds (direct / transfer), arrival-time constraints and departure-time windows.
- **Pushes** one aggregated DingTalk message per round: per-route KPI sections with gauges, one-line action advice, 7-day trend, smoothed price charts, merged detail table image, and cross-channel price comparison for the same flight. Quiet hours (e.g. 23:00–07:00) silence routine heartbeats/storms/phone calls while hit alerts still get through; every send is archived for in-console replay.
- **Escalates** on target hits: 🚨 title, @your phone in group, storm re-push, optional ntfy phone popup + ringtone (DND-piercing), optional Aliyun phone call/SMS. Debounced (2h / further ¥50 drop).

## The console

A zero-dependency single-page console served on `127.0.0.1:8765`, designed like an airline dispatch board: monospace digits, numbered section labels, hairline dividers.

**Main view = tabbed workspace** (Overview / Trend·Calendar / Flight details / Channel health — one screen per session, remembers your last tab). **Settings = panel-based** (left rail switches between Channel login / Users & routes / Global params — one panel at a time, no endless scrolling).

Run pulse: per-round per-channel row counts & latency in a ring buffer — a 4-cell mono statline plus stacked pulse bars (red cap = some channel failed), so collection health is visible at a glance. DingTalk pushes carry a "full details" link; on Windows, target-hit toasts jump straight to the same single-alert page. Keyboard: `1`/`2` switch console/settings, `Ctrl/⌘+S` save settings, `R` run a sweep now (press twice to confirm), `/` focus search.

**All settings hot-reload on save — no restart, ever**: routes, thresholds, notifiers (DingTalk / ntfy / Aliyun / ServerChan, each with a one-click test button — the Windows toast test fires a real local notification), scan interval & jitter, console port (rebound in place), headless mode, crawler timeouts & pacing, user-agent, debug dumps, daily-report hour, image host. The **Global config center** groups schedule / crawler / general with 🔥 hot badges, and startup-only paths (database, log, browser profile) are honestly marked ♻ read-only. Settings also support field-level search, `Ctrl/⌘+S` save, and export/import of the whole config as JSON.

## Quick start (Windows, no Python needed)

1. Download the latest `ticket-monitoring-vX.Y.Z-win64.zip` from [Releases](https://github.com/dengmeiluan/ticket-monitoring/releases).
2. Unzip anywhere, double-click `机票监控.exe`.
3. Open `http://127.0.0.1:8765` → ⚙️ Settings: add routes (Chinese city names with autocomplete), target prices, and your DingTalk robot Webhook + signing secret. Hit 「🔔 测试推送」 to verify.
4. Save — monitoring starts immediately.

> Ctrip requires one QR-code login: `机票监控.exe --login ctrip` (the other four channels work out of the box).

## From source

```bash
git clone https://github.com/dengmeiluan/ticket-monitoring.git
cd ticket-monitoring
pip install -r requirements.txt
playwright install chromium
python main.py
```

Zero-config demo data: `python webui.py --demo`.

## Development

```bash
python tests/test_core_units.py   # unit tests (36 cases)
python tests/test_alert_path.py   # push-pipeline dry run (24 assertions)
python docs/uitest.py             # full UI self-test (94 assertions, self-hosted demo)
python docs/screenshot.py         # regenerate README screenshots
python docs/demo_build.py         # rebake the static demo site (docs/site)
```

Hard-earned lessons (anti-bot, DingTalk quirks, engineering pitfalls): [docs/LESSONS.md](docs/LESSONS.md). Before filing PRs, read [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md).

## License

Apache-2.0. For personal learning and research only — please respect each platform's terms of service.
