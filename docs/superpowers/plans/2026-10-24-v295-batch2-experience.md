# v1.5.295 Batch 2 — Visual, Mobile and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the flat/unified console language, make folds and mobile surfaces truthful and usable, add a restrained Sector Strip signature, and land measurable search-filter performance without overclaiming.

**Architecture:** CSS/token consolidation plus small JS helpers inside `webui.py`. No new frontend framework. Visual changes stay behind existing classes; screenshots and UI gates prove pixels at exact widths/themes. Performance work is limited to the measured hot paths (closed facet panel, repeated row icons) with a reproducible 4× CPU gate.

**Tech Stack:** Python 3.11, inline CSS/JS in `webui.py`, Playwright, Node `--check`, existing `docs/uitest.py`.

**Spec:** `docs/superpowers/specs/2026-10-24-v295-evidence-first-design.md`

## Global Constraints

- All new radii/shadows/prices use shared tokens; no page-local one-off values.
- No animated decoration; hover does not move layout.
- Mobile must remain usable at 320/390; no horizontal page overflow.
- Accessibility: visible focus, `aria-expanded`/`aria-controls` truthful, chart has a text/data alternative.
- Performance claims must come from `docs/perf_gate.py` output, not estimates.
- No release/push/tag in this batch.

---

### Task 1: Token consolidation, one title, one price grammar, two login surfaces

**Files:**
- Modify: `webui.py` (v294 flat block ~6423; watch markup ~6750; login CSS ~1848/6457; price CSS ~1014/3854)
- Test: `tests/test_v295_tokens.py` (create)

**Interfaces:**
- Produces CSS tokens: `--r-card:14px`, `--r-container:12px`, `--r-ctl:8px`, `--price-lg:24px`, `--price-md:19px`, `--price-sm:16px`.
- No API change.

- [ ] **Step 1: Write failing source/UI tests**

```python
def test_tokens_and_single_watch_title():
    src = open("webui.py", encoding="utf-8").read()
    assert "--r-card:14px" in src and "--r-container:12px" in src
    assert "--price-lg:24px" in src
    # one visible 关注航班 title, not seclab + h2 duplicate
    assert src.count('<h2 class="ws-title"') == 0

def test_login_has_one_nested_surface():
    src = open("webui.py", encoding="utf-8").read()
    assert "#loginRows .lgslot{background:transparent" in src
    assert "#loginRows .lgcard{box-shadow:none" in src
```

- [ ] **Step 2: Run and confirm failure** — missing tokens/markup.

- [ ] **Step 3: Implement tokens and CSS**

Add near v294 flat block:

```css
:root{--r-card:14px;--r-container:12px;--r-ctl:8px;
 --price-lg:24px;--price-md:19px;--price-sm:16px}
.ucard.mon-card,#montab-watch .ws-card,#searchview .srx-list,
#searchview .srx-mirror,#cfgview .ucard{border-radius:var(--r-card)!important;
 box-shadow:none!important;border-color:transparent!important}
.ws-card{border-radius:var(--r-card)!important;box-shadow:none!important}
.kpi .num{font-size:var(--price-lg)!important;color:var(--r-ink)!important}
.srx-price b{font-size:var(--price-md)!important;color:var(--r-ink)!important}
.spmon-lowday .p{font-size:var(--price-lg)!important;color:var(--r-ink)!important}
#loginRows .lgcard{box-shadow:none!important;border-color:transparent!important;
 background:var(--r-surface-2)!important;padding:12px!important}
#loginRows .lgslot{background:transparent!important;border-top:0!important;
 padding-top:0!important}
```

In watch markup remove the duplicate visible title: keep the `.seclab` (`关注航班`) and delete the `<h2 class="ws-title">…</h2>` block; keep any subtitle/role text below. If the h2 carried the route name, move that text into the existing `.ucard .uhead` subtitle.

- [ ] **Step 4: Run source test + UI gate**

`pytest tests/test_v295_tokens.py -q`, then `python docs/uitest.py`. Expected: source test PASS, UI 628+ with one radius family; if a gate expects 31px numerals, update it only if the new measured value is intentional and documented.

- [ ] **Step 5: Commit**

```bash
git add webui.py tests/test_v295_tokens.py
git commit -m "style: consolidate card radius, price grammar and login surfaces"
```

---

