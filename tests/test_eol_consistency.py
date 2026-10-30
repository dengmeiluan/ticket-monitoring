# -*- coding: utf-8 -*-
"""文档与文本文件不得混用换行符（混合 EOL 是 bug，不是风格）。

背景：docs/LESSONS.md 曾把「换行符事故」判例本身写成真实 CR/LF 混排——
判例正文被截成 3 个物理行，`newline='\\n'` 里的转义变成真控制字符，
文件同时混用 CRLF/LF，`git diff` 静默失真。文本文件统一为单一 EOL 形态。
"""
import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]

# 只查文本类文件；二进制与产物不参与
TEXT_SUFFIXES = {".md", ".txt", ".py", ".yaml", ".yml", ".ini", ".spec",
                 ".json", ".ps1", ".cfg", ".toml"}
SKIP_DIRS = {"_scratch", "build", "_build", "_build_check", "dist", "dist_package",
             "user_data", "user_data_free", "__pycache__", ".git", "site"}

CRLF = b"\r\n"
LF = b"\n"
NUL = b"\x00"
NL = "\n"


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    for rel in out.splitlines():
        p = pathlib.PurePosixPath(rel)
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if SKIP_DIRS & set(p.parts):
            continue
        yield rel


def _mixed(rel, raw):
    if NUL in raw[:2048]:
        return None
    crlf = raw.count(CRLF)
    lf = raw.count(LF) - crlf
    if crlf and lf:
        return "%s（CRLF %d / 裸 LF %d）" % (rel, crlf, lf)
    return None


def test_no_mixed_eol_in_text_files():
    offenders = []
    for rel in _tracked_text_files():
        hit = _mixed(rel, (REPO / rel).read_bytes())
        if hit:
            offenders.append(hit)
    assert not offenders, "以下文件混用换行符：" + NL + NL.join(offenders)


def test_untracked_text_files_have_single_eol():
    """**未跟踪**的文本文件同样不得混用换行符。

    背景：上面那条只遍历 `git ls-files`，未跟踪文件完全不在视野里——
    实测 `tests/test_docs_code_contract.py` 至今未被跟踪（`git ls-files` 无此项），
    它被 Python 文本模式写文件翻成 CRLF 时，旧门禁毫无反应。
    """
    tracked = set(subprocess.run(["git", "ls-files"], cwd=REPO,
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout.splitlines())
    offenders = []
    # os.walk + onerror：并发跑测时 _scratch 等目录会被建/删，rglob 在
    # 遍历中 stat 消失路径会抛 FileNotFoundError（8 worker 实测红）
    for dirpath, dirnames, filenames in os.walk(REPO, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = pathlib.Path(dirpath) / name
            if p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = p.relative_to(REPO).as_posix()
            if rel in tracked:
                continue
            try:
                hit = _mixed(rel, p.read_bytes())
            except OSError:
                continue
            if hit:
                offenders.append(hit)
    assert not offenders, (
        "以下**未跟踪**文件混用换行符：" + NL + NL.join(offenders))


def test_repo_uses_one_eol_form_only():
    """全仓只保留一种行尾：工作树文本文件一律 LF，且由 .gitattributes 钉住。

    背景：`.gitattributes` 曾只有一条 `*.ps1` 规则，其余靠 core.autocrlf
    隐式决定——工作树里 470 个文件是 CRLF、176 个是 LF，同一份改动在不同
    机器上 diff 形态不同，`git diff --stat` 也因平台而异。现在
    `.gitattributes` 用 `* text=auto eol=lf` 钉死一种形态：工作树检出即 LF，
    入库时 git 自动把任何 CRLF 归一成 LF blob，存储层不会再出现第二种形态。

    这里只校验「工作树形态 + 属性声明」，不去读索引形态：索引里残留的
    CRLF blob 会在下一次 `git add` 被属性自动归一，钉住属性才是根因。
    """
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "eol=lf" in attrs, (
        ".gitattributes 未声明 eol=lf——行尾形态会再次随平台漂移")
    assert "eol=crlf" not in attrs, (
        ".gitattributes 同时声明了 crlf 与 lf 两套规则，仓库又变成两种形态")

    offenders = []
    for rel in _tracked_text_files():
        raw = (REPO / rel).read_bytes()
        if NUL in raw[:2048]:
            continue
        crlf = raw.count(CRLF)
        lf = raw.count(LF) - crlf
        if crlf > 0:
            offenders.append("%s（CRLF %d / 裸 LF %d）" % (rel, crlf, lf))
    assert not offenders, (
        "以下文本文件工作树不是 LF：" + NL + NL.join(offenders[:20]))


def test_site_bake_does_not_rewrite_line_endings():
    """烘焙脚本必须显式 `newline="\\n"`，否则每次重烘都把站点变回 CRLF。

    背景：`docs/demo_build.py` 用文本模式 `open(OUT,"w")` 写 index.html，
    Windows 上每个 `\\n` 被翻成 `\\r\\n`（实测 23210 处）。上面两条门禁都
    扫不到它——`site/index.html` 后缀不在 TEXT_SUFFIXES 里（.html 不在），
    且 `site` 在 SKIP_DIRS 里，属于双重盲区；只有人去跑
    `git ls-files --eol` 才看得见。这里直接钉住生成器写法，
    保证产出形态与 `.gitattributes` 的 eol=lf 一致。
    """
    src = (REPO / "docs" / "demo_build.py").read_text(encoding="utf-8")
    assert 'open(OUT, "w", encoding="utf-8", newline="\\n")' in src, (
        "demo_build.py 写 index.html 未锁 newline，Windows 上会产出 CRLF")


def test_no_lone_cr_bytes_in_text_files():
    """文本文件里不得出现孤立 CR（`\\r\\r\\n` 这类破损换行）。

    背景：docs/LESSONS.md 曾有 4 处 `\\r\\r\\n`——正文被截成多余物理行，
    渲染时空行，`splitlines()` 多出条目。混合 EOL 门禁只看「CRLF 与裸 LF
    是否同时存在」，`\\r\\r\\n` 会被算成 CRLF，于是这条破损一直没被发现。
    """
    offenders = []
    for rel in _tracked_text_files():
        raw = (REPO / rel).read_bytes()
        if NUL in raw[:2048]:
            continue
        n = 0
        i = raw.find(b"\r")
        while i >= 0:
            if raw[i + 1:i + 2] != NL:
                n += 1
            i = raw.find(b"\r", i + 1)
        if n:
            offenders.append("%s（%d 处）" % (rel, n))
    assert not offenders, "以下文件含孤立 CR：" + NL + NL.join(offenders)


def test_lessons_newline_judgement_is_single_paragraph():
    """LESSONS 的换行符判例必须是完整一段，转义保持字面量。"""
    text = (REPO / "docs" / "LESSONS.md").read_text(encoding="utf-8")
    assert "newline='\\n'" in text, "判例里的 \\n 转义被写成了真实换行"
    assert "newline='\\r\\n'" in text, "判例里的 \\r\\n 转义被写成了真实换行"
    start = text.index("又一变体（换行符维度）")
    para = text[start:start + 520]
    assert "stat 行数量级与预期改动面不符" in para, "判例段落被物理换行截断"
