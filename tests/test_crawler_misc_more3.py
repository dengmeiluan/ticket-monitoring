# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1770_train_recover.py
- tests/test_r607_h5_path_has_one_name.py
- tests/test_r913_policy_engine.py
- tests/test_r930_ready_budget.py
- tests/test_r956_rotation_records_normally.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import logging
import os
import re
import sys
import time

from core.policy import ChannelPolicy, PolicyEngine
from core.riskscore import LoginLedger
from core.yield_stats import YieldLedger
from crawlers.app_base import wait_ready
from crawlers.app_tongcheng import AppTongchengCrawler, is_train_page
from crawlers.base import BaseCrawler, SessionBusyError
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r1770_train_recover.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    warning = info


class _Dev:
    """假设备：dump 依次返回给定 XML；tap 记录调用。"""

    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []

    def dump(self):
        return self.pages[0] if self.pages else ""

    def tap(self, x, y):
        self.taps.append((x, y))
        if len(self.pages) > 1:
            self.pages.pop(0)
        return True

    def keyevent(self, k):
        return True

    def current_activity(self):
        return "com.tongcheng.android/.Main"


def _train():
    return io.open(TRAIN, encoding="utf-8", errors="replace").read()


def test_recover_helper_switches_back_to_flight_tab():
    xml = _train()
    c = AppTongchengCrawler({}, _Log())
    c.paths = []
    c.user_data_root = os.path.join(ROOT, "_scratch", "_u")
    # 第一次 dump 是火车票页，tap 之后模拟「变成机票表单」
    flight = xml.replace("查询火车票", "机票查询")
    dev = _Dev([xml, flight])
    page = c._recover_flight_tab(dev)
    assert page, "没切回机票"
    assert not is_train_page(page), "仍是火车票页"
    assert dev.taps, "没有点机票 tab"


def test_failure_note_distinguishes_train_page():
    src = io.open(os.path.join(ROOT, "crawlers", "app_tongcheng.py"),
                  encoding="utf-8").read()
    assert "_recover_flight_tab" in src, "没有恢复助手"
    assert "点城市位后落到火车票页" in src, "失败时没说清是火车票页"
    assert "切回机票后仍打不开城市页" in src, "恢复失败的记账缺失"


# ---- merged from tests/test_r607_h5_path_has_one_name.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                   encoding="utf-8", newline="").read()


def test_fallback_does_not_prefix_paths():
    src = _src()
    i = src.index("def _h5_fallback")
    seg = src[i:i + 1400]
    assert 'path="H5:"' not in seg, (
        "兜底仍在给 H5 采集器的路径加前缀（会产生 H5:H5 双名）")
    assert "self.paths.extend(" in seg, "兜底没有原样透传路径"


def test_h5_crawler_owns_the_path_name():
    """名字必须来自 H5 采集器本身——它是这条通路的唯一记账方。"""
    h5 = io.open(os.path.join(ROOT, "crawlers", "fliggy_h5.py"),
                 encoding="utf-8", newline="").read()
    assert 'path_note("H5"' in h5, "H5 采集器没有用 H5 作为路径名"


def test_fallback_notes_use_the_same_constant():
    """兜底自己的两条记账（缺会话 / 异常）也要用同一个名字。"""
    src = _src()
    i = src.index("def _h5_fallback")
    seg = src[i:i + 1400]
    assert "_FLIGGY_H5_PATH" in seg, "兜底记账没有走统一常量"
    assert not re.search(r'path_note\("H5"', seg), (
        "还有写死的 \"H5\" 字面量（与常量并存迟早漂移）")


