#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量验证并发编排（r481）：pytest 走 xdist，UI 自检同跑。

两条泳道：pytest（-n N，按文件整组分配）与 docs/uitest.py 同时跑；
UI 自检按 docs/uitest_profile.json 的实测权重切成 4 片并行（每片独立
demo 服 + 浏览器，结果合并校验总项数）。末尾给统一摘要，任何一条红即
非零退出。串行口径原样保留，`--serial` 的 pytest 命令与 CONTRIBUTING
里的验收命令逐词一致。

用法：
  python tools/test_all.py                    # 默认 min(8, CPU) 个 worker
  python tools/test_all.py --workers 12
  python tools/test_all.py --serial           # 串行（与 CI 同口径）
  python tools/test_all.py --no-ui            # 只跑语法检查 + pytest
  python tools/test_all.py --ui-shards 1      # UI 自检退回单进程
  python tools/test_all.py --profile-ui       # 重算 UI 分片权重（完整跑一轮）
  python tools/test_all.py --bootstrap-deps   # 无管理员权限时把 xdist 装到 _scratch/testdeps

退出码：0 全绿；1 用例失败；2 语法检查失败；3 跑测期间源码被改写；4 缺 xdist。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "_scratch" / "test_run"
DEPS_DIR = ROOT / "_scratch" / "testdeps"

COMPILE_TARGETS = (["main.py", "webui.py", "report.py", "wizard.py"]
                   + ["core/" + p.name for p in sorted((ROOT / "core").glob("*.py"))]
                   + ["crawlers/" + p.name
                      for p in sorted((ROOT / "crawlers").glob("*.py"))])

SOURCE_GLOBS = ("webui.py", "main.py", "report.py", "wizard.py",
                "core/*.py", "crawlers/*.py", "tests/*.py", "tools/*.py",
                "docs/*.py", "docs/*.md", "docs/*.yaml",
                "README.md", "README_EN.md", "CONTRIBUTING.md",
                "config.example.yaml", ".github/workflows/*.yml")

# 真正决定「这次结果算不算数」的是**被测代码**。门禁脚本自己、文档、
# 测试文件被并行会话改过，不该把整轮结果判作废——实测踩过：跑测 3 分钟里
# 只有 tools/test_all.py 与 CONTRIBUTING.md 被改，产品代码一个字节没动，
# 却整轮作废，等于白跑。
CODE_GLOBS = ("webui.py", "main.py", "report.py", "wizard.py",
              "core/*.py", "crawlers/*.py")


def default_workers():
    return max(1, min(8, os.cpu_count() or 4))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _port_listening(port):
    s = socket.socket()
    s.settimeout(0.2)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    except OSError:
        return False
    finally:
        s.close()


def cleanup_demo_dbs(min_age=30.0, base_dir=None):
    """回收跑测遗留的按端口 demo 合成库（测试进程被 terminate，走不到
    _demo_main 的 finally）。正在监听的端口不碰——可能是别人的演示实例。"""
    removed = 0
    base = Path(base_dir) if base_dir else Path(tempfile.gettempdir())
    for p in base.glob("ticket_demo_prices_*.db"):
        try:
            port = int(p.stem.rsplit("_", 1)[1])
            if time.time() - p.stat().st_mtime < min_age:
                continue
        except (OSError, ValueError, IndexError):
            continue
        if _port_listening(port):
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def build_pytest_command(workers, junit=None, serial=False, extra=()):
    cmd = [sys.executable, "-m", "pytest"]
    if not serial:
        # loadfile：整文件一个 worker——module 级 fixture（demo 服务 +
        # 浏览器页）与跨类状态不被拆散（loadscope 会把方法按类再分组）
        cmd += ["-p", "xdist.plugin", "-n", str(int(workers)),
                "--dist", "loadfile"]
    cmd += ["tests/", "-q"]
    if junit is not None:
        cmd.append("--junitxml=%s" % junit)
    cmd += list(extra)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return cmd, env


def build_uitest_command(port, result=None):
    result = Path(result) if result else RUN_ROOT / "uitest_result.txt"
    env = dict(os.environ, UITEST_PORT=str(int(port)),
               UITEST_RESULT=str(result))
    return [sys.executable, "docs/uitest.py"], env, str(result)


