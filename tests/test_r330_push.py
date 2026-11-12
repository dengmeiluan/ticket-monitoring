# -*- coding: utf-8 -*-
"""c330 推送审校五案（audit_c330_push.md，TDD 先行）：

C1（P2）slim 心跳行：双侧 ≥9 全角名域价格判据整行蒸发——剥窗保价
档数学不可达（44/40 实测）直落 bare（26.5/40 无价格），截名机制
（地板档同源）前移一步即可保价，违背「价格判据最后丢」档序律。
C2（P2）_ops_fallbacks 冒号族地板档载荷全灭：「孤低价拦截×1：(截)」
空载句——前缀占满预算，与首渠道让位档「渠道名优先入预算」取数侧
自相矛盾。修：载荷优先，head 尾部整段保（路由短名由同消息小节标题
托底）。
C3（P3）hits 头混合「双名+联程」形态丢航班号：剥名档 49/39 超后直
落裸判据——首名+首码档 34/39 可达而未入链（旧「防死档」论断对长
混合名不成立）。
C4（P3）特价快讯半角 ¥（全库唯一币符分叉）+价格行无守卫（超宽剥
附加段保价判据）。
C5（P3）_storm_title 保尾切法切出半截日期 token（「11/等7条」悬垂
——半截比无更险，卅一§2 同族）。

C6（价带守卫渲染侧纵深不对称）备案不修：现役链输入均已上游滤过，
agent 自证「非现役可达成因」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r330_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _disp_dw, _ops_fallbacks, _storm_title  # noqa: E402


# ────────────────── C1：截名保价档 ──────────────────

def test_c1_bare_price_line_longname_keeps_price():
    """长名域（乌鲁木齐→阿拉善左旗）：截名保价档 ≤40 且 ￥ 在场
    （旧链此域唯一可达的合规档是 bare 身份行，零价格）。"""
    from core.alerter import _bare_price_line
    line = _bare_price_line("乌鲁木齐→阿拉善左旗", "09/25", "直飞 ￥2451")
    assert "￥2451" in line, "价格判据不得蒸发：" + line
    assert _disp_dw(line) <= 40, line


def test_c1_bare_price_line_shortname_verbatim():
    """短名域零回归：head 预算内整名原样（与剥窗档产出同构）。"""
    from core.alerter import _bare_price_line
    line = _bare_price_line("上海→海口", "01/29", "直飞 ￥2000")
    assert line == "> 上海→海口 01/29 ｜ 直飞 ￥2000", line


def test_c1_slim_digest_longname_price_survives():
    """全链锚：slim 心跳降级链在长名域选中的行含价格（_fit_line 首
    合规选档语义下，截名保价档必须排在 bare 之前才可达）。"""
    from core.alerter import Alerter
    from core.models import Route

    class _NL:
        def warning(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

    al = Alerter(_NL(), storage=None, heartbeat_style="slim")
    route = Route(from_name="乌鲁木齐", to_name="阿拉善左旗",
                  from_code="URC", to_code="ALAA", dates=["2026-09-25"],
                  alert_direct=2500, alert_transfer=0)
    sec = {"date": "2026-09-25",
           "best_direct": {"price": 2451.0, "_stale_h": None},
           "best_transfer_mkt": None, "best_transfer": None}
    rs = [(route, [sec])]
    payload = al._digest_payload(rs, fresh=True, slim=True)
    body = payload["desp"].replace("\n", " ")
    assert "￥2451" in body, "slim 心跳长名域整行零价格（C1 病灶）：" + body[:300]


# ────────────────── C2：运维注冒号族地板档 ──────────────────

def test_c2_ops_colon_floor_keeps_payload():
    """冒号族地板档载荷优先：渠道+价格判据在场且 ≤40（旧地板产出
    「(截)」空载句）。"""
    fbs = _ops_fallbacks("乌→上 10/04 孤低价拦截×1：飞猪￥700")
    floor = fbs[-1]
    assert "飞猪￥700" in floor, "载荷（渠道￥价）不得全灭：" + floor
    assert _disp_dw(floor) <= 40, floor


def test_c2_ops_no_colon_family_unchanged():
    """无冒号族零回归：地板档仍走原「40−前缀−标记」逐字截。"""
    fbs = _ops_fallbacks("乌→上 10/04 直挂标注缺失·途牛")
    floor = fbs[-1]
    assert floor.endswith("(截)"), floor
    assert "直挂标注缺失" in floor, floor
    assert _disp_dw(floor) <= 40, floor


# ────────────────── C3：hits 头混合形态 ──────────────────

def test_c3_mixed_dualname_codeshare_keeps_code():
    """混合形态（双名+联程）剥名档超宽时，首名+首码档可达且被选中
    （航班号不整体消失）。走真实渲染入口 _hit_head_fbs + _fit_line。"""
    from core.alerter import _fit_line, _hit_head_fbs
    base = "> 🔥 **直飞 ￥46800**"
    nm = "新海航｜金鹏航空Y87519/海南航空HU7849"
    head = _fit_line(f"{base} {nm}", fallbacks=_hit_head_fbs(base, nm),
                     limit=39)
    assert "Y87519" in head or "HU7849" in head, \
        "航班号整体消失（C3 病灶）：" + head
    assert _disp_dw(head) <= 39, head


def test_c3_pure_codeshare_and_dualname_unchanged():
    """纯联程与纯双名形态零回归（else 分支与剥名档原样）。"""
    from core.alerter import _hit_head_fbs
    base = "> 🔥 **直飞 ￥800**"
    # 纯联程：保「/」前段
    fbs = _hit_head_fbs(base, "海南航空 HU7849/春秋9C8845")
    assert fbs[0] == f"{base} 海南航空 HU7849", fbs
    # 纯双名：保「｜」后段，无「/」不加档
    fbs2 = _hit_head_fbs(base, "新海航｜金鹏航空 Y87519")
    assert fbs2 == [f"{base} 金鹏航空 Y87519", base], fbs2


# ────────────────── C4：特价快讯币符与守卫 ──────────────────

def test_c4_special_push_fullwidth_and_guard():
    """特价快讯：币符统一全角 ￥（安全集在册）；附加段（折扣+航司）
    超宽剥尾保价判据。"""
    from core.specials import SpecialDeal, build_special_push
    from core.models import Route  # noqa: F401（占位防 import 顺序误删）
    watch = Route(from_name="上海", to_name="", from_code="SHA",
                  to_code="URC", dates=["2026-11-01"], alert_direct=0,
                  alert_transfer=0)
    d = SpecialDeal(src="tuniu", from_code="SHA", to_code="URC",
                    date="2026-11-01", src_price=480.0,
                    discount="2.1折｜含20kg托运｜免费退改｜选座",
                    airline="中国联合航空 KN5977 波音738")
    title, desp = build_special_push(watch, [(d, 450.0)])
    assert "¥" not in desp, "半角 ¥ 是全库唯一币符分叉（安全集外）"
    assert "￥450" in desp, desp
    for blk in desp.split("\n\n"):
        for ln in blk.split("\n"):
            if ln.startswith("￥"):
                assert _disp_dw(ln) <= 40, "价格行须守宽：" + ln


# ────────────────── C5：风暴标题 token 边界 ──────────────────

def test_c5_storm_title_no_half_date_token():
    """保尾切法的切点不得落在日期 token 中段（「11/等7条」悬垂）。"""
    import re
    t = ("🚨 达标！上→巴 11/16 直飞￥2306｜另监控 "
         "乌→上 10/16 · 乌→上 11/16 · 乌→沪 12/01 等3条")
    out = _storm_title(3, 3, t)
    assert out.endswith("等3条"), out
    assert not re.search(r"\d{1,2}/等", out), "半截日期悬垂：" + out