def test_no_doubled_name_reaches_the_ledger():
    """真跑一次包装逻辑：并进 PC 采集器的路径不能出现 H5:H5。"""
    import sys
    sys.path.insert(0, ROOT)
    from crawlers.fliggy import FliggyCrawler, _FLIGGY_H5_PATH

    class FakeH5:
        session_state_path = __file__      # 存在即可，走正常分支
        paths = [{"path": _FLIGGY_H5_PATH, "status": "ok", "rows": 2},
                 {"path": "listingsearch", "status": "ok", "rows": 1}]

        def fetch(self, *a, **k):
            return [{"price": 1}]

    c = object.__new__(FliggyCrawler)
    c.config = {}
    c.logger = __import__("logging").getLogger("t")
    c.paths = []
    # 只测包装段：替换掉真实 H5 类。`_h5_fallback` 现在从
    # `crawlers.fliggy_h5` 里 import（不是 `crawlers.fliggy` 的命名空间），
    # 打在旧位置等于没打补丁——假替身不生效，真 H5 找不到会话直接返回，
    # 账本为空，测试就以「H5 不在 names」假红。补丁必须打在 import 源上。
    import crawlers.fliggy_h5 as mod
    real = mod.FliggyH5Crawler
    mod.FliggyH5Crawler = lambda *a, **k: FakeH5()
    try:
        c._h5_fallback("SHA", "BJS", ["2026-11-01"])
    finally:
        mod.FliggyH5Crawler = real
    names = [p.get("path") for p in c.paths]
    assert "H5:H5" not in names, "账本里出现了双名前缀：%s" % names
    assert "H5:H5:listingsearch" not in names, names
    assert "H5" in names, names


# ---- merged from tests/test_r913_policy_engine.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r913")


def _eng(tmp_path, plat="", **cfg):
    """策略引擎。``plat`` 传给 profile —— 账本与状态都落 user_data/<plat>/。"""
    cfg.setdefault("user_data_dir", str(tmp_path))
    return PolicyEngine(cfg, repo_root=".", profile=plat)


def _seed_login(tmp_path, plat, streak=3, device_risk=True, now=1000.0):
    """在 ``<tmp>/<plat>/login_ledger.json`` 里造登录连击（真实路径）。"""
    path = os.path.join(str(tmp_path), plat)
    os.makedirs(path, exist_ok=True)
    ll = LoginLedger(os.path.join(path, "login_ledger.json"))
    for i in range(streak):
        ll.note_result(plat, False, device_risk=device_risk, now=now + i)
    return ll


def _seed_yield(tmp_path, plat, pattern, rows=1):
    """``pattern`` 是 bool 序列：True=成功。"""
    path = os.path.join(str(tmp_path), plat)
    os.makedirs(path, exist_ok=True)
    yl = YieldLedger(os.path.join(path, "yield_stats.json"))
    for ok in pattern:
        yl.note(plat, "pc", ok, rows=rows)
    return yl


# ---------------------------------------------------------------------------
# 1. 默认与档位
# ---------------------------------------------------------------------------
def test_default_is_healthy_and_allow(tmp_path):
    pol = _eng(tmp_path, "ctrip").decide("ctrip", now=1000.0)
    assert pol.state == "healthy" and pol.allow is True
    assert pol.pace_factor == 1.0 and pol.need_warmup is False
    assert pol.rotate is False and pol.wait_s(now=1000.0) == 0


def test_slow_level_degrades_but_allows(tmp_path):
    pol = _eng(tmp_path, "ctrip").decide("ctrip", now=1000.0, captcha=True,
                                         login_wall=True)
    assert pol.allow is True                 # 48 分只是 slow 档
    assert pol.state == "degraded"
    assert pol.pace_factor == 2.5
    assert pol.need_warmup is True


def test_pause_level_slows_to_max_but_still_allows(tmp_path):
    e = _eng(tmp_path, "ctrip")
    pol = e.decide("ctrip", now=1000.0, statuses=[429], soft=True,
                   rate_pressure=True, login_wall=True)
    assert pol.score >= 65
    assert pol.allow is True and pol.state == "degraded"
    assert pol.pace_factor == 3.0            # 短时冷却交给熔断器
    assert any("熔断器" in r for r in pol.reasons)
    assert pol.wait_s(now=1000.0) == 0


def test_human_level_blocks_and_persists(tmp_path):
    e = _eng(tmp_path, "ctrip")
    _seed_login(tmp_path, "ctrip", streak=3, now=1000.0)
    pol = e.decide("ctrip", now=1005.0, identity_score=0, stealth_score=0,
                   captcha=True)
    assert pol.score >= 80, pol.score
    assert pol.allow is False and pol.state == "blocked"
    assert pol.wait_s(now=1005.0) >= 1800
    # 状态落盘：下一轮即使不带信号也必须继续停
    pol2 = e.decide("ctrip", now=1100.0)
    assert pol2.allow is False and pol2.state == "blocked"
    # 到期后进 rehab
    pol3 = e.decide("ctrip", now=1005.0 + 3700)
    assert pol3.allow is True and pol3.state == "rehab"
    assert pol3.pace_factor == 1.5 and pol3.need_warmup is True


