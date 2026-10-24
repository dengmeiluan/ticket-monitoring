# ✈️ ticket-monitoring

> Self-hosted multi-channel flight price monitoring: 5-platform fare collection →
> rich DingTalk group reports → 4-layer urgent alerts when your target price hits.
> Domestic and international routes (destinations across five continents) run
> through the same collection → judging → push pipeline.
> Your data stays on your machine. Everything is configured in the browser. Free & open source.

[![Live Demo](https://img.shields.io/badge/🎪_Live_Demo-click_to_play-brightgreen)](https://dengmeiluan.github.io/ticket-monitoring/site/)
[![Release](https://img.shields.io/github/v/release/dengmeiluan/ticket-monitoring?display_name=release)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![CI](https://github.com/dengmeiluan/ticket-monitoring/actions/workflows/ci.yml/badge.svg)](https://github.com/dengmeiluan/ticket-monitoring/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows_%7C_Linux_%7C_macOS-0078D6)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**[🎪 Live demo (zero install)](https://dengmeiluan.github.io/ticket-monitoring/site/)** · [中文文档](README.md) · [Releases (all platforms)](https://github.com/dengmeiluan/ticket-monitoring/releases)

![Overview workspace (light)](docs/screenshots/console-light.png)

![Trend & calendar (dark)](docs/screenshots/console-dark.png)

![Flight watch studio (demo synthetic data, not live quotes): real collection points, target line and channel coverage in one view](docs/screenshots/console-watch-studio.png)

![Specials monitoring (demo synthetic data): daily low-price calendar, monitored trend and real flights on the lowest day in one view](docs/screenshots/console-specials.png)

<details>
<summary>More screenshots: panel-based settings / flight watch config / date modes / global config center / restart &amp; migration / flight details / K-line / watch K-line / push preview / channel diagnosis / search first paint / mobile</summary>

![Channel diagnosis: latest-round evidence separates login expiry, CAPTCHA, IP/rate risk control and timeouts.](docs/screenshots/console-health.png)

![Search first paint: intro, price band, five sources and mirror are collapsible; flat depth without heavy borders.](docs/screenshots/console-search.png)

![Panel-based settings: date mode switch, channel readiness and save bar in one view.](docs/screenshots/console-config.png)

![Flight watch config: add or edit a watch inside a configured route/date with channels, target, alerts and notes.](docs/screenshots/console-config-watch.png)

![Date mode switch: range or specific-day, one editor at a time with drafts kept.](docs/screenshots/console-date-modes.png)

![Global config center](docs/screenshots/console-globals.png)

![Restart & migration center](docs/screenshots/console-restart.png)

![Flight details](docs/screenshots/console-details.png)

![K-line trend](docs/screenshots/console-kline.png)

![Watch K-line: real collection points, target line and channel coverage in one view.](docs/screenshots/console-watch-kline.png)

![Push preview](docs/screenshots/console-preview.png)

<img src="docs/screenshots/console-mobile.png" width="380" alt="Mobile details">

<img src="docs/screenshots/console-mobile-filter.png" width="380" alt="Mobile filters with a persistent view-results action">

<img src="docs/screenshots/console-watch-mobile.png" width="380" alt="Mobile flight watch studio">

</details>

## What it does

- **Collects** flight details (price, flight no., times, transfers, duration, terminals, cabin, aircraft, punctuality, baggage rules) from five Chinese travel platforms: Qunar, Fliggy, Ctrip, Tongcheng, Tuniu — each on its live path (Qunar H5 with login, since its PC web flight site retired on 2026-10-10; Fliggy PC SSR read, Ctrip PC international flight list with mobile H5 for domestic, Tongcheng mobile H5, Tuniu direct HTTP), zero browser overhead except where a channel demands it.
- **Qunar web retirement (Oct 2026)**: Qunar's PC flight search/booking page retired on 2026-10-10. Collection and user deep links now use its H5 (`m.flight`; the PC revival probe is off by default); the login window opens the unified account page (SMS code / QR) and the shared `.qunar.com` cookie is required for full H5 detail. App-only fares and auto-booking are out of scope; the other four channels are unaffected.
- **Watches** your routes with per-route thresholds (direct / transfer), arrival-time constraints and departure-time windows. Each route can watch **multiple departure dates at once** through a range / specific-day mode switch — one editor at a time, both drafts retained, applied ranges merge and dedupe automatically; every date gets its own collection, push section, trend chart and calendar. **Cloning a route** copies the whole config in one click (the copy starts disabled: fix the cities, then switch on). Every route has an **enable/disable switch** — pausing keeps the whole config and exempts the route from scheduling, pushes and details everywhere; no more delete-to-stop. A **daily report** lands at your configured hour (default 09:00) with per-route KPIs and trend images.
- **Pushes** one aggregated DingTalk message per round: per-route KPI sections in a **three-tier semantic layout** (price as a direct link / flight body / decision fields in a grey quote tier) with **semantic tier dots** (🎯 hit · 🟩 below line · 🟨 near — "above line" is the default state and carries no dot), one-line action advice, 7-day trend, smoothed price charts with **four-tier hit point rings** (● dark green = truly actionable hit / ○ fine green = market broke the line / ○ amber = near / ▼ red = fell back below line) speaking the same language as the push copy, the details table and the calendar, a merged detail table image (with cross-channel price comparison for the same flight — the table image is the single carrier, nothing truncated), and per-channel jump links on hit rows. Every text line is width-guarded for phone screens (degrades gracefully, always keeping price/flight/criteria). If the table image upload ever fails, a **text fallback** carries the full TOP5 details instead (same-price multi-channel rows merge into one line with a ×N badge — information never vanishes with the picture). Email delivery (163/QQ mail boxes, full-page screenshot and push charts inline — zero external image loading on the recipient side) can run alongside DingTalk; every send is archived for in-console replay. Quiet hours (e.g. 23:00–07:00) silence routine heartbeats/storms/phone calls while hit alerts still get through.
- **Monitors international flights** with zero extra configuration: still just three-letter codes — scope is detected automatically (either end outside the mainland city set, incl. HK/MO/TW and overseas, marks the route international). International rows always carry the **tax-inclusive total price** (a small tax breakdown accompanies the detail row), cross-day tolerance widens to 0-7 days and duration truth is timezone-corrected; the city panel gains an international-hot tab 272 destinations (33 highlighted), searchable by Chinese name / pinyin / code, route heads show an automatic globe badge, hit rows are tagged tax-inclusive, and the cross-channel phantom-price guards grade by the international price range.
- **Escalates** on target hits: 🚨 title, @your phone in group, storm re-push, optional ntfy phone popup + ringtone (DND-piercing), optional **Bark push to iPhone** (self-hosted server supported), optional Aliyun phone call/SMS, Windows toast jumping to the single-alert page. Debounced (2h / further ¥50 drop). If an escalation channel itself fails, the next DingTalk push says so — an alerting system must surface its own outages.

## The console

A zero-dependency single-page console served on `127.0.0.1:8765`, designed like an airline dispatch board: monospace digits, numbered section labels, hairline dividers.

**Main view = tabbed workspace** (Overview / Special fares / Route trend / Watch trend / Watch details / Channel health — one screen per session, remembers your last tab). The trend tab carries a **14-day price calendar** (cheapest day badged 「★ 最低」, every other day shows a +￥ delta) plus 7-day insights. Detail rows carry an inline **📈 jump that opens that route's trend** (paired with the ↗ outbound link, anchoring route and date), and clicking any trend data point (or pressing Enter on the focused chart) opens that round's route details with the route and departure date locked — the in-page jump graph is closed both ways. **Settings = panel-based** (left rail switches between Channel login / Users & routes / Flight watch / Global params — one panel at a time, no endless scrolling).

**Official brand layer**: the five OTAs and 87 airlines use locally embedded official app/site marks where verified — channels are square app tiles, airlines are circular carrier avatars — across search rows, mirrors, details, matrices, the watch studio and every config surface. Unlisted carriers fall back to an IATA circular code; no runtime external requests and no borrowed logos.

**Watch-flight studio** is one of six monitor tabs: watched flights are a subset of a configured route + date detail set from the same locally stored rows; a route rail filters them and a full-width line/K-line chart replays only real observations (48h/7/30/90/180d), and a focus strip shows target gap, channel coverage and source freshness. The same route rail drives a filterable flight roster (status, target, airline, direct/transfer, departure window, cabin, channel, price); the overview also mounts watch cards with a 7-day mini trend, channel coverage and a 30-day jump. Every flight seen during a normal route scan is persisted to a flight-level daily OHLC table, so any search row can preview its real history without being watched; target-hit alerts are sent by the scan pipeline with dedupe. All watch settings (cities with autocomplete, date, live candidate flights, channels, target, alert toggle, note) are editable independently in Settings → Flight watch. Mini trends and overview cards aggregate by calendar day and use one red target token; route and flight charts are point-to-point polylines, and the route chart has an “outliers” toggle (IQR extremes hidden by default with a note).

Run pulse: per-round per-channel row counts & latency in a ring buffer — a 4-cell mono statline plus stacked pulse bars (red cap = some channel failed), so collection health is visible at a glance. DingTalk pushes carry a "full details" link; on Windows, target-hit toasts jump straight to the same single-alert page. Keyboard: `1`/`2` switch console/settings, `S` open the realtime search view, `M` toggle list / flight × channel matrix, `J`/`K` step through detail differences, `3`/`4`/`5`/`6`/`7` jump straight to Overview / Trend / Watch / Details / Health, `Ctrl/⌘+S` save settings, `R` run a sweep now (press twice to confirm), `/` focus search, `↑`/`↓` step through probe rows, `Esc` close overlays.

![Realtime search (real collected data)](docs/screenshots/console-probe.png)

<details><summary>Mobile realtime search: parsed list / mirror / triple alignment</summary>

<img src="docs/screenshots/console-probe-mobile.png" width="300" alt="Mobile parsed list">
<img src="docs/screenshots/console-probe-mobile-mirror.png" width="300" alt="Mobile original-page mirror">
<img src="docs/screenshots/console-probe-mobile-detail.png" width="300" alt="Mobile triple alignment">

</details>

![Active probe: city autocomplete, five-channel selector and realtime probe (never stored or pushed)](docs/screenshots/console-probe-probe.png)

![Probe city autocomplete: Chinese / pinyin / IATA, keyboard selection, full domestic/international picker](docs/screenshots/console-probe-city.png)

<details><summary>Demo console (synthetic data, DEMO badge visible): overview / search / list-mirror / calibration / probe / shared filters</summary>

<img src="docs/screenshots/console-probe-overview.png" width="300" alt="Demo console overview (synthetic data)">
<img src="docs/screenshots/console-probe-monitor.png" width="300" alt="Demo search console, dark (synthetic data)">
<img src="docs/screenshots/console-probe-workbench.png" width="300" alt="Demo parsed list and original-page mirror (synthetic data)">
<img src="docs/screenshots/console-probe-health.png" width="300" alt="Demo five-platform calibration (synthetic data)">
<img src="docs/screenshots/console-probe-probe-overview.png" width="300" alt="Demo active probe, one-line form and batch (synthetic data)">
<img src="docs/screenshots/console-probe-probe-workbench.png" width="300" alt="Demo shared filters: common / processed-history / search-only (synthetic data)">

</details>

**Realtime search** (`🔎 Search`, real collected data): a dedicated view over real `/api/state` rows, not a mock table. The chain is: 14-day departure band + five-source briefing → quick/advanced filters → parsed list or flight × channel matrix → original-page mirror → triple-aligned detail → sign-off/export. The live probe now supports up to four route/date legs in one batch, with real per-channel phases, incremental results, cancel, reconnect and retry.

- **Honest data boundary**: the departure band only draws points that exist in the DB; missing days stay “not collected”; the observation-day axis is labeled separately. Calendar-only rows (no flight number/time) are never marked qualified and never enter same-flight ladders. A channel with no rows stays “unavailable” — no sample data is injected.
- **Common + processed-history + search-only filters**: the common group (direct/transfer, cabin, airline, departure/arrival airport, share/stop/risk, time windows, price band, baggage/meal/LCC/cross-day/hide-calendar) uses the same names and semantics as the details table; the processed-history group (layover/flight duration, on-time rate, aircraft age, checked baggage, aircraft type/size, child fare, few seats) filters the same locally stored fields; search-only gates cover original page, raw, missing/complete fields, stale padding and qualified-only. Search filters are a superset of detail filters; airline/airport/cabin/aircraft are multi-select with facet counts, departure/arrival support 00-06 and minute-precise windows, and presets cover direct+bag, daytime, calm and qualified-only. The panel shows live hit counts and active conditions, a sticky footer on mobile, and “clear common filters” keeps search-only conditions. Persisted, with one-click relax on empty.
- **Parsed list ⇄ flight × channel matrix**: 13 field ticks, risk badges (age/policy/check-in/bait/black-card/refund), in-row quick view, same-flight grouping, load-more; matrix rows are real same-flight groups, missing cells are “not supplied”; a cell opens the detail.
- **Mirror**: five channel tabs, list/detail/four-up; mirror values are projected from **the same raw row** (missing keys = not supplied). The UI explicitly says “structural redraw, not an original screenshot/iframe” and links to the real page.
- **Triple-aligned detail**: parsed ⇄ mirror(raw) ⇄ raw path with four states (match / not supplied / not captured / mismatch); derived fields (price/airport/cabin) are labeled “scope difference”. Field click locates the raw key; 30-day trend, two-axis calendar, five-cell same-flight ladder, conclusion/note/review, prev/next (J/K), evidence JSON and snapshot.
- **Five-platform calibration book**: five channels × list/detail/calendar/cross + four-up; empty states are never filled with teaching samples.
- **Active probe**: origin/destination fields reuse the config city index (Chinese / pinyin / IATA autocomplete, keyboard selection, full domestic/international picker); any OD/date, real five-crawler collection, **not stored and never pushed**; per-channel row counts / unavailable / failure; sessions kept locally. When no configured threshold applies, rows are labeled “probe not evaluated”. The hosted demo is a static site: the probe entry is disabled with an explanation; run locally for real collection.
- **Evidence export**: CSV (parsed price, raw/original-page price, times, cabin, aircraft, baggage, meal, punctuality, seats, tax, refund, alignment, capture time, raw row, evidence fingerprint, landing page, conclusion, note; BOM+RFC4180) and evidence JSON (raw + provenance), plus single-row evidence JSON copy. `probe://srx` state strings (mirror tab, calendar axis and detail tab included) and up to 12 local snapshots.
- **Real coverage**: each channel moves with its live login/session state — Qunar's PC web flight site retired on 2026-10-10 and its H5 returns no fares anonymously, so a login session is required; Tongcheng may return a 444 session gate, Ctrip international uses its PC flight list (calendar is only a fallback and is marked “needs login” when the session lapses), Tuniu international may be unavailable. The UI labels this round as **flight-level / calendar / fallback / unavailable / needs login** instead of freezing one snapshot into a fixed coverage claim. Calendar-only thin rows carry no flight number or times, are never marked qualified and never enter same-flight ladders; the 14-day band only draws real departure days. Missing is shown as missing, never synthesized.

![Triple alignment: parsed ⇄ mirror ⇄ raw](docs/screenshots/console-probe-detail.png)

![Flight × channel matrix](docs/screenshots/console-probe-matrix.png)

![Five-platform calibration book](docs/screenshots/console-probe-gallery.png)

**Routine settings hot-reload on save; startup-level changes show a diff and require a restart**: routes, thresholds, notifiers (DingTalk / ntfy / **Bark** / Aliyun / ServerChan / email, each with a one-click test button — the Windows toast test fires a real local notification), scan interval & jitter, console port (rebound in place), headless mode, crawler timeouts & pacing, user-agent, debug dumps, daily-report hour, image host, **date quick-picks & range select / direct-flights-only toggle / round-trip multi-return dates / airline whitelist (three equivalent writings — `MU` / `China Eastern` full name / `东航` short alias, auto-normalized to the code with a live resolution preview as you type; `!` prefix = exclusion) / no-LCC / min baggage / wide-body / price ceiling / max total flight duration in hours (incl. layovers, 0.5h steps) / no-overnight / departure & arrival time windows (both support overnight wrap-around windows)**. The **Global config center** groups schedule / crawler / general with 🔥 hot badges; startup-level paths (database, log, browser profile, chromium cache) are **editable**, each showing its resolved **absolute path** with a 📂 open-folder button — old database & login-state files auto-migrate on path change. Settings also support field-level search, `Ctrl/⌘+S` save, and export/import of the whole config as JSON.

### Real-time search (real collected data)

The **Search** tab is an independent workbench over the real `/api/state` rows — no mock data.
It chains **14-day fare band → five-channel source cards → filters → list / flight×channel matrix → structural mirror → triple-aligned detail → sign-off / export**:

- **Honest source state**: each channel shows real / calendar / fallback / not-supplied, landing-page and raw availability; missing stays “not supplied”, never back-filled with samples. Calendar rows have no flight identity and never qualify.
- **Filters and views**: direct/transfer, cabin, airline, time windows, price band, baggage/meal/LCC/share/cross-day/stop, has landing page/raw, hide calendar, missing-only, complete-only, risk-only; parsed list with 13 field ticks and risk badges; one-click expand; matrix cells open the detail.
- **Mirror and evidence**: the mirror is a structural redraw from the same raw row, explicitly not a screenshot or iframe; detail shows parsed ⇄ mirror ⇄ raw, a 30-day trend, dual-axis calendar and same-flight price ladder.
- **Probe**: full city autocomplete (Chinese / pinyin / IATA) with the same domestic + international panel as the config page; a probe runs real channels but **does not write the DB or push**; no threshold means “probe not evaluated”.
- **Export**: CSV (parsed + raw + provenance), evidence JSON, single-row copy, `probe://srx` state strings, up to 12 snapshots.

### Keyboard shortcuts

| Key | Action |
|---|---|
| `1` / `2` | Monitor console / Config |
| `S` | Jump to the real-time search console |
| `M` (search) | Toggle list / flight×channel matrix |
| `J` / `K` (detail) | Next / previous difference or missing field |
| `↑` / `↓` (list) | Move row and sync the right-hand evidence pane |
| `3` / `4` / `5` / `6` / `7` | Overview / Trend / Watch / Details / Health |
| `Ctrl/⌘ + S` | Save config and hot-reload |
| `R` | Scan now (press again within 3 s to confirm) |
| `/` | Focus search or details search |
| `Esc` | Close overlay / collapse the comparison row |

## Feature matrix

The capability map follows **collect → push → visualize → configure**. Each section is a short table; details live in the live demo and the sections above.

### Collection & monitoring

| Capability | What it does |
|---|---|
| **Five-channel detail** | Qunar / Fliggy / Ctrip / Tongcheng / Tuniu share one schema (price / flight no. / times / transfer / cross-day / duration); each channel uses its best path (Qunar H5 with login, Ctrip PC international list + mobile H5 domestically, Tongcheng H5, Fliggy SSR, Tuniu HTTP, session channels on demand). Eligibility/risk/lure fares carry ⚠ badges. |
| **Multi-date monitoring** | One route can watch multiple departure dates via a **range / specific-day mode bar** (one editor open at a time, both drafts kept); future 7/30 days, a start–end range or single days merge and de-duplicate; each date is collected, pushed and charted independently; route cloning copies all settings. |
| **Round-trip multi-return** | A round-trip switch with **multiple return dates** (7/8 days from the outbound, a range, or day-by-day); collection runs per pair and the price is the tax-inclusive round-trip total. |
| **Enable / pause** | Each route has an enable switch: pausing keeps every setting and exempts scheduling / push / details — pausing no longer means deleting. |
| **Qualification** | Separate direct/transfer thresholds; route-level gates for airline whitelist (code / full name / short alias, `!` = exclude), no LCC, no stop/share, free baggage ≥N kg, wide-body, price ceiling, max total duration, no overnight, departure/arrival wrap-around windows, transfer connection limits, baggage-through and latest transfer arrival. Only current-round data qualifies. |
| **Multi-user** | Each user has their own routes, thresholds and DingTalk group; identical routes are collected once with staggered queries. |

### Special fares & international

| Capability | What it does |
|---|---|
| **Special-fare discovery** | Search five official sources by departure, destination and date range: Ctrip low-price calendar + national board, Qunar official H5 deals (page-generated signature), Fliggy cheapestCalendar (fallback board on soft refusal), Tongcheng low-price calendar, and Tuniu's domestic H5 calendar. Every price carries its tax basis. The radar persists each monitored date/range, shows a calendar and monitoring trend, and links the low-price date to already-collected real flights (or a one-click detail probe); calendar/board prices remain discovery only. |
| **International monitoring** | Still only IATA codes: any endpoint outside the mainland set switches to international automatically (five continents, zero config); price is always **tax-inclusive**, tax shown separately; cross-day allows 0–7 days and duration is timezone-corrected; the city panel has a 🌐 international tab grouped by region (272 cities / 33 hot) with three search paths. |
| **Price guards** | Outlier/low-lure guards scale with the international range; calendar/thin rows never qualify or enter same-flight comparison. |

### Push & alerts

| Capability | What it does |
|---|---|
| **Aggregated push** | One message per round across routes; qualified sections float to the top; **three-line KPI** + semantic dots (🎯 hit / 🟩 break-line / 🟨 near) + 💡 suggestion + 📉 7-day trend; every line is width-guarded for phones and always keeps price / flight / verdict; channel failures self-report at the bottom. |
| **Urgent alerts** | DingTalk @phone + storm repeat + **Windows toast (click opens the single-flight detail)** + ntfy popup/ring + **Bark iOS** (self-hosted server supported) + Aliyun call/SMS; 2 h / further ¥50 de-bounce. |
| **Quiet hours** | A wrap-around window (e.g. 23:00–07:00) suppresses market heartbeats / storm / calls, while the main qualified push and ntfy still go out. |
| **Preview & history** | 👁 local approximate DingTalk rendering without waiting for a round; 📨 every send is archived (including failures) and replayable in the console. |

### Visualization & interaction

| Capability | What it does |
|---|---|
| **Trends** | Line + gradient area and **K-line** (OHLC hover, red up / green down); 48 h / 7 d / 30 d / 90 d / half-year; the lowest point is labelled with its date and time. |
| **Watch studio** | Switch flights by route; full-width real trend (line/K-line × ranges), target runway, channel coverage, status/target/airline/direct-transfer/time filters; overview watch cards mirror the same data (7-day sparkline, coverage, 30-day jump); the config page creates and edits a watch only inside a configured route/date (live candidates, channels/target/notify/note); any flight can be previewed from the search list without watching it first. |
| **Official brand layer** | Five channels and 87 airlines use locally embedded official app/site icons where verified: square app tiles for channels, circular carrier avatars for airlines, across search/mirror/detail/matrix/watch/config; unknown carriers fall back to a circular IATA code, with zero runtime external links. |
| **Flight-level history** | Every full route scan writes each collected flight into `flight_daily` day buckets (platform/cabin × daily OHLC), independent of watch config; long windows survive raw cleanup; `/api/srx/flight/trend` works for any flight. |
| **Four-tier rings** | ● deep green = real hit / ○ thin green = break-line / ○ amber = near / ▼ red = hit released — the same language as push copy, details 🔥 and calendar colors. |
| **Calendar, table, health** | 14-day lowest-price heat cards + 7-day insight; 20+ filter dimensions, CSV export and per-row booking links; channel health shows per-round stripes/logs and push-channel health; the pulse card keeps a persisted ring buffer; six monitor views (overview, specials, route trend, watch trend, watch details, channel health) keep one session each; browser notifications for hits. |

### Configuration & reliability

| Capability | What it does |
|---|---|
| **Panel config** | Left-side partitions (channel login / users & routes / flight watch / global), one section on screen; high-frequency route fields first, low-frequency constraints collapsed; every field explains itself and sections show live summaries. |
| **Global config center** | Schedule/crawler parameters hot-reload; startup-level paths (DB / log / login state / Chromium dir) are editable with 📂 open-folder and auto-migrate on change; illegal paths, four paths in one place, non-writable paths and illegal listen addresses are blocked before save; every channel has a real test button. |
| **Hot reload** | Routes, thresholds, push, interval, **port rebind**, headless, timeouts, pacing, daily report hour and image host take effect on save; DB/log/login/Chromium/listen/scan-on-boot show an old→new diff and a restart prompt. |
| **Search & import/export** | Field-level search; JSON export/import (credentials stay local); dirty-change count and validation before save; `Ctrl/⌘+S`. |
| **Login, demo, data window** | One-click browser login for each channel (no CLI); `--demo` zero-config demo and a static Pages demo from the same render chain; detail rows auto-clean after 14 days while daily buckets keep 400 days; trends replay 48 h–half-year. |
| **Reliability** | Single-instance lock, DingTalk -1 no-retry, visible channel failures, first-round throttling; link-provenance CI gate from crawler to UI; image failure falls back to text so information never vanishes. |

## Quick start (prebuilt, no Python needed)

1. Download your platform package from [Releases](https://github.com/dengmeiluan/ticket-monitoring/releases) (about 60–94 MB):
   Windows `…-win64.zip` / Linux `…-linux-x64.zip` / Apple Silicon `…-macos-arm64.zip` / Intel Mac `…-macos-x64.zip`.
2. Unzip anywhere and run it: Windows `TicketMonitor.exe`;
   Linux/macOS `chmod +x TicketMonitor && ./TicketMonitor`.
3. Open `http://127.0.0.1:8765` → ⚙️ Settings: add routes (Chinese city names with autocomplete), target prices, and your DingTalk robot Webhook + signing secret. Hit 「🔔 测试推送」 to verify.
4. Save — monitoring starts immediately.

> Ctrip and Qunar require a login session (`--login ctrip` / `--login qunar`); Qunar's login opens the unified account page (SMS code / QR), and its H5 only returns full detail when signed in. Tongcheng is best after a login session; Tuniu requires a login for its domestic list (international works anonymously); Fliggy works anonymously domestically, while its international list needs a login session.

### Docker / NAS

```bash
cp config.example.yaml config.yaml   # first run: create config (or do it in the web UI)
docker compose up -d
```

Open `http://NAS_IP:8765`. Config, the price database (`data/`), browser sessions (`user_data/`) and logs all live in local volumes — upgrades and rebuilds keep your data. The image ships chromium and CJK fonts (~1.5 GB, no first-run browser download). The Windows toast channel auto-disables inside containers; DingTalk/email pushes are unaffected. On a NAS without Docker, grab `…-linux-x64.zip` and run it directly.

## Special fares monitoring

Don't want to pin fixed routes? The special-fares watch takes just **departure city + target price** and discovers deals on its own:

- **Five-source discovery**: Ctrip low-price calendar and national board, Qunar's official H5 deal deep-link (the page generates its own signature; saved sessions read the real response), Fliggy cheapestCalendar (tax-inclusive, 7-day window; a soft refusal falls back to the domestic departure board with a cooldown), Tongcheng `queryCalendarLowestPrice` (login/signature-free; 90 days international, 180 domestic), and Tuniu's domestic H5 same-origin daily calendar (bare price; international stays honestly empty when the source has no official calendar). Each price is labelled with its tax basis and any cache/fallback state; a mixed-basis minimum is marked, never passed off as a like-for-like cheapest.
- **Cross-channel verification**: board/calendar prices alone never trigger a push — on a new low, the live channel crawlers verify the lowest bookable price for that route & date, and **only the verified, actually-purchasable price gets pushed** (bait prices and bare-fare mismatches are filtered out).
- **Direct booking links**: every deal carries the platform's official deep link (round trips get both dates), delivered through all push channels.
- **Spam-free**: the same deal pushes once; a further drop re-pushes; at most 3 verifications per round; quiet hours defer instead of dropping.

Configure it in the console (⚙️ → user card → 🎯 Special fares, three fields, hot-reload) or equivalently in `config.yaml`:

```yaml
users:
- name: your-name
  specials:
  - from: SHA
    from_name: Shanghai
    max_price: 400        # target price
    days: 30              # only departures within 30 days
```

> The Tuniu board's departure city follows this machine's public IP (API limitation) — it only lists deals when the IP city matches; the Ctrip calendar accepts any departure city. Together they cover both cases.
>
> An optional **collection proxy** (`crawler.proxy`, e.g. a local Clash at `http://127.0.0.1:7897`) routes every channel browser and the discovery layer through it — the egress IP becomes configurable (bypasses IP-level rate limits; the Tuniu board city follows the egress IP). Set it in the console (🌐 collection card, hot-reload). Note: rule-based proxy setups usually send domestic sites DIRECT (egress unchanged), which gains nothing for domestic endpoints — use China-direct or load-balanced groups when you actually need IP rotation; overseas exits raise anti-bot risk.

## International flights

Want to watch Tokyo, Bangkok or London? International routes need **zero extra
configuration**: still just three-letter codes (SHA→NRT). When either end sits
outside the mainland city set, the crawler **switches to the international
endpoint automatically** — destinations across five continents, ready to watch:

- **Five-channel international collection**: qunar / fliggy / ctrip /
  tongcheng / tuniu each walk their international surface (international list
  pages / tax-inclusive calendars). Judging, digest push and the detail chain
  need no special-casing — domestic and international routes can be mixed
  freely in one config
- **Tax transparency**: international prices are always the **tax-inclusive
  total** (cross-channel comparison never mixes bases); the tax breakdown
  rides along in detail rows ("incl. tax ¥415") and hit rows are tagged
  tax-inclusive; the fliggy pre-tax surcharge pad is waived for
  international rows
- **Timezone correction**: departure/arrival times are local wall clocks on
  both ends — true duration = naive difference − timezone difference
  (SHA→NRT reads 02:20→06:20, four hours on the clock, three hours in the
  air); the cross-day tolerance widens to 0-7 days so long international
  itineraries are no longer falsely rejected; latest-arrival limits judge by
  local arrival time
- **City panel**: the 🌐 international tab groups 272 destinations (33 highlighted) by region
  (Hong Kong/Macau/Taiwan → Japan/Korea → SE Asia → South Asia → Middle East →
  Europe → Americas → Oceania → Africa), searchable by Chinese name, pinyin
  or code ("dongjing", "成田" and NRT all reach Tokyo Narita); route heads
  show an automatic globe badge
- **Phantom-price guards grade by range**: international prices get their own
  upper bound — full long-haul economy range and premium-cabin low windows
  enter the pool as usual, while polluted page prices are still rejected

No new config fields: fill the city pair as usual — `from`/`to` with
international codes is all it takes.

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
crawlers/          five channels: qunar(H5 primary + PC revival probe) / ctrip / tongcheng(XHR intercept)
                   / fliggy(PC SSR read) / tuniu(httpx reverse)
core/alerter.py    one aggregated push per round; _digest_payload pure builder (reused by console preview)
core/intl.py       international city dictionary / IANA tz offsets / route scope detection (mainland-code single source)
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

## Configuration

Everything is configured in the web ⚙️ Settings page and **hot-reloads on save (no restart)**: routes, targets and departure windows; DingTalk / ServerChan WeChat / ntfy / Bark / Aliyun notifications / email (163/QQ app passwords; the full-page screenshot and chart are embedded in the message — no external image fetch on the receiving side); scan interval and jitter; console port (switched in place); headless browser; fetch timeout and pacing; daily report hour; image host; **date quick/range selection, direct-only, multi-return dates, airline allowlist (three spellings plus `!` exclusion, parsed live), exclude LCC, baggage minimum, large-aircraft-only, price cap, maximum duration, exclude cross-day, arrival window**. `config.yaml` is only the persistence format. The four startup-level paths (database / log / login profile / chromium cache) are editable: each shows its resolved **absolute path** with a 📂 open-folder action, and changing the database or login path **migrates the old file**. A “restart required” banner plus 🔄 one-click restart appears when needed (see `config.example.yaml`).

## Deployment (Windows)

Three PowerShell scripts live at the repo root:

```powershell
.\start.ps1    # start in background (PID in .monitor.pid, logs in logs/)
.\status.ps1   # process / port / last-round status
.\stop.ps1     # stop
```

Auto-start on login: Task Scheduler → Create Basic Task → trigger "At log on" → action runs `start.ps1`.

Linux/macOS from source: `nohup python main.py >/dev/null 2>&1 &`
(wrap it in a standard systemd/launchd service template if needed). The single-instance
lock is native on all three platforms (Windows msvcrt / POSIX flock); a second launch exits.

## Packaging

```bash
pip install pyinstaller
pyinstaller TicketMonitor.spec --noconfirm
# dist/TicketMonitor/ is the complete distributable (Playwright runtime included;
# the Chromium browser itself downloads on first launch, ~120MB)
```

Four assets (three platforms) share one shape: the spec has no Windows-only surface.
Windows / Linux x64 / macOS Apple Silicon / Intel Mac each run the same command on their
own platform (CI matrix `release-build.yml`). Chromium is not bundled — the app installs
the kernel on first launch; the Windows toast channel disables itself on other platforms
while all other channels stay available. All assets attach to one Release and a
`SHA256SUMS.txt` aggregate checksum is archived with each build.

## Development

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q   # full suite: 3703 tests — per-channel parsing units (placeholder guards / pass-through lenses / aggregation safeties) + push-pipeline dry runs + link-provenance gate + chart-vs-list consistency + version gate
python docs/uitest.py             # full UI self-test (628 assertions, self-hosted demo, zero-JS-error hard gate)
python docs/screenshot.py         # regenerate README screenshots (start the demo first: python webui.py --demo --port 8799)
python docs/demo_build.py         # rebake the static demo site (docs/site)
```

## FAQ

**Q: Does leaving the page open cost much?**
A: Polling uses a signature cache + ETag/304 — zero recomputation server-side and zero download browser-side when nothing changed; the page pauses polling when hidden and refreshes once on return.

**Q: Pushes fail with -1 "system busy"?**
A: That's DingTalk's "ghost delivery" — it errors but the message usually did land in the group. Policy is single-send, never retry; losses are naturally covered next round (phone escalation is an independent channel for hits).

**Q: Why is Fliggy sometimes cheaper by 50-100?**
A: Historically Fliggy's PC list showed tax-exclusive fares. Hit qualification now uses the **channel's original price without a tax pad**; international rows always use the **tax-inclusive total**. Any channel-side price-basis note is preserved in details and pushes for verification.

**Q: Ctrip shows "no data this round"?**
A: Login expired — run `--login ctrip` once and re-scan the QR code.

**Q: How do I generate a first configuration with Chinese Q&A?**
A: Run `python main.py --setup` (packaged: `TicketMonitor.exe --setup`). Without a config.yaml, a direct launch creates an empty skeleton and opens the web Settings page; the wizard and the web page are interchangeable.

**Q: How do I configure international routes?**
A: Just enter the IATA codes (for example SHA→NRT or SHA→LHR). When either endpoint is outside the mainland-city set, the app automatically switches to the international endpoint: prices are always tax-inclusive totals, durations are timezone-corrected, and the cross-day window widens to 0–7 days. No extra toggle is needed.

**Q: Do I need to restart after changing settings?**
A: For routine settings, no. Routes/thresholds/notifiers/interval/jitter/port/headless/timeouts/pacing/report hour/image host hot-reload on save. **Startup-level items** (database, log, browser profile, chromium cache, listen address, run-on-start) need a restart: saving shows a diff and a one-click 🔄 restart (spawns the new instance before exiting the old one; the page recovers automatically).

**Q: Will my credentials leak?**
A: Fares and settings live only on your machine (`config.yaml` / `data/`, both git-ignored). Outbound traffic only reaches the push channels and image host you configure. Demo mode and the online demo use synthetic data and never read back real credentials.

Hard-earned lessons (anti-bot, DingTalk quirks, engineering pitfalls): [docs/LESSONS.md](docs/LESSONS.md). Before filing PRs, read [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md).

## License

Apache-2.0. Please respect each platform's terms of service; evaluate compliance before commercial use or redistribution.

## Links

- [LINUX DO community](https://linux.do)
