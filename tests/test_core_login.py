# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1592_login_cooldown_escalates.py
- tests/test_r397_login_not_error.py
- tests/test_r477_login_action_matches_evidence.py
- tests/test_r478_relogin_is_an_intervention.py
- tests/test_r479_relogin_takes_effect.py
- tests/test_r496_relogin_ledger_idempotent.py
- tests/test_r678_login_entry_is_usable.py
- tests/test_r708_login_row_fits_all_channels.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import pytest
import re
import sys
import tempfile

from core.pacing import ChannelBreaker
from core.storage import PriceStorage
from datetime import datetime, timedelta


# ---- merged from tests/test_r1592_login_cooldown_escalates.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _pacer():
    return ChannelBreaker(base_s=300, cap_s=3600,
                          login_cooldown_s=900, challenge_cooldown_s=21600)


def test_login_cooldown_escalates_and_caps():
    p = _pacer()
    got = []
    for _ in range(6):
        got.append(p.trip("fliggy", "login"))
    assert got[0] == 900, got
    assert got[1] == 1800, got
    assert got[2] == 3600, got
    assert got[3] == 7200, got
    assert got[4] == 14400, got
    assert got[5] == 14400, "没封顶：%s" % got


def test_success_resets_login_escalation():
    p = _pacer()
    p.trip("fliggy", "login")
    p.trip("fliggy", "login")
    for _ in range(3):
        p.note_ok("fliggy", need=1)
    assert p.trip("fliggy", "login") == 900, "成功之后应从 900 重新开始"


def test_other_breaker_kinds_unaffected():
    p = _pacer()
    cd = p.trip("fliggy", "captcha")
    assert cd >= 0, cd


# ---- merged from tests/test_r397_login_not_error.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _store():
    d = tempfile.mkdtemp(prefix="tm_r397_")
    return PriceStorage(os.path.join(d, "prices.db"))


def _feed(st, status, n=1, path="H5"):
    for _ in range(n):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                           path, status, rows=0)


def test_login_not_counted_as_error():
    st = _store()
    _feed(st, "login", 5)
    _feed(st, "error", 2)
    _feed(st, "timeout", 1)
    n = st.path_stats(hours=24)["tongcheng"]
    assert n["login"] == 5, n
    assert n["error"] == 3, n          # error + timeout 才是真基础设施失败


def test_login_bucket_exists_on_paths_too():
    st = _store()
    _feed(st, "login", 4, path="窗历")
    p = st.path_stats(hours=24)["tongcheng"]["paths"]["窗历"]
    assert p["login"] == 4, p
    assert p["error"] == 0, p


def test_buckets_sum_to_attempts():
    """六个桶必须能加总回 attempts——否则有状态在统计里凭空消失。"""
    st = _store()
    for s in ("ok", "calendar", "empty", "login", "blocked",
              "soft_reject", "unsupported", "error", "timeout",
              "parse_error"):
        _feed(st, s, 2)
    n = st.path_stats(hours=24)["tongcheng"]
    keys = ("ok", "empty", "login", "blocked", "soft", "unsupported",
            "error")
    assert sum(int(n.get(k) or 0) for k in keys) == n["attempts"], n


def test_login_does_not_shrink_rate_denominator():
    """login 仍是失败（不进分母剔除），只是不再冒充 error。"""
    st = _store()
    _feed(st, "ok", 5)
    _feed(st, "login", 5)
    n = st.path_stats(hours=24)["tongcheng"]
    assert n["rate"] == 0.5, n
    assert n["rate_excl_empty"] == 0.5, n


# ---- merged from tests/test_r477_login_action_matches_evidence.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_advise_login_carries_surface_evidence():
    from core.pacing import advise
    node = {
        "query_attempts": 17, "query_ok": 0,
        "scopes": {"intl": {"paths": {
            "H5": {"attempts": 17, "login": 13, "ok": 0, "calendar": 0,
                   "empty": 0, "unsupported": 0},
        }}},
    }
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert got["state"] == "login", got
    assert got.get("path") == "H5", "登录判定未回传通路证据：%r" % (got,)
    assert got.get("scope") == "intl"
    assert "H5" in got["hint"]


