# -*- coding: utf-8 -*-
"""Public release alignment checker.

Verifies that README / README_EN / screenshots / GitHub Release / assets /
source SHA all tell the same story for the current version.

Usage:
    python docs/release_align_check.py            # full check (needs ghtoken.txt)
    python docs/release_align_check.py --local    # repo-only, skip GitHub API

Exit code 0 only when every check passes. Intended to run after the release
assets and body have been updated (see docs/RELEASE_PROCESS.md).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "dengmeiluan/ticket-monitoring"
API = "https://api.github.com/repos/" + REPO
REL_NAME = "机票监控台 · 初版（滚动更新）"

CN_INTRO = (
    "> 自托管的多渠道机票价格监控：航班明细采集 → 钉钉图文推送 → 达标四层强提醒。\n"
    "> 国内航线与国际航线（五洲目的地）同一套采集-判定-推送链路。\n"
    "> 数据留在本机，配置全在网页，开源免费。"
)
EN_INTRO = (
    "> Self-hosted multi-channel flight price monitoring: fare collection →\n"
    "> rich DingTalk group reports → 4-layer urgent alerts when your target price hits.\n"
    "> Domestic and international routes (destinations across five continents) run\n"
    "> through the same collection → judging → push pipeline.\n"
    "> Your data stays on your machine. Everything is configured in the browser. Free & open source."
)

checks = []


def ck(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(("  OK   " if cond else "  FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def git(*args):
    return subprocess.check_output(["git"] + list(args), cwd=ROOT).decode("utf-8").strip()


def git_z(*args):
    """NUL-separated git output: no core.quotePath C-style quoting.

    `git ls-files` wraps non-ASCII paths in quotes + octal escapes; a
    startswith/endswith filter then drops the test file and the published
    count is short by its tests (2026-11-02 rehearsal: 5883 vs 5885).
    """
    out = subprocess.check_output(["git"] + list(args), cwd=ROOT)
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def _curl(url, token=False, timeout=60):
    """Fetch via curl/Schannel.

    Python's OpenSSL has no CA bundle on some Windows hosts; api.github.com
    fails chain verification while curl (Schannel) succeeds. Keep TLS
    verification on; do not fall back to an unverified context.
    """
    cfg = ['header = "Accept: application/vnd.github+json"',
           'header = "User-Agent: release-align-check"']
    if token:
        try:
            tok = read("ghtoken.txt").strip()
        except OSError:
            tok = ""
        if tok:
            cfg.append('header = "Authorization: token %s"' % tok)
    p = subprocess.run(
        ["curl", "-fsSL", "--max-time", str(int(timeout)),
         "--config", "-", url],
        input=("\n".join(cfg) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("curl %s: %s" % (
            url, p.stderr.decode("utf-8", "replace").strip()[:200]))
    return p.stdout


def gh(path):
    return json.loads(_curl(API + path, token=True).decode("utf-8"))


def screenshot_refs(md):
    refs = re.findall(r"!\[[^\]]*\]\((docs/screenshots/[^)\s]+)\)", md)
    refs += re.findall(r"<img[^>]+src=\"(docs/screenshots/[^\"]+)\"", md)
    return [r for r in refs if not r.startswith("http")]


def _digest_fallback(assets, body):
    """Check zip assets' server-side digests against the release body.

    Returns (checked, total_zips, missing_names). Used when the release
    asset URL is unreachable (local proxy 502); the API `digest` is the
    server-side sha256 of the uploaded file, so this is not weaker for the
    zips. Callers must label the fallback explicitly.
    """
    zips = [a for a in assets if a["name"].endswith(".zip")]
    checked, missing = 0, []
    for a in zips:
        d = a.get("digest") or ""
        if not d.startswith("sha256:"):
            continue
        checked += 1
        if d[7:] not in body:
            missing.append(a["name"])
    return checked, len(zips), missing


def main():
    online = "--local" not in sys.argv
    main_py = read("main.py")
    ver = re.search(r'^__version__\s*=\s*"([^"]+)"', main_py, re.M).group(1)
    head = git("rev-parse", "HEAD")
    print("version=%s head=%s" % (ver, head[:7]))

    readme = read("README.md")
    readme_en = read("README_EN.md")

    ck("CN canonical intro unchanged", CN_INTRO in readme)
    ck("EN canonical intro unchanged", EN_INTRO in readme_en)
    ck("CN no hard-coded version badge", "img.shields.io/badge/version-" not in readme)
    ck("EN no hard-coded version badge", "img.shields.io/badge/version-" not in readme_en)
    ck("CN release badge follows release name",
       "github/v/release/dengmeiluan/ticket-monitoring?display_name=release" in readme)
    ck("EN release badge follows release name",
       "github/v/release/dengmeiluan/ticket-monitoring?display_name=release" in readme_en)
    ck("CN no internal round jargon", not re.search(r"\br3\d{2}[a-z]?\b", readme))
    ck("EN no internal round jargon", not re.search(r"\br3\d{2}[a-z]?\b", readme_en))
    ck("CN no stale extra positioning line",
       "给想自己跑一份价格监控" not in readme)

    notes = "docs/release-notes-v%s.md" % ver
    ck("release notes for current version", os.path.exists(os.path.join(ROOT, notes)), notes)
    if os.path.exists(os.path.join(ROOT, notes)):
        note = read(notes)
        ck("release notes date present", bool(re.search(r"2026-\d{2}-\d{2}", note)))
        ck("release notes no internal round jargon", not re.search(r"\br3\d{2}[a-z]?\b", note))

    # Actual gate counts, not prose.
    try:
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   PYTHONIOENCODING="utf-8")
        # Public counts describe the committed release, not a dirty worktree:
        # an untracked parallel-session test file must not move the badge.
        # -z：中文测试文件名不做 C 风格转义（否则 startswith 过滤掉它，
        # 计数少 2；2026-11-02 彩排实测 5883 vs 真实 5885）。
        tracked_tests = [
            p for p in git_z("ls-files", "-z", "tests")
            if p.startswith("tests/test_") and p.endswith(".py")]
        out = subprocess.check_output(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"] + tracked_tests,
            cwd=ROOT, env=env, stderr=subprocess.STDOUT).decode("utf-8", "replace")
        m = re.search(r"(\d+) tests collected", out)
        pytest_n = m.group(1) if m else ""
    except Exception as e:
        pytest_n = ""
        print("  (pytest collect failed: %r)" % e)
    ck("pytest count readable", bool(pytest_n), pytest_n)
    if pytest_n:
        ck("CN pytest count current", "%s 项" % pytest_n in readme, pytest_n)
        ck("EN pytest count current", "%s tests" % pytest_n in readme_en, pytest_n)

    uitest_n = ""
    try:
        # Public count belongs to the committed release, not a dirty worktree
        # (parallel sessions update docs/uitest_result.txt while auditing).
        res = git("show", "HEAD:docs/uitest_result.txt")
        m = re.search(r"=== (\d+)/(\d+) 通过 ===", res)
        if m and m.group(1) == m.group(2):
            uitest_n = m.group(2)
    except (OSError, subprocess.CalledProcessError):
        pass
    ck("uitest result green and readable", bool(uitest_n), uitest_n or "missing")
    if uitest_n:
        ck("CN uitest count current", "%s 断言" % uitest_n in readme, uitest_n)
        ck("EN uitest count current", "%s assertions" % uitest_n in readme_en, uitest_n)

    cn_refs = screenshot_refs(readme)
    en_refs = screenshot_refs(readme_en)
    refs = sorted(set(cn_refs + en_refs))
    missing = [p for p in refs if not os.path.exists(os.path.join(ROOT, p))]
    ck("all referenced screenshots exist", not missing, ", ".join(missing[:4]))
    ck("CN/EN screenshot sets in parity",
       set(cn_refs) == set(en_refs),
       "cn-only=%s en-only=%s" % (sorted(set(cn_refs) - set(en_refs))[:3],
                                  sorted(set(en_refs) - set(cn_refs))[:3]))
    untracked = []
    for p in refs:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", p],
                           cwd=ROOT, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            untracked.append(p)
    ck("all referenced screenshots are tracked", not untracked,
       ", ".join(untracked[:4]))
    tracked_shots = [p for p in git("ls-files", "docs/screenshots").splitlines()
                     if p.endswith(".png")]
    ref_set = set(refs)
    orphans = [p for p in tracked_shots if p not in ref_set]
    ck("no orphan screenshots", not orphans, ", ".join(orphans[:5]))
    zero = [p for p in refs
            if os.path.exists(os.path.join(ROOT, p))
            and os.path.getsize(os.path.join(ROOT, p)) == 0]
    ck("no zero-byte screenshots", not zero, ", ".join(zero[:4]))
    nested = os.path.join(ROOT, "docs", "screenshots", "docs")
    ck("no nested screenshot junk", not os.path.exists(nested),
       "docs/screenshots/docs exists")

    site = read("docs/site/index.html")
    sm = re.search(r'<meta name="tm-build" content="([^"]+)"', site)
    stamp_ok = False
    stamp_txt = sm.group(1) if sm else "missing"
    if sm:
        parts = sm.group(1).split()
        if len(parts) >= 2 and ver in parts[0]:
            code_hash = "code:" + hashlib.sha256(
                open(os.path.join(ROOT, "webui.py"), "rb").read()
            ).hexdigest()[:12]
            stamp_ok = parts[1] == code_hash
    ck("site build stamp current", stamp_ok, stamp_txt)

    if not online:
        return finish()

    # The local site stamp is computed from the working tree; a dirty webui
    # makes every online stamp comparison meaningless (bake source != HEAD).
    dirty = git("status", "--porcelain", "--untracked-files=no")
    ck("working tree clean at release", not dirty,
       dirty.splitlines()[0] if dirty else "")

    try:
        rel = gh("/releases/tags/v1.0")
    except Exception as e:
        ck("GitHub release readable", False, repr(e))
        return finish()
    body = rel.get("body") or ""
    name = rel.get("name") or ""
    assets = rel.get("assets") or []
    names = sorted(a["name"] for a in assets)
    zips = [n for n in names if n.endswith(".zip")]
    ck("release name is the constant initial title", name == REL_NAME, name)
    ck("release name carries no version", ver not in name and not re.search(r"\d+\.\d+\.\d+", name), name)
    ck("release body canonical CN intro",
       all(line in body for line in CN_INTRO.splitlines()))
    ck("release body carries current version", ver in body)
    m_date = re.search(r"### ticket-monitoring v[^\n]*?(\d{4}-\d{2}-\d{2})", body)
    # The Release is the constant initial release; its body is updated each
    # version, so the body date tracks updated_at, not the initial publish date.
    upd = (rel.get("updated_at") or "")[:10]
    if m_date and upd:
        try:
            ck("release updated date matches body",
               date.fromisoformat(upd) >=
               date.fromisoformat(m_date.group(1)) - timedelta(days=1),
               "updated=%s body=%s" % (upd, m_date.group(1)))
        except ValueError:
            ck("release updated date matches body", False,
               "updated=%s body=%s" % (upd, m_date.group(1)))
    ck("release body no internal round jargon",
       not re.search(r"\br3\d{2}[a-z]?\b", body))
    ck("release has four platform zips", len(zips) == 4, ", ".join(zips))
    ck("release has SHA256SUMS.txt", "SHA256SUMS.txt" in names)
    ck("release asset set exact", set(names) == set(zips) | {"SHA256SUMS.txt"},
       ", ".join(names))

    try:
        deps = gh("/deployments?per_page=100")
        ck("exactly one Pages deployment", len(deps) == 1,
           ", ".join(str(d.get("id")) for d in deps))
    except Exception as e:
        ck("Pages deployments readable", False, repr(e))

    # 部署记录的 sha 只说明「哪次 push 触发了部署」，不证明站点内容来自
    # 那棵树：2026-11-02 实测 main `5cff7f5` / tag `02766a3`，Pages 部署
    # sha 是 `5cff7f5`，而线上站点戳 `2a326e3c` 是旧树 `02766a3` 烘的。
    # 必须读**实际服务的页面**，与发布树（工作树已 clean）的 webui 对戳。
    try:
        pages_url = "https://%s.github.io/%s/site/" % tuple(REPO.split("/"))
        req = urllib.request.Request(
            pages_url, headers={"User-Agent": "release-align-check"})
        with urllib.request.urlopen(req, timeout=30) as r:
            live_site = r.read().decode("utf-8", "replace")
        m_site = re.search(r'<meta name="tm-build" content="([^"]+)"',
                           live_site)
        want_code = "code:" + hashlib.sha256(
            open(os.path.join(ROOT, "webui.py"), "rb").read()
        ).hexdigest()[:12]
        parts = m_site.group(1).split() if m_site else []
        ck("published site stamp matches HEAD",
           len(parts) >= 2 and ver in parts[0] and parts[1] == want_code,
           (m_site.group(1) if m_site else "no tm-build") + " want " + want_code)
    except Exception as e:
        ck("published site readable", False, repr(e))

    try:
        sums = _curl(
            "https://github.com/%s/releases/download/v1.0/SHA256SUMS.txt"
            % REPO, timeout=60).decode("utf-8")
    except Exception as e:
        sums = ""
        print("  (SHA256SUMS fetch failed: %r)" % e)
    sum_lines = [l for l in sums.splitlines() if l.strip()]
    digests = {a["name"]: (a.get("digest") or "") for a in assets}
    if not sum_lines:
        # The release-asset URL can 502 through a local proxy while the API
        # (and its server-side `digest`) is fine. Don't leave a false red:
        # verify the body against the API digests, explicitly labelled.
        checked, total, missing = _digest_fallback(assets, body)
        for name in missing:
            ck("release body has api digest for " + name, False, "sha256 missing")
        ck("asset URL unavailable; API digests cover the zips",
           total > 0 and checked == total and not missing,
           "sums download failed via local proxy; %d zips checked" % checked)
    else:
        ck("SHA256SUMS has four lines", len(sum_lines) == 4, str(len(sum_lines)))
        for line in sum_lines:
            m = re.match(r"([0-9a-f]{64})\s+(\S+\.zip)$", line.strip())
            ck("SHA256SUMS line valid: " + (m.group(2) if m else line[:40]), bool(m))
            if m:
                ck("release body has sha256 for " + m.group(2), m.group(1) in body)
                ck("sha256 asset exists: " + m.group(2), m.group(2) in zips)
                ck("remote digest matches " + m.group(2),
                   digests.get(m.group(2)) == "sha256:" + m.group(1),
                   digests.get(m.group(2), "missing"))

    ck("release source SHA matches HEAD", head[:7] in body, head[:7])
    try:
        remote = git("rev-parse", "origin/main")
        ck("origin/main == HEAD", remote == head, "origin=%s" % remote[:7])
    except Exception as e:
        ck("origin/main readable", False, repr(e))

    # Tag target must carry the shipped version: the Release page's
    # "Source code" link resolves through the tag, not through HEAD.
    tag_ver = ""
    try:
        import base64
        obj = gh("/contents/main.py?ref=v1.0")
        raw = base64.b64decode(obj.get("content") or "").decode("utf-8")
        m = re.search(r'^__version__\s*=\s*"([^"]+)"', raw, re.M)
        tag_ver = m.group(1) if m else ""
    except Exception as e:
        print("  (tag content read failed: %r)" % e)
    ck("tag v1.0 carries current version", tag_ver == ver, tag_ver or "unreadable")
    try:
        ref = gh("/git/ref/tags/v1.0")
        tag_sha = (ref.get("object") or {}).get("sha") or ""
        ck("tag v1.0 target == HEAD", tag_sha == head, tag_sha[:7])
    except Exception as e:
        ck("tag target readable", False, repr(e))
    ck("release target == HEAD",
       (rel.get("target_commitish") or "") in (head, "main"),
       str(rel.get("target_commitish")))

    # CI must be green on the exact source SHA before publishing.
    ci_state = ""
    try:
        runs = gh("/actions/runs?head_sha=%s&per_page=30" % head).get(
            "workflow_runs") or []
        ci = [x for x in runs if x.get("name") == "CI"]
        if ci:
            ci_state = "%s/%s" % (ci[0].get("status"), ci[0].get("conclusion"))
    except Exception as e:
        ci_state = "unreadable:%r" % (e,)
    ck("CI green on HEAD", ci_state == "completed/success", ci_state)
    rb_state = "missing"
    try:
        runs = gh("/actions/runs?head_sha=%s&per_page=50" % head).get(
            "workflow_runs") or []
        rb = [x for x in runs if x.get("name") == "release-build"]
        if rb:
            rb_state = "%s/%s" % (rb[0].get("status"), rb[0].get("conclusion"))
    except Exception as e:
        rb_state = "unreadable:%r" % (e,)
    ck("release-build green on HEAD", rb_state == "completed/success", rb_state)

    # release-build 绿只证明四平台包构建过；镜像是否真的推上 ghcr 取决于
    # 手动勾选的 push_image（issue #8 的原始现象就是「文档写了但没推」）。
    # 匿名 token 能列出 tag，才说明镜像是 public、可直接 docker pull。
    try:
        tok_url = ("https://ghcr.io/token?scope=repository:%s:pull"
                   "&service=ghcr.io" % REPO.lower())
        req = urllib.request.Request(
            tok_url, headers={"User-Agent": "release-align-check"})
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.loads(r.read().decode("utf-8")).get("token") or ""
        req = urllib.request.Request(
            "https://ghcr.io/v2/%s/tags/list" % REPO.lower(),
            headers={"Authorization": "Bearer " + tok,
                     "User-Agent": "release-align-check"})
        with urllib.request.urlopen(req, timeout=30) as r:
            tags = json.loads(r.read().decode("utf-8")).get("tags") or []
        short = "sha-" + head[:7]
        ck("ghcr image is public for HEAD", short in tags and "latest" in tags,
           ", ".join(tags[-8:]))
    except Exception as e:
        ck("ghcr image readable", False, repr(e))

    # Live console is required for alignment; no silent skip.
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=3) as r:
            live = json.loads(r.read().decode("utf-8"))
        ck("live 8765 version == source", str(live.get("version") or "") == ver,
           str(live.get("version") or ""))
    except Exception as e:
        ck("live 8765 reachable", False, repr(e))

    return finish()


def finish():
    bad = [n for n, ok, _ in checks if not ok]
    print("\n=== %d/%d passed ===" % (len(checks) - len(bad), len(checks)))
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("PASS: public README / screenshots / Release / assets / source are aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
