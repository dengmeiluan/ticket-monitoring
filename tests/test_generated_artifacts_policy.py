# -*- coding: utf-8 -*-
"""门禁：生成物与仓库边界（docs/GENERATED_ARTIFACTS.md 的可执行版本）。

2026-11-12 的问题：`docs/uitest_result.txt` 是**每次运行都变**的生成物，
却因为历史原因留在 git 索引里——`git status` 长期挂着一个永远脏的文件，
审阅者分不清哪些是真改动；并发跑还会互相覆盖结果。

这条门禁把边界钉死：
1. A 类（生成物）绝不许被跟踪——命中即报具体路径；
2. B 类（生成物但必须入库）必须既在索引里、又在文档里写明「怎么重生成」；
3. `docs/uitest_result.txt` 必须在 `.gitignore` 且不在索引里；
4. 文档存在且覆盖三类划分（防"删了文档、门禁还在绿"）。
"""
import io
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "GENERATED_ARTIFACTS.md")

# A 类：生成物，必须不入库
FORBIDDEN_PATTERNS = (
    r"(^|/)__pycache__/",
    r"\.pyc$",
    r"^data/",
    r"^logs/",
    r"^user_data/",
    r"^debug/",
    r"^_scratch/",
    r"^dist_package/",
    r"^_build",
    r"^build/",
    r"^dist/",
    r"\.statecache$",
    r"\.log$",
    r"\.bak",
    r"uitest_.*\.(js|png)$",
    r"uitest_v\d+_result\.json$",
    r"^docs/uitest_result\.txt$",
    r"^\.uitest\.lock$",
    r"\.db$",
)

# B 类：生成物但必须入库（每项都要能在文档里查到重生成方式）
ALLOW = {
    "docs/site/index.html": "GitHub Pages 发布的静态站本体",
    "tests/ci_durations.json": "CI 分片耗时快照（均衡分片）",
    "docs/uitest_profile.json": "UI 自检分片权重（test_parallel_suite 读它）",
}
ALLOW_GLOB = {
    "docs/screenshots/": "README/Release 引用的截图，由 docs/screenshot.py 生成",
}


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def _doc():
    assert os.path.exists(DOC), "缺 docs/GENERATED_ARTIFACTS.md（边界文档）"
    return io.open(DOC, encoding="utf-8").read()


def test_generated_artifacts_are_not_tracked():
    import re
    bad = []
    for p in _tracked():
        for pat in FORBIDDEN_PATTERNS:
            if re.search(pat, p):
                if any(p == k or p.startswith(k) for k in ALLOW):
                    continue
                if any(p.startswith(k) for k in ALLOW_GLOB):
                    continue
                bad.append((p, pat))
                break
    assert not bad, "这些生成物被 git 跟踪了（应从索引移除并 gitignore）：%s" % bad[:6]


def test_uitest_result_is_ignored_and_untracked():
    gi = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    assert "docs/uitest_result.txt" in gi, "uitest 结果文件没进 .gitignore"
    assert "docs/uitest_result.txt" not in _tracked(), \
        "docs/uitest_result.txt 仍被跟踪（它是每次运行都变的生成物）"


def test_bucket_b_files_are_tracked_and_documented():
    tracked = set(_tracked())
    doc = _doc()
    for path, why in ALLOW.items():
        assert path in tracked, "B 类文件不在索引里：%s" % path
        assert os.path.exists(os.path.join(ROOT, path)), "B 类文件不存在：%s" % path
        assert path in doc, "文档没列 B 类文件：%s" % path
    for prefix, why in ALLOW_GLOB.items():
        assert any(p.startswith(prefix) for p in tracked), \
            "B 类目录下没有跟踪文件：%s" % prefix
        assert prefix in doc, "文档没列 B 类目录：%s" % prefix


def test_doc_covers_three_buckets_and_refresh_commands():
    doc = _doc()
    for k in ("A. 生成物", "B. 生成物", "C. 真·源文件",
              "docs/demo_build.py", "docs/screenshot.py",
              "ci_shard", "uitest_profile"):
        assert k in doc, "边界文档缺：%s" % k


def test_test_all_does_not_claim_result_file_is_tracked():
    """`tools/test_all.py` 里曾写「受跟踪的常态产物」——那是错的，别再漂回去。"""
    src = io.open(os.path.join(ROOT, "tools", "test_all.py"),
                  encoding="utf-8").read()
    assert "受跟踪的常态产物" not in src, \
        "test_all.py 仍声称结果文件受跟踪（实际已不入库）"
