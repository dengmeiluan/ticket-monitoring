# -*- coding: utf-8 -*-
"""r1169：两件事——(A) 状态词单一真源；(B) 双端槽位补到 10 格、顺序由后端下发。

A. 状态漂移现状（2026-11-10 实测）
   后端 `status` 有 10 个词：available / page_ok / saved / pending / saving /
   active / login_required / challenge / save_error / missing；
   前端另有 **三套各写一份的中文表**（`LBL` / `SLOT_STATUS_CN` / `lgShortStatus`
   的内联表）。同一个 `page_ok`，一处写「入口可达」、一处写「已保存 · 页面可访问
   （明细未验证）」。用户在三张卡上看到三种说法，这是"一切统一状态"的正题。
   修法：后端给出 7 档语义 + 中文（`state7` / `state_cn`），前端优先用它，旧表退为兜底。

B. 双端现状：`LOGIN_SLOTS` 9 格，缺 `qunar_h5`（用户已拍板 D1：所有渠道 PC+H5
   双端固定登录，避免歧义）；前端还硬编码了一份 `const order=[...]` ——
   后端加一格页面就静默少一格（第二份声明）。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.channels import BROWSER_CHANNELS  # noqa: E402
from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER  # noqa: E402

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


# ---------------- A. 状态单一真源 ----------------

def test_state7_is_exactly_seven_buckets():
    import webui
    tbl = getattr(webui, "SLOT_STATE7", None)
    assert tbl, "缺少 SLOT_STATE7（状态唯一真源）"
    codes = [k for k, _ in tbl]
    assert len(codes) == 7, "只允许 7 个语义档，实际 %r" % (codes,)
    assert len(set(codes)) == 7
    for k, cn in tbl:
        assert cn and cn.strip(), "档 %s 没有中文" % k


def test_every_known_status_maps_into_state7():
    import webui
    known = ["available", "page_ok", "saved", "pending", "saving", "active",
             "login_required", "challenge", "save_error", "missing"]
    codes = {k for k, _ in webui.SLOT_STATE7}
    for st in known:
        s7, cn = webui._slot_state7(st)
        assert s7 in codes, "%s 落到了枚举之外：%s" % (st, s7)
        assert cn and cn.strip(), "%s 没有中文" % st


def test_unknown_status_never_silently_blank():
    """负控：出现未登记的新词时，必须显式落到「待确认」，不许静默空白。"""
    import webui
    s7, cn = webui._slot_state7("some_new_word")
    assert s7 == "unknown", s7
    assert cn == "待确认", cn


def test_service_closed_slot_is_retired():
    import webui
    s7, cn = webui._slot_state7("saved", service_closed=True)
    assert s7 == "retired" and cn == "停服", (s7, cn)


def test_payload_carries_state7_and_cn():
    assert "_slot_state7(" in WEBUI, "槽位载荷没走统一派生函数"
    assert '"state_cn"' in WEBUI or "state_cn\"] = " in WEBUI, "槽位载荷没带 state_cn"
    assert '"slot_order": list(LOGIN_SLOT_ORDER)' in WEBUI, (
        "顺序没有随接口下发（前端只能再写一份）")


def test_frontend_prefers_backend_label():
    """前端必须优先用后端 state_cn，旧的三套表只做兜底。"""
    assert "s.state_cn" in WEBUI, "前端没有优先使用后端 state_cn"


# ---------------- B. 双端槽位 10 格 + 顺序单源 ----------------

def test_every_browser_channel_has_pc_and_h5():
    for plat in BROWSER_CHANNELS:
        assert plat in LOGIN_SLOTS, plat
        assert plat + "_h5" in LOGIN_SLOTS, "%s 缺 H5 槽位（D1 双端）" % plat
    assert len(LOGIN_SLOT_ORDER) == len(BROWSER_CHANNELS) * 2


def test_qunar_h5_exists_and_is_marked_closed():
    m = LOGIN_SLOTS["qunar_h5"]
    assert m["surface"] == "h5" and m["mobile"] is True
    assert m.get("service_closed") is True, "去哪儿已停服，H5 格必须是 retired 语义"
    assert m["profile"] != LOGIN_SLOTS["qunar"]["profile"], "两格不能共用 profile"
    assert "://m." in m["login_url"], "H5 槽位必须指向移动站"
    # 保住既有契约：requirement 仍是「必须登录」（test_goal_requirements 会查）
    assert m.get("requirement") == "必须登录"


def test_order_comes_from_backend_not_hardcoded():
    """负控：前端不许再硬编码整份槽位顺序表。"""
    assert "const order=['ctrip','ctrip_h5','qunar'" not in WEBUI, (
        "前端仍硬编码 9 项顺序表：后端加一格页面会静默少一格")
    assert "Object.keys(j.slots)" in WEBUI, "顺序没有从 /api/login-state 的 slots 派生"


def test_cards_derive_their_slot_list_from_backend():
    """卡片里的槽位列表也必须派生——写死就会漏格（实测 qunar_h5 少了一整行）。"""
    assert "function _slotsFor(" in WEBUI, "没有派生函数 _slotsFor"
    for v in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert "_slotsFor('%s')" % v in WEBUI, "%s 卡没有走派生" % v
    assert "slots:[by.qunar]" not in WEBUI, "去哪儿卡仍是写死单槽（漏 qunar_h5）"


def test_unsubscribed_app_is_labelled_not_missing():
    """没被订阅 ≠ 未登录（app_tongcheng 从来不在订阅里）。"""
    assert "'unsubscribed'" in WEBUI, "没有 unsubscribed 这一档"
    assert "未纳入采集" in WEBUI, "缺少给人看的「未纳入采集」文案"