UI_PROFILE = ROOT / "docs" / "uitest_profile.json"
UI_SHARD_OVERHEAD = 6.0   # 每片起 demo 服 + 浏览器 + 首页加载


def load_ui_profile(path=None):
    path = Path(path) if path else UI_PROFILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        secs = [float(s["seconds"]) for s in data["sections"]]
    except Exception:
        return None
    if not secs:
        return None
    data["weights"] = secs
    return data


def plan_contiguous(weights, n, overhead=UI_SHARD_OVERHEAD):
    """把连续段切成 n 组，最小化最大组耗时（DP）。返回下标组列表。"""
    m = len(weights)
    n = max(1, min(int(n), m))
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    cut = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for k in range(1, n + 1):
        for i in range(1, m + 1):
            s = 0.0
            for j in range(i - 1, -1, -1):
                s += weights[j]
                if j != 0 and dp[k - 1][j] == INF:
                    continue
                val = max(dp[k - 1][j], s + overhead)
                if val < dp[k][i]:
                    dp[k][i] = val
                    cut[k][i] = j
    groups = []
    i = m
    for k in range(n, 0, -1):
        j = cut[k][i]
        groups.append(list(range(j, i)))
        i = j
    groups.reverse()
    return groups


def plan_shards(profile, n):
    """优先用 profile 里已实测验证过的分组；否则按权重 DP，并把新段补进最轻组。

    兼容两种 profile 形状：老版 `{"weights": [...], "shards": [...]}` 与
    新版 `{"sections": [{"i":0,"seconds":..}, ...], "shards": ...}`。
    实测踩过：profile 由 `--profile-ui` 用新版格式写出，而这里只读 `weights`，
    直接 KeyError；门禁因此拿不到分组，UI 分片的覆盖面就成了未定义状态。
    """
    if "weights" in profile:
        secs = profile["weights"]
    else:
        rows = sorted(profile.get("sections") or [],
                      key=lambda s: int(s.get("i") or 0))
        secs = [float(s.get("seconds") or 0) for s in rows]
    shards = profile.get("shards")
    if shards and len(shards) == n:
        covered = sorted(i for g in shards for i in g)
        if covered == list(range(len(secs))):
            return [sorted(int(i) for i in g) for g in shards]
    groups = plan_contiguous(secs, n)
    covered = {i for g in groups for i in g}
    for i in range(len(secs)):
        if i in covered:
            continue
        k = min(range(len(groups)),
                key=lambda j: sum(secs[x] for x in groups[j]))
        groups[k].append(i)
    return [sorted(g) for g in groups]


def sections_arg(indices):
    """[0,1,2,5,9,10] → '0-2,5,9-10'（docs/uitest.py 的 UITEST_SECTIONS 语法）。"""
    parts = []
    idx = sorted(indices)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        parts.append(str(idx[i]) if i == j else "%d-%d" % (idx[i], idx[j]))
        i = j + 1
    return ",".join(parts)


def merge_ui_results(paths, total_checks=None):
    """按分片顺序合并 UI 结果：check 行原样、JS 错误聚合、总数对齐。

    `mismatch` 只在**覆盖面变少**时为真（r507）：r503 那次 569/666 是分片
    计划没算出来、有检查根本没跑——那才是空转。反过来，新增 UI 检查会让
    合并数 > profile 快照数（实测 r506 加了两条待判读数检查 → 668/666），
    那不是覆盖缺口，只是 profile 快照旧了，不该判失败。两个方向都打日志，
    但只有「少」才改变退出码。
    """
    lines, errs = [], []
    ok = bad = 0
    for p in paths:
        p = Path(p)
        if not p.exists():
            errs.append("缺少分片结果 %s" % p.name)
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for ln in text.splitlines():
            if ln.startswith(" … ") or ln.startswith(" ✓ ") or ln.startswith(" ✗ "):
                lines.append(ln)
                if ln.startswith(" ✓ "):
                    ok += 1
                elif ln.startswith(" ✗ "):
                    bad += 1
            elif ln.startswith("JS 错误:"):
                body = ln[len("JS 错误:"):].strip()
                if body and body != "无":
                    errs.append(body)
    lines.append("JS 错误: " + (" | ".join(errs[:3]) if errs else "无"))
    lines.append("=== %d/%d 通过 ===" % (ok, ok + bad))
    mismatch = None
    if total_checks is not None:
        want = int(total_checks)
        if (ok + bad) < want:
            mismatch = "short"
        elif (ok + bad) > want:
            mismatch = "grown"
    return "\n".join(lines) + "\n", ok, bad, errs, mismatch


