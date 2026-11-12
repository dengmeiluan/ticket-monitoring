# -*- coding: utf-8 -*-
"""r953：设备读不到时自检报 **0 分**，把"没读到"渲染成"检测到 13 条泄漏"。

实机日志（2026-11-04 19:05，采集进行中 adb 端口被占用）：

```
[android] root/模拟器隐藏：1 条动作，自检 0 分（剩余：无）
```

`0 分` 与 `剩余：无` **互相矛盾**：按 `score = 100 - 8*hits`，0 分需要 13 条以上
证据；而 `root`/`emulator` 两个列表都是空的。真正的原因是
`detect()` 的**初值就是 `score: 0`**，而设备读不到时它带着这个 0 直接 return：

```python
rep = {..., "score": 0, ...}
props = props_of(dev)
if not props:
    rep["error"] = "device offline"
    return rep          # ← 0 分就此泄漏给上层
```

危害不是数字难看，而是**指错方向**：操作员看到"自检 0 分"会以为隐藏彻底失败、
去折腾设备/重装，而实际什么都没发生（下一轮就 100 分了）。
这类"用 0 表示未知"的写法，和本仓库前面四次的假成功是同一族——
**默认值必须能被区分出来**。

修法：读不到时 `score = None`（"未知"），并把两处的 `%d` 换成会分辨
None 的渲染。下游本来就支持：`riskscore` 是 `if val is None: continue`，
`app_base` 用 `isinstance(数值)` 过滤 —— **不会因为读不到就加风险分**。

`audit()` 还有一个更隐蔽的同类问题：`_EMU_PROPS` 里有一批规则的
needle 是**空串**（"运营商信息为空"这类），props 为空时它们**全部命中**，
于是自检从 88 直接砸成十几分，看起来像身份伪装崩了。同样改成提前返回未知。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r953_unknown_not_zero.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402
from core.android import stealth as st  # noqa: E402


class _NoDevice:
    """什么都读不到的设备（采集进行中端口被占用的真实形态）。"""

    def _sh(self, *a, timeout=None):
        return ""


class _Offline(_NoDevice):
    def sh(self, *a, timeout=None):
        return ""


# ---------------------------------------------------------------------------
# 1. detect：读不到 = 未知，不是 0 分
# ---------------------------------------------------------------------------
def test_detect_unknown_not_zero():
    r = st.detect(_Offline())
    assert r.get("score") is None, "读不到设备不许报 0 分（0 分=检测到 13 条以上）"
    assert r.get("error"), "要留下读不到的证据"
    assert r.get("root") == [] and r.get("emulator") == []


def test_audit_unknown_not_phantom_leaks():
    r = fp.audit(_Offline())
    assert r.get("score") is None, "audit 读不到时不许算分"
    assert r.get("leaks") == [], \
        "props 为空时空 needle 会全部命中，必须提前返回"


# ---------------------------------------------------------------------------
# 2. 渲染：必须说"未知"，不能印成数字
# ---------------------------------------------------------------------------
def test_fmt_audit_score_unknown():
    assert "未知" in fp._fmt_audit_score({"score": None})
    assert "0 分" not in fp._fmt_audit_score({"score": None})


def test_fmt_audit_score_int():
    out = fp._fmt_audit_score({"score": 88, "score_note": "已到上限（x）"})
    assert "88 分" in out and "已到上限" in out, out
    # 不许出现嵌套括号（note 自己带括号时不能再套一层）
    assert "（已到上限（" not in out, out


def test_prepare_log_does_not_print_zero():
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    i = src.find("root/模拟器隐藏")
    seg = src[max(0, i - 200):i + 500]
    assert "自检 %d 分" not in seg, "日志还在用 %d 印分数（None 会崩或假报 0）"
    assert "未知" in seg, "日志没区分未知"


# ---------------------------------------------------------------------------
# 3. 下游不许把"未知"当风险
# ---------------------------------------------------------------------------
def test_riskscore_skips_unknown():
    src = io.open(os.path.join(ROOT, "core", "riskscore.py"),
                  encoding="utf-8").read()
    i = src.find("identity_score")
    seg = src[max(0, i - 400):i + 600]
    assert "is None" in seg, "riskscore 没跳过未知分数"


def test_app_base_filters_non_numeric_score():
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    assert "isinstance(ip.get(\"score\"), (int, float))" in src \
        or "isinstance(ip.get(" in src, "app_base 没过滤 None 分数"
