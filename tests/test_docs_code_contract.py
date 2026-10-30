# -*- coding: utf-8 -*-
"""文档与代码的关键契约不得漂移。

背景：docs/EXECUTION_SPEC_LATEST.md 曾长期把圆角写成「两档 12/9」、把
PCHART 写成 mount/draw/hover/destroy、把画布宽度写成「不随点数放大」、
把触屏热区写成 44px——四条都与代码相反，且没有任何测试发现。
本文件只钉「文档里写死的、代码里也有的」硬值，防止再次分叉。
"""
import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = (ROOT / "docs" / "EXECUTION_SPEC_LATEST.md").read_text(encoding="utf-8")
WEBUI = (ROOT / "webui.py").read_text(encoding="utf-8")
BASE = (ROOT / "crawlers" / "base.py").read_text(encoding="utf-8")


def test_version_matches_docs():
    """main.py 版本必须与规范标题、基线行一致。"""
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    ver = re.search(r'^__version__\s*=\s*"([^"]+)"', main_py, re.M).group(1)
    assert "v%s" % ver in SPEC, "规范标题/基线未同步到当前版本 %s" % ver


def test_radius_tokens_documented_match_code():
    """规范列出的圆角令牌必须与 webui.py 定义一致。"""
    defs = dict(re.findall(r"(--r[0-9]*|--pill):\s*([0-9]+px)", WEBUI))
    assert defs, "未找到圆角令牌定义"
    for token, value in defs.items():
        if token == "--pill":
            continue
        assert token in SPEC, "规范缺少圆角令牌 %s" % token
        # 规范里应出现该令牌及其真实值
        assert re.search(re.escape(token) + r"[^\n]{0,12}" + re.escape(value),
                         SPEC), "规范中 %s 的值与代码（%s）不一致" % (token, value)


def test_pchart_api_documented_matches_code():
    """规范不得再宣传不存在的 PCHART 方法，且必须列出真实成员。"""
    for ghost in ("PCHART.mount", "PCHART.draw(", "PCHART.hover(", "PCHART.destroy"):
        assert ghost not in SPEC, "规范仍在引用未实现的 %s" % ghost
    for real in ("PCHART.frame", "PCHART.axes", "PCHART.gaps",
                 "PCHART.pick", "PCHART.placeTip"):
        assert real in SPEC, "规范未列出真实接口 %s" % real
        assert real.replace("PCHART.", "") in WEBUI, "代码中缺少 %s" % real


def test_canvas_width_rule_matches_code():
    """画布宽度必须是「取大(可视宽, min(点数×间距, 2.4×))」，不得写回锁宽。"""
    assert "不随点数放大" not in SPEC, "规范退回到已被否决的锁宽描述"
    assert "baseW*2.4" in WEBUI or "baseW * 2.4" in WEBUI, "代码中未找到 2.4× 上限"
    assert "2.4" in SPEC and "可视宽" in SPEC, "规范未说明画布宽度的取大规则"


def test_readme_quoted_label_emoji_prefix():
    """README 「」里的文案若在界面以"无 emoji 形式"存在，就不得自行加 emoji 前缀。

    实测踩过：README 写「✈ 只要直飞」，界面按钮实为纯文本「只要直飞」——
    读者 Ctrl+F 带 emoji 找会搜不到。
    """
    offenders = []
    examined = 0
    for name in ("README.md", "README_EN.md"):
        p = ROOT / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for term in set(re.findall("「([^」\n]{2,20})」", line)):
                stripped = re.sub(r"^[^\w一-鿿]+", "", term).strip()
                if stripped == term or not stripped:
                    continue
                examined += 1
                if term in WEBUI:
                    continue
                if stripped in WEBUI:
                    offenders.append("%s:%d 「%s」→ 界面无 emoji 版「%s」" % (name, i, term, stripped))
    # 下限：README 有 43 处「」术语，其中带 emoji 前缀的是本条判据的检查对象。
    # 0 命中可能是「所有前缀都改对了」，也可能是「「」换成了别的引号」——
    # 后者会让门禁静默失效，所以要求至少看过若干「」术语。
    assert examined >= 5, (
        "README 里带前缀的「」术语只有 %d 个，本门禁疑似失去检查对象" % examined)
    assert not offenders, (
        "README 给界面文案自加了 emoji 前缀：" + "\n".join(sorted(set(offenders))))


def test_readme_action_labels_exist_in_ui():
    """README 「」里的**动作型**文案（清空/清除/展开/收起/只看…）必须与界面一致。

    实测踩过：README 写「清空共同筛选」，界面按钮实为「清除共同筛选」；
    又写「中转与时段约束」，折叠头实为「筛选与时段约束」——读者照着找找不到。
    只查动作型（带动词），描述性短语（如「最大可省」「哪天几点」）不在此列。
    """
    ACTIONS = ("清空", "清除", "展开", "收起", "只看", "重置", "立即", "保存")
    ui = WEBUI
    offenders = []
    examined = 0
    for name in ("README.md", "README_EN.md"):
        p = ROOT / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for term in set(re.findall("「([^」\\n]{2,20})」", line)):
                if not any(a in term for a in ACTIONS):
                    continue
                examined += 1
                if term in ui:
                    continue
                offenders.append("%s:%d 「%s」" % (name, i, term))
    # 下限：README 里「」引用的动作文案至少应有 1 处。0 命中说明
    # 引号风格被改（如换成 " 或 `` ）或 ACTIONS 词表失配 —— 门禁会静默失效。
    assert examined, (
        "README 的「」里没有任何动作型文案，本门禁失去检查对象——"
        "需人工确认引号风格与 ACTIONS 词表")
    assert not offenders, (
        "README 引用界面不存在的动作文案：" + "\n".join(sorted(set(offenders))))


def test_doc_referenced_test_files_exist():
    """文档提到的 `tests/test_xxx.py` 必须真实存在，或标注为未创建/计划。

    实测踩过：`docs/CHANNEL_SESSION.md` 的回归命令里写着
    `tests/test_channel_auth_classification.py`——该文件从未存在，读者照抄
    整条命令会直接报 "file or directory not found"，连其余四个用例也跑不成。
    """
    exist = {p.name for p in (ROOT / "tests").glob("test_*.py")}
    assert exist, "tests/ 下没有测试文件"
    offenders = []
    for p in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("_scratch/"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for name in set(re.findall(r"tests/(test_[a-z0-9_]+\.py)", line)):
                if name in exist:
                    continue
                if any(k in line for k in ("未创建", "从未创建", "未实现", "不存在",
                                           "计划", "提案", "已从命令")):
                    continue
                offenders.append("%s:%d %s" % (rel, i, name))
    assert not offenders, (
        "文档引用了不存在的测试文件（照抄命令会失败）：" + "\n".join(sorted(set(offenders))))


def test_spec_line_refs_still_point_at_claim():
    """SPEC 里的 `file.py:NNN` 行号引用，指向的那一行必须真的还含该断言的特征。

    实测踩过：§6.3 写「画布宽度…（实测 `webui.py:13185-13192`）」，
    webui.py 被并行改写后该区间已是"推送预览弹窗"代码——行号漂了 473 行，
    而 gate 只校验语义（`baseW*2.4` 存在），所以一直没人发现。
    做法：为每一处行号引用登记一个特征串，读该行验证；行号失配即报错。
    """
    # (文档锚点特征, 源文件, 行号, 该行必须包含的串)
    CHECKS = [
        ("PEP 604", "core/radar_alerts.py", 25, "float | None"),
        ("PEP 604", "crawlers/ctrip.py", 1010, "float | None"),
        ("PEP 604", "crawlers/tongcheng.py", 1051, "float | None"),
    ]
    # 文档里实际出现的行号引用必须都在 CHECKS 里登记过——
    # 否则新增一处引用而门禁不知道，它照样是绿的（CONTRIBUTING 就曾被漏掉）。
    doc_refs = set()
    for name in ("docs/EXECUTION_SPEC_LATEST.md", "CONTRIBUTING.md",
                 "HANDOFF.md", "docs/CHANNEL_SESSION.md", "docs/INTL_DESIGN.md"):
        q = ROOT / name
        if not q.exists():
            continue
        body = q.read_text(encoding="utf-8", errors="replace")
        # HANDOFF 第 233 行起是历史运行记录，里面的行号是当轮快照，不参与当前校验
        cut = body.find("下表是历史运行记录的累积")
        if cut > 0:
            body = body[:cut]
        for m in re.finditer(r"((?:core|crawlers|tests|docs)/[A-Za-z0-9_./-]+\.py):(\d+)", body):
            doc_refs.add((m.group(1), int(m.group(2))))
    registered = {(rel, lineno) for _, rel, lineno, _ in CHECKS}
    unregistered = sorted(doc_refs - registered)
    assert not unregistered, (
        "文档里这些行号引用未登记到 CHECKS，行号漂了也不会被发现：%s" % unregistered)

    offenders = []
    for label, rel, lineno, needle in CHECKS:
        p = ROOT / rel
        if not p.exists():
            offenders.append("%s: 文件不存在" % rel)
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        if lineno > len(lines):
            offenders.append("%s:%d 超出文件长度 %d" % (rel, lineno, len(lines)))
            continue
        if needle not in lines[lineno - 1]:
            offenders.append("%s:%d 已不含「%s」（现内容：%s）"
                             % (rel, lineno, needle, lines[lineno - 1].strip()[:60]))
    assert not offenders, (
        "SPEC 的行号引用已漂移（改用符号锚点，或同步行号）：\n" + "\n".join(offenders))

    # §6.3 已改符号锚点：不得再写 webui.py 的行号区间
    assert not re.search(r"webui\.py:\d{4,5}", SPEC), (
        "SPEC 又给 webui.py 写了行号——该文件被并行改写，行号必漂，请用符号锚点")


def test_documented_cli_flags_exist():
    """面向用户的文档里写的 `--flag` 必须是本项目 argparse 真有的参数。

    实测：README/CONTRIBUTING 教人跑 `--demo/--setup/--login/--setup-login/--once/
    --port/--restart-delay` 等，若某个被改名或删除，读者照抄会直接报错。
    排除项：CSS 自定义属性（`--bg:` 这类）、Chromium/PyInstaller 等第三方参数、
    以及收在「坑」语境里说明"这不是本版参数"的引用。
    """
    src = ""
    for rel in ("main.py", "webui.py", "wizard.py"):
        pth = ROOT / rel
        if pth.exists():
            src += pth.read_text(encoding="utf-8", errors="replace")
    flags = set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', src))
    assert flags, "未解析到任何 argparse 参数"
    # CSS 变量（--bg / --sbh 等）在样式里以 `--name:` 或 `var(--name)` 出现
    cssvars = set(re.findall(r"(--[a-z0-9-]+)\s*:", src)) |         set(re.findall(r"var\((--[a-z0-9-]+)\)", src))
    third_party = {"--no-proxy-server", "--disable-blink-features", "--noconfirm",
                   "--no-confirm", "--local", "--amend", "--detach", "--system",
                   "--force", "--check", "--time-style", "--short", "--cached",
                   "--hard", "--fill", "--tags", "--stl"}
    offenders = []
    for name in ("README.md", "README_EN.md", "CONTRIBUTING.md"):
        pth = ROOT / name
        if not pth.exists():
            continue
        for i, line in enumerate(pth.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            # 反引号里常是整条命令（`python main.py --setup`），
            # 所以先取反引号内容，再从里面提 flag——只匹配"反引号内只有 flag"会漏掉绝大多数写法。
            for span in re.findall(r"`([^`]+)`", line):
                # 外部工具的 flag 不归本项目管（git / pyinstaller / pip / playwright …）
                if re.search(r"\b(git|pyinstaller|pip|playwright|npm|npx|curl|netstat|"
                             r"findstr|tasklist|powershell|pwsh)\b", span, re.I):
                    continue
                for f in set(re.findall(r"(--[a-z][a-z0-9-]{2,})", span)):
                    if f in flags or f in cssvars:
                        continue
                    # 第三方参数只在"源码里确实出现这个串"时才放行——
                    # 早先直接用静态白名单，任何未登记的名字都会被放行（负控假绿）。
                    if f in third_party and f in src:
                        continue
                    offenders.append("%s:%d %s" % (name, i, f))
    assert not offenders, (
        "文档教人用的命令行参数在 argparse 里不存在：" + "\n".join(sorted(set(offenders))))


def test_spec_and_handoff_called_functions_exist():
    """SPEC / HANDOFF 里写成 `foo()` 的函数名必须在源码里真有定义。

    与 `test_doc_called_identifiers_exist` 互补：那条查 README/CHANNEL_SESSION/
    INTL_DESIGN/CAPTCHA_SOLUTION，这条查规范与交割文档——它们最常被当作
    "实现真值"引用，点错名会让人以为功能不存在。
    第三方 API 走白名单；扫描范围含 tests/（门禁自身的名字也在文档里出现）。
    """
    THIRD = {"scroll_into_view_if_needed", "wait_for_timeout", "set_viewport_size",
             "evaluate", "add_init_script", "storage_state", "is_closed",
             "query_selector", "inner_html", "dispatch_event",
             # 浏览器标准 API：文档里写「程序化 focus() 不触发 :focus-visible」
             # 指的是 DOM 方法，不是仓库里的函数（r619 实测误报）
             "focus", "blur", "closest", "matches", "getBoundingClientRect"}
    src = []
    for rel in ("main.py", "webui.py", "report.py", "wizard.py"):
        q = ROOT / rel
        if q.exists():
            src.append(q.read_text(encoding="utf-8", errors="replace"))
    for sub in ("core", "crawlers", "tests"):
        d = ROOT / sub
        if d.is_dir():
            for f in d.rglob("*.py"):
                src.append(f.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(src)
    offenders = []
    examined = 0
    for name in ("docs/EXECUTION_SPEC_LATEST.md", "HANDOFF.md"):
        q = ROOT / name
        if not q.exists():
            continue
        for i, line in enumerate(q.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for fn in set(re.findall(r"`([a-z_][a-z0-9_]{3,})\(\)`", line)):
                if fn in THIRD:
                    continue
                examined += 1
                # 箭头函数也是函数：源码里大量用 `const glab=(…) => …`
                # 形式，只认 `def`/`function` 会把合法引用误报成
                # 「不存在的函数」（r651 实测：glab() 被误报）。
                if any(form % fn in blob for form in (
                        "def %s(", "function %s(", "const %s=", "let %s=",
                        "var %s=", "async function %s(")):
                    continue
                offenders.append("%s:%d %s()" % (name, i, fn))
    # 下限：SPEC 有 2 处、HANDOFF 有 12 处 `fn()` 写法（实测）。0 命中＝写法变了。
    assert examined, "SPEC/HANDOFF 里没有 `fn()` 写法，本门禁失去检查对象"
    assert not offenders, (
        "规范/交割文档引用了不存在的函数：" + "\n".join(sorted(set(offenders))))


def test_doc_called_identifiers_exist():
    """文档里写成 `name()` 的调用式标识符，必须能在源码里找到同名函数/方法。

    实测踩过：`_fc_key` 这类名字在文档里像"现有 API"，全仓却不存在。
    与 `test_playbook_named_identifiers_exist` 互补：那条只看 PLAYBOOK 的
    强特征常量/下划线名，这条看各文档的"调用式"写法。
    白名单放第三方 API 与已被明确标注为"提案/未实现"的名字。
    """
    ALLOW_THIRD_PARTY = {"scroll_into_view_if_needed", "wait_for_timeout",
                         "set_viewport_size", "evaluate", "add_init_script",
                         "storage_state", "is_closed", "query_selector"}
    src_parts = []
    for rel in ("main.py", "webui.py", "report.py", "wizard.py"):
        p = ROOT / rel
        if p.exists():
            src_parts.append(p.read_text(encoding="utf-8", errors="replace"))
    for sub in ("core", "crawlers"):
        d = ROOT / sub
        if d.is_dir():
            for f in d.rglob("*.py"):
                src_parts.append(f.read_text(encoding="utf-8", errors="replace"))
    src = "\n".join(src_parts)

    targets = [ROOT / "HANDOFF.md", ROOT / "README.md",
               ROOT / "docs" / "CHANNEL_SESSION.md",
               ROOT / "docs" / "INTL_DESIGN.md",
               ROOT / "docs" / "CAPTCHA_SOLUTION.md"]
    offenders = []
    examined = 0
    for p in targets:
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for name in set(re.findall(r"`([a-z_][a-z0-9_]{4,})\(\)`", line)):
                if name in ALLOW_THIRD_PARTY:
                    continue
                examined += 1
                if ("def %s(" % name) in src or ("function %s(" % name) in src:
                    continue
                # 允许"提案/建议/未实现"语境
                if any(k in line for k in ("建议", "提案", "未实现", "未创建", "计划")):
                    continue
                offenders.append("%s:%d %s()" % (p.name, i, name))
    # 下限：五份文档里确实有 `name()` 写法（实测 >0，全部来自 CAPTCHA_SOLUTION）。
    # 0 命中说明反引号风格或正则变了，门禁会静默失效。
    assert examined, "五份目标文档里没有 `name()` 写法，本门禁失去检查对象"
    assert not offenders, "文档调用了不存在的函数：\n" + "\n".join(sorted(set(offenders)))


def test_spec_ui_filter_keys_exist():
    """SPEC 提到的 `SRX.f.<key>` 筛选键必须在 webui.py 里真实使用。

    实测踩过：§7 写「UI 用『去日历/补位』筛选（`webui.py` 的 `real` 键对应
    `SRX.f.hideCal`）」——`SRX.f.real` 根本不存在，真实开关就叫 `hideCal`。
    读者按文档去找 `real` 会扑空。
    """
    real_keys = set(re.findall(r"SRX\.f\.([A-Za-z_][\w]*)", WEBUI))
    # 这里是**代码侧**锚点：webui.py 没有 SRX.f.* 说明筛选结构被重构，
    # 本门禁的靶子消失——必须失败并要求人工把门禁改到新结构上，不能 skip。
    assert real_keys, "webui.py 里没有 SRX.f.* 键（筛选结构已变），需把本门禁改到新结构"
    offenders = []
    examined = 0
    for m in re.finditer(r"`?SRX\.f\.([A-Za-z_][\w]*)`?", SPEC):
        examined += 1
        k = m.group(1)
        if k not in real_keys:
            offenders.append(k)
    # 下限：SPEC 确实提到 1 个 SRX.f.* 键（实测 `SRX.f.hideCal`）。
    # 0 命中说明写法变了，门禁会静默失效。
    assert examined, "SPEC 未提及任何 SRX.f.* 键，本门禁失去检查对象"
    assert not offenders, (
        "SPEC 提到的 SRX.f.* 键在 webui.py 中不存在：%s" % sorted(set(offenders)))


def test_docs_with_many_line_refs_declare_staleness():
    """行号引用超过阈值的文档，必须在正文声明「行号是当时的快照」。

    实测：CAPTCHA_SOLUTION 有 19 处 `file.py:NNN-NNN`，抽查
    `qunar.py:419-443`（现为 `fetch()` 定义）、`tuniu.py:492-493`（普通字段赋值）、
    `ctrip.py:733-751`（`lay_min = 0`）——全部已不是原文描述的逻辑。
    这类文档不该逐条改行号（改完下次又漂），而应显式告知读者改用符号检索。
    """
    offenders = []
    examined = 0
    for p in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("_scratch/"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        n = len(re.findall(r"(?:core|crawlers|tests|docs)/[\w./-]+\.py:\d+", text))
        if n < 8:
            continue
        examined += 1
        has_decl = ("行号" in text and
                    any(k in text for k in ("漂移", "快照", "当时", "不要按行号")))
        if not has_decl:
            offenders.append("%s（%d 处行号引用，无时效声明）" % (rel, n))
    # 下限：这条判据的靶子是「有大量行号引用的文档」。若一处都没命中，
    # 要么行号引用被批量清掉（判据失去对象），要么正则被改坏——都不该算绿。
    assert examined, (
        "没有任何文档的行号引用 ≥8 处，本门禁失去检查对象——"
        "需人工确认是行号被清理还是正则失效")
    assert not offenders, (
        "以下文档有大量行号引用却未声明其时效：%s" % offenders)


def test_touch_target_documented_matches_gate():
    """触屏热区地板文档值必须与门禁实测值一致（36px）。"""
    uitest = (ROOT / "docs" / "uitest.py").read_text(encoding="utf-8")
    assert "coarse 裸 button 36px" in uitest, "门禁中的触屏地板已变更，需复核规范"
    assert "触屏热区 ≥ 44px" not in SPEC, "规范仍写 44px 硬门槛"
    assert "36px" in SPEC, "规范未写明 36px 地板"


def test_path_status_vocabulary_documented():
    """PATH_STATUS 的每个取值都必须在规范的状态表里出现。"""
    m = re.search(r"PATH_STATUS\s*=\s*\(([^)]*)\)", BASE, re.S)
    assert m, "未找到 PATH_STATUS"
    statuses = re.findall(r'"([a-z_]+)"', m.group(1))
    assert statuses, "PATH_STATUS 为空"
    for s in statuses:
        assert "`%s`" % s in SPEC, "规范状态表缺少 `%s`" % s

def test_live_rate_fields_documented():
    """r406「在用口径」的三个对外字段必须同时出现在代码与规范里。

    这条防的是：文档写下字段名却拼错（读者照着取不到值），
    或代码改了字段名而文档没跟（口径说明失真）。
    """
    storage = (ROOT / "core" / "storage.py").read_text(encoding="utf-8")
    for field in ("retired_paths", "query_rate_live", "query_attempts_live"):
        assert '"%s"' % field in storage or "%s" % field in storage,             "代码中缺少在用口径字段 %s" % field
        assert field in SPEC, "规范未记录在用口径字段 %s" % field
    # 原口径必须保留可对照（新口径是补充视图，不覆盖）
    assert "query_rate" in storage and "query_rate" in SPEC,         "原口径 query_rate 不应被删除——新口径是补充视图"
    # 退役判据的关键一票否决必须写进规范
    assert "一次都没成功" in SPEC, "规范未写明『还在出数即不退役』这条关键判据"

def test_live_rate_consumers_documented_as_actual():
    """「在用口径」的消费方必须与代码实际一致——双向一致，不是单向禁令。

    实测（2026-10-27）：先是只有 core/pacing.py 读 query_rate_live；
    随后健康徽标也切了过去（消除"徽标 13% / 小标国际 73%"并列矛盾）。
    这条门禁要求：代码用没用 → 文档必须说一样，两种方向都不许漂。
    """
    pacing = (ROOT / "core" / "pacing.py").read_text(encoding="utf-8")
    webui = (ROOT / "webui.py").read_text(encoding="utf-8")
    assert "query_rate_live" in pacing, "建议层应消费在用口径"
    assert "消费方现状" in SPEC, "规范缺少消费方现状表"

    ui_live = "query_rate_live" in webui
    doc_ui_live = re.search(r"渠道健康徽标[^\n]*在用口径", SPEC) is not None
    assert ui_live == doc_ui_live, (
        "UI 是否用 query_rate_live 与文档不一致：代码=%s 文档=%s —— 改了代码就同步「消费方现状」表"
        % (ui_live, doc_ui_live))
    # 分通路速览这条反向约束始终成立：它展示的是每条通路自己，不该用聚合口径。
    # 判据跟着代码结构走：2026-10-28 核对发现独立「路径行」已不存在，
    # 分通路并进健康卡的 `.hpath`，读的是 paths[p].paths[k].rate。
    # 旧断言写死「路径行仍用原口径」，结构一变就变成守着一个不存在的组件。
    has_hpath = re.search(r'class="hpath"', webui) is not None
    doc_hpath = "`.hpath`" in SPEC
    assert has_hpath == doc_hpath, (
        "UI 是否渲染 .hpath 与文档不一致：代码=%s 文档=%s" % (has_hpath, doc_hpath))
    if has_hpath:
        assert re.search(r"paths\[p\]\.paths\[k\]\.rate", SPEC), (
            "规范未写明 .hpath 用的是每条通路自己的 rate")
        # 文档必须显式说明「路径行已不存在」，否则读者会按旧表述去找一个没有的组件。
        assert "「控制台路径行」已不存在" in SPEC, (
            "规范未声明旧的「控制台路径行」已不存在")

def test_style_compliance_numbers_match_measurement():
    """SPEC §3 的字号/间距/阴影三组"实测"数字必须能被按文档口径复现。

    实测踩过（2026-10-28）：文档写「825 条 / 93.7%」「1628 条 / 43.7%」
    「174 条阴影中 119 条非 none」，按主样式块口径实测是 826 / 1611 / 175·123
    ——数字已随并行会话推进漂了，且**文档没写统计范围**，读者无从复现。
    这类数字带容差比较：并行会话会持续微调样式，精确相等会变成噪声源。
    """
    css = re.findall(r"<style[^>]*>(.*?)</style>", WEBUI, re.S)
    assert css, "webui.py 里没有 <style> 块"
    main = css[0]          # 口径：只取主样式块（文档已写明）
    FONT = {10, 11, 12, 13, 14, 16, 17, 18, 22}
    SPACE = {4, 6, 8, 12, 16, 24}

    fonts = [int(x) for x in re.findall(r"font-size:\s*(\d+)px", main)]
    assert fonts, "主样式块未解析到 font-size 声明"
    font_pct = 100.0 * sum(1 for f in fonts if f in FONT) / len(fonts)

    vals = []
    for prop in ("padding", "margin", "gap"):
        for m in re.finditer(r"(?<![-\w])%s:\s*([^;}\n]+)" % prop, main):
            vals += [int(x) for x in re.findall(r"(\d+)px", m.group(1))]
    assert vals, "主样式块未解析到 padding/margin/gap 数值"
    space_pct = 100.0 * sum(1 for v in vals if v in SPACE) / len(vals)

    shadows = re.findall(r"box-shadow:\s*([^;}\n]+)", main)
    assert shadows, "主样式块未解析到 box-shadow 声明"

    # 文档必须写明"主样式块"口径，否则上面的数字无从复现。
    # 锚到完整口径句而非只搜「主样式」——实测负控时全文还有第 2 处「主样式」，
    # 只搜词会让删掉口径段也照样绿。
    assert re.search(r"只取 `webui\.py` 的\*\*第一个 `<style>` 块\*\*", SPEC), (
        "SPEC 未写明这组样式数字的统计范围（第一个 <style> 块），读者无从复现")

    def claimed(pat, label, conv=int):
        m = re.search(pat, SPEC)
        assert m, "SPEC 未找到 %s 的实测数字（本门禁失去锚点）" % label
        return conv(m.group(1))

    claimed_dec = lambda pat, label: claimed(pat, label, float)

    def near(a, b, tol):
        return abs(a - b) <= tol

    f_doc = float(claimed_dec(r"实测合规率 \*\*(\d+(?:\.\d+)?)%", "字号合规率"))
    assert near(font_pct, f_doc, 2), "字号合规率：实测 %.1f%%，文档 %s%%" % (font_pct, f_doc)

    s_doc = claimed_dec(r"落在这 6 值的 \*\*(\d+(?:\.\d+)?)%", "间距合规率")
    assert near(space_pct, float(s_doc), 2), (
        "间距合规率：实测 %.1f%%，文档 %s%%" % (space_pct, s_doc))

    m = re.search(r"(\d+) 条 `font-size` 声明", SPEC)
    assert m, "SPEC 未写 font-size 声明条数"
    assert near(len(fonts), int(m.group(1)), 60), (
        "font-size 声明条数：实测 %d，文档 %s" % (len(fonts), m.group(1)))

    m = re.search(r"（(\d+) 个 `padding`/`margin`/`gap`", SPEC)
    assert m, "SPEC 未写 padding/margin/gap 数值个数"
    assert near(len(vals), int(m.group(1)), 200), (
        "间距数值个数：实测 %d，文档 %s" % (len(vals), m.group(1)))

    m = re.search(r"实测 (\d+) 条阴影声明中 (\d+) 条非 none", SPEC)
    assert m, "SPEC 未写阴影声明条数"
    non_none = sum(1 for s in shadows if s.strip() != "none")
    assert near(len(shadows), int(m.group(1)), 30), (
        "阴影声明条数：实测 %d，文档 %s" % (len(shadows), m.group(1)))
    assert near(non_none, int(m.group(2)), 30), (
        "非 none 阴影条数：实测 %d，文档 %s" % (non_none, m.group(2)))

    # §3 第 2 条：分隔线的「94 条 / 80 条用 var(--line)」也必须可复现。
    # 原句写「绝大多数是 1px solid var(--line)」——实测 solid 只有 59 条，
    # 另有 21 条 dashed 同样用 --line，按「用 --line」算才是 85%，措辞据此改写。
    borders = [b.strip() for b in
               re.findall(r"border-(?:top|bottom):\s*([^;}\n]+)", main)]
    assert borders, "主样式块未解析到 border-top/bottom 声明"
    m = re.search(r"`border-top/bottom` 声明 \*\*(\d+) 条\*\*", SPEC)
    assert m, "SPEC 未写 border-top/bottom 声明条数（本门禁失去锚点）"
    assert near(len(borders), int(m.group(1)), 20), (
        "border 声明条数：实测 %d，文档 %s" % (len(borders), m.group(1)))
    m = re.search(r"其中 (\d+) 条用发丝色", SPEC)
    assert m, "SPEC 未写用发丝色 --line 的条数"
    with_line = sum(1 for b in borders if "--line)" in b)
    assert near(with_line, int(m.group(1)), 20), (
        "用 var(--line) 的 border 条数：实测 %d，文档 %s" % (with_line, m.group(1)))


def test_color_tokens_documented_match_code():
    """规范 §3.2 颜色表的每个令牌值必须与 webui.py :root 定义一致。

    旧规范曾整段写错（canvas #f1f3f6 实为 --bg #eceff4，且令牌名 --r-canvas
    根本不存在）。这条把「亮/暗两套值」都钉住，防止再次分叉。
    """
    css = re.search(r"<style>(.*?)</style>", WEBUI, re.S).group(1)
    # 亮色根块（--blue:#0b62d6 那一块）
    light_anchor = css.find("--bg:#eceff4")
    assert light_anchor > 0, "未找到亮色根块（--bg:#eceff4）"
    # 语义色（--blue/--red/--green/--orange）写在 --bg 之前，窗口必须前扩
    light = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})",
                            css[max(0, light_anchor - 600):light_anchor + 1200]))
    # 暗色根块
    dark_anchor = css.find("--bg:#0a0f16")
    assert dark_anchor > 0, "未找到暗色根块（--bg:#0a0f16）"
    dark = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})",
                           css[max(0, dark_anchor - 600):dark_anchor + 1200]))

    checked = 0
    for token in ("bg", "card", "tx", "tx2", "mut", "line", "line2",
                  "grid", "headbg", "hover", "rowalt", "blue", "red",
                  "green", "orange"):
        if token not in light:
            continue
        row = "`--%s`" % token
        assert row in SPEC, "规范颜色表缺少 %s" % row
        assert light[token] in SPEC, "规范缺少 %s 亮色值 %s" % (token, light[token])
        if token in dark:
            assert dark[token] in SPEC, "规范缺少 %s 暗色值 %s" % (token, dark[token])
        checked += 1
    assert checked >= 12, "只核对了 %d 个令牌，疑似解析失败" % checked


