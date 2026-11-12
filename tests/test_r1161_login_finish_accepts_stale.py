# -*- coding: utf-8 -*-
"""r1161：保存登录把"会话文件陈旧"说成"没有会话文件"，用户照着提示也修不好。

用户原话：「我途牛操作登录了，但是无法保存页面上的保存登录」。

现状（`_finish_login`，r1063 T139 留下的分支）：无活动窗口时只看 `mtime < 6h`，
超时一律落进同一条错误文案「profile 里没有会话文件」——文件明明在，只是旧了。
用户能做的只有反复重登，而"旧会话"其实**可以用一次真核验直接判定**。

契约（三条，缺一不可）：
1. **不假装刚登录**：陈旧会话仍然 `ok=False`（守住 r1063 的诚实契约）；
2. **说清事实 + 给真出路**：`err` 写明"已 X 小时未更新"，并**自动发起核验**
   （`*_h5` 页面核验 / PC 真查询自检），`verified_at` 会自己更新；
3. **真没文件**时才说"还没有任何登录记录"，且保留"关窗即保存"的提示。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _mk_profile(tmp_path, slot, age_h):
    d = tmp_path / slot
    d.mkdir(parents=True, exist_ok=True)
    f = d / "session-state.json"
    f.write_text('{"cookies":[]}', encoding="utf-8")
    t = time.time() - age_h * 3600.0
    os.utime(f, (t, t))
    return f


def _call(tmp_path, monkeypatch, plat, slot):
    import webui
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)}}, raising=False)
    monkeypatch.setattr(webui._State, "login_sessions", {}, raising=False)
    verified = []
    monkeypatch.setattr(webui, "_verify_login_slot",
                        lambda k: verified.append(k) or {"ok": True},
                        raising=False)
    probed = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": probed.append(p) or {"ok": True},
                        raising=False)
    return webui._finish_login(plat, slot), verified, probed


def test_stale_h5_session_is_explained_and_auto_verified(tmp_path, monkeypatch):
    """7 小时前的 H5 会话：不能假装刚登录，但必须说清原因并自动核验。"""
    _mk_profile(tmp_path, "tuniu_h5", 7)
    r, verified, _ = _call(tmp_path, monkeypatch, "tuniu", "tuniu_h5")
    assert r.get("ok") is False, "陈旧会话不许冒充新登录：" + str(r)
    assert r.get("stale") is True, r
    assert 6.5 <= float(r.get("age_h") or 0) <= 7.5, r
    assert "小时未更新" in (r.get("err") or ""), "必须把『多久没更新』说出来：" + str(r)
    assert "没有会话文件" not in (r.get("err") or ""), (
        "文件明明在，不能再说没有会话文件：" + str(r))
    time.sleep(0.2)
    assert verified == ["tuniu_h5"], "陈旧 H5 会话必须自动发起页面核验：%s" % verified
    assert r.get("verifying") is True, r


def test_stale_pc_session_uses_probe_not_page_verify(tmp_path, monkeypatch):
    """PC 槽位走真查询自检（probe），不打开登录页（会误判成需登录）。"""
    _mk_profile(tmp_path, "tuniu", 8)
    r, verified, probed = _call(tmp_path, monkeypatch, "tuniu", "tuniu")
    assert r.get("ok") is False and r.get("stale") is True, r
    assert r.get("verifying") is False, r
    time.sleep(0.2)
    assert verified == [], "PC 槽位不该走页面核验：%s" % verified
    assert probed and probed[0] == "tuniu", probed


def test_fresh_session_still_saves(tmp_path, monkeypatch):
    _mk_profile(tmp_path, "tuniu_h5", 0.2)
    r, _, _ = _call(tmp_path, monkeypatch, "tuniu", "tuniu_h5")
    assert r.get("ok") is True and r.get("saved") is True, r
    assert r.get("stale") is False, r


def test_no_file_is_honest_and_actionable(tmp_path, monkeypatch):
    """负控：真没登过时，文案必须既承认"还没有记录"，又保住 r1063 的"关窗即保存"。"""
    r, verified, _ = _call(tmp_path, monkeypatch, "tuniu", "tuniu_h5")
    assert r.get("ok") is False, r
    assert "还没有任何登录记录" in (r.get("err") or ""), r
    assert "没有进行中的登录窗口" in (r.get("err") or ""), r
    assert "关窗" in (r.get("hint") or ""), r
    assert verified == [], "没有会话文件时不该发起核验"