### Task 2: Sector Strip signature on three surfaces

**Files:**
- Modify: `webui.py` (CSS near `.spmon-*`; JS helpers; overview/watch/radar templates)
- Test: `tests/test_v295_sector_strip.py` (create)

**Interfaces:**
- `sectorStripHTML({from,to,target,price,status,cls,link}) -> str`
- CSS `.sector-strip`, `.ss-route`, `.ss-rail`, `.ss-notch`, `.ss-price`, `.ss-state`.

- [ ] **Step 1: Write failing tests**

```python
def test_sector_strip_component_and_surfaces():
    src = open("webui.py", encoding="utf-8").read()
    for s in ("function sectorStripHTML", "class=\"sector-strip",
              "spMonLow", "renderMonWatch", "ws-route"):
        assert s in src, s
```

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement CSS/JS**

```css
.sector-strip{display:flex;align-items:center;gap:10px;min-height:44px;
 padding:4px 10px;border-radius:var(--r-container);background:var(--r-surface-2);
 font-family:var(--num);color:var(--r-ink)}
.ss-route{font-size:12px;font-weight:700;letter-spacing:.4px;white-space:nowrap}
.ss-rail{position:relative;flex:1 1 auto;height:2px;background:var(--r-hair)}
.ss-notch{position:absolute;top:-3px;width:8px;height:8px;border-radius:50%;
 background:var(--r-signal);box-shadow:0 0 0 2px var(--r-surface-2)}
.ss-price{font-size:var(--price-md);font-weight:700;white-space:nowrap}
.ss-state{font-size:10px;font-weight:700;white-space:nowrap;color:var(--r-ink-3)}
.sector-strip.low .ss-notch,.sector-strip.hit .ss-notch{background:var(--r-signal)}
.sector-strip.hit .ss-state{color:var(--r-signal)}
```

Add `--r-signal` to the token block if absent (use the existing red/amber semantic token; do not introduce a new hue).

JS helper:

```js
function sectorStripHTML(o){
 const a=he(o.from||'—'),b=he(o.to||'—');
 const t=Number(o.target||0),p=o.price==null?'—':'¥'+he(String(o.price));
 const pos=t>0?' style="left:'+Math.max(4,Math.min(96,100-(Number(o.price)/t)*100))+'%"':' style="left:50%"';
 return '<div class="sector-strip '+(o.cls||'')+'" title="'+he(o.title||'')+'">'
  +'<span class="ss-route">'+a+' <span style="color:var(--r-ink-3)">→</span> '+b+'</span>'
  +'<span class="ss-rail"><i class="ss-notch"'+pos+'></i></span>'
  +'<span class="ss-price">'+p+'</span><span class="ss-state">'+he(o.status||'')+'</span></div>';
}
```

Insert:
- `spMonLow`: above low-day header, `sectorStripHTML({from:q.from,to:sel.to||q.to,price:sel.price,target:0,status:sel.basis==='tax_included'?'含税':(sel.basis==='bare'?'裸价':'口径未标'),cls:'low'})`.
- Watch route summary: replace the route/target text row with `sectorStripHTML({from:...,to:...,price:...,target:...,status:...})`.
- Overview watch cards: render one strip above the mini chart, replacing the 3px channel bar.

- [ ] **Step 4: Run UI gate + screenshots at 1512/390**

Check `.sector-strip` count >= 3 on monitor, no overflow, price/status not clipped. Expected PASS.

- [ ] **Step 5: Commit**

```bash
git add webui.py tests/test_v295_sector_strip.py
git commit -m "style: add sector strip signature"
```

---

### Task 3: Fold truth, mobile five-source, calendar affordance, chart fallback

**Files:**
- Modify: `webui.py` (`srxFold`, restore block ~7627; hero markup; brief/grid CSS; spMonRender/JS; chart markup)
- Test: `tests/test_v295_mobile_fold.py` (create)

**Interfaces:**
- `srxSetFold(id, folded)` updates class/storage/button text/`aria-expanded`/`aria-controls`.
- `spMonCalFit()` sets `xhint` and scrolls selected date into view.

- [ ] **Step 1: Write failing tests**

```python
def test_fold_aria_restore_source_pins():
    src = open("webui.py", encoding="utf-8").read()
    for s in ("aria-controls", "srxSetFold", "srx-folded",
              "innerWidth<=900", "spMonCalFit"):
        assert s in src, s
```

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement**