def test_no_ghost_tokens_in_spec():
    """规范引用的每个 `--token` 都必须在 webui.py 某个 :root 里真实定义。

    注意：项目存在两套令牌（主 :root 与 <style id="r364-flat">），
    两套都是真值，不能因为不在第一套里就判幽灵。
    """
    css = re.search(r"<style>(.*?)</style>", WEBUI, re.S).group(1)
    all_style = "".join(re.findall(r"<style[^>]*>(.*?)</style>", WEBUI, re.S))
    defined = set(re.findall(r"--([a-z0-9-]+)\s*:", all_style))

    # 排除命令行参数（如 `--local`），它们不是 CSS 令牌
    CLI_FLAGS = {"local", "help", "version", "demo", "login", "setup-login",
                 "profile-ui", "ui-shards", "workers", "serial", "no-ui",
                 "no-pin", "bootstrap-deps", "pytest-args"}
    ghosts = []
    tokens = sorted(set(re.findall(r"`--([a-z0-9-]+)`", SPEC)))
    # 下限：SPEC 里确有 24 个 `--token` 引用（实测）。0 命中说明反引号写法变了。
    assert tokens, "SPEC 未提及任何 `--token`，本门禁失去检查对象"
    for token in tokens:
        if token in CLI_FLAGS:
            continue
        if token not in defined:
            ghosts.append(token)
    assert not ghosts, "规范引用了代码中不存在的令牌: %s" % ghosts

def test_handoff_core_modules_exist():
    """HANDOFF 架构速览里点名的 core 模块必须真实存在。

    防的是：模块被删除/改名后文档仍指着一个不存在的路径，
    接手者按文档去找却扑空。
    """
    import os
    handoff = (ROOT / "HANDOFF.md")
    if not handoff.exists():
        pytest.skip("HANDOFF.md 不在版本库（gitignore），跳过")
    text = handoff.read_text(encoding="utf-8")
    refs = set(re.findall(r"^(core/[a-z_]+\.py)", text, re.M))
    assert len(refs) >= 8, "架构速览点名的 core 模块过少（%d），疑似解析失败" % len(refs)
    missing = [r for r in sorted(refs) if not (ROOT / r).exists()]
    assert not missing, "HANDOFF 指向不存在的模块: %s" % missing

def test_probe_design_hard_contracts():
    """探针台设计文档的硬契约必须与代码一致（14 日价带 / 字段规格数 / 5 渠道矩阵）。"""
    doc_path = ROOT / "docs" / "design" / "probe-console-design.md"
    if not doc_path.exists():
        pytest.skip("设计文档不存在")
    doc = doc_path.read_text(encoding="utf-8")

    # 14 日价带：CSS 里 repeat(14) 必须仍在
    assert "repeat(14" in WEBUI, "价带列数已变，设计文档的『14 日价带』需复核"
    assert "14 日价带" in doc

    # 字段规格：代码定义数与文档说明必须一致
    lines = WEBUI.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("const SRX_FIELD_SPECS=[")), None)
    assert start is not None, "未找到 SRX_FIELD_SPECS"
    total = 0
    for l in lines[start + 1:]:
        if l.startswith("];"):
            break
        if re.match(r"\s*\{k:'[a-zA-Z]+'", l):
            total += 1
    assert total >= 13, "字段规格数异常：%d" % total
    assert "定义 **%d** 个字段" % total in doc, (
        "设计文档的字段数说明与代码（%d）不符" % total)

    # 矩阵 5 列
    assert "矩阵 5 列" in doc or "列=5 渠道" in doc
    from core.channel_links import PLATS
    assert len(PLATS) == 5, "渠道数已变（%d），矩阵列数与文档需同步" % len(PLATS)

def test_uncommitted_round_range_covers_worktree():
    """SPEC/HANDOFF 声明的「未提交轮次区间」必须覆盖工作区代码里的最高 rNNN。

    实测踩过：两处都写 r418–r421，而工作区已推进到 r423/r424
    （r423 来源接入改卡头第二段、r424 窄档探针开关），读者会以为最新只到 r421。
    注意 r422 实际不存在——区间用"–"连写时需说明跳号，避免读者去查一个空轮次。
    """

    def max_round(text):
        # 只在注释里找 "rNNN"，且前面不是字母/数字——
        # 否则 base64 图片数据里的随机串（如 …T7x9r888）会被当成轮次号。
        nums = []
        for line in text.splitlines():
            if not line.lstrip().startswith(("#", "//", "/*", "*")):
                continue
            nums += [int(x) for x in re.findall(r"(?<![A-Za-z0-9])r(\d{3})\b", line)]
        return max(nums) if nums else 0

    worktree_max = 0
    for rel in ("webui.py",):
        p = ROOT / rel
        if p.exists():
            worktree_max = max(worktree_max, max_round(p.read_text(encoding="utf-8", errors="replace")))
    for sub in ("core", "crawlers"):
        d = ROOT / sub
        if d.is_dir():
            for f in d.glob("*.py"):
                worktree_max = max(
                    worktree_max, max_round(f.read_text(encoding="utf-8", errors="replace")))
    if worktree_max < 418:
        pytest.skip("工作区未出现 r418+ 改动")

    for name in ("docs/EXECUTION_SPEC_LATEST.md", "HANDOFF.md"):
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        # 必须声明"r418 起"这一起点
        assert re.search(r"r418\s*起", text), (
            "%s 未声明「r418 起的新轮次尚未提交」" % name)
        # 可以写死端点，也可以写"以工作区为准"；只要二者之一即可
        has_cutoff = re.search(r"截至[^\n]{0,20}r\d{3}", text) is not None
        has_authority = "以工作区" in text
        assert has_cutoff or has_authority, (
            "%s 未给出未提交轮次的截止点或「以工作区为准」的判据" % name)
        if has_cutoff:
            # 只取「到 rNNN / 至 rNNN」这种明确端点，避免把日期 2026-10-28 里的数字误配
            ends = [int(x) for x in re.findall(r"(?:到|至)\s*r(\d{3})\b", text)]
            assert ends, "%s 写了「截至」但没给出「到 rNNN」端点" % name
            end = max(ends)
            assert end >= worktree_max, (
                "%s 声明截至 r%d，但工作区代码已到 r%d（并行会话又推进了，请更新）"
                % (name, end, worktree_max))


def test_spec_markdown_tables_are_well_formed():
    """全仓文档里每个 Markdown 表格内部列数必须一致（不同表格可以不同列数）。

    实测踩过：§2 里一张 2 列表与一张 3 列表之间只差一个空行，
    Markdown 会把它们并成一张表，后两行错位渲染；另有单行 2 列挂进 3 列表尾部。
    同类问题在 HANDOFF 里也发现了（单元格被物理换行截断成裸文本续行）。
    这类问题肉眼扫文档看不出来，但读者看到的是错位的表格。
    """

    def ncols(line):
        # 统计未被反斜杠转义的竖线（不用正则，避免转义层数问题）
        n, prev = 0, ""
        for ch in line:
            if ch == "|" and prev != "\\":
                n += 1
            prev = ch
        return n - 2

    bad = []
    targets = list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md"))
    for p in targets:
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(("_scratch/", "node_modules/")):
            continue
        start, width = 0, 0
        for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.startswith("|"):
                start, width = 0, 0
                continue
            c = ncols(line)
            if width == 0:
                start, width = i, c
            elif c != width:
                bad.append("%s:%d %d 列（该表从第 %d 行起为 %d 列）"
                           % (rel, i, c, start, width))
    assert not bad, "文档表格列数不自洽：" + "\n".join(bad)


def test_throttle_panel_location_matches_code():
    """SPEC 若提到节流面板曾挂在配置页，必须同时指明它已并入健康卡。

    实测：r420 把「节流与干预」从「配置 · 全局参数」搬进 `#healthcard .hpace`，
    但 SPEC 的缺陷对照表仍只在"问题"列写"挂在全局参数下"，"修法"列没写落点变化，
    读者会去配置页找这块面板。
    """
    live = "节流与干预" in WEBUI and "hpace" in WEBUI
    if not live:
        pytest.skip("界面已无节流与干预子区，SPEC 需人工复核")
    assert "#healthcard .hpace" in SPEC or "并入健康卡" in SPEC, (
        "SPEC 未写明节流面板已并入健康卡（现落点 #healthcard .hpace）")
    for line in SPEC.splitlines():
        if "节流状态面板" not in line:
            continue
        assert ("并入健康卡" in line or "不再挂在" in line), (
            "节流面板那一行只写了旧位置，没写最终落点：%s" % line.strip()[:80])


def test_spec_health_slot_labels_match_ui():
    """SPEC §5.5 描述的会话槽位文案必须与界面 `LBL` 表一致。

    实测（2026-10-27 核对）：SPEC 写「PC 入口可达 / H5 需重登」、
    演示态「PC 演示 / H5 演示」，与 `webui.py` 的 `LBL` 表
    （`page_ok:'入口可达'`、`login_required:'需重登'`）及
    `surf+' 演示'` 完全对应。这条防的是文案改名后文档不跟。
    """
    w = WEBUI
    if "page_ok:" not in w or "login_required:" not in w:
        pytest.skip("界面 LBL 表结构已变，需人工核对")
    m = re.search(r"const LBL=\{(.*?)\}", w, re.S)
    assert m, "未找到会话槽位 LBL 表"
    table = m.group(1)
    assert "page_ok:'入口可达'" in table, "LBL 表里 page_ok 文案已改，SPEC 需同步"
    assert "login_required:'需重登'" in table, "LBL 表里 login_required 文案已改"
    spec = SPEC
    assert "入口可达" in spec and "需重登" in spec, (
        "SPEC §5.5 未写出槽位真实文案（入口可达 / 需重登）")
    assert " 演示" in w, "界面已无「演示」后缀，SPEC 的演示态描述需复核"


def test_playbook_defaults_block_matches_code():
    """PLAYBOOK「默认值与本机取值」块里的代码默认值必须等于 `pacing.DEFAULTS`。

    这行是"一行写五个默认值"的浓缩表述，代码改默认后最容易静默过期，
    而读者会拿它判断"我没配置时到底跑多少"。
    """
    pace = (ROOT / "core" / "pacing.py").read_text(encoding="utf-8", errors="replace")
    pb = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    if not pb.exists():
        pytest.skip("PLAYBOOK 不存在")
    text = pb.read_text(encoding="utf-8", errors="replace")
    # PLAYBOOK 存在就必须有「代码默认」块——缺了说明该节被删/改名，
    # 此时 skip 等于静默失效（守护没了却仍显示绿）。
    assert "代码默认" in text, "PLAYBOOK 已删掉「代码默认」块，本门禁失去锚点，需人工补回"
    # 默认值块跨两行（第一行 4 个 TTL 键，第二行 breaker base/cap），必须整体取
    lines = text.splitlines()
    idx = next((k for k, l in enumerate(lines) if "代码默认" in l and "fast_ttl" in l), None)
    assert idx is not None, "PLAYBOOK「代码默认」行里没有 fast_ttl，需人工核对"
    line = " ".join(lines[idx:idx + 3])
    offenders = []
    for key, label in (("fast_ttl_min", "fast_ttl"), ("slow_ttl_min", "slow_ttl"),
                       ("near_ratio", "near"), ("stagger_seconds", "stagger"),
                       ("breaker_base_s", "base"), ("breaker_cap_s", "cap"),
                       ("login_cooldown_s", "login_cooldown")):
        m = re.search(r"%s\"\s*:\s*([0-9.]+)" % key, pace)
        if not m:
            continue
        want = m.group(1)
        if want.endswith(".0"):
            want = want[:-2]
        if not re.search(r"%s[^0-9]{0,3}%s(?![0-9])" % (label, re.escape(want)), line):
            offenders.append("%s 应为 %s（文档：%s）" % (label, want, line.strip()[:60]))
    assert not offenders, "PLAYBOOK 默认值块与 DEFAULTS 不符：%s" % offenders

    # 键集合完整性：DEFAULTS 里每个标量键都要在这两行里出现（用中文别名映射），
    # 否则新增/改名的键会静默漏写——实测 warmup 两项就漏了很久。
    # 这里只校验"文档块提到过"，具体值由上面的逐项比对负责。
    ALIAS = {
        "fast_ttl_min": "fast_ttl", "slow_ttl_min": "slow_ttl",
        "near_ratio": "near", "stagger_seconds": "stagger",
        "min_gap_s": "min_gap", "per_minute": "per_minute",
        "breaker_base_s": "base", "breaker_cap_s": "cap",
        "login_cooldown_s": "login_cooldown", "warmup_enabled": "warmup",
        "warmup_platforms": "warmup",
    }
    gone = [k for k, alias in ALIAS.items()
            if re.search(r'"%s"\s*:' % k, pace) and alias not in line]
    assert not gone, (
        "PLAYBOOK 默认值块漏了这些 DEFAULTS 键（或其别名）：%s —— "
        "读者会以为没有该配置项" % gone)


