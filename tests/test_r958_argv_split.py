# -*- coding: utf-8 -*-
"""r958：`adb shell` 三段 argv（`sh -c "<脚本>"`）= 恒假探针 / 静默空写。

## 机制（同日实测三种写法对照）

```
_sh("shell", "sh", "-c", "printf 'x' >> f && echo TM_OK")
    → adb 把 argv 用空格拼成一条命令交给**设备 shell 重新解析**：
      sh -c printf 'x' >> f && echo TM_OK
      内层只拿到 `sh -c printf`（payload 变位置参数被丢）
    → 实测：报 `printf: Needs 1 argument`，**文件 0 字节**
_sh("shell", "printf 'x' >> f && echo TM_OK")      # 单个 argv
    → 实测：TM_OK，内容落地                    ← 正确形态
```

同一条规律杀掉了三类东西：
* **存在性探针恒假**：`sh -c "test -e X && echo A || echo B"` → 内层 `sh -c test`
  恒假 → 任何路径都判"不存在" → `root 痕迹: []` 与"自检 100 分"55 轮无效；
* **能力探测假阴性**：remount 探针里 `-o remount,rw /` 被丢掉，
  于是**可写系统**被报成"块设备只读（remount 被拒）"，
  把我引向"全局改不动 → 得装 Magisk"的整条弯路；
* **ANR 诊断恒空**：`f=$(ls -t /data/anr/…)` 的 `$f` 被外层解析成空 →
  "渠道为什么卡住"这条线索从来没报出来过。

## 收口

`device.run_script()` + `fingerprint.sh_script()` 是**唯一**执行带元字符脚本的入口
（整条脚本单个 argv）；`write_remote` 也统一走它。本测试整文件扫描，
命中即失败（docstring 里的反例已改写成散文，避免误报）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r958_argv_split.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 三段 argv 的调用形态：("shell", "sh", "-c", ...) 或 ('shell','sh','-c',...)
BAD_FORMS = (
    '"shell", "sh", "-c"',
    "'shell', 'sh', '-c'",
    '"shell", "sh", "-c"',
    "dev._sh(\"shell\", \"sh\", \"-c\"",
)
SCAN_DIRS = ("core", "crawlers", "scripts")


def _py_files():
    for base in SCAN_DIRS:
        d0 = os.path.join(ROOT, base)
        for cur, dirs, files in os.walk(d0):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in files:
                if fn.endswith(".py"):
                    yield os.path.join(cur, fn)


# ---------------------------------------------------------------------------
# 1. 全仓扫描：不许再有"三段 argv 交给设备 shell 重解析"的调用
# ---------------------------------------------------------------------------
def test_no_three_argv_sh_c_anywhere():
    bad = []
    for path in _py_files():
        s = io.open(path, encoding="utf-8").read()
        for n, line in enumerate(s.splitlines(), 1):
            code = line.split("#", 1)[0]
            for form in BAD_FORMS:
                if form in code:
                    bad.append("%s:%d  %s" % (
                        os.path.relpath(path, ROOT), n, line.strip()[:80]))
    assert not bad, (
        "adb 三段 argv 会被设备 shell 重新解析（探针恒假/写入落空）。\n"
        "请改用 device.run_script / fingerprint.sh_script：\n  "
        + "\n  ".join(bad))


def test_single_argv_entry_points_exist():
    from core.android.device import AdbDevice
    from core.android import fingerprint as fp
    assert hasattr(AdbDevice, "run_script"), "缺 AdbDevice.run_script"
    assert hasattr(fp, "sh_script"), "缺 fingerprint.sh_script"


# ---------------------------------------------------------------------------
# 2. run_script 真的把脚本作为**一个** argv 传下去
# ---------------------------------------------------------------------------
class _Rec:
    def __init__(self):
        self.calls = []

    def _sh(self, *a, timeout=None):
        self.calls.append(list(a))
        return "OUT"


def test_run_script_passes_script_as_one_arg():
    from core.android.device import AdbDevice
    d = AdbDevice.__new__(AdbDevice)          # 不跑 __init__（不需要真 adb）
    rec = _Rec()
    d._sh = rec._sh
    script = "f=$(ls -t /data/anr | head -1); [ -n \"$f\" ] && head -4 x/$f"
    got = d.run_script(script)
    assert got == "OUT"
    assert rec.calls == [["shell", script]], rec.calls   # 恰好两段，无 sh -c


def test_write_remote_still_verifies_by_readback():
    """写文件必须读回比对（`>` 落空时不能假报成功）。"""
    from core.android import fingerprint as fp

    class _W:
        def __init__(self):
            self.stored = None

        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            if cmd.startswith("shell cat"):
                return self.stored or ""
            if "echo" in cmd and ">" in cmd:
                # 模拟被本地/设备 shell 吃掉重定向：什么都没写
                return ""
            return ""

    w = _W()
    assert fp.write_remote(w, "/data/local/tmp/x.ok", "boot-1") is False, \
        "写入没落地却返回 True（假成功）"


# ---------------------------------------------------------------------------
# 3. 探针不许恒假：存在的文件必须判存在
# ---------------------------------------------------------------------------
def test_probe_detects_existing_file():
    from core.android import fingerprint as fp

    class _P:
        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            if cmd.startswith("shell ls -ld"):
                p = cmd.split()[-1]
                if p == "/system":
                    return "drwxr-xr-x 2 root root 4096 x /system"
                if p == "/system/bin":
                    return "drwxr-xr-x 2 root root 4096 x /system/bin"
                return ""
            if cmd.startswith("shell ls -d"):
                p = cmd.split()[-1]
                return p if p == "/system/bin/sh" else ""
            return ""

    assert fp._exact_path_exists(_P(), "/system/bin/sh") is True, \
        "存在的文件判不出存在 = 探针恒假（本仓栽过 55 轮的那条）"
    assert fp._exact_path_exists(_P(), "/system/bin/su") is False