def test_route_level_login_stays_non_relogin():
    """同一通路其他航线正常出数时不催重登（既有判据不许被本次改动带偏）。"""
    from core.pacing import advise
    node = {
        "query_attempts": 72, "query_ok": 30,
        "scopes": {"intl": {"paths": {
            "H5": {"attempts": 72, "login": 40, "ok": 30, "calendar": 2,
                   "empty": 0, "unsupported": 0},
        }}},
    }
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert got["state"] != "login"
    assert "别急着重登" in got["hint"]


def test_multi_slot_vendor_picks_slot_from_path_evidence():
    """账本判来的登录（无 needs_login）也必须按 adv.path 选端。"""
    w = _w()
    i = w.index("if(_own2.length>1){")
    seg = w[i:w.index("const _open=PACE.detail===k;", i)]
    assert "adv.path" in seg, "多会话分支未读路径证据"
    assert "surface_label" in seg, "按钮未写出是哪一端"
    # 分支不能再被 needs_login 独占门控
    assert "if(_own2.length>1&&v.needs_login)" not in w, \
        "多会话分支仍只在运行时 needs_login 时生效"
    # 兜底仍保留：没有路径证据时用坏槽位
    assert "_bad2" in seg, "缺坏槽位兜底"
    assert "verifyNow(" in seg, "单会话/无槽位时仍要有验证入口"


def test_no_evidence_falls_back_to_vendor_window_not_guessed_end():
    """运行时 needs_login 且两端都「已存待验」时，不得断言是哪一端。

    渲染实测：该载荷下按钮曾写成「去登录 PC」（取首个槽位），而真正被
    拦的是 H5 那份 profile——用户的会话明明没坏，却被指去登另一端。
    无证据时退回厂商级验证窗口（那里打开的就是采集同一份 profile）。
    """
    w = _w()
    i = w.index("if(_own2.length>1){")
    seg = w[i:w.index("const _open=PACE.detail===k;", i)]
    assert "_bad2[0]||null" in seg, "无证据时仍会猜首个槽位"
    assert "_own2[0].key" not in seg, "仍在无证据时落到首个槽位"


def test_top_entry_also_targets_the_evidenced_surface():
    """顶部「去登录」与行内按钮必须同源选端。

    实测隐患：账本说飞猪「国际 H5」被拦，行内已改成「去登录 H5」，但顶部
    `#hauthact` 仍写 dataset.p=<厂商>，点开落到飞猪 PC 登录行——同一屏两个
    「去登录」指向不同端。
    """
    w = _w()
    i = w.index("function healthLoginNudge(")
    seg = w[i:w.index("function healthSlotNote(", i)]
    assert "adv.path" in seg, "顶部入口未读路径证据"
    assert "ha.dataset.p=_keys[0]" in seg, "顶部入口未按证据落到槽位"


# ---- merged from tests/test_r478_relogin_is_an_intervention.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_saved_login_writes_relogin_intervention():
    w = _w()
    # 锚点只取不随提示语变化的前缀：r805cf 起日志会区分「人机验证 / 网页登录」，
    # 写死后缀会让行为完好的用例因文案变化而红（2026-11-02 实测 gate 唯一红项）。
    i = w.index('_State.logger.info("[登录] %s 会话已保存')
    # 终止锚点（r1353）：原来用 `if key == "fliggy_h5":` 当边界，而该分支
    # 已被 r1063 泛化成 `if key != meta.get("plat"):`（所有独立端槽位同款），
    # 用例因此 ValueError 而不是断言失败。改用**紧随其后的语义注释**做边界：
    # 注释描述的是"保存完成后立刻清登录墙记忆"，位置稳定且不含行为代码。
    j = w.index("# r1063 T128：登录成功 → 立刻清登录墙记忆", i)
    seg = w[i:j]
    assert '"relogin"' in seg, "会话保存后未写重登干预账"
    assert "save_intervention(" in seg, "未调用入账接口"
    assert "scope=str(key)" in seg, "槽位未入 scope（PC/H5 无法区分）"
    # 必须真的走 PriceStorage（不是打印日志了事）
    assert "PriceStorage(_anchored(" in seg