def test_breaker_backoff_ladder_matches_code():
    """文档写的退避阶梯必须与 `ChannelBreaker` 的 base/cap 实参推导一致。

    实测踩过：CAPTCHA_SOLUTION 写「指数退避（15/60/180 分钟）」，
    而代码是 `base_s=300`、`cap_s=3600`、`min(cap, base*2^(n-1))`
    → 实际阶梯是 5/10/20/40/60 分钟。照文档排障会等错时长。
    """
    pace = (ROOT / "core" / "pacing.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"def __init__\(self,\s*base_s=(\d+),\s*cap_s=(\d+)", pace)
    if not m:
        pytest.skip("ChannelBreaker 默认参数已变，需人工核对")
    base, cap = int(m.group(1)), int(m.group(2))
    ladder, cur = [], base
    while True:
        ladder.append(cur // 60)
        if cur >= cap:
            break
        cur = min(cap, cur * 2)
    expect = "/".join(str(x) for x in ladder)
    doc = (ROOT / "docs" / "CAPTCHA_SOLUTION.md")
    if not doc.exists():
        pytest.skip("CAPTCHA_SOLUTION 不存在")
    text = doc.read_text(encoding="utf-8", errors="replace")
    if "指数退避" not in text:
        pytest.skip("文档未描述退避")
    assert expect in text, (
        "文档未写出真实的退避阶梯 %s 分钟（base_s=%d / cap_s=%d）" % (expect, base, cap))
    for stale in ("15/60/180", "15、60、180"):
        assert stale not in text, "文档仍写旧阶梯 %s" % stale


def test_breaker_kinds_documented_match_code():
    """PLAYBOOK 的「现行实现（真值）」表必须覆盖 classify_failure 的全部返回值和 Breaker 的 kind。

    防的是：分类函数新增/改名了状态，而文档里的退避表仍写着旧的四类，
    读者按文档排障会找不到对应行。
    """
    playbook_path = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    if not playbook_path.exists():
        pytest.skip("PLAYBOOK 不存在")
    doc = playbook_path.read_text(encoding="utf-8")
    pacing = (ROOT / "core" / "pacing.py").read_text(encoding="utf-8")

    # classify_failure 的字符串返回值
    fn_start = pacing.find("def classify_failure(")
    assert fn_start > 0, "未找到 classify_failure"
    fn_end = pacing.find("\nclass ", fn_start)
    body = pacing[fn_start:fn_end if fn_end > 0 else fn_start + 3000]
    kinds = set(re.findall(r'return\s+"([a-z_]+)"', body))
    assert kinds, "未解析到 classify_failure 的返回值"

    # 只看「现行实现（真值）」那一节，避免全文其它小节的同名提及造成假绿
    start = doc.find("#### 现行实现（真值")
    assert start > 0, "PLAYBOOK 缺少「现行实现（真值）」小节"
    tail = doc.find("\n### ", start + 10)
    section = doc[start:tail if tail > 0 else len(doc)]
    assert len(section) > 200, "真值小节内容过少，可能被删空"

    # 每个 kind 都必须以表格行形式出现：| `kind` |
    missing = [k for k in sorted(kinds)
               if ("| `%s`" % k) not in section]
    assert not missing, "PLAYBOOK 真值表缺少分类行: %s" % missing

def test_playbook_claimed_improvements_hold():
    """PLAYBOOK 现况表标「已解决」的指标，近期日志不得复现。

    口径：按**日期**判定，不按日志行数——本机一天重启数十次，行数与时间不成比例。
    当前钉 SessionBusyError（文档称 2026-10-23 07:04 后 0 次）；
    若近期又出现，说明功能退化或文档需更新。
    """
    playbook_path = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    log_path = ROOT / "logs" / "monitor.log"
    if not playbook_path.exists() or not log_path.exists():
        pytest.skip("PLAYBOOK 或日志不存在")
    doc = playbook_path.read_text(encoding="utf-8", errors="replace")
    if "现况对照" not in doc:
        pytest.skip("PLAYBOOK 尚无现况对照表")

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    hits = [l for l in lines if "SessionBusyError" in l]
    if not hits:
        return  # 从未出现，与「已解决」一致
    last_date = hits[-1][:10]
    # 文档声明的最后出现日期
    m = re.search(r"SessionBusyError.*?(\d{4}-\d{2}-\d{2}) 07:04", doc)
    if not m:
        pytest.skip("文档未给出 SessionBusyError 的最后出现日期")
    declared = m.group(1)
    assert last_date <= declared, (
        "日志中 SessionBusyError 最后出现在 %s，晚于文档声明的 %s——"
        "要么功能退化，要么文档需更新" % (last_date, declared))

def test_playbook_section9_keys_and_landing_points_exist():
    """PLAYBOOK §9 的实现表：列的配置键必须在 config.example.yaml，落点必须能找到。

    防的是：节流功能重构后键改名/删键/移模块，而这张"已落地实现"表仍指着旧名字，
    读者照着配却不生效。
    """
    playbook_path = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    cfg_path = ROOT / "config.example.yaml"
    if not playbook_path.exists() or not cfg_path.exists():
        pytest.skip("PLAYBOOK 或示例配置不存在")
    doc = playbook_path.read_text(encoding="utf-8", errors="replace")
    cfg = cfg_path.read_text(encoding="utf-8", errors="replace")

    start = doc.find("## 9. 已落地实现")
    assert start > 0, "PLAYBOOK 缺少 §9 已落地实现"
    end = doc.find("\n## 10.", start)
    section = doc[start:end if end > 0 else len(doc)]

    # 表内用反引号写的键；含花括号枚举的展开后逐个验证叶子名
    raw_keys = set(re.findall(r"`([a-z_]+(?:\.[a-z_{},]+)+)`", section))
    assert len(raw_keys) >= 6, "§9 配置键解析过少（%d）" % len(raw_keys)
    leaves = set()
    for k in raw_keys:
        head, _, tail = k.rpartition(".")
        if tail.startswith("{") and tail.endswith("}"):
            for name in tail.strip("{}").split(","):
                name = name.strip()
                if name:
                    leaves.add(name)
        elif tail:
            leaves.add(tail)
    assert leaves, "未能从 §9 配置键中解析出叶子名"
    # 只验证配置段里的键；`last_round.busy` 这类是运行时 API 字段，不是 config 键
    CONFIG_ROOTS = {"schedule", "crawler", "notifier", "image_host"}
    cfg_leaves = set()
    for k in raw_keys:
        root = k.split(".")[0]
        if root not in CONFIG_ROOTS:
            continue
        tail = k.rpartition(".")[2]
        if tail.startswith("{") and tail.endswith("}"):
            for name in tail.strip("{}").split(","):
                name = name.strip()
                if name:
                    cfg_leaves.add(name)
        elif tail:
            cfg_leaves.add(tail)
    assert cfg_leaves, "未解析到属于配置段的键"
    missing = sorted(l for l in cfg_leaves if l not in cfg)
    assert not missing, "§9 列的配置键在 config.example.yaml 中不存在: %s" % missing

    # 落点里点名的 py 文件必须存在
    files = set(re.findall(r"((?:core|crawlers)/[a-z_]+\.py)", section))
    assert files, "§9 未点名任何模块文件"
    gone = [f for f in sorted(files) if not (ROOT / f).exists()]
    assert not gone, "§9 落点指向不存在的文件: %s" % gone

def test_doc_referenced_config_keys_exist_in_example():
    """文档以 `crawler.x` / `schedule.x` 形式点名的配置键，示例配置里必须存在。

    实测踩过：`crawler.tls_impersonate` 在 4 个 crawler 里被读取、
    PLAYBOOK 也两次教人用它排障，但 config.example.yaml 里根本没这个键——
    用户照文档配了，以为是"默认值"，实际是"看不见的开关"。
    """
    import yaml
    cfg_path = ROOT / "config.example.yaml"
    if not cfg_path.exists():
        pytest.skip("示例配置不存在")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert isinstance(cfg, dict), "示例配置不是映射"

    docs = [ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md",
            ROOT / "docs" / "EXECUTION_SPEC_LATEST.md",
            ROOT / "docs" / "HANDOFF.md"]
    ROOTS = {"crawler", "schedule", "notifier"}
    referenced = set()
    for p in docs:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.findall(r"`((?:crawler|schedule|notifier)\.([a-z_][a-z0-9_]*))`", text):
            referenced.add((m[0], m[1]))
    assert referenced, "未从文档解析到任何配置键引用"

    raw_cfg = cfg_path.read_text(encoding="utf-8", errors="replace")
    missing = []
    for full, leaf in sorted(referenced):
        root = full.split(".")[0]
        section = cfg.get(root)
        if not isinstance(section, dict):
            missing.append("%s（示例配置无 %s 段）" % (full, root))
            continue
        if leaf in section:
            continue
        # 允许以「注释示例」出现（如 `# proxy: http://...`，默认关闭的可选项）
        if re.search(r"^\s*#\s*%s\s*:" % re.escape(leaf), raw_cfg, re.M):
            continue
        missing.append(full)
    assert not missing, "文档提到但示例配置缺失的键: %s" % missing


def test_example_config_keys_are_actually_read():
    """反向：config.example.yaml 里活着的每个叶子键，代码里必须真的读它。

    只查"文档提到的键存在"是不够的——示例里可能躺着**代码从不读取**的键
    （历史遗留），用户照示例配了却毫无效果，比"看不见的开关"更隐蔽。
    注释掉的行（默认关闭的可选）不算：那是提案不是现状。
    """
    import yaml
    cfg_path = ROOT / "config.example.yaml"
    if not cfg_path.exists():
        pytest.skip("示例配置不存在")

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    assert isinstance(cfg, dict), "示例配置不是映射"

    def leaves(d, pre=""):
        out = []
        for k, v in d.items():
            key = pre + str(k)
            if isinstance(v, dict):
                out += leaves(v, key + ".")
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                out += [key + "." + kk for kk in v[0]]
            elif isinstance(v, list):
                continue
            else:
                out.append(key)
        return out

    src = ""
    for p in [ROOT / "main.py", ROOT / "webui.py", ROOT / "wizard.py",
              ROOT / "report.py"]:
        if p.exists():
            src += p.read_text(encoding="utf-8", errors="replace")
    for p in (ROOT / "core").rglob("*.py"):
        src += p.read_text(encoding="utf-8", errors="replace")
    for p in (ROOT / "crawlers").rglob("*.py"):
        src += p.read_text(encoding="utf-8", errors="replace")

    # 结构段的键（如 users.routes）由 schema 驱动，不按字面 get()
    structural = {"name", "routes", "platforms", "notifier", "users"}
    dead = []
    for key in leaves(cfg):
        leaf = key.split(".")[-1]
        if leaf in structural:
            continue
        if ('"%s"' % leaf) in src or ("'%s'" % leaf) in src:
            continue
        # 允许无引号的 .get(leaf ...) 形态
        if re.search(r"\.get\(\s*%s\b" % re.escape(leaf), src):
            continue
        dead.append(key)
    assert not dead, (
        "示例配置里有代码从不读取的键（用户配了也没效果）：%s" % dead)


def test_image_host_primary_path_documented():
    """文档不得把已死的 freeimage 写成效力主通路；主通路必须是代码里的 ghimg。

    实测踩过：HANDOFF 架构块写「report.py → freeimage 图床（直连）」，
    而 `report.py` 与 `config.example.yaml` 早已把 ghimg 定为主通路，
    freeimage 端点被封、只留熔断兼容——照架构块配的人会踩到死链。
    """
    report = ROOT / "report.py"
    if not report.exists():
        pytest.skip("report.py 不存在")
    src = report.read_text(encoding="utf-8", errors="replace")
    assert "upload_ghimg" in src, "report.py 里没有 ghimg 上传实现"
    assert 'provider == "ghimg"' in src, "report.py 未把 ghimg 当 provider 分支"

    example = (ROOT / "config.example.yaml")
    if example.exists():
        raw = example.read_text(encoding="utf-8", errors="replace")
        assert re.search(r"^\s+provider:\s*ghimg", raw, re.M), (
            "config.example.yaml 的默认 provider 不是 ghimg")

    handoff = ROOT / "HANDOFF.md"
    if handoff.exists():
        text = handoff.read_text(encoding="utf-8", errors="replace")
        # 架构块那一行：不得再把 freeimage 写成 report.py 的落点
        for line in text.splitlines():
            if "report.py" in line and "freeimage" in line:
                assert "ghimg" in line, (
                    "HANDOFF 把 freeimage 写成 report.py 的主通路：%s" % line.strip()[:90])


def test_fliggy_transfer_claim_matches_code():
    """「飞猪没有中转」这类否定性断言，必须与 crawler 的实际解析能力对齐。

    实测踩过：HANDOFF §6 第 5 条长期写「飞猪 PC 中转缺失（页面无中转分区）」，
    而 `crawlers/fliggy.py` 早已解析折叠中转块（两段一转），r386 起连国际
    中转卡片也建行入库。读者据此以为飞猪不能比中转价，会漏掉一条真实通路。
    """
    fliggy = ROOT / "crawlers" / "fliggy.py"
    if not fliggy.exists():
        pytest.skip("fliggy crawler 不存在")
    src = fliggy.read_text(encoding="utf-8", errors="replace")

    # 代码侧事实：中转块确实被解析
    parses_transfer = ("中转" in src and "transCity" in src) or ("中转块" in src)
    if not parses_transfer:
        pytest.skip("fliggy 已不解析中转，文档可写「缺失」")

    handoff = ROOT / "HANDOFF.md"
    if not handoff.exists():
        pytest.skip("HANDOFF 不存在")
    for line in handoff.read_text(encoding="utf-8", errors="replace").splitlines():
        # 只抓「飞猪…中转缺失/无中转分区」这种紧密否定句式；
        # 历史记录里一行同时提到「飞猪」和「中转」是常态，不能按同现判定。
        if not re.search(r"飞猪[^\n]{0,20}中转[^\n]{0,10}(?:缺失|无)", line):
            continue
        if any(k in line for k in ("已不成立", "~~", "曾经", "旧称", "不再")):
            continue
        raise AssertionError(
            "HANDOFF 仍称飞猪中转缺失，但 crawler 已解析中转块：%s" % line.strip()[:90])

    # 「仅直达」同族：库内 fliggy 元素实测有大量中转（transfer=true / transCity 非空），
    # 任何文档写"飞猪仅直达/只有直飞"都属过期。允许带"旧记/已过期/推翻"的更正语境。
    for p in (ROOT / "HANDOFF.md", ROOT / "README.md",
              ROOT / "README_EN.md", ROOT / "docs" / "INTL_DESIGN.md",
              ROOT / "docs" / "CHANNEL_SESSION.md"):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "飞猪" not in line and "fliggy" not in line.lower():
                continue
            if not re.search(r"(仅直达|只有直飞|only direct)", line, re.I):
                continue
            if any(k in line for k in ("旧记", "已过期", "推翻", "曾经", "旧称")):
                continue
            raise AssertionError(
                "%s 仍称飞猪「仅直达」，但库内有大量中转元素：%s"
                % (p.name, line.strip()[:90]))


def test_handoff_core_units_all_blocks_count():
    """HANDOFF 说 test_core_units.py 里剩几个 `ALL = ` 收集块，必须与文件真实一致。

    实测踩过：原写「遗留两个」，实际只剩 1 个——这类"具体数字"最容易随重构过期，
    而读者会拿它判断"能不能直跑"。
    """
    core = ROOT / "tests" / "test_core_units.py"
    handoff = ROOT / "HANDOFF.md"
    if not core.exists() or not handoff.exists():
        pytest.skip("文件不存在")
    actual = sum(1 for ln in core.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.startswith("ALL = "))
    text = handoff.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"(一|两|二|\d+)\s*个\s*\*{0,2}\s*`ALL = `\s*\*{0,2}\s*收集块", text)
    assert m, ("HANDOFF 已不再提 `ALL = ` 收集块数量——"
              "本门禁失去锚点，需人工确认该节是否被删/改写")
    zh = {"一": 1, "两": 2, "二": 2}
    claimed = zh.get(m.group(1)) or int(m.group(1))
    assert claimed == actual, (
        "HANDOFF 说剩 %d 个 `ALL = ` 块，实际 %d 个" % (claimed, actual))


def test_spec_mandatory_gates_have_uitest_coverage():
    """§8.3「必须长期保持的门禁」里点名的视口档，uitest 必须真的用到。

    实测踩过：第 9 条原写「渠道入口列头/行左缘对齐 ≤ 1px（1100/1280/1512）」，
    但 v304e 把渠道入口重做成「渠道 × 4 入口矩阵」后，这三个宽度档已无用例，
    1100 甚至根本不是视口（只是别处的测试时间戳）。读者会以为还有门禁兜底。
    """
    spec = ROOT / "docs" / "EXECUTION_SPEC_LATEST.md"
    uitest = ROOT / "docs" / "uitest.py"
    if not spec.exists() or not uitest.exists():
        pytest.skip("规范或 uitest 不存在")

    body = uitest.read_text(encoding="utf-8", errors="replace")
    used = set(int(x) for x in re.findall(r'"width":\s*(\d{3,4})', body))
    assert used, "uitest 里读不到任何视口宽度"

    text = spec.read_text(encoding="utf-8", errors="replace")
    i = text.find("### 8.3")
    j = text.find("### 8.4", i)
    assert i >= 0 and j >= 0, "规范缺少 §8.3 或之后的 §8.4（锚点丢失，需人工补回）"
    section = text[i:j]

    # 只查写成「a/b/c 档」的宽度枚举，且要求每个数字都是真实视口。
    # 引用旧条目时会把废弃档位原样抄一遍（如「旧条目写 1100/1280/1512」），
    # 那是历史引述不是承诺——同一行出现「已过期/旧条目/勿再引用」时跳过。
    offenders = []
    for line in section.splitlines():
        if any(k in line for k in ("已过期", "旧条目", "勿再引用", "已不存在")):
            continue
        for m in re.finditer(r"(\d{3,4}/\d{3,4}(?:/\d{3,4})+)", line):
            nums = [int(x) for x in m.group(1).split("/")]
            missing = [n for n in nums if n not in used]
            if missing:
                offenders.append("%s（缺：%s）" % (m.group(1), missing))
    assert not offenders, (
        "§8.3 点名的视口档在 uitest 里没有用例：%s\n可用宽度：%s"
        % (offenders, sorted(used)))


def test_readme_airline_examples_resolve():
    """README 举的航司输入示例（`MU`/`东方航空`/`东航`/`!9C`/`!春秋`）必须真能解析。

    文档用这几个例子解释「三写法等价 + `!` 前缀排除」。若 alias 词表被重构、
    简称改名或漏项，读者照着文档输入会解析不出来——而这几个例子正是
    「输入即时解析预览」功能的说明书。
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from core.airlines import alias_payload
    alias = alias_payload()["alias"]

    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    # 只在该行提到「三写法等价」时校验，避免把别处的航司缩写当示例
    line = next((l for l in readme.splitlines()
                 if "三写法等价" in l and "MU" in l), None)
    assert line is not None, "README 里找不到「三写法等价」示例行，本门禁失去锚点"

    for token in re.findall(r"`([^`]+)`", line):
        for part in token.split(","):
            raw = part.strip().lstrip("!")
            if not raw or len(raw) > 12:
                continue
            # 跳过非航司记号（如纯占位符 N、¥N）
            if re.fullmatch(r"[N¥]", raw):
                continue
            assert raw in alias, (
                "README 用作示例的航司写法 %r 无法被 core.airlines 解析" % raw)


def test_readme_notification_channels_match_code():
    """README/EN 声称的通知通道必须都在 `core/notifier.py`（及 report/main）里真有实现。

    实测（2026-10-28）：README 列出「钉钉 / Server酱 / ntfy / Bark / 阿里云 / 邮件」
    六个通道，逐个 grep 均能落到具体实现函数，故文档准确——但此前没有任何门禁
    守着这条。通道被合并/删除而文档不删，读者会照着配一个发不出去的渠道。
    """
    CHANNELS = {                       # 中文名 → 代码里的特征串
        "钉钉": "dingtalk",
        "Server酱": "serverchan",
        "ntfy": "ntfy",
        "Bark": "bark",
        "阿里云": "aliyun",
        "邮件": "smtp",
    }
    src = []
    for rel in ("core/notifier.py", "core/alerter.py", "report.py", "main.py"):
        p = ROOT / rel
        if p.exists():
            src.append(p.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(src).lower()
    assert blob, "通知相关源码全部缺失，本门禁失去检查对象"

    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    readme_en = (ROOT / "README_EN.md").read_text(encoding="utf-8", errors="replace")

    checked = 0
    for cn, token in CHANNELS.items():
        # 只在该通道确实被 README 声称时校验（README 可能选择不宣传某个后端）
        if cn not in readme and token not in readme_en.lower():
            continue
        checked += 1
        assert token in blob, (
            "README 声称支持「%s」，但代码里找不到 %r —— 读者会配一个不存在的通道"
            % (cn, token))
    assert checked >= 4, (
        "只在 README 里匹配到 %d 个通知通道，本门禁疑似失去锚点" % checked)


def test_spec_historical_run_notes_are_time_bound():
    """SPEC 里「新增 N 项门禁全过」「X passed」这类运行记录必须带时间/轮次限定。

    实测踩过（2026-10-28）：§1.3 保留着 2026-10-27 的复跑记录（「新增 6 项文档
    契约门禁全过」），而门禁已从 6 项扩到 91 项、用例总数从 4066 涨到 4200+。
    那段读起来像现状，读者会以为门禁只有 6 条、总数只有 4066。
    """
    spec = (ROOT / "docs" / "EXECUTION_SPEC_LATEST.md").read_text(encoding="utf-8")
    lines = spec.splitlines()

    TIME_MARK = re.compile(r"20\d\d-\d\d-\d\d|\d{1,2}:\d{2}|第[一二三四五六七八九十]+次|当时|那轮")
    # 「0 failed」是**验收标准**（全绿的定义），不是某次运行的快照——豁免。
    # 只有带具体数字的「N passed」「N 项全过」才是运行记录。
    offenders = []
    checked = 0
    for i, line in enumerate(lines):
        if not re.search(r"\d+\s*passed|\d+\s*项[^\n]{0,12}全过", line):
            continue
        if re.search(r"(^|\D)0\s*failed", line) and not re.search(r"\d+\s*passed", line):
            continue          # 纯验收标准
        checked += 1
        window = "\n".join(lines[max(0, i - 2):i + 1])
        if not TIME_MARK.search(window):
            offenders.append("L%d: %s" % (i + 1, line.strip()[:80]))
    assert checked >= 3, "只找到 %d 处运行记录，本门禁疑似失去锚点" % checked
    assert not offenders, (
        "SPEC 里的运行记录没有时间/轮次限定，会被读成现状：\n" + "\n".join(offenders[:6]))


def test_spec_startup_keys_are_actually_startup_level():
    """SPEC §4.1b 的「启动级」清单必须与 `webui.py::_startup_vals` 实际产物一致。

    实测踩过（2026-10-28）：README 三处都写六项启动级（含 `web.host` / `run_on_start`），
    而界面的重启中心空态文案只写四项，漏了后两项；EXECUTION_SPEC 里**根本没有
    这一节**——新配置项该热加载还是该重启，全靠读代码猜。
    这条门禁要求：SPEC 必须持续声明这张表，且表里的键必须仍由 `_startup_vals` 产出。
    """
    spec = (ROOT / "docs" / "EXECUTION_SPEC_LATEST.md").read_text(encoding="utf-8")
    i = spec.find("### 4.1b")
    assert i > 0, "SPEC 缺少 §4.1b「配置生效契约」，本门禁失去锚点"
    j = spec.find("\n### ", i + 5)
    section = spec[i:j if j > 0 else len(spec)]

    # 1) 六项启动级都必须在**表格行**里点名（不能只在散文里顺带提到）。
    #    实测负控：只把表格里的键改掉时，若正文别处还有该词，纯 in 判断会放行。
    table_rows = [l for l in section.splitlines() if l.startswith("| ")]
    rows_blob = "\n".join(table_rows)
    required = ("db_path", "log_path", "user_data_dir", "browser_dir",
                "web.host", "run_on_start")
    missing = [k for k in required if k not in rows_blob]
    assert not missing, "§4.1b 启动级**表格**里缺少：%s" % missing

    # 2) 代码侧：`_startup_vals` 必须仍产出路径四件
    k = WEBUI.find("def _startup_vals(")
    assert k > 0, "webui.py 里找不到 _startup_vals()，本门禁失去代码锚点"
    body = WEBUI[k:k + 2000]
    for key in ("db_path", "log_path", "user_data_dir", "browser_dir"):
        assert '"%s"' % key in body, (
            "_startup_vals 不再产出 %s —— §4.1b 的启动级表需同步" % key)
    # r345 起 host / run_on_start 也在同一函数里产出
    assert '"host"' in body and '"run_on_start"' in body, (
        "_startup_vals 不再产出 host/run_on_start —— 启动级表里这两项要复核")

    # 3) 热加载清单必须与「启动级」明确分开，不能又出现在启动级表里
    hot_i = section.find("**热加载")
    assert hot_i > 0, "§4.1b 未列出「热加载」清单，读者无法判断改了要不要重启"
    hot = section[hot_i:hot_i + 400]
    for k2 in ("web.port", "无头"):
        assert k2 in hot, "§4.1b 热加载清单缺少 %s" % k2


def test_intl_city_count_claims_match_data():
    """README/EN 写的「国际面板 272 城 / 33 热门」必须等于 `core.intl` 的实际数据。

    实测踩过（2026-10-28）：我一开始去数 `core.citydata.CITY`，得到 289 城/20 热门，
    差点报「文档写错」——那份是**大陆城市表**（判国内/国际用），不是国际面板数据。
    真正的数据源是 `core.intl.INTL_CITY_NAME` / `INTL_CITY_HOT`（实测正好 272/33）。
    这条门禁把"用哪份数据"也钉住，避免下一个人重走这个弯。
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from core.intl import INTL_CITY_NAME, INTL_CITY_HOT, INTL_REGIONS, INTL_REGION

    n_city = len(INTL_CITY_NAME)
    n_hot = len(INTL_CITY_HOT)
    assert n_city > 100, "国际城市表过小（%d），疑似解析失败" % n_city
    assert n_hot > 0, "国际热门城市为空"

    docs = {
        "README.md": (r"(\d+) 城（(\d+) 热门）", r"(\d+) 城点选（(\d+) 热门）"),
        "README_EN.md": (r"(\d+) destinations \((\d+) highlighted\)",
                         r"(\d+) cities / (\d+) hot"),
    }
    checked = 0
    for name, pats in docs.items():
        p = ROOT / name
        assert p.exists(), "%s 不存在" % name
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat in pats:
            for m in re.finditer(pat, text):
                checked += 1
                assert int(m.group(1)) == n_city, (
                    "%s 写 %s 个国际城市，实际 %d：%s"
                    % (name, m.group(1), n_city, m.group(0)))
                assert int(m.group(2)) == n_hot, (
                    "%s 写 %s 个热门城市，实际 %d（core.intl.INTL_CITY_HOT）：%s"
                    % (name, m.group(2), n_hot, m.group(0)))
    assert checked >= 2, (
        "README/EN 里只匹配到 %d 处「N 城 / N 热门」表述，本门禁疑似失去锚点" % checked)

    # 地区分组数也要对得上（面板按地区分组是同一件事的组成部分）
    n_region = len(INTL_REGIONS)
    assert re.search(r"按地区分组", "".join(
        (ROOT / n).read_text(encoding="utf-8", errors="replace") for n in docs)), (
        "README 未提「按地区分组」")
    assert n_region >= 5, "国际地区分组过少（%d）" % n_region

    # README 多处写「五洲目的地」。核对：分组里必须覆盖亚/欧/美/大洋/非五个洲，
    # 其中亚洲按区块细分（港澳台/日韩/东南亚/南亚/中东）。实测踩过：
    # INTL_REGION 比 INTL_CITY_NAME 多 BHX/NCL 两条（无展示名），
    # 数错集合会得出 274 城；面板真正展示的是 INTL_CITY_NAME 的 272 个。
    names = set(INTL_REGIONS)
    asia_blocks = {"港澳台", "日韩", "东南亚", "南亚", "中东"}
    assert asia_blocks <= names, (
        "国际分组缺亚洲区块：%s" % sorted(asia_blocks - names))
    for c in ("欧洲", "美洲", "大洋洲", "非洲"):
        assert c in names, "国际分组缺 %s，README 的「五洲目的地」不成立" % c
    assert re.search(r"五洲", (ROOT / "README.md").read_text(encoding="utf-8")), (
        "README 不再提「五洲」，需复核这句还需不需要")
    assert len(INTL_REGION) >= n_city, (
        "INTL_REGION(%d) 少于 INTL_CITY_NAME(%d)，分组表漏了城市"
        % (len(INTL_REGION), n_city))


def test_readme_feature_parity():
    """README 与 README_EN 的「特性矩阵」必须覆盖同一批能力。

    RELEASE_PROCESS §1 要求 "feature counts and claims stay in parity"。
    实测踩过：CN 矩阵 41 行、EN 30 行，其中「可视化对齐」整条在 EN 缺失——
    英文读者会以为没有"网页走势与推送图同密度"这项能力。
    合并同类行是允许的（如出发时段/中转衔接并入 Qualification），
    但合并后必须仍有对应词面，所以判据是"英文关键词族里至少命中一个"。
    """
    cn_p, en_p = ROOT / "README.md", ROOT / "README_EN.md"
    if not cn_p.exists() or not en_p.exists():
        pytest.skip("README 缺失")

    def matrix(path, heading):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        try:
            i = next(k for k, l in enumerate(lines) if l.startswith(heading))
        except StopIteration:
            return None
        rows = []
        for l in lines[i + 1:]:
            if l.startswith("## "):
                break
            if l.startswith("| "):
                cells = [c.strip().strip("*").strip()
                         for c in l.strip().strip("|").split("|")]
                if len(cells) >= 2 and cells[0] not in ("能力", "Capability", "---"):
                    rows.append(cells)
        return rows

    cn = matrix(cn_p, "## 特性矩阵")
    en = matrix(en_p, "## Feature matrix")
    assert cn and en, "解析不到特性矩阵"
    en_blob = " ".join(" ".join(r) for r in en).lower()

    # CN 能力名 → EN 侧可接受的词族（任命中即算覆盖）
    FAMILY = {
        "五渠道明细": ["five-channel"],
        "多日期监控": ["multi-date"],
        "往返多返程日": ["round-trip"],
        "航线启停": ["pause"],
        "达标判定": ["qualification"],
        "出发时段挡位": ["departure", "qualification"],
        "中转衔接与直挂": ["layover", "qualification"],
        "多租户": ["multi-user"],
        "特价机票监控": ["special-fare"],
        "国际航班监控": ["international"],
        "聚合推送": ["aggregated push"],
        "强提醒": ["urgent"],
        "免打扰时段": ["quiet hours"],
        "同班比价": ["same-flight"],
        "推送预览与历史": ["preview"],
        "走势图": ["trends"],
        "关注航班台": ["watch studio"],
        "官方品牌语义层": ["brand"],
        "航班维度历史": ["flight-level history"],
        "达标点四档环": ["four-tier"],
        "页内跳转图谱": ["jump"],
        "价格日历": ["calendar"],
        "明细表": ["table"],
        "渠道健康": ["health"],
        "运行脉冲": ["pulse"],
        "子视图工作台": ["tabbed workspace", "six monitor views"],
        "可视化对齐": ["visualization parity", "information density"],
        "浏览器通知": ["notification"],
        "面板式配置台": ["panel config"],
        "全局配置中心": ["global config"],
        "配置全热加载": ["hot reload"],
        "配置搜索与导入导出": ["import"],
        "网页登录": ["login"],
        "演示模式": ["demo"],
        "数据窗口": ["data window"],
        "可靠性": ["reliability"],
    }
    missing = []
    for row in cn:
        name = row[0]
        fam = FAMILY.get(name)
        if not fam:
            continue
        if not any(k in en_blob for k in fam):
            missing.append("%s → %s" % (name, fam))
    assert not missing, "EN 特性矩阵缺少这些能力（或有新能力未登记词族）：%s" % missing

    # 反向：EN 有能力行、CN 完全没有对应词面时，中文读者同样会漏读。
    CN_FAMILY = {
        "five-channel": ["五渠道"], "multi-date": ["多日期"], "round-trip": ["往返"],
        "qualification": ["达标判定", "出发时段", "中转衔接"],
        "multi-user": ["多租户"], "special-fare": ["特价机票"],
        "international": ["国际航班"], "aggregated push": ["聚合推送"],
        "urgent alerts": ["强提醒"], "quiet hours": ["免打扰"],
        "preview": ["推送预览"], "trends": ["走势图"], "watch studio": ["关注航班台"],
        "brand": ["品牌"], "flight-level history": ["航班维度历史"],
        "four-tier": ["四档环"], "calendar, table, health": ["价格日历", "明细表", "渠道健康"],
        "panel config": ["面板式配置台"], "global config": ["全局配置中心"],
        "hot reload": ["热加载"], "search & import/export": ["导入导出"],
        "visualization parity": ["可视化对齐"], "reliability": ["可靠性"],
        "price guards": ["毒价", "价格上限"],
    }
    cn_blob = " ".join(" ".join(r) for r in cn)
    en_missing = []
    for row in en:
        name = row[0].lower()
        fam = CN_FAMILY.get(name)
        if not fam:
            continue   # 合并行（Login, demo, data window 等）已在正向校验里覆盖
        if not any(k in cn_blob for k in fam):
            en_missing.append("%s → %s" % (row[0], fam))
    assert not en_missing, "CN 特性矩阵缺少这些能力：%s" % en_missing


def test_readme_no_duplicate_feature_sections():
    """同一份 README 里不得出现两套讲同一件事的小节。

    实测踩过：README_EN 的「控制台一览」里同时有 `**Realtime search**` 段
    与 `### Real-time search` 段，两套都在讲实时检索、内容大部分重复，
    读者读到第二遍会怀疑是不是不同功能；而中文版只有一套。
    判据：同文中出现两个以上指向同一主题的标题/加粗段首即判失败。
    """
    TOPICS = {
        "实时检索": ["realtime search", "real-time search", "实时检索"],
    }
    for name in ("README.md", "README_EN.md"):
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        for topic, keys in TOPICS.items():
            lead = 0
            for line in text.splitlines():
                stripped = line.strip().lstrip("#* ").strip("* ")
                if not stripped:
                    continue
                # 只看"段首标题"：行首即主题词（允许前面有 ## ### 或 ** ）
                for k in keys:
                    if stripped.startswith(k):
                        lead += 1
                        break
            assert lead <= 1, (
                "%s 里有 %d 处「%s」段首，疑似重复小节（同一主题只应有一套）"
                % (name, lead, topic))


def test_readme_radar_refresh_cadence_matches_code():
    """README 写的雷达快照节奏（首采 90s / 每 2 小时）必须与 `webui.py` 的循环一致。

    实测：代码是 `time.sleep(90 if first else 7200)`，旧实现先睡 2 小时才首采，
    控制台刚启动会长时间空窗。文档若只写「每 2 小时」会让人以为首采也要等 2 小时。
    """
    webui_path = ROOT / "webui.py"
    if not webui_path.exists():
        pytest.skip("webui.py 不存在")
    src = webui_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"time\.sleep\((\d+)\s+if\s+first\s+else\s+(\d+)\)", src)
    assert m, ("webui.py 里找不到雷达快照循环 `time.sleep(N if first else M)`——"
              "实现已变，README 的节奏说明需人工核对")
    first_s, period_s = int(m.group(1)), int(m.group(2))
    assert period_s % 3600 == 0, "周期不是整小时，文档需要改写"
    period_h = period_s // 3600

    for name in ("README.md", "README_EN.md"):
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        # 只在这两处提到节奏时校验
        if "监控快照" not in text and "Monitoring trend" not in text:
            continue
        assert ("%d 秒" % first_s) in text or ("~%d s" % first_s) in text, (
            "%s 未写首采约 %d 秒（代码 time.sleep(%d if first else %d)）"
            % (name, first_s, first_s, period_s))
        assert ("每 %d 小时" % period_h) in text or ("every %d hours" % period_h) in text, (
            "%s 未写每 %d 小时刷新" % (name, period_h))


def test_fliggy_tax_pad_claim_matches_value():
    """文档对飞猪税垫的描述必须与 `FLIGGY_TAX_PAD` 的实际值一致。

    实测踩过：`FLIGGY_TAX_PAD` 早已归零（0），即**所有航线**都不再加税垫；
    而 README_EN 仍写「pad is waived **for international rows**」——
    读起来像"国内还在加"，与代码相反。
    """
    alerter = ROOT / "core" / "alerter.py"
    if not alerter.exists():
        pytest.skip("alerter 不存在")
    src = alerter.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^FLIGGY_TAX_PAD\s*=\s*(\d+)", src, re.M)
    assert m, "未找到 FLIGGY_TAX_PAD 定义"
    pad = int(m.group(1))

    # 全仓文档都查：INTL_DESIGN §1.6 曾写「垫税是国内裸价渠道特例」，
    # 读起来像"国内还在加"，而 pad 早已是 0——只查 README 会漏掉它。
    docs = [ROOT / "README.md", ROOT / "README_EN.md",
            ROOT / "docs" / "INTL_DESIGN.md",
            ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md",
            ROOT / "HANDOFF.md"]
    for p in docs:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "税垫" not in text and "surcharge pad" not in text.lower():
            continue
        if pad == 0:
            assert re.search(r"(不再加税垫|no longer adds a tax allowance|当前为 0|FLIGGY_TAX_PAD\s*=\s*0)", text), (
                "%s 未说明税垫已归零（FLIGGY_TAX_PAD=0）" % p.name)
            assert not re.search(r"waived for\s+international rows", text), (
                "%s 仍写「仅国际行豁免税垫」，但 pad=0 是全局不加" % p.name)
        else:
            assert re.search(r"\+?\s*%d\b" % pad, text), (
                "%s 未写明税垫值 %d" % (name, pad))

def test_playbook_named_identifiers_exist():
    """PLAYBOOK §10 之后的各轮小节点名了大量函数/常量；这些名字必须能在源码里找到。

    实测踩过：`_fc_key` 全仓不存在（真实是 `flight_key` / `_srx_flight_key`），
    读者按文档去找会扑空。本测试只覆盖**强特征**标识符（下划线开头或全大写常量），
    避免把 YAML 键、JS 属性、DOM API 误判为项目符号。
    """
    playbook_path = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    if not playbook_path.exists():
        pytest.skip("PLAYBOOK 不存在")
    doc = playbook_path.read_text(encoding="utf-8", errors="replace")

    start = doc.find("## 10. 第二轮")
    assert start > 0, "PLAYBOOK 缺少 §10"
    section = doc[start:]

    # 只取强特征：_snake_case 或 ALL_CAPS（≥4 字符）
    raw = set(re.findall(r"`(_[a-z][a-z0-9_]{3,}|[A-Z][A-Z0-9_]{3,})`", section))
    # 排除第三方/标准符号与文档自造术语
    EXCLUDE = {
        "None", "URL_TPL", "WEBGL_debug_renderer_info", "__ADDCHROME__",
        "QN205", "QN277", "MKT_CKID", "FAILURE_KINDS", "_bfa", "_m_h5_tk",
    }
    candidates = sorted(raw - EXCLUDE)
    assert len(candidates) >= 10, "解析到的标识符过少（%d）" % len(candidates)

    # 汇总源码（核心模块 + 包一层 webui，后者太大只取前 2MB）
    haystack = []
    for rel in ("main.py", "report.py"):
        p = ROOT / rel
        if p.exists():
            haystack.append(p.read_text(encoding="utf-8", errors="replace"))
    for sub in ("core", "crawlers"):
        d = ROOT / sub
        if d.is_dir():
            for f in d.glob("*.py"):
                haystack.append(f.read_text(encoding="utf-8", errors="replace"))
    web = ROOT / "webui.py"
    if web.exists():
        # 全文读，不截断——webui.py 约 390 万字符，截断会把后半段的
        # 函数误判为"不存在"（踩过：_probe_plat_lock 在 358 万字符处）
        haystack.append(web.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(haystack)

    missing = [c for c in candidates if c not in blob]
    assert not missing, "PLAYBOOK 点名但源码中找不到的标识符: %s" % missing

def test_intervention_thresholds_documented_match_code():
    """干预后趋势的判定阈值（70% / 40% / 30 分钟桶 / 16 桶 / 3 样本 / 连续 2 次）必须与代码一致。

    这些是读者用来判断「干预到底有没有效」的口径，改一处而文档没跟，
    会让人拿错阈值做决策。
    """
    playbook_path = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    if not playbook_path.exists():
        pytest.skip("PLAYBOOK 不存在")
    doc = playbook_path.read_text(encoding="utf-8", errors="replace")
    storage = (ROOT / "core" / "storage.py").read_text(encoding="utf-8", errors="replace")
    pacing = (ROOT / "core" / "pacing.py").read_text(encoding="utf-8", errors="replace")

    # 1) 30 分钟分桶
    assert "/ 1800" in storage, "干预趋势分桶不再是 1800 秒，文档的『每 30 分钟』需复核"
    assert "每 30 分钟" in doc

    # 2) 最多 16 桶
    #    r618 起分域切片在取数之后做（is_intl_route 是 Python 侧函数，
    #    SQL 表达不了），桶上限改由 `trend[:16]` 承担。判据守的是
    #    「上限是 16 个桶」这个语义，不绑某一种实现写法。
    assert "[:16]" in storage or "LIMIT 16" in storage, (
        "干预趋势桶数上限已变，文档的『16 个桶』需复核")
    assert "16 个桶" in doc or "16 桶" in doc

    # 3) 70% / 40% 回落阈值——必须锚在「干预后趋势」那一段，
    #    全文搜 "<40%" 会被别节的分档表撞上（实测假绿）
    i = doc.find("干预后每 30 分钟趋势")
    assert i > 0, "PLAYBOOK 缺少干预后趋势小节"
    seg = doc[i:i + 900]
    assert ">= 0.7" in storage and "< 0.4" in storage, "回落阈值已变，文档的 70%/40% 需复核"
    assert "≥70%" in seg, "干预趋势段未写 70% 恢复线"
    assert "<40%" in seg, "干预趋势段未写 40% 回落线"

    # 4) 干预后样本门槛 3
    assert "< 3" in pacing or "min_samples" in pacing
    assert "<3 个样本" in doc or "3 个样本" in doc or "≥3 次" in doc

    # 5) 连续成功 2 次清零
    assert "ok_streak" in pacing and ">= max(1, int(need or 2))" in pacing
    assert "连续成功 2 次" in doc

def test_channel_session_statuses_documented():
    """CHANNEL_SESSION 的状态表必须覆盖 `channelAuthView` 的 labels 全部键。

    实测踩过：文档只列了 8 个后端状态，漏掉 read_error / loading / demo
    三个前端派生状态——用户看到「状态读取失败」时在文档里查不到含义。
    """
    doc_path = ROOT / "docs" / "CHANNEL_SESSION.md"
    if not doc_path.exists():
        pytest.skip("CHANNEL_SESSION 不存在")
    doc = doc_path.read_text(encoding="utf-8", errors="replace")

    i = WEBUI.find("const labels={")
    assert i > 0, "未找到 channelAuthView 的 labels"
    j = WEBUI.find("};", i)
    seg = WEBUI[i:j if j > 0 else i + 1500]
    keys = set(re.findall(r"([a-z_]+):'", seg))
    assert len(keys) >= 8, "labels 解析到的状态过少（%d）" % len(keys)

    missing = sorted(k for k in keys if ("| %s |" % k) not in doc)
    assert not missing, "CHANNEL_SESSION 状态表缺少: %s" % missing

    # 文档还声称「前 8 个由后端产出；后 3 个前端派生」。这个划分也得对得上：
    # 若后端新增/删除状态而文档仍写 8/3，读者会按错的来源去查代码。
    prod = WEBUI.find('status = "saving" if saving else "active"')
    assert prod > 0, "未找到 /api/login-state 的 status 产生处，本门禁失去锚点"
    prod_seg = WEBUI[prod:prod + 700]
    backend = set(re.findall(r'status = "([a-z_]+)"', prod_seg))
    backend |= set(re.findall(r'\? "([a-z_]+)"', prod_seg))
    backend |= set(re.findall(r'else "([a-z_]+)"', prod_seg))
    assert len(backend) >= 6, "后端 status 只解析出 %d 个，疑似结构变更" % len(backend)
    derived = keys - backend
    m = re.search(r"前 (\d+) 个由后端产出；后 (\d+) 个", doc)
    assert m, "CHANNEL_SESSION 未说明后端/前端派生各几个状态"
    assert int(m.group(1)) == len(backend), (
        "文档说后端产出 %s 个，代码实际 %d 个：%s"
        % (m.group(1), len(backend), sorted(backend)))
    assert int(m.group(2)) == len(derived), (
        "文档说前端派生 %s 个，代码实际 %d 个：%s"
        % (m.group(2), len(derived), sorted(derived)))

def test_intl_design_core_contract_matches_code():
    """INTL_DESIGN §1.1/§1.2 的硬契约：scope 判定、价口径、时长公式、增量键。

    这些是国际行的语义基础；代码改了而文档没跟，会导致跨端口径分歧。
    """
    import importlib
    import sys as _sys
    doc_path = ROOT / "docs" / "INTL_DESIGN.md"
    if not doc_path.exists():
        pytest.skip("INTL_DESIGN 不存在")
    doc = doc_path.read_text(encoding="utf-8", errors="replace")

    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    intl = importlib.import_module("core.intl")
    citydata = importlib.import_module("core.citydata")
    flightnorm = (ROOT / "core" / "flightnorm.py").read_text(encoding="utf-8", errors="replace")

    # 1) scope 判定：HKG 属国际，PEK 属国内
    assert intl.is_intl_city("HKG") is True, "HKG 应判为国际"
    assert intl.is_intl_city("PEK") is False, "PEK 应判为国内"
    assert intl.is_intl_route("SHA", "PEK") is False, "国内航线不该判国际"
    assert intl.is_intl_route("SHA", "HKG") is True, "任一端口国际即整条国际"
    assert "is_intl_city" in doc and "is_intl_route" in doc

    # 2) MAINLAND_CODES = CITY 去掉「中国」前缀条目
    assert len(citydata.CITY) == 289, "CITY 城数已变（%d），文档写的 289 需复核" % len(citydata.CITY)
    assert len(intl.MAINLAND_CODES) < len(citydata.CITY), "MAINLAND 应少于 CITY"
    assert "289 城" in doc

    # 2b) 机场码补充层：城市字典是城市码口径，PKX 这类机场码要靠额外集合兜住。
    #     文档曾漏记这一层；漏记的后果是读者以为"字典够用"，改字典就会把机场码判成国际。
    extra = [n for n in dir(intl) if "AIRPORTS_EXTRA" in n]
    assert extra, "core.intl 里找不到机场码补充集合"
    sym = extra[0]
    assert ("`%s`" % sym) in doc, "INTL_DESIGN 未记录机场码补充层 %s" % sym
    assert intl.is_intl_city("PKX") is False, "PKX（大兴机场码）应判为国内"
    assert intl.is_intl_city("PVG") is False, "PVG 应判为国内"

    # 5) 往返（§2.6）落地状态：主链路与特价侧已接入，雷达未接入。
    #    文档曾整节标「二期统一设计」，读者会以为往返还没做。
    models = (ROOT / "core" / "models.py").read_text(encoding="utf-8", errors="replace")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    specials = (ROOT / "core" / "specials.py").read_text(encoding="utf-8", errors="replace")
    radar = (ROOT / "core" / "special_radar.py").read_text(encoding="utf-8", errors="replace")
    rt_landed = ("ret_date" in models and "ret_dates" in models
                 and "ret_dates" in main_src and "ret_price" in specials)
    if rt_landed:
        # 允许以引述形式出现（「本节原标『二期统一设计』」），禁止作为现状标题/结论
        for line in doc.splitlines():
            if "二期统一设计" not in line:
                continue
            assert any(k in line for k in ("原标", "曾标", "旧称", "过去")), (
                "往返已落地，INTL_DESIGN §2.6 仍把「二期统一设计」当作现状：%s"
                % line.strip()[:80])
        assert "已落地" in doc and "往返" in doc
    if "backDate" not in radar and "tripType" not in radar:
        assert "特价雷达" in doc and ("未接入" in doc or "未接" in doc), (
            "特价雷达仍未接入往返，文档需要如实写明")

    # 6) 同程国际明细：代码已有 H5 book1 通路（探针用），文档不能说"明细挂二期"
    tc = (ROOT / "crawlers" / "tongcheng.py").read_text(encoding="utf-8", errors="replace")
    if "INTL_H5_BOOK" in tc and "_intl_h5_url" in tc:
        assert "INTL_H5_BOOK" in doc or "tiflight/book1" in doc, (
            "同程已有 H5 国际明细通路，INTL_DESIGN §2.3 未记录")
        # 标题不得再把"列表明细"整体判为挂二期
        for line in doc.splitlines():
            if line.startswith("### 2.3") and "同程" in line:
                assert "列表明细挂二期" not in line, (
                    "§2.3 标题仍写「列表明细挂二期」，但 H5 明细通路已落地")

        # HANDOFF 渠道表必须同时交代两件事：定时采集用日历价、探针另有 H5 明细。
        # 实测踩过：只写「国际走低价日历窗」，读者会以为同程国际永远没有明细；
        # 而库里同程国际行确实全无航班号（日历价），所以也不能反过来吹成"有明细"。
        hoff = ROOT / "HANDOFF.md"
        if hoff.exists():
            for line in hoff.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.startswith("| tongcheng"):
                    continue
                assert "日历" in line, "HANDOFF 同程行没写定时采集走日历价"
                assert ("INTL_H5_BOOK" in line or "book1" in line), (
                    "HANDOFF 同程行没写探针的 H5 明细通路（§2.3 已记录）")

    # 7) 途牛国际：库里已有真实国际行时，"受理不出数/软墙"就是过期结论。
    #    实测（2026-10-27）：SHA→LHR 286 / BKK 277 / NRT 251 / SIN 205 行，
    #    全部带航班号，每轮批只落 1 行 —— 是"能出但极少"，不是"不出数"。
    import sqlite3
    db = ROOT / "data" / "prices.db"
    tuniu_intl = 0
    if db.exists():
        try:
            con = sqlite3.connect(str(db))
            tuniu_intl = con.execute(
                "select count(*) from flight_prices where platform='tuniu' "
                "and extra like '%\"intl\": 1%'").fetchone()[0]
            con.close()
        except Exception:
            tuniu_intl = 0
    if tuniu_intl > 0:
        for name in ("INTL_DESIGN.md", "CAPTCHA_SOLUTION.md"):
            p = ROOT / "docs" / name
            if not p.exists():
                continue
            body = p.read_text(encoding="utf-8", errors="replace")
            for line in body.splitlines():
                if "途牛" not in line:
                    continue
                if not re.search(r"(受理不出数|软墙)", line):
                    continue
                # 允许"推翻/旧结论/过期/不是软墙"这类更正语境
                if re.search(r"(推翻|旧结论|已过期|不是软墙|已不成立|复核)", line):
                    continue
                raise AssertionError(
                    "%s 仍把途牛国际写成「受理不出数/软墙」，但库里有 %d 行真实国际数据：%s"
                    % (name, tuniu_intl, line.strip()[:80]))

    # 8) 途牛国际的**形态判据**：「行数 ≈ 不同 fetched_at 数」= 每轮只落 1 行。
    #    这条比"有多少行"稳定得多——行数天天涨，但这个等式不变；哪天变成一轮多行，
    #    说明采集口径变了（needQueryMore 被改），文档的「能出但极少」就不再成立。
    if db.exists():
        try:
            con = sqlite3.connect(str(db))
            rows = con.execute(
                "select from_city||'-'||to_city, count(*), count(distinct fetched_at) "
                "from flight_prices where platform='tuniu' and extra like '%\"intl\": 1%' "
                "group by 1 having count(*) >= 20").fetchall()
            bad_no = con.execute(
                "select count(*) from flight_prices where platform='tuniu' "
                "and extra like '%\"intl\": 1%' and (flight_no is null or flight_no='')"
            ).fetchone()[0]
            con.close()
        except Exception:
            rows, bad_no = [], 0
        # 库里一条途牛国际行都没有时，第 8 条无对象可查——跳过，不判红。
        # 实测 2026-10-30：活动库 data/prices.db 的 tuniu 行为 0（本轮没跑
        # 途牛），而旧备份里仍有 1362 行；门禁若把「没数据」写成「聚合为空」，
        # 就会天天报一条与代码无关的红，掩盖真正的形态变化。
        if tuniu_intl == 0:
            pytest.skip("库里没有途牛国际行，形态判据无检查对象")
        assert rows, "库里有途牛国际行但按航线聚合为空，本门禁失去检查对象"
        # 实测四条航线**精确相等**（285/285、274/274、249/249、204/204）。
        # 容差只给 20%：>1.2× 就说明出现了"一轮落多行"（负控时注入 60 行同 fetched_at，
        # 204→264 = 1.29×，阈值若设 1.5 会漏掉，故收紧）。
        multi = [(r[0], r[1], r[2]) for r in rows if r[1] > r[2] * 1.2]
        assert not multi, (
            "途牛国际出现「一轮落多行」的航线（行数 > 1.2×不同 fetched_at）：%s —— "
            "若采集口径确实改了，需同步 INTL_DESIGN §2.4 的形态判据" % multi)
        assert bad_no == 0, (
            "途牛国际国际行有 %d 条缺 flight_no——INTL_DESIGN 的「行均带航班号」不再成立"
            % bad_no)

        # 8b) 字段形态：HANDOFF 渠道表说「明细 100 条：直飞 5 / 中转 95」，
        #     判转机必须看 transCity —— extra 元素里**没有 transfer 键**。
        #     我实测时先按 transfer 判，结果 200 行全算成直飞（假结论）；
        #     按 transCity 才对。这条钉住「文档点明的判据字段确实存在」。
        try:
            con = sqlite3.connect(str(db))
            row = con.execute(
                "select extra from flight_prices where platform='tuniu' "
                "and from_city='SHA' and to_city='LHR' limit 1").fetchone()
            con.close()
        except Exception:
            row = None
        assert row, "库里有 SHA-LHR 途牛国际行却取不到 extra，本门禁失去锚点"
        import json
        elems = json.loads(row[0])
        assert isinstance(elems, list) and elems, (
            "途牛 extra 不是非空数组（与文档「每行是元素数组」不符）")
        assert "transCity" in elems[0], (
            "途牛 extra 元素缺 transCity —— 文档说按它判直飞/中转")
        assert "transfer" not in elems[0], (
            "途牛 extra 出现了 transfer 键，文档「没有 transfer 键、按它判会全判直飞」需复核")

    # 3) 时长公式：国际档必须减时区差
    assert "tz_arr - tz_dep" in flightnorm.replace("tz_arr − tz_dep", "tz_arr - tz_dep") \
        or "- (tz_arr - tz_dep)" in flightnorm, "国际时长公式未减时区差"
    assert "tz_arr − tz_dep" in doc or "tz_arr - tz_dep" in doc

    # 4) 四个增量键在代码里被写
    for key in ("intl", "tz_dep", "tz_arr", "arrDate"):
        assert '"%s"' % key in doc or "`%s`" % key in doc, "文档未记录增量键 %s" % key

def test_playbook_referenced_guards_exist():
    """文档里「守卫 `test_xxx`」点名的用例必须真的存在于 tests/。

    读者据此核对「这条约束有没有门禁保护」；名字失联会让人误判已被保护
    （或反过来，以为没保护而重复写一个）。
    """
    playbook_path = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    if not playbook_path.exists():
        pytest.skip("PLAYBOOK 不存在")
    doc = playbook_path.read_text(encoding="utf-8", errors="replace")
    names = sorted(set(re.findall(r"守卫\s*`(test_[a-z0-9_]+)`", doc)))
    assert names, "文档未引用任何守卫"

    tests_dir = ROOT / "tests"
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in tests_dir.glob("test_*.py"))
    missing = [n for n in names if ("def %s(" % n) not in blob]
    assert not missing, "文档引用但 tests/ 中不存在的守卫: %s" % missing

def test_asset_ledger_counts_match_code():
    """ASSET_LEDGER 的资源数量（渠道品牌 / 航司图标 / 机型族）必须与 webui.py 一致。

    这份清单是「官方图标随包内嵌」的对外承诺；数量漂移意味着清单漏记新增资源
    （或记了已删资源），读者按清单核对会得到错误结论。
    """
    doc_path = ROOT / "docs" / "ASSET_LEDGER.md"
    if not doc_path.exists():
        pytest.skip("ASSET_LEDGER 不存在")
    doc = doc_path.read_text(encoding="utf-8", errors="replace")

    def _block(start_marker):
        i = WEBUI.find(start_marker)
        assert i > 0, "未找到 %s" % start_marker
        j = WEBUI.find("};", i)
        return WEBUI[i:j if j > 0 else i + 2_000_000]

    # 渠道品牌图标
    brands = set(re.findall(r'"([a-z]+)"\s*:\s*"data:image', _block("const SRX_BRAND_IMG={")))
    assert len(brands) == 5, "品牌图标数已变：%d" % len(brands)
    assert "渠道图标（5/5）" in doc, "ASSET_LEDGER 未写「渠道图标（5/5）」"

    # 航司图标
    airlines = set(re.findall(r'"([A-Z0-9]{2})"\s*:\s*"data:image', _block("SRX_AIR_IMG={")))
    assert len(airlines) >= 50, "航司图标数异常：%d" % len(airlines)
    assert "航司图标（%d 个" % len(airlines) in doc, \
        "ASSET_LEDGER 的航司图标数（%d）与文档不符" % len(airlines)

    # 机型族
    lines = WEBUI.splitlines()
    st = next((i for i, l in enumerate(lines)
               if l.startswith("const SRX_PLANE_MODEL={")), None)
    assert st is not None, "未找到 SRX_PLANE_MODEL"
    models = 0
    for l in lines[st + 1:]:
        if l.startswith("}"):
            break
        if re.match(r"\s+\w+\s*:\s*\{", l):
            models += 1
    assert models >= 10, "机型条目异常：%d" % models
    assert "机型资源（%d 个机族）" % models in doc, \
        "ASSET_LEDGER 的机型数（%d）与文档不符" % models

    # README / README_EN 里也写死了「87 家航司」，那边没有门禁——一并钉住。
    for name in ("README.md", "README_EN.md"):
        p = ROOT / name
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(\d+)\s*(?:家航司|airlines)", body):
            assert int(m.group(1)) == len(airlines), (
                "%s 写 %s 家航司，代码 SRX_AIR_IMG 有 %d 个"
                % (name, m.group(1), len(airlines)))

def test_captcha_doc_endpoints_exist():
    """CAPTCHA_SOLUTION 里写的 /api/... 端点必须在 webui.py 里真实存在。

    实测踩过：文档写 `/api/challenge/tickets` 与 `_State.challenge_tickets`，
    两者全不存在（真实是 `_probe_challenge_ticket()` 挂在探针任务上）——
    按文档去调接口会 404，去翻字段会扑空。
    """
    doc_path = ROOT / "docs" / "CAPTCHA_SOLUTION.md"
    if not doc_path.exists():
        pytest.skip("CAPTCHA 文档不存在")
    doc = doc_path.read_text(encoding="utf-8", errors="replace")
    # 先剥掉外链（如 playwright.dev/.../api/class-browsercontext），只留本项目路由
    stripped = re.sub(r"<https?://[^>]+>", "", doc)
    stripped = re.sub(r"https?://\S+", "", stripped)
    routes = sorted(set(re.findall(r"(?<![\w./])(/api/[a-z0-9/_-]+)", stripped)))
    assert routes, "文档未提到任何 API 路由"
    missing = [r for r in routes if r not in WEBUI]
    assert not missing, "文档提到但 webui.py 中不存在的路由: %s" % missing

def test_release_process_claims_match_checker():
    """RELEASE_PROCESS 说「跑 release_align_check 直到 PASS」，那检查器必须还在查关键项。

    防的是：有人为让检查变绿而删掉检查项，文档仍宣称「已对齐」——
    比从未检查更危险（假安全）。
    """
    checker = (ROOT / "docs" / "release_align_check.py")
    doc = (ROOT / "docs" / "RELEASE_PROCESS.md")
    if not checker.exists() or not doc.exists():
        pytest.skip("发布对齐脚本或流程文档不存在")
    src = checker.read_text(encoding="utf-8", errors="replace")
    text = doc.read_text(encoding="utf-8", errors="replace")

    # 文档承诺会校验的对象 → 检查器里必须真的有为它设的检查
    required = {
        "canonical intro": "canonical intro",
        "version badge": "version badge",
        "round jargon": "round jargon",
        "release notes": "release notes",
        "pytest count": "pytest count",
        "uitest count": "uitest count",
        "screenshot": "screenshot",
        "site build stamp": "site build stamp",
        "SHA256SUMS": "SHA256SUMS",
        "deployment": "deployment",
        "tag": 'tag v1.0',
        "CI": "CI green",
        "live 8765": "live 8765",
    }
    missing = [label for label, needle in required.items() if needle not in src]
    assert not missing, "release_align_check 缺少文档承诺的检查: %s" % missing

    # 文档必须说明「跑到 PASS」这一步存在
    assert "release_align_check" in text
    assert "PASS" in text

def test_lessons_referenced_identifiers_exist():
    """LESSONS 判例里以反引号点名的项目标识符，必须仍能在源码中定位。

    判例是后来的决策依据；若它指向一个已被删除/改名的函数，
    读者会照着判例去改一段不存在的代码。只查强特征名（_snake / ALL_CAPS），
    排除第三方符号与文档自造术语。
    """
    lessons = ROOT / "docs" / "LESSONS.md"
    if not lessons.exists():
        pytest.skip("LESSONS 不存在")
    doc = lessons.read_text(encoding="utf-8", errors="replace")

    raw = set(re.findall(r"`(_[a-z][a-z0-9_]{4,}|[A-Z][A-Z0-9_]{4,})`", doc))
    # 第三方/通用符号与文档自造术语
    EXCLUDE = {
        "ERR_CONNECTION_REFUSED", "FAIL_SYS_TOKEN_EMPTY", "GIT_SSH_COMMAND",
        "MAINT", "_scratch", "_token",   # _scratch/_token 是通用词
    }
    candidates = sorted(raw - EXCLUDE)
    assert len(candidates) >= 8, "解析到的标识符过少（%d）" % len(candidates)

    haystack = []
    for rel in ("main.py", "report.py", "webui.py", "wizard.py"):
        p = ROOT / rel
        if p.exists():
            haystack.append(p.read_text(encoding="utf-8", errors="replace"))
    for sub in ("core", "crawlers"):
        d = ROOT / sub
        if d.is_dir():
            for f in d.glob("*.py"):
                haystack.append(f.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(haystack)

    missing = [c for c in candidates if c not in blob]
    assert not missing, "LESSONS 点名但源码中找不到的标识符: %s" % missing

def test_all_docs_api_routes_exist():
    """docs/ 下所有文档提到的 `/api/...` 路由都必须在 webui.py 里真实存在。

    比单文件版更宽：设计文档（superpowers/specs 等）同样会写「调 /api/xxx」，
    路由被改名/删除后读者按文档调接口会 404。外链（playwright.dev 等）先剥掉。
    """
    docs_dir = ROOT / "docs"
    if not docs_dir.is_dir():
        pytest.skip("docs 目录不存在")
    offenders = {}
    # 根目录的 README/README_EN/HANDOFF 也被读者按图索骥调接口，
    # 早先只扫 docs/ 会漏掉它们。
    md_files = list(docs_dir.rglob("*.md")) + [ROOT / n for n in
                                              ("README.md", "README_EN.md", "HANDOFF.md")]
    total_routes = 0
    for p in md_files:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        stripped = re.sub(r"<https?://[^>]+>", "", text)
        stripped = re.sub(r"https?://\S+", "", stripped)
        routes = set(re.findall(r"(?<![\w./])(/api/[a-z0-9/_-]+)", stripped))
        total_routes += len(routes)
        # 文档明确标注「未按此名实现／未落地」的段落允许保留提案路径
        allowed = set()
        for marker in ("未按此名实现", "均未按此名实现", "未落地"):
            idx = stripped.find(marker)
            while idx >= 0:
                seg = stripped[max(0, idx - 600):idx + 200]
                allowed |= set(re.findall(r"(/api/[a-z0-9/_-]+)", seg))
                idx = stripped.find(marker, idx + 1)
        missing = sorted(r for r in routes
                         if r not in WEBUI and r not in allowed)
        if missing:
            offenders[str(p.relative_to(ROOT))] = missing
    # 下限：文档里确有大量 /api/ 路由引用（实测 100+）。0 说明正则或外链剥离逻辑坏了。
    assert total_routes >= 5, (
        "文档里只解析出 %d 个 /api/ 路由引用，本门禁疑似失去检查对象" % total_routes)
    assert not offenders, "文档提到但 webui.py 中不存在的路由: %s" % offenders

def test_handoff_status_section_has_no_hardcoded_pid():
    """HANDOFF「当前状态」段不得写死进程 PID——重启即失效。

    实测踩过：正文写「PID 169944」，而当时 `.monitor.pid` 是 95172、
    netstat 里实际监听的是 189700，三个值互不相同。
    正确做法是给出获取方式（netstat / .monitor.pid 及其差异说明）。
    """
    p = ROOT / "HANDOFF.md"
    if not p.exists():
        pytest.skip("HANDOFF 不存在")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("**当前状态"))
    except StopIteration:
        pytest.skip("HANDOFF 无「当前状态」段")
    # 段落到下一个空行后的标题/表格为止
    end = start + 1
    while end < len(lines) and not lines[end].startswith("| 项 |"):
        end += 1
    seg = "\n".join(lines[start:end])
    assert not re.search(r"PID\s*\**\s*\d{3,}", seg) and not re.search(r"PID \*\*\d{3,}", seg), (
        "HANDOFF 当前状态段写死了 PID（重启即失效）：请改为给出获取方式")
    assert "netstat" in seg, "当前状态段应给出取 PID 的方式（netstat）"


def test_uncommitted_rounds_note_is_consistent():
    """SPEC 与 HANDOFF 对「哪些轮次尚未提交」的说法必须一致。

    实测踩过：HEAD 停在 r417，但工作区已有 r418 起的未提交代码；
    SPEC 正文引用了这些轮次，而 HANDOFF 头部只写到 r417——
    同一仓库两处对"当前做到哪"说法不同，读者无法判断哪些是已发布行为。

    判据用「r418 起」而非写死区间端点：并行会话持续推进（已见 r421→r423→r430），
    写死端点的门禁会因文档换了表述而静默 skip，反而失去守护作用。
    """
    spec = ROOT / "docs" / "EXECUTION_SPEC_LATEST.md"
    handoff = ROOT / "HANDOFF.md"
    if not spec.exists() or not handoff.exists():
        pytest.skip("文档不存在")
    s = spec.read_text(encoding="utf-8", errors="replace")
    h = handoff.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"r418\s*起", s), "SPEC 未声明「r418 起的新轮次尚未提交」"
    assert re.search(r"r418\s*起", h), (
        "SPEC 已声明 r418 起未提交，HANDOFF 头部却没有同步说明")
    assert "尚未提交" in h or "只在工作区" in h, (
        "HANDOFF 未说明这些轮次尚未提交")


