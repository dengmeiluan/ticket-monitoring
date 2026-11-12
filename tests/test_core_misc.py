# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1058_challenge_cooldown.py
- tests/test_r1452_qunar_web_retired_entries.py
- tests/test_r1626_enabled_channels_advice.py
- tests/test_r1903_safezip_matrix.py
- tests/test_r318_dingfp.py
- tests/test_r335_winkey.py
- tests/test_r382_taxonomy.py
- tests/test_r805ae_rt_scope_single_source.py
- tests/test_r805w_roundtrip_not_oneway_baseline.py
- tests/test_r901_capability_matrix_rendered.py
- tests/test_r915_android_hardening.py
- tests/test_r961_buildid_sync.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import ast
import core.health as _health
import core.notifier as _nm
import io
import json
import logging
import main as _m
import os
import pytest
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from core.android import abi_canary, buildid as bi, display, fingerprint, hardening
from core.notifier import DingTalkNotifier
from core.pacing import ChannelBreaker, Pacing, advise, classify_failure, parse_pacing
from core.safezip import UnsafeArchiveError, is_safe_member, safe_extract
from core.storage import PriceStorage
from datetime import date, datetime as _real_dt, timedelta
from types import SimpleNamespace, SimpleNamespace as _NS

# 活数据日期：防「日期已过」校验/过期窗键 sweep 随日历腐化
# （写作时当日=2026-11-16、次日=2026-11-17、历史行锚=写作日-6）
_FUTURE = (date.today() + timedelta(days=7)).isoformat()
_FUTURE1 = (date.today() + timedelta(days=8)).isoformat()
_PAST6 = (date.today() - timedelta(days=6)).isoformat()


# ---- merged from tests/test_r1058_challenge_cooldown.py ----

def _t(**kw):
    return ChannelBreaker(**kw)


def test_hard_block_gets_long_cooldown():
    b = _t()
    now = 1_000_000.0
    cd = b.trip("p", "captcha", now=now,
                note="阿里安全容器 com.alibaba.wireless.security")
    assert cd == b.challenge_cooldown_s == 21600, cd
    ok, left = b.allow("p", now=now + 60)
    assert ok is False and left > 20000, (ok, left)


def test_plain_captcha_unchanged():
    """普通滑块仍走阶梯退避（base_s=300），不能被硬风控规则误伤。"""
    b = _t()
    assert b.trip("p", "captcha", now=1_000_000.0, note="请拖动滑块") == 300


def test_login_cooldown_unchanged():
    b = _t()
    assert b.trip("p", "login", now=1_000_000.0, note="请登录") == 900


def test_hard_block_does_not_accumulate_strikes():
    """硬风控不计 strikes：它不是普通限流，累积次数没有意义。"""
    b = _t()
    now = 1_000_000.0
    for i in range(3):
        b.trip("p", "captcha", now=now + i, note="需实名核验")
    st = b._rec("p")
    assert st["strikes"] == 0, st
    assert st["reason"] == "challenge", st


def test_switching_off_falls_back_to_ladder():
    b = _t(challenge_cooldown_s=0)
    assert b.trip("p", "captcha", now=1_000_000.0,
                  note="需实名核验") == 300


def test_markers_cover_observed_evidence():
    """这四条是 2026-11-06 实测到的真实文案，必须都被判成硬风控。"""
    b = _t()
    now = 1_000_000.0
    for note in ("当前登录环境存在风险，已被限制登录(50003)",
                 "账号风险检测 / 存在1条限制登录风险 / 请完成实名核验",
                 "当前账号行为异常，已被限制注册(40006)",
                 "com.alibaba.wireless.security.open.middletier.fc.ui."
                 "ContainerActivity"):
        assert b.trip("p", "captcha", now=now, note=note) == 21600, note


def test_config_roundtrip_and_clamp():
    assert parse_pacing({})["challenge_cooldown_s"] == 21600
    assert parse_pacing(
        {"crawler": {"breaker": {"challenge_cooldown_s": 3600}}}
    )["challenge_cooldown_s"] == 3600
    # 上限一週、下限 0
    assert parse_pacing(
        {"crawler": {"breaker": {"challenge_cooldown_s": 10 ** 9}}}
    )["challenge_cooldown_s"] == 604800
    assert parse_pacing(
        {"crawler": {"breaker": {"challenge_cooldown_s": -5}}}
    )["challenge_cooldown_s"] == 0


def test_breaker_survives_reconfigure():
    b = _t()
    now = time.time()
    b.trip("p", "captcha", now=now, note="需实名核验")
    b.configure(base_s=600, cap_s=1800)   # 热重载只换阈值
    ok, left = b.allow("p", now=now + 10)
    assert ok is False and left > 20000, (ok, left)


# ---- merged from tests/test_r1452_qunar_web_retired_entries.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_qunar_web_cells_are_marked_retired():
    from core.channel_links import channel_links
    r = channel_links()
    qunar_cells = [c for c in r["cells"] if c["plat"] == "qunar"]
    assert len(qunar_cells) == 4, qunar_cells
    for c in qunar_cells:
        assert c["retired"] is True, c
        # 入口地址保留作历史参考（ok 仍表示 URL 存在），但前端必须按
        # retired 渲染，不能只看 url 就发链接。
        assert c["url"], c
    for c in r["cells"]:
        if c["plat"] != "qunar":
            assert c["retired"] is False, c
    for c in r["specials"]:
        assert c["retired"] is (c["plat"] == "qunar"), c






def test_setup_check_reports_host_platform_and_app_boundary():
    """自检第一步就说清平台边界：网页三平台可用；App 仅 Windows+MuMu。"""
    from core import setup_check as sc
    row = sc.check_platform()
    assert row["name"] == "运行平台", row
    assert "App 渠道" in row["detail"], row
    rows = sc.run_checks()
    assert rows[0]["name"] == "运行平台", rows[0]