def summarize_junit(path):
    """统计 JUnit 结果；失败项给「classname::name :: 消息首行」。"""
    out = {"passed": 0, "failed": 0, "skipped": 0, "total": 0,
           "time": 0.0, "failures": [], "modules": {}}
    root = ET.parse(str(path)).getroot()
    for suite in root.iter("testsuite"):
        try:
            out["time"] += float(suite.get("time") or 0.0)
        except ValueError:
            pass
    for case in root.iter("testcase"):
        out["total"] += 1
        cls = case.get("classname") or "?"
        fname = case.get("file")
        mod = Path(fname).name if fname else cls.split(".")[-1]
        try:
            dt = float(case.get("time") or 0.0)
        except ValueError:
            dt = 0.0
        out["modules"][mod] = out["modules"].get(mod, 0.0) + dt
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is not None:
            out["failed"] += 1
            msg = bad.get("message") or (bad.text or "")
            first = msg.strip().splitlines()[0] if msg.strip() else "(无消息)"
            out["failures"].append("%s::%s :: %s"
                                   % (cls, case.get("name"), first))
        elif case.find("skipped") is not None:
            out["skipped"] += 1
        else:
            out["passed"] += 1
    return out


def summarize_uitest(result_path):
    p = Path(result_path)
    if not p.exists():
        return {"passed": 0, "failed": 1, "total": 0}
    text = p.read_text(encoding="utf-8", errors="replace")
    ok = len(re.findall(r"^\s*✓", text, re.M))
    bad = len(re.findall(r"^\s*✗", text, re.M))
    return {"passed": ok, "failed": bad, "total": ok + bad}


def source_digest(globs=None):
    h = hashlib.md5()
    for pat in (globs or SOURCE_GLOBS):
        for p in sorted(ROOT.glob(pat)):
            if not p.is_file():
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            h.update(p.name.encode("utf-8"))
            h.update(data)
    return h.hexdigest()


def _spawn(cmd, env, log_path):
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                            stdout=log, stderr=subprocess.STDOUT, **kwargs)
    return proc, log


def _kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), 15)
    except Exception:
        pass


def _xdist_available():
    try:
        import xdist  # noqa: F401
        return True
    except Exception:
        return False


def _reexec_with_local_deps():
    env = dict(os.environ)
    sep = os.pathsep
    env["PYTHONPATH"] = str(DEPS_DIR) + (sep + env["PYTHONPATH"]
                                         if env.get("PYTHONPATH") else "")
    return subprocess.call([sys.executable, str(Path(__file__).resolve())]
                           + sys.argv[1:], cwd=str(ROOT), env=env)


def ensure_xdist(bootstrap):
    """确保 xdist 可用；本机系统 site-packages 无写权限时用本地目录引导。"""
    if _xdist_available():
        return 0
    if (DEPS_DIR / "xdist").is_dir():
        print("[deps] 使用 %s 里的 pytest-xdist" % DEPS_DIR)
        return _reexec_with_local_deps()
    if bootstrap:
        print("[deps] 安装 pytest-xdist 到 %s ..." % DEPS_DIR)
        DEPS_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, "-m", "pip", "install",
                            "--target", str(DEPS_DIR), "--no-deps",
                            "execnet", "pytest-xdist"],
                           cwd=str(ROOT))
        if r.returncode != 0:
            print("[deps] 安装失败；请手动 pip install pytest-xdist")
            return 4
        return _reexec_with_local_deps()
    print("[deps] 未检测到 pytest-xdist。安装：python -m pip install pytest-xdist\n"
          "       无管理员权限：python tools/test_all.py --bootstrap-deps")
    return 4


