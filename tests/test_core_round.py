# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1060_round_backoff.py
- tests/test_r741_round_trip_declaration_evidence.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import core.scheduler as sched_mod
import datetime as dt
import io
import os
import pytest

from core.channels import BROWSER_CHANNELS, dim_state
from core.pacing import round_backoff_minutes as rb


# ---- merged from tests/test_r1060_round_backoff.py ----

# ---------- 纯函数 ----------

def test_clean_round_has_no_backoff():
    assert rb(30, 0, 0) == 0


def test_one_or_two_trips_back_off_one_interval():
    assert rb(30, 1, 0) == 30
    assert rb(30, 2, 0) == 30
    assert rb(30, 0, 1) == 30          # 冷却中的渠道也算受阻


def test_three_or_more_trips_back_off_two_intervals():
    assert rb(30, 3, 0) == 60
    assert rb(30, 1, 2) == 60          # trips + blocked 合计


def test_capped():
    assert rb(600, 5, 0) == 240        # 默认封顶 240
    assert rb(600, 5, 0, cap_min=60) == 60


def test_bad_input_is_zero():
    assert rb(None, "x", None) == 0
    assert rb(0, 5, 5) == 0


# ---------- 调度器集成 ----------

class _Job:
    pass


class _FakeSched:
    """够 _schedule_next 用的最小替身。"""

    def __init__(self):
        self.timezone = dt.timezone(dt.timedelta(hours=8))
        self.next_run_time = None

    def get_job(self, job_id):
        return _Job()

    def modify_job(self, job_id, next_run_time=None):
        self.next_run_time = next_run_time


def _delta_for(state):
    s = _FakeSched()
    before = dt.datetime.now(s.timezone)
    sched_mod._schedule_next(s, state)
    after = dt.datetime.now(s.timezone)
    # 用中点消掉执行耗时带来的误差
    return (s.next_run_time
            - (before + (after - before) / 2)).total_seconds() / 60.0


def test_scheduler_applies_backoff():
    plain = _delta_for({"interval_minutes": 30, "jitter_minutes": 0})
    backed = _delta_for({"interval_minutes": 30, "jitter_minutes": 0,
                         "backoff_minutes": 30})
    assert abs(plain - 30) < 1.5, plain
    assert abs(backed - 60) < 1.5, backed


def test_scheduler_ignores_garbage_backoff():
    d = _delta_for({"interval_minutes": 30, "jitter_minutes": 0,
                    "backoff_minutes": "oops"})
    assert abs(d - 30) < 1.5, d


def test_wake_at_still_wins():
    """静默窗结束的 wake_at 仍取较短值：退避不能把补采推得更晚。

    `wake_at` 的语义是**剩余秒数**（main.py 里由
    `Pacing.seconds_until_quiet_end()` 写入），不是绝对时间戳——
    传时间戳会得到 `epoch/60` 这个荒谬的"分钟数"。
    """
    state = {"interval_minutes": 30, "jitter_minutes": 0,
             "backoff_minutes": 120, "wake_at": 5 * 60}
    d = _delta_for(state)
    assert d <= 6, d


# ---- merged from tests/test_r741_round_trip_declaration_evidence.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 返回行级的返程证据字段：必须出现在「比对」的上下文里，并非请求参数
EVIDENCE_FIELDS = ("backDate", "retDate", "retFlightNo", "returnDate",
                   "backFlightNo")


def _src(plat: str) -> str:
    return io.open(os.path.join(ROOT, "crawlers", plat + ".py"),
                   encoding="utf-8", newline="").read()


# 每个 y 渠道的「往返总价」证据形态不同：行级回程字段、价差不变式、
# 官方往返接口/产品总价、页面「往返总价」文案。这里按渠道钉真实实现，
# 不再用 skip 把不适用的分支跳过——不适用就断言它属于 n/""。
RT_EVIDENCE = {
    "ctrip": ("_fetch_rt", "containstax=1", "product_round_trip_total"),
    "qunar": ("_fetch_rt", "_parse_rt_body", "往返总价",
              "product_round_trip_total"),
    "tongcheng": ("book1/roundtrips", "_parse_rt_fps", "_fetch_intl_rt",
                  "miflightapi/ts/list", 'e.get("tp")', 'e.get("lng")'),
    "tuniu": ("avgTotalPrice", "product_round_trip_total"),
    "fliggy": ('.get("backDate")', "!= ret_date"),
}