def test_login_backoff_degrades_not_blocks(tmp_path):
    _seed_login(tmp_path, "qunar", streak=3, now=1000.0)
    pol = _eng(tmp_path, "qunar").decide("qunar", now=1001.0)
    assert pol.allow is True                  # 不许关闸：登录墙要照记照跑
    assert pol.state == "rehab"
    assert pol.pace_factor >= 1.5
    assert any("登录退避" in r for r in pol.reasons)


# ---------------------------------------------------------------------------
# 2. 产量只调速度
# ---------------------------------------------------------------------------
def test_good_yield_allows_faster(tmp_path):
    _seed_yield(tmp_path, "fliggy", [True] * 40, rows=3)
    pol = _eng(tmp_path, "fliggy").decide("fliggy", now=1000.0)
    assert pol.state == "healthy" and pol.allow is True
    assert pol.pace_factor == 0.8
    assert any("可加频" in r for r in pol.reasons)


def test_bad_yield_degrades_without_blocking(tmp_path):
    _seed_yield(tmp_path, "tuniu", [True] * 3 + [False] * 7)
    pol = _eng(tmp_path, "tuniu").decide("tuniu", now=1000.0)
    assert pol.allow is True                 # 真无票/解析失败不等于被封
    assert pol.state == "degraded"
    assert pol.pace_factor >= 1.5
    assert any("因果链" in r for r in pol.reasons)


def test_few_samples_do_not_move_the_needle(tmp_path):
    _seed_yield(tmp_path, "ctrip", [True] + [False] * 2)
    pol = _eng(tmp_path, "ctrip").decide("ctrip", now=1000.0)
    assert pol.state == "healthy" and pol.pace_factor == 1.0
    assert any("不据此调整" in r for r in pol.reasons)


def test_degraded_is_sticky_for_one_round_then_expires(tmp_path):
    """一轮滑块的证据要留到下一轮，但不能永久粘住。"""
    e = _eng(tmp_path, "qunar")
    # 滑块 + 登录墙 = 48 分 → degraded，余温 60min
    e.decide("qunar", now=1000.0, captcha=True, login_wall=True)
    pol = e.decide("qunar", now=1400.0)              # 不带信号，仍在窗口内
    assert pol.state == "degraded" and pol.pace_factor >= 2.5
    assert any("余温" in r for r in pol.reasons)
    later = e.decide("qunar", now=1000.0 + 3700)     # 窗口过期
    assert later.state == "healthy"


# ---------------------------------------------------------------------------
# 3. 只读查询不推进状态机
# ---------------------------------------------------------------------------
def test_two_way_queries_do_not_write_state(tmp_path):
    e = _eng(tmp_path, "ctrip")
    e.decide("ctrip", now=1000.0, identity_score=0, stealth_score=0,
             captcha=True, two_way=True)
    assert not os.path.isfile(os.path.join(str(tmp_path), "ctrip",
                                           "policy_state.json"))
    snap = e.snapshot(plats=["ctrip", "qunar"], now=1000.0)
    assert set(snap) == {"ctrip", "qunar"}
    assert snap["ctrip"]["allow"] is True     # 没喂信号 → 默认放行
    assert not os.path.isfile(os.path.join(str(tmp_path), "ctrip",
                                           "policy_state.json"))


def test_state_file_is_valid_json(tmp_path):
    e = _eng(tmp_path, "ctrip")
    _seed_login(tmp_path, "ctrip", streak=3, now=1000.0)
    e.decide("ctrip", now=1005.0, identity_score=0, stealth_score=0,
             captcha=True)
    with open(os.path.join(str(tmp_path), "ctrip", "policy_state.json"),
              encoding="utf-8") as f:
        d = json.load(f)
    assert d["ctrip"]["state"] == "blocked"
    assert d["ctrip"]["until"] > 1005.0


# ---------------------------------------------------------------------------
# 4. 接线：闸门 + 关闸轮次不入账
# ---------------------------------------------------------------------------
def _mk(name, runner, cfg):
    class _C(BaseCrawler):
        def fetch(self, fc, tc, dates, ret_date=""):
            return runner(self)
    _C.name = name
    return _C(cfg, _LOG)


