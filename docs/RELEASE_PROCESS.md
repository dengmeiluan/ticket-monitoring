# Public UI Release & Alignment Process

This is the fixed cadence for every UI/design wave and every public release. It exists so README, screenshots, Release notes, package assets and commit history always tell one story.

## 1. Canonical copy (single source of truth)

The opening blockquote of `README.md` / `README_EN.md` is the original introduction and must not be re-positioned or extended:

```markdown
> 自托管的多渠道机票价格监控：航班明细采集 → 钉钉图文推送 → 达标四层强提醒。
> 国内航线与国际航线（五洲目的地）同一套采集-判定-推送链路。
> 数据留在本机，配置全在网页，开源免费。
```

```markdown
> Self-hosted multi-channel flight price monitoring: fare collection →
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
   - `python tools/test_all.py --workers 8` (default parallel gate: syntax + pytest via xdist + UI self-check side by side)
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q` (serial fallback; same test set as CI, which splits the same files across 4 shards)
   - `python docs/uitest.py`
   - the project’s live 8765 acceptance
   - the channel × domestic/international matrix
   - required performance measurements
   - a **clean clone** full run (`git clone` the exact release tree, no `data/`,
     `logs/`, `_scratch/`) must report **0 skipped** on the 6684-test scale.
     Data/environment skips are release blockers; if an environment-only gate
     (missing font/Chromium/adb) truly cannot run, list it explicitly in the
     release report instead of letting it hide inside a green summary.
3. **Back up** the complete Git history, uncommitted work and necessary audit evidence outside the repository; verify restore. Backups must never enter the public repository or packages.
4. **Converge history**: inventory public branches, tags, Releases and deployments; reduce the final source to a single root initialization commit. Before and after the rewrite, compare the source tree and assert that no verified feature is lost except explicit public-material and distribution cleanup. Check for new remote commits before updating; use operations with expected-state protection. Record the operation in the release notes.
5. **Bump and bake**: only after gates pass, bump the version in `main.py`, its version gate and `docs/release-notes-v<version>.md`; update README/EN counts, screenshots and site. CN/EN README, Release and site keep the full first-release introduction with one chapter order, one screenshot order, one set of facts and one capability boundary. Public material must not accumulate internal rounds, duplicated release prose or development logs.
6. **Rebuild assets**: the history rewrite creates a new SHA; the final packages must be built from that new initialization commit. Trigger `.github/workflows/release-build.yml` (`workflow_dispatch`) on the exact pushed SHA and reject artifacts whose run `head_sha` differs.
7. **Verify packages**: package root layout, no config/data/logs/user_data/ghtoken, packaged executable `--version` equals the release version, all required offline assets present, and SHA256 values. Four platforms must be checked.
8. **Replace the asset set**: one upload per Release under the constant `v1.0` tag — four zips plus one `SHA256SUMS.txt`. Replace the previous set only after the new set is verified with `python tools/verify_release_assets.py --dir dist_package` (exact five files, package roots, no config/data/logs/credentials, SHA256SUMS hashes match). `dist_package/` keeps only those five files; intermediate folders, old packages, check folders and duplicate sha files are removed after checking absolute paths.
9. **Update the single Release**: name is the constant `机票监控台 · 初版（滚动更新）`; body = `docs/RELEASE_BODY.md` with its placeholders filled (canonical intro + current version/counts/source SHA/SHA256; `tests/test_release_body_source.py` guards channel counts/scopes/multi-city honesty/placeholders). Version belongs in the body only, never in the Release name. Keep the tag name constant, but move `v1.0` to the exact verified SHA last, after assets/body, and verify `main.py` at the tag carries the current version. Do not describe a new build as an old SHA artifact or alter the real publication date.
10. **Deploy and align**: update the one active deployment, then `python docs/prune_deployments.py` so only the newest Pages deployment remains; run `python docs/release_align_check.py` until PASS; then verify GitHub source, initialization commit, tag, Release, four packages, SHA256SUMS, CN/EN intro, screenshots, site and live 8765 all agree. Platform-managed audit records, external caches and third-party forks that cannot be removed must be reported honestly, not claimed as cleared.

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

## 6. 预检与并发写陷阱（2026-11-01 实测）