def test_readmes_have_per_os_quickstart_and_consistent_python_floor():
    """README 中英都要有分系统步骤，且 Python 下限与 setup_check 同为 3.11。

    2026-11-11 用户实报：不同系统的引导脚本执行不清；此前 README 徽章
    写 3.10+，setup 脚本/CI/Docker 实际要求 3.11。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("README.md", "README_EN.md"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert "Windows" in text and "macOS" in text and "Linux" in text, name
        assert "Python 3.11+" in text, name
        assert "Python 3.10" not in text and "3.10%2B" not in text, name
        # 发行包体积必须跟当前 Release 资产同量级（旧文案 60–94MB 已过期）
        assert "127–250" in text, name
        assert "60–94" not in text, name
        # App 渠道平台边界必须写明，避免 macOS/Linux 用户白装模拟器
        assert "Windows + MuMu" in text, name


# ---- merged from tests/test_r1626_enabled_channels_advice.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOW = time.time()
OLD = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 33 * 3600))


def _node():
    return {"last_seen_at": OLD, "paths": {}}


def test_disabled_channel_says_not_in_plan():
    got = advise("qunar", {}, {}, now=NOW, node=_node(),
                 enabled={"fliggy", "ctrip", "tongcheng", "tuniu"})
    assert got["state"] == "disabled", got
    assert got["severity"] == "ok", got
    assert "不在你的采集清单" in got["hint"], got["hint"]
    assert "检查监控进程" not in got["hint"], (
        "不在清单里的渠道仍教人去查进程：%s" % got["hint"])


def test_enabled_but_stale_still_warns_about_process():
    got = advise("qunar", {}, {}, now=NOW, node=_node(),
                 enabled={"qunar", "fliggy"})
    assert got["state"] == "stalled", got
    assert "采集没在跑" in got["hint"], got["hint"]


def test_no_enabled_arg_keeps_old_behaviour():
    got = advise("qunar", {}, {}, now=NOW, node=_node())
    assert got["state"] == "stalled", got


def test_empty_enabled_is_not_treated_as_all_disabled():
    # 调用方读不到清单时传 None（而不是空集）；空集会被当成"全都不在清单"。
    got = advise("qunar", {}, {}, now=NOW, node=_node(), enabled=None)
    assert got["state"] == "stalled", got


# ---- merged from tests/test_r1903_safezip_matrix.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _make_zip(tmp, entries, links=(), fifo=(), big=None):
    p = os.path.join(str(tmp), "pkg.zip")
    with zipfile.ZipFile(p, "w") as z:
        for name, text in entries.items():
            z.writestr(name, text)
        for name, data in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, data)
        for name in fifo:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFIFO | 0o644) << 16
            z.writestr(info, "")
        if big:
            name, size = big
            info = zipfile.ZipInfo(name)
            info.file_size = size
            z.writestr(info, b"\0" * 16)
    return p


def _dest(tmp):
    d = os.path.join(str(tmp), "cache")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.mark.parametrize("bad", [
    "../escaped.txt",
    "a/../../escaped.txt",
    "/abs.txt",
    "C:/evil.txt",
    "C:\\\\evil.txt",
    "//host/share/evil.txt",
    "core/../../evil.txt",
])
def test_traversal_and_absolute_names_are_refused(tmp_path, bad):
    z = _make_zip(tmp_path, {bad: "x", "ok.txt": "fine"})
    dest = _dest(tmp_path)
    with zipfile.ZipFile(z) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest)
    # 先校验后落盘：一个字节都不许写
    assert os.listdir(dest) == [], os.listdir(dest)


def test_symlink_member_is_refused(tmp_path):
    z = _make_zip(tmp_path, {"ok.txt": "fine"}, links=[("link", "/etc")])
    dest = _dest(tmp_path)
    with zipfile.ZipFile(z) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest)
    assert os.listdir(dest) == []


def test_fifo_member_is_refused(tmp_path):
    z = _make_zip(tmp_path, {"ok.txt": "fine"}, fifo=["pipe"])
    dest = _dest(tmp_path)
    with zipfile.ZipFile(z) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest)


@pytest.mark.skipif(os.name != "posix", reason="只有 POSIX 能真正建软链")
def test_symlink_write_through_cannot_escape(tmp_path):
    """`link -> /outside` + `link/pwned.txt`：真能逃出去的那条路，必须被拒。"""
    outside = os.path.join(str(tmp_path), "outside")
    os.makedirs(outside)
    z = _make_zip(tmp_path,
                  {"link/pwned.txt": "pwn"},
                  links=[("link", outside)])
    dest = _dest(tmp_path)
    with zipfile.ZipFile(z) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest)
    assert not os.path.exists(os.path.join(outside, "pwned.txt"))


@pytest.mark.skipif(os.name != "posix", reason="Windows 建软链需特权")
def test_preexisting_symlink_in_dest_is_not_followed(tmp_path):
    """目标目录里**已有**软链指向外面时，也不许顺着写。"""
    outside = os.path.join(str(tmp_path), "outside")
    os.makedirs(outside)
    dest = _dest(tmp_path)
    os.symlink(outside, os.path.join(dest, "hole"))
    z = _make_zip(tmp_path, {"hole/pwned.txt": "pwn"})
    with zipfile.ZipFile(z) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest)
    assert not os.path.exists(os.path.join(outside, "pwned.txt"))


def test_normal_package_extracts_with_nested_dirs(tmp_path):
    z = _make_zip(tmp_path, {"core/mod.py": "NEW\n",
                             "nested/deep/x.txt": "D\n"})
    dest = _dest(tmp_path)
    with zipfile.ZipFile(z) as f:
        written = safe_extract(f, dest)
    assert (open(os.path.join(dest, "core", "mod.py"), encoding="utf-8")
            .read()) == "NEW\n"
    assert os.path.exists(os.path.join(dest, "nested", "deep", "x.txt"))
    assert "core/mod.py" in [w.replace(os.sep, "/") for w in written]


def test_member_cap_and_size_cap(tmp_path):
    z = _make_zip(tmp_path, {"a.txt": "1"})
    dest = _dest(tmp_path)
    with zipfile.ZipFile(z) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest, max_entries=0)
    # writestr() 会用 data 长度覆盖 file_size，所以这里直接卡 1 字节上限
    z2 = _make_zip(tmp_path, {"big.bin": "0123456789"})
    with zipfile.ZipFile(z2) as f:
        with pytest.raises(UnsafeArchiveError):
            safe_extract(f, dest, max_total_bytes=1)


def test_is_safe_member_semantics(tmp_path):
    root = os.path.realpath(str(tmp_path))
    assert is_safe_member("a/b.txt", root)
    assert is_safe_member("a/./b.txt", root)
    assert not is_safe_member("../x", root)
    assert not is_safe_member("a/../../x", root)
    assert not is_safe_member("/etc/passwd", root)
    assert not is_safe_member("C:/x", root)


def test_repo_has_single_extraction_entry():
    """全仓不许再有**真实调用** `.extractall(`——解压只走 core.safezip。

    用 AST 而不是 `git grep`：后者在 GBK 控制台下会把中文注释解崩，
    也会把文档字符串里提到的 `extractall(` 误判成调用。
    """
    hits = []
    skip_dirs = {".git", "_scratch", "_tools", "_vendor", "_internal", "build",
                 "dist", "data", "logs", "user_data", "__pycache__",
                 ".pytest_cache", "_build", "_build_check"}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            if rel == "core/safezip.py":
                continue
            try:
                tree = ast.parse(io.open(path, encoding="utf-8").read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "extractall"):
                    hits.append("%s:%d" % (rel, node.lineno))
    assert not hits, "这些地方还在直接 extractall：%s" % hits[:5]


def test_security_doc_names_the_entry():
    """安全文档只有一份：根 `SECURITY.md`（README 指向它），不许再分叉。"""
    assert not os.path.exists(os.path.join(ROOT, "docs", "SECURITY.md")), \
        "又出现了 docs/SECURITY.md——安全文档必须单源（根 SECURITY.md）"
    p = os.path.join(ROOT, "SECURITY.md")
    assert os.path.exists(p), "缺根 SECURITY.md"
    d = io.open(p, encoding="utf-8").read()
    for k in ("core.safezip", "safe_extract", "符号链接", "升级包", "extractall"):
        assert k in d, "SECURITY.md 缺：" + k


# ---- merged from tests/test_r318_dingfp.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _R:
    def __init__(self):
        self.text = str({"errcode": 0})

    def json(self):
        return {"errcode": 0}


def test_dingtalk_desp_carries_fingerprint_time():
    """出站正文尾部携带 ⏰ HH:MM 生成时刻（防内容指纹行恒落位）。"""
    captured = {}

    def _fake_post(url, json=None, **k):
        captured["payload"] = json
        return _R()

    orig = _nm.httpx.post
    orig_dt = _nm.datetime
    _nm.httpx.post = _fake_post
    # 时刻来源钉到固定值：证明词面取自 datetime.now() 而非写死
    _nm.datetime = SimpleNamespace(now=lambda: _real_dt(2026, 10, 16, 14, 7))
    work = tempfile.mkdtemp(prefix="ding_fp_")
    old = os.getcwd()
    os.chdir(work)
    try:
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x",
                             logging.getLogger("t"))
        assert d.send("标题", "正文内容") is True
        text = captured["payload"]["markdown"]["text"]
        assert "正文内容" in text, "原正文须保留"
        assert re.search(r"⏰ 14:07\s*$", text), repr(text[-40:])
    finally:
        _nm.httpx.post = orig
        _nm.datetime = orig_dt
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)


def test_dingtalk_fingerprint_time_after_truncation():
    """超长 desp 截断后时刻行仍恒落位（地板档：截断产物+⏰ 行）。"""
    captured = {}

    def _fake_post(url, json=None, **k):
        captured["payload"] = json
        return _R()

    orig = _nm.httpx.post
    orig_dt = _nm.datetime
    _nm.httpx.post = _fake_post
    _nm.datetime = SimpleNamespace(now=lambda: _real_dt(2026, 10, 16, 9, 30))
    work = tempfile.mkdtemp(prefix="ding_fp2_")
    old = os.getcwd()
    os.chdir(work)
    try:
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x",
                             logging.getLogger("t"))
        big = "很长的正文" * 5000   # 远超 18000 字节
        assert d.send("标题", big) is True
        text = captured["payload"]["markdown"]["text"]
        assert len(text.encode("utf-8")) <= 18000, len(text.encode("utf-8"))
        assert re.search(r"⏰ 09:30\s*$", text), repr(text[-40:])
    finally:
        _nm.httpx.post = orig
        _nm.datetime = orig_dt
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)


# ---- 未达标心跳正文小型化（方案 A：防内容指纹的产品级正解） ----

def _route():
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=1900, alert_transfer=1700)


def _sections():
    return [{"date": "2026-09-25",
             "best_direct": {"price": 1950, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"},
             "best_transfer": None,
             "seen_plats": ["qunar"]}]


def test_digest_heartbeat_body_slim():
    """未达标心跳正文小型化：3815 字节恒定大正文每轮命中钉钉模糊查重
    （绝对相似量 ~2000 字节阈值，探针矩阵实锤）→ 应答恒 -1 但照常投
    递；224 字节小正文恒定连发实测零命中。断言：未达标轮 desp ≤700
    字节、含每航线 KPI 摘要行、不含图例行（总表图内自含）。"""
    import logging
    from core.alerter import Alerter
    a = Alerter(logging.getLogger("t"), storage=None, digest=True)
    a.round_charts = {}
    p = a._digest_payload([(_route(), _sections())],
                          fresh=False, with_tables=False)
    desp = p["desp"]
    assert len(desp.encode("utf-8")) <= 700, (
        len(desp.encode("utf-8")), desp[:200])
    assert "全部未达标" in desp
    assert "直飞 ￥1950" in desp, desp
    assert "🟩" not in desp, "图例行应省略（总表图内自含）"


# ---- 心跳形态三态配置（可配置/建议化/健壮降级） ----

def _mk(style, fail_streak=None):
    import logging
    from core.alerter import Alerter

    class _N:
        _fail_streak = 0 if fail_streak is None else fail_streak

    a = Alerter(logging.getLogger("t"), storage=None, digest=True,
                notifier=_N(), heartbeat_style=style)
    a.round_charts = {}
    return a


def test_heartbeat_style_slim_default():
    """slim（默认推荐）：未达标心跳轻量摘要——防钉钉正文模糊查重
    （绝对相似量 ~2000 字节阈值实测），状态恢复真 ok。未知配置值
    同落 slim（安全默认）。"""
    for style in ("slim", "", "未知值"):
        a = _mk(style)
        assert a._hb_slim() is True, style
        p = a._digest_payload([(_route(), _sections())],
                              fresh=False, with_tables=False,
                              slim=a._hb_slim())
        assert len(p["desp"].encode("utf-8")) <= 700


def test_heartbeat_style_full():
    """full：全量图文形态（用户显式选择）——正文主体超钉钉判重阈值，
    应答将恒 -1「系统繁忙」（消息仍送达）；选此档即接受假失败状态，
    配置页须如实标注。形态断言用结构词面（小节标题/KPI 行），夹具
    数据量小、字节数断言不适用。"""
    a = _mk("full")
    assert a._hb_slim() is False
    p = a._digest_payload([(_route(), _sections())],
                          fresh=False, with_tables=False,
                          slim=a._hb_slim())
    assert "#### ✈️" in p["desp"], "全量小节标题在场"
    assert "MU8369" in p["desp"], "KPI 行含航班身份（轻量形态仅价格）"


def test_heartbeat_style_auto_downgrades_on_streak():
    """auto：全量优先（前期观感完整），钉钉连败 ≥3（判重实锤）自动
    降为轻量——健壮形态：最后能完全成功（状态恢复真 ok）。跨轮形态
    自适应，单发零重试铁律不动。非钉钉通道（无 _fail_streak）恒全量
    （无指纹问题）。形态断言用结构词面（小节标题 vs 单行摘要）。"""
    a = _mk("auto", fail_streak=0)
    assert a._hb_slim() is False, "auto 前期按全量"
    p = a._digest_payload([(_route(), _sections())],
                          fresh=False, with_tables=False,
                          slim=a._hb_slim())
    assert "#### ✈️" in p["desp"], "前期全量小节"
    a2 = _mk("auto", fail_streak=3)
    assert a2._hb_slim() is True, "连败 ≥3 降轻量"
    p2 = a2._digest_payload([(_route(), _sections())],
                            fresh=False, with_tables=False,
                            slim=a2._hb_slim())
    assert "#### ✈️" not in p2["desp"], "降级后轻量行（无小节标题）"
    a3 = _mk("auto")   # notifier 无 _fail_streak（非钉钉通道）
    a3.notifier = None
    assert a3._hb_slim() is False, "非钉钉通道无指纹，auto 恒全量"


# ---- merged from tests/test_r335_winkey.py ----

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

class _L:
    def __init__(self):
        self.seen = []

    def warning(self, m, *a):
        self.seen.append(("W", m % a if a else m))

    def info(self, m, *a):
        self.seen.append(("I", m % a if a else m))


def _iso(monkeypatch, tmp_path):
    # r320 写入面生产资格门双锚：helper 读 SENTINEL_STATE_FILE 环境变量
    # 优先，仅 patch 模块属性会被绕过（读写劈叉）
    monkeypatch.setenv("SENTINEL_STATE_FILE",
                       str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_SENT_SUPPLIED", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    return _L()


def _rows(n, share_rows=0):
    """单窗直飞行群：n 行裸价行，前 share_rows 行带 shareCarrier。"""
    rows = []
    for i in range(n):
        f = {"price": 1000 + i}
        if i < share_rows:
            f["shareCarrier"] = "X%d" % i
        rows.append(f)
    return rows


def _rec(plat, fc, tc, dd, rows):
    return [_NS(platform=plat, from_city=fc, to_city=tc,
                depart_date=dd, extra=json.dumps(rows))]


SHARE_HIT = "shareCarrier 命中 0"


def test_multi_window_same_day_each_fires_once(monkeypatch, tmp_path):
    """同字段多窗同日断供各自首鸣：窗 B 不得被窗 A 的「今日已报」
    短路吞掉（共享平键的遮蔽缺陷窗键版根治钉）。"""
    lg = _iso(monkeypatch, tmp_path)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 20)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE1, _rows(20, 20)), lg)
    assert lg.seen == []
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 0)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE1, _rows(20, 0)), lg)
    hits = [m for lv, m in lg.seen if SHARE_HIT in m]
    assert len(hits) == 2, lg.seen
    assert ("tuniu", "share", "SHA", "SGN", _FUTURE) in _m._SENT_LAST
    assert ("tuniu", "share", "SHA", "SGN", _FUTURE1) in _m._SENT_LAST
    assert ("tuniu", "share") not in _m._SENT_LAST, \
        "字段哨留痕不得再落跨窗平键"


def test_never_supplied_interference_and_single_fire(monkeypatch, tmp_path):
    """窗 A 在燃 + 无源窗 B 穿插 + 窗 A 复扫：A 恰 1 鸣、B 零鸣、
    A 的窗键留痕原样（无源窗穿插互扰的窗键终态验收钉）。"""
    lg = _iso(monkeypatch, tmp_path)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 20)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 0)), lg)
    assert len([1 for lv, m in lg.seen if SHARE_HIT in m]) == 1
    akey = ("tuniu", "share", "SHA", "SGN", _FUTURE)
    assert akey in _m._SENT_LAST
    _m._field_sentinel(
        _rec("tuniu", "SHA", "CNX", _FUTURE, _rows(20, 0)), lg)
    assert akey in _m._SENT_LAST, "无源窗不得波及他窗留痕"
    assert not [m for lv, m in lg.seen if "CNX" in m], lg.seen
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 0)), lg)
    assert len([1 for lv, m in lg.seen if SHARE_HIT in m]) == 1, \
        "窗 A 复扫不得重鸣"


def test_streak_per_window(monkeypatch, tmp_path):
    """连日升级按窗独立累计：窗 A 已连续 2 日在燃第 3 日升 INFO，
    同字段窗 B 首鸣保持 WARNING（共享平键下两窗共用一个计数）。"""
    lg = _iso(monkeypatch, tmp_path)
    import datetime as _dt
    yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    akey = ("tuniu", "share", "SHA", "SGN", _FUTURE)
    bkey = ("tuniu", "share", "SHA", "SGN", _FUTURE1)
    _m._SENT_LAST[akey] = yest
    _m._SENT_CNT[akey] = 2
    _m._SENT_SUPPLIED[akey] = yest
    _m._SENT_SUPPLIED[bkey] = yest
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 0)), lg)
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE1, _rows(20, 0)), lg)
    kinds = {k for k, _ in lg.seen}
    assert "I" in kinds and "W" in kinds, lg.seen
    a_msgs = [m for lv, m in lg.seen if "连续3日" in m]
    assert a_msgs and _FUTURE in a_msgs[0], lg.seen
    assert _m._SENT_CNT[akey] == 3 and _m._SENT_CNT[bkey] == 1


def test_message_carries_window_identity_and_health_parses(
        monkeypatch, tmp_path):
    """告警词面自带窗辨识（读者不复算即知哪窗断供），且 health 时间线
    正则对新词面照常收录（日志面消费端同轮协议）。"""
    lg = _iso(monkeypatch, tmp_path)
    akey = ("tuniu", "share", "SHA", "SGN", _FUTURE)
    _m._SENT_SUPPLIED[akey] = "2026-10-01"
    _m._field_sentinel(
        _rec("tuniu", "SHA", "SGN", _FUTURE, _rows(20, 0)), lg)
    hits = [m for lv, m in lg.seen if SHARE_HIT in m]
    assert hits and "窗 SHA→SGN " + _FUTURE in hits[0], lg.seen
    # _L 捕获的模板串已含「[解析哨兵] 」前缀，health 正则按生产日志
    # 行形态直接匹配
    mm = _health._SENT.match(hits[0])
    assert mm and mm.group(1) == "tuniu", hits[0]


def test_state_roundtrip_mixed_key_shapes(monkeypatch, tmp_path):
    """状态文件混形往返：5 元窗键留痕[日期,连击]、平键行为哨留痕、
    supplied 族、domzero 族同文件互不串形。"""
    _iso(monkeypatch, tmp_path)
    akey = ("tuniu", "share", "SHA", "SGN", _FUTURE)
    _m._SENT_LAST[akey] = "2026-10-18"
    _m._SENT_CNT[akey] = 4
    _m._SENT_LAST[("tuniu", "noDet")] = "2026-10-18"
    _m._SENT_CNT[("tuniu", "noDet")] = 2
    _m._SENT_SUPPLIED[("qunar", "meal", "HAK", "SHA", "2027-02-13")] = \
        "2026-10-18"
    _m._DOMZERO_SEEN[("tuniu", "dom")] = True
    _m._sent_save()
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    _m._DOMZERO_SEEN.clear()
    _m._sent_load()
    assert _m._SENT_LAST[akey] == "2026-10-18"
    assert _m._SENT_CNT[akey] == 4
    assert _m._SENT_LAST[("tuniu", "noDet")] == "2026-10-18"
    assert _m._SENT_CNT[("tuniu", "noDet")] == 2
    assert _m._SENT_SUPPLIED[
        ("qunar", "meal", "HAK", "SHA", "2027-02-13")] == "2026-10-18"
    assert _m._DOMZERO_SEEN[("tuniu", "dom")] is True


def test_trans_rowtype_sentinel_window_keyed(monkeypatch, tmp_path):
    """行型断供哨（trans）同族窗键控：两窗各有直飞满量+中转零行、
    各有历史供给 → 各自首鸣，词面各带本窗辨识。"""
    lg = _iso(monkeypatch, tmp_path)
    direct = [{"price": 1000 + i} for i in range(22)]
    for dd in (_FUTURE, _FUTURE1):
        t = dict(direct[0])
        t["transCity"] = "西安"
        t["layover"] = 90
        _m._field_sentinel(
            _rec("tongcheng", "URC", "SHA", dd, direct + [t]), lg)
    assert lg.seen == []
    for dd in (_FUTURE, _FUTURE1):
        _m._field_sentinel(
            _rec("tongcheng", "URC", "SHA", dd, direct), lg)
    hits = [m for lv, m in lg.seen if "中转零行" in m]
    assert len(hits) == 2, lg.seen
    assert any(_FUTURE in m for m in hits)
    assert any(_FUTURE1 in m for m in hits)


def test_behavior_sentinels_keep_flat_keys(monkeypatch, tmp_path):
    """行为型哨（跨窗聚合量）保持平键：noDet 的留痕/连击仍落
    (plat,fld)，不得被窗键控波及。"""
    lg = _iso(monkeypatch, tmp_path)
    recs = [_NS(platform="tuniu", from_city="SHA", to_city="HAK",
                depart_date="2027-01-29", extra=""),
            _NS(platform="tuniu", from_city="SHA", to_city="HAK",
                depart_date="2027-01-30", extra="")]
    _m._field_sentinel(recs, lg)
    assert any("明细 0 行" in m for lv, m in lg.seen), lg.seen
    assert ("tuniu", "noDet") in _m._SENT_LAST
    assert ("tuniu", "noDet", "SHA", "HAK", "2027-01-29") \
        not in _m._SENT_LAST


def test_retire_pops_window_key_family(monkeypatch, tmp_path):
    """死键退役摘除窗键族留痕：5 元窗键与旧平键一并清（观测面豁免键
    的留痕悬挂防复发）。"""
    _iso(monkeypatch, tmp_path)
    _m._SENT_LAST[("ctrip", "page", "URC", "SHA", "2027-01-29")] = \
        "2026-10-18"
    _m._SENT_CNT[("ctrip", "page", "URC", "SHA", "2027-01-29")] = 2
    rows = [{"price": 1000 + i, "plane": "空客A320", "cabin": "经济舱",
             "meal": "有餐食", "prate": 90, "discount": "4.5折",
             "depTerminal": "T2", "arrTerminal": "T1",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for i in range(12)]
    _m._field_sentinel(
        [_NS(platform="ctrip", from_city="URC", to_city="SHA",
             depart_date="2027-01-29", extra=json.dumps(rows))], _L())
    assert ("ctrip", "page", "URC", "SHA", "2027-01-29") \
        not in _m._SENT_LAST, _m._SENT_LAST


def test_stale_window_marks_swept(monkeypatch, tmp_path):
    """过期窗键留痕 sweep（r336 Soldier m3 卫生债随迁）：键内嵌出发
    日期早于今天的 _SENT_LAST/_SENT_CNT 留痕永不再命中（窗已过期
    跳采），长跑月级缓慢泄漏——每轮 _field_sentinel 尾部清理；平键
    （行为型哨/zrow/qsup）与当期窗键不在清理域；_SENT_SUPPLIED 是
    r334 案③持久化供给基线（化石窗由「未过期窗」枚举语义处置，
    LESSONS 卅二§1），不在清理域。"""
    lg = _iso(monkeypatch, tmp_path)
    stale = ("ctrip", "page", "URC", "SHA", "2020-01-01")
    live = ("qunar", "page", "XXX", "YYY", "2099-01-01")   # 本轮不扫的航线（防 never-supplied 摘除分支干扰断言）
    _m._SENT_LAST[stale] = "2026-10-18"
    _m._SENT_CNT[stale] = 3
    _m._SENT_LAST[live] = "2026-10-19"
    _m._SENT_CNT[live] = 1
    _m._SENT_LAST[("ctrip", "rowfall")] = "2026-10-19"   # 平键
    _m._SENT_SUPPLIED[("ctrip", "page", "URC", "SHA", "2020-01-01")] = 1
    rows = [{"price": 1000 + i, "plane": "空客A320", "cabin": "经济舱",
             "meal": "有餐食", "prate": 90, "discount": "4.5折",
             "depTerminal": "T2", "arrTerminal": "T1",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for i in range(12)]
    _m._field_sentinel(
        [_NS(platform="ctrip", from_city="URC", to_city="SHA",
             depart_date="2099-01-01", extra=json.dumps(rows))], _L())
    assert stale not in _m._SENT_LAST, "过期窗留痕未清"
    assert stale not in _m._SENT_CNT
    assert live in _m._SENT_LAST, "当期窗留痕误清"
    assert ("ctrip", "rowfall") in _m._SENT_LAST, "平键误清"
    assert _m._SENT_SUPPLIED[("ctrip", "page", "URC", "SHA",
                              "2020-01-01")] == 1, "供给基线误清"


# ---- merged from tests/test_r382_taxonomy.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_444_is_soft_not_login():
    """444 不得再归为"需登录"，也不得冷却渠道。"""
    assert classify_failure(["soft_reject"], "国际日历 HTTP 444") == "soft"
    p = Pacing({})
    kind, cd = p.observe("tongcheng", ["soft_reject"],
                         "国际日历会话门拒 code=444")
    assert kind == "soft" and cd == 0
    ch = p.snapshot()["channels"]["tongcheng"]
    assert ch["state"] == "ok" and ch["strikes"] == 0
    assert ch["needs_warmup"] is True
    assert ch["needs_login"] is False
    a = advise("tongcheng", ch, {})
    assert a["state"] == "soft_reject"
    assert a["action"] == "probe"        # 让用户自检/预热，而不是重登


def test_real_login_still_login():
    """真登录墙（710114/needLogin）必须仍然是 login。"""
    assert classify_failure(["login"], "登录号（710114/needLogin）") == "login"
    p = Pacing({})
    kind, cd = p.observe("tuniu", ["login"], "710114")
    assert kind == "login" and cd > 0
    ch = p.snapshot()["channels"]["tuniu"]
    assert ch["needs_login"] is True
    assert advise("tuniu", ch, {})["action"] == "relogin"


def test_soft_precedes_ip_when_note_has_444():
    """软拒常带 444 字样，不能被 IP 规则先吃掉（否则整家冷却）。"""
    assert classify_failure([], "HTTP 444 关连接") == "soft"
    p = Pacing({})
    kind, cd = p.observe("tongcheng", [], "HTTP 444 关连接")
    assert kind == "soft" and cd == 0
    assert p.snapshot()["channels"]["tongcheng"]["strikes"] == 0


def test_true_empty_is_not_login():
    assert classify_failure(["empty"], "原站明确返回无符合条件的航班") == ""


def test_qunar_no_result_does_not_inherit_login_suspect():
    """源码契约：no_result 必须先于 login_suspect 判定。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", "qunar.py"),
              encoding="utf-8") as f:
        src = f.read()
    i = src.find('_h5_status = ("ok" if got else')
    assert i > 0
    block = src[i:i + 420]
    assert '"empty" if _nores' in block, block
    j = src.find('_api_status = ("ok" if got else')
    assert j > 0
    assert '"empty" if _nores' in src[j:j + 420]


