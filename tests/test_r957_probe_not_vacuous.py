# -*- coding: utf-8 -*-
"""r957：探针恒假 = **假阴性自检**，连错 55 轮没人发现；判暴露面要按攻击者权限判。

## 一、这条探针一直是死的

`_exact_path_exists` 在 2026-11-04 之前长这样：

```python
_call(dev, "shell", "sh", "-c", "test -e %s && echo TM_YES || echo TM_NO" % _q(p))
```

adb 会**把命令行按空格拆开**送进设备 shell，于是设备真正执行的是
`sh -c test` —— 内层 `test` 拿不到参数 → **恒假** → 外层 `|| echo TM_NO` 永远命中。
**任何路径都判"不存在"。**

自测（`/system/bin/sh` 必然存在）：

```
修前： /system/bin/sh exists=False      ← 铁证
修后： /system/bin/sh exists=True
       /system/bin/su exists=False      （真的没有 su）
       /data/adb/magisk exists=True     ← 之前 55 轮从来没报过
```

也就是说这一整天的 `root 痕迹: []`、`自检 100 分（剩余：无）`
**全是没有验证过的断言**。这类东西比报错更糟：报错会打扰人，
假阴性让人**放心**。

同一成因还解释了我此前记错的一件事：`ls -ld /data/adb` 会回一整屏根目录
条目（acct/adb_keys/apex/bin…），当时记成"`ls` 把目录展开了"，
其实是被拆成 `sh -c ls` + 位置参数，`ls` **根本没收到路径**。
所以真正结论是：**探测命令里不许出现 shell 元字符**
（`-c`、`&&`、`||`、`|`、`>`、引号）。最终形态 = `ls -ld <单条路径>`，
参数各自独立传，怎么拆都不变语义。

## 二、存在 ≠ App 看得见

修好探针后第一件事是把 `/data/adb/magisk` 报成 root 痕迹。差点据此把
resetprop 的工位删掉 —— 然后发现判据错了：**自检在 `adb root`（uid=0）下跑**，
而 App 是 untrusted_app：

| 路径 | 父目录权限 | App 能否 stat |
|---|---|---|
| `/data/adb/magisk` | `/data/adb` = `drwx------` 0700 | **不能 traverse → 看不见** |
| `/data/local/tmp/magisk_bin` | `/data/local/tmp` = `drwxrwx--x` 0771 | others 有 x → **看得见** |
| `/mnt/shared` | `drwxrwxr-x` | **看得见 → 真泄漏** |

**判暴露面要按攻击者的权限判，不是按 root 的权限判。**
于是 `app_can_see()`：父链每一级都要对 others 开 `x`；
拿不到权限位时**保守返回 True**（宁可多报，不能把真泄漏判没）。
看不见的进 `hidden_from_app`（如实列出，但**不扣风险分**）。

`stealth.detect()` 与 `fingerprint.audit()` 用同一判据（两处规则不一致
必然漂移）。

修好后真实自检：

```
detect score = 84  root(App可见)=[]  hidden_from_app=['fs:/data/adb/magisk']
             emulator=[nemud props 写回, shared:/mnt/shared（需在 MuMu 设置里关掉）]
audit  score = 88  = ceiling 88（只剩不可清的 ABI 两条）
```

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r957_probe_not_vacuous.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402


class _Dev:
    """假设备：`ls -ld <path>` 按字典回放；其它命令返回空。"""

    def __init__(self, existing, modes=None):
        self.existing = set(existing)
        self.modes = dict(modes or {})
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        if toks[:3] == ["shell", "ls", "-ld"]:
            out = []
            for p in toks[3:]:
                if p in self.existing:
                    mode = self.modes.get(p, "drwxr-xr-x")
                    out.append("%s 2 root root 4096 2026-11-04 12:00 %s"
                               % (mode, p))
            return "\n".join(out)
        if toks[:3] == ["shell", "ls", "-d"]:
            p = toks[3] if len(toks) > 3 else ""
            return p if p in self.existing else ""
        if cmd.strip() == "shell getprop":
            return "[ro.product.model]: [V2405A]"
        if cmd.startswith("shell getprop "):
            return ""
        return ""


# ---------------------------------------------------------------------------
# 1. 探针不许恒假：存在的路径必须返回 True
# ---------------------------------------------------------------------------
def test_probe_true_for_existing_path():
    d = _Dev({"/system/bin/sh"})
    assert fp._exact_path_exists(d, "/system/bin/sh") is True, \
        "存在的文件判 False = 恒假探针（曾错 55 轮，见 docstring）"


def test_probe_false_for_missing_path():
    d = _Dev({"/system/bin/sh"})
    assert fp._exact_path_exists(d, "/system/bin/su") is False


def test_probe_requires_exact_match_not_non_empty():
    """存在性必须**精确等于路径**，不能"有输出就算存在"。

    为什么单独钉这条（2026-11-04 我自己踩的）：实验脚本里我用了
    `stdout+stderr` 合并的读法去判"文件删了没"，
    `ls` 对**不存在**的文件会往 stderr 打
    `ls: /x: No such file or directory` —— 非空 → 被我读成"还在"，
    于是"已清理"这件事被判成"未清理"（方向是保守的，但同一写法反过来
    也能把"还在"判成"已删"，那就危险了）。
    共享探针只取 stdout 且**整行比对路径**，所以不受污染。
    """
    class _Err:
        def _sh(self, *a, timeout=None):
            # 模拟把错误信息当输出回流（stderr 污染）
            return "ls: /system/bin/su: No such file or directory"

    assert fp._exact_path_exists(_Err(), "/system/bin/su") is False, \
        "非空即算存在 → 报错文本会被当成文件存在"

    class _Ok:
        def _sh(self, *a, timeout=None):
            return "/system/bin/sh"

    assert fp._exact_path_exists(_Ok(), "/system/bin/sh") is True


def test_probe_uses_no_shell_metacharacters():
    """探测命令必须是独立 argv，不能包 `sh -c`。

    adb 会把命令行按空格拆开送进设备 shell，`sh -c "a && b"` 会被拆成
    `sh -c a` + 外层 `&& b`，内层永远拿不到参数 → 结果恒假。
    """
    src = io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                  encoding="utf-8").read()
    i = src.find("def _exact_path_exists")
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    # 只看函数体（切掉 docstring），否则注释里的反面示例会误报
    code = body.split('"""')[2] if body.count('"""') >= 2 else body
    assert '"sh", "-c"' not in code, "探针还在用 sh -c（会被拆参数 → 恒假）"
    assert "test -e" not in code, "探针还在用 test -e（同样会被拆参数）"
    assert '"ls", "-d"' in code or '"ls", "-ld"' in code, \
        "探针应改用 ls -d 单条路径"


# ---------------------------------------------------------------------------
# 2. 存在 ≠ App 看得见
# ---------------------------------------------------------------------------
def test_app_cannot_see_under_0700_parent():
    """`/data/adb` 是 0700 → App 无法 traverse → 里面的东西不算暴露面。"""
    d = _Dev({"/data", "/data/adb", "/data/adb/magisk"},
             modes={"/data": "drwxrwx--x", "/data/adb": "drwx------"})
    assert fp._exact_path_exists(d, "/data/adb/magisk") is True
    assert fp.app_can_see(d, "/data/adb/magisk") is False, \
        "父目录 0700 时不该算 App 可见（按 root 权限判会造成假警报）"


def test_app_can_see_under_world_traversable_parent():
    d = _Dev({"/data", "/data/local", "/data/local/tmp",
              "/data/local/tmp/magisk_bin"},
             modes={"/data": "drwxrwx--x", "/data/local": "drwxr-x--x",
                    "/data/local/tmp": "drwxrwx--x"})
    assert fp.app_can_see(d, "/data/local/tmp/magisk_bin") is True


def test_app_can_see_is_conservative_when_unknown():
    """拿不到权限位时宁可判"看得见"，不能把真泄漏判没。"""
    d = _Dev({"/x/y"})          # 没有父目录 /x 的信息
    assert fp.app_can_see(d, "/x/y") is True


def test_visibility_cache_avoids_repeat_adb():
    """同一次 detect 里多条路径共享权限位缓存（每轮都跑，不能白烧 adb）。"""
    d = _Dev({"/data", "/data/adb", "/data/adb/magisk", "/data/adb/ksu"},
             modes={"/data": "drwxrwx--x", "/data/adb": "drwx------"})
    cache = {}
    fp.app_can_see(d, "/data/adb/magisk", cache)
    n1 = len([c for c in d.calls if "ls -ld" in c])
    fp.app_can_see(d, "/data/adb/ksu", cache)
    n2 = len([c for c in d.calls if "ls -ld" in c])
    assert n2 == n1, "父目录权限位没复用，每条路径都重查一次 adb"


# ---------------------------------------------------------------------------
# 3. 两处必须同一判据（否则报告自相矛盾）
# ---------------------------------------------------------------------------
def test_both_detectors_use_app_visibility():
    base = os.path.join(ROOT, "core", "android")
    st = io.open(os.path.join(base, "stealth.py"), encoding="utf-8").read()
    fpr = io.open(os.path.join(base, "fingerprint.py"), encoding="utf-8").read()
    assert "app_can_see(dev, p" in st, "stealth 没按 App 权限判"
    assert "app_can_see(dev, p" in fpr, "audit 没按 App 权限判"
    assert '"hidden_from_app"' in st