def test_relogin_counts_as_manual_boundary_and_maps_to_chinese():
    """重登不属 auto_*，必须能当成效分界；两处溯源都要显示「重登」。"""
    st = io.open(os.path.join(ROOT, "core", "storage.py"),
                 encoding="utf-8", newline="").read()
    assert "substr(action,1,5) <> 'auto_'" in st
    assert not re.search(r"action\s*<>\s*'auto'", st)
    w = _w()
    assert "relogin:'重登'" in w, "干预成效未把 relogin 映射成中文动作名"
    # 两处干预记录渲染（展开溯源 + 行内溯源）都必须走中文映射，
    # 否则读者看到「relogin」对不上面板上的「上次重登」。
    assert w.count("relogin:'重登'") >= 2, "有一处溯源仍直出英文动作名"
    i = w.index("const _acn=({probe:'自检'")
    assert "esc(act)}}" not in w[i:i + 400].replace("title=\"'+esc(act)+'\"", ""), \
        "动作名仍在可见文本里直出英文"


def test_relogin_effect_flows_through_storage():
    """行为级：relogin 落库后，intervention_effect 以它为分界并给出前后对比。"""
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))
    with ps._conn() as c:
        for i in range(4):
            c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status) "
                "VALUES ('2026-10-29 06:0%d:00','fliggy','BKK','CAN',"
                "'2026-11-05','H5','login')" % i)
        for i in range(4):
            c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status) "
                "VALUES ('2026-10-29 07:0%d:00','fliggy','BKK','CAN',"
                "'2026-11-05','H5','ok')" % i)
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy_h5",
                         before="login_wall", note="网页登录保存会话",
                         at="2026-10-29 06:30:00")
    e = ps.intervention_effect("fliggy", 24)
    assert e.get("has") is True
    assert e.get("action") == "relogin", e
    assert e.get("before") == 0.0, e
    assert e.get("after") == 1.0, e
    from core.pacing import effect_verdict
    state, hint, sev = effect_verdict(e)
    assert state in ("improved", "recovered"), (state, hint)
    assert "100%" in hint, hint


# ---- merged from tests/test_r479_relogin_takes_effect.py ----

def _ps():
    """临时库。时间戳必须落在 24h 窗口内（path_stats 按 now 过滤），
    写字面日期会在第二天变成窗口外从而静默零样本。"""
    import os
    from datetime import datetime, timedelta
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    return PriceStorage(os.path.join(d, "t.db"))


def _at(minutes_ago):
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, status, at):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'fliggy','BKK','CAN','2026-11-05','H5',?)",
            (at, status))


def test_login_since_ok_resets_after_a_success():
    ps = _ps()
    stamps = []
    for i in range(12):
        t = _at(120 + i)
        if i == 0:
            last_login = t        # 记录**写入值**；循环后再算 _at(120)
        _row(ps, "login", t)      # 会跨秒，重算会差 1 秒（曾因此偶发红）
    _row(ps, "ok", _at(60))
    for i in range(3):
        _row(ps, "ok", _at(40 - i))
    n = ps.path_stats(24)["fliggy"]
    p = n["paths"]["H5"]
    assert p["login"] == 12, "总登录数仍应保留（历史证据）"
    assert p["login_since_ok"] == 0, "出数后登录连击未清零"
    assert n["last_login_at"] == last_login


def test_still_blocked_after_login_keeps_the_run():
    ps = _ps()
    _row(ps, "ok", _at(200))
    for i in range(9):
        _row(ps, "login", _at(120 - i*5))
    p = ps.path_stats(24)["fliggy"]["paths"]["H5"]
    assert p["login_since_ok"] == 9, "重登后又被拦的连击被吞掉"


def test_advise_stops_nagging_after_relogin_worked():
    from core.pacing import advise
    node = {"query_attempts": 45, "query_ok": 33,
            "scopes": {"intl": {"paths": {"H5": {
                "attempts": 45, "login": 27, "ok": 33, "calendar": 0,
                "empty": 0, "unsupported": 0, "login_since_ok": 0}}}}}
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert got["state"] != "login", "重登已生效仍在催重登：%r" % (got,)
    assert got["action"] != "relogin"


@pytest.mark.parametrize("run,expect_login", [(18, True), (2, False)])
def test_advise_uses_the_run_not_the_window_total(run, expect_login):
    from core.pacing import advise
    node = {"query_attempts": 20, "query_ok": 0,
            "scopes": {"intl": {"paths": {"H5": {
                "attempts": 20, "login": 20, "ok": 0, "calendar": 0,
                "empty": 0, "unsupported": 0, "login_since_ok": run}}}}}
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert (got["state"] == "login") is expect_login, got


