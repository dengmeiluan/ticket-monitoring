"""一键引导：`python -m core.bootstrap`（r1063 T157）

目标（objective 原话）：**"github 下载我们项目的安装的时候傻瓜化可自动化爬取"**。

现状：`core.setup_check` 已经把「安全修复动作」定义全了
（`install_deps` / `install_browser` / `create_config` / `mkdir` /
`launch_emulator` / `restart_emulator`），但用户要自己跑 `--fix`、自己判断
还差什么、自己起服务。这个模块把整条链串起来：

1. 反复「自检 → 修可修的」，最多 3 轮（装依赖后往往才暴露下一项）；
2. 把剩余问题按 ✅/⚠/❌ 汇总，并给出**下一步该做什么**（人话）；
3. `--start` 直接拉起监控（等价于 `python main.py`），并打印面板地址。

**边界**：只做"机器能不能跑"的事，绝不碰账号、登录、策略、订阅
——这些属于用户意图，不替用户决定。
"""
from __future__ import annotations

import os
import subprocess
import sys

MAX_PASSES = 3


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bootstrap(echo=print, max_passes: int = MAX_PASSES,
              checks=None, apply=None) -> dict:
    """把环境修到"能跑"。返回 {ok, passes, fixed, remaining}。"""
    from core import setup_check as sc

    run_checks = checks or sc.run_checks
    apply_fix = apply or sc.apply_fix
    fixed = []
    rows = []
    passes = 0
    for _ in range(max(1, int(max_passes))):
        passes += 1
        rows = run_checks()
        todo = sc.fixable(rows)
        if not todo:
            break
        for row in todo:
            name = str(row.get("name") or "")
            ok = False
            try:
                ok = bool(apply_fix(row))
            except Exception as e:                       # 修复失败不该炸
                echo("  ✗ %s 修复异常：%s" % (name, str(e)[:80]))
            if ok:
                fixed.append(name)
                echo("  ✓ 已修复：%s" % name)

    remaining = [r for r in rows if r.get("level") in
                 (sc.BAD, sc.WARN)]
    ok = not any(r.get("level") == sc.BAD for r in rows)
    return {"ok": ok, "passes": passes, "fixed": fixed,
            "remaining": remaining}


def _report(rep: dict, echo=print) -> None:
    echo("")
    if rep["fixed"]:
        echo("已自动修复 %d 项：%s" % (len(rep["fixed"]),
                                    "、".join(rep["fixed"])))
    if not rep["remaining"]:
        echo("✅ 环境已就绪：直接开跑即可（下一条命令见下方提示）")
    else:
        echo("还有 %d 项需要你看一眼（不影响启动的会标 ⚠）："
             % len(rep["remaining"]))
        for r in rep["remaining"]:
            mark = "❌" if str(r.get("level")) == "BAD" else "⚠ "
            echo("  %s %s：%s" % (mark, r.get("name"), r.get("detail")))
            if r.get("fix"):
                echo("     → %s" % r.get("fix"))
    echo("")
    echo("下一步：")
    echo("  python -m core.bootstrap --start   # 修完顺手启动监控")
    echo("  python main.py                     # 或者自己起")
    echo("  python -m core.advise              # 自动诊断：现在最该做什么")
    echo("  python -m core.channel_matrix      # 起来后看每家每条通路")
    echo("  python -m core.channel_matrix --login   # 需要登录时看该登哪一格")


def _start(echo=print) -> dict:
    """拉起监控（新进程；不阻塞本命令）。"""
    root = _root()
    py = sys.executable or "python"
    try:
        proc = subprocess.Popen([py, os.path.join(root, "main.py")], cwd=root)
    except Exception as e:
        echo("✗ 启动失败：%s" % str(e)[:120])
        return {"ok": False, "why": str(e)[:120]}
    echo("已启动监控（pid=%s）。面板一般在本机 8765 端口。" % proc.pid)
    return {"ok": True, "pid": proc.pid}


def main(argv=None) -> int:                              # pragma: no cover
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    print("=== 一键引导（只修『能不能跑』，不碰账号/登录/策略）===")
    rep = bootstrap()
    _report(rep)
    if "--start" in argv:
        out = _start()
        return 0 if out.get("ok") else 1
    return 0 if rep["ok"] else 1


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())
