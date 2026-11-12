# -*- coding: utf-8 -*-
"""r1153：核验入口只放行 fliggy_h5 —— 其它 8 个槽位点「核验」必然 400。

现象（用户原话）：「途牛 h5 我看也登录了，但是你页面没变啊」「途牛操作登录了，
但是无法保存页面上的保存登录」。

根因（2026-11-10 实测）：
* `POST /api/login-verify`：`if slot != "fliggy_h5": 400 该槽位不支持页面核验`
* `_verify_login_slot()`：`if not meta or key != "fliggy_h5": 返回不支持`
* `_slot_verify_loop()`：写死只轮询 `("fliggy_h5",)`

而 `/api/login-state`（r1063 T250）**PC 与 H5 槽位都读 `_SLOT_VERIFY`**——
闸门不放行 ⇒ 9 个槽位永远拿不到真实页面分类，只能靠猜：
于是 `saved=True` 却 `active=False`，页面一直显示"需核验/需登录"。

本文件先写断言（此时应全红），再改 webui.py，让"任何已保存会话的槽位"都能真核验。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_route_accepts_every_slot():
    """路由不得把非 fliggy_h5 的槽位直接 400。"""
    assert 'slot != "fliggy_h5"' not in WEBUI, (
        "POST /api/login-verify 仍只放行 fliggy_h5；其余槽位点核验必 400")
    assert "slot != 'fliggy_h5'" not in WEBUI


def test_verifier_not_gated_to_fliggy_h5():
    """核验函数不得写死只支持一个槽位。"""
    assert 'key != "fliggy_h5"' not in WEBUI, (
        "_verify_login_slot 仍写死 fliggy_h5")
    assert "该槽位不支持页面核验" not in WEBUI, (
        "仍存在「该槽位不支持页面核验」这条硬拒绝")


def test_loop_covers_all_slots():
    """定时核验不得写死单个槽位。"""
    assert 'for key in ("fliggy_h5",)' not in WEBUI, (
        "_slot_verify_loop 仍只轮询 fliggy_h5")


def test_frontend_verify_button_covers_all_h5_slots():
    """前端「立即核验」按钮不得只给飞猪 H5（其它 _h5 槽位点不到核验）。"""
    assert "const h5=key==='fliggy_h5'" not in WEBUI, (
        "前端仍只把飞猪 H5 当 H5；携程/同程/途牛 H5 没有「立即核验」")
    assert "endsWith('_h5')" in WEBUI, "前端应按 _h5 后缀识别双端槽位"


def test_loop_only_verifies_h5_family():
    """定时核验只跑 *_h5：PC 槽位走真查询自检（probe），打开登录页会误判。"""
    assert 'if not str(key or "").endswith("_h5")' in WEBUI, (
        "_slot_verify_loop 未按 _h5 族收口")


def test_due_slot_picker_prefers_stalest():
    """抽出的纯函数：按"最久没核验"挑一个到期槽位（负控：全都新鲜则返回 None）。"""
    import webui  # noqa: E402  只导入，不启动服务

    pick = getattr(webui, "_slots_due_for_verify", None)
    assert pick is not None, "缺少纯函数 _slots_due_for_verify（无法做行为断言）"

    now = 100000.0
    # 两个槽位都过期：应挑更旧的
    got = pick({"ctrip": {"status": "page_ok", "ts": now - 5000},
                "tuniu_h5": {"status": "page_ok", "ts": now - 9000}},
               now=now, ttl_s=1800)
    assert got == "tuniu_h5", got
    # 全都新鲜 → None（负控：不许瞎核验）
    assert pick({"ctrip": {"status": "page_ok", "ts": now - 10}},
                now=now, ttl_s=1800) is None
    # 没核验过的槽位视为最旧
    assert pick({"ctrip": {"status": "page_ok", "ts": now - 10},
                 "tongcheng": {}}, now=now, ttl_s=1800) == "tongcheng"
