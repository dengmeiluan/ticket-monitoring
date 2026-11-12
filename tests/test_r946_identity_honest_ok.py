# -*- coding: utf-8 -*-
"""r946：身份层假报"已应用" —— 设备上一条都没改，日志却说生效了。

2026-11-04 实测（MuMu / Android 15）：

```
[android] 身份已应用 id-3776d688-00：4 条生效 / 24 条失败，自检 88 分
```

而设备上：

```
getprop ro.product.model  →  SM-A5260      ← 目标机型根本没写进去
```

`ensure()` 原来**无条件** `rep["ok"] = True`，于是"身份已应用"这句
完全不能作为判断依据。这是本仓库第 4 次踩同类（前三次：`setprop` 返回 0
但值不变、`cleared` 虚报 42 条、`as_root` 引号丢失）。

### 为什么改不动

实测探明：`magisk resetprop` 在本机**只能写非 `ro.*`**：

| 键 | 结果 |
|---|---|
| `persist.test.abc` | ✅ OK |
| `ro.nemu`（MuMu 非标准键） | ✅ 能清（意外收获） |
| `ro.product.model` / `ro.debuggable` | ❌ `set prop error` |

根因：`ps -A | grep magiskd` = **0**、`/data/adb` 不存在 ——
我们只提取了 `magisk` 二进制，**没有 magiskd 守护进程**。
`resetprop` 退化成普通 `setprop`，标准 `ro.*` 被 property_service 保护。

要真正改机型必须**完整安装 Magisk**（patch boot.img 改 ramdisk）。

### 修法

`ensure()` 的 `ok` 改成看"真的写进去了几条"：

* 有 `verified`（写前≠值 且 写后==目标）→ ok
* 只有 `android_id`（走 `settings put`，真生效）→ ok，但日志要**分开说**
* 全 mismatch/失败 → `ok=False` + `why` 点明"需完整 Magisk"

日志措辞也改了，不再笼统说"身份已应用"：

```
[android] 身份写入 id-004ac104-00：android_id 已改、15 条 ro.* 未生效（需完整 Magisk）；自检 88 分
```

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r946_identity_honest_ok.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src() -> str:
    return io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                   encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. ok 判定必须看 verified，不能无条件 True
# ---------------------------------------------------------------------------
def test_ok_not_unconditional_true():
    """`ensure()` 里不许再有裸的 `rep["ok"] = True`。"""
    s = _src()
    i = s.find('rep["audit"]["identity_id"] = ident.ident_id')
    assert i > 0
    seg = s[i:i + 2600]
    assert 'rep["ok"] = bool(_verified)' in seg, \
        "ok 判定没看 verified（会假报已应用）"
    assert 'rep["ok"] = True' not in seg, "还有无条件 True"


def test_ok_reports_why_when_nothing_written():
    s = _src()
    assert 'rep["why"]' in s
    assert "完整 Magisk" in s, "没有说明根治手段"


# ---------------------------------------------------------------------------
# 2. 日志措辞必须区分 android_id 与 ro.*
# ---------------------------------------------------------------------------
def test_log_distinguishes_android_id_from_ro():
    s = _src()
    i = s.find("身份写入")
    assert i > 0, "找不到新的日志措辞"
    seg = s[max(0, i - 4000):i + 400]
    assert "android_id 已改" in seg, "日志没单独说 android_id"
    assert "未生效" in seg, "日志没如实说 ro.* 未生效"
    # 旧的笼统措辞不许出现在 **logger 调用**里（注释里提到它是在解释为什么改）
    for ln in seg.splitlines():
        if 'logger.' in ln:
            assert "身份已应用" not in ln, "logger 里仍有笼统措辞：%s" % ln.strip()


# ---------------------------------------------------------------------------
# 3. as_root 走 base64（引号不再丢）
# ---------------------------------------------------------------------------
def test_as_root_uses_base64():
    s = _src()
    i = s.find("def as_root(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    # 最终方案是 **本地临时文件 + adb push + 执行**（base64 只是中间尝试，
    # 它没解决"`>` 被 Windows 本地 shell 吃掉"的问题）。
    assert "mkstemp" in body, "as_root 没走临时文件"
    assert "push" in body, "as_root 没走 adb push"
    # 不许再把 script 直接塞进 sh -c / su -c
    assert '"shell", "sh", "-c", script' not in body, \
        "还有把脚本直接塞进 sh -c 的写法"
    assert '"shell", "su", "-c", script' not in body, \
        "还有把脚本直接塞进 su -c 的写法"
    # push 的返回码必须检查（不许无条件认定成功）
    assert "pushed = bool(dev.push" in body or "returncode" in body, \
        "push 没检查返回码（会假成功）"


# ---------------------------------------------------------------------------
# 4. _is_emulator 不能因为 props 被清就失效
# ---------------------------------------------------------------------------
def test_is_emulator_has_props_independent_fallback():
    """`stealth.hide()` 会用 resetprop --delete 把 nemu 键**连键带值删掉**，
    于是 props 上完全看不出是模拟器——必须有 props 之外的判据。"""
    s = _src()
    i = s.find("def _is_emulator(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    # 兜底通过**显式参数** vendor_hint 传入（保持 _is_emulator 是纯函数，
    # 否则装了 MuMu 的机器上跑测试会恒为 True）。
    assert "vendor_hint" in body, "没有 props 之外的兜底判据"
    assert "vendor_hint and p" in body, "兜底没按 vendor_hint 生效"
    # 而 ensure() 必须真的去问 MuMu 并把结果传进来
    s2 = _src()
    assert "_vendor.read(vm_index=vm)" in s2, "ensure 没传 vendor_hint"
