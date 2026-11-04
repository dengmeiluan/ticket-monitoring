# -*- coding: utf-8 -*-
"""r940：国际配额让位要**轮转**，不能永远饿死后面的航线。

2026-11-04 实测：qunar 今天 30 次尝试只有 7 次 ok（**23%**），失败全是
`1999/8 国际列表限流`。拆开看：

    7×  H5      ok          | touch.qunar.com H5 列表
    6×  QUERY   soft_reject | 国际查询让位
    5×  H5      soft_reject | 1999/8 连续 2 次（Cookie 在场→按限流退避）
    5×  H5      soft_reject | 1999/8 间歇放行（单次）

机制：国际列表限额**约 5 分钟/次、与航线无关**，而配置里有 **4 条国际航线**
（NRT/BKK/SIN/LHR）。而让位窗口内**所有**国际航线一律跳过，采集每轮又都从
配置里第一条（SHA→NRT）开始：

    NRT 拿配额 → BKK/SIN/LHR 全让位 → 下一轮**又从 NRT 开始**
    ⇒ NRT 天天成功，其余三条永远轮不到。

修法：让位窗口只挡「**刚查过的**」，给「**一直没轮到的**」留一个口子——
**每个让位窗口最多绕过一次**。绕过的那条立刻记时间戳，下个窗口轮到下一条，
于是 4 条国际航线公平轮转。

为什么是"每窗口一次"而不是"全都放行"：
4 条同时打会连撞 4 次 1999，把限流坐实，比现在更糟。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r940_intl_rotation.py -q
"""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.qunar import QunarCrawler  # noqa: E402


def _crawler(tmp_path=None):
    """测试专用 crawler：**不读生产轮转文件**（否则断言受真实状态影响）。"""
    import tempfile
    root = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp(prefix="r940_")
    return QunarCrawler({"user_data_dir": root, "profile": "qunar"}, None)


def _arm_quiet(c, left_s=600, reason="上一条国际查询软空/限流"):
    c._intl_quiet_until = time.time() + left_s
    c._intl_quiet_reason = reason
    return c._intl_quiet_until


# ---------------------------------------------------------------------------
# 1. 状态初始化
# ---------------------------------------------------------------------------
def test_state_initialised():
    c = _crawler()
    assert isinstance(c._intl_route_seen, dict) and c._intl_route_seen == {}
    assert c._intl_bypass_at == 0.0


# ---------------------------------------------------------------------------
# 2. 核心：从没轮到的航线，第一个让位窗口要放它一次
# ---------------------------------------------------------------------------
def test_never_tried_route_bypasses_once():
    c = _crawler()
    _arm_quiet(c)
    assert _would_bypass(c, "SHA", "BKK") is True, \
        "从没轮到过的航线被让位挡掉了（这就是饿死的根因）"


def test_bypass_only_once_per_window():
    """同一让位窗口内，绕过一次之后其余航线必须让位。"""
    c = _crawler()
    win = _arm_quiet(c)
    assert _would_bypass(c, "SHA", "BKK") is True      # 第一条绕过
    c._intl_bypass_at = win                            # 模拟"绕过已用"
    c._intl_route_seen["SHA-BKK"] = time.time()
    assert _would_bypass(c, "SHA", "SIN") is False, \
        "同一窗口内又放了一条：会连撞 1999"


def test_new_window_allows_next_route():
    """下一个让位窗口（until 变了）：轮到下一条。"""
    c = _crawler()
    old = _arm_quiet(c)
    c._intl_bypass_at = old
    c._intl_route_seen["SHA-BKK"] = time.time()
    assert _would_bypass(c, "SHA", "SIN") is False, "旧窗口不该再放"

    # 新窗口（until 改变）
    new = _arm_quiet(c, left_s=900)
    assert new != old
    assert _would_bypass(c, "SHA", "SIN") is True, "新窗口没有轮到下一条"


# ---------------------------------------------------------------------------
# 3. 刚成功过的航线不该抢这个口子
# ---------------------------------------------------------------------------
def test_recently_served_route_does_not_bypass():
    c = _crawler()
    _arm_quiet(c, reason="上一条国际明细已成功")
    c._intl_route_seen["SHA-NRT"] = time.time() - 30      # 刚查过
    assert _would_bypass(c, "SHA", "NRT") is False, \
        "刚查过的航线又绕过：配额会被它独吞"