Replace fold function:

```js
function _foldName(btn,id){
 const cur=String(btn.textContent||'').trim();
 const base=cur.replace(/^(收起|展开)/,'')||'详情';
 return (id?base:base);
}
function srxSetFold(id,folded){
 const el=$(id);if(!el)return;
 el.classList.toggle('srx-folded',!!folded);
 document.querySelectorAll('[onclick*="'+id+'"]').forEach(btn=>{
  if(!btn.classList.contains('srx-foldbtn'))return;
  const base=_foldName(btn,id);
  btn.textContent=(folded?'展开':'收起')+base;
  btn.setAttribute('aria-expanded',folded?'false':'true');
  btn.setAttribute('aria-controls',id);
 });
}
function srxFold(id,btn){const el=$(id);const folded=!el.classList.contains('srx-folded');
 srxSetFold(id,folded);
 try{const m=JSON.parse(localStorage.getItem('jpsrx_folds')||'{}');m[id]=folded;
  localStorage.setItem('jpsrx_folds',JSON.stringify(m))}catch(e){}
}
try{const _fm=JSON.parse(localStorage.getItem('jpsrx_folds')||'{}');
 Object.keys(_fm).forEach(id=>{if(_fm[id])srxSetFold(id,true)});
}catch(e){}
```

Move the hero fold button after the `srxHeroSub` paragraph so mobile static flow is below the copy. Add:

```css
@media(max-width:900px){
 .srx-hero-copy .srx-foldbtn{position:static;display:inline-flex;margin:6px 0 0 auto}
}
#searchview .srx-grid:has(.srx-mirror.srx-folded){grid-template-columns:1fr}
@media(min-width:901px) and (max-width:1100px){
 #searchview .srx-brief{display:flex!important;overflow-x:auto}
 #searchview .srx-brief .srx-src{flex:0 0 168px}
}
#searchview .srx-src-h{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.spmon-cal.xhint{-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 24px),transparent);
 mask-image:linear-gradient(to right,#000 calc(100% - 24px),transparent)}
```

Calendar fit in `spMonRender` after setting `cal.innerHTML`:

```js
try{
 const _cal=$('spMonCal');
 if(_cal){
  _cal.classList.toggle('xhint',_cal.scrollWidth>_cal.clientWidth+4);
  const _sel=_cal.querySelector('.spmon-day.sel');
  if(_sel)_sel.scrollIntoView({inline:'nearest',block:'nearest'});
 }
}catch(e){}
```

Chart markup: add `role="img" aria-label="特价监控时间轴"` to `#spMonChart`, add a hidden `<table id="spMonTable" class="sr-only">` after it; in `spMonRender` fill rows date/price/channel. Add `.sr-only` CSS.

Low-day flight mobile:

```css
@media(max-width:360px){
 .spmon-flight{grid-template-columns:1fr auto;grid-template-areas:"fid fpr" "ftime ftime"}
 .spmon-flight .fid{grid-area:fid}.spmon-flight .ftime{grid-area:ftime;white-space:normal}
 .spmon-flight .fpr{grid-area:fpr}
}
```

- [ ] **Step 4: Run UI gate at 320/390/901/1024/1360**; assert fold button not over meta, five sources no overlap, calendar selected visible, no overflow.

- [ ] **Step 5: Commit.**

---

### Task 4: Performance guard and reproducible gate

**Files:**
- Modify: `webui.py` (`srxApplyFilterChange`/`srxRenderFacets` ~17042)
- Create: `docs/perf_gate.py`
- Test: `tests/test_v295_perf_source.py` (create)

**Interfaces:**
- `srxRenderFacets(force)` returns immediately when `!SRX.more && !force`.
- Perf gate outputs JSON: viewport, rows, p50/p95/max, throttle.

- [ ] **Step 1: Write failing source test**

```python
def test_facets_guard_when_closed():
    src = open("webui.py", encoding="utf-8").read()
    assert "if(!SRX.more&&!force)return" in src
    assert os.path.exists("docs/perf_gate.py")
```

- [ ] **Step 2: Implement guard**

At top of `srxRenderFacets(force)`:

```js
if(!SRX.more&&!force)return;
```

Ensure the open path calls `srxRenderFacets(true)`.