@pytest.mark.parametrize("plat", BROWSER_CHANNELS)
def test_round_trip_y_has_channel_specific_evidence(plat):
    """记 y 就必须有可复核的「渠道自报往返总价」实现。

    证据按渠道取真实形态：飞猪/同程读行级回程字段并比对；携程/去哪儿
    用官方往返页/接口的产品总价；途牛用 avgTotalPrice。**不适用该分支
    的渠道断言其为 n/""，不再 skip**。
    """
    state = dim_state(plat, "round_trip")
    if state != "y":
        assert state in ("", "n"), state
        return
    src = _src(plat)
    missing = [t for t in RT_EVIDENCE[plat] if t not in src]
    assert not missing, (
        "%s 声明 round_trip=y，但缺少往返总价证据 %s；"
        "只把 ret_date 塞进 URL 不算证据" % (plat, missing))


def test_round_trip_states_are_exhaustive():
    """三态必须互斥且完整：y 有证据、n/"" 有明确声明，没有第四种。"""
    states = {p: dim_state(p, "round_trip") for p in BROWSER_CHANNELS}
    assert set(states.values()) <= {"y", "", "n"}, states
    for plat, st in states.items():
        assert st in ("y", "", "n"), (plat, st)


def test_fliggy_still_goes_through_the_strict_row_compare():
    """钉子：飞猪必须**读返回行 backDate 并比对**，不能被 skip 放过。

    r769 为途牛放宽了入口（它没有回程字段），但飞猪有——如果哪天飞猪的
    比对被删，这条要红，而不是静默退化成「靠价差」。
    """
    src = _src("fliggy")
    assert '.get("backDate")' in src, "飞猪不再读返回行 backDate"
    assert "bk != ret_date" in src or "!= ret_date" in src,         "飞猪不再比对回程日：其他回程日的行会被误认"


def test_tongcheng_domestic_round_trip_declared_after_api():
    """r815h 国内 book1/roundtrips；r926 国际 book1 RT 页 ts/list。

    国内：`book1/roundtrips` 的 atp 是组合总价（210/210）。
    国际：登录档案下 book1 RT 页的 `miflightapi/ts/list`，每条 res 的
    `tp` 是含税总价、`lng` 带去/返两段（2026-11-03 SHA→HKG 41 条 ¥1463）。
    矩阵 y 覆盖国内/国际，只采渠道总价，不做两段单程相加。
    """
    assert dim_state("tongcheng", "round_trip") == "y"
    src = _src("tongcheng")
    assert "book1/roundtrips" in src and "_parse_rt_fps" in src, (
        "声明国内往返 y，但代码里没有 roundtrips 接口/解析器")
    assert "_fetch_intl_rt" in src and "miflightapi/ts/list" in src, (
        "国际往返 y，但代码里没有 book1 RT 页/ts/list 通路")
    assert 'e.get("tp")' in src and 'e.get("lng")' in src, (
        "国际往返没有读 tp/lng（含税总价 + 去/返两段）")


DOCS_MAKING_CHANNEL_CLAIMS = ("docs/INTL_DESIGN.md", "docs/APP_CHANNELS.md",
                              "docs/HANDOFF_CAPABILITY_MATRIX.md")


@pytest.mark.parametrize("doc", DOCS_MAKING_CHANNEL_CLAIMS)
def test_docs_do_not_claim_tongcheng_supports_round_trip(doc):
    """文档不能把同程写成「支持往返」——代码已经取不到，用户会照着去查。

    只禁「同一行里既有同程又有『支持』且没有否定词」这种表述；
    「同程不支持」「同程……取不到」这类如实记录必须放行。
    """
    path = os.path.join(ROOT, doc)
    if not os.path.isfile(path):
        pytest.skip("%s 不在本工作树" % doc)
    src = io.open(path, encoding="utf-8").read()
    bad = []
    for line in src.splitlines():
        if "同程" not in line or "支持" not in line:
            continue
        if any(neg in line for neg in ("不支持", "取不到", "改判", "已否定",
                                       "n（", "round_trip=n")):
            continue
        bad.append(line.strip()[:120])
    assert not bad, "%s 把同程写成支持往返：%s" % (doc, bad[:3])