def test_long_starved_route_bypasses():
    """超过半个让位窗口（450s）没轮到：算饿死，放行。"""
    c = _crawler()
    _arm_quiet(c)
    c._intl_route_seen["SHA-LHR"] = time.time() - 1200
    assert _would_bypass(c, "SHA", "LHR") is True


# ---------------------------------------------------------------------------
# 4. 没有让位窗口时：不受影响（正常查询）
# ---------------------------------------------------------------------------
def test_no_quiet_window_means_no_gate():
    c = _crawler()
    c._intl_quiet_until = 0.0
    assert _would_bypass(c, "SHA", "BKK") is True       # 无窗口 = 正常放行


# ---------------------------------------------------------------------------
# 5. 源码钉
# ---------------------------------------------------------------------------
def test_source_has_rotation():
    src = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                  encoding="utf-8").read()
    assert "_intl_route_seen" in src, "没有记录'上次轮到'的状态"
    assert "_intl_bypass_at" in src, "没有'每窗口只绕过一次'的闸"
    assert "国际航线轮转" in src, "没有可读的轮转日志"




# ---------------------------------------------------------------------------
# 6. 持久化：重启后轮转必须**接着走**（本轮核心）
# ---------------------------------------------------------------------------
def test_rotation_persists_across_restart(tmp_path):
    """`_intl_route_seen` 必须落盘。

    2026-11-04：轮转状态原来只放内存，**每次进程重启就清空**，而配置里
    第一条永远是 SHA→NRT —— 结果"NRT 每次都吃到重启后的第一份配额"。
    当天重启了 6 次，等于把轮转永久钉在第一条上。

    落盘之后，即使每轮都重启，4 条国际航线也能公平轮完。
    """
    import json
    import os as _os
    cfg = {"user_data_dir": str(tmp_path), "profile": "qunar"}
    routes = [("SHA", "NRT"), ("SHA", "BKK"), ("SHA", "SIN"), ("SHA", "LHR")]
    got = []
    for rnd in range(4):
        c = QunarCrawler(cfg, None)          # 每轮都是"新进程"
        c._intl_quiet_until = time.time() + 600 + rnd * 1000
        for fc, tc in routes:
            if _would_bypass(c, fc, tc):
                got.append(tc)
                c._intl_bypass_at = c._intl_quiet_until
                c._intl_route_seen["%s-%s" % (fc, tc)] = time.time()
                c._save_intl_rotation()
                break                         # 一窗口只放一条
    assert got == ["NRT", "BKK", "SIN", "LHR"], got
    # 文件真的写出来了
    p = _os.path.join(str(tmp_path), "qunar", "intl_rotation.json")
    assert _os.path.isfile(p)
    assert len(json.load(open(p, encoding="utf-8"))) == 4


def test_rotation_file_corrupt_is_tolerated(tmp_path):
    """轮转文件损坏：当作"都没轮到过"，不许抛。"""
    import os as _os
    d = _os.path.join(str(tmp_path), "qunar")
    _os.makedirs(d, exist_ok=True)
    with open(_os.path.join(d, "intl_rotation.json"), "w",
              encoding="utf-8") as f:
        f.write("{not-json")
    c = QunarCrawler({"user_data_dir": str(tmp_path), "profile": "qunar"}, None)
    assert c._intl_route_seen == {}


def test_rotation_save_is_fail_soft(tmp_path):
    """写不进去也不能抛（采集优先）。"""
    c = QunarCrawler({"user_data_dir": "/definitely/not/writable/\x00",
                      "profile": "qunar"}, None)
    c._intl_route_seen["X-Y"] = 1.0
    c._save_intl_rotation()        # 不该抛

# ---------------------------------------------------------------------------
# helper：复刻 fetch() 里的让位判定（不发请求）
# ---------------------------------------------------------------------------
def _would_bypass(c, fc, tc):
    """True = 越过让位窗口放行。"""
    if not (c._intl_quiet_until > time.time()):
        return True
    key = "%s-%s" % (fc, tc)
    last = float(c._intl_route_seen.get(key) or 0)
    starved = (time.time() - last) >= max(60.0, c.INTL_SOFT_QUIET_S / 2)
    never = last <= 0
    bypass_ok = (c._intl_bypass_at != c._intl_quiet_until)
    return bool((never or starved) and bypass_ok)