def test_gate_blocks_when_state_file_says_blocked(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}
    called = []
    c = _mk("ctrip", lambda s: called.append(1) or [], cfg)
    eng = c._policy()
    _seed_login(tmp_path, "ctrip", streak=3, now=time.time())
    pol = eng.decide("ctrip", now=time.time(), identity_score=0,
                     stealth_score=0, captcha=True)
    assert pol.allow is False
    out = c.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert out == [] and called == []          # fetch 根本没被调用
    assert c.policy_blocked is True
    assert c.last_policy["state"] == "blocked"
    # 关闸轮次不计入爬取率
    assert c._yield_ledger().samples("ctrip") == 0


def test_gate_allows_healthy_channel(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}
    called = []

    def _run(s):
        called.append(1)
        s.path_note("pc", "ok", rows=2)
        return [1, 2]
    c = _mk("ctrip", _run, cfg)
    assert c.safe_fetch("SHA", "NRT", ["2026-11-16"]) == [1, 2]
    assert called == [1] and c.policy_blocked is False
    assert c._yield_ledger().samples("ctrip") == 1


def test_round_feedback_persists_degraded(tmp_path):
    """本轮发生滑块 → 下一轮即使没信号也按降档走（余温窗口内）。"""
    cfg = {"user_data_dir": str(tmp_path)}

    def _run(s):
        s.path_note("pc", "blocked", detail="滑块验证")
        return []
    c = _mk("qunar", _run, cfg)
    c.safe_fetch("SHA", "NRT", ["2026-11-16"])
    with open(os.path.join(str(tmp_path), "qunar", "policy_state.json"),
              encoding="utf-8") as f:
        assert json.load(f)["qunar"]["state"] in ("degraded", "watch")
    pol = c._policy_now(two_way=True)
    assert pol.pace_factor >= 1.5


def test_sleep_scales_with_policy(tmp_path, monkeypatch):
    import crawlers.base as base_mod
    cfg = {"user_data_dir": str(tmp_path), "delay_min": 1, "delay_max": 2}
    c = _mk("ctrip", lambda s: [], cfg)
    seen = []
    monkeypatch.setattr(base_mod.time, "sleep", lambda v: seen.append(v))
    c._sleep()
    assert 1.0 <= seen[-1] <= 2.0                 # healthy → 原区间
    c._policy_cache = (time.time(), ChannelPolicy("ctrip", "degraded",
                                                  True, 0, 2.5))
    for _ in range(20):
        c._sleep()
    assert all(1.0 <= v <= 5.0 for v in seen[1:])  # 上限被放大
    assert max(seen[1:]) > 2.0


def test_policy_gate_switch_disables_blocking(tmp_path):
    """``policy_gate: false`` 要一键回到旧行为，但账本照记。"""
    cfg = {"user_data_dir": str(tmp_path), "policy_gate": "false"}
    called = []

    def _run(s):
        called.append(1)
        s.path_note("pc", "ok", rows=1)
        return [1]
    c = _mk("ctrip", _run, cfg)
    eng = c._policy()
    _seed_login(tmp_path, "ctrip", streak=3, now=time.time())
    eng.decide("ctrip", now=time.time(), identity_score=0, stealth_score=0,
               captcha=True)
    assert c.safe_fetch("SHA", "NRT", ["2026-11-16"]) == [1]
    assert called == [1] and c.policy_blocked is False
    assert c._yield_ledger().samples("ctrip") == 1      # 度量不受开关影响


def test_busy_still_wins_over_policy(tmp_path):
    """抢锁失败仍是 busy：不写账本、不改策略状态。"""
    cfg = {"user_data_dir": str(tmp_path)}

    def _busy(s):
        raise SessionBusyError("busy")
    c = _mk("ctrip", _busy, cfg)
    assert c.safe_fetch("SHA", "NRT", ["2026-11-16"]) == []
    assert c.last_busy is True
    assert c._yield_ledger().samples("ctrip") == 0
    assert not os.path.isfile(os.path.join(str(tmp_path), "ctrip",
                                           "policy_state.json"))