def test_tongcheng_444_does_not_set_login_suspect():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", "tongcheng.py"),
              encoding="utf-8") as f:
        src = f.read()
    # 找到 code=444 分支，确认不再 login_suspect / 不再写 login
    i = src.find('if _code == "444" or "非法链接"')
    assert i > 0
    block = src[i:i + 700]
    # 只断言"没有赋值/置位"，注释里出现该词是允许的
    assert "login_suspect = True" not in block, block
    assert "type(self).login_suspect" not in block, block
    assert '"soft_reject"' in block, block
    # HTTP 444 两处也必须是 soft_reject
    assert src.count('"soft_reject" if _hs == 444') == 1
    assert src.count('"soft_reject" if ar.status == 444') == 1


def test_failure_kind_vocabulary_is_stable():
    from core.pacing import failure_kind
    assert failure_kind("soft")[0] == "会话层软拒"
    assert failure_kind("soft")[2] is True          # 自动自愈
    assert failure_kind("login")[0] == "登录态失效"
    assert failure_kind("login")[2] is False        # 需人工
    assert failure_kind("ip")[2] is False
    unknown = failure_kind("something_new")
    assert unknown[0] == "未分类"


def test_recurrence_flags_soft_as_autoheal(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(4):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2027-06-01",
                           "日历", "soft_reject", attempt_id="a%d" % i)
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01",
                           "H5", "login", attempt_id="b%d" % i)
    rows = {r["platform"]: r for r in st.failure_recurrence(24, 3)}
    assert rows["tongcheng"]["kind"] == "soft"
    assert rows["qunar"]["kind"] == "login"