- **站点戳 = `sha256(webui.py)[:12]`**（不是 commit SHA）。任何一次 webui 改动都会让戳立刻过期；冻结点确定后重烘 `python docs/demo_build.py`，再跑对账。2026-11-01 曾烘到 `code:b7cd172d18df` 并通过，随后并行会话在 00:01 改写 webui，戳再次过期——**不要在热树上把 25/25 当最终结论**。
- **对账的 pytest 项数是「已跟踪测试」**（`git ls-files tests` + `pytest --collect-only`），不是工作树全量。新增测试未入库时不计入；把它们 stage/commit 后数字会变。因此：**对齐放最后**，任何 staging/提交之后同步 README/EN 的跟踪口径并重跑 `release_align_check.py --local`。
- **对账的 UI 项数读 `HEAD:docs/uitest_result.txt`**（已提交版本），不是工作树。工作树新跑出 670/670 并不会让对账变 670；发布提交要把新的 uitest 结果一起入库，README 的 UI 断言数同步改成结果文件里的实际值，再对账。
- **全量门禁在并发会话下用 `--workers 4`**：8 worker 曾出现 demo free-port 竞态（`test_r851` setup 连接拒绝，已加三次新端口重试）与内存压力。跑前/跑后必须看工具的 CODE_GLOBS 哈希 WARN；一旦产品代码被改写，整轮作废，不得把其中的 passed 当绿证。
- **线上 8765 只在写会话停止后重启**：比较进程启动时间与 `webui.py` mtime；启动早于最后一次改动即为旧代码。重启后复验 `/api/health` 诊断卡 10 张（5 浏览器 + 5 App）、探针 10 chip、390 无横向溢出。
- **本地 25/25 是快照**：它证明 README/截图/站点戳/计数在当前 tracking 下自洽；在线 Release/tag/四平台包/ghcr 镜像仍需带 token 的在线对账与 `release-build` 工作流。

### 6.1 在线面预检（2026-11-02 01:00 +0800 实测）

本地绿不等于在线自洽。发布前先用 token 核四角；当时在线面有三处不一致，下轮发布必须一并收口：

- **tag 目标 ≠ 已发布源码**：`v1.0` → `02766a3`，但 Release 正文与 `release-build` run `41105554843` 的 `head_sha` 都是 `5cff7f5`；两棵树不同（`5cff7f5` 比 `02766a3` 多 9 个文件改动，含 App 雷达修复）。按 §3.9，tag 必须移到本轮**实际构建**的那个 SHA。
- **站点戳 ≠ 已发布树**：线上 `site/` 的 `tm-build code:` = `2a326e3c8a3d`（=`02766a3:webui.py` 的 `sha256[:12]`），而 `5cff7f5:webui.py` = `5e1f74c5daef`。Pages 部署记录的 sha 虽是 `5cff7f5`，站点内容却是旧树烘的——**部署 sha 不等于烘站源码**。每轮必须在最终树上重烘，戳必须对 `sha256(webui.py)[:12]`。
- **已发布 SHA 的 CI 是红的**：run `41105518625` 在 `5cff7f5` 上 `21 failed / 5185 passed`（r620 无 DISPLAY、r652 Windows 盘符、r675 容器 host 等此后已在本地树修掉，但**下次推送必须等 CI 绿**再动 tag/资产）。
- ghcr 公开镜像当前 `latest` 与 `sha-5cff7f5` 同源；下一轮必须在新 SHA 上重建并推送，`latest` 才能与 Release 对上。

只读核验：`git ls-remote --heads origin`；GitHub API `releases/latest`、`git/ref/tags/v1.0`、`actions/runs`；`curl https://<pages>/site/ | grep tm-build`；匿名 `ghcr.io/token` + `/v2/<owner>/<repo>/tags/list`。

### 6.2 在线对账器与预跑清单（2026-11-02 实测）

- **`git ls-files` 必须用 `-z`**：默认 quotePath 把中文测试名（`tests/test_r643_干预覆盖每个可见渠道.py`）包成引号转义，`startswith("tests/test_")` 过滤掉它 → tracked 计数少 2（HEAD 真实 5445、旧 README 5443；发布应 5885）。普查/计数一律 NUL 分隔，并在提交树上算。
- **GitHub API / SHA256SUMS 走 curl/Schannel**：本机 Python/OpenSSL 无 CA bundle（`C:\Program Files\Common Files\SSL/cert.pem` 不存在），`api.github.com` 报 `unable to get issuer certificate`；curl（Windows 证书库）正常。`_curl` 用 `--config -` 从 stdin 读 token，**不关 TLS 校验**；Pages/ghcr 仍用 urllib。不要给资产 URL 加多轮 retry——代理 502 时重试会把一次失败放大成 60s 挂起。
- **资产 502 的回退**：`SHA256SUMS` 下载失败时，用 release API 的 `digest` 对正文 SHA 做**明确标注**的回退校验；不静默跳过，也不把代理 502 当产品失败。
- **预跑实测（29/46）**：线上正文 intro/version 仍 1.5.306、**正文 SHA 只与 win64 当前资产一致（另 3 个 zip 的 API digest 不在正文）**、Pages 部署 **11 个**、站点戳 `2a326e3c` 旧树、source/tag/CI/release-build/ghcr 不同源；live 8765 1.5.307 通过。发版须重建正文+四资产（同一组 SHA）、`prune_deployments.py` 到 1、重烘站点、CI/release-build 绿、ghcr 新 SHA，再在线对账全绿。
- **计数以冻结后的 tracked 为准**：并行会话与日期参数会让计数漂移；发布前冻结写者、重跑 4w、`git ls-files -z tests` 重新 collect 并同步 README/EN/UI，再做 root commit。
- **资产必须用最终依赖重建**：依赖清单变化后旧资产不可复用——`e65cee1` 四平台包构建早于 `numpy` 声明，冻结包内滑块缺口检测会静默无候选。发版必须按最终 `requirements.txt` 重跑 release-build，并重算四资产 SHA、正文与 `SHA256SUMS.txt`。