# ---- merged from tests/test_r930_ready_budget.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class FakeDev:
    """按脚本逐帧返回 dump；``delay`` 模拟单帧耗时。"""

    def __init__(self, frames, delay=0.0):
        self.frames = list(frames)
        self.delay = delay
        self.n = 0
        self.dumps = 0

    def dump(self):
        self.dumps += 1
        if self.delay:
            time.sleep(self.delay)
        i = min(self.n, len(self.frames) - 1)
        self.n += 1
        return self.frames[i]


HOME = '<node text="机票查询" />'
DIALOG = '<node text="机票查询" /><node text="Search_Calendar_Dialog_Title" />'
OTHER = '<node text="选择城市" />'


# ---------------------------------------------------------------------------
# 1. 正常路径
# ---------------------------------------------------------------------------
def test_ready_when_two_stable_frames():
    d = FakeDev([HOME, HOME, HOME])
    ok, xml, why = wait_ready(d, "机票查询", interval=0)
    assert ok is True and "机票查询" in xml


def test_residual_dialog_is_not_ready():
    """残留日历弹层里也有「机票查询」，但那是未就绪。"""
    d = FakeDev([DIALOG, HOME, HOME])
    ok, _, _ = wait_ready(d, "机票查询",
                          exclude=("Search_Calendar_Dialog_Title",),
                          interval=0)
    assert ok is True
    assert d.dumps >= 3          # 跳过第一帧弹层


def test_never_ready_reports_frames():
    d = FakeDev([OTHER])
    ok, _, why = wait_ready(d, "机票查询", frames=4, base_s=0.01,
                            interval=0)
    assert ok is False
    assert "未就绪" in why and "机票查询" in why


# ---------------------------------------------------------------------------
# 2. 帧数预算（核心修复）
# ---------------------------------------------------------------------------
def test_frame_budget_is_respected():
    """帧数上限必须生效——慢机上不能无限等。"""
    d = FakeDev([OTHER], delay=0.0)
    wait_ready(d, "机票查询", frames=5, base_s=999, interval=0)
    assert d.dumps == 5, d.dumps


def test_slow_first_frame_extends_deadline():
    """首帧慢 → 放宽总时长（否则慢机 3 帧就撞死）。"""
    # 每帧 0.05s，base_s 极小：若不放宽，帧数还没用完就超时退出
    d = FakeDev([OTHER, OTHER, OTHER, HOME, HOME], delay=0.05)
    ok, _, _ = wait_ready(d, "机票查询", frames=6, base_s=0.01,
                          slow_s=5, slow_frame_s=0.01, interval=0)
    assert ok is True, "首帧慢时没有放宽总时长"
    assert d.dumps >= 5


def test_stable_counter_resets_on_bad_frame():
    """中间夹一帧坏页面，连续计数要重置（否则残留弹层被当首页）。"""
    d = FakeDev([HOME, OTHER, HOME, HOME], delay=0.0)
    ok, _, _ = wait_ready(d, "机票查询", interval=0, stable=2)
    assert ok is True
    assert d.dumps >= 4


def test_single_stable_frame_when_stable_1():
    d = FakeDev([HOME], delay=0.0)
    ok, _, _ = wait_ready(d, "机票查询", interval=0, stable=1)
    assert ok is True and d.dumps == 1


# ---------------------------------------------------------------------------
# 3. 源码钉：智行改成了帧预算
# ---------------------------------------------------------------------------
def test_zhixing_uses_frame_budget():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    assert "frames < 14" in src, "智行等首页仍没有帧数预算"
    assert "time.time() + 150" in src, "智行没有慢机自适应放宽"
    assert "for _ in range(6)" in src, "BACK 回退仍是 4 级（两层弹层会差一步）"
    # 失败文案必须报出**实际帧数与耗时**，便于下次判断是慢还是真打不开
    assert "等 %d 帧" in src


