# -*- coding: utf-8 -*-
"""r1063 T94：出口 IP 定性 + 会话窗口进入面板载荷。

**IP 定性**（本机实测 2026-11-08）：`58.246.127.206`，上海联通（CNC Group
CHINA169），`proxy=False hosting=False mobile=False` → **住宅线路，IP 不是风险点**。
这条把"换出口 IP"从解封阶梯里划掉了——省得白折腾。

**面板载荷**：`/api/pacing` 的渠道对象新增 `session` 字段（结构化），
前端要不要显示由它决定（不动任何布局）。注意演示模式没有真实库，
那段代码不执行，所以只能在真实模式下看到——用例改为**源码级**锁接线。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_session_field_is_wired_into_pacing_payload():
    assert "from core import session_window as _sw" in SRC
    assert '_ch["session"] = _session' in SRC
    # 必须用真实存在的 root 助手（第一版写成 `_ud_root_local()`，会被 try 吞掉）
    seg = SRC[SRC.index("from core import session_window as _sw"):
              SRC.index("from core import session_window as _sw") + 400]
    assert "_ud_root()" in seg, seg
    assert "_ud_root_local" not in seg, "不存在的助手会被 try 静默吞掉"


def test_session_field_inside_path_stats_block():
    """要放在 path_stats 那段里（真实模式才执行），别放到别处。"""
    i_sess = SRC.index('_ch["session"] = _session')
    i_paths = SRC.index("_paths = {}", i_sess)
    assert 0 < i_paths - i_sess < 600, (i_sess, i_paths)


def test_ud_root_helper_exists():
    import webui
    assert callable(getattr(webui, "_ud_root", None))
    root = webui._ud_root()
    assert str(root)
