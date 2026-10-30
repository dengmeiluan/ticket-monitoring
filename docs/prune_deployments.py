# -*- coding: utf-8 -*-
"""Prune GitHub Pages deployment history to one active deployment.

GitHub Pages creates a deployment record for every build on the legacy
branch source. This script keeps the newest deployment (the live one) and
deletes the rest, so the environment does not accumulate history.

Usage:
    python docs/prune_deployments.py --dry-run
    python docs/prune_deployments.py
"""
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "dengmeiluan/ticket-monitoring"
API = "https://api.github.com/repos/" + REPO


def token():
    env = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    with open(os.path.join(ROOT, "ghtoken.txt"), encoding="utf-8") as f:
        return f.read().strip()


def main():
    dry = "--dry-run" in sys.argv
    h = {"Authorization": "Bearer " + token(),
         "Accept": "application/vnd.github+json"}
    deps = requests.get(API + "/deployments?per_page=100", headers=h, timeout=30)
    deps.raise_for_status()
    rows = deps.json()
    if not rows:
        print("no deployments")
        return
    keep = rows[0]["id"]
    print("keep deployment", keep, rows[0].get("sha", "")[:7])
    removed = 0
    for dep in rows[1:]:
        if dry:
            print("would delete", dep["id"], dep.get("sha", "")[:7])
            removed += 1
            continue
        url = API + "/deployments/" + str(dep["id"])
        r = requests.delete(url, headers=h, timeout=30)
        if r.status_code == 422 and "active deployment" in r.text:
            requests.post(url + "/statuses", headers=h,
                          json={"state": "inactive"}, timeout=30).raise_for_status()
            r = requests.delete(url, headers=h, timeout=30)
        if r.status_code in (204, 404):
            removed += 1
            print("deleted", dep["id"], dep.get("sha", "")[:7])
        else:
            print("failed", dep["id"], r.status_code, r.text[:120])
    print("kept=%s removed=%s dry=%s" % (keep, removed, dry))


if __name__ == "__main__":
    main()
