# -*- coding: utf-8 -*-
"""r474: 把「原始需求清单」固化为静态契约（每项一条断言）。

这不是替代既有细粒度契约，而是给本轮目标（统一登录 / 节流归位 /
健康多维 / 面板质感 / 干预四性 / 进程健壮）提供一张总表：
任何一项被后续重构抹掉，这里会先红。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def _p():
    return io.open(os.path.join(ROOT, "core", "pacing.py"), encoding="utf-8",
                   newline="").read()


def test_goal_a_all_vendors_require_login():
    """统一「必须登录」，废弃「建议登录」。"""
    from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER
    assert len(LOGIN_SLOT_ORDER) == 6
    assert all(LOGIN_SLOTS[k].get("requirement") == "必须登录"
               for k in LOGIN_SLOT_ORDER)
    w = _w()
    # 用户可见文案里不得再出现该档（只允许注释里说明历史）
    vis = re.sub(r"/\*.*?\*/", "", w, flags=re.S)
    assert "建议登录" not in vis


def test_goal_b_independent_slots_when_cookies_not_shared():
    """cookie 不共享的必须独立登录：飞猪 PC / H5 各自入口。"""
    from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER
    fl = [k for k in LOGIN_SLOT_ORDER if LOGIN_SLOTS[k]["plat"] == "fliggy"]
    assert fl == ["fliggy", "fliggy_h5"]
    w = _w()
    assert "lgOpenFliggy" in w
    assert "loginStart(" in w
    assert "两域会话不共享" in w


def test_goal_c_pacing_lives_in_health_card_only():
    """节流实时面板只能在渠道健康卡内；参数从那里一键直达配置分区。

    r638 起参数集中在独立的「渠道节流」分区（之前是全局参数里的锚点），
    所以判据看「直达函数切到某个配置分区并聚焦节流控件」，不再钉死锚点 id。
    """
    w = _w()
    assert w.count('id="paceBox"') == 1
    assert "healthcard .hpace" in w
    assert "cfgGoThrottle" in w, "健康卡没有参数直达入口"
    fn = w[w.index("function cfgGoThrottle("):]
    fn = fn[:fn.index("async function health(")]
    assert "showCfgPanel(" in fn and "glbQs" in fn, (
        "直达函数没有切分区并聚焦节流控件：%r" % fn[:160])


def test_goal_d_health_has_five_dimensions():
    """厂商 / 分域 / 分通路 / 分会话 / 诊断卡同维。"""
    w = _w()
    assert "shownRate" in w, "缺厂商级徽标（在用口径）"
    assert "scoped('dom','国内')" in w, "缺分域"
    assert "dead.forEach(pp=>pws.push(pathCN(pp)+' 退役'))" in w, \
        "缺分通路（含退役；r659 起名字走 pathCN）"
    assert "function healthSlotNote(" in w, "缺分会话"
    assert "_attach_diag_slots" in w and "dead_surfaces" in w, "缺诊断卡同维"


def test_goal_e_panel_typography_and_interaction():
    """节流面板：字号三档 / 零硬编码色 / 焦点保持 / 溯源贴身。"""
    w = _w()
    a = w.index(".pace{display:flex")
    b = w.index("@media(max-width:480px){", a)
    seg = w[a:b]
    assert sorted(set(re.findall(r"font-size:(\d+)px", seg))) == \
        ["11", "12", "16"]
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", seg)
    assert "PACE.focusKey" in w and "data-pk" in w
    assert "paceDetail" in w
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in w


def test_goal_f_interventions_are_automatic_configurable_and_idempotent():
    """可自动化 / 可配置 / 可开关 / 可执行 / 可幂等 / 可生效。"""
    p, w = _p(), _w()
    # 自动化
    assert "def observe(" in p and "def set_health(" in p and "def advise(" in p
    # 可配置 + 可开关
    for k in ("breaker_enabled", "warmup_enabled", "fast_ttl_min",
              "min_gap_s", "per_minute", "scan_quiet_start",
              "health_penalty_enabled"):
        assert k in w, "缺配置项 " + k
    assert "health_penalty_enabled" in p
    # 可执行
    for ep in ("/api/pacing/reset", "/api/channel/warmup",
               "/api/channel/probe", "/api/channel/verify"):
        assert ep in w, "缺干预接口 " + ep
    # 可幂等
    assert "PACE_BUSY" in w
    # 可生效
    s = io.open(os.path.join(ROOT, "core", "storage.py"),
                encoding="utf-8", newline="").read()
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    assert "def intervention_effect" in s and "save_intervention" in m


def test_goal_g_states_are_clear_and_aligned():
    """状态清晰：全状态自述；两面板同数（遮蔽只认服务端 demo）。"""
    w = _w()
    for lab in ("冷却 ", "需登录", "路径劣化", "软拒待预热", "恢复中",
                "仅有日历", "数据陈旧", "成功率低", "待首轮"):
        assert ("lab='" + lab + "'") in w
    assert "暂无通路账" in w, "path_degraded 兜底仍在凭空断言"
    assert "右侧为停更前的历史口径" in w, "陈旧状态未点明右半口径"
    assert "_maskSynth" in w and "_pthDemo" in w, "遮蔽未按服务端标记"
    p = _p()
    # r479：判据从「24h 总登录数」换成「最近一次出数之后的登录连击数」，
    # 否则重登生效后旧窗口里的 login 行仍会继续催重登。
    assert "_login_n >= 10" not in p, "仍在用窗口总登录数判定（重登后会重复催）"
    assert "_ln_run >= 8" in p and "_okish * 5 <= _n" in p, \
        "登录墙判定缺「本路是否几乎不出数」的第三条件"


def test_goal_h_process_level_robustness():
    """进程级：多线程不阻塞 / 并发上限 / 渠道互斥 / 日志可观测。"""
    w = _w()
    base = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                   encoding="utf-8", newline="").read()
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    assert "ThreadingHTTPServer" in w and "daemon_threads" in w
    assert "BoundedSemaphore(2)" in base
    assert "def platform_lock" in base
    assert "[干预]" in m and "[自检]" in m

def test_auto_interventions_are_audited_without_polluting_manual_effect():
    """自动熔断/降频也要留痕，且不能污染「手动干预成效」的分界。

    实测：干预账在 10-27 03:30 之后 35 小时零记录，而同期采集正常跑——
    因为只有手动 warm/verify/probe 写库，系统自动做过什么、冷却多久，
    事后完全查不到（可观测性缺口）。
    现自动熔断入账 action=auto_trip。两条连带约束：
      1) 前端不得把 auto_* 的 ok=0 染红写成「失败」——那是它的正常语义；
      2) intervention_effect 的分界只能用**人工干预**，否则自动事件会把
         用户上一次手动干预的前后对比冲掉。
    """
    import os
    import tempfile
    from core.storage import PriceStorage
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    assert '"auto_trip"' in m, "自动熔断未入账"
    st = io.open(os.path.join(ROOT, "core", "storage.py"),
                 encoding="utf-8", newline="").read()
    assert "substr(action,1,5) <> 'auto_'" in st,         "干预成效分界未排除自动事件"
    w = _w()
    assert "/^auto_/.test(act)" in w, "前端未区分自动动作与人工结果"

    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))
    ps.save_intervention("ctrip", "auto_trip", ok=False, scope="ip",
                         note="自动熔断 ip，冷却 300s")
    ps.save_intervention("ctrip", "probe", ok=True, rows=5)
    e = ps.intervention_effect("ctrip", 24)
    assert e.get("has") and e.get("action") == "probe",         "自动事件污染了手动干预的对比分界"

def test_ledger_login_wall_lights_the_top_entry():
    """账本判定的会话失效必须点亮顶部「去登录」，否则用户根本不知道要重登。

    实测：节流面板已写「需登录 | 国际 H5 近 24h 被登录墙拦 13/17 次、仅 0 次出数」，
    而健康卡顶部 `#hauthact` 仍是 hidden——它只看会话槽位的 needs_login
    （"已保存"就算好），不看账本里的登录墙统计。用户不点开节流面板就完全
    没有提示，属「可干预的及时性」缺口。
    现由 `healthLoginNudge(loadPacing 的载荷)` 点亮，判据与节流行同源
    （advice.state==='login'），不另造一套。
    """
    w = _w()
    assert "function healthLoginNudge(" in w
    i = w.index("function healthLoginNudge(")
    seg = w[i:i + 1200]
    assert "advice||{}).state==='login'" in seg, "未按 advice 判会话失效"
    assert "ha.hidden=false" in seg, "点亮动作缺失"
    assert "if(!ha||!ha.hidden)return" in seg, "已点亮时会被覆盖"
    assert "healthLoginNudge(j)" in w, "loadPacing 未调用"


def test_goal_i_intervention_success_rate_is_a_real_metric():
    """「干预成功率」是原始需求点名的指标，不能只有「上次干预前后对比」。

    intervention_effect 回答「上一次干预效果如何」；这里要的是
    「这类按钮一共按了 N 次，几次真把渠道救回来」——选哪个钮的依据。
    """
    s = io.open(os.path.join(ROOT, "core", "storage.py"),
                encoding="utf-8", newline="").read()
    assert "def intervention_success_rate(" in s, "缺干预成功率指标"
    assert "healed" in s and "unhealed" in s
    # 未采集的窗口不得算失败，也不得被静默丢弃（r506 起单列 unjudged）
    assert "不计入分母" in s, "未采集窗口的分母口径没有写明"
    assert "unjudged" in s, "判不了的窗口没有被单列出来"
    w = _w()
    assert "近 7 天成功率" in w, "指标没有出现在面板上"
    assert "样本不足" in w, "样本不足时仍报百分比"