def test_await_home_also_uses_frame_budget():
    """同一策略的第二处：`_await_home` 也必须是帧预算。

    2026-11-04 复查发现 `_await_home` 仍是纯秒数（默认 30s）。慢机
    （5 个浏览器渠道同时占 CPU，单帧 ~20s）30s 只够 1–2 帧，于是判
    「没取到首页（dump 连续为空），无法判断当前档位」——看着像
    uiautomator 挂了，其实只是慢。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    i = src.find("def _await_home")
    assert i > 0
    seg = src[i:i + 1800]
    assert "frames: int = 10" in seg, "_await_home 没有帧预算参数"
    assert "for _ in range(max(2, int(frames)))" in seg, \
        "_await_home 仍按纯时间循环"


# ---- merged from tests/test_r956_rotation_records_normally.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

QUNAR_PY = os.path.join(ROOT, "crawlers", "qunar.py")


def _fetch_body():
    src = open(QUNAR_PY, encoding="utf-8").read()
    i = src.find("    def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j]


def _record_line(body):
    """返回**记账那一行**（赋值给 `_intl_route_seen[...]`）。

    不能直接用 `find("_intl_route_seen[")`：第一处命中其实是**读**
    （`float(self._intl_route_seen.get(_rk_key) or 0)`），
    拿读的位置去判结构会得出完全错误的结论。
    """
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith("self._intl_route_seen[") and "] =" in s:
            return ln
    return None


# ---------------------------------------------------------------------------
# 1. 结构：记账必须在让位块**外面**
# ---------------------------------------------------------------------------
def _guard_of(body, rec):
    """往上找**最近的一行可执行代码**（跳过注释/空行）作为 rec 的守卫。"""
    i = body.index(rec)
    head = body[:i].splitlines()
    for ln in reversed(head):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        return s
    return ""


def test_record_is_outside_the_quiet_branch():
    """记账不能只在"让位窗口激活时放行"那一支里。

    **不能用缩进判断**：旧写法（藏在让位块内）和新写法（块外的独立
    `if _is_intl …`）都是 12 空格缩进，看起来一样，语义完全不同。
    所以要钉的是**守卫条件**：记账所在分支不许要求 `quiet_until` 激活，
    否则正常路径（窗口未激活）抓完不记 → BKK 永远"从没轮到过"。
    """
    body = _fetch_body()
    rec = _record_line(body)
    assert rec, "找不到记账行"
    guard = _guard_of(body, rec)
    assert guard.startswith("if "), "记账没有守卫：%s" % guard
    assert "_is_intl" in guard, "记账不该作用于国内线：%s" % guard
    assert "quiet_until" not in guard, (
        "记账的守卫要求让位窗口激活 → 正常路径抓完不记，"
        "被 1999 卡死的航线每轮重抓（实测 SHA-BKK 19:44/19:58/20:02）")


def test_record_gated_off_during_backoff_window():
    """退避窗口里那一支会 `return []`，所以它**之前**的记账必须跳过。"""
    body = _fetch_body()
    rec = _record_line(body)
    assert rec, "找不到记账行"
    i = body.index(rec)
    seg = body[max(0, i - 900):i]
    assert "_WAIT_BACKOFF_UNTIL" in seg, \
        "记账没排除退避窗口：只路过的航线会被记成'查过了'，挤掉真正该轮到的"


def test_yield_returns_happen_before_the_record():
    """让位（quiet skip）必须 `return []` 在记账之前，否则会让位也记一笔。"""
    body = _fetch_body()
    rec = _record_line(body)
    assert rec, "找不到记账行"
    i_rec = body.index(rec)
    # 让位那一支的特征：path_note(... "paced" ...) + return []
    i_yield = body.find("国际查询让位：%s")
    assert 0 < i_yield < i_rec, "让位分支在记账之后（会让'没查'也记成'查过'）"
    seg = body[i_yield:i_rec]
    assert "return []" in seg, "让位分支没有提前 return"


def test_only_one_record_site():
    body = _fetch_body()
    n = sum(1 for ln in body.splitlines()
            if "_intl_route_seen[" in ln and "=" in ln and "get(" not in ln)
    assert n == 1, "记账点有 %d 处，多处实现必然漂移" % n


# ---------------------------------------------------------------------------
# 2. 落盘：轮转靠文件跨进程存活，写不进等于没记
# ---------------------------------------------------------------------------
def _crawler(tmp_path):
    import logging
    c = QunarCrawler({"user_data_dir": str(tmp_path),
                      "profile": "qunar"}, None)
    # 这几条测试会走到 `fetch()` 的日志分支；没 logger 会在 self.logger.info
    # 上炸掉（AttributeError），看起来像产品的错。补一个静默 logger。
    c.logger = logging.getLogger("r956")
    return c


def _quiet_gaps(monkeypatch):
    """让 `fetch()` 不真的 sleep、也不真的抓网页，只记录它有没有发抓取。

    为什么要 stub `_fetch_inner`：这几条测试钉的是**闸门行为**
    （谁该被挡、谁该被记账），不是抓取解析。真发请求会碰浏览器和网络。
    """
    now = time.time()
    QunarCrawler._cooldown_until = 0.0
    # 必须留够间隔：wait 的第二项是 `MIN_GAP_S - (now - last_done)`，
    # 设成 now 反而刚好触发最小间隔、真的去 sleep。
    QunarCrawler._last_done_ts = now - 10_000
    QunarCrawler._WAIT_BUDGET["used_s"] = 0.0
    QunarCrawler._WAIT_BUDGET["since"] = now
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    calls = []

    def _fake_inner(self, f, t, dates, **kw):
        calls.append((f, t))
        return []
    monkeypatch.setattr(QunarCrawler, "_fetch_inner", _fake_inner)
    return calls


def _key(c):
    """轮转表里 SHA-BKK 的时间戳（None = 从没记过）。"""
    return c._intl_route_seen.get("SHA-BKK")


def test_rotation_round_trip_through_disk(tmp_path):
    c1 = _crawler(tmp_path)
    assert c1._intl_route_seen == {}
    c1._intl_route_seen["SHA-BKK"] = time.time()
    c1._save_intl_rotation()

    c2 = _crawler(tmp_path)                     # 新实例 = 模拟重启
    assert c2._intl_route_seen.get("SHA-BKK"), \
        "没落盘/读不回：重启后 BKK 又变'从没轮到过'，老 bug 复发"


def test_load_tolerates_garbage(tmp_path):
    """轮转文件坏了不许把采集带崩（fail-soft）。"""
    c1 = _crawler(tmp_path)
    p = c1._intl_rot_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not json")
    c2 = _crawler(tmp_path)
    assert c2._intl_route_seen == {}


def test_bypass_gate_flips_once_recorded(tmp_path):
    """记账之后，同窗口内这条线不该再被判定为'从没轮到过'。"""
    c = _crawler(tmp_path)
    c._intl_quiet_until = time.time() + 600
    c._intl_quiet_reason = "配额保护"
    assert c._intl_route_seen.get("SHA-BKK") is None   # 从没查过

    key = "SHA-BKK"
    last = float(c._intl_route_seen.get(key) or 0)
    never = last <= 0
    assert never, "起点应是'从没轮到过'"

    c._intl_route_seen[key] = time.time()             # 记账
    c._save_intl_rotation()
    last2 = float(c._intl_route_seen.get(key) or 0)
    assert last2 > 0, "记了还是'从没轮到过' → 每轮重抓同一条线"


# ---------------------------------------------------------------------------
# 6. 退避窗口只管国际线（本轮我自己引入、又被测试撞出来的 bug）
# ---------------------------------------------------------------------------
def test_backoff_window_must_not_block_domestic(tmp_path, monkeypatch):
    """国际线被 1999 限流，不许把**国内**查询一起挡掉。

    这不是假想：退避窗口的判定原本写在国内外**共用**的 attempt 循环里，
    所以只要窗口点着，国内 fetch 也直接 `return []`。
    是测试隔离（类级窗口被同批其它测试留在未来时刻）把它撞出来的，
    而本文件自己的注释早就写明"国内列表另有配额，不受此限"。

    一个渠道的一半产能，绝不能被另一半的配额拖走。
    """
    calls = _quiet_gaps(monkeypatch)
    c = _crawler(tmp_path)
    c._intl_quiet_until = 0.0
    QunarCrawler._WAIT_BACKOFF_UNTIL = time.time() + 600   # 窗口开着
    try:
        c.fetch("SHA", "BJS", ["2026-11-16"])              # 国内线
    finally:
        QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    assert calls, "退避窗口把国内查询也挡了"


def test_domestic_still_absent_from_rotation_when_backoff_open(
        tmp_path, monkeypatch):
    """国内线既不被挡，也不该混进国际轮转表。"""
    calls = _quiet_gaps(monkeypatch)
    c = _crawler(tmp_path)
    c._intl_quiet_until = 0.0
    QunarCrawler._WAIT_BACKOFF_UNTIL = time.time() + 600
    try:
        c.fetch("SHA", "BJS", ["2026-11-16"])
    finally:
        QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    assert calls
    assert not any(k.startswith("SHA-BJS") for k in c._intl_route_seen)