def test_panel_shows_recurrence_with_action_flag():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "反复出现" in src
    assert "autoHeal" in src and "需人工" in src and "自动" in src
    assert "failure_kind" in src


def test_legacy_444_login_rows_are_relabelled_as_soft(tmp_path):
    """历史行曾把 444 记成 login；复发账必须按证据改判，避免自相矛盾。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2027-06-01",
                           "日历", "login", note="会话门拒 code=444",
                           attempt_id="old%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "soft_reject"
    assert row["kind"] == "soft"
    # 证据原样保留，便于核对
    assert "444" in (row["evidence"] or {}).get("note", "")


def test_legacy_real_login_is_not_relabelled(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("tuniu", "SHA", "BKK", "2027-06-01",
                           "H5/API", "login", note="登录号（710114/needLogin）",
                           attempt_id="t%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "login" and row["kind"] == "login"


def test_legacy_no_result_login_rows_are_relabelled_as_empty(tmp_path):
    """去哪儿"原站无符合条件的航班"曾被记 login（1999 双向重载）。

    真实 48h 账本里这类历史行 44 条；不按证据改判，复发面板会把
    真无票说成"登录态失效（需人工）"，把用户推去做无用重登。
    """
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path(
            "qunar", "SHA", "HKG", _PAST6, "API", "login",
            note="原站返回无符合条件的航班（可能受指纹 SDK/风控环境影响）",
            attempt_id="q%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "empty"
    assert row["kind"] == "empty"
    assert "无符合条件的航班" in (row["evidence"] or {}).get("note", "")


def test_legacy_1999_login_rows_are_relabelled_soft(tmp_path):
    """r385 受控 A/B 推翻了 r382 的假设：1999 不是登录墙。

    同 profile、零介入、6 轮 × SHA→LHR：首轮 1999 后连续 5 轮出数，
    未重登即自愈。故历史 login 行（证据写 1999）展示时按 soft 归类，
    不再催用户重登。改名保留用例位（原 test_legacy_1999_login_wall_
    stays_login 的结论已被实测推翻）。
    """
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "HKG", _PAST6, "H5",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="k%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "soft_reject" and row["kind"] == "soft"


def test_recurrence_marks_recovered_after_later_success(tmp_path):
    """失败后又成功 = 已恢复：复发账不再继续喊「需人工」。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-01", "H5",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="b%d" % i)
    st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-02", "H5", "ok",
                       rows=30, attempt_id="ok")
    row = next(r for r in st.failure_recurrence(24, 3)
               if r["path"] == "H5")
    assert row["recovered"] is True, "之后已出数，不能还标需人工"
    assert row["last_ok_at"]


def test_recurrence_not_recovered_without_later_success(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2027-06-01", "日历",
                           "soft_reject", note="国际日历请求形态门拒 code=444",
                           attempt_id="s%d" % i)
    row = next(r for r in st.failure_recurrence(24, 3)
               if r["path"] == "日历")
    assert row["recovered"] is False