def test_handoff_header_date_not_behind_body():
    """HANDOFF 头部「最后更新」日期不得早于正文里出现的最新日期。

    实测踩过：头部写 `最后更新：2026-10-27`，正文同一文件里却写
    「截至 2026-10-28 02:30 到 r430」——读者看头部会以为这是昨天的交割，
    实际内容已更新到今天。头部日期是"这份文档有多新"的唯一信号，落后即误导。
    """
    handoff = ROOT / "HANDOFF.md"
    if not handoff.exists():
        pytest.skip("HANDOFF.md 不在版本库（gitignore），跳过")
    lines = handoff.read_text(encoding="utf-8", errors="replace").splitlines()
    head = next((l for l in lines[:12] if "最后更新" in l), None)
    assert head is not None, "HANDOFF 头部缺少「最后更新」行，本门禁失去锚点"
    m = re.search(r"(20\d\d-\d\d-\d\d)", head)
    assert m, "「最后更新」未写日期：" + head.strip()[:80]
    head_date = m.group(1)
    body = "\n".join(lines)
    # 只取「文档时效」语境的日期：截至/实测/复核/更新。
    # 不能扫所有日期——HANDOFF 里大量 `SHA→HAK 2027-01-29` 是**航班日期**，
    # 拿它当"文档最新日期"会要求头部写到 2027 年（实测踩过）。
    dates = re.findall(r"(?:截至|实测|复核|更新[：:]?)\s*(20\d\d-\d\d-\d\d)", body)
    assert dates, "HANDOFF 正文没有可供判断时效的日期（截至/实测/复核/更新）"
    newest = max(dates)
    assert head_date >= newest, (
        "HANDOFF 头部「最后更新：%s」早于正文最新时效日期 %s——头部需同步"
        % (head_date, newest))