### 6.3 发布后在线复核（2026-11-02 发布轮，发布树 0d4b058 / v1.5.307）

> 只读核对，不包含当前工作树未发布的 10 渠道改动。旧 §6.1/§6.2 的
> 「CI 红 / Pages 旧戳 / ghcr 5cff7f5」是 2026-10-31 预跑时的历史问题，
> 本发布轮已全部关闭；不要把那段当现状。
>
> **2026-11-03 09:54 更新**：tag 已重指 `e65cee1`（多 4 个提交），
> ghcr `latest` = `sha-e65cee1` digest `5fb025bb…`（与 Release 同 digest）；
> 下表是 09:20 时点记录，`ab04c22` 现仅对应 live 树。

| 项 | 实测（2026-11-03 09:20） |
|---|---|
| Release | tag 恒定 `v1.0` → `ab04c22`；名称「机票监控台 · 初版（滚动更新）」；正文 `当前版本 v1.5.307 · 源码 ab04c22` |
| 资产完整性 | 4 个平台 zip + `SHA256SUMS.txt`；Release API `digest` 与正文 SHA **4/4 相等**（win64/linux-x64/macos-arm64/macos-x64） |
| CI / release-build / Pages | 三个工作流在 `ab04c22` 上 success；Pages 部署成功 |
| 容器镜像 | 匿名 manifest **200**；`sha-ab04c22` digest `sha256:9b72acb1…`；`latest` = `sha-934e108` digest `sha256:c8fe5de9…`（HEAD 更新，**非同 digest**；要 Release 同源请 pin `sha-ab04c22`） |
| Issue / PR | 0 open / 0 open（GitHub API `open_issues_count=0`） |

**结论**：Release 的 tag、正文、四资产、CI、Pages 已同源；镜像 `latest` 跟随 HEAD，
不再与 Release 源同 digest，对外说明必须区分 `latest` 与 `sha-ab04c22`。
当前工作树另有 r933–r935（多程数据层/配置隔离/实际渠道错峰）未提交；Release `v1.0` 当前 → `e65cee1`（首发 `ab04c22`），live 8765 已切到 `_release_ab04`（10 渠道，PID 47952）。

### 6.4 本地打包环境必须隔离（2026-11-03 实测）

- 本机全局 Python 装有 torch/scipy/onnxruntime 等可选包。直接在本机执行
  `pyinstaller TicketMonitor.spec` 时，分析阶段会处理
  `hook-scipy / hook-torchvision / hook-onnxruntime / hook-tensorflow`，
  远大于发布包（历史 win64 zip 约 63MB）。
- 已停止该临时构建并清理 `_scratch/_pkg_build`、`_scratch/_pkg_dist`；
  **未改 spec、未碰 `dist_package` 发布资产**。
- 发布资产只能由 `release-build` CI 的干净环境（仅 `requirements.txt` +
  pyinstaller）构建。若必须本地验证打包，请用只装 requirements 的专用 venv，
  或在 spec 显式 excludes；**不得把本机污染产物当 Release 资产**。
- 本机未安装 Docker：本地无法构建/运行镜像；镜像发布严格由 `release-build`
  CI 推送，线上只用匿名 token/manifest 核对（`latest` 与 `sha-0d4b058` 同 digest）。
- 干净 venv 验证（2026-11-03 03:35）：PyInstaller 6.22.2 构建成功，`--version=1.5.307`，
  归档含全部 App 模块（`app_tongcheng` / `app_tongcheng_parse` / `app_ctrip_roundtrip` /
  `core.android.ocr`）；候选 zip 按 release-build 的 `make_archive(root_dir=dist/TicketMonitor)`
  根布局打包（根=`TicketMonitor.exe`+`_internal/`），**61,932,953 bytes / 864 entries**，
  SHA256 `3c472292102f8a0d45b06bfaef962a350d513359e3d7bba2666891b8a208a8a4`
  （含同程 App 国际往返与 `PATH_CN["app-roundtrip"]`；r919 旧包 `35a9c2c9…` 已作废）。
  仅存 `_scratch/ticket-monitoring-win64-candidate-root.zip`，未进 `dist_package`、未上传。
- 当前树候选（2026-11-03 23:30，源码 `318a70d`，含 App 设备锁 WIP）：
  PyInstaller 6.22.2 构建成功，`--version=1.5.307`，TOC 含 `core.multicity` /
  `crawlers.ctrip_multicity` / `webui` / `crawlers.captcha` / `crawlers.slider` /
  `core.policy` / `core.android.vendor` / `core.android.hardening`；zip
  **117,001,794 bytes / 1027 entries**，SHA256
  `0c4cc2aa4da3966a0628044ae3bf84ffe4b8144d0ed35ab8c468c75c8064bab4`；
  `_internal` 含 cv2/numpy（干净 venv 已装 numpy 2.4.6 / opencv 5.0.0），
  tests/config/user_data/data 条目 0（`_internal/cv2/data/` 是 OpenCV 合法数据目录）；
  未上传。冻结后重算，不复用；旧 `67babb53` 作废。
