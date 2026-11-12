# -*- coding: utf-8 -*-
"""公开文档相对链接门禁（r930）。

开源维护面最容易被忽略的回归：文件改名/删除后，README 或 docs 里的
相对链接仍指向旧路径，GitHub 上直接 404。本门禁只检查**仓库内相对
链接**（http/https/mailto/tel/锚点/发版占位符跳过），并剥离代码块，
避免把示例里的 `](url)` 当成真链接。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = ["README.md", "README_EN.md", "CONTRIBUTING.md", "SECURITY.md"]
DOC_GLOB = "docs"

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_RE = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_RE = re.compile(r"`[^`\n]*`")


def _candidate_files():
    out = [os.path.join(ROOT, f) for f in FILES
           if os.path.isfile(os.path.join(ROOT, f))]
    docs = os.path.join(ROOT, DOC_GLOB)
    if os.path.isdir(docs):
        for name in sorted(os.listdir(docs)):
            if name.endswith(".md"):
                out.append(os.path.join(docs, name))
    return out


def _bad_links(text, base_dir):
    text = FENCE_RE.sub("", text)
    text = CODE_RE.sub("", text)
    links = [m.group(1) for m in LINK_RE.finditer(text)]
    links += [m.group(1) for m in HTML_RE.finditer(text)]
    bad = []
    for link in links:
        link = link.strip()
        if not link or link.startswith((
                "http://", "https://", "mailto:", "tel:", "#", "data:")):
            continue
        if "{{" in link or "}}" in link:
            continue
        path = link.split("#", 1)[0]
        if not path:
            continue
        if path.startswith("/"):
            target = os.path.join(ROOT, path.lstrip("/"))
        else:
            target = os.path.join(base_dir, path)
        if not os.path.exists(os.path.normpath(target)):
            bad.append(link)
    return bad


def test_public_docs_have_no_broken_relative_links():
    bad = []
    for f in _candidate_files():
        try:
            text = io.open(f, encoding="utf-8").read()
        except OSError:
            continue
        for link in _bad_links(text, os.path.dirname(f)):
            bad.append((os.path.relpath(f, ROOT), link))
    assert not bad, "公开文档存在死链：%s" % bad[:20]


def test_broken_link_is_detected():
    """负控：纯函数必须能抓到不存在的相对路径。"""
    bad = _bad_links("[x](definitely-missing-file.md)", ROOT)
    assert bad == ["definitely-missing-file.md"], bad
    assert _bad_links("[x](#anchor)", ROOT) == []
    assert _bad_links("[x]({{SCREENSHOT_BASE}}/a.png)", ROOT) == []
    assert _bad_links("```\n[x](missing.md)\n```", ROOT) == []
    assert _bad_links("`![](url)`", ROOT) == []
    assert _bad_links("`[t](url)`", ROOT) == []
    assert _bad_links('<img src="missing-shot.png">', ROOT) == [
        "missing-shot.png"]