def test_worktree_snapshot_has_timestamp():
    """SPEC 里写的"未提交项数量"必须带时间戳，且不能久到失效。

    实测踩过：正文长期写「2026-10-27 13:59 实测 49 项未提交」，
    而实际已是 68 项——这类数字一天内就会翻倍，读者会据此误判工作区干净程度。
    又一次踩过：正文改写成「70 项变更」后，本门禁只认「项未提交」，
    正则 0 命中——"没有找到要检查的东西"被当成了绿灯。
    """
    spec = (ROOT / "docs" / "EXECUTION_SPEC_LATEST.md")
    if not spec.exists():
        pytest.skip("SPEC 不存在")
    text = spec.read_text(encoding="utf-8", errors="replace")
    matched = 0
    for line in text.splitlines():
        m = re.search(r"(\d+)\s*项(?:未提交|变更)", line)
        if not m:
            continue
        matched += 1
        assert re.search(r"20\d\d-\d\d-\d\d", line), (
            "未提交项数量没有时间戳，无从判断时效：" + line.strip()[:80])
    assert matched, (
        "SPEC 未声明工作区未提交项数量（「N 项变更/未提交」）——"
        "本门禁失去锚点，需人工确认该节是否被删/改写")


def test_snapshot_untracked_list_matches_disk():
    """SPEC 快照里点名的「未跟踪项」必须真的存在且真的未入库。

    实测踩过：快照列了 7 个未跟踪文件，实际有 11 个——
    漏掉的 `docs/MOBILE_MUMU_ACCEPTANCE.md` 等已被 LESSONS/HANDOFF 引用，
    读者按清单找不全；反向错误（列了已提交或不存在的路径）同样会误导。
    只校验「点名即真实」，不校验覆盖面：并行会话随时新增文件，
    要求清单穷举会让门禁变成噪声源。

    另一种合法形态是「未跟踪 0 项」——并行会话把成果提交后清单必然消失。
    这种形态下没有点名可校验，且该行本身写明「以 `git status` 现场为准、
    与本文不符按现场重算」，所以这里不比对现场数量：并行会话每隔几分钟就会
    新建一个临时测试文件，比对现场会让门禁变成噪声源（正是上面那条要避免的）。
    """
    import subprocess
    spec = ROOT / "docs" / "EXECUTION_SPEC_LATEST.md"
    text = spec.read_text(encoding="utf-8", errors="replace")
    line = next((l for l in text.splitlines() if "未跟踪项含" in l), None)
    if line is None:
        assert re.search(r"未跟踪\s*[0０]\s*项", text), (
            "SPEC 快照既未列出未跟踪项、也未声明「未跟踪 0 项」，"
            "本门禁失去锚点")
        return
    # 只取「未跟踪项含 …」到句号为止——同一行后面还会提到 `webui.py`
    # （并行会话在改的**已入库**文件），整行扫描会把它们误判成未跟踪项。
    seg = line.split("未跟踪项含", 1)[1].split("。", 1)[0]
    listed = re.findall(r"`([\w./-]+\.(?:py|md|yaml|json|html|txt|patch))`", seg)
    assert len(listed) >= 3, "只解析出 %d 个未跟踪项，疑似格式变更" % len(listed)
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split())
    bad = []
    for rel in listed:
        if rel.endswith(".patch"):
            continue
        if not (ROOT / rel).exists():
            bad.append("%s（磁盘上不存在）" % rel)
        elif rel in tracked:
            bad.append("%s（已入库，不应再算未跟踪）" % rel)
    assert not bad, "SPEC 快照的未跟踪清单与实际不符：%s" % bad


