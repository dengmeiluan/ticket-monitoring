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

CN_INTRO = (
    "> 自托管的多渠道机票价格监控：五平台明细采集 → 钉钉图文推送 → 达标四层强提醒。\n"
    "> 国内航线与国际航线（五洲目的地）同一套采集-判定-推送链路。\n"
    "> 数据留在本机，配置全在网页，开源免费。"
)
EN_INTRO = (
    "> Self-hosted multi-channel flight price monitoring: 5-platform fare collection →\n"
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


def gh(path):
    token = ""
    try:
        token = read("ghtoken.txt").strip()
    except OSError:
        pass
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "release-align-check",
    })
    if token:
        req.add_header("Authorization", "token " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def screenshot_refs(md):
    refs = re.findall(r"!\[[^\]]*\]\((docs/screenshots/[^)\s]+)\)", md)
    refs += re.findall(r"<img[^>]+src=\"(docs/screenshots/[^\"]+)\"", md)
    return [r for r in refs if not r.startswith("http")]


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
        tracked_tests = [
            p for p in git("ls-files", "tests").splitlines()
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
    ck("release name carries current version", ver in name, name)
    ck("release body canonical CN intro",
       all(line in body for line in CN_INTRO.splitlines()))
    ck("release body carries current version", ver in body)
    m_date = re.search(r"### ticket-monitoring v[^\n]*?(\d{4}-\d{2}-\d{2})", body)
    pub = (rel.get("published_at") or "")[:10]
    if m_date and pub:
        try:
            ck("release published date matches body",
               date.fromisoformat(pub) >=
               date.fromisoformat(m_date.group(1)) - timedelta(days=1),
               "published=%s body=%s" % (pub, m_date.group(1)))
        except ValueError:
            ck("release published date matches body", False,
               "published=%s body=%s" % (pub, m_date.group(1)))
    ck("release body no internal round jargon",
       not re.search(r"\br3\d{2}[a-z]?\b", body))
    ck("release has four platform zips", len(zips) == 4, ", ".join(zips))
    ck("release has SHA256SUMS.txt", "SHA256SUMS.txt" in names)
    ck("release asset set exact", set(names) == set(zips) | {"SHA256SUMS.txt"},
       ", ".join(names))

    try:
        req = urllib.request.Request(
            "https://github.com/%s/releases/download/v1.0/SHA256SUMS.txt" % REPO,
            headers={"User-Agent": "release-align-check"})
        with urllib.request.urlopen(req, timeout=30) as r:
            sums = r.read().decode("utf-8")
    except Exception as e:
        sums = ""
        print("  (SHA256SUMS fetch failed: %r)" % e)
    sum_lines = [l for l in sums.splitlines() if l.strip()]
    digests = {a["name"]: (a.get("digest") or "") for a in assets}
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
