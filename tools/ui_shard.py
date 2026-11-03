# -*- coding: utf-8 -*-
"""docs/uitest.py 的分段分片：段号从源码 `_want(N)` 派生。

为什么要有这个工具
------------------
UI 自检是单进程脚本，整轮约 6 分钟，已经是 CI 的关键路径。脚本本身支持
``UITEST_SECTIONS``（0–49 段），但**段号不能写死在 workflow 里**：新增一段
后矩阵不知道，就会漏跑。这里直接从 ``docs/uitest.py`` 提取全部段号，按
连续区间二分，并校验 workflow 与分片计划一致。

用法：
    python tools/ui_shard.py --stats 2      # 并集=全集/无重复 + workflow 自检
    python tools/ui_shard.py --print 2 0    # 第 0 片：UITEST_SECTIONS 取值
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "uitest.py"
WF = ROOT / ".github" / "workflows" / "ci.yml"


def sections():
    text = SRC.read_text(encoding="utf-8")
    nums = sorted({int(m) for m in re.findall(r"_want\((\d+)\)", text)})
    if not nums:
        raise SystemExit("docs/uitest.py 没有 _want(N) 段标记")
    if nums != list(range(nums[0], nums[-1] + 1)):
        raise SystemExit("uitest 段号不连续：%r" % nums)
    return nums


def plan(n):
    if n < 1:
        raise SystemExit("分片数必须 >=1")
    secs = sections()
    size = (len(secs) + n - 1) // n
    groups = [secs[i * size:(i + 1) * size] for i in range(n)]
    groups = [g for g in groups if g]
    if len(groups) != n:
        raise SystemExit("段数不足，无法切成 %d 片" % n)
    return groups


def fmt(ids):
    out, start, prev = [], ids[0], ids[0]
    for x in ids[1:]:
        if x == prev + 1:
            prev = x
            continue
        out.append(str(start) if start == prev else "%d-%d" % (start, prev))
        start = prev = x
    out.append(str(start) if start == prev else "%d-%d" % (start, prev))
    return ",".join(out)


def check_workflow(n):
    wf = WF.read_text(encoding="utf-8")
    m = re.search(r"\n  uitest:\n(.*?)(?=\n  ci-ok:\n)", wf, re.S)
    if not m:
        raise SystemExit("ci.yml 找不到 uitest job")
    block = m.group(1)
    if "group: [%s]" % ", ".join(str(i) for i in range(n)) not in block:
        raise SystemExit("uitest matrix 不是 %d 组" % n)
    for needle in ("--stats %d" % n, "--print %d" % n, "UITEST_SECTIONS"):
        if needle not in block:
            raise SystemExit("uitest job 缺少 %r" % needle)
    tail = wf[wf.index("  ci-ok:"):]
    if "needs: [test, uitest]" not in tail:
        raise SystemExit("ci-ok 没有聚合 test + uitest")


def main(argv):
    if "--stats" in argv:
        n = int(argv[argv.index("--stats") + 1])
        groups = plan(n)
        all_ids = [x for g in groups for x in g]
        secs = sections()
        if sorted(all_ids) != secs or len(all_ids) != len(set(all_ids)):
            raise SystemExit("分片并集 != 全集或存在重复")
        for i, g in enumerate(groups):
            print("group %d  %3d 段  %s" % (i, len(g), fmt(g)))
        print("全部 %d 段：无遗漏/无重复" % len(secs))
        check_workflow(n)
        print("CI workflow 与 %d 片 UI 矩阵一致" % n)
        return 0
    if "--print" in argv:
        n = int(argv[argv.index("--print") + 1])
        k = int(argv[argv.index("--print") + 2])
        groups = plan(n)
        if not (0 <= k < len(groups)):
            raise SystemExit("片号越界")
        print(fmt(groups[k]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