def test_docs_head_anchor_matches_git():
    """SPEC 与 HANDOFF 里写的 HEAD 短哈希必须等于当前 git HEAD。

    实测：代码几轮内从 r404 推进到 r411，文档锚点却一直停在旧的——
    读者按文档的 HEAD 去对账会找不到对应代码。
    """
    import subprocess
    spec_path = ROOT / "docs" / "EXECUTION_SPEC_LATEST.md"
    handoff_path = ROOT / "HANDOFF.md"
    try:
        head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"],
                              cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        pytest.skip("非 git 环境")
    assert head, "读不到 HEAD"

    for p, label in ((spec_path, "SPEC"), (handoff_path, "HANDOFF")):
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "仓库 HEAD" not in text:
            continue
        # 两种合格写法：
        #  a) 写死当前 HEAD —— 必须与 git 一致（原有判据，读者可直接对账）；
        #  b) 显式声明「以 git rev-parse --short HEAD 为准，随提交同步」——
        #     并行会话每提交一次 hash 就变，写死值必然过期，但读者按命令
        #     仍能拿到正确 HEAD，意图（文档不指向错代码）同样成立。
        if head in text:
            continue
        assert re.search(
            r"仓库 HEAD[^\n]{0,200}git rev-parse --short HEAD", text), (
            "%s 的 HEAD 锚点既不是当前 HEAD（%s），也没声明以 "
            "`git rev-parse --short HEAD` 为准——轮次推进后需同步" % (label, head))

    # 顶部「最后更新：rNNN」也必须跟上：曾长期停在 r411，而同文件的
    # 「仓库 HEAD」行已写 r417 —— 同一份文档里两个轮次锚点互相矛盾。
    try:
        rounds = subprocess.run(
            ["git", "log", "-1", "--format=%s"], cwd=ROOT,
            capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace").stdout
    except Exception:
        rounds = ""
    m_head = re.search(r"\(r(\d{2,4})\)|（r(\d{2,4})）", rounds)
    if handoff_path.exists() and m_head:
        cur_round = int(m_head.group(1) or m_head.group(2))
        text = handoff_path.read_text(encoding="utf-8", errors="replace")
        m_upd = re.search(r"最后更新[^\n]{0,40}?r(\d{2,4})", text)
        if m_upd:
            stale = int(m_upd.group(1))
            assert stale >= cur_round - 2, (
                "HANDOFF 顶部「最后更新」停在 r%d，而 HEAD 已是 r%d"
                % (stale, cur_round))

def test_historical_test_counts_are_marked():
    """历史快照文档里的**pytest 计数**必须就近标注「历史/当轮/快照/当时的」。

    范围刻意收窄（实测教训）：
    - 只查「N passed」（pytest 口径）；「N 项/断言」在设计文档里多为 mock 门禁数
      或 uitest 断言数（658 就是当前值），一并纳入会大面积误报。
    - 只查三份历史快照类文档；设计文档文首已有时效边界，不再逐行要求。
    阈值 3900：当前量级 4000+，低于它的 pytest 计数一定是旧快照。
    """
    targets = [
        ROOT / "docs" / "ACCEPTANCE_MATRIX.md",
        ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md",
        ROOT / "docs" / "CAPTCHA_SOLUTION.md",
    ]
    MARKERS = ("历史", "当轮", "快照", "当时的")
    bad = []
    for p in targets:
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in re.finditer(r"(\d{3,4})\s*passed", line):
                if int(m.group(1)) >= 3900:
                    continue
                # 只看计数附近的上下文，不看整行——同一行别处的「历史」等词
                # 会造成假绿（实测：『与历史 round 词面』把未标注行放行了）
                near = line[max(0, m.start() - 30):m.end() + 90]
                if not any(k in near for k in MARKERS):
                    bad.append("%s:%d %s" % (p.name, i, m.group(0)))
    assert not bad, "历史 pytest 计数未标注时效: " + "; ".join(bad)

def test_doc_gates_do_not_skip_on_missing_anchor():
    """文档契约门禁不得在"目标文档存在、但关键锚点找不到"时 skip。

    实测踩过：`test_uncommitted_rounds_note_is_consistent` 写死「r418–r421」，
    文档改口径后它直接 skip——门禁还在、绿灯也还亮，但守护已经没了。
    同理 PLAYBOOK 删掉「代码默认」块、HANDOFF 删掉收集块说明时都会 skip。

    规则：源文件缺失可以 skip（无从校验）；**文档存在但锚点缺失必须失败**。
    """
    BLOCKED = ("未列出", "未提", "缺少 §", "未找到", "解析不", "未标注", "未声明")
    src = (ROOT / "tests" / "test_docs_code_contract.py").read_text(
        encoding="utf-8", errors="replace")
    offenders = []
    cur = ""
    for i, line in enumerate(src.splitlines(), 1):
        m = re.match(r"def (test_\w+)\(", line)
        if m:
            cur = m.group(1)
        if "pytest.skip(" not in line:
            continue
        if cur == "test_doc_gates_do_not_skip_on_missing_anchor":
            continue
        if any(k in line for k in BLOCKED):
            offenders.append("%s:%d %s" % (cur, i, line.strip()[:70]))
    assert not offenders, (
        "这些门禁在「锚点缺失」时会 skip（假绿），应改为 assert：\n"
        + "\n".join(offenders))


def test_tracked_targets_referenced_by_gates_exist():
    """门禁源码引用到的**已入库**文件必须真实在磁盘上。

    实测（2026-10-28 变异审计）：本文件里有 34 处 `if not X.exists(): skip`。
    对未入库文件（HANDOFF、日志）跳过是对的；但 `X` 若是已入库文档
    （SPEC/PLAYBOOK/README/CONTRIBUTING…），删掉它不会让任何门禁变红——
    十几条守护一起静默消失，CI 依旧全绿。这是比"锚点缺失"更彻底的假绿：
    锚点至少还要文档存在才谈得上。
    """
    import subprocess
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split())
    src = (ROOT / "tests" / "test_docs_code_contract.py").read_text(
        encoding="utf-8", errors="replace")
    # 只认带路径语义后缀的字面量：`name.py` / `docs/X.md`，排除主机名、URL
    SUFFIX = (".md", ".py", ".yaml", ".yml", ".json", ".txt", ".html")
    # 两种写法都要还原成仓库相对路径：`ROOT / "docs" / "X.md"` 与裸 `"docs/X.md"`。
    # 只认裸字面量会漏掉前者——实测负控时 `ROOT / "docs" / "LESSONS.md"` 未被覆盖。
    cands = set()
    for m in re.finditer(r"ROOT\s*/\s*((?:\"[^\"\n]*\"\s*/\s*)*\"[^\"\n]*\")", src):
        cands.add("/".join(re.findall(r"\"([^\"\n]*)\"", m.group(1))))
    cands.update(re.findall(r"\"([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)\"", src))

    missing = []
    for lit in sorted(cands):
        if not lit.endswith(SUFFIX) or lit.startswith(("http", "/")):
            continue
        if lit not in tracked:
            continue
        if not (ROOT / lit).exists():
            missing.append(lit)
    assert not missing, (
        "门禁引用的已入库文件已不存在（对应守卫已静默失效）：%s" % missing)


def test_spec_gate_index_matches_actual_tests():
    """SPEC §8.4 的门禁清单必须与实际存在的测试函数一致。

    这张清单本身就是文档——若它列了不存在的门禁（或漏了新增的），
    读者会误判"这个约束有保护"。
    """
    spec_path = ROOT / "docs" / "EXECUTION_SPEC_LATEST.md"
    if not spec_path.exists():
        pytest.skip("SPEC 不存在")
    spec = spec_path.read_text(encoding="utf-8", errors="replace")
    i = spec.find("### 8.4 文档契约门禁")
    assert i > 0, "SPEC 缺少 §8.4 门禁清单"
    j = spec.find("\n## ", i)
    section = spec[i:j if j > 0 else len(spec)]

    listed = set(re.findall(r"`(test_[^`\s()]+)`", section))
    # 只认函数名：排除 `tests/test_core_units.py` 这类路径。
    # 注意不能简单地"含点就排除"——门禁说明里常写 `webui.py::_startup_vals`，
    # 那种串里函数名后面还有 `::`，已被 `[^`\s()]+` 匹配到，需按"是否以 .py 结尾"判断。
    listed = {x for x in listed
              if not x.endswith(".py") and "/" not in x and "::" not in x}
    assert len(listed) >= 20, "清单解析到的门禁过少（%d）" % len(listed)
    # 元门禁自身在清单里出现是正常的（它是自述），比较时两边都排除
    listed.discard("test_spec_gate_index_matches_actual_tests")

    # 函数名允许中文（如 test_计划文档checkbox状态须与实际一致）。
    # 实测踩过：旧正则 `test_[a-z0-9_]+` 不匹配中文名，于是该门禁在
    # 「清单」和「实际」两边都被漏掉——两边同时缺席，比对仍然相等，永远绿。
    # 用 `[\w\u4e00-\u9fff]+` 且排除点号，否则会把 `tests/test_core_units.py` 当函数名。
    actual = set(re.findall(r"^def (test_[\w\u4e00-\u9fff]+)\(",
                            (ROOT / "tests" / "test_docs_code_contract.py")
                            .read_text(encoding="utf-8"), re.M))
    # 本测试自身不必列在清单里（它是元门禁）
    actual.discard("test_spec_gate_index_matches_actual_tests")

    missing = sorted(listed - actual)
    assert not missing, "SPEC §8.4 列了不存在的门禁: %s" % missing

    unlisted = sorted(actual - listed)
    assert not unlisted, "有门禁未写进 SPEC §8.4 清单: %s" % unlisted

def test_doc_cross_references_exist():
    """文档之间以 `docs/...md` 形式互相引用时，被引用的文件必须存在。

    实测踩过：LESSONS 里写了 `docs/MOBILE_CHANNEL_OPTIONS.md` 等引用，
    若那份文件被改名/删除，读者点过去就是空的——而没有任何测试会红。
    """
    docs_dir = ROOT / "docs"
    if not docs_dir.is_dir():
        pytest.skip("docs 目录不存在")
    offenders = {}
    total_refs = 0
    for p in docs_dir.rglob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        # 只取反引号里的 docs/...md 引用（排除 URL 与纯文本提及）
        refs = set(re.findall(r"`(docs/[A-Za-z0-9_./-]+\.md)`", text))
        total_refs += len(refs)
        missing = sorted(r for r in refs if not (ROOT / r).exists())
        if missing:
            offenders[str(p.relative_to(ROOT))] = missing
    # 下限：docs 之间确有大量互引（实测 39 处）。0 命中说明引用格式变了
    # （如改用 markdown 链接 [x](docs/y.md)）——那正是本门禁该跟着改的时候。
    assert total_refs >= 5, (
        "docs/*.md 之间只解析出 %d 处互引，本门禁疑似失去检查对象" % total_refs)
    assert not offenders, "文档互相引用了不存在的文件: %s" % offenders


def test_doc_code_path_refs_exist_or_marked():
    """文档以反引号点名的 `docs/ core/ crawlers/ tests/` 路径必须存在，或就近标注未实现/不入库。

    实测踩过三类：
    1. CAPTCHA_SOLUTION 的「代码落点」表点名 `core/challenges.py`、`tests/test_challenge_classifier.py`
       ——全仓不存在，是按表 import 会失败的地方；
    2. 「存证 `docs/evidence/xxx.json`」——该目录从未入库，文件实际在 gitignore 的 `_scratch/` 下；
    3. 设计稿引用 `docs/evidence/...` 但它从未被创建。
    判定：路径不存在时，同一行或相邻 3 行内必须有「未实现/未创建/不存在/不入库/gitignore」之一。
    """
    PAT = re.compile(r"`((?:docs|core|crawlers|tests)/[A-Za-z0-9_./-]+\.(?:md|py|json))`")
    MARKERS = ("未实现", "未创建", "不存在", "不入库", "gitignore", "待建", "提案")
    offenders = []
    examined = 0
    for p in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("_scratch/"):
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            for ref in set(PAT.findall(line)):
                examined += 1
                if (ROOT / ref).exists():
                    continue
                # 标记必须在**同一行**或紧邻的上一行行尾。
                # 早先用 ±3 行窗口，表格上方的总提示句会把整张表一起放行（负控假绿）。
                same_line = any(m in line for m in MARKERS)
                prev_line = any(m in lines[i - 1] for m in MARKERS) if i else False
                if same_line or prev_line:
                    continue
                offenders.append("%s:%d %s" % (rel, i + 1, ref))
    # 下限：全仓文档里确有大量 `docs/...` 路径点名（实测 100+）。0 说明反引号写法变了。
    assert examined >= 5, (
        "文档里只解析出 %d 个 docs/core/crawlers/tests 路径引用，本门禁疑似失去检查对象"
        % examined)
    assert not offenders, (
        "文档点名了不存在的路径，且未标注未实现/不入库：\n" + "\n".join(sorted(set(offenders))))

def test_spec_test_count_bases_explained():
    """SPEC 里若同时出现带路径与不带路径的 pytest 命令，必须解释收集口径差异。

    实测：`pytest -q` 收 4205、`pytest tests/ -q` 收 4201、README 写 4079（已跟踪）。
    三个数都对，差在范围；文档不解释会让读者以为某个数字是错的。
    """
    spec = ROOT / "docs" / "EXECUTION_SPEC_LATEST.md"
    if not spec.exists():
        pytest.skip("SPEC 不存在")
    text = spec.read_text(encoding="utf-8", errors="replace")
    # 只要 SPEC 教人跑「不带路径」的 pytest，就必须解释收集范围——
    # 不带路径会连未入库测试一起收（4205），`tests/` 收 4201，README 的 4079 是已跟踪口径。
    if "pytest -q" not in text:
        pytest.skip("SPEC 未使用不带路径的 pytest 写法")
    assert "收集口径" in text, (
        "SPEC 教人跑 `pytest -q`（不带路径）却没解释收集口径差异")
    assert "跟踪" in text, "SPEC 未说明 README 的计数是已跟踪口径"


def test_readme_test_count_states_basis():
    """README 教人跑 `pytest tests/` 时给出的计数，必须说明它是"跟踪口径"。

    实测踩过：README 写「全量 4079 项」，而 `pytest tests/ --collect-only`
    实际收集 **4201** 项——差额是若干尚未入库的测试文件
    （如 `tests/test_docs_code_contract.py` 本身）。
    读者按"4079"核对会以为少跑了 122 个用例。
    """
    for name, hint in (("README.md", "跟踪口径"),
                       ("README_EN.md", "tracked")):
        p = ROOT / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "pytest tests/ -q" not in line:
                continue
            if not re.search(r"4\d{3}\s*(项|tests)", line):
                continue
            assert hint in line, (
                "%s:%d 给了测试计数却没说统计口径（应含「%s」）" % (name, i, hint))