def mirror_ui_result(src, dst):
    """把 UI 结果回写到仓库内 docs/uitest_result.txt（受跟踪的常态产物）。

    Windows 上目标被别的进程短暂打开时 os.replace 会 PermissionError
    （并行跑 standalone uitest 的实测），重试后仍失败就退化为直写并告警：
    镜像文件是证据，不该让整轮门禁崩掉。"""
    dst = Path(dst)
    # 唯一临时名：两个会话同时跑门禁时共用 `.next` 会互相截断，
    # 落出「659 行检查 + 666 总数」这种半截文件（实测）
    nxt = dst.with_name(dst.name + ".%d.next" % os.getpid())
    try:
        shutil.copyfile(str(src), str(nxt))
    except OSError as exc:
        print("[warn] UI 结果拷贝失败：%s" % exc)
        return False
    for _ in range(10):
        try:
            os.replace(str(nxt), str(dst))
            return True
        except PermissionError:
            time.sleep(0.2)
        except OSError as exc:
            print("[warn] UI 结果回写失败：%s" % exc)
            break
    try:
        shutil.copyfile(str(src), str(dst))
        return True
    except OSError as exc:
        print("[warn] UI 结果回写 docs/ 失败：%s" % exc)
        return False


def update_ui_profile():
    """跑一轮完整 UI（UITEST_TRACE）重算分片权重，写 docs/uitest_profile.json。"""
    run_dir = RUN_ROOT / ("profile-%s" % time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    res = run_dir / "uitest_profile_result.txt"
    trace = run_dir / "uitest_trace.err"
    env = dict(os.environ, UITEST_TRACE="1", UITEST_PORT=str(free_port()),
               UITEST_RESULT=str(res))
    print("[profile] 完整 UI 采样中（约 6 分钟）...")
    with open(trace, "w", encoding="utf-8") as fh:
        rc = subprocess.call([sys.executable, "docs/uitest.py"], cwd=str(ROOT),
                             env=env, stdout=subprocess.DEVNULL, stderr=fh)
    end = time.time()
    rows = []
    for ln in trace.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\[t\] ([\d.]+) (.+)$", ln)
        if m:
            rows.append((float(m.group(1)), m.group(2)))
    if not rows:
        print("[profile] 没采到分段计时，放弃写 profile")
        return 1
    secs = []
    for i, (t, name) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else end
        secs.append({"i": i, "name": name,
                     "seconds": round(max(0.0, nxt - t), 1)})
    total_checks = 0
    if res.exists():
        total_checks = sum(
            1 for ln in res.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.startswith(" ✓ ") or ln.startswith(" ✗ "))
    data = {"generated": time.strftime("%Y-%m-%d"),
            "source": "UITEST_TRACE=1 python docs/uitest.py",
            "total_checks": total_checks, "sections": secs}
    old = load_ui_profile(UI_PROFILE)
    shards = old.get("shards") if old else None
    if shards:
        covered = sorted(int(i) for g in shards for i in g)
        if covered != list(range(len(secs))):
            shards = None
    if shards:
        data["shards"] = shards
    UI_PROFILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8", newline="\n")
    print("[profile] %d 段 / %d 项 → %s" % (len(secs), total_checks, UI_PROFILE))
    return 0 if rc == 0 else 1


def _fmt(sec):
    return "%.1fs" % sec


def main():
    # 摘要行里会带用例自己写的中文/符号（实测算例断言文本含 ❌ 时
    # UnicodeEncodeError 在 print 处崩掉，**整轮结果作废**：退出码
    # 既不是 0 也不是 1，跑测方只看到一段 traceback）。输出只是给人看的，
    # 容错替换即可，判定逻辑不受影响。
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="全量验证并发编排")
    ap.add_argument("--workers", type=int, default=0,
                    help="pytest worker 数（默认 min(8, CPU)）")
    ap.add_argument("--serial", action="store_true",
                    help="串行口径（与 CONTRIBUTING/CI 同款的 pytest 命令）")
    ap.add_argument("--no-ui", action="store_true", help="不跑 docs/uitest.py")
    ap.add_argument("--ui-shards", type=int, default=0,
                    help="UI 自检分片数（0=自动：有 profile 用 4 片）")
    ap.add_argument("--no-compile", action="store_true", help="跳过语法检查")
    ap.add_argument("--no-pin", action="store_true",
                    help="跑测前后不比对源码哈希")
    ap.add_argument("--bootstrap-deps", action="store_true",
                    help="缺 xdist 时安装到 _scratch/testdeps")
    ap.add_argument("--pytest-args", default="",
                    help="附加 pytest 参数（引号内整体传入）")
    ap.add_argument("--profile-ui", action="store_true",
                    help="重算 UI 分片权重（完整跑一轮）后退出")
    args = ap.parse_args()

    if args.profile_ui:
        return update_ui_profile()

    workers = args.workers or default_workers()
    if not args.serial:
        code = ensure_xdist(args.bootstrap_deps)
        if code:
            return code

    run_dir = RUN_ROOT / ("%s-%d" % (time.strftime("%Y%m%d-%H%M%S"),
                                     os.getpid()))
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in (run_dir / "pytest.xml", run_dir / "uitest_result.txt"):
        try:
            stale.unlink()
        except OSError:
            pass

    cleanup_demo_dbs(min_age=300)   # 上次崩溃/中断留下的库，先回收
    digest0 = None if args.no_pin else source_digest()
    code0 = None if args.no_pin else source_digest(CODE_GLOBS)
    t0 = time.time()
    psum = None

    if not args.no_compile:
        ct0 = time.time()
        r = subprocess.run([sys.executable, "-m", "py_compile"]
                           + COMPILE_TARGETS, cwd=str(ROOT),
                           capture_output=True, text=True, errors="replace")
        compile_ok = (r.returncode == 0)
        compile_dur = time.time() - ct0
        (run_dir / "compile.log").write_text(
            (r.stdout or "") + (r.stderr or ""), encoding="utf-8")
        if not compile_ok:
            print("[FAIL] 语法检查失败：%s" % (run_dir / "compile.log"))
            return 2
    else:
        compile_ok, compile_dur = True, 0.0

    extra = args.pytest_args.split() if args.pytest_args else []
    pcmd, penv = build_pytest_command(
        workers, junit=run_dir / "pytest.xml", serial=args.serial, extra=extra)

    prof = None
    ui_plan = []      # [(段下标列表 or None, 结果文件)]
    if not args.no_ui:
        prof = load_ui_profile()
        n_ui = 1 if args.serial else args.ui_shards
        if n_ui <= 0:
            n_ui = len(prof.get("shards") or []) if prof else 1
        if prof and n_ui > 1:
            groups = plan_shards(prof, n_ui)
            ui_plan = [(g, run_dir / ("uitest_%d.txt" % k))
                       for k, g in enumerate(groups)]
        else:
            ui_plan = [(None, run_dir / "uitest_result.txt")]

    print("[run] pytest %s  worker=%s"
          % ("(serial)" if args.serial else "(xdist loadfile)", workers))
    if ui_plan:
        print("[run] uitest %s 同时进行（结果先落临时文件，跑完合并回写）"
              % ("%d 片" % len(ui_plan) if len(ui_plan) > 1 else "单进程"))

    pproc = None
    plog = None
    uiprocs, ulogs = [], []
    pdur = udur = 0.0
    prc = None
    ui_rcs = []
    ut_start = None
    try:
        pt0 = time.time()
        pproc, plog = _spawn(pcmd, penv, run_dir / "pytest.log")
        if ui_plan:
            ut_start = time.time()
            for k, (indices, res) in enumerate(ui_plan):
                ucmd, uenv, _ = build_uitest_command(free_port(), res)
                if indices is not None:
                    uenv["UITEST_SECTIONS"] = sections_arg(indices)
                up, ul = _spawn(ucmd, uenv,
                                run_dir / ("uitest_%d.log" % k))
                uiprocs.append(up)
                ulogs.append(ul)
        prc = pproc.wait()
        pdur = time.time() - pt0
        ui_rcs = [p.wait() for p in uiprocs]
        # 分片拿不到前序段的预热，空态/未完成渲染偶发；失败片单跑重试一次
        for k, rc in enumerate(ui_rcs):
            if rc == 0:
                continue
            idx, res = ui_plan[k]
            first = Path(res)
            try:
                shutil.copyfile(str(first),
                                str(first.with_name(first.stem + ".first.txt")))
            except OSError:
                pass
            cmd, env, _ = build_uitest_command(free_port(), res)
            if idx is not None:
                env["UITEST_SECTIONS"] = sections_arg(idx)
            p2, l2 = _spawn(cmd, env, run_dir / ("uitest_%d.retry.log" % k))
            print("[retry] UI 分片 %d 首次未过，单独重跑一次（首跑结果已留档）" % k)
            ui_rcs[k] = p2.wait()
            l2.close()
        udur = time.time() - ut_start if ut_start else 0.0
    except KeyboardInterrupt:
        print("\n[abort] 收到中断，回收泳道 ...")
        _kill_tree(pproc)
        for p in uiprocs:
            _kill_tree(p)
        return 130
    finally:
        for fh in [plog] + ulogs:
            try:
                if fh is not None:
                    fh.close()
            except Exception:
                pass

    code = 0
    try:
        psum = summarize_junit(run_dir / "pytest.xml")
    except Exception as exc:
        print("[warn] 解析 pytest.xml 失败：%s" % exc)
    if prc != 0:
        code = 1

    swept = cleanup_demo_dbs()

    ui = None
    if ui_plan:
        urc = 0 if all(rc == 0 for rc in ui_rcs) else 1
        merged = None
        if len(ui_plan) > 1:
            total_checks = prof["total_checks"] if prof else None
            merged_text, ok, bad, errs, mismatch = merge_ui_results(
                [res for _, res in ui_plan], total_checks)
            merged = run_dir / "uitest_merged.txt"
            merged.write_text(merged_text, encoding="utf-8", newline="\n")
            ui = {"passed": ok, "failed": bad, "total": ok + bad}
            if mismatch == "short":
                print("[warn] UI 分片合计 %d 项，少于 profile 的 %d 项"
                      "（有检查没跑到，覆盖面缺口）" % (ok + bad, total_checks))
                urc = 1
            elif mismatch == "grown":
                print("[info] UI 检查已增至 %d 项（profile 快照为 %d 项）；"
                      "覆盖变多不是缺口，结果有效"
                      % (ok + bad, total_checks))
        else:
            ui = summarize_uitest(ui_plan[0][1])
        if urc != 0:
            code = 1
        src = merged if merged is not None else ui_plan[0][1]
        if Path(src).exists():
            mirror_ui_result(src, ROOT / "docs" / "uitest_result.txt")

    # 跑测期间源码被改写（并行会话）→ 分两级看待：
    #   被测代码变了 → 本次结果作废（结论对不上当前代码，必须重跑）；
    #   只有门禁脚本/文档/测试文件变了 → 只提示，不废——被测代码一个字节
    #   没动，结论依然成立。（实测踩过：3 分钟里只改了 tools/test_all.py
    #   与 CONTRIBUTING.md，整轮却被判作废，等于白跑半小时。）
    if code0 is not None and source_digest(CODE_GLOBS) != code0:
        print("[WARN] 跑测期间**产品代码**被改写，本次结果作废（--no-pin 可跳过比对）")
        code = 3
    elif digest0 is not None and source_digest() != digest0:
        print("[info] 跑测期间门禁脚本/文档/测试文件有改动；被测代码未变，"
              "结果仍然有效")

    total = time.time() - t0
    print("\n== 全量验证摘要 ==")
    print("语法检查            %s  %s"
          % ("ok" if compile_ok else "FAIL",
             _fmt(compile_dur) if not args.no_compile else "skip"))
    if psum is not None:
        print("pytest %-6s     %s  %s  passed %d / skipped %d / failed %d"
              % ("serial" if args.serial else "%dw" % workers,
                 "ok" if prc == 0 else "FAIL", _fmt(pdur),
                 psum["passed"], psum["skipped"], psum["failed"]))
        top = sorted(psum["modules"].items(), key=lambda kv: -kv[1])[:5]
        if top:
            print("最慢文件：" + "  ".join("%s %s" % (k, _fmt(v))
                                          for k, v in top))
        for line in psum["failures"][:20]:
            print("  FAILED  " + line)
    if ui is not None:
        print("uitest %-2s        %s  %s  %d/%d"
              % ("%d片" % len(ui_plan) if len(ui_plan) > 1 else "",
                 "ok" if urc == 0 else "FAIL", _fmt(udur),
                 ui["passed"], ui["total"]))
    if swept:
        print("演示库回收          %d 个" % swept)
    print("总墙钟              %s" % _fmt(total))
    print("日志                %s" % run_dir)
    return code


if __name__ == "__main__":
    sys.exit(main())
