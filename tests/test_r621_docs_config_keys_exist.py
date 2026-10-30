# -*- coding: utf-8 -*-
"""r621：文档里写的配置键，必须是 config.example.yaml 里真的有的键。

GitHub #11 的回复与 README FAQ 都把监听地址写成 `network.host`、端口写成
`network.port`，而真实键是 `web.host` / `web.port`。用户照着改 yaml 会
**改不生效且不报错**——比不说更糟：他会以为自己已经放开了局域网访问。

这类错误的隐蔽之处：`network` 段确实存在（推送/超时等配置在别处叫相近名字），
肉眼看不出。判据必须是「这个点分键在示例配置里存在吗」。

范围刻意收窄为 `config.yaml` 里真实存在的顶层段名（web/notify/push/users…），
避免把 `python setup.py`、`docs/xx.md` 这类文件名误判成配置键。
负控：把 README 的 `web.host` 改回 `network.host` 即红。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8",
              errors="replace") as fh:
        return fh.read()


def _top_sections(example):
    """config.example.yaml 的顶层段名（缩进 0 且以 ':' 结尾）。"""
    out = set()
    for line in example.splitlines():
        m = re.match(r"^([a-z_][a-z0-9_]*)\s*:", line)
        if m:
            out.add(m.group(1))
    return out


def _keys_in_section(example, section):
    """某顶层段下的二级键（2 空格缩进）。

    注释掉的示例行也算「存在的键」——示例配置用 `# proxy: ...` 的形式
    给出可选键（实测 crawler.proxy / crawler.browser_dir 都是注释态），
    只看未注释行会把它们误报成不存在。
    """
    keys = set()
    inside = False
    for line in example.splitlines():
        if not line.strip():
            continue
        if re.match(r"^%s\s*:" % re.escape(section), line):
            inside = True
            continue
        if inside and re.match(r"^[a-z_]", line):
            inside = False
        if inside:
            m = re.match(r"^  #?\s*([a-z_][a-z0-9_]*)\s*:", line)
            if m:
                keys.add(m.group(1))
    return keys


def test_docs_reference_only_real_config_keys():
    example = _read("config.example.yaml")
    sections = _top_sections(example)
    assert {"web", "users", "crawler"} <= sections, (
        "示例配置的顶层段名变了，本门禁需复核：%s" % sorted(sections))

    docs = {}
    # HANDOFF.md 被 .gitignore（不在版本库），CI checkout 里没有它——
    # 只校验仓库内确实存在的文档，否则该门禁在 CI 上恒红。
    for name in ("README.md", "HANDOFF.md",
                 os.path.join("docs", "EXECUTION_SPEC_LATEST.md")):
        try:
            docs[name] = _read(name)
        except (OSError, FileNotFoundError):
            continue

    bad = []
    pat = re.compile(r"`([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)`")
    for name, text in docs.items():
        for m in pat.finditer(text):
            sec, key = m.group(1), m.group(2)
            if sec not in sections:
                continue          # 不是配置段（文件名/模块名等）
            real = _keys_in_section(example, sec)
            # 段下可以有三级键（如 users.routes.alert_threshold），
            # 这里只校验二级；命不中二级但出现在全文同名 key 也算过。
            if key in real:
                continue
            if re.search(r"^\s+%s\s*:" % re.escape(key), example, re.M):
                continue
            bad.append("%s: %s.%s" % (name, sec, key))
    assert not bad, (
        "文档引用了 config.example.yaml 里不存在的配置键"
        "（用户照改会静默不生效）：\n" + "\n".join(sorted(set(bad))))


def test_readme_faq_uses_web_section_for_listen_address():
    """#11 的落点：监听地址与端口都在 web 段下。"""
    readme = _read("README.md")
    assert "`web.host`" in readme, "README 没写明监听地址是 web.host"
    assert "`web.port`" in readme, "README 没写明端口是 web.port"
    for wrong in ("`network.host`", "`network.port`"):
        assert wrong not in readme, (
            "README 仍在用不存在的键 %s（用户照改不生效）" % wrong)