def test_readme_retention_days_match_code():
    """README 说的「清理 N 天前明细」必须等于 `PriceStorage.RAW_RETAIN_DAYS`。

    实测踩过：代码 r392 已把保留期改成 8 天（注释明写「不再硬编码 14」），
    而 README 中英两版仍写 14 天——用户按 14 天规划存储会高估占用一倍。
    """
    storage = ROOT / "core" / "storage.py"
    if not storage.exists():
        pytest.skip("storage 不存在")
    m = re.search(r"RAW_RETAIN_DAYS\s*=\s*(\d+)",
                  storage.read_text(encoding="utf-8", errors="replace"))
    assert m, "未找到 RAW_RETAIN_DAYS"
    days = int(m.group(1))

    for name, pat in (("README.md", r"清理\s*(\d+)\s*天前明细"),
                      ("README_EN.md", r"auto-clean after\s*(\d+)\s*days")):
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        mm = re.search(pat, text)
        if not mm:
            continue   # 该行未提保留期，另行人工核对
        assert int(mm.group(1)) == days, (
            "%s 写 %s 天，代码 RAW_RETAIN_DAYS=%d" % (name, mm.group(1), days))


def test_readme_login_requirement_matches_code():
    """README 的登录要求结论必须与 `SESSION_REQUIREMENT` 一致。

    2026-10-27 起口径变为「全部渠道必须登录」，README 曾长期写
    「同程建议登录 / 飞猪国内匿名可取」，是明确的反向陈述。
    这里按代码的 required/suggested 分布决定 README 必须出现哪种说法。
    """
    import importlib
    import sys as _sys
    readme = ROOT / "README.md"
    if not readme.exists():
        pytest.skip("README 不存在")
    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    links = importlib.import_module("core.channel_links")
    req = getattr(links, "SESSION_REQUIREMENT", {})
    assert req, "SESSION_REQUIREMENT 为空"
    cn = readme.read_text(encoding="utf-8", errors="replace")

    all_required = all(v[0] == "required" for v in req.values())
    if all_required:
        assert "都必须登录" in cn or "全部渠道都必须登录" in cn, (
            "代码里五个渠道全部 required，README 必须明确「都必须登录」")
        # 不得再出现反向说法
        for stale in ("同程建议登录", "飞猪国内匿名可取", "途牛国际匿名"):
            assert stale not in cn, "README 仍有反向陈述：%s" % stale
    else:
        # 混合口径：至少要写清必须登录的渠道
        must = [k for k, v in req.items() if v[0] == "required"]
        assert "必须登录" in cn, "README 未提必须登录；实际 %s" % must

def _mumu_install_dir():
    """探测 MuMu 安装目录；探测不到返回 None（调用方跳过该子断言）。

    优先 TM_MUMU_DIR；否则按各盘符的常见安装位置猜一遍。测试里不得写死
    某一台机器的绝对路径——换机必假红，读者也会看到与项目无关的本机信息。
    """
    import os as _os
    cands = []
    env = (_os.environ.get("TM_MUMU_DIR") or "").strip()
    if env:
        cands.append(pathlib.Path(env))
    for drive in ("C:", "D:", "E:"):
        cands.append(pathlib.Path(drive + _os.sep) / "Program Files"
                     / "Netease" / "MuMu")
    for p in cands:
        try:
            if p.is_dir():
                return p
        except OSError:
            continue
    return None


def test_mobile_docs_sizes_match_reality():
    """移动端文档里的体积数字必须与磁盘实测一致。

    实测踩过两处：①「4 个 APK 约 448 MB」实际目录 768 MB 且智行样本已不在；
    ②「MuMu 3.6 GB」是安装器本体，装完实例后实测 7.1 GB。
    这类数字读者会直接拿去估算部署成本，错了就是误导。
    """
    import shutil
    runtime_doc = ROOT / "docs" / "MOBILE_RUNTIME_VERIFICATION.md"
    mumu_doc = ROOT / "docs" / "MOBILE_MUMU_ACCEPTANCE.md"

    # ① APK 目录：文档若提到该目录，就必须写明真实体量量级
    apk_dir = ROOT / "_scratch" / "mobile_paths" / "apk"
    if runtime_doc.exists() and apk_dir.is_dir():
        doc = runtime_doc.read_text(encoding="utf-8", errors="replace")
        total = sum(f.stat().st_size for f in apk_dir.rglob("*") if f.is_file())
        gb = total / (1024 ** 3)
        # 文档写的 GB 数必须落在实测 ±20% 内
        nums = [float(x) for x in re.findall(r"约 \*\*(\d+(?:\.\d+)?)\s*MB\*\*", doc)]
        nums += [float(x) * 1024 for x in re.findall(r"约 \*\*(\d+(?:\.\d+)?)\s*GB\*\*", doc)]
        if nums:
            claimed_mb = max(nums)
            assert abs(claimed_mb - total / 1024 ** 2) / (total / 1024 ** 2) < 0.2, (
                "APK 目录体量与文档不符：实测 %.0f MB，文档写 %.0f MB"
                % (total / 1024 ** 2, claimed_mb))

    # ② MuMu 安装目录：按环境变量/常见安装位置探测，找不到就跳过。
    #    不能把某一台机器的绝对路径写进测试——换机必假红，也泄露本机信息。
    mumu = _mumu_install_dir()
    if mumu_doc.exists() and mumu is not None:
        doc = mumu_doc.read_text(encoding="utf-8", errors="replace")
        total = sum(f.stat().st_size for f in mumu.rglob("*") if f.is_file())
        gb = total / (1024 ** 3)
        m = re.search(r"(\d+(?:\.\d+)?)\s*GB", doc[doc.find("实测"):] if "实测" in doc else doc)
        assert m, "MuMu 文档未写实测体积"
        claimed = float(m.group(1))
        assert abs(claimed - gb) / gb < 0.2, (
            "MuMu 体量与文档不符：实测 %.1f GB，文档写 %.1f GB" % (gb, claimed))

def test_mobile_runtime_status_claims_match_reality():
    """文档若声称「本机还没装 Android 运行时」，那 adb 就不能真连上设备。

    实测踩过：PATH_B_PLAN 写「本机还没装任何 Android 运行时」，
    而此时 MuMu 已装、`127.0.0.1:16384` 在监听——这句话会让后来的人
    以为要从头装环境，实际已经装好了。
    """
    import shutil
    import subprocess
    plan = ROOT / "docs" / "MOBILE_PATH_B_PLAN.md"
    if not plan.exists():
        pytest.skip("PATH_B_PLAN 不存在")
    doc = plan.read_text(encoding="utf-8", errors="replace")

    adb = shutil.which("adb")
    if not adb:
        # 项目内 adbutils 自带 adb
        cand = ROOT / "_scratch" / "spike_mobile"
        if not cand.is_dir():
            pytest.skip("无 adb 可用")
    try:
        from adbutils import adb as _adb
        devices = [d.serial for d in _adb.list()]
    except Exception:
        pytest.skip("adbutils 不可用")

    has_device = bool(devices)
    stale = "本机还没装任何 Android 运行时" in doc and "**当时**" not in doc
    if has_device and stale:
        raise AssertionError(
            "文档声称未装 Android 运行时，但 adb 已连上设备 %s——需更新" % devices)


def test_handoff_mobile_verdict_not_left_at_theory():
    """HANDOFF 的 App 抓包结论不得停留在"仅理论可行"而不提已实测跑通。

    实测踩过：结论行只写「理论可行…成本高…不作为主方案」，
    而另一份文档里 MuMu 已把美团/智行都跑通——同一个仓库两种结论。
    判据：HANDOFF 提到 App 抓包时，必须同时出现实测结论与"未接入爬虫"的边界。
    """
    handoff = ROOT / "HANDOFF.md"
    if not handoff.exists():
        pytest.skip("HANDOFF 不存在")
    text = handoff.read_text(encoding="utf-8", errors="replace")
    if "App 抓包" not in text:
        pytest.skip("HANDOFF 未讨论 App 抓包")
    assert "MOBILE_RUNTIME_VERIFICATION" in text, (
        "HANDOFF 谈 App 抓包却没指向实测记录文档")
    assert "仍未接入爬虫" in text or "不等于渠道已支持" in text, (
        "HANDOFF 未写清边界：运行时跑通 ≠ 渠道已支持")

def test_计划文档checkbox状态须与实际一致():
    """计划类文档若 0 个勾选但产物已存在，必须写明「落地状态」。

    实测踩过：batch1（52 个 `- [ ]`）与 batch2（32 个）都从未回填勾选，
    但产物文件与用例全在、全绿——读者会把「已完成」读成「未开工」。
    判据：0 个已勾 + 有产物引用的文件存在 → 必须出现「落地状态」字样。
    """
    plans = ROOT / "docs" / "superpowers" / "plans"
    if not plans.is_dir():
        pytest.skip("plans 目录不存在")
    bad = []
    for p in plans.glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        n_open = len(re.findall(r"^- \[ \]", text, re.M))
        n_done = len(re.findall(r"^- \[x\]", text, re.M))
        if n_open == 0 or n_done > 0:
            continue
        # 有产物引用（tests/ 或 docs/ 的 py/md）
        refs = set(re.findall(r"`((?:tests|core|crawlers|docs)/[A-Za-z0-9_.]+\.(?:py|md))`", text))
        existing = [r for r in refs if (ROOT / r).exists()]
        if existing and "落地状态" not in text:
            bad.append("%s（%d 个未勾，但 %d 个产物已存在）"
                       % (p.name, n_open, len(existing)))
    assert not bad, "计划文档未声明落地状态: " + "; ".join(bad)

def test_plan_declared_artifacts_exist():
    """计划文档「落地状态」段里点名的产物路径必须真实存在，缺失项必须被明确点名。

    实测：batch1 声称「实测产物（8/9 存在）」并列出唯一缺失项，batch2 声称「6/6 存在」——
    逐项核对均属实。这条防的是下次改完代码后，声明里的路径悄悄失效
    （读者会以为产物还在）。
    """
    plans = ROOT / "docs" / "superpowers" / "plans"
    if not plans.is_dir():
        pytest.skip("plans 目录不存在")
    offenders = []
    sections = 0
    for p in plans.glob("*.md"):
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        # 只在「落地状态」声明段内取路径
        idx = next((k for k, l in enumerate(lines) if "落地状态" in l), None)
        if idx is None:
            continue
        sections += 1
        block = "\n".join(lines[idx:idx + 20])
        refs = set(re.findall(r"`((?:tests|core|crawlers|docs)/[A-Za-z0-9_.]+\.(?:py|md))`", block))
        for ref in refs:
            if (ROOT / ref).exists():
                continue
            # 缺失项必须在该段里被明确标注为缺失/未创建
            if re.search(r"(缺失|未创建|不存在)[^\n]{0,40}%s" % re.escape(ref.split("/")[-1]), block):
                continue
            offenders.append("%s → %s" % (p.name, ref))
    # 下限：实测有两份计划带「落地状态」段。0 段说明标题被改写（如改成「完成情况」），
    # 门禁会一无所获却依旧绿。
    assert sections, "没有任何计划文档含「落地状态」段，本门禁失去检查对象"
    assert not offenders, (
        "计划文档声明了不存在的产物且未标注缺失：" + "\n".join(sorted(set(offenders))))


def test_readme_console_tabs_match_ui():
    """README 列出的主轴页签名必须与 `#montabs` 的实际按钮文案一致。

    实测踩过：README 写「关注航线走势 / 关注航班走势 / 关注航班明细」，
    而界面钮是「航线走势 / 航班走势 / 航班明细」——用户照 README 找页签会找不到。
    """
    readme = ROOT / "README.md"
    if not readme.exists():
        pytest.skip("README 不存在")
    i = WEBUI.find('id="montabs"')
    assert i > 0, "未找到 #montabs"
    j = WEBUI.find("</div>", i)
    seg = WEBUI[i:j if j > 0 else i + 2000]
    labels = [x.strip() for x in re.findall(r">([^<>\n]{2,10})<", seg) if x.strip()]
    assert len(labels) == 6, "montabs 解析到 %d 个页签：%s" % (len(labels), labels)

    doc = readme.read_text(encoding="utf-8", errors="replace")
    missing = [lab for lab in labels if lab not in doc]
    assert not missing, "README 未出现界面页签名：%s" % missing
    # 只在「页签列举」语境里禁旧名：`关注航班` 作为功能概念（关注对象）是合法的，
    # 不能一刀切禁词（实测误报：第 60 行的「关注航线/关注航班」是功能说明）。
    for line in doc.splitlines():
        if "子视图工作台" not in line and "页签" not in line:
            continue
        for stale in ("关注航线走势", "关注航班走势", "关注航班明细"):
            assert stale not in line, "页签列举仍用界面不存在的名字：%s" % line.strip()[:80]


def test_readme_shortcut_keys_match_ui():
    """README 数字快捷键表必须与 `keydown` 里的 `gotoMonTab` 映射一致。

    实测踩过：README 写「3/4/5/6/7 = 概览/走势/关注/明细/健康」，
    而代码是 3=概览 4=航线走势 5=航班明细 6=渠道健康 7=航班走势——
    按 5 想开关注台的人会落到明细页，且顺序全错。
    """
    keys = dict(re.findall(r"e\.key==='(\d)'\)gotoMonTab\('([a-z]+)'\)", WEBUI))
    assert len(keys) == 5, "解析到 %d 个数字快捷键：%s" % (len(keys), keys)

    i = WEBUI.find('id="montabs"')
    assert i > 0, "未找到 #montabs"
    seg = WEBUI[i:WEBUI.find("</div>", i)]
    zh = {}
    for tab, label in re.findall(r'data-t="([a-z]+)"[^>]*>(?:<svg.*?</svg>|<i.*?</i>)?([^<]*)', seg):
        label = label.strip()
        if label:
            zh[tab] = label
    assert len(zh) == 6, "montabs 解析到 %d 个页签：%s" % (len(zh), zh)

    expected_zh = [zh[keys[k]] for k in sorted(keys)]
    en_alias = {
        "overview": "Overview", "trend": "Route trend", "details": "Flight details",
        "health": "Channel health", "watch": "Flight trend",
    }
    expected_en = [en_alias[keys[k]] for k in sorted(keys)]

    def row_items(name):
        p = ROOT / name
        if not p.exists():
            pytest.skip("%s 不存在" % name)
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 4 and re.fullmatch(r"`\d`( / `\d`){4}", cells[1]):
                return re.findall(r"`(\d)`", cells[1]), cells[2]
        return None

    for name, expected in (("README.md", expected_zh), ("README_EN.md", expected_en)):
        got = row_items(name)
        assert got, "%s 里找不到数字快捷键表行" % name
        row_keys, row_text = got
        assert sorted(row_keys) == sorted(keys), "%s 快捷键键位变化：%s" % (name, row_keys)
        body = re.sub(r"^(直达\s*|Direct to\s*)", "", row_text)
        body = re.sub(r"\s*(子视图|sub-?views?)\s*$", "", body, flags=re.I)
        items = [x.strip() for x in body.split(" / ") if x.strip()]
        assert items == expected, "%s 快捷键页签名与界面不符：文档 %s ≠ 代码 %s" % (name, items, expected)


def test_config_partitions_documented_match_nav():
    """配置页左侧分区数/名必须与 `#cfgnav` 的 `.cnav` 实际项一致。

    实测踩过：README 写「渠道登录/用户与航线/航班监控/全局参数」四分区，
    而 `#cfgnav` 只有三项——「关注航班」是用户卡 D 区里的单实例面板
    （`#cfgWatch` 在 `#cfgWatchPark` 与用户卡之间搬运），不是左侧分区。
    读者照 README 找「航班监控」分区会找不到入口。
    """
    i = WEBUI.find('<aside class="cfgnav" id="cfgnav">')
    assert i > 0, "未找到 #cfgnav"
    j = WEBUI.find("</aside>", i)
    nav = WEBUI[i:j if j > 0 else i + 4000]
    nav_items = re.findall(r'class="cnav[^"]*" data-p="([a-z]+)"', nav)
    assert nav_items == ["login", "users", "pacing", "globals"], (
        "左侧分区变化：%s" % nav_items)
    labels = [x.strip() for x in re.findall(r'</svg>([^<]+)<i class="cnavn"', nav)]
    assert len(labels) == len(nav_items), "分区名解析失败：%s" % labels
    nav_badge_labels = lambda: labels
    EN_PARTITION_ALIASES = {
        "channel login": "渠道登录", "users & routes": "用户与航线",
        "users and routes": "用户与航线", "global": "全局参数",
        "channel pacing": "渠道节流", "pacing": "渠道节流",
    }

    # 面板数与分区数必须相等；多出来的面板只能是用户卡内联的关注面板
    panels = re.findall(r'<div class="cfpanel" id="panel-([a-z]+)"', WEBUI)
    extra = sorted(set(panels) - set(nav_items))
    assert extra == ["watch"], "多出的配置面板不是已知的关注面板：%s" % extra
    assert 'id="cfgWatchPark"' in WEBUI, "关注面板寄存区缺失，无法解释 panel-watch 无左侧入口"

    for name in ("README.md", "README_EN.md"):
        p = ROOT / name
        if not p.exists():
            pytest.skip("%s 不存在" % name)
        doc = p.read_text(encoding="utf-8", errors="replace")
        # 只钉「左侧分区枚举」这一处：从左/侧/L-side 起，到括号收尾为止
        m = re.search(r"(?:左侧|left[\s-]?side)[^（(\n]{0,40}[（(]([^）)\n]{4,80})[）)]", doc, re.I)
        assert m, "%s 找不到左侧分区枚举" % name
        enum = re.sub(r"\s*/\s*", "/", m.group(1).strip())
        parts = [x.strip() for x in enum.split("/") if x.strip()]
        assert len(parts) == len(nav_items), (
            "%s 左侧分区数 %d ≠ 界面 %d（%s）：%s" % (name, len(parts), len(nav_items), parts, enum))
        for p_ in parts:
            assert p_ in nav_badge_labels() or p_ in EN_PARTITION_ALIASES, (
                "%s 分区名「%s」不在界面左侧导航里（界面：%s）" % (name, p_, nav_badge_labels()))
        for stale in ("航班监控", "flight watch"):
            assert stale not in enum.lower(), "%s 把「%s」写成左侧分区（它是用户卡 D 区内联面板）" % (name, stale)


def test_no_stale_watch_tab_name_in_any_doc():
    """任何 md 在「页签枚举」语境里写出「关注航线走势 / 关注航班走势 / 关注航班明细」
    都必须就近标注改名——这些名字在 `#montabs` 里已不存在。

    实测踩过：历史设计文档与验收矩阵一直写着旧页签枚举，读者对照界面找不到；
    但「关注航线/关注航班走势」作为功能概念（曲线内容）是合法的，
    不能一刀切禁词（同 test_readme_console_tabs_match_ui 的教训）。
    """
    stale_names = ("关注航线走势", "关注航班走势", "关注航班明细",
                   "watch trend", "watch details")
    enum_hints = ("tab", "页签", "子视图")
    annotate_hints = ("改名", "已去掉", "现为", "落地差异", "旧名", "旧称", "已废",
                      "renamed", "no longer")
    offenders = []
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(("_scratch/", "docs/release-notes", ".workbuddy/", "node_modules/")):
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            low = line.lower()
            if not any(s.lower() in low for s in stale_names):
                continue
            if not any(h in low for h in enum_hints):
                continue
            window = "\n".join(lines[i:i + 9]).lower()
            if any(k in window for k in annotate_hints):
                continue
            offenders.append("%s:%d %s" % (rel, i + 1, line.strip()[:70]))
    assert not offenders, "文档仍用界面不存在的页签名：\n" + "\n".join(offenders)


def test_advice_hint_states_its_own_basis():
    """建议条的成功率文案必须自报口径（「查询成功率」），并在有退役通路时说明。

    实测踩过（r417）：健康面板按轮次报 13%、建议条按查询报 100%，
    用户以为两个面板互相矛盾。两者都对，缺的是那一句口径说明。
    """
    pacing = (ROOT / "core" / "pacing.py").read_text(encoding="utf-8")
    i = pacing.find("def advise(")
    assert i > 0, "未找到 advise"
    j = pacing.find("\ndef ", i + 10)
    body = pacing[i:j if j > 0 else i + 20000]
    assert "查询成功率" in body, "建议条文案没有写明是查询口径"
    assert "已排除退役通路" in body, "有退役通路时建议条没说明剔除情况"
    assert "retired_paths" in body and "query_rate_live" in body, (
        "建议条未读取在用口径字段（退役说明会缺数据源）")

    spec = (ROOT / "docs" / "EXECUTION_SPEC_LATEST.md").read_text(encoding="utf-8")
    assert "查询成功率" in spec, "SPEC 未记录建议条的口径用词"
    assert "已排除退役通路" in spec, "SPEC 未记录退役通路的文案要求"


def test_playbook_penalty_basis_matches_code():
    """PLAYBOOK 的「成功率保护」表必须写明它读的是哪个口径，且与 main.py 一致。

    实测：同程有三套数字（轮次 13% / 查询 76% / 在用 100%），
    罚速表若只写「近 24h 成功率」，读者会以为它跟着健康徽标在用计算用口径，
    实际 `main.py` 传的是原口径 `query_rate`——判错就会去查错的数据源。
    """
    playbook = ROOT / "docs" / "RATE_LIMIT_PLAYBOOK.md"
    if not playbook.exists():
        pytest.skip("PLAYBOOK 不存在")
    doc = playbook.read_text(encoding="utf-8", errors="replace")

    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    uses_raw = 'set_health(_p, _node.get("query_rate")' in main_src
    uses_live = "set_health(_p, _node.get(\"query_rate_live\")" in main_src
    assert uses_raw or uses_live, "未找到 set_health 的口径来源"

    # 文档必须指名原口径，且不得写成在用口径
    assert "原口径" in doc and "query_rate" in doc, (
        "PLAYBOOK 未写明罚速表读的是原口径 query_rate")
    if uses_raw:
        assert not uses_live, "main.py 两种口径都在传，需人工核对文档"
        # 罚速段必须点名原口径，且不得出现"用在用口径"这类正面断言。
        # 注意：「不是在用口径」是否定句，是合法写法，不能一刀切禁词
        # （同 test_readme_console_tabs_match_ui 的教训）。
        i = doc.find("成功率保护")
        seg = doc[i:i + 1200].split("###")[0] if i > 0 else doc
        assert "原口径" in seg, "罚速段没写它读的是原口径"
        claims_live = re.search(r"(?:使用|采用|按|用的是)\s*「?在用口径", seg)
        assert not claims_live, (
            "罚速段声称用在用口径，但 main.py 实际传 query_rate：%s"
            % (claims_live.group(0) if claims_live else ""))