# ---- merged from tests/test_r496_relogin_ledger_idempotent.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_relogin_write_is_deduplicated_within_the_same_minute():
    """复现写入逻辑：同分钟重复 → 只落一条；跨分钟 → 各落一条。"""
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))

    import time as _t

    def write(plat, key, at, now=None):
        """与 webui._start_login 里的入账块同构的幂等判断（30 秒窗口）。"""
        now = _t.time() if now is None else now
        dup = False
        for r0 in ps.interventions(plat, 8):
            if (str(r0.get("action")) != "relogin"
                    or str(r0.get("scope")) != str(key)):
                continue
            try:
                ts = _t.mktime(_t.strptime(
                    str(r0.get("at") or "")[:19], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            if abs(now - ts) <= 30:
                dup = True
                break
        if not dup:
            # 必须同时写 at：save_intervention 默认用真实 now 落库，
            # 而比较基准是我们构造的时间戳。不写 at 时两者相差可能远超
            # 30 秒（并发门禁下实测失败），去重逻辑显得「没生效」。
            ps.save_intervention(plat, "relogin", ok=True, scope=str(key),
                                 before="login_wall", note="x", at=at)

    t0 = datetime.now().replace(second=10, microsecond=0)
    a = t0.strftime("%Y-%m-%d %H:%M:%S")
    b = (t0 + timedelta(seconds=21)).strftime("%Y-%m-%d %H:%M:%S")
    c = (t0 + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")

    def _ts(x):
        return _t.mktime(_t.strptime(x, "%Y-%m-%d %H:%M:%S"))

    write("fliggy", "fliggy", a, now=_ts(a))
    write("fliggy", "fliggy", b, now=_ts(b))   # +21 秒：同一次保存的重复写入
    rows = ps.interventions("fliggy", 10)
    assert len(rows) == 1, "30 秒内重复写入未去重：%r" % [
        (r["at"], r["scope"]) for r in rows]

    write("fliggy", "fliggy", c, now=_ts(c))   # +3 分钟：确属另一次登录
    rows = ps.interventions("fliggy", 10)
    assert len(rows) == 2, "跨分钟的第二次登录被误去重：%r" % [
        (r["at"], r["scope"]) for r in rows]

    # 不同槽位不受影响（飞猪 PC 与 H5 是两次独立登录）
    write("fliggy", "fliggy_h5", b, now=_ts(b))
    rows = ps.interventions("fliggy", 10)
    assert len(rows) == 3, "不同槽位被误判为重复：%r" % [
        (r["at"], r["scope"]) for r in rows]


def test_dedup_does_not_inflate_the_success_rate():
    """澄清：重复行**不**放大成功率分母（同秒记录在按 (plat, i) 分组时
    会被合并成一次窗口，n 仍为 1）。所以重复的真实危害不是指标，而是
    **溯源可读性**——用户看到两条一模一样的「重登」，会以为自己按了两次。

    这条把事实钉住，避免后人（包括我自己）再次基于「重复会放大分母」
    这个错误前提去改指标逻辑。
    """
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))
    now = datetime.now() - timedelta(minutes=30)
    at = now.strftime("%Y-%m-%d %H:%M:%S")
    with ps._conn() as cc:
        cc.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'fliggy','BKK','CAN','2026-11-05','H5','ok')",
            ((now + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),))
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy_h5", at=at)
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy_h5", at=at)
    assert len(ps.interventions("fliggy", 10)) == 2, "重复行确实落了两条"
    r = ps.intervention_success_rate()
    assert r["relogin"]["n"] == 1, (
        "同秒重复被合并后 n 应为 1；若变成 2 说明分组逻辑变了，"
        "此时重复才会真的放大分母，需要重新评估去重策略：%r" % (r,))


def test_write_site_is_guarded():
    """写入点必须有 30 秒窗口去重，否则重复会再次出现。

    为什么是 30 秒而不是「同一分钟」：同一分钟内用户真的重试一次
    （第一次没通过、立刻再登）是**另一次干预**，按分钟去重会把真实重试
    吞掉。而同一次保存的重复写入时间戳精确到秒完全一致，30 秒足够挡住。
    """
    w = webui_full_src()
    i = w.index('meta["plat"], "relogin"')
    seg = w[max(0, i - 2200):i]
    assert "_dup" in seg, "重登入账缺幂等判断"
    assert 'r0.get("scope")' in seg, \
        "去重未按槽位区分（飞猪 PC/H5 是两次独立登录）"
    assert "<= 30" in seg, "去重未按 30 秒时间窗（秒差 1–2 秒的重复会漏掉）"
    assert "mktime" in seg and "strptime" in seg, \
        "去重未按时间差比较（字符串相等挡不住跨秒的重复）"


