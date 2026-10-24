# Public UI Release & Alignment Process

This is the fixed cadence for every UI/design wave and every public release. It exists so README, screenshots, Release notes, package assets and commit history always tell one story.

## 1. Canonical copy (single source of truth)

The opening blockquote of `README.md` / `README_EN.md` is the original introduction and must not be re-positioned or extended:

```markdown
> 自托管的多渠道机票价格监控：五平台明细采集 → 钉钉图文推送 → 达标四层强提醒。
> 国内航线与国际航线（五洲目的地）同一套采集-判定-推送链路。
> 数据留在本机，配置全在网页，开源免费。
```

```markdown
> Self-hosted multi-channel flight price monitoring: 5-platform fare collection →
> rich DingTalk group reports → 4-layer urgent alerts when your target price hits.
> Domestic and international routes (destinations across five continents) run
> through the same collection → judging → push pipeline.
> Your data stays on your machine. Everything is configured in the browser. Free & open source.
```

Rules:
- No hard-coded `Version` badge. The Release badge is the single version pointer: use `github/v/release?display_name=release` so it follows the Release name (the constant `v1.0` tag is not a version).
- No internal round jargon (`r348`, “production probe”, etc.) in public copy.
- CN/EN section order, screenshot order, feature counts and claims stay in parity.
- The Release body starts with the canonical one-paragraph intro; version, gate counts, source SHA and SHA256 follow it. Do not rewrite the intro per release.
- Feature facts must match the shipped build: monitor tabs, config partitions, `SHA256SUMS.txt`, actual platform count/sizes.
- Current capability descriptions must match the live implementation; do not keep “four sources” or old “not connected” wording after a source is integrated.

## 2. Every UI wave (fixed rhythm)

1. **Deep-check GitHub**: `git fetch origin --prune`; read `origin/main`, latest Release name/body/assets, README/EN and screenshots. Record the remote SHA/version and compare with local. Never design against stale visuals.
2. **Concurrent audits**: at least the five fixed areas — configuration cards/settings rails, filter/table workbench, overlays (modals/popovers/savebar/toasts), global text clipping/overflow, buttons/actions/touch. For cross-page work add product semantics, watch/trend, filter consistency, official assets, first-paint state and performance. Each audit must return viewport, selector, rects and file:line; the main agent owns final integration.
3. **Implement** the P0/P1 findings; do not add new decorative scope. Keep one canonical action per job and one page identity. Shared defects must be fixed at the common component or root cause, not as per-page CSS patches.
4. **Add a gate for every fixed defect**, at the viewport where it was found (320/390/671/768/1024/1280/1360/1512/1920). A fix without a gate is not done.
5. **Bake docs**: regenerate `docs/screenshots`, rebuild `docs/site/index.html`, update README/EN feature counts and alt text, and add `docs/release-notes-v<version>.md`.
6. **Verify pixels**: Playwright light/dark at the affected widths, zero pageerror, no horizontal overflow, no text/button intersections. Check 100%/125%/200% zoom in a real browser or equivalent layout condition, not only via device scale factor. Compare the rendered page against the screenshot/initial intro standard.
7. **Keep the working tree coherent**: do not commit partial parallel-session work; do not rewrite unrelated history. Process commits are local working history only — the public history is converged at delivery (§3).

## 3. Final public form: one initialization commit, one first release

This is the fixed public shape. Working commits are process history, not the public story.

The final public form must have all of the following simultaneously:

- One initialization commit containing the complete current delivery.
- One official Release.
- One active public deployment.
- One current asset set: four platform zips + `SHA256SUMS.txt`.
- One complete CN/EN introduction, screenshot set and capability statement matching the first-release positioning.

Release cadence:

1. **Freeze** parallel writers; confirm `webui.py`, backend, tests and docs are the same coherent state. Do not build from a moving worktree.
2. **Integrate** the complete feature backend, tests and pins. Run, and only proceed when all are green:
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q`
   - `python docs/uitest.py`
   - the project’s live 8765 acceptance
   - the channel × domestic/international matrix
   - required performance measurements
3. **Back up** the complete Git history, uncommitted work and necessary audit evidence outside the repository; verify restore. Backups must never enter the public repository or packages.
4. **Converge history**: inventory public branches, tags, Releases and deployments; reduce the final source to a single root initialization commit. Before and after the rewrite, compare the source tree and assert that no verified feature is lost except explicit public-material and distribution cleanup. Check for new remote commits before updating; use operations with expected-state protection. Record the operation in the release notes.
5. **Bump and bake**: only after gates pass, bump the version in `main.py`, its version gate and `docs/release-notes-v<version>.md`; update README/EN counts, screenshots and site. CN/EN README, Release and site keep the full first-release introduction with one chapter order, one screenshot order, one set of facts and one capability boundary. Public material must not accumulate internal rounds, duplicated release prose or development logs.
6. **Rebuild assets**: the history rewrite creates a new SHA; the final packages must be built from that new initialization commit. Trigger `.github/workflows/release-build.yml` (`workflow_dispatch`) on the exact pushed SHA and reject artifacts whose run `head_sha` differs.
7. **Verify packages**: package root layout, no config/data/logs/user_data/ghtoken, packaged executable `--version` equals the release version, all required offline assets present, and SHA256 values. Four platforms must be checked.
8. **Replace the asset set**: one upload per Release under the constant `v1.0` tag — four zips plus one `SHA256SUMS.txt`. Replace the previous set only after the new set is verified. `dist_package/` keeps only those five files; intermediate folders, old packages, check folders and duplicate sha files are removed after checking absolute paths.
9. **Update the single Release**: name/body = canonical intro + current version/counts/source SHA/SHA256. Keep the tag name constant, but move `v1.0` to the exact verified SHA last, after assets/body, and verify `main.py` at the tag carries the current version. Do not describe a new build as an old SHA artifact or alter the real publication date.
10. **Deploy and align**: update the one active deployment; run `python docs/release_align_check.py` until PASS; then verify GitHub source, initialization commit, tag, Release, four packages, SHA256SUMS, CN/EN intro, screenshots, site and live 8765 all agree. Platform-managed audit records, external caches and third-party forks that cannot be removed must be reported honestly, not claimed as cleared.

Do not push, retag, publish or rewrite shared history without explicit user authorization.

## 4. Definition of done

- README/EN canonical intro unchanged; no stale version/count/jargon.
- All referenced screenshots exist, are tracked, non-zero, current, width-capped on mobile, and match the shipped UI.
- Release name/body/assets/source SHA are version-consistent; four platform packages verified.
- `v1.0` tag target carries the current version; CI is green on the exact source SHA.
- pytest + uitest green with zero pageerror; the exact pushed SHA produced the assets.
- Local live console and GitHub public page show the same current design.
- Public history is exactly one initialization commit; one Release, one deployment and one current asset set.
- `dist_package/` holds exactly the four current zips + `SHA256SUMS.txt`.

## 5. Artifact & history hygiene

- `dist_package/` is a delivery surface, not a workshop: keep only `ticket-monitoring-win64.zip`, `ticket-monitoring-linux-x64.zip`, `ticket-monitoring-macos-arm64.zip`, `ticket-monitoring-macos-x64.zip` and `SHA256SUMS.txt`. Delete `_check*`, `_ci`, `release_*`, `_r*_dist`, `_rel_*` and ad-hoc `.sha256` files as soon as they are superseded.
- Release notes live in `docs/` and are tracked; `.gitignore`'s root-only `/RELEASE-*.md` rule must never swallow `docs/release-notes-*.md`.
- Public history is a single initialization commit. Working commits and fixups are temporary and must be converged before publication; never expose the development train as the public story.
- One GitHub Release, one Pages deployment, one asset set. Do not upload intermediate builds or re-bake identical screenshots just to create a new commit.
- A history rewrite must be explicit: freeze writers, create a backup branch outside the public line, verify pre/post tree equality, then re-point `main` and `v1.0` with expected-state protection and rebuild assets from the new SHA.
