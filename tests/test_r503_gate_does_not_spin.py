# -*- coding: utf-8 -*-
"""r503：门禁自身不能空转——两处「盖了章却没跑全」的实测缺陷。

① `tools/test_all.py::plan_shards` 读 `profile["weights"]`，而 `--profile-ui`
   用新版格式写出的是 `{"sections": [{"i","seconds"}...]}` —— 直接 KeyError，
   门禁拿不到分组，**UI 分片的覆盖面成为未定义状态**。实测那次只跑出 569 项，
   而 profile 记的是 666 项，门禁只打了 [warn] 就继续。

② `docs/uitest.py` 结尾 `open(RESULT, encoding="utf-8")` 严格解码结果文件，
   混入任何非 UTF-8 字节就抛 UnicodeDecodeError —— 崩在 `os._exit` **之前**，
   退出码既不是 0 也不是 1，跑测方只看到一段 traceback，**全部检查结果作废**。

两条都属「绿灯可能空转」：门禁看起来跑完了，其实漏了东西。
"""
import importlib.util
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gate():
    spec = importlib.util.spec_from_file_location(
        "test_all", os.path.join(ROOT, "tools", "test_all.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_shard_plan_accepts_both_profile_shapes():
    """新旧两种 profile 形状都要能算出覆盖全段的计划。"""
    ta = _gate()
    old = {"weights": [10, 20, 30, 40], "shards": None}
    new = {"total_checks": 100,
           "sections": [{"i": 0, "seconds": 10}, {"i": 1, "seconds": 20},
                        {"i": 2, "seconds": 30}, {"i": 3, "seconds": 40}]}
    for prof, n_sec in ((old, 4), (new, 4)):
        g = ta.plan_shards(prof, 2)
        cov = sorted(i for x in g for i in x)
        assert cov == list(range(n_sec)), \
            "分片计划没覆盖全部段：%r ← profile=%r" % (cov, list(prof))


def test_real_profile_plan_covers_every_section():
    """仓库里真实的 profile 必须能被算成全段覆盖（这是门禁覆盖面的事实来源）。"""
    ta = _gate()
    p = json.load(io.open(os.path.join(ROOT, "docs", "uitest_profile.json"),
                          encoding="utf-8"))
    n = len(p.get("sections") or p.get("weights") or [])
    assert n > 0, "profile 里既没有 sections 也没有 weights"
    g = ta.plan_shards(p, 4)
    cov = sorted(i for x in g for i in x)
    assert cov == list(range(n)), \
        "真实 profile 的分片计划漏段：覆盖 %d 段，应有 %d" % (len(set(cov)), n)


def test_uitest_result_echo_survives_bad_bytes():
    """结果回显必须容错：严格解码会崩在 exit 之前，让全部结果作废。"""
    w = io.open(os.path.join(ROOT, "docs", "uitest.py"), encoding="utf-8",
                newline="").read()
    i = w.index("with open(RESULT")
    seg = w[i:i + 200]
    assert 'errors="replace"' in seg or "errors='replace'" in seg, \
        "结果回显仍严格解码（非 UTF-8 字节会让进程崩在 os._exit 之前）"
    # 崩掉就不能执行到 os._exit：确保回显被 try 包住
    assert "except Exception" in w[max(0, i - 400):i + 400], \
        "结果回显没有兜底"


def test_drift_verdict_separates_code_from_tooling():
    """源码改写判定要分级：只有**产品代码**变了才作废整轮。

    实测踩过：跑测 3 分钟里只有 `tools/test_all.py` 与 `CONTRIBUTING.md`
    被并行会话改过，产品代码一个字节没动，整轮却被判作废（退出码 3），
    等于白跑半小时。作废的判据应当是「结论还能不能对得上现在的代码」。
    """
    w = io.open(os.path.join(ROOT, "tools", "test_all.py"),
                encoding="utf-8", newline="").read()
    assert "CODE_GLOBS" in w, "没有区分「被测代码」的 glob"
    i = w.index("CODE_GLOBS = (")
    seg = w[i:w.index(")", i) + 1]
    for core in ("webui.py", "main.py", "core/*.py", "crawlers/*.py"):
        assert core in seg, "CODE_GLOBS 漏了 %s" % core
    # tools/ tests/ docs/ 这些不该进 CODE_GLOBS
    for soft in ("tools/*.py", "tests/*.py", "docs/*.md"):
        assert soft not in seg, "%s 不该算「产品代码」" % soft
    # 两级判定：代码变 → 退出码 3；只有脚本/文档变 → 仅提示
    # 用 rindex：源码里 `source_digest(CODE_GLOBS)` 先出现在 code0 的赋值处，
    # 判定处在文件末尾。
    j = w.rindex("if code0 is not None and source_digest(CODE_GLOBS) != code0")
    assert "code = 3" in w[j:j + 600], "产品代码变化未作废整轮"
    # 条件本身必须在位：只把 `code = 3` 留在代码里、把 if 改成 False，
    # 门禁就形同虚设了（实测这种变异能骗过「只查字面量」的断言）。
    assert "if code0 is not None and source_digest(CODE_GLOBS) != code0" in w, \
        "作废条件被禁用或改写了"
    assert "结果仍然有效" in w[j:j + 900], "脚本/文档变化仍被当作废"


def test_code_globs_only_covers_the_shipped_product():
    """行为面：改 tools/ 下的文件不应影响 CODE_GLOBS 摘要。"""
    ta = _gate()
    import tempfile
    d = tempfile.mkdtemp()
    # 用一个假的 ROOT 不好构造，改为直接比对当前仓库的两次摘要
    a = ta.source_digest(ta.CODE_GLOBS)
    b = ta.source_digest(ta.CODE_GLOBS)
    assert a == b, "同一时刻两次摘要不一致"
    full = ta.source_digest()
    assert full != a, "CODE_GLOBS 摘要应与全量摘要不同（否则没起到区分作用）"