# ---- merged from tests/test_r678_login_entry_is_usable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
# 明确不是「用户可登录页面」的措辞（WAF/拒绝/停服）
BLOCK_WORDS = ("WAF", "安全检测", "Web应用防火墙", "无法继续", "访问被拒绝",
               "Forbidden", "站点已停止")




def _open(browser, url):
    ctx = browser.new_context(
        user_agent=UA_IPHONE, viewport={"width": 390, "height": 844},
        is_mobile=True, has_touch=True, locale="zh-CN",
        timezone_id="Asia/Shanghai")
    try:
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=35000)
            pg.wait_for_timeout(2500)
        except Exception as e:
            pytest.skip("站点不可达（外部状态，不作缺陷）：%s" % type(e).__name__)
        return {
            "url": pg.url, "title": pg.title(),
            "text": pg.inner_text("body")[:1500],
            "password": pg.locator("input[type=password]").count(),
            "tel": pg.locator(
                "input[type=tel],input[inputmode=numeric]").count(),
        }
    finally:
        ctx.close()


def _assert_login_surface(rec, name):
    hit = [w for w in BLOCK_WORDS if w in (rec["title"] + rec["text"])]
    assert not hit, "%s 登录入口落到拦截页（%s）：%s" % (
        name, "/".join(hit), rec["url"])
    assert rec["password"] + rec["tel"] > 0 or "登录" in rec["text"], (
        "%s 登录入口没有任何登录控件/文案，用户无从登录：%s"
        % (name, rec["url"]))






# ---- merged from tests/test_r708_login_row_fits_all_channels.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def _login_card_rule(src):
    """取**含 grid-template-columns** 的那条 #loginRows .lgcard 规则。

    同选择器在样式表里有多条（视觉态/间距态各一条），不能取第一条：
    第一条只管背景与边框，没有列定义。
    """
    for m in re.finditer(r"#loginRows \.lgcard\{([^}]*)\}", src):
        if "grid-template-columns" in m.group(1):
            return m.group(1)
    raise AssertionError("找不到定义列宽的 #loginRows .lgcard 规则")


def test_name_column_is_content_sized():
    """第一列不能写死像素：多渠道接入后最长名字会变。"""
    rule = _login_card_rule(_webui())
    m = re.search(r"grid-template-columns:([^;!]+)", rule)
    assert m, rule
    first = m.group(1).strip().split()[0]
    assert not re.match(r"^\d+px$", first), (
        "名字列写死成 %s —— 加第 6/7 家渠道（App + 真机徽标）就会裁字" % first)
    assert ("max-content" in first) or ("auto" in first), first


def test_name_column_never_clips():
    """名字单元格不能带 text-overflow:clip/ellipsis（等价于承认装不下）。"""
    src = _webui()
    for m in re.finditer(r"#loginRows[^{]*\.lgname[^{]*\{([^}]*)\}", src):
        body = m.group(1)
        assert "text-overflow" not in body, (
            "登录行名字被设了 text-overflow：%s" % body[:120])


def test_seven_channels_share_one_list():
    """七家渠道必须落在同一个列表/同一套行样式里。

    否则「只有 App 行走另一套布局」——正是用户说的「没把原来的渠道
    一起考虑」。判据：渲染行数由 APP 渠道 + 浏览器渠道共同决定，
    且没有第二份 #loginRows 之类的独立容器。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    assert len(APP_CHANNELS) + len(BROWSER_CHANNELS) >= 7
    src = _webui()
    assert src.count('id="loginRows"') == 1, "登录行容器不止一个"


def test_app_channel_names_come_from_single_source():
    """渠道显示名不得在登录区另抄一份（App 名要与 SRX_PLATS 同源）。

    判据只看**代码**：先把块注释/行注释剥掉，注释里提到「智行 App」
    是在解释历史缺陷，不算硬编码。
    """
    src = _webui()
    assert "APP_PLAT_NAME" in src, "App 渠道中文名应有单源表"
    m = re.search(r"function renderLoginCards[\s\S]{0,8000}", src)
    assert m, "找不到 renderLoginCards"
    body = m.group(0)
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    body = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.splitlines())
    assert "智行 App" not in body, (
        "renderLoginCards 代码里硬编码了 App 名，应走 APP_PLAT_NAME 单源")
