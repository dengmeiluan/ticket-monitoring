# -*- coding: utf-8 -*-
"""r1063 T172：手动中止本轮（objective 里的"一切可中断"）。

以前只能等一轮自己跑完（一条航线最多 300s，一轮七八条就是十几分钟）。
现在有三条路都能中止：

```bash
python -m core.interrupt            # 请求中止（航线边界生效）
python -m core.interrupt --clear    # 撤销
python -m core.interrupt --state    # 看状态
```

面板/脚本：`POST /api/run/stop`。

**诚实边界（写进文档与测试）**：只在**航线之间**生效，**不强杀线程**——
正在跑的浏览器/模拟器操作没有安全中断点，硬杀会留半截状态（页面残挂、
设备被占）。所以语义是"不再派发下一条航线"，正在飞的那条会跑完并照常落库。

另加两条纪律：
* 中止请求有 **TTL（15 分钟）**：昨天点过一次不该在今天悄悄吞掉一轮；
* `/api/run` **开始时**清掉遗留请求：新一轮不该被上一轮的意图影响。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import interrupt as IT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_request_and_clear():
    IT.clear()
    assert IT.requested() is False
    IT.request(by="test")
    assert IT.requested() is True
    IT.clear()
    assert IT.requested() is False


def test_request_expires(monkeypatch):
    """过期请求必须自动失效（否则昨天的一次点击会吞掉今天的轮次）。"""
    IT.clear()
    IT.request(by="test")
    real = time.time
    monkeypatch.setattr(IT.time, "time", lambda: real() + IT.TTL_S + 5,
                        raising=False)
    assert IT.requested() is False
    assert IT.state()["active"] is False
    IT.clear()


def test_state_shape():
    IT.clear()
    st = IT.state()
    for k in ("requested", "at", "by", "active", "ttl_s"):
        assert k in st, st


def test_main_loop_checks_interrupt_between_routes():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    i = src.index("for qi, (fc, tc, d) in enumerate(queries):")
    seg = src[i:i + 1200]
    assert "_itr.requested()" in seg, "航线循环入口必须问一次中止"
    assert "不再派发下一条航线" in seg, "语义要写清：不强杀线程"
    assert "_itr.clear()" in seg, "生效后要清掉请求，否则后续轮次全被吞"


def test_api_has_stop_and_clears_on_run():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert '"/api/run/stop"' in w
    i = w.index('elif self.path == "/api/run":')
    seg = w[i:i + 400]
    assert "_itr.clear()" in seg, "新一轮开始必须清掉遗留中止请求"

def test_marker_is_cross_process(tmp_path, monkeypatch):
    """`request()` 必须落盘：CLI 在**另一个进程**里，只靠内存标志看不到。

    实测暴露过：webui 里 `POST /api/run/stop` 置位成功，另开
    `python -m core.interrupt --state` 读到 false —— 那条路等于没接线。
    """
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    IT.clear()
    IT.request(by="pytest")
    marker = tmp_path / ".interrupt.json"
    assert marker.is_file(), "没有落盘标记，CLI 那条路就是死的"
    # 模拟"另一个进程"：清空内存态，只留文件
    with IT._LOCK:
        IT._STATE.update({"requested": False, "at": 0.0, "by": ""})
    assert IT.requested() is True, "只靠落盘标记也必须能读到请求"
    IT.clear()
    assert not marker.is_file(), "clear() 要顺手把标记删掉"


def test_state_reports_marker_path(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    IT.clear()
    st = IT.state()
    assert "marker" in st and str(tmp_path) in st["marker"]
