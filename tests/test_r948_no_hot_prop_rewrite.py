# -*- coding: utf-8 -*-
"""r948：运行中改 `ro.product.device` / `ro.build.*` 会把设备搞挂。

2026-11-04 连踩两次，两次都是**同一个成因**：

1. 第一次：`apply_props` 无差别 `resetprop --delete`，把 **`ro.adb.secure`**
   删了 → adbd 不再校验 adb key → `error: closed` → 设备 **offline**；
2. 第二次：改 `ro.product.device` / `ro.product.board` / `ro.build.id`
   / `ro.build.fingerprint`（值都对、也没删关键键）→ **还是 offline**。

第二次才是关键认知：**system_server 等进程在运行中会读这些字段**，
中途改掉会让它重启，连带 adbd 掉线。**"值是正确的"不等于"可以热改"。**

所以这一层的规则必须是：

* **能安全改的**：MuMu 没提供官方键、且没人运行时依赖的键
  —— `ro.nemu`、`ro.build.version.nemux`、`nemud.*`（实测把模拟器标记
  清零，携程从 `50003 限制登录` 变成「请完成拼图验证」）；
* **只能用官方键在 boot 时注入的**：`ro.product.*`、`ro.hardware`、
  `ro.board.platform`、`ro.build.*` —— 也就是 MuMuManager 的
  `phone_brand` / `phone_miit` / `phone_model`（实测有效且稳定：重启后
  brand/model/device/board/name 全部一致，`ro.nemu` 也保持空）；
* **绝对不能 delete 的**：`ro.adb.secure` 那一类（见 `_NO_DELETE`）。

`ensure()` 里加一道闸：非"安全白名单"的键在运行中**不写**，
只报告"需官方键 + 重启"，避免再拿生产换一次指纹。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _canary() -> str:
    return io.open(os.path.join(ROOT, "core", "android", "abi_canary.py"),
                   encoding="utf-8").read()


def _fp() -> str:
    return io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                   encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. 危险键黑名单必须在，且必须包含曾把设备搞挂的那几个
# ---------------------------------------------------------------------------
def test_no_delete_blocklist_exists():
    s = _canary()
    assert "_NO_DELETE" in s, "没有 delete 黑名单（会再次把设备搞挂）"
    seg = s[s.find("_NO_DELETE"):s.find("_NO_DELETE") + 900]
    for k in ("ro.adb.secure", "ro.serialno", "ro.boot.serialno",
              "ro.bootmode", "ro.boot.verifiedbootstate", "ro.bootloader"):
        assert k in seg, "黑名单缺 %s" % k


def test_no_delete_guard_applied():
    """delete-then-set 分支必须带 `k not in _NO_DELETE` 判定。"""
    s = _canary()
    assert "k not in _NO_DELETE" in s, "黑名单没真的生效"


def test_blocklist_records_both_incidents():
    """两处事故都要在注释里留痕（否则下次还会"值对就敢改"）。"""
    s = _canary() + _fp()
    assert "ro.adb.secure" in s and "offline" in s.replace(" ", "")
    assert "system_server" in s or "运行中" in s, \
        "没记录『值对也不能热改』这条认知"


# ---------------------------------------------------------------------------
# 2. 只允许改"没人运行时依赖"的键
# ---------------------------------------------------------------------------
def test_hot_write_guard_present():
    """必须有一道"运行中不许热改机型/构建字段"的闸。"""
    s = _canary()
    assert "_HOT_WRITE_SAFE" in s or "_NO_HOT_WRITE" in s, \
        "没有热改白名单/黑名单"


def test_hot_write_blocks_product_and_build():
    """`ro.product.device` / `ro.build.*` 这类必须被拦下并说明替代路径。"""
    s = _canary()
    i = s.find("_NO_HOT_WRITE =")
    if i < 0:
        i = s.find("_NO_HOT_WRITE")
    assert i > 0
    seg = s[i:i + 3200]
    assert "ro.product.device" in seg or "ro.product." in seg
    assert "phone_miit" in seg or "官方键" in seg, \
        "没指出正确路径（官方键 + 重启）"


# ---------------------------------------------------------------------------
# 3. `_magisk` 必须做 ro.* 探针（只看文件在不在会被静默失败骗）
# ---------------------------------------------------------------------------
def test_magisk_probe_uses_ro_key():
    s = _fp()
    i = s.find("def _magisk(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    assert "ro.boot.revision" in body, "探针没用 ro.* 键"
    assert "tmprobe" in body, "没有 delete-then-set 探针"
    # 明确记录 persist.* 不可当探针
    assert "persist." in body, "没记录『persist.* 能写不代表 ro.* 能写』"


def test_adb_path_candidates_include_mumu():
    """`as_root` 现在走 adb push，必须有 MuMu 的 adb 绝对路径。"""
    s = io.open(os.path.join(ROOT, "scripts", "magisk_bootstrap.py"),
                encoding="utf-8").read()
    assert "Netease\\MuMu" in s or "Netease/MuMu" in s, \
        "没带 MuMu adb 路径（裸 `adb` 会静默失败）"


# ---------------------------------------------------------------------------
# 4. as_root 不许再用管道/重定向（Windows 会被本地 shell 吃掉）
# ---------------------------------------------------------------------------
def test_as_root_avoids_pipe_and_redirect():
    """真正的调用参数里不许出现管道/重定向（docstring 提到它们是解释原因）。"""
    s = _fp()
    i = s.find("def as_root(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    # 只看传给 _call / sh 的实际参数行
    for ln in body.splitlines():
        code = ln.split("#", 1)[0]
        if "_call(" in code or '"shell"' in code:
            assert "| base64 -d | sh" not in code, \
                "还在用管道（Windows 上 stdout 会丢）：%s" % code.strip()
            assert " > " not in code, \
                "实际参数里还有重定向：%s" % code.strip()
    assert "push" in body and "mkstemp" in body, "没走 adb push 方案"
