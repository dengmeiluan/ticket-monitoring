# -*- coding: utf-8 -*-
"""r1167：App 卡片把"设备上登着"读成"已保存"，用户看到"我登了三家，页面没变"。

现场（2026-11-10 12:2x 实测 `/api/app-login/state?plat=…`）：

```
app_zhixing   saved=True   saved_at=1793581990（11-02 的快照）
app_qunar     saved=True   saved_at=1793700048（11-03 的快照）
app_fliggy    saved=False  ← 设备上今天 12:26 还在跑采集
app_ctrip     saved=False  ← 同上，还有 6 个 login_fail dump
app_tongcheng saved=False
```

`user_data/android_snapshots/` 里**只有 app_qunar / app_zhixing 两个 tar.gz**。
也就是说：`saved` 只表示"有没有导出过快照"，而用户读成"登录了没有"；
设备上登着但没导快照时，页面显示"未保存"，用户以为系统坏了。

契约（本文件断言）：
1. 三个事实分开报：`snapshot_saved`（有快照文件）/ `live_now`（设备上此刻登着）/
   `evidence`（给界面直接用的一句话档位）；
2. 旧字段 `saved / saved_at / session / needs_login` 一律保留（不许破坏既有前端）；
3. **负控**：有会话但没快照时，`saved` 不能变成 True（不许把"设备在线"冒充"已存快照"）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import login_api  # noqa: E402


class _Sess:
    status = "pending"

    def view(self):
        return {"plat": "app_fliggy", "status": "pending",
                "saved": False, "needs_login": False}


class _Reg:
    def __init__(self, sess=None):
        self._s = sess

    def get(self, plat):
        return self._s


def _state(reg, snapshot=None, needs_login=None):
    out, code = login_api.handle_state(reg, "app_fliggy",
                                       None if snapshot is None else (lambda p: snapshot),
                                       None if needs_login is None else (lambda p: needs_login))
    assert code == 200, (out, code)
    return out


def test_no_session_no_snapshot():
    out = _state(_Reg(None), snapshot={"exists": False, "mtime": 0})
    assert out["snapshot_saved"] is False, out
    assert out["live_now"] is False, out
    assert out["saved"] is False, out
    assert out["evidence"] == "无", out


def test_snapshot_only():
    out = _state(_Reg(None), snapshot={"exists": True, "mtime": 1793700048.0})
    assert out["snapshot_saved"] is True and out["saved"] is True, out
    assert out["live_now"] is False, out
    assert out["evidence"] == "快照", out


def test_live_without_snapshot_is_not_saved():
    """关键场景：设备上登着、但没导快照 —— 用户说的"我登了但页面没变"。"""
    out = _state(_Reg(_Sess()), snapshot={"exists": False, "mtime": 0})
    assert out["live_now"] is True, out
    assert out["snapshot_saved"] is False, out
    assert out["saved"] is False, "没有快照就不能报已保存（否则重启即失效）"
    assert out["evidence"] == "设备在线", out


def test_live_and_snapshot():
    out = _state(_Reg(_Sess()), snapshot={"exists": True, "mtime": 1793700048.0})
    assert out["live_now"] is True and out["snapshot_saved"] is True, out
    assert out["evidence"] == "快照", out


def test_legacy_fields_kept():
    out = _state(_Reg(None), snapshot={"exists": True, "mtime": 1793700048.0},
                 needs_login=True)
    for k in ("ok", "session", "needs_login", "saved", "saved_at"):
        assert k in out, "旧字段 %s 被删了，前端会静默坏掉：%s" % (k, out)
    assert out["needs_login"] is True


def test_ui_distinguishes_live_unsaved():
    """界面必须能把「设备上登着但没存快照」单独显示出来。"""
    import io

    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "live_unsaved" in w, "前端没有「设备在线未存快照」这一档"
    assert "设备已登录 · 未存快照" in w, "缺少给人看的中文标签"
    assert "live_now" in w and "snapshot_saved" in w, (
        "前端没有把 live_now / snapshot_saved 从接口读下来")
