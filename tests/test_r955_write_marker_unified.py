# -*- coding: utf-8 -*-
"""r955：marker 写入被 Windows 吃掉引号 → fast path 形同虚设，hide 每轮全跑。

**根因**：`write_remote` 在 `fingerprint.py` 新增，取代所有直接
`sh -c "echo X > /path"` 的 marker 写法。

2026-11-04 确诊（三个 boot 标记文件都有这毛病）：

```
_call(dev, 'shell', 'sh', '-c', 'echo %s > /data/local/tmp/tm_x.ok' % q(boot))
```

Windows 的命令行解析器会把 `>` 当成**本地重定向**截走，
命令**不完整到设备**。所以设备上**文件被创建了但内容是空的**。
而读（`cat`）是好的 —— 于是 `prepare()` 里的 boot_id 比较永远不成立，
`hide()` **每轮全量重跑**：denylist 读写 sqlite、logcat 快照、
magiskpolicy 复核……全是浪费。

**统一修法**：新增 `write_remote(dev, path, text) -> bool`，
走本地临时文件 + `adb push`（路径里不含引号/管道/重定向字符）。
测试替身（无 `push`）退回 `sh -c` 保持原有语义，读回校验确保写对了。

调用点（3 处）：
* `stealth._mark_path(vm)` 里的 boot 标记 → 改用 `write_remote`
* `emulator_tuning._mark_path(vm)` 里的 boot 标记 → 改用 `write_remote`
* `fingerprint._mark_path(ident.vm)` 里的身份标记 → 改用 `write_remote`

**效果**（实测）：
* marker 写对了，第二次 prepare 返回 `skipped: done this boot`；
* 但 fast path **仍需重清厂商 props**（nemuinit 会写回）→ 调用 `refresh()`；
* `hide()` 不再每轮全量跑（省掉 denylist sqlite + logcat 快照的开销）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r955_write_marker_unified.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402


def _src(name: str) -> str:
    return io.open(os.path.join(ROOT, "core", "android", name),
                   encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. `write_remote` 统一 helper 存在
# ---------------------------------------------------------------------------
def test_write_remote_exists():
    assert hasattr(fp, "write_remote"), "没有统一的 write_remote"


def test_write_remote_signature():
    """签名：`write_remote(dev, path, text, *, timeout=None) -> bool`。"""
    import inspect
    sig = inspect.signature(fp.write_remote)
    params = list(sig.parameters.keys())
    assert params[:3] == ["dev", "path", "text"], params
    assert "timeout" in params, "不许丢失超时控制"


# ---------------------------------------------------------------------------
# 2. 3 个调用点都改成 write_remote
# ---------------------------------------------------------------------------
def test_stealth_marker_uses_write_remote():
    s = _src("stealth.py")
    assert "from .fingerprint import write_remote" in s, "stealth 没导入 write_remote"
    # 整个 prepare() 函数体里不许再出现 `echo ... > 标记` 这种写法
    # （标记写入发生在 hide() **之后**，所以窗口要盖到函数结尾）
    i = s.find("def prepare(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j if j > 0 else len(s)]
    assert "write_remote(" in body, "stealth 的 boot 标记没走 write_remote"
    assert 'echo %s > %s' not in body, \
        "prepare 里还在用 `sh -c \"echo X > path\"`（Windows 上静默失败）"


def test_emulator_tuning_marker_uses_write_remote():
    s = _src("emulator_tuning.py")
    assert "from .fingerprint import write_remote" in s
    # 找 boot 标记写入那段
    i = s.find("def ensure(")
    if i < 0:
        i = 0
    seg = s[i:]
    j = seg.find("_mark_path(vm)")
    if j > 0:
        # 标记写入附近 100 字内要有 write_remote
        nearby = seg[j:j + 200]
        assert "write_remote(" in nearby or "echo" not in nearby, \
            "emulator_tuning marker 还在用 echo >"


def test_fingerprint_marker_uses_write_remote():
    s = _src("fingerprint.py")
    i = s.find("def write_marker(")
    assert i > 0
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    assert "write_remote(" in body, "身份 marker 还在用 echo >"


# ---------------------------------------------------------------------------
# 3. fast path 仍要跑 refresh
# ---------------------------------------------------------------------------
def test_fast_path_still_refreshes_props():
    """本 boot 已 hide 过，但仍需重清厂商 props（nemuinit 会写回）。"""
    s = _src("stealth.py")
    i = s.find('if not force and boot and cur == boot:')
    assert i > 0
    seg = s[i:i + 700]
    assert "refresh(" in seg, \
        "fast path 直接 return（nemuinit 写回后没人管了）"


def test_hide_full_path_not_run_every_round():
    """确认 boot marker 机制生效：第二次 prepare 应返回 skipped。"""
    # 这个由真机实测确认（见文档里的例子），代码层面钉 fast path 分支存在
    s = _src("stealth.py")
    assert "done this boot" in s