def test_design_doc_channel_coverage_claims():
    """设计文档里的「当前只有 N/5 渠道」必须带复核日期；五渠道均已注册进代码。

    实测踩过：probe-console-design §0.10.3 把 10-21 的「3/5 渠道（去哪儿/同程 0）」
    写成"当前"，而当天五个渠道都有真实落库行——读者会误判两个渠道断供。
    判据：出现「N/5 渠道」的句子，同一段（前 300 字符内）必须有日期或"当时/快照/复核"。
    """
    design = ROOT / "docs" / "design" / "probe-console-design.md"
    if not design.exists():
        pytest.skip("设计稿不存在")
    doc = design.read_text(encoding="utf-8", errors="replace")

    bad = []
    occurrences = 0
    for m in re.finditer(r"\d\s*/\s*5\s*渠道", doc):
        occurrences += 1
        start = max(0, m.start() - 300)
        ctx = doc[start:m.end() + 120]
        if re.search(r"20\d\d-\d\d-\d\d|当时|快照|复核|过期|已过期", ctx):
            continue
        bad.append(ctx.replace("\n", " ")[-90:])
    # 下限：实测设计稿有 1 处「N/5 渠道」断言。0 处说明该说法被删或改写，
    # 门禁会停摆——那时应当删掉本门禁，而不是让它假装还在守。
    assert occurrences, (
        "设计稿已无「N/5 渠道」这类覆盖断言，本门禁失去检查对象（需人工确认是否删掉该门禁）")
    assert not bad, "渠道覆盖断言没有时效标注：\n" + "\n".join(bad)

    # 五个渠道都必须在 crawler 注册表里，否则"5/5"这一类说法无从谈起
    links = (ROOT / "core" / "channel_links.py").read_text(encoding="utf-8")
    for plat in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert '"%s"' % plat in links, "渠道注册表缺少 %s" % plat


def test_doc_symbol_anchors_exist():
    """文档里写成 `path.py::symbol()` 的锚点，符号必须真的存在。

    实测踩过：CAPTCHA_SOLUTION 的能力表用一串裸行号做证据
    （`crawlers/base.py:419-464`），webui.py 被几轮大改后全部失配；
    我按语义改成符号锚点时又凭印象写了 `_record_path()`/`_persistent_ctx()`，
    两者在代码里并不存在——符号锚点比行号稳，但必须被验证。
    """
    pat = re.compile(r"`([\w/]+\.py)::(\w+)\(\)`")
    offenders = []
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(("_scratch/", "node_modules/")):
            continue
        for m in pat.finditer(p.read_text(encoding="utf-8", errors="replace")):
            src_file, symbol = m.group(1), m.group(2)
            src = ROOT / src_file
            if not src.exists():
                offenders.append("%s: 文件不存在 %s" % (rel, src_file))
                continue
            body = src.read_text(encoding="utf-8", errors="replace")
            if ("def %s(" % symbol) not in body and ("function %s(" % symbol) not in body:
                offenders.append("%s: %s 里没有 %s()" % (rel, src_file, symbol))
    assert not offenders, "文档符号锚点失效：\n" + "\n".join(sorted(set(offenders)))

    spec = (ROOT / "docs" / "EXECUTION_SPEC_LATEST.md").read_text(encoding="utf-8")
    assert "节流罚速" in spec or "set_health" in spec, (
        "SPEC 未记录罚速读原口径这条边界")


def test_security_policy_claims_match_code():
    """SECURITY.md 的三条硬声明必须与代码/配置一致——它是读者-facing 的安全承诺。

    实测踩过（2026-10-28）：原文写「控制台只监听 `127.0.0.1`，不暴露公网」，
    却在同一文件末尾说「请不要手动改绑 0.0.0.0」——自相矛盾：配置本来就支持
    `web.host: 0.0.0.0`（局域网可达，手机看详情页的前提）。安全声明必须说清
    「默认」与「可改绑」，否则用户会以为改不了、或以为改不了就没风险。
    同时漏记 ghimg 的 10 分钟熔断与 smms 的「不推荐」定性。
    """
    doc_path = ROOT / "SECURITY.md"
    assert doc_path.exists(), "SECURITY.md 不存在（读者会以为项目没有安全策略）"
    doc = doc_path.read_text(encoding="utf-8", errors="replace")

    # 1) config.yaml 必须仍被 gitignore——这是"凭据永不入库"承诺的地基
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    assert re.search(r"^config\.yaml\s*$", gitignore, re.M), (
        ".gitignore 不再拦截 config.yaml，但 SECURITY.md 承诺凭据永不入库")
    assert "config.yaml" in doc, "SECURITY.md 未说明凭据存放位置"

    # 2) 监听地址：默认回环 + 可改绑，两者都要写，且不得写成"只监听"
    # r675 起默认值由 _bind_host() 单源解析：config 显式值 → TM_WEB_HOST
    # 环境变量 → 127.0.0.1。旧锚点写死 `get("host") or "127.0.0.1"` 的源码
    # 形状，函数一抽出来就永远匹配不到——锚点失效不等于默认值改错。
    # 这里按函数体取回环兜底那行，仍要求「回环是缺省」这一语义。
    _bh = re.search(r"def _bind_host\(.*?\n(?=\S)", WEBUI, re.S)
    assert _bh, "未找到 _bind_host()，本门禁失去锚点"
    code_default = re.search(r'or\s*"(127\.0\.0\.1)"', _bh.group(0))
    assert code_default, "web.host 缺省不再是回环 127.0.0.1，SECURITY.md 说法需复核"
    assert "默认只监听" in doc, (
        "SECURITY.md 必须写明控制台是「默认」监听回环（配置可改绑 0.0.0.0）")
    assert "0.0.0.0" in doc, "SECURITY.md 必须提示可改绑 0.0.0.0 及其无鉴权风险"
    assert "只监听 `127.0.0.1`，不暴露公网" not in doc, (
        "SECURITY.md 仍有「只监听 127.0.0.1，不暴露公网」的绝对化说法（与 web.host 可改绑矛盾）")

    # 3) 图床：提到的 provider 必须在 report.py 里真有实现
    report = (ROOT / "report.py").read_text(encoding="utf-8", errors="replace")
    for prov in ("ghimg", "smms", "freeimage"):
        assert prov in doc, "SECURITY.md 未列出 provider %s" % prov
        assert ("upload_%s(" % prov) in report, (
            "SECURITY.md 提到的 provider %s 在 report.py 里没有 upload_%s" % (prov, prov))
    # ghimg 的熔断冷却必须写出来（用户以为是即时失败，实际跳 10 分钟）
    m = re.search(r"_GH_FAIL_COOLDOWN_S\s*=\s*([\d.]+)", report)
    assert m, "report.py 未找到 ghimg 熔断冷却常量"
    assert "600" in doc or "10 分钟" in doc, (
        "SECURITY.md 未写明 ghimg 失败后的熔断时长（代码 %s 秒）" % m.group(1))


def test_mobile_docs_conclusions_are_consistent():
    """5 份移动端文档对同一事实的说法必须一致，且过期结论要被标注推翻。

    实测踩过（2026-10-28）：`MOBILE_CHANNEL_OPTIONS.md` 头部说 MuMu 已验收
    （`adb connect` 免点界面、美团跑通），同一文件的路径表 C 行却仍标「⚠️ 未实测」；
    同时 `MOBILE_MUMU_ACCEPTANCE.md` 写「智行装不上（只有 32 位）」，而同日
    `MOBILE_ZHIXING_A12_RESULT.md` 已推翻该结论——三处互相矛盾。
    读者按哪份做都会得到不同结论，这是移动端这组文档最典型的漂移形态。
    """
    opts = ROOT / "docs" / "MOBILE_CHANNEL_OPTIONS.md"
    mumu = ROOT / "docs" / "MOBILE_MUMU_ACCEPTANCE.md"
    zx = ROOT / "docs" / "MOBILE_ZHIXING_A12_RESULT.md"
    for p in (opts, mumu, zx):
        assert p.exists(), "%s 不存在" % p.name

    opt = opts.read_text(encoding="utf-8", errors="replace")
    # 1) MuMu 那行不得再标"未实测"
    line_c = next((l for l in opt.splitlines()
                   if l.startswith("| **C**")), None)
    assert line_c, "路径总表找不到 C 行（本门禁失去锚点）"
    assert "未实测" not in line_c or "LDPlayer" in line_c, (
        "C 行仍把 MuMu 标成未实测，但 MOBILE_MUMU_ACCEPTANCE.md 已验收：%s"
        % line_c.strip()[:90])
    assert "已实测" in line_c, "C 行未写明 MuMu 已实测通过"

    # 2) MuMu 验收文档里"智行装不上"必须标注已被推翻。
    #    标注常在下方引用块/表格后的段落里，所以看该行 + 后续 8 行，
    #    不能只看同一行（实测：标注写成紧邻的 `>` 引用段，逐行判会假红）。
    mu = mumu.read_text(encoding="utf-8", errors="replace")
    mu_lines = mu.splitlines()
    for i, line in enumerate(mu_lines):
        if "智行" not in line:
            continue
        if not re.search(r"(装不上|只有 32 位|armeabi)", line):
            continue
        window = "\n".join(mu_lines[i:i + 9])
        assert re.search(r"(推翻|已推翻|以 .*ZHIXING.* 为准|旧结论|当次)", window), (
            "MOBILE_MUMU_ACCEPTANCE 仍把「智行只有 32 位/装不上」写成结论而未标注推翻：%s"
            % line.strip()[:90])

    # 3) 智行文档必须仍给出 64 位结论（不得被回退）
    z = zx.read_text(encoding="utf-8", errors="replace")
    assert "arm64-v8a" in z and "64 位" in z, (
        "MOBILE_ZHIXING_A12_RESULT 不再声明 64 位包可用的结论")


def test_zhixing_apk_abi_claim_matches_files():
    """智行文档的「两个包，一个 32 位一个 64 位」必须能被本地 APK 逐字节复现。

    实测踩过（2026-10-28）：文档写 88.5MB/armeabi、104.0MB/arm64-v8a 并给了
    精确安装字节 104,041,797，但 `_scratch/mobile_paths/apk/` 下另有两份
    10.26.0 版（79–80MB、**只有 armeabi**）——若不指明路径，复核者会打开错的包，
    得出「智行还是只有 32 位」的反向结论（这正是文档第 1 节记录的历史误判）。
    本门禁钉住：路径被点名 + 字节数/A­BI/.so 数三项都对得上。
    """
    import zipfile
    doc_path = ROOT / "docs" / "MOBILE_ZHIXING_A12_RESULT.md"
    assert doc_path.exists(), "MOBILE_ZHIXING_A12_RESULT.md 不存在"
    doc = doc_path.read_text(encoding="utf-8", errors="replace")

    cases = [
        ("_scratch/mobile_paths/apk2/zhixing_travel_10.25.8.apk", 88475842, "armeabi", 51),
        ("_scratch/mobile_paths/apk2/zhixing_v2.apk", 104041797, "arm64-v8a", 65),
    ]
    for rel, size, abi, nso in cases:
        p = ROOT / rel
        # APK 样本只在装了移动运行时的机器上存在（_scratch 不入库）。
        # 缺失时跳过**体积/ABI**子断言，仍校验文档写明了路径与结论——
        # 否则这条门禁在 CI 上永远红，读者也看不到任何有效结论。
        if not p.exists():
            assert rel in doc, "文档未写明 64/32 位样本的本地路径：%s" % rel
            continue
        assert rel in doc, "文档未写明 64/32 位样本的本地路径：%s" % rel
        assert p.stat().st_size == size, (
            "%s 实际 %d 字节，文档写 %d" % (rel, p.stat().st_size, size))
        with zipfile.ZipFile(p) as z:
            libs = [n for n in z.namelist()
                    if n.startswith("lib/") and n.endswith(".so")]
        abis = {n.split("/")[1] for n in libs}
        assert abis == {abi}, "%s 的 ABI 是 %s，文档写 %s" % (rel, sorted(abis), abi)
        assert len(libs) == nso, (
            "%s 的 .so 有 %d 个，文档写 %d" % (rel, len(libs), nso))
    # 精确安装字节必须出现在文档里，且与 64 位包一致
    assert "%d" % 104041797 in doc.replace(",", ""), (
        "文档未记录 64 位包的精确安装字节 104041797")


def test_design_context_doc_matches_code():
    """`.impeccable.md`（设计上下文）里的硬值必须与代码一致。

    实测踩过（2026-10-28）：原文写「蓝主色（#1a73e8 族）」——该色值在
    webui.py 里**一次都没出现**，真实主色是 `--blue:#0b62d6`（亮）/`#63a4f8`（暗）。
    设计文档是"给 AI/新人看的风格基准"，色值错了会被照着做错。
    另有两处口径过期：写死「3 条航线」（航线数由 `monitor.routes` 配置）、
    写「近 48h 轮次聚类」（实际范围 48h/7天/30天/90天/半年，默认 30 天）。
    """
    p = ROOT / ".impeccable.md"
    if not p.exists():
        # 该文件被 .gitignore（本地设计上下文，不入库），CI checkout 里没有。
        # 缺失时本门禁无对象可校验——跳过而不是判红（判红只说明环境不同）。
        import pytest as _pytest
        _pytest.skip(".impeccable.md 未入库（本地设计上下文），跳过")
    doc = p.read_text(encoding="utf-8", errors="replace")

    # 1) 文档里出现的每个 hex 色值，要么在 webui.py 里存在，要么被标注为"废弃/旧"
    for hexv in set(re.findall(r"#[0-9a-fA-F]{6}\b", doc)):
        if hexv.lower() in WEBUI.lower():
            continue
        line = next((l for l in doc.splitlines() if hexv in l), "")
        assert re.search(r"(旧|废弃|曾被|不再|历史)", line), (
            "设计上下文引用了代码中不存在的色值 %s：%s" % (hexv, line.strip()[:80]))

    # 2) 主题三态必须与代码的 THEMES 一致
    themes = re.search(r"THEMES\s*=\s*\[([^\]]*)\]", WEBUI)
    assert themes, "未找到 THEMES 定义，本门禁失去锚点"
    for mode in re.findall(r"'([a-z]+)'|\"([a-z]+)\"", themes.group(1)):
        name = mode[0] or mode[1]
        if name in ("auto", "light", "dark"):
            assert name in doc or "亮" in doc, (
                "代码主题含 %s，设计上下文未提及主题三态" % name)

    # 3) 走势范围不得写死成只有 48h
    assert "近 48h 轮次聚类" not in doc, (
        "设计上下文仍把走势范围写死为「近 48h」——实际有 48h/7天/30天/90天/半年")


def test_historical_release_notes_declare_staleness():
    """历史版本的 release-notes 必须声明「这是当次快照」。

    实测踩过（2026-10-28）：38 份 release-notes 里有 37 份**没有任何时效声明**，
    正文却写满测试计数、渠道状态、界面结论——读者（尤其 AI）会把
    「v1.5.265 渠道 5/5 全绿」当成现状引用，而这正是文档漂移的主要来源。
    当前版本那份不标（它就是现状），其余一律要标。
    """
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    cur = re.search(r'^__version__\s*=\s*"([^"]+)"', main_py, re.M).group(1)
    notes = sorted((ROOT / "docs").glob("release-notes-v*.md"))
    assert notes, "docs/ 下没有 release-notes，本门禁失去检查对象"

    missing = []
    checked = 0
    for p in notes:
        m = re.match(r"release-notes-v([\d.]+)\.md$", p.name)
        assert m, "release-notes 命名不符合 release-notes-vX.Y.Z.md: %s" % p.name
        ver = m.group(1)
        if ver == cur:
            continue          # 当前版本 = 现状，不需要历史声明
        checked += 1
        head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:8])
        if "时效边界" not in head:
            missing.append(p.name)
    assert checked >= 5, "只找到 %d 份历史 release-notes，疑似目录结构变更" % checked
    assert not missing, (
        "这些历史 release-notes 缺「时效边界」声明，读者会把当次快照误当现状：%s"
        % missing[:8])


def test_contributing_commands_carry_required_env():
    """CONTRIBUTING 里的验证命令必须带够环境变量，且说法与实测一致。

    实测踩过（两处）：
    1. 旧版只写 `python docs/uitest.py`，而该脚本会打印 `✓/✗/♻`，
       Windows GBK 控制台下直接 `UnicodeEncodeError` 崩掉。
    2. 反向我也写错过一次：声称 pytest 也"必须"带 PYTHONIOENCODING——
       实测 pytest 在 GBK 下会把 `❌` 转义成 `\\u274c` 正常输出，不崩。
       结论改成"对 pytest 不是硬要求"后才准确。
    """
    doc = ROOT / "CONTRIBUTING.md"
    if not doc.exists():
        pytest.skip("CONTRIBUTING 不存在")
    text = doc.read_text(encoding="utf-8", errors="replace")

    # 只在 ```bash 代码块里取命令行——正文里的「pytest 在加载插件阶段就崩」
    # 是解释，不是命令（第一版按整行匹配，把说明句当命令判红）。
    blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
    assert blocks, "CONTRIBUTING 没有 bash 命令块"
    commands = [ln.strip() for b in blocks for ln in b.splitlines() if ln.strip()]
    assert commands, "CONTRIBUTING 的命令块是空的"

    pytest_cmds = [ln for ln in commands if "pytest " in ln]
    assert pytest_cmds, "CONTRIBUTING 没给 pytest 命令"
    for ln in pytest_cmds:
        assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in ln, (
            "pytest 命令没带插件隔离变量：%s" % ln)

    uitest_cmds = [ln for ln in commands if "uitest.py" in ln]
    assert uitest_cmds, "CONTRIBUTING 没给 uitest 命令"

    # 不得声称「不加 PYTHONIOENCODING 就崩」——实测两条命令都有兜底：
    # pytest 把 ❌ 转义成 \u274c；uitest 在 main() 里 reconfigure(errors="replace")。
    # 两种语序都要抓：旧式「uitest 必须带 X」与本轮的「X 必须带上」。
    for bad in (r"uitest[^\n]{0,40}必须[^\n]{0,20}PYTHONIOENCODING",
                r"pytest[^\n]{0,40}必须[^\n]{0,20}PYTHONIOENCODING",
                r"PYTHONIOENCODING[^\n]{0,30}必须"):
        assert not re.search(bad, text), (
            "CONTRIBUTING 声称该命令必须带 PYTHONIOENCODING，与实测不符（两者都有兜底）")

    # 若文档要求带编码变量，脚本必须真有兜底或真会崩，二者至少一条成立
    if "PYTHONIOENCODING" in text:
        uitest = (ROOT / "docs" / "uitest.py").read_text(encoding="utf-8", errors="replace")
        has_guard = 'reconfigure(errors="replace")' in uitest
        has_glyph = any(ch in uitest for ch in ("✓", "✗", "♻"))
        assert has_guard or has_glyph, (
            "uitest.py 既不打印非 GBK 字符也没有 reconfigure 兜底，文档提编码变量就无依据")


def test_python_floor_matches_pep604_usage():
    """README 徽章/CONTRIBUTING 声明的 Python 下限，必须能跑得动代码里的 PEP 604 注解。

    实测踩过：README 长期挂 `Python 3.9+`，但 `core/radar_alerts.py:25` 的
    `prev_low: float | None = None` 是 dataclass 字段注解——**运行时求值**，
    3.9 会直接 `TypeError: unsupported operand type(s) for |`。
    判据：存在不受 `from __future__ import annotations` 保护的文件里
    用了 `X | None` 注解，则文档下限必须 ≥ 3.10。
    """
    future_ok = set()
    pep604_files = []
    skip_prefix = ("_scratch/", "_build_check/", ".venv/", "build/", "dist/")
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(skip_prefix):
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        if "from __future__ import annotations" in body:
            future_ok.add(rel)
            continue
        for ln in body.splitlines():
            if re.search(r"(?::|->)\s*\w+\s*\|\s*(?:None|int|str|float|list|dict)\b", ln):
                pep604_files.append(rel)
                break

    if not pep604_files:
        pytest.skip("代码里没有需要 3.10 的注解，下限可放宽")

    for name in ("README.md", "README_EN.md", "CONTRIBUTING.md"):
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"Python[- ](\d+)\.(\d+)\s*(\+|%2B|plus)?", text)
        if not m:
            continue
        major, minor = int(m.group(1)), int(m.group(2))
        assert (major, minor) >= (3, 10), (
            "%s 声明 Python %d.%d+，但代码里的 PEP 604 注解需要 3.10"
            "（例：%s）" % (name, major, minor, sorted(set(pep604_files))[:3]))



def test_tests_carry_no_machine_specific_paths():
    """测试不得写死本机真实路径/工作目录（换机必假红，也泄露本机信息）。

    实测踩过：文档体积校验把某一台机器的 MuMu 安装目录写死在测试里，
    换机后该断言直接不执行（假绿），换平台还会假红。
    判据只认「本机独有的目录名」（开发目录/用户主目录名）；喂给路径
    校验函数的合成样例（D:/ok/prices.db、C:/MuMu）不算。
    """
    bad = []
    skip = {"test_docs_code_contract.py"}
    for p in sorted((ROOT / "tests").rglob("*.py")):
        if p.name in skip:
            continue
        for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "noqa: machine-path" in line:
                continue
            if "idea_project" in line.lower():
                bad.append("%s:%d  %s" % (p.name, i, line.strip()[:90]))
    assert not bad, "测试里出现本机开发目录路径：%s" % bad[:10]