- [ ] **Step 3: Add perf gate**

`docs/perf_gate.py` starts demo on a free port, loads search, sets 50 rows, runs 25 filter clicks with `Emulation.setCPUThrottlingRate=4`, records `performance.now()` around `renderSearch()`/click, writes `_scratch/perf_v295.json` and prints P50/P95/max. It must not modify repo data. Target: P95 ≤300ms at 50 rows/4×; 200% 24-row P95 ≤200ms.

- [ ] **Step 4: Run**

`python docs/perf_gate.py`; record numbers. If P95 >300, do not claim success; report the measured gap and leave the guard in (it is still a measured improvement).

- [ ] **Step 5: Commit.**

---

### Task 5: Docs, site stamp, align-check truth

**Files:**
- Modify: `README.md`, `README_EN.md`, `docs/EXECUTION_SPEC_LATEST.md`, `docs/site/index.html` (generated), `docs/demo_build.py`, `docs/release_align_check.py`, `.github/workflows/release-build.yml`
- Create: `docs/release-notes-v1.5.295.md`

**Interfaces:**
- Site contains `<meta name="tm-build" content="<version> <sha> <date>">`.
- Align check fails if live 8765 is unavailable or remote asset digest differs.

- [ ] **Step 1: Fix stale copy**

README line ~227 and README_EN ~192: `五个子视图` → `六个子视图` / `five sub-views` → `six sub-views`. Confirm the list includes 特价雷达.

- [ ] **Step 2: Site stamp**

In `docs/demo_build.py` `build()`, inject after `<head>` or replace `<title>`:
```python
stamp = ('<meta name="tm-build" content="%s %s %s">'
         % (version, sha, time.strftime("%Y-%m-%d")))
shim = shim.replace("</head>", stamp + "</head>", 1)
```
Use `main.__version__` and `git rev-parse HEAD`; if git unavailable, write `unknown` and let align check fail.

- [ ] **Step 3: Align check**

- Remove the live-skip branch: if `/api/state` unavailable, fail.
- Add: parse `tm-build` from `docs/site/index.html`; require version/sha match HEAD.
- Add: remote asset `digest` equal to `SHA256SUMS` and local `dist_package` file hash.
- Add: GitHub tag ref == HEAD, release target_commitish == HEAD, release name contains version.
- Add: release-build latest run `head_sha == HEAD` and success.

- [ ] **Step 4: Workflow sidecar**

Change `dist_package/${{ matrix.asset }}.sha256` upload path to `dist_package/${{ matrix.asset }}.zip.sha256`, or remove the sidecar upload entirely (SHA256SUMS is generated later). Prefer removing the sidecar path and keeping only the zip.

- [ ] **Step 5: Release notes**

Create `docs/release-notes-v1.5.295.md` with: schema migrations, alert rules, health classification, provenance level, visual/performance results, exact counts from batch 2 gates, known boundaries. Do not claim release/publish yet.

- [ ] **Step 6: Run align check locally in `--local` mode**; expected all checks pass except online-only checks if deliberately skipped. Commit docs/site/check changes.

---

### Task 6: Batch 2 acceptance

- [ ] **Step 1:** Rebuild screenshots from the new demo; inspect 320/390/1440/1512 light/dark, specials/watch/search/health/login.
- [ ] **Step 2:** Run `python docs/uitest.py` (628+ new assertions), `python docs/perf_gate.py`, full pytest.
- [ ] **Step 3:** Run live acceptance at 320/390/1440/1512 × light/dark, 125%/200% equivalent; check no overflow, specials monitor, health diag, folds, Sector Strip.
- [ ] **Step 4:** Run `docs/search_live_gate.py`.
- [ ] **Step 5:** Report numbers and open boundaries. Do not publish; ask for release authorization separately.

---

## Self-Review

- Spec coverage: Task 1 tokens/login/price; Task 2 signature; Task 3 folds/mobile/a11y; Task 4 performance; Task 5 docs/align; Task 6 gates. Batch 1 covers monitoring/health/provenance.
- No placeholders: all new helpers/tests have concrete code/signatures.
- Risk: Sector Strip placement in existing watch/overview markup may require selector adjustments; keep the component optional per surface and prove with UI count >=3.
- Performance target is a ceiling, not a promise; if missed, report exact P95.