def test_recurrence_recovered_only_for_same_path(tmp_path):
    """别的路径成功不能顶替：H5 好了不代表 API 也好了。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-01", "API",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="a%d" % i)
    st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-02", "H5", "ok",
                       rows=20, attempt_id="ok2")
    row = next(r for r in st.failure_recurrence(24, 3)
               if r["path"] == "API")
    assert row["recovered"] is False


# ---- merged from tests/test_r805ae_rt_scope_single_source.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_every_unsupported_cell_is_explained():
    """任何写「不支持」的格子都必须说明为什么，否则会被读成「渠道没有」。

    两次踩点：携程**产品上有往返**、五个浏览器站点**都有多程入口**，
    只是我们没接/结果页不给总价。只显示「不支持」= 把「我们不采集」
    读成「渠道没有这个产品」，用户自然要问「为啥不都实现」。
    """
    from core.channels import (CHANNEL_DIMENSIONS, DIMENSION_NOTES,
                               DIMENSIONS)
    missing = ["%s.%s" % (p, d)
               for p in CHANNEL_DIMENSIONS
               for d in DIMENSIONS
               if CHANNEL_DIMENSIONS[p].get(d) == "n"
               and not (DIMENSION_NOTES.get((p, d)) or "").strip()]
    assert not missing, (
        "这些格子写 n 却没有说明为什么：%s" % sorted(missing))


def test_partial_round_trip_channels_declare_scope_and_note():
    from core.channels import (CHANNEL_DIMENSIONS, DIMENSION_NOTES,
                               DIMENSION_SCOPE, DIMENSIONS)
    partial = {p for p, cells in CHANNEL_DIMENSIONS.items()
               if cells.get("round_trip") == "y"
               and (p, "round_trip") in DIMENSION_SCOPE}
    assert partial == {"fliggy", "app_qunar",
                      "app_tongcheng", "app_fliggy"}, (
        "「只覆盖一端」的往返渠道集合变了：%s（改声明时同步改本判据）"
        % sorted(partial))
    for p in partial:
        sc = DIMENSION_SCOPE[(p, "round_trip")]
        assert sc in ("仅国际", "仅国内"), (
            "%s 的范围短标签不是「仅国际/仅国内」：%r" % (p, sc))
        note = DIMENSION_NOTES.get((p, "round_trip")) or ""
        assert sc.strip("仅") in note, (
            "%s 的完整说明没写出范围（%r 里找不到 %r）——短标签与长说明"
            "必须说同一件事" % (p, note, sc))
    # 反向：全覆盖的渠道不得带 scope，否则会拼出假限定
    full = [p for p, cells in CHANNEL_DIMENSIONS.items()
            if cells.get("round_trip") == "y" and p not in partial]
    for p in full:
        assert (p, "round_trip") not in DIMENSION_SCOPE, (
            "%s 往返是全覆盖，不该有限定标签（会读成「只覆盖一端」）" % p)
    assert "round_trip" in DIMENSIONS, "本门禁的维度锚点失效"


def test_frontend_does_not_hardcode_rt_scope():
    src = webui_full_src()
    assert "RT_SCOPE_NOTE" not in src, (
        "前端仍留着写死的往返范围表——声明改了它不会跟着改")
    assert "channel_dims_payload()" in src, "接口没走单一矩阵载荷"
    payload = io.open(os.path.join(ROOT, "core", "channels.py"),
                      encoding="utf-8").read()
    i = payload.find('"channels": [')
    assert i > 0, "接口片段锚点失效"
    seg = payload[i:i + 1100]
    assert "dim_scopes" in seg, (
        "载荷没下发 dim_scopes，前端无从拼范围文案（只能退回写死）")






# ---- merged from tests/test_r805w_roundtrip_not_oneway_baseline.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FC, TC, D = "SHA", "BJS", "2026-11-27"


def _row(price, kind, ts):
    el = [{"price": price, "code": "HO1251", "name": "吉祥",
           "depDate": D, "depTime": "10:25", "arrTime": "12:40"}]
    if kind == "RT":
        el[0]["tripType"] = "RT"
        el[0]["backDate"] = "2026-12-01"
    return type("P", (), {
        "platform": "fliggy", "from_city": FC, "to_city": TC,
        "depart_date": D, "price": float(price), "airline": "吉祥",
        "flight_no": "HO1251", "depart_time": "10:25",
        "arrive_time": "12:40", "fetched_at": ts,
        "extra": json.dumps(el, ensure_ascii=False), "prov": ""})()


def _fresh():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_round_trip_row_does_not_replace_oneway_baseline():
    st = _fresh()
    # 单程先入库、往返后入库（MAX(id) 会选中往返那条）
    st.save_many([_row(500.0, "OW", "2026-11-27 10:00:00"),
                  _row(1200.0, "RT", "2026-11-27 10:05:00")])
    got = [(x["platform"], x["price"]) for x in st.latest_prices(24 * 7)]
    assert got == [("fliggy", 500.0)], (
        "往返 ¥1200 顶替了单程基线：重启后会以为当天明细已采过。实际 %s" % (got,))


def test_only_round_trip_means_no_oneway_baseline():
    st = _fresh()
    st.save_many([_row(1200.0, "RT", "2026-11-27 10:05:00")])
    got = st.latest_prices(24 * 7)
    assert got == [], (
        "当天只有往返行时不能返回单程基线（宁可当没采过）：%s" % (got,))


def test_plain_oneway_still_returned():
    """负控反面：修复不能把正常单程也挡掉。"""
    st = _fresh()
    st.save_many([_row(500.0, "OW", "2026-11-27 10:00:00")])
    got = [(x["platform"], x["price"]) for x in st.latest_prices(24 * 7)]
    assert got == [("fliggy", 500.0)], "普通单程基线被误挡：%s" % (got,)


def _daily_bucket(st):
    import sqlite3
    con = sqlite3.connect(st.db_path)
    try:
        return con.execute(
            "SELECT kind, n, lo, hi, open, close FROM price_daily "
            "WHERE from_city=? AND to_city=? AND depart_date=?",
            (FC, TC, D)).fetchall()
    finally:
        con.close()


def test_round_trip_does_not_inflate_daily_calendar():
    """`price_daily` 是**单程**价格日历的数据源，往返价不许混进去。

    受控实验（修复前）：先存单程 ¥500 重算日桶得
    `('d',1,500,500,500,500)`；再存往返 ¥1200 重算 → 变成
    `('d',2,500,1200,500,1200)`——**hi 与 close 被抬到往返价**。
    日历面板/日 OHLC/改期比价都读这张表，用户会看到"当天收盘 1200"，
    以为单程涨了 2.4 倍。
    """
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    st.save_many([_row(500.0, "OW", ts)])
    st.refresh_daily(FC, TC, D)
    before = _daily_bucket(st)
    assert before and before[0][3] == 500.0, before

    st.save_many([_row(1200.0, "RT", ts)])
    st.refresh_daily(FC, TC, D)
    after = _daily_bucket(st)
    assert after == before, (
        "往返价进了单程日桶：修复前 hi/close 会被抬到 1200。实际 %s" % (after,))
    # 反面：正常单程仍要能算进日桶
    st2 = _fresh()
    st2.save_many([_row(500.0, "OW", ts)])
    st2.refresh_daily(FC, TC, D)
    got = _daily_bucket(st2)
    assert got and got[0][1] == 1 and got[0][3] == 500.0, (
        "正常单程没能进日桶（修复过头）：%s" % (got,))


def _flight_bucket(st):
    import sqlite3
    con = sqlite3.connect(st.db_path)
    try:
        return con.execute(
            "SELECT n, lo, hi, open, close FROM flight_daily "
            "WHERE from_city=? AND to_city=? AND depart_date=?",
            (FC, TC, D)).fetchall()
    finally:
        con.close()


def test_round_trip_only_still_shows_on_calendar():
    """**反面回归**（r805y）：只配置往返的航线，日历不许空盘。

    r805x 的「一律排除往返」把口径污染治好了，却让「只配往返」的航线
    `price_daily`/`flight_daily` 双双 0 行——用户看不到任何走势。正确
    口径是**互斥而非排除**：有单程就用单程，一条单程都没有时用往返。
    """
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    st.save_many([_row(1200.0, "RT", ts)])
    st.refresh_daily(FC, TC, D)
    st.refresh_flight_daily(FC, TC, D)
    pd = _daily_bucket(st)
    fd = _flight_bucket(st)
    assert pd and pd[0][1] == 1 and pd[0][3] == 1200.0, (
        "只配往返时 price_daily 空了或价不对（走势长窗会整片没数）：%s" % (pd,))
    assert fd and fd[0][0] == 1 and fd[0][1] == 1200.0, (
        "只配往返时 flight_daily 空了或价不对：%s" % (fd,))


def test_mixed_still_prefers_oneway_not_average():
    """混合时必须**只用单程**，不能平均、也不能选较新的往返。"""
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    # 往返先入库、单程后入库（MAX(id) 会指向单程；这里主要防"平均"）
    st.save_many([_row(1200.0, "RT", ts), _row(500.0, "OW", ts)])
    st.refresh_daily(FC, TC, D)
    st.refresh_flight_daily(FC, TC, D)
    pd = _daily_bucket(st)
    fd = _flight_bucket(st)
    assert pd[0][1] == 1 and pd[0][4] == 500.0, (
        "混合时 price_daily 出现了往返/平均值：%s" % (pd,))
    assert fd[0][0] == 1 and fd[0][3] == 500.0, (
        "混合时 flight_daily 出现了往返/平均值：%s" % (fd,))


def test_round_trip_does_not_inflate_flight_daily():
    """`flight_daily` 按航班身份分桶——同一班机的单程价与往返总价会撞进
    同一个 key，hi/close 直接被抬到往返价（受控实验：500 → 1200）。
    航班历史面板要给的是「这班单程卖多少钱」。
    """
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    st.save_many([_row(500.0, "OW", ts)])
    st.refresh_flight_daily(FC, TC, D)
    before = _flight_bucket(st)
    assert before and before[0][2] == 500.0, before

    st.save_many([_row(1200.0, "RT", ts)])
    st.refresh_flight_daily(FC, TC, D)
    after = _flight_bucket(st)
    assert after == before, (
        "往返价进了航班日桶：修复前 close 会从 500 变 1200。实际 %s" % (after,))
    st2 = _fresh()
    st2.save_many([_row(500.0, "OW", ts)])
    st2.refresh_flight_daily(FC, TC, D)
    got = _flight_bucket(st2)
    assert got and got[0][0] == 1 and got[0][1] == 500.0, (
        "正常单程没能进航班日桶（修复过头）：%s" % (got,))


# ---- merged from tests/test_r901_capability_matrix_rendered.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port






















# ---- merged from tests/test_r915_android_hardening.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r915")

_ABI_PROPS = dict(abi_canary.ABI_X86)


class FakeDev:
    """够用的 adb 替身：props / settings / wm / logcat / am / dump。

    ``apply_noop=True`` 模拟「ro.* 只读、setprop 静默无效」——2026-11-03 在无
    Magisk 的 MuMu 上实测到的真实情况，用来钉住 canary 不许把它判成成功。
    """

    def __init__(self, props=None, logcat="", activity="", xml="<node>" * 8,
                 size="Physical size: 900x1600", density="Physical density: 320",
                 fail_activity=False, apply_noop=False, can_write=True):
        self.props = dict(props if props is not None else _ABI_PROPS)
        self.logcat = logcat
        self.activity = activity
        self.xml = xml
        self.size = size
        self.density = density
        self.fail_activity = fail_activity
        self.apply_noop = apply_noop
        # can_write=True 模拟"有 Magisk/resetprop"的实例；False 模拟实测的
        # 那台 MuMu（三条路全堵）
        self.can_write = can_write
        self.calls = []
        self.mark = ""
        self._su = True

    def _sh(self, *args, timeout=None):
        cmd = " ".join(str(a) for a in args)
        self.calls.append(cmd)
        return self._route(cmd)

    def _route(self, cmd):
        # `fingerprint.as_root()` 现在把脚本 **base64** 后传输
        # （`echo <b64> | base64 -d | sh`）——因为引号经 adb shell 会丢。
        # 假设备要把它解回来再路由，否则所有 as_root 调用都变成"没执行"。
        if "base64 -d" in cmd:
            import base64 as _b64
            import re as _re
            m = _re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", cmd)
            if m:
                try:
                    real = _b64.b64decode(m.group(1)).decode("utf-8")
                except Exception:
                    return ""
                return self._route("shell " + real)
            return ""
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v) for k, v in self.props.items())
        if "command -v resetprop" in cmd:
            return "/data/adb/magisk/resetprop" if self.can_write else ""
        # `_magisk()` 现在用 `ls <path>` 直传探测（`sh -c "test -e \'...\'"`
        # 经 adb shell 后引号会丢，实测误报 TM_NO）。假设备要跟着支持。
        if cmd.startswith("shell ls "):
            _p = cmd[len("shell ls "):].strip()
            if not self.can_write:
                return ""
            if _p.endswith("resetprop"):
                return "/data/adb/magisk/resetprop"
            if _p.endswith("/magisk"):
                return "/data/local/tmp/magisk_bin/magisk"
            return ""
        if "command -v su" in cmd:
            return "/system/bin/su" if self._su else ""
        if "remount,rw" in cmd:
            # 模拟实测：块设备只读 → touch 失败
            return "mount: '/dev/block/sda6' is read-only\nTM_RW_FAIL\n"
        if "boot_id" in cmd:
            return "boot-1"
        if cmd.startswith("shell logcat -c"):
            # 假设备不清日志：这些测试要看的是"启动后出现了什么崩溃行"，
            # 清掉反而测不到（真机上 `logcat -c` 是必要的）。
            return ""
        if cmd.startswith("shell logcat"):
            return self.logcat
        if cmd.startswith("shell am force-stop"):
            return ""
        if cmd.startswith("shell monkey"):
            return "Events injected: 1"
        if cmd.startswith("shell current") or "dumpsys activity" in cmd:
            if self.fail_activity:
                raise RuntimeError("device gone")
            return "topResumedActivity=ActivityRecord{x y %s/Launcher}" % (
                self.activity or "com.example")
        if cmd.startswith("shell dumpsys package"):
            # 与实机一致（2026-11-03 实测 MuMu/Android 15）：目标包都是
            # arm64-v8a 主 ABI。预检据此判 low，canary 才肯动手。
            pkg = cmd.rsplit(" ", 1)[-1]
            return ("Packages:\n  Package [%s]\n    primaryCpuAbi=%s\n"
                    "    secondaryCpuAbi=null\n" % (pkg,
                                                  getattr(self, "primary",
                                                          "arm64-v8a")))
        if cmd.startswith("shell wm size"):
            return self.size
        if cmd.startswith("shell wm density"):
            return self.density
        # **`_magisk()` 的 delete-then-set 探针是"裸命令"**（参数直接传，
        # 不经 `sh -c`、不带引号）：`shell <rp> --delete ro.boot.revision`
        # 和 `shell <rp> ro.boot.revision tmprobe`。要按真实语义回答，
        # 否则 `_magisk()` 会判"没有可用 resetprop"，apply_props 退化成
        # `setprop`，整批身份写入的 verified 就空了。
        if "resetprop" in cmd and "echo" not in cmd:
            parts = cmd.split()
            if "--delete" in parts:
                _i = parts.index("--delete")
                if _i + 1 < len(parts):
                    self.props[parts[_i + 1].strip("'")] = ""
                return ""
            _i = parts.index("resetprop")
            if _i + 2 < len(parts) and not self.apply_noop:
                self.props[parts[_i + 1].strip("'")] = (
                    parts[_i + 2].strip("'"))
            return ""
        if "-n " in cmd or "setprop" in cmd:
            # 只解析两种真实形态：`setprop 'KEY' 'VAL'` 与
            # `<path>/resetprop -n 'KEY' 'VAL'`（apply_props 就是把它们拼成
            # 一条 `... && echo OK ... || echo FAIL ...` 的脚本）。
            import re as _re
            out = []
            for m in _re.finditer(r"(?:setprop|-n)\s+'([^']+)'\s+'([^']*)'", cmd):
                key, val = m.group(1), m.group(2)
                if not self.apply_noop:
                    self.props[key] = val
                out.append("OK " + key)
            return "\n".join(out)
        if "cat /data/local/tmp/tm_" in cmd:
            return self.mark
        return ""

    # probe 走 current_activity / dump
    def current_activity(self):
        if self.fail_activity:
            raise RuntimeError("device gone")
        # 真实 AdbDevice 返回 `pkg/Activity`，probe 按 `/` 前段比对包名
        return "%s/.Main" % (self.activity or "com.example")

    def dump(self):
        return self.xml


# ---------------------------------------------------------------------------
# 1. ABI canary
# ---------------------------------------------------------------------------
def test_canary_ok_path_restores_and_persists(tmp_path):
    dev = FakeDev(activity="ctrip.android.view")
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is True
    assert rep["restored"] is True
    # 恢复的是原值，不是硬编码
    assert rep["after"].get("ro.product.cpu.abi") == _ABI_PROPS["ro.product.cpu.abi"]
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is True
    # 落盘可读
    v = abi_canary.verdict(str(tmp_path))
    assert v["ctrip.android.view"]["ok"] is True


def test_canary_failure_still_restores_and_records(tmp_path):
    dev = FakeDev(activity="ctrip.android.view",
                  logcat="E AndroidRuntime: Process: ctrip.android.view, "
                         "java.lang.UnsatisfiedLinkError: libx.so")
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False
    assert rep["restored"] is True
    assert "UnsatisfiedLinkError" in (rep["probe"]["errors"] or [])
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


def test_probe_ignores_foreign_crashes(tmp_path):
    """框架重启时 system_server 的 SIGSEGV 不能算到 App 头上。"""
    dev = FakeDev(activity="ctrip.android.view",
                  logcat="F DEBUG: pid 1234, tid 1234, SIGSEGV\n"
                         "E ActivityManager: ANR in system_server")
    rep = abi_canary.probe(dev, "ctrip.android.view", wait_s=2)
    assert rep["errors"] == []
    assert rep["foreign_crashes"] >= 1


def test_canary_restores_even_when_probe_raises(tmp_path):
    dev = FakeDev(activity="ctrip.android.view", fail_activity=True)
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False
    # 关键：异常路径也必须恢复
    assert rep["restored"] is True
    assert any("wm" in c or "setprop" in c or "-n " in c for c in dev.calls)


def _writes(dev):
    """从调用记录里挑出**真正的写入**（能力探测里的 `command -v resetprop`
    含 `-n `，不是写）。"""
    return [c for c in dev.calls
            if "setprop '" in c or "resetprop -n '" in c]


def test_canary_dry_run_does_not_touch_device(tmp_path):
    dev = FakeDev()
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1, dry_run=True)
    assert rep["ok"] is True and rep["dry_run"] is True
    assert _writes(dev) == []


def test_spoof_allowed_expires(tmp_path):
    dev = FakeDev(activity="ctrip.android.view")
    abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                   user_data_dir=str(tmp_path), restart_wait_s=1)
    import time as _t
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path),
                                    now=_t.time() + 8 * 86400) is False
    assert abi_canary.spoof_allowed("nope.pkg", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# 1b. 只读预检（判定「改了会不会炸」）
# ---------------------------------------------------------------------------
def _abi_dev(abilist="x86_64,arm64-v8a,x86", abilist64="x86_64,arm64-v8a",
             bridge="libnb.so", primary="arm64-v8a", can_write=True):
    """造一台带 dumpsys 输出的设备。"""
    dev = FakeDev(can_write=can_write)
    dev.props.update({"ro.product.cpu.abilist": abilist,
                      "ro.product.cpu.abilist64": abilist64,
                      "ro.dalvik.vm.native.bridge": bridge})
    dev.primary = primary
    orig = dev._route

    def _route(cmd):
        if cmd.startswith("shell dumpsys package"):
            pkg = cmd.rsplit(" ", 1)[-1]
            return ("Packages:\n  Package [%s]\n    primaryCpuAbi=%s\n"
                    "    secondaryCpuAbi=null\n    versionCode=1\n"
                    % (pkg, dev.primary))
        return orig(cmd)
    dev._route = _route
    return dev


def test_preflight_low_when_all_packages_are_arm64():
    dev = _abi_dev(primary="arm64-v8a")
    rep = abi_canary.preflight(dev, ["ctrip.android.view", "com.Qunar"])
    assert rep["ok"] is True and rep["risk"] == "low"
    assert "so 选择已定" in rep["why"]
    assert set(rep["packages"]) == {"ctrip.android.view", "com.Qunar"}


def test_preflight_high_when_packages_still_x86():
    dev = _abi_dev(primary="x86_64")
    rep = abi_canary.preflight(dev, ["ctrip.android.view"])
    assert rep["ok"] is False and rep["risk"] == "high"
    assert "x86_64" in rep["why"]


def test_preflight_medium_when_mixed(tmp_path):
    dev = _abi_dev(primary="arm64-v8a")
    orig = dev._route
    seen = {"n": 0}

    def _route(cmd):
        if cmd.startswith("shell dumpsys package"):
            seen["n"] += 1
            pkg = cmd.rsplit(" ", 1)[-1]
            abi = "arm64-v8a" if "ctrip" in pkg else "x86_64"
            return "primaryCpuAbi=%s\nsecondaryCpuAbi=null\n" % abi
        return orig(cmd)
    dev._route = _route
    rep = abi_canary.preflight(dev, ["ctrip.android.view", "com.Qunar"])
    assert rep["risk"] == "medium" and rep["ok"] is True


def test_preflight_blocked_without_arm_runtime():
    dev = _abi_dev(abilist="x86_64,x86", abilist64="x86_64", bridge="")
    rep = abi_canary.preflight(dev, ["ctrip.android.view"])
    assert rep["ok"] is False and rep["risk"] == "blocked"
    assert "没有 arm64-v8a" in rep["why"]


def test_preflight_no_installed_package():
    dev = _abi_dev()
    orig = dev._route
    dev._route = lambda cmd: ("Unable to find package" if "dumpsys" in cmd
                              else orig(cmd))
    rep = abi_canary.preflight(dev, ["com.nope"])
    assert rep["ok"] is False
    assert "没有已安装" in rep["why"]


def test_preflight_blocked_when_no_write_channel():
    """无 Magisk + 块设备只读 → **全局** ro.* 改不了，必须判 blocked。

    这种情况下即使 app 全是 arm64，也不能让 canary 白跑一次
    「命令报成功、读回没变」的过程。

    但提示必须指向**能走通的那条路**（MuMu 官方 per-app ABI 表）——
    2026-11-03 实测 ABI 伪装已通过 abi-select 表跑通，与全局 ro.* 无关。
    """
    dev = _abi_dev(primary="arm64-v8a", can_write=False)
    rep = abi_canary.preflight(dev, ["ctrip.android.view"])
    assert rep["ok"] is False and rep["risk"] == "blocked"
    assert "ro.*" in rep["why"]
    assert rep["capabilities"]["can_write_ro"] is False
    # 提示里要有「官方 per-app 表」这条真正可走的路，以及 Magisk 作为兜底
    assert "set_app_abi" in rep["why"] or "per-app" in rep["why"], rep["why"]
    assert "Magisk" in rep["why"]


def test_canary_refuses_without_write_channel(tmp_path):
    dev = _abi_dev(primary="arm64-v8a", can_write=False)
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False and "预检未通过" in rep["error"]
    assert _writes(dev) == []
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


def test_canary_refuses_when_preflight_blocks(tmp_path):
    """预检不过时**一个 prop 都不许写**——canary 自己不能把设备改坏。"""
    dev = _abi_dev(abilist="x86_64,x86", abilist64="x86_64", bridge="")
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False
    assert "预检未通过" in rep["error"]
    assert _writes(dev) == []
    # 也不许落 ok 判定
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


def test_canary_refuses_when_props_are_readonly(tmp_path):
    """这台 MuMu 的真实情况：无 Magisk，setprop 对 ro.* 静默无效。

    命令全报 OK、读回一条没变 —— 必须判成「写不进去」并给出原因，
    **不许**把它当成可行、更不许落 ok 判定。
    """
    dev = FakeDev(activity="ctrip.android.view", apply_noop=True)
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False and rep["wrote"] is False
    # 报错文案要么点出"读回没生效"，要么点出"机型字段不许热改"
    # （两者都是拒绝，不是放行）。
    # 三种**都是合法拒绝**（关键是 `wrote=False`，没把只读判成可行）：
    #   预检未通过      —— 还没动手就拦下（最省事）
    #   读回没生效      —— 试了但没写进去
    #   机型字段禁热改  —— 明确不让运行中改
    assert any(k in rep["error"] for k in
               ("读回生效", "热改", "官方键", "预检未通过")), rep["error"][:120]
    assert not rep["probe"]                      # 没写进去就不该探活
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# 2. 显示：解析 / 对齐 / 计划 / 缩放
# ---------------------------------------------------------------------------
def test_display_actual_prefers_override():
    dev = FakeDev(size="Physical size: 720x1280\nOverride size: 1080x2400",
                  density="Physical density: 320\nOverride density: 440")
    got = display.actual(dev)
    assert (got["width"], got["height"]) == (1080, 2400)
    assert got["density"] == 440 and got["override"] is True


def test_align_identity_rewrites_profile_only():
    ident = fingerprint.build(5, vm=0)
    before_display = list(ident.profile.get("display") or [])
    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    rep = display.align_identity(ident, dev)
    assert rep["changed"] is True
    assert ident.profile["display"] == [900, 1600]
    assert ident.profile["density"] == 320
    assert before_display != ident.profile["display"]
    # 不动设备设置
    assert not [c for c in dev.calls if c.startswith("shell wm size ") and
                "reset" not in c]


def test_plan_spoof_keeps_dp_size_constant():
    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    p = display.plan_spoof(dev, width=1080, height=1920)
    # 1920/1600 = 1.2 → density 320*1.2 = 384
    assert (p["width"], p["height"]) == (1080, 1920)
    assert p["density"] == 384


def test_scale_for_and_audit():
    assert display.scale_for((900, 1600), (1080, 1920)) == (1.2, 1.2)
    assert display.scale_for(None, None) == (1.0, 1.0)
    assert display.scale_for((0, 0), (100, 100)) == (1.0, 1.0)
    ident = fingerprint.build(1, vm=0)
    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    got = display.audit(dev, ident)
    assert got["ok"] is False and got["issues"]     # 池里机型不会是 900x1600


# ---------------------------------------------------------------------------
# 3. AdbDevice 坐标换算
# ---------------------------------------------------------------------------
def _device(monkeypatch, size="900x1600"):
    from core.android import device as devmod
    calls = []

    class _P:
        def __init__(self, out):
            self.stdout = out.encode()
            self.stderr = b""
            self.returncode = 0

    def _run(cmd, timeout, binary=False):
        calls.append(" ".join(cmd))
        if "wm" in cmd and "size" in cmd:
            return _P("Physical size: %s" % size)
        return _P("")
    monkeypatch.setattr(devmod, "_run", _run)
    d = devmod.AdbDevice("adb", "127.0.0.1:16384")
    return d, calls


def test_device_without_design_is_unchanged(monkeypatch):
    d, calls = _device(monkeypatch)
    assert d.tap(100, 200) is True
    assert any(c.endswith("input tap 100 200") for c in calls)


def test_device_scales_when_design_set(monkeypatch):
    d, calls = _device(monkeypatch, size="1080x1920")
    d.set_design(900, 1600)                     # 1.2×
    assert d.to_device(100, 200) == (120, 240)
    assert d.to_design(120, 240) == (100, 200)
    d.tap(100, 200)
    assert any(c.endswith("input tap 120 240") for c in calls), calls
    d.swipe(0, 0, 100, 100, 200)
    assert any(c.endswith("input swipe 0 0 120 120 200") for c in calls), calls


def test_device_set_design_zero_disables(monkeypatch):
    d, _ = _device(monkeypatch)
    d.set_design(900, 1600)
    assert d.set_design(0, 0) is None
    assert d.to_device(10, 10) == (10, 10)


# ---------------------------------------------------------------------------
# 4. 编排顺序与 ABI 闸门
# ---------------------------------------------------------------------------
def test_harden_runs_steps_in_fixed_order(monkeypatch, tmp_path):
    order = []

    def _ident(dev, cfg, log, **kw):
        order.append("identity")
        return {"ok": True}

    def _stealth(dev, cfg, log, **kw):
        order.append("stealth")
        return {"ok": True}

    def _tune(dev, cfg, log, **kw):
        order.append("tuning")
        return {"ok": True}

    monkeypatch.setattr(fingerprint, "ensure", _ident)
    from core.android import stealth as st_mod
    from core.android import emulator_tuning as tune_mod
    monkeypatch.setattr(st_mod, "prepare", _stealth)
    monkeypatch.setattr(tune_mod, "apply", _tune)

    dev = FakeDev()
    rep = hardening.harden(dev, {"android": {}}, _LOG,
                           user_data_dir=str(tmp_path))
    assert order == ["identity", "stealth", "tuning"]
    assert rep["ok"] is True
    # 没有身份文件就不做对齐，但也不报错
    assert [s for s in rep["steps"] if s[0] == "display-align"][0][1] is True


def test_harden_aligns_display_when_identity_exists(monkeypatch, tmp_path):
    store = fingerprint.default_store(str(tmp_path), "device")
    ident = fingerprint.build(9, vm=0)
    store.put(ident)

    monkeypatch.setattr(fingerprint, "ensure",
                        lambda *a, **k: {"ok": True, "skipped": "test"})
    from core.android import stealth as st_mod
    from core.android import emulator_tuning as tune_mod
    monkeypatch.setattr(st_mod, "prepare", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(tune_mod, "apply", lambda *a, **k: {"ok": True})

    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    rep = hardening.harden(dev, {"android": {}}, _LOG,
                           user_data_dir=str(tmp_path))
    assert rep["display"]["align"]["changed"] is True
    saved = fingerprint.default_store(str(tmp_path), "device").get(0)
    assert saved.profile["display"] == [900, 1600]


def test_abi_gate_off_by_default(monkeypatch, tmp_path):
    dev = FakeDev()
    rep = hardening._abi_gate(dev, {"android": {}}, _LOG,
                              user_data_dir=str(tmp_path))
    assert rep["ok"] is True and "skipped" in rep
    assert not [c for c in dev.calls if "-n " in c]


def test_abi_gate_auto_requires_canary_verdict(monkeypatch, tmp_path):
    cfg = {"android": {"identity": {"spoof_abi": "auto"}}}
    dev = FakeDev()
    rep = hardening._abi_gate(dev, cfg, _LOG, user_data_dir=str(tmp_path))
    assert rep["ok"] is True and "canary" in rep["skipped"]
    assert not [c for c in dev.calls if "-n " in c]

    # 造一份 ok 判定 → 允许写
    import json
    import time
    path = os.path.join(str(tmp_path), "device", "abi_canary.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pkg = next(iter(__import__("core.android.stealth", fromlist=["x"])
                    .KNOWN_APPS.values()))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({pkg: {"ok": True, "at": time.time()}}, f)
    dev2 = FakeDev()
    rep2 = hardening._abi_gate(dev2, cfg, _LOG, user_data_dir=str(tmp_path))
    assert rep2["ok"] is True and rep2.get("apply", {}).get("applied")


# ---- merged from tests/test_r961_buildid_sync.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PROPS = {
    "ro.product.model": "V2405A",
    "ro.product.brand": "vivo",
    "ro.product.device": "V2405A",
    "ro.build.version.release": "15",
    "ro.build.version.sdk": "35",
    "ro.build.version.incremental": "1171",
    "ro.build.id": "V417IR",
    "ro.build.display.id": "V417IR release-keys",
    "ro.build.fingerprint":
        "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys",
}


class _Dev:
    def __init__(self, props=None):
        self.props = dict(props if props is not None else PROPS)
        self.set_calls = []
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        return ""


def _fake_magisk(monkey, path="/data/adb/magisk/magisk resetprop"):
    """resetprop 写成功 = 让 getprop 读回目标值（真实写用 sh_script 记录）。

    注意脚本里的值是 `_q()` 加过单引号的，必须脱引号再落到 props 上，
    否则读回比对会因为多两个引号字符而假失败。
    """
    import re
    monkey.setattr(bi, "_magisk", lambda dev: path)

    def fake_sh(dev, script, timeout=None):
        dev.set_calls.append(script)
        m = re.search(r"resetprop\s+(\S+)\s+(.+)$", script)
        if m:
            v = m.group(2).strip()
            if v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            dev.props[m.group(1)] = v
        return ""

    monkey.setattr(bi, "sh_script", fake_sh)


# ---------------------------------------------------------------------------
# 1. 边界：改什么由"值里含旧 build 号"**动态发现**，安全边界靠**排除表**兜
# ---------------------------------------------------------------------------
def test_banned_list_covers_structural_keys():
    """不再断言"白名单里没有危险键"，而是断言**排除表覆盖**危险键。

    白名单一定会漏：第一版只列了 `ro.build.id` + 六个分区 fingerprint，
    漏掉五个分区 `ro.<part>.build.id` 与 `ro.vendor_dlkm.*`，
    结果写出 `Build.ID=AP3A…` 而 `ro.system.build.id=V417IR` 的**半改状态**
    —— 比不改更糟，因为自洽性正是风控 SDK 最常查的一项。
    现在模型是"含旧号就改"，兜底的只能是排除表，所以它必须显式覆盖：
    版本族 / ABI / SoC / 启动链 / 序列号 / adb 开关 / dalvik。
    """
    need = ("ro.build.version.", "ro.product.cpu.", "ro.hardware",
            "ro.board.platform", "ro.boot.", "ro.serialno",
            "ro.adb.secure", "ro.debuggable", "dalvik.")
    for n in need:
        assert n in bi.BANNED_SUBSTR, "%s 必须在排除表里" % n


def test_target_for_emits_only_keys_it_was_given():
    """计划里的键全部来自传入的 props，一个都不发明（这就是动态发现）。"""
    props = dict(PROPS)
    props["ro.vendor.build.id"] = "V417IR"      # 模拟分区 id 落后
    props["ro.build.description"] = "missi_V2405A-user 15 V417IR 1171 x"
    want = bi.target_for(props)
    assert want, "含旧 build 号却没生成计划"
    assert set(want) <= set(props), set(want) - set(props)
    for k in ("ro.build.id", "ro.build.display.id", "ro.build.description",
              "ro.build.fingerprint", "ro.vendor.build.id"):
        assert k in want, "%s 含旧号却漏发现（成套字段漏一个=半改）" % k
    assert all("V417IR" not in v for v in want.values()), want


def test_target_for_invents_nothing_for_absent_keys():
    """设备上没读到的键，绝不凭空生成写入。

    这不是吹毛求疵：白名单版本会给设备上**并不存在**的键硬写一个值，
    于是"改了什么"和"设备上有什么"两套事实开始分叉。
    动态发现天然只会处理真存在的值 —— 这正是放弃白名单的理由。
    """
    props = {"ro.product.model": "V2405A", "ro.build.id": "V417IR"}
    want = bi.target_for(props)
    assert set(want) <= set(props), set(want) - set(props)
    assert "ro.build.description" not in want, \
        "props 里没有 description，不该凭模板造一个写进去"


def test_banned_key_is_skipped_even_if_it_holds_old_id():
    """排除表优先于动态发现：版本族键哪怕含旧号也不许改。"""
    props = dict(PROPS)
    props["ro.build.version.incremental"] = "15.V417IR"
    want = bi.target_for(props)
    assert "ro.build.version.incremental" not in want, \
        "改到版本族键：这正是今天两次 system_server 重启的成因"


def test_target_for_keeps_version_and_incr_untouched():
    """fingerprint 里的 release/incremental **沿用现值**，不自己造版本。"""
    want = bi.target_for(PROPS)
    fp = want["ro.build.fingerprint"]
    assert ":15/" in fp and fp.endswith("1171:user/release-keys"), fp
    assert "V417IR" not in fp, "fingerprint 里还留着 MuMu 的 build 号"
    assert want["ro.build.id"] != "V417IR"


def test_target_for_refuses_unknown_model():
    """机型不在池里 → 空 dict（不凭猜写一个 build 号进去）。"""
    assert bi.target_for({"ro.product.model": "NOPE-1",
                          "ro.build.id": "V417IR"}) == {}


def test_target_for_is_inplace_replace_not_recompose():
    """只替换旧 build 号那一段，其余部分**原样保留**。

    MuMu 注入器已经把 flavor/release/incremental/tags 组成一套自洽值，
    自己按模板重拼任何一处对不上，就制造出新矛盾（比统一像模拟器更可疑）。
    """
    props = {
        "ro.product.model": "V2405A",
        "ro.build.id": "V417IR",
        "ro.build.display.id": "V417IR release-keys",
        "ro.build.description": "missi_V2405A-user 15 V417IR 1171 release-keys",
        "ro.build.fingerprint":
            "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys",
        "ro.vendor.build.fingerprint":
            "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys",
    }
    want = bi.target_for(props)
    assert want["ro.build.display.id"] == "AP3A.240905.015 release-keys", want
    assert want["ro.build.description"] == (
        "missi_V2405A-user 15 AP3A.240905.015 1171 release-keys"), want
    assert want["ro.build.fingerprint"] == (
        "vivo/V2405A/V2405A:15/AP3A.240905.015/1171:user/release-keys"), want
    # description 也要被发现：漏了它就会出现 ID 与 DESCRIPTION 互相矛盾
    assert "ro.build.description" in want, want
    # 不含旧 build 号的键一律不动；设备上是空值的键也不发明
    assert all("V417IR" not in v for v in want.values()), want
    assert set(want) <= set(props), set(want) - set(props)


def test_already_coherent_is_not_a_failure():
    """已经自洽时返回空目标，且 `sync` 必须算 ok（不能污染成功率账本）。"""
    props = {"ro.product.model": "V2405A",
             "ro.build.id": "AP3A.240905.015",
             "ro.build.fingerprint":
                 "vivo/V2405A/V2405A:15/AP3A.240905.015/1171:user/release-keys"}
    assert bi.target_for(props) == {}


def test_sync_reports_residual_and_refuses_to_claim_success(monkeypatch):
    """写完必须复查"全机还有没有旧 token"。

    只检查"我改过的键对不对"是不够的：真实事故里九个键**全部写成功**，
    而另外七个键压根没进入计划，日志一片 green —— 半改状态被当成改完了。
    这条用例把"有残留 ⇒ ok=False / verified=False"钉住。
    """
    monkeypatch.setattr(bi, "_magisk",
                        lambda dev: "/data/adb/magisk/magisk resetprop")

    def fake_sh(dev, script, timeout=None):
        # 只写入 props 里**已存在**的键：分区 id 不在计划里 → 留下残留
        import re
        m = re.search(r"resetprop\s+(\S+)\s+(.+)$", script)
        if m:
            k = m.group(1)
            v = m.group(2).strip().strip("'")
            # **只让主命名空间写成功**，分区键模拟"没生效" ——
            # 动态发现之后分区键本来就在计划里，若照原写法全部写成功，
            # 这个用例根本测不到残留。
            if k.startswith("ro.build."):
                dev.props[k] = v
        dev.set_calls.append(script)
        return ""

    monkeypatch.setattr(bi, "sh_script", fake_sh)
    props = dict(PROPS)
    props["ro.system.build.id"] = "V417IR"     # 在计划内，但假写不生效 → 残留
    d = _Dev(props=props)
    rep = bi.sync(d, CFG)
    assert rep.get("residual"), rep
    assert rep["ok"] is False and rep["verified"] is False, rep


# ---------------------------------------------------------------------------
# 2. 默认关：不许有任何设备动作
# ---------------------------------------------------------------------------
def test_disabled_by_default(monkeypatch):
    d = _Dev()
    rep = bi.sync(d)
    assert rep["changed"] == 0 and "未启用" in rep["skipped"], rep
    assert d.set_calls == [], "开关没生效，默认就在写设备"


def test_no_resetprop_channel_reports_failure():
    import pytest
    d = _Dev()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bi, "_magisk", lambda dev: "")
    try:
        rep = bi.sync(d, config={"android": {"build_id": {"enabled": True}}})
        assert rep["ok"] is False and rep["changed"] == 0, rep
        assert "resetprop" in rep["error"]
    finally:
        monkey.undo()


# ---------------------------------------------------------------------------
# 3. 开启后：写、读回、失败不谎报
# ---------------------------------------------------------------------------
CFG = {"android": {"build_id": {"enabled": True}}}


def test_sync_applies_and_verifies(monkeypatch):
    _fake_magisk(monkeypatch)
    d = _Dev()
    rep = bi.sync(d, CFG)
    assert rep["ok"] is True and rep["changed"] > 0, rep
    assert rep["verified"] is True and not rep["failed"]
    assert any("--delete" in c for c in d.set_calls), \
        "没先 --delete：property area 的『已写过』标记会让 set 静默失效（§6.31）"
    assert d.props["ro.build.id"] != "V417IR"
    assert "V417IR" not in d.props["ro.build.fingerprint"]


def test_sync_is_cheap_when_already_coherent(monkeypatch):
    """已自洽时不该再发任何 resetprop（这条路径每轮都会走）。"""
    _fake_magisk(monkeypatch)
    d = _Dev()
    bi.sync(d, CFG)                       # 第一次真写
    n = len(d.set_calls)
    rep2 = bi.sync(d, CFG)                # 第二次应零写入
    assert rep2["changed"] == 0 and rep2["skipped"] == "已自洽", rep2
    assert len(d.set_calls) == n, "已自洽还在重复写"


def test_sync_refuses_unknown_model_on_device():
    """机型不认识时**什么都不写**，但这是"无事可做"，不是失败。"""
    d = _Dev(props={"ro.product.model": "MYSTERY",
                    "ro.build.id": "V417IR",
                    "ro.build.fingerprint": "x"})
    rep = bi.sync(d, CFG)
    assert rep["changed"] == 0 and rep["verified"] is True, rep
    assert rep["skipped"] and "不在 PHONE_POOL" in rep["skipped"], rep


def test_sync_does_not_claim_success_when_readback_mismatches(monkeypatch):
    """核心诚实条款：写命令返回 0 不算成功，必须读回相等。"""
    monkeypatch.setattr(bi, "_magisk",
                        lambda dev: "/data/adb/magisk/magisk resetprop")

    def fake_sh(dev, script, timeout=None):
        dev.set_calls.append(script)      # 记录写入，但 props **不变**
        return ""

    monkeypatch.setattr(bi, "sh_script", fake_sh)
    d = _Dev()
    rep = bi.sync(d, CFG)
    assert rep["ok"] is False, "读回没变却报成功（假成功）"
    assert rep["failed"], rep
    assert rep["verified"] is False


# ---------------------------------------------------------------------------
# 4. 接进流水线（否则又是一个只写不读的死模块）
# ---------------------------------------------------------------------------
def test_wired_into_harden():
    src = io.open(os.path.join(ROOT, "core", "android", "hardening.py"),
                  encoding="utf-8").read()
    assert "buildid" in src and '"build-id"' in src, "没接进 harden()"
    # 在 magisk 步之后：这条通道依赖 resetprop 已就位
    assert src.find("magisk-resetprop") < src.find("buildid"), \
        "顺序错了：resetprop 还没部署就想去盖"


def test_off_in_example_config():
    ex = io.open(os.path.join(ROOT, "config.example.yaml"),
                 encoding="utf-8").read()
    i = ex.find("build_id:")
    assert i > 0 and "enabled: false" in ex[i:i + 60], \
        "示例配置默认必须是关（要人工在采集空档验证）"
