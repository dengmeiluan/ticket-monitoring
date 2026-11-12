# -*- coding: utf-8 -*-
"""r1063 T250-T251：issue #15 的两个真问题。

1. **"核验成功但仍让我继续核验"**：
   * 后端 `_login_state_view()` 的 **PC 分支**把 `verified_at` 写死成空串、
     `detail` 写死空——核验结果 `_SLOT_VERIFY[key]` 只有 H5 分支读；
   * 前端 `lgActionHTML` 对 `page_ok`（核验过、页面可达、无出数）仍然显示
     「立即核验」，用户点完还是这句，读作"核验没生效"。
2. **"更新要卸载重装吗"**：项目此前**没有**检测更新与升级能力。

本文件用源码契约 + 纯函数单测钉住这两件事。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import update as U  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(p):
    return io.open(os.path.join(ROOT, p), encoding="utf-8").read()


# ---------------- ① 核验结果必须在 PC 槽位可见 ----------------

def test_pc_slot_reads_verify_result():
    """PC 分支必须读核验结果（r1063 T250）。

    r1063 T310：**不再用"定位点后 N 字符"的窗口**——后续改动（T270 的状态抬升）
    会把目标行挤出窗口，导致本地绿、CI 红（窗口宽度依赖文件行距，太脆）。
    改为整文件断言 + 单独钉住定位点本身存在。
    """
    w = _src("webui.py")
    assert "_pv = dict(_SLOT_VERIFY.get(key)" in w, "PC 分支必须读核验结果"
    assert '"verified_at": _pv.get("at", "")' in w, \
        "verified_at 不能继续写死空串"
    assert '"page_ok": _st == "page_ok"' in w


def test_frontend_shows_verified_time_and_renames_button():
    w = _src("webui.py")
    assert "_vtxtSide" in w and "核验于 " in w, "槽位说明要显示核验时间"
    i = w.index("st==='page_ok' ? '再核验'")
    seg = w[i:i + 500]
    assert "上次核验：页面可达但未出数" in seg, "要说明为什么还要再点一次"


# ---------------- ② 检测更新 / 热更新 ----------------

def test_version_tuple_and_skip_rules():
    assert U._vtuple("v1.7.1") > U._vtuple("1.6.0")
    assert U._vtuple("1.6.0") > U._vtuple("v1.5.307")
    assert U._skip("user_data/x") and U._skip("data/prices.db")
    assert U._skip("config.yaml") is True, "升级绝不能覆盖用户配置"
    assert U._skip("core/update.py") is False


def test_parse_rolling_release_body():
    """滚动 release：tag 恒为 v1.0，真实版本/源码在正文。"""
    body = ("**当前版本：1.6.0 · 源码 16b54ea20eff39b42ced8505cbab67c631faec76"
            " · 2026-11-09**")
    assert U._parse_release_version(body) == "1.6.0"
    assert U._parse_release_commit(body).startswith("16b54ea")


def test_local_commit_reports_source():
    h, src = U.local_commit()
    assert src in ("git", "build", ""), src
    if src == "git":
        assert len(h) >= 7


def _fake_releases(body_ver="1.6.0", commit="deadbeefcafe", tag="v1.0"):
    body = "当前版本：%s · 源码 %s · 2026-11-09" % (body_ver, commit)
    return json.dumps([{"tag_name": tag, "body": body, "draft": False,
                        "prerelease": False, "html_url": "https://x/y",
                        "published_at": "2026-11-09", "assets": []}])


def test_check_new_version(monkeypatch):
    monkeypatch.setattr(U, "local_version", lambda: "1.5.0")
    monkeypatch.setattr(U, "local_commit", lambda: ("deadbeefcafe", "build"))
    monkeypatch.setattr(U, "_get", lambda *a, **k: (
        _fake_releases(body_ver="1.6.0").encode(), "fake"))
    monkeypatch.setattr(U, "_save_cache", lambda rec: None)
    r = U.check(force=True)
    assert r["ok"] and r["has_update"], r
    assert r["latest"] == "v1.6.0", r


def test_same_version_new_build_only_for_packaged(monkeypatch):
    """同版本 + 打包安装 + 源码不同 → 有新构建；开发树不算。"""
    monkeypatch.setattr(U, "local_version", lambda: "1.6.0")
    monkeypatch.setattr(U, "_save_cache", lambda rec: None)
    monkeypatch.setattr(U, "_get", lambda *a, **k: (
        _fake_releases(body_ver="1.6.0", commit="aaaabbbbcccc").encode(),
        "fake"))
    monkeypatch.setattr(U, "local_commit", lambda: ("aaaabbbbcccc", "build"))
    assert U.check(force=True)["has_update"] is False, "源码相同不该报有更新"
    monkeypatch.setattr(U, "local_commit", lambda: ("111122223333", "build"))
    assert U.check(force=True)["has_update"] is True, "打包安装源码不同＝有新构建"
    monkeypatch.setattr(U, "local_commit", lambda: ("111122223333", "git"))
    assert U.check(force=True)["has_update"] is False, "开发树不按提交比"


def test_apply_skips_user_data(tmp_path, monkeypatch):
    assert U._skip("user_data/app_zhixing/x.json")
    assert U._skip("data/prices.db")
    assert U._skip("logs/monitor.log")
    assert U._skip("debug/raw.json")

def _fake_release_with_assets(body_ver="1.6.0", tag="v1.0"):
    import json
    body = "当前版本：%s · 源码 deadbeefcafe · 2026-11-10" % body_ver
    assets = [
        {"name": "SHA256SUMS.txt",
         "browser_download_url": "https://x/SHA256SUMS.txt"},
        {"name": "ticket-monitoring-linux-x64.zip",
         "browser_download_url": "https://x/linux.zip"},
        {"name": "ticket-monitoring-win64.zip",
         "browser_download_url": "https://x/win.zip"},
    ]
    return json.dumps([{"tag_name": tag, "body": body, "draft": False,
                        "prerelease": False, "html_url": "https://x/rel",
                        "published_at": "2026-11-10", "assets": assets}])


def test_old_version_gets_update_with_zip(monkeypatch):
    """主路径：本机 1.5.x，仓库已发 1.6.0 → 应报有更新且给出**与部署形态相符**的资产。

    r1261 口径：`check()` 现在显式按 `deploy_mode()` 选资产——
    源码部署要的是源码包（zipball），发行部署才优先 windows 包。
    旧断言"永远优先 win.zip"正是 r1209 那个 bug 的一半（源码部署被喂了 exe 包）。
    """
    monkeypatch.setattr(U, "local_version", lambda: "1.5.307")
    monkeypatch.setattr(U, "_save_cache", lambda rec: None)
    monkeypatch.setattr(U, "_get", lambda *a, **k: (
        _fake_release_with_assets().encode(), "fake"))
    r = U.check(force=True)
    assert r["ok"] and r["has_update"], r
    assert r["latest"] == "v1.6.0", r
    # 夹具里既没有 source 资产、也没有 zipball_url → 退回普通 zip（linux.zip）
    assert r["zip"].endswith(".zip"), "应当仍给出一个可下载的 zip：%r" % r.get("zip")
    # 发行部署下才优先 windows 包（这是 `_pick_zip(rel, "binary")` 的契约）
    rel = {"assets": [
        {"name": "ticket-monitoring-linux.zip",
         "browser_download_url": "https://x/linux.zip"},
        {"name": "ticket-monitoring-win64.zip",
         "browser_download_url": "https://x/win.zip"}]}
    assert U._pick_zip(rel, "binary").endswith("win.zip")
    assert "1.6.0" in r["reason"]


def test_pick_zip_falls_back_when_no_win_asset():
    rel = {"assets": [{"name": "a.zip", "browser_download_url": "https://x/a.zip"},
                      {"name": "readme.txt", "browser_download_url": "https://x/r"}]}
    assert U._pick_zip(rel) == "https://x/a.zip"
    assert U._pick_zip({"assets": []}) == ""
