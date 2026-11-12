# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1061_net_no_env_proxy.py
- tests/test_r1069_hardening_probe.py
- tests/test_r252_sentinel.py
- tests/test_r353_brand_identity.py
- tests/test_r356_icons.py
- tests/test_r395_path_rename_recovery.py
- tests/test_r403_empty_needs_evidence.py
- tests/test_r406_retired_path_live_rate.py
- tests/test_r605_config_clamp_is_visible.py
- tests/test_r606_every_number_is_validated.py
- tests/test_r719_narrow_channel_surfaces.py
- tests/test_r805ax_doc_matrix_matches_code.py
- tests/test_r805z_matrix_three_way.py
- tests/test_r822_static_demo_surfaces.py
- tests/test_r922_display_spoof.py
- tests/test_r926_selfaudit_no_false_positive.py
- tests/test_r958_argv_split.py
- tests/test_r967_yield_report_reads_real_paths.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import base64
import core.net as net
import hashlib
import httpx
import io
import json
import logging
import main as _m
import os
import pytest
import re
import sys
import tempfile
import importlib.util as _ilu

# W1：yield_report.py 已迁 scripts/（原 docs/ 内联导入位失效），按路径加载
_yr_spec = _ilu.spec_from_file_location(
    "yield_report",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "scripts", "yield_report.py"))
yr = _ilu.module_from_spec(_yr_spec)
_yr_spec.loader.exec_module(yr)

from PIL import Image, ImageChops
from core.alerter import Alerter
from core.android import display, fingerprint as fp, stealth as st
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_DIMENSIONS, DIMENSIONS, app_alignment_gaps, plat_cn
from core.models import CAL_PATH_FAMILY
from core.riskscore import default_ledger as default_login
from core.storage import PriceStorage
from core.yield_stats import default_ledger
from types import SimpleNamespace as _NS


# ---- merged from tests/test_r1061_net_no_env_proxy.py ----

def test_new_client_survives_broken_no_proxy(monkeypatch):
    """坏 NO_PROXY 下建客户端不能抛异常（这正是线上空转的现场）。"""
    monkeypatch.setenv('NO_PROXY', '[::1]')
    monkeypatch.setenv('no_proxy', '[::1]')
    c = net.new_client('', headers={'A': 'b'}, timeout=5)
    try:
        assert getattr(c, '_trust_env', False) is False
        assert not (getattr(c, '_mounts', None) or {}), (
            '不该套任何环境代理路由')
    finally:
        c.close()


def test_raw_httpx_still_breaks_on_that_env(monkeypatch):
    """反证：不经过 net.py 的裸 httpx 仍然会崩，说明问题确实来自环境代理。

    这条是负控——如果哪天 httpx 自己修好了，它会失败，提醒我们复评。
    """
    monkeypatch.setenv('NO_PROXY', '[::1]')
    monkeypatch.setenv('no_proxy', '[::1]')
    try:
        httpx.Client().close()
    except httpx.InvalidURL:
        return
    raise AssertionError('httpx 已不再受该环境变量影响，请复评本文件前提')


def test_get_and_post_pass_trust_env_false(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen['get'] = kw
        return 'GET'

    def fake_post(url, **kw):
        seen['post'] = kw
        return 'POST'

    # 强制走 httpx 兜底分支（impersonate=""）
    monkeypatch.setattr(httpx, 'get', fake_get)
    monkeypatch.setattr(httpx, 'post', fake_post)
    assert net.get('http://x', impersonate='') == 'GET'
    assert net.post('http://x', impersonate='') == 'POST'
    assert seen['get'].get('trust_env') is False
    assert seen['post'].get('trust_env') is False


def test_explicit_proxy_still_honoured(monkeypatch):
    """显式 proxy=（我们自己配的出口）必须仍然生效，不能被默认值覆盖。"""
    captured = {}

    import curl_cffi.requests as _cffi

    class FakeSession:
        def __init__(self, **kw):
            captured.update(kw)

        def close(self):
            pass

    monkeypatch.setattr(_cffi, 'Session', FakeSession)
    s = net.new_client('chrome', proxy='http://127.0.0.1:7897', timeout=5)
    s.close()
    assert captured.get('proxies') == {
        'http': 'http://127.0.0.1:7897',
        'https': 'http://127.0.0.1:7897'}


# ---- merged from tests/test_r1069_hardening_probe.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _bs():
    # bootstrap 内部用相对导入，必须按包导入（与 test_android_bootstrap 同法）
    from core.android import bootstrap as bs
    return bs


GOOD = (
    "enforce=Enforcing\n"
    "cpu=processor\t: 0 BogoMIPS\t: 38.40 \n"
    "zpid=758\n"
    "zyg=3\n"
    "cloak=arm64-v8a.so\n"
    "cloak_off=\n"
)


def _by_name(res):
    return {c[0]: (c[1], c[2]) for c in res["checks"]}


def test_good_device_is_ok():
    m = _bs()
    res = m.parse_probe(GOOD)
    assert res["ok"] is True, res
    assert res["missing"] == []


def test_permissive_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("enforce=Enforcing", "enforce=Permissive"))
    assert res["ok"] is False
    assert any("SELinux" in x for x in res["missing"])


def test_intel_cpuinfo_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("BogoMIPS\t: 38.40", "vendor_id: GenuineIntel"))
    assert res["ok"] is False
    assert any("cpuinfo" in x for x in res["missing"])


def test_zygisk_not_injected_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("zyg=3", "zyg=0"))
    assert res["ok"] is False
    assert any("Zygisk" in x for x in res["missing"])


def test_cloak_disabled_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("cloak_off=\n",
                                     "cloak_off=/data/adb/modules/mumu_cloak/disable\n"))
    assert res["ok"] is False
    assert any("mumu_cloak" in x for x in res["missing"])


def test_cloak_missing_is_flagged():
    m = _bs()
    res = m.parse_probe(GOOD.replace("cloak=arm64-v8a.so\n", "cloak=\n"))
    assert res["ok"] is False
    assert any("mumu_cloak" in x for x in res["missing"])


def test_no_output_is_unknown_not_pass():
    """读不到 ≠ 通过。这是最容易写成假绿的地方。"""
    m = _bs()
    res = m.parse_probe("")
    assert res["ok"] is None
    assert res["checks"] == []


def test_garbage_output_is_unknown():
    m = _bs()
    res = m.parse_probe("error: device offline\n")
    assert res["ok"] is None


def test_missing_items_carry_actionable_next():
    """缺项时必须给出可执行命令，而不是只说"未就位"。"""
    m = _bs()
    res = m.parse_probe(GOOD.replace("enforce=Enforcing", "enforce=Permissive"))
    assert "setup_device.py" in res["next"]
    assert "apply" in res["next"]


def test_crlf_output_parses():
    """adb 输出常带 CRLF，不能被 \\r 干扰。"""
    m = _bs()
    res = m.parse_probe(GOOD.replace("\n", "\r\n"))
    assert res["ok"] is True


def test_probe_hardening_never_raises():
    """dev 抛异常时必须降级为 None，不能把状态查询打挂。"""
    m = _bs()

    class Boom:
        def run_script(self, *a, **k):
            raise RuntimeError("adb died")

    res = m.probe_hardening(Boom())
    assert res["ok"] is None


def test_status_includes_hardening_key(monkeypatch):
    """status() 必须带上 hardening 字段（UI/CLI 靠它显示伪装状态）。"""
    m = _bs()

    class _Mgr:
        def __init__(self, *a, **k):
            pass

        def available(self):
            return True

        def info(self):
            return {"is_android_started": True, "adb_port": 16384,
                    "adb_host_ip": "127.0.0.1"}

    monkeypatch.setattr(m, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(m, "MuMuManager", _Mgr)
    st = m.status({"android": {"enabled": True}})
    assert "hardening" in st
    assert st["state"] == "ready"


# ---- merged from tests/test_r252_sentinel.py ----

class _L:
    def __init__(self):
        self.seen = []

    def warning(self, *a, **k):
        self.seen.append(a)

    def info(self, *a, **k):
        self.seen.append(a)


def _setup(monkeypatch, tmp_path):
    """哨兵状态隔离四件套（照抄 test_field_sentinel_warns_on_dead_field
    并补 _SENT_CNT/_SENT_SUPPLIED——连续命中计数/供给基线不清会让
    跨用例首日判定漂移）。"""
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()


def _run(logger, plat, rows):
    _m._field_sentinel([_NS(platform=plat, extra=json.dumps(rows))], logger)


def _direct_rows(n, with_vals):
    """直飞行群夹具：with_vals=True 带四键真值（健康形态）；
    其余观测键（直飞行群比率族/机场码/航站楼）带值防旁哨噪音，
    让目标四键是行间唯一差异。"""
    rows = []
    for _ in range(n):
        r = {"price": 1000, "cabin": "经济舱", "meal": "无餐食",
             "prate": "97", "plane": "空客321(中)", "planeSize": "中型机",
             "discount": "4.5折", "depTerminal": "T2",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
        if with_vals:
            r.update({"avgDelay": 21, "planeAge": "6.3",
                      "cancelRate": 10, "bridgeRate": 80})
        rows.append(r)
    return rows


def _trans_rows(n):
    """中转行群夹具：结构性无四键（生产真实形态）；全行观测键
    （机场码/航站楼）与中转观测键（svc/tterm/layover）带值防旁哨。"""
    return [{"price": 1000, "transCity": "西安", "layover": 90,
             "depTerminal": "T2", "transferService": "免费改签",
             "transTerminal": "咸阳T3",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for _ in range(n)]


def test_trans_only_round_no_false_alarm(monkeypatch, tmp_path):
    """全中转轮（直飞售罄夜形态）不鸣四键假火：分母=direct_n=0<10
    不观测。旧代码全行分母 n=20≥20 撞分子恒 0 → 四键齐鸣「键名
    失效」假火。bag_direct 零直挂出勤：r316 窗粒度供给基线语义下
    「该窗从未有过直挂」=never-supplied 特征静默（供给基线写入后
    归零才真警——寻源温度计的断链面，恒零面由 dump 调研观察）。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _trans_rows(20))
    msgs = " ".join(str(a) for a in lg.seen)
    for kw in ("avgDelay", "cancelRate", "bridgeRate", "planeAge"):
        assert kw not in msgs, (kw, lg.seen)
    assert sum(1 for a in lg.seen if "行李直挂" in str(a)) == 0, lg.seen


def test_direct_round_dead_keys_still_warn(monkeypatch, tmp_path):
    """直飞行群在场且四键全灭照报：键名失效检测能力不丢
    （旧代码 n=10<20 不报——新门槛 direct_n≥10 与比率观测族对齐）。
    供给基线语义：先健康轮写供给，再断链轮——「曾供给后归零」真警。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _direct_rows(10, with_vals=True))
    assert lg.seen == [], lg.seen          # 供给轮健康零告警
    lg2 = _L()
    _run(lg2, "tongcheng", _direct_rows(10, with_vals=False))
    warned = {a[2] for a in lg2.seen}   # (plat, k, msg) 形态的第 3 段
    assert len(lg2.seen) == 4, lg2.seen
    for kw in ("avgDelay", "cancelRate", "bridgeRate", "planeAge"):
        assert any(kw in m for m in warned), (kw, lg2.seen)


def test_mixed_round_direct_ok_no_alarm(monkeypatch, tmp_path):
    """混合轮（直飞满勤 + 中转在场）不鸣四键假火：中转行群结构性
    恒 0 不再稀释判定，直飞行群健康即哨静默。（bag_direct 夹具
    无直挂行=never-supplied 静默，供给语义同
    test_trans_only_round_no_false_alarm 注。）"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _direct_rows(10, with_vals=True) + _trans_rows(20))
    msgs = " ".join(str(a) for a in lg.seen)
    for kw in ("avgDelay", "cancelRate", "bridgeRate", "planeAge"):
        assert kw not in msgs, (kw, lg.seen)
    assert sum(1 for a in lg.seen if "行李直挂" in str(a)) == 0, lg.seen


def test_below_floor_round_not_observed(monkeypatch, tmp_path):
    """直飞行群 <10 样本不足整轮不观测（行群观测的样本就是行群自身）。"""
    _setup(monkeypatch, tmp_path)
    lg = _L()
    _run(lg, "tongcheng", _direct_rows(9, with_vals=False))
    assert lg.seen == [], lg.seen


def test_digest_pool_isolated_from_prod_db(monkeypatch):
    """合成池与生产 DB 隔离（conftest autouse _isolate_recent_flights
    在位验证）：storage=None 时补位链读默认 data/prices.db 近 6h
    真实行——v15133 tie 组钉曾随生产数据面漂移（夜间 tongcheng
    高价中转行抬锚，合成 1600 tie 组被孤低价守卫双杀）白天绿入夜红。
    根治后池=夹具行：无 _stale_h 补位行混入。"""
    import core.alerter as am
    import datetime as _dt
    _today = _dt.date.today().isoformat()   # 动态日期：补位按 (航线,depart_date) 查近 6h——硬编码日期过午夜后钉变零回归钉
    rows = [dict({"price": 1600, "name": "东航MU5700", "code": "MU5700",
                  "depTime": "10:00", "arrTime": "15:00",
                  "depDate": _today, "arrDate": _today,
                  "transCity": "兰州", "totalDuration": "9时30分",
                  "layoverM": 120}, _platform=p)
            for p in ("fliggy", "ctrip")]

    class _NS:
        pass

    rec = _NS()
    rec.platform, rec.extra, rec.depart_date = "fliggy", json.dumps(
        [rows[0]], ensure_ascii=False), _today
    rec2 = _NS()
    rec2.platform, rec2.extra, rec2.depart_date = "ctrip", json.dumps(
        [rows[1]], ensure_ascii=False), _today
    rec.from_city = rec2.from_city = "URC"
    rec.to_city = rec2.to_city = "SHA"
    rec.price = rec2.price = 1600

    a = am.Alerter(_L(), notifier=None, storage=None, digest=True, user="t")
    route = am.Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                     to_name="上海", dates=[_today],
                     alert_direct=0, alert_transfer=1700,
                     transfer_arrival_max="23:59",
                     transfer_baggage="direct")
    secs = a._build_sections(route, [rec, rec2])
    pool = [f for s in secs for f in (s.get("top_direct") or [])
            + (s.get("top_transfer") or [])]
    assert all(not f.get("_stale_h") for f in pool), pool
    assert all(f.get("price") == 1600 for f in pool), pool


# ---- merged from tests/test_r353_brand_identity.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def _const(name):
    m = re.search(r"const %s=(\{.*?\});\n" % re.escape(name), SRC, re.S)
    assert m, name
    return json.loads(m.group(1))


BRAND = _const("SRX_BRAND_IMG")
AIR = _const("SRX_AIR_IMG")
META = _const("SRX_AIR_META")
_AM = re.search(r"const SRX_BRAND_ALIAS=\{(.*?)\};", SRC, re.S)
ALIAS = dict(re.findall(r"(\w+):'(\w+)'", _AM.group(1) if _AM else ""))


def _brand_uri(p):
    return BRAND.get(p) or BRAND.get(ALIAS.get(p, ""))


def _icon_raw(uri):
    """图标外置化：注册表值是内容寻址 URL（/assets/icons/img_<md5前8>.png），
    像素判据改读 webui_assets/icons/ 下的同名文件，仍校验 PNG 魔数。"""
    assert uri.startswith("/assets/icons/img_"), uri[:40]
    with open(os.path.join(ROOT, "webui_assets", "icons",
                           uri.rsplit("/", 1)[-1]), "rb") as f:
        raw = f.read()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return raw


def _png_ok(uri):
    return len(_icon_raw(uri))


def test_every_channel_is_embedded_official_mark():
    """每个渠道（含两个 App 渠道）都必须有内嵌官方图标。

    只断言 5 家浏览器渠道时，新增的 app_zhixing/app_qunar 会静默没有
    图标（`srxPlatIcon` 取不到就返回空串、行里直接少一块）。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    need = set(BROWSER_CHANNELS) | set(APP_CHANNELS)
    missing = [p for p in need if not _brand_uri(p)]
    assert not missing, "缺图标：%s" % sorted(missing)
    for p in need:
        assert _png_ok(_brand_uri(p)) > 1500, p
    for key, uri in BRAND.items():
        assert _png_ok(uri) > 1500, key
        assert not re.search(r"https?://", uri), key


def test_app_zhixing_icon_has_no_promo_banner():
    """智行 App 图标只保留官方「智行」字标，不能再带「酒店真低价」促销条。

    旧图底部是橙色营销横幅，缩到 16–22px 读成广告/噪点，渠道身份不成立。
    """
    import io
    from PIL import Image
    raw = _icon_raw(BRAND["app_zhixing"])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    assert im.size == (256, 256), im.size
    w, h = im.size
    for y in range(h - 50, h):
        for x in range(w):
            r, g, b = im.getpixel((x, y))
            assert not (r > 170 and g < 160 and b < 130), (
                "智行图标底部仍有促销横幅像素 @%s,%s" % (x, y))
    # 蓝色底：底部应整体偏蓝，不能是白色/黑色横条
    px = [im.getpixel((x, h - 20)) for x in range(0, w, 8)]
    assert sum(1 for r, g, b in px if b > r + 40) >= len(px) * 0.9


def test_airline_official_icons_cover_major_carriers():
    for code in ("MU", "CA", "CZ", "MF", "9C", "HO", "HU", "3U", "ZH", "SC"):
        assert code in AIR and _png_ok(AIR[code]) > 1500
        assert code in META and META[code][0]
    for code, (name, color) in META.items():
        assert re.fullmatch(r"[0-9A-Z]{2}", code), code
        assert name and re.fullmatch(r"#[0-9a-f]{6}", color), code


def test_icon_helpers_distinguish_channel_and_airline_semantics():
    assert "function srxPlatIcon(" in SRC
    assert "function srxAirIcon(" in SRC
    assert "bic bic-ota " in SRC and "bic bic-air " in SRC
    assert re.search(r"\.bic-ota\{[^}]*border-radius", STYLE)
    assert re.search(r"\.bic-air\{[^}]*border-radius:50%", STYLE)
    assert "官方图标" in SRC
    assert "官方航司图标" in SRC


def test_search_mirror_watch_and_config_use_brand_icons():
    assert "srxPlatIcon(f.platKey)" in SRC
    assert "srxAirIcon(f.code)" in SRC
    assert "srxPlatIcon(ch)" in SRC and "srxPlatIcon(c)" in SRC
    assert "srxPlatIcon(p)" in SRC and "srxPlatIcon(x.platKey)" in SRC
    assert "function wsBrandMark(" in SRC
    assert "srxPlatIcon(q.platform)" in SRC
    assert "srxPlatIcon(info.plat)" in SRC
    assert "srxAirIcon(w.code)" in SRC
    assert "srxFillStaticChips" in SRC
    assert "srxPlatIcon(srxPlatKey(f.platKey||f.plat))" in SRC
    # 渠道筛选 chip 的图标必须经 srxPlatKey 解析：本轮之前的写法是
    # `srxPlatIcon(PK[p]||'')`，而 `PK` 是只列 5 家浏览器渠道的写死表，
    # 两个 App 渠道查不到 → chip 没有官方图标。判据守「走单一解析入口」，
    # 不守那张表的字面写法。
    assert "srxPlatIcon(srxPlatKey(p))" in SRC, (
        "渠道筛选 chip 没有走 srxPlatKey（App 渠道会丢官方图标）")
    assert "srxPlatIcon(srxPlatKey(m[0]))" in SRC, (
        "「全线最低」渠道胶囊没有走 srxPlatKey（App 渠道会丢官方图标）")
    assert "srxPlatIcon(p)}${CN[p]||p}" in SRC
    assert "srxPlatIcon(p)}${PLATS[p]}" in SRC
    assert 'id="monWatchCard"' in SRC and 'id="monWatchList"' in SRC
    assert "const airCode=srxAirCode(f.code);" in SRC
    assert "const airOfficial=!cal&&!!airCode;" in SRC
    assert "function srxPlatKey(" in SRC
    assert 'data-plat="${srxPlatKey(f.platKey||f.plat)}"' in SRC
    assert ".ws-fident .mark.has-air" in STYLE
    assert "font-size:max(8px,calc(var(--bic) * .34))" in STYLE
    assert "${srxPlatIcon(p)}<span class=\"lgnm\">" in SRC
    assert "srx-wchip .bic" in STYLE


def test_arrival_superscript_cannot_shift_baseline():
    # +1 已移出到达时刻 <b>，成为独立网格列：不再参与任一文本行盒。
    m = re.search(re.escape("#searchview .srx-times .xday") + r"\{([^}]*)\}", STYLE)
    assert m
    body = m.group(1)
    assert "align-self:start" in body
    assert "vertical-align:3px" not in body
    assert re.search(r"#searchview \.srx-times b\{[^}]*line-height:18px", STYLE)
    assert re.search(r"#searchview \.srx-times\{[^}]*grid-template-columns:auto auto auto auto", STYLE)


def test_watch_tab_refresh_after_state_load():
    # 静默恢复深链时 S 未到，首拍 wsLoad 无用户；状态到达后必须补拉。
    assert "MONTAB==='watch'&&typeof wsLoad==='function')wsLoad(false)" in SRC


# ---- merged from tests/test_r356_icons.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def _const(name):
    m = re.search(r"const %s=(\{.*?\});\n" % re.escape(name), SRC, re.S)
    assert m, name
    return json.loads(m.group(1))


BRAND = _const("SRX_BRAND_IMG")
AIR = _const("SRX_AIR_IMG")
META = _const("SRX_AIR_META")
_AM = re.search(r"const SRX_BRAND_ALIAS=\{(.*?)\};", SRC, re.S)
ALIAS = dict(re.findall(r"(\w+):'(\w+)'", _AM.group(1) if _AM else ""))


def _brand_uri(p):
    return BRAND.get(p) or BRAND.get(ALIAS.get(p, ""))
SPRITE = re.search(r'<svg id="plSprite".*?</svg>', SRC, re.S).group(0)
PLANE_MODEL_SRC = re.search(r"const SRX_PLANE_MODEL=(\{.*?\});\n", SRC, re.S).group(1)
PLANE_CODE_SRC = re.search(r"const SRX_PLANE_CODE=(\{.*?\});\n", SRC, re.S).group(1)
PLANE_MODEL_KEYS = re.findall(r"\b([a-z][a-z0-9]*)\s*:\{maker:", PLANE_MODEL_SRC)
PLANE_CODES = dict(re.findall(r"'([A-Z0-9]+)'\s*:\s*'([a-z0-9]+)'", PLANE_CODE_SRC))
SPRITE_IDS = set(re.findall(r'<symbol id="pl-([a-z0-9]+)"', SPRITE))


def _png(uri):
    # 图标外置化：值是 /assets/icons/ URL，PNG 字节在 webui_assets/icons/。
    assert uri.startswith("/assets/icons/img_"), uri[:32]
    with open(os.path.join(ROOT, "webui_assets", "icons",
                           uri.rsplit("/", 1)[-1]), "rb") as f:
        raw = f.read()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(raw)).convert("RGBA"), raw


def _nonwhite_bbox(im):
    r, g, b = im.convert("RGB").split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    box = darkest.point(lambda v: 0 if v > 245 else 255, mode="1").getbbox()
    assert box, "blank icon"
    x0, y0, x1, y1 = box
    return x0, y0, x1 - 1, y1 - 1


DATA_CODES = set(
    "MU CZ FM CA MF HO 9C 3U ZH HU SC GS SQ Y8 OZ JL UQ QR HX AQ KE NX G5 NH MH TG "
    "PN VN CX VJ D7 GA AY EY BK UA LH PR TK GF PG AA OD 9H AC KY DL LX RY JD IJ BR "
    "EK KL FU NZ EU ET KN NS BA GK AF DZ GJ QW 9G CI VZ".split()
)


def test_every_ota_mark_is_full_bleed_complete_official_png():
    """**每个**渠道（含两个 App 渠道）都要是满版官方标记。

    判据对全部渠道一视同仁：256×256、四角非白、PNG 内嵌。
    智行用 APK 里的 launcher 图标（`r/y/ark_icon.png`，官方 288×288，
    圆角外透明 → 填品牌蓝后满版）；去哪儿 App 与浏览器 qunar 同一品牌
    标记，直接复用。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    need = set(BROWSER_CHANNELS) | set(APP_CHANNELS)
    missing = [p for p in need if not _brand_uri(p)]
    assert not missing, "缺图标：%s" % sorted(missing)
    for p in need:
        im, _ = _png(_brand_uri(p))
        assert im.size == (256, 256), (p, im.size)
        for xy in ((0, 0), (255, 0), (0, 255), (255, 255)):
            r, g, b, _ = im.getpixel(xy)
            assert max(r, g, b) - min(r, g, b) > 8 or max(r, g, b) < 240, (p, xy)
    for key, uri in BRAND.items():
        im, _ = _png(uri)
        assert im.size == (256, 256), (key, im.size)
        # Full-bleed tiles: the official field reaches every corner, so no white crop ring.
        for xy in ((0, 0), (255, 0), (0, 255), (255, 255)):
            r, g, b, _ = im.getpixel(xy)
            assert max(r, g, b) - min(r, g, b) > 8 or max(r, g, b) < 240, (key, xy)
        # Ctrip's dolphin tail must not touch the tile edge (the old crop was clipped).
        if key == "ctrip":
            r, g, b = im.convert("RGB").split()
            darkest = ImageChops.darker(ImageChops.darker(r, g), b)
            box = darkest.point(lambda v: 255 if v > 235 else 0, mode="1").getbbox()
            assert box
            x0, y0, x1, y1 = box
            assert min(x0, y0, 256 - x1, 256 - y1) >= 8


def test_airline_catalog_matches_meta_and_covers_all_real_codes():
    assert len(AIR) == 87 and len(META) == 89
    # W1 (World Ticket) and LT (Longjiang) have no verified official icon:
    # they fall back to an honest IATA tile instead of a fabricated mark.
    assert set(META) - set(AIR) == {"W1", "LT"}
    assert set(AIR) <= set(META)
    assert DATA_CODES <= set(AIR)
    for code in ("JD", "UQ", "RY", "FU", "9H", "9D", "GY"):
        assert code in AIR and code in META
    seen = {}
    for code, uri in AIR.items():
        im, raw = _png(uri)
        assert len(raw) > 1000, code
        assert im.size == (192, 192), (code, im.size)
        digest = hashlib.sha1(raw).hexdigest()
        assert digest not in seen, (code, seen.get(digest))
        seen[digest] = code
        name, color = META[code]
        assert name and re.fullmatch(r"#[0-9a-f]{6}", color), code
        _nonwhite_bbox(im)
    # 9H was a clipped source; the replacement must have breathing room on all sides.
    im, _ = _png(AIR["9H"])
    x0, y0, x1, y1 = _nonwhite_bbox(im)
    assert min(x0, y0, 191 - x1, 191 - y1) >= 5


def test_airline_name_resolver_precedes_false_embedded_codes():
    for name in ("东航", "国航", "南航", "海航", "春秋", "吉祥", "山航", "上航", "天津", "阿联酋", "国泰", "英航", "亚航X"):
        assert "'%s':'" % name in SRC
    assert "'亚航X':'D7'" in SRC
    fn = re.search(r"function srxAirCode\(v\)\{(.*?)\n\}", SRC, re.S).group(1)
    assert fn.index("SRX_AIR_NAME") < fn.index("const emb=")
    assert 'class="bic bic-air' in SRC and "style=\"--ac:'+m.color+'\"" in SRC


def test_real_aircraft_codes_map_to_model_families():
    expected = {
        "738": "b737", "73H": "b737", "7M8": "b737max", "32Q": "a321",
        "359": "a350", "77W": "b777", "388": "a380", "919": "c919",
        "C909": "arj21", "290": "ejet", "333": "a330", "789": "b787",
    }
    for code, key in expected.items():
        assert PLANE_CODES.get(code) == key, (code, PLANE_CODES.get(code))
    assert set(PLANE_CODES.values()) <= set(PLANE_MODEL_KEYS)
    assert "unknown" in PLANE_MODEL_KEYS
    # Every model family has a sprite symbol, including the honest unknown fallback.
    assert set(PLANE_MODEL_KEYS) == SPRITE_IDS
    assert len(PLANE_MODEL_KEYS) == 22
    assert PLANE_CODES.get("32S") == "a320"
    assert PLANE_CODES.get("DH8D") == "turboprop"
    assert "SRX_PLANE_RANGE" in SRC and "range=true" in SRC
    for key in ("a320", "a321", "a330", "a350", "a380", "b737", "b737max",
                "b747", "b767", "b777", "b787", "c919", "arj21", "ejet", "atr",
                "turboprop", "unknown"):
        assert "pl-" + key in SPRITE


def test_aircraft_icons_are_textured_and_honest():
    assert "SRX_PLANE_BODY" not in SRC
    assert "制造商识别色" in SRC and "体量口径" in SRC and "不冒充" in SRC
    assert "function srxPlaneIcon(" in SRC and '<use href="#pl-\'+m.key+\'"/>' in SRC
    for needle in ("--pl-w1:", "--pl-w2:", "--pl-w3:", "drop-shadow(0 0 .55px"):
        assert needle in STYLE
    assert ".bic-plane svg{width:100%;height:100%" in STYLE
    # unknown must render a symbol rather than a blank <use>
    assert 'id="pl-unknown"' in SPRITE and 'stroke-dasharray="1.1 1"' in SPRITE


def test_icons_wired_into_all_identity_surfaces():
    for needle in (
        "srxAirIcon(a[0])", "srxPlaneIcon(a)",
        "srxAirIcon(f.code)", "srxPlaneIcon(f.plane||f.planeSize)",
        "const planeMark=!cal&&(f.plane||f.planeSize)?srxPlaneIcon(f.plane||f.planeSize):''",
        "planeMark", "const airCode=srxAirCode(f.code);",
        "srxPlatIcon(srxPlatKey(x.plat)||x.plat)",
        "(f.plane||f.planeSize)?'<span class=\"nw nw-keep\"",
    ):
        assert needle in SRC, needle
    # Filters, detail grid, list rows and matrix all share the same helpers.
    assert SRC.count("srxPlaneIcon(") >= 8
    assert SRC.count("srxAirIcon(") >= 12


def test_control_icons_are_svg_not_emoji():
    label = re.search(r"function _fltCatLabel\(k\)\{(.*?)\}\n", SRC, re.S).group(1)
    for emoji in ("✈", "🔁", "🔥", "🧳"):
        assert emoji not in label
    assert "#i-sliders" in SRC and "#i-chart" in SRC and "#i-scale" in SRC
    assert "#i-flame" in SRC and "#i-bag" in SRC
    page = SRC[SRC.index('PAGE = r"""'):SRC.index('NOTIFY_PAGE = r"""')]
    assert "🚨" not in page and "✈️" not in page
    assert ".fire .ic{" in STYLE


def test_brand_css_keeps_semantic_shapes_and_texture():
    assert re.search(r"\.bic-ota\{[^}]*border-radius", STYLE)
    assert re.search(r"\.bic-air\{[^}]*border-radius:50%", STYLE)
    assert "color-mix(in srgb,var(--ac" in STYLE
    assert "radial-gradient(circle at 32% 22%" in STYLE
    assert ".bic-air>img{object-fit:contain;padding:7%}" in STYLE


# ---- merged from tests/test_r395_path_rename_recovery.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _db():
    d = tempfile.mkdtemp(prefix="tm_r395_")
    return PriceStorage(os.path.join(d, "prices.db"))


def _rows(store):
    return store.failure_recurrence(hours=24, min_count=1)


def test_family_is_shared_not_duplicated():
    """族表只有一份定义（pacing/storage 共用），避免两处漂移。"""
    assert CAL_PATH_FAMILY == ("日历", "窗历")
    import core.pacing as pacing
    src = open(pacing.__file__, encoding="utf-8").read()
    # 不得再各写一份字面量族表
    assert '_CAL_FAMILY = ("日历", "窗历")' not in src
    assert "_CAL_FAMILY = CAL_PATH_FAMILY" in src


def test_rename_counts_as_recovered():
    """旧「日历」失败 → 新「窗历」成功 = 已恢复（r384 真实形态）。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "窗历", "calendar", rows=1, note="同程低价日历 90 天窗口")
    rows = [r for r in _rows(s) if r["path"] == "日历"]
    assert rows, "复发组应仍在（毛病确实反复过）"
    assert rows[0]["status"] == "soft_reject"
    assert rows[0]["recovered"] is True, rows[0]


def test_other_paths_still_recovered_within_own_name():
    """族外不跨通路担保：H5 成功不能顶日历的账。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "H5", "ok", rows=20, note="www.ly.com H5 列表")
    rows = [r for r in _rows(s) if r["path"] == "日历"]
    assert rows[0]["recovered"] is False, rows[0]


def test_still_failing_after_rename_is_not_recovered():
    """窗历也失败时不得谎称已恢复（别把真故障洗白）。"""
    s = _db()
    for _ in range(2):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "窗历", "calendar", rows=1, note="同程低价日历 90 天窗口")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "窗历", "soft_reject", note="窗历门拒 code=444")
    rows = [r for r in _rows(s) if r["path"] == "窗历"]
    assert rows, "窗历自身失败也要进复发账"
    assert rows[0]["recovered"] is False, rows[0]


def test_route_scoped_not_channel_wide():
    """别的航线成功不能顶本航线（原有语义不能因族匹配而放宽）。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "LHR", "2026-11-16",
                      "窗历", "calendar", rows=1, note="同程低价日历 90 天窗口")
    rows = [r for r in _rows(s) if r["to_city"] == "BKK"]
    assert rows[0]["recovered"] is False, rows[0]


def test_relabel_groups_merge_after_classification():
    """归类改写后同类要合并，不能并列出两条一模一样的行。

    真实形态（qunar API HAK→SHA）：SQL 先按 path_status 分成 login(4) 与
    empty(3) 两组，改写把 login 也判成 empty，界面上就成了
    「empty×4」和「empty×3」两条同名行——读者会以为是两件事。
    """
    s = _db()
    for _ in range(4):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "login",
                          note="原站返回无符合条件的航班（可能受指纹 SDK/风控环境影响）")
    for _ in range(3):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "empty",
                          note="原站返回符合条件的航班占位")
    rows = [r for r in _rows(s)
            if r["platform"] == "qunar" and r["path"] == "API"]
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "empty"
    assert rows[0]["count"] == 7, rows[0]


def test_relabel_merge_keeps_distinct_statuses_apart():
    """合并不许把不同状态揉成一团（soft_reject 与 empty 是两件事）。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "login",
                          note="国际列表 1999/8 未登录硬拒")
    for _ in range(2):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "empty",
                          note="原站无符合条件的航班")
    rows = [r for r in _rows(s)
            if r["platform"] == "qunar" and r["path"] == "API"]
    assert sorted(r["status"] for r in rows) == ["empty", "soft_reject"], rows


# ---- merged from tests/test_r403_empty_needs_evidence.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")

# 这些措辞描述的是"我们没拿到/没解析出"，不是"站点说没票"
PSEUDO_EMPTY_MARKERS = ("请求无响应", "未解析到", "没拿到", "无证据")
# 正则版：允许短语中间夹词（"H5 无 listingsearch 响应" 曾漏网，r405）
PSEUDO_EMPTY_PATTERNS = (
    re.compile(r"无.{0,24}响应"),
    re.compile(r"未(解析|拿到|获取)"),
    re.compile(r"没有(拿到|收到|获取)"),
)


def _sources():
    for fn in sorted(os.listdir(CRAWLERS)):
        if fn.endswith(".py"):
            path = os.path.join(CRAWLERS, fn)
            yield fn, open(path, encoding="utf-8").read()


def test_no_pseudo_empty_wording():
    """不得把"没拿到/没解析出"的文案写成 empty 状态。

    只看**代码行**（去掉注释），否则解释这条规则本身的注释会被误报。
    同时用**正则**匹配短语中间夹词的形态——「H5 无 listingsearch 响应」
    曾因字面标记只覆盖「请求无响应」而漏网（r405）。
    """
    bad = []
    for fn, src in _sources():
        lines = src.splitlines()
        for line_no, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if not re.search(r'["\']empty["\']', code):
                continue
            ctx = "\n".join(
                ln.split("#", 1)[0] for ln in lines[max(0, line_no - 3):line_no + 2])
            for mk in PSEUDO_EMPTY_MARKERS:
                if mk in ctx:
                    bad.append((fn, line_no, mk, code.strip()[:60]))
            for pat in PSEUDO_EMPTY_PATTERNS:
                m = pat.search(ctx)
                if m:
                    bad.append((fn, line_no, m.group(0), code.strip()[:60]))
    assert not bad, bad


def test_every_crawler_has_error_escape():
    """每个采集渠道都必须能记 error——否则失败时只能二选一（login/empty）。

    判据要看**能力**，不是「该文件里出现字面量」：继承 `AppBaseCrawler`
    的渠道（app_zhixing 等）统一走 `safe_fetch()`，异常在那里就被记成
    `app-error`，子类自己不必再写一遍。曾经只查文件字面量，于是
    `app_zhixing.py` 被判缺牌——而它其实有（r609 实测）。
    """
    try:
        with open(os.path.join(CRAWLERS, "app_base.py"),
                  encoding="utf-8", errors="replace") as f:
            base = f.read()
    except OSError:
        base = ""
    # 判据必须落在 `safe_fetch` 的**函数体**里：整个文件查关键字会假绿——
    # `PATH_STATUS` 元组、`path_note` 的默认兜底都含 "error"，
    # 实测删掉 safe_fetch 里那两行之后断言照样通过。
    base_escapes = False
    _i = base.find("def safe_fetch(")
    if _i >= 0:
        _j = base.find("\n    def ", _i + 10)
        _body = base[_i:_j if _j > 0 else _i + 1200]
        base_escapes = ('"error"' in _body and "path_note(" in _body
                        and "except Exception" in _body)
    missing = []
    for fn, src in _sources():
        if fn in ("__init__.py", "challenge.py"):
            continue
        if "path_note(" not in src:
            continue
        own = ('"error"' in src or "'error'" in src)
        # 基类在 `crawlers/app_base.py` 里叫 `AppCrawler`（早前注释里写的是
        # `AppBaseCrawler`，那个名字类上并不存在）。只认旧名会把继承这条
        # 逃逸能力的渠道（app_qunar 等）判成缺牌——它们 `safe_fetch()` 里
        # 的 error 分支是真生效的（r666 实况）。
        inherits_app = (("AppCrawler" in src or "AppBaseCrawler" in src)
                        and base_escapes)
        if not (own or inherits_app):
            missing.append(fn)
    assert not missing, missing


def test_empty_writes_are_not_bare_else():
    """`empty` 不得出现在"其他全失败"的裸 else 上。

    允许形态：`("empty" if <明确条件> else ...)` 或显式
    `path_note(..., "empty", ...)` 且上下文有 no-result 依据。
    """
    bad = []
    for fn, src in _sources():
        for line_no, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if not re.match(r'^else\s*["\']empty["\']', s):
                continue
            bad.append((fn, line_no, s))
    assert not bad, bad


def test_pacing_classifies_all_six_buckets():
    """path_stats 的六个桶必须都存在（r397 的登录/错误分离不能回退）。"""
    from core.storage import PriceStorage
    import tempfile
    st = PriceStorage(os.path.join(tempfile.mkdtemp(prefix="r403_"), "p.db"))
    st.save_fetch_path("x", "SHA", "BKK", "2026-11-16", "H5", "login")
    n = st.path_stats(hours=24)["x"]
    for k in ("ok", "empty", "login", "blocked", "soft", "unsupported",
              "error"):
        assert k in n, (k, sorted(n))


# ---- merged from tests/test_r406_retired_path_live_rate.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _store():
    return PriceStorage(os.path.join(tempfile.mkdtemp(prefix="tm_r406_"), "p.db"))


def _feed(st, plat, entries):
    """entries: [(path, status, attempt_id, date[, offset_s])]

    offset_s 用于造"时间先后"：判据靠 last_at 比较，同一秒内分不出顺序
    （真实库里新旧通路相隔数十分钟，测试必须还原这个形状）。
    """
    from datetime import datetime, timedelta
    # 全部落在"1 小时前"起步的窗口内（留足余量，避免跨午夜被 24h 过滤）
    base = datetime.now() - timedelta(hours=1)
    for e in entries:
        path, status, aid, d = e[0], e[1], e[2], e[3]
        off = e[4] if len(e) > 4 else 0
        ts = (base + timedelta(seconds=off)).strftime("%Y-%m-%d %H:%M:%S")
        st.save_fetch_path(plat, "SHA", "BKK", d, path, status,
                           rows=5 if status in ("ok", "calendar") else 0,
                           attempt_id=aid)
        with st._conn() as c:
            c.execute("UPDATE fetch_paths SET fetched_at=? WHERE attempt_id=?",
                      (ts, aid))


def _node(st, plat, scope=None):
    n = st.path_stats(hours=24)[plat]
    return n if scope is None else n["scopes"][scope]


def test_retired_path_excluded_from_live_rate():
    """旧「日历」全失败且之后无人再试 → 退役，不计入在用口径。"""
    st = _store()
    # 旧「日历」：3 次尝试全失败（早期）
    _feed(st, "tc", [("日历", "login", "a1", "2026-11-16", 0),
                     ("日历", "login", "a2", "2026-11-16", 10),
                     ("日历", "login", "a3", "2026-11-16", 20)])
    # 新「窗历」：之后每次都成功
    _feed(st, "tc", [("窗历", "calendar", "b1", "2026-11-16", 600),
                     ("窗历", "calendar", "b2", "2026-11-16", 900)])
    n = _node(st, "tc")
    assert n["retired_paths"] == ["日历"], n["retired_paths"]
    assert n["query_rate"] == round(2 / 5, 4), n["query_rate"]
    assert n["query_rate_live"] == 1.0, n["query_rate_live"]
    assert n["query_attempts_live"] == 2, n["query_attempts_live"]


def test_live_path_with_success_is_never_retired():
    """还在出数的路径永不退役——哪怕另一条路更晚尝试过。

    回归：第一版判据只看"别人更晚"，把携程 PC（129 次成功）判成退役。
    """
    st = _store()
    _feed(st, "ctrip", [("PC", "ok", "p1", "2026-11-16", 0),
                        ("PC", "ok", "p2", "2026-11-16", 10)])
    _feed(st, "ctrip", [("H5", "ok", "h1", "2026-11-16", 600),
                        ("H5", "ok", "h2", "2026-11-16", 700),
                        ("H5", "ok", "h3", "2026-11-16", 900)])
    n = _node(st, "ctrip")
    assert n["retired_paths"] == [], n["retired_paths"]
    assert n["query_rate_live"] == n["query_rate"]


def test_dead_path_without_replacement_is_not_retired():
    """失败路径若没有"更晚且成功"的替代者，不进退役名单（可能只是被限流）。"""
    st = _store()
    _feed(st, "q", [("H5", "login", "a1", "2026-11-16", 0),
                    ("H5", "login", "a2", "2026-11-16", 10)])
    n = _node(st, "q")
    assert n["retired_paths"] == [], n["retired_paths"]
    assert n["query_rate_live"] == n["query_rate"]


def test_mixed_query_counted_once():
    """同一次查询走了多条路径：只要有一条在用，就仍算一次在用查询。"""
    st = _store()
    # 同一次查询：旧日历失败 + 窗历成功（同一 attempt_id）
    # 同一次查询（同一 attempt_id）走了两条路：旧日历失败 + 窗历成功
    _feed(st, "tc", [("日历", "login", "m1", "2026-11-16", 0),
                     ("窗历", "calendar", "m1", "2026-11-16", 0)])
    # 另一次查询只走旧路径，且发生在更晚的时刻——它自己就是"最后尝试者"，
    # 因此旧路径无法被判成"被取代"（有意的保守：宁可少判退役，也不要把
    # 还在尝试的路说成废弃）。这里只验证"混合查询按一次计"。
    _feed(st, "tc", [("窗历", "calendar", "m2", "2026-11-16", 600)])
    n = _node(st, "tc")
    assert n["retired_paths"] == ["日历"], n["retired_paths"]
    # m1（含旧+新）算一次在用；m2 算一次 → 共 2 次，且都成功
    assert n["query_attempts_live"] == 2, n["query_attempts_live"]
    assert n["query_rate_live"] == 1.0
    # 原口径：m1（旧失败+新成功）与 m2（成功）两次查询，都判成功
    assert n["query_attempts"] == 2, n["query_attempts"]
    assert n["query_rate"] == 1.0, n["query_rate"]


def test_scopes_have_their_own_retired_sets():
    """国际退役不影响国内口径（同程国内 H5 一直正常）。"""
    st = _store()
    _feed(st, "tc", [("日历", "login", "d1", "2026-11-16", 0),
                     ("窗历", "calendar", "d2", "2026-11-16", 600)])
    # 国内：H5 正常
    st.save_fetch_path("tc", "SHA", "URC", "2026-11-16", "H5", "ok",
                       rows=9, attempt_id="dom1")
    n = _node(st, "tc")
    assert n["scopes"]["intl"]["retired_paths"] == ["日历"], n["scopes"]["intl"]
    assert n["scopes"]["dom"]["retired_paths"] == [], n["scopes"]["dom"]


# ── advise 必须采用在用口径，否则修了统计也传不到用户眼前 ──────────────

def test_advise_uses_live_rate():
    """退役路径拉低原口径时，advise 必须报在用口径的数字。

    真实形态：同程原口径 63.5%、在用口径 100%。若 advise 仍读原口径，
    用户看到的还是"63.5%、需要处理"——修了统计等于没修。
    """
    from core.pacing import advise
    st = _store()
    # 与真实形态一致：国内 H5 出明细 + 国际窗历出日历价
    _feed(st, "tc", [("日历", "login", "a1", "2026-11-16", 0),
                     ("日历", "login", "a2", "2026-11-16", 10)])
    _feed(st, "tc", [("窗历", "calendar", "b1", "2026-11-16", 600)])
    st.save_fetch_path("tc", "SHA", "URC", "2026-11-16", "H5", "ok",
                       rows=9, attempt_id="dom1")
    n = st.path_stats(hours=24)["tc"]
    assert n["query_rate"] < 1.0, "前置：原口径应被旧路径拖低"
    assert n["query_rate_live"] == 1.0
    a = advise("tc", {}, {}, node=n)
    assert "100%" in a["hint"], a["hint"]
    assert a["state"] == "ok", a


def test_advise_falls_back_when_no_retired():
    """没有退役路径时行为不变（不引入新分支差异）。"""
    from core.pacing import advise
    st = _store()
    _feed(st, "q", [("H5", "ok", "x1", "2026-11-16", 0),
                    ("H5", "ok", "x2", "2026-11-16", 10)])
    n = st.path_stats(hours=24)["q"]
    assert n["retired_paths"] == []
    assert n["query_rate_live"] == n["query_rate"]
    a = advise("q", {}, {}, node=n)
    assert a["state"] == "ok"


# ---- merged from tests/test_r605_config_clamp_is_visible.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_clamp_helper_exists_and_shows_reason():
    w = _w()
    assert "function glbClamp(" in w, "缺少夹取反馈函数"
    i = w.index("function glbClamp(")
    seg = w[i:i + 900]
    assert "box.textContent=reason" in seg, "没有把原因写进提示位"
    # 样式表 `.glcell .verr{display:none}` 会压过空串：必须显式 block，
    # 否则「回写发生了、解释永远看不见」（实测 display 仍是 none）
    assert "box.style.display='block'" in seg, "提示位没有真正显示"
    assert "el.value=txt" in seg, "没有把输入框回写成真实生效值"


def test_three_constraints_call_the_helper():
    w = _w()
    for cid, keyword in (("glbHslow", "降频线不能高于合格线"),
                         ("glbHslf", "重降频倍数不能低于轻降频倍数"),
                         ("glbBcs", "熔断封顶")):
        i = w.index("'%s'" % cid)
        seg = w[i:i + 400]
        assert "glbClamp(this" in seg, "%s 没有调用夹取反馈" % cid
        assert keyword in seg, "%s 的提示没说明被夹原因" % cid


def test_clamp_rules_match_backend():
    """前端夹取规则必须与后端 parse 的上下界一致，否则两边会打架。"""
    import sys
    sys.path.insert(0, ROOT)
    from core.pacing import parse_pacing
    got = parse_pacing({"crawler": {"health_ok_ratio": 0.7,
                                    "health_slow_ratio": 0.9,
                                    "health_slow_factor": 1.5,
                                    "health_slowest_factor": 1.0}})
    assert got["health_slow_ratio"] <= got["health_ok_ratio"], got
    assert got["health_slowest_factor"] >= got["health_slow_factor"], got




# ---- merged from tests/test_r606_every_number_is_validated.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_decimal_fields_parse_as_float():
    w = _w()
    i = w.index("function glbCheck(el,returnMsg)")
    seg = w[i:i + 500]
    assert "r.dec?parseFloat(v):parseInt(v)" in seg, (
        "比率/倍数类用 parseInt 会把 0.05 读成 0 → 永远判越界")


def test_dynamic_ids_resolved_by_prefix():
    w = _w()
    assert "GLB_RANGES_DYN" in w, "没有动态前缀规则表"
    assert "function glbRangeOf(" in w, "没有统一的范围解析入口"
    i = w.index("const GLB_RANGES_DYN=[")
    seg = w[i:i + 400]
    assert "glbCad_" in seg, "渠道节奏（动态 id）没有覆盖"


def test_save_path_also_checks_dynamic_ids():
    """输入侧标红、保存侧放行 = 两套结论；保存也要用同一解析器。"""
    w = _w()
    i = w.index("async function saveCfg()")
    seg = w[i:i + 2600]
    assert "glbRangeOf(el.id)" in seg, "保存侧没有覆盖动态 id 控件"



def test_table_bounds_match_backend_clamps():
    """表里的 min/max 必须与后端 `parse_pacing` 的钳制一致。

    实测踩过：`per_minute` 后端下界是 **0**（0 = 不限），我凭 onchange 里
    的 `Math.max(0,…)` 手抄时写成了 1 —— 于是默认值 0 被判越界，
    **保存直接被拦**（`test_save_demo_readonly_gate` 与特价保存两条同时红）。
    边界不是文案，抄错一次就是「默认配置存不下去」。
    """
    import sys
    sys.path.insert(0, ROOT)
    from core.pacing import parse_pacing
    got = parse_pacing({"crawler": {
        "rate": {"per_minute": -5, "min_gap_s": -1},
        "max_concurrency": -1,
        "stagger_seconds": -1,
        "fast_ttl_min": 1,
        "slow_ttl_min": 1,
        "near_ratio": -1,
        "near_days": -1,
    }})
    # 负值一律夹回下界（不是拒绝），说明后端认的下界就是这些
    assert got["per_minute"] == 0, got["per_minute"]
    assert got["min_gap_s"] == 0, got["min_gap_s"]
    assert got["max_concurrency"] >= 0
    assert got["stagger_seconds"] == 0, got["stagger_seconds"]
    # 这几项后端对非法值是「回落默认」而不是「夹到边界」——判据是
    # 「非法输入不得原样通过」，不是「等于某个具体边界」。
    assert got["fast_ttl_min"] >= 5, got["fast_ttl_min"]
    assert got["slow_ttl_min"] >= 5, got["slow_ttl_min"]
    assert got["near_ratio"] >= 0, got["near_ratio"]
    assert got["near_days"] >= 0, got["near_days"]


def test_declared_zero_is_valid_where_backend_allows_zero():
    """凡是后端允许 0 的项，前端校验表下界也必须是 0（否则默认值存不下去）。"""
    w = _w()
    for cid in ("glbRpm", "glbGap", "glbSessMax", "glbMaxConc", "glbNearD",
                "glbJt", "glbStg"):
        i = w.index("{id:'%s'" % cid)
        seg = w[i:i + 90]
        assert "min:0" in seg, "%s 的下界不是 0（后端允许 0=不限）：%s" % (cid, seg)






# ---- merged from tests/test_r822_static_demo_surfaces.py ----

pytest.importorskip("playwright",
                    reason="静态站门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "docs", "site", "index.html")

def _baked():
    with open(SITE, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"window\.__BAKED__=(\{.*?\});\n", src, re.S)
    assert m, "找不到 window.__BAKED__"
    return json.loads(m.group(1))




def test_static_bake_contains_matrix_health_and_links():
    baked = _baked()
    plats = {c["plat"] for c in baked["dims"]["channels"]}
    assert plats == set(BROWSER_CHANNELS) | set(APP_CHANNELS), plats

    h = baked["health"]
    diag = {c.get("plat") for c in (h.get("diag") or [])}
    assert diag == plats, diag
    assert h.get("demo") is True
    assert all(str(c.get("label") or "").startswith("演示")
               for c in h.get("diag") or []), h.get("diag")
    # 公开站不能把本机真实登录态烘进 HTML
    assert not any(c.get("slots") for c in h.get("diag") or []), (
        "静态站烘焙了真实登录槽位")
    assert h.get("paths"), "静态站健康载荷没有分通路账"

    links = baked.get("channelLinks") or {}
    assert links.get("ok") is True
    assert {c["plat"] for c in links.get("channels") or []} >= set(
        APP_CHANNELS)
    assert links.get("specials"), "静态站没有官方特价频道入口"

    assert baked.get("pulse", {}).get("rounds"), "静态站没有运行脉冲"
    paths = baked.get("paths") or {}
    assert paths.get("demo") is True, paths
    assert set(paths.get("platforms") or {}) >= set(APP_CHANNELS), paths


# ---- merged from tests/test_r719_narrow_channel_surfaces.py ----

pytest.importorskip("playwright",
                    reason="窄档普查依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None

APPS = tuple(plat_cn(p) for p in APP_CHANNELS)
BROWSERS = tuple(plat_cn(p) for p in BROWSER_CHANNELS)
ALL_CN = BROWSERS + APPS


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p
















# ---- merged from tests/test_r805ax_doc_matrix_matches_code.py ----
# W2b 段3：HANDOFF_CAPABILITY_MATRIX.md / HANDOFF_FULL_SESSION.md 已删（W1），
# 引用它们的 4 个用例与矩阵比对辅助随之删除；APP_CHANNELS.md 保留，
# 其 2 个用例留驻。

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _doc(name):
    return io.open(os.path.join(ROOT, "docs", name), encoding="utf-8").read()


def _gaps_diffs(got):
    want = {p: app_alignment_gaps(p) for p in APP_CHANNELS}
    return {p: (got.get(p), want[p]) for p in want if got.get(p) != want[p]}


def _parse_app_gap_table(text):
    """APP_CHANNELS.md 的「尚未对齐」两列表 → {plat: (dim, …)}。"""
    cn2id = {v: k for k, v in Alerter.PLATFORM_CN_EXTRA.items()}
    out = {}
    for label, cell in re.findall(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|",
                                  text, re.M):
        if label not in cn2id:
            continue
        out[cn2id[label]] = () if cell in ("—", "-", "") else tuple(
            re.findall(r"`([a-z_]+)`", cell))
    return out


def test_app_channels_gap_table_matches_code():
    """人读的「尚未对齐」表也得跟 `app_alignment_gaps` 一致。"""
    bad = _gaps_diffs(_parse_app_gap_table(_doc("APP_CHANNELS.md")))
    assert not bad, (
        "APP_CHANNELS.md 的 App 缺口表过期（渠道: (文档, 代码)）：%r" % (bad,))


def test_app_channels_summary_matches_connected_gaps():
    """摘要句与缺口表同源：表说已对齐，正文不能再写「还差」。

    2026-11-03 实测漂移：`APP_CHANNELS.md` 顶部还写「去哪儿 App 还差
    calendar/low_fare」，而同文件缺口表已是 `—`、矩阵两者均 y。
    """
    text = _doc("APP_CHANNELS.md")
    checks = (("app_qunar", "去哪儿 App", ("calendar", "low_fare")),)
    for plat, label, dims in checks:
        missing = set(app_alignment_gaps(plat))
        for dim in dims:
            if dim in missing:
                continue
            assert ("还差 `%s`" % dim) not in text, (
                "%s 的 %s 已接通（缺口表为 —），顶部摘要仍在说「还差」"
                % (label, dim))


# ---- merged from tests/test_r805z_matrix_three_way.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ALL_PLATS = tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)


def test_every_channel_declares_every_dimension():
    for p in ALL_PLATS:
        row = CHANNEL_DIMENSIONS.get(p)
        assert row is not None, "%s 没有任何维度声明" % p
        missing = [d for d in DIMENSIONS if d not in row]
        assert not missing, "%s 缺这些维度：%s" % (p, missing)
        for d in DIMENSIONS:
            assert row[d] in ("y", "n", ""), (p, d, row[d])


def test_calendar_y_requires_a_real_calendar_path():
    """声明 calendar=y 的渠道，源码里必须真有日历通路。

    判据用**通路特有**的标记，不是随便一个 `calendar` 字样：
      * ctrip   —— `_fetch_intl_calendar` / calendar 端点
      * fliggy  —— `cheapestCalendar`
      * tongcheng —— `ts/calendar` 或 窗历
      * qunar   —— 内嵌低价日历 / lowFlight
    App 渠道走真机视图树，另有 `test_app_calendar_is_backed_by_a_real_path`
    专门守（**r700/r701 是往返门禁，不覆盖 calendar**——这句此前写错，
    导致 app_qunar 的 calendar=y 一直没人兜）。
    """
    marks = {
        "ctrip": ("calendar", "_fetch_intl_calendar"),
        "fliggy": ("cheapestCalendar",),
        "tongcheng": ("ts/calendar", "calendar_lowest", "窗历"),
        "qunar": ("lowFlight", "calendar"),
        "tuniu": ("fetch_tuniu_calendar", 'path_note("日历"'),
    }
    for p, needles in marks.items():
        if CHANNEL_DIMENSIONS[p].get("calendar") != "y":
            continue
        src = io.open(os.path.join(ROOT, "crawlers", p + ".py"),
                      encoding="utf-8").read()
        assert any(n in src for n in needles), (
            "%s 声明 calendar=y，但源码里找不到任何日历通路痕迹 %s"
            % (p, needles))


def test_app_calendar_is_backed_by_a_real_path():
    """App 渠道的 `calendar` 也必须由**真实日历通路**支撑。

    这条此前缺失：r805z 的日历判据只覆盖浏览器四家，注释还写着
    「App 由 r700/r701 覆盖」——**那两条是往返门禁，不覆盖 calendar**。
    于是 `app_qunar` 长期记着 calendar=y：它的 App 确实有日历页，但采集
    只把日历当「选日」用、随后进列表取明细，源码里 0 处
    `path_note("日历", ...)`，账本全历史也只有 `航班明细` 一种 entry_path
    ——按「calendar = 独立日历通路」的定义不该记 y（与途牛同型）。

    判据双向：
      · y → 源码必须真有 `path_note("日历"`（智行：4 处，账本 49 行）；
      · n → 源码必须确实没有（防止「其实接了却仍记 n」）。
    """
    import io as _io
    for plat in ("app_zhixing", "app_qunar"):
        src = _io.open(os.path.join(ROOT, "crawlers", plat + ".py"),
                       encoding="utf-8").read()
        has_cal_path = 'path_note("日历"' in src
        declared = CHANNEL_DIMENSIONS[plat].get("calendar")
        if has_cal_path:
            assert declared == "y", (
                "%s 源码里有独立日历通路（path_note(\"日历\")），"
                "声明却记 %r" % (plat, declared))
        else:
            assert declared != "y", (
                "%s 没有独立日历通路（源码 0 处 path_note(\"日历\")、"
                "账本无「日历」entry_path），calendar 不能记 y" % plat)
            assert (plat, "calendar") in _notes(), (
                "%s 的 calendar 记了 %r，必须给悬停说明讲清为什么"
                "（App 有日历页但只用于选日）" % (plat, declared))


def _notes():
    from core.channels import DIMENSION_NOTES
    return DIMENSION_NOTES


def test_tuniu_calendar_is_not_overclaimed():
    """途牛没有独立日历通路——这格必须是 n，且源码确实没有。

    反向也守住：万一以后真的接了日历，这条会红，提示把声明升回去。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    has_cal = any(n in src for n in ("calendar", "日历", "cheapestCalendar"))
    declared = CHANNEL_DIMENSIONS["tuniu"].get("calendar")
    if has_cal:
        assert declared == "y", (
            "途牛源码里已经出现日历通路，声明应升回 y（当前 %r）" % declared)
    else:
        assert declared == "n", (
            "途牛没有日历通路，calendar 不能记 %r（账本也只有 H5/API）"
            % declared)


def test_low_fare_matches_special_capability_table():
    """`low_fare` 与特价源表必须一致——同一件事两张表不能给相反答案。"""
    from core.specials import SPECIAL_CAPABILITY
    for p in ALL_PLATS:
        declared = CHANNEL_DIMENSIONS[p].get("low_fare")
        ent = SPECIAL_CAPABILITY.get(p) or {}
        has_src = bool(ent.get("sources"))
        if has_src:
            assert declared == "y", (
                "%s 在 SPECIAL_CAPABILITY 里有 %d 个源，矩阵却记 %r"
                % (p, len(ent["sources"]), declared))
        else:
            assert declared != "y", (
                "%s 在 SPECIAL_CAPABILITY 里没有源，矩阵却记 y" % p)


# ---- merged from tests/test_r922_display_spoof.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r922")

DESIGN = (900, 1600)


class _Dev:
    """假设备：``wm size/density`` 可读可写，``input`` 调用被记录。"""

    def __init__(self, size="900x1600", density=240, nodes=8):
        self.w = int(size.split("x")[0])
        self.h = int(size.split("x")[1])
        self.d = int(density)
        self.override = False
        self.nodes = nodes
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd == "shell wm size":
            return ("Physical size: 900x1600\nOverride size: %dx%d"
                    % (self.w, self.h)) if self.override else \
                   "Physical size: %dx%d" % (self.w, self.h)
        if cmd == "shell wm density":
            return ("Physical density: 240\nOverride density: %d" % self.d) \
                if self.override else "Physical density: %d" % self.d
        if cmd.startswith("shell wm size reset"):
            self.w, self.h, self.override = 900, 1600, False
            return ""
        if cmd.startswith("shell wm density reset"):
            self.d, self.override = 240, False
            return ""
        if cmd.startswith("shell wm size "):
            wh = cmd.split()[-1]
            self.w, self.h = [int(x) for x in wh.split("x")]
            self.override = True
            return ""
        if cmd.startswith("shell wm density "):
            self.d = int(cmd.split()[-1])
            self.override = True
            return ""
        return ""

    def dump(self):
        return "<node>" * self.nodes


# ---------------------------------------------------------------------------
# 1. display：读 / 计划 / 执行 / 回滚
# ---------------------------------------------------------------------------
def test_actual_reads_physical():
    got = display.actual(_Dev())
    assert (got["width"], got["height"], got["density"]) == (900, 1600, 240)
    assert got["override"] is False


def test_actual_prefers_override():
    d = _Dev()
    display.spoof(d, width=1080, height=1920, density=288)
    got = display.actual(d)
    assert (got["width"], got["height"]) == (1080, 1920)
    assert got["override"] is True


def test_plan_spoof_keeps_dp_constant():
    """density 与 height 同比 → dp 尺寸不变，界面布局不乱。"""
    p = display.plan_spoof(_Dev(), width=1080, height=1920)
    assert p["density"] == int(round(240 * (1920 / 1600.0)))   # 288
    p2 = display.plan_spoof(_Dev(), width=1080, height=1680)
    assert p2["density"] == int(round(240 * (1680 / 1600.0)))  # 252


def test_spoof_then_reset_roundtrip():
    d = _Dev()
    rep = display.spoof(d, width=1080, height=1920, density=288)
    assert rep["ok"] is True
    assert (rep["after"]["width"], rep["after"]["height"]) == (1080, 1920)
    back = display.reset(d)
    assert (back["after"]["width"], back["after"]["height"]) == (900, 1600)
    assert back["after"]["override"] is False


def test_spoof_rejects_empty_target():
    class _NoSize(_Dev):
        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            self.calls.append(cmd)
            return ""            # 读不到 wm size
    rep = display.spoof(_NoSize(), width=0, height=0)
    assert rep["ok"] is False and "目标分辨率" in rep["error"]


def test_scale_for_math():
    assert display.scale_for(DESIGN, (1080, 1920)) == (1.2, 1.2)
    assert display.scale_for(DESIGN, (900, 1600)) == (1.0, 1.0)
    assert display.scale_for(None, (1080, 1920)) == (1.0, 1.0)
    assert display.scale_for(DESIGN, (0, 0)) == (1.0, 1.0)


def test_audit_flags_mismatch():
    from core.android import fingerprint
    ident = fingerprint.build(3, vm=0)
    got = display.audit(_Dev(), ident)
    # 池里的机型不会是 900x1600 → 必然报不一致
    assert got["ok"] is False and got["issues"]


# ---------------------------------------------------------------------------
# 2. AdbDevice 坐标换算
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
    return devmod.AdbDevice("adb", "s"), calls


def test_design_off_is_byte_identical(monkeypatch):
    d, calls = _device(monkeypatch)
    assert d.design is None
    d.tap(100, 200)
    assert any(c.endswith("input tap 100 200") for c in calls), calls


def test_window_size_prefers_override(monkeypatch):
    """``wm size`` 有两行，必须取 Override —— 否则改屏幕后换算恒为 1.0。

    2026-11-03 实机踩到：屏幕已改成 1080x1920，但 ``window_size`` 正则取到
    第一个匹配（``Physical size: 900x1600``），于是 ``scale`` 恒等、
    写死的坐标全部按原值发出去 → 点击位置全偏，而账本只表现成
    「设城市失败 / 页面认不出」。
    """
    from core.android import device as devmod

    class _P:
        def __init__(self, out):
            self.stdout = out.encode()
            self.stderr = b""
            self.returncode = 0

    def _run(cmd, timeout, binary=False):
        joined = " ".join(cmd)
        if "wm" in joined and "size" in joined:
            return _P("Physical size: 900x1600\nOverride size: 1080x1920")
        return _P("")
    monkeypatch.setattr(devmod, "_run", _run)
    d = devmod.AdbDevice("adb", "s")
    assert d.window_size() == (1080, 1920)      # 不是 (900, 1600)！


def test_window_size_falls_back_to_physical(monkeypatch):
    from core.android import device as devmod

    class _P:
        def __init__(self, out):
            self.stdout = out.encode()
            self.stderr = b""
            self.returncode = 0

    def _run(cmd, timeout, binary=False):
        joined = " ".join(cmd)
        if "wm" in joined and "size" in joined:
            return _P("Physical size: 720x1280")     # 没有 override
        return _P("")
    monkeypatch.setattr(devmod, "_run", _run)
    assert devmod.AdbDevice("adb", "s").window_size() == (720, 1280)


def test_design_on_scales_tap_and_swipe(monkeypatch):
    d, calls = _device(monkeypatch, size="1080x1920")
    d.set_design(*DESIGN)                       # 1.2×
    assert d.to_device(100, 200) == (120, 240)
    assert d.to_design(120, 240) == (100, 200)
    d.tap(100, 200)
    assert any(c.endswith("input tap 120 240") for c in calls), calls
    d.swipe(0, 0, 100, 100, 200)
    assert any(c.endswith("input swipe 0 0 120 120 200") for c in calls), calls


def test_design_roundtrip_is_stable(monkeypatch):
    d, _ = _device(monkeypatch, size="1080x2400")
    d.set_design(*DESIGN)
    for x, y in ((0, 0), (450, 800), (899, 1599)):
        dx, dy = d.to_device(x, y)
        bx, by = d.to_design(dx, dy)
        assert abs(bx - x) <= 1 and abs(by - y) <= 1, (x, y, dx, dy, bx, by)


def test_set_design_zero_disables(monkeypatch):
    d, calls = _device(monkeypatch)
    d.set_design(900, 1600)
    assert d.set_design(0, 0) is None
    d.tap(10, 10)
    assert any(c.endswith("input tap 10 10") for c in calls)


def test_unreadable_size_falls_back_to_identity(monkeypatch):
    d, calls = _device(monkeypatch, size="?")
    d.set_design(*DESIGN)
    assert d._scale() == (1.0, 1.0)             # 读不到就不换算
    d.tap(100, 200)
    assert any(c.endswith("input tap 100 200") for c in calls)


# ---------------------------------------------------------------------------
# 3. CLI 的核心行为（不起真设备：只验"目标计算 + 白屏判据"）
# ---------------------------------------------------------------------------
def test_cli_idle_hint_reads_log(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import display_spoof as cli
    log = tmp_path / "monitor.log"
    log.write_text("x", encoding="utf-8")
    assert "活动" in cli._idle_hint(str(log))
    old = tmp_path / "old.log"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (0, 0))
    assert "空闲" in cli._idle_hint(str(old))
    assert "读不到" in cli._idle_hint(str(tmp_path / "nope.log"))


def test_cli_ui_alive_detects_blank():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import display_spoof as cli
    ok, why = cli._ui_alive(_Dev(nodes=8))
    assert ok is True and "8" in why
    ok2, why2 = cli._ui_alive(_Dev(nodes=2))
    assert ok2 is False and "白屏" in why2


# ---- merged from tests/test_r926_selfaudit_no_false_positive.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r926")


class FakeDev:
    """按命令返回：``test -e`` 走 exists 集合，``getprop`` 走 props。"""

    def __init__(self, exists=(), props=None, listing=None,
                 dirs=None, modes=None):
        self.exists = set(exists)
        # 父目录（app_can_see 要查它们的权限位）
        self.dirs = set(dirs or ("/data", "/data/local", "/data/local/tmp",
                                 "/mnt", "/system", "/system/bin",
                                 "/system/xbin", "/sbin"))
        # 默认 others 有 r-x（= App 能 traverse），让旧测试语义不变；
        # 要钉"0700 看不见"就把对应目录传成 drwx------
        self.modes = dict(modes or {})
        # 至少要有一个 prop：`detect()` 拿不到任何 props 会提前返回
        # （"device offline"），后面的文件探测根本不会执行。
        self.props = dict(props if props is not None
                          else {"ro.product.model": "SM-A5260"})
        self.listing = listing or "acct\nadb_keys\napex\nbin\ncache\n"
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        # **新契约**：`ls -d <单条路径>` 判存在、`ls -ld <父链...>` 判权限位。
        # 两者都把路径当**独立 argv**，所以不经过任何 shell 解析。
        if toks[:3] == ["shell", "ls", "-ld"]:
            out = []
            for p in toks[3:]:
                if p in self.exists or p in self.dirs:
                    mode = self.modes.get(p, "drwxr-xr-x")
                    out.append("%s 2 root root 4096 2026-11-04 12:00 %s"
                               % (mode, p))
            return "\n".join(out)
        if toks[:3] == ["shell", "ls", "-d"]:
            p = toks[3] if len(toks) > 3 else ""
            return p if (p in self.exists or p in self.dirs) else ""
        if "test -e" in cmd:
            # 旧契约（保留：钉"不许再用 sh -c 探测"——它会被 adb 拆参数恒假）
            import re as _re
            m = _re.search(r"test -e '([^']+)'", cmd)
            path = m.group(1) if m else ""
            return "TM_YES" if path in self.exists else "TM_NO"
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if "ls " in cmd:
            return self.listing          # 模拟 ls 展开目录的恶劣行为
        return ""


# ---------------------------------------------------------------------------
# 1. audit：不能把目录内容当残留
# ---------------------------------------------------------------------------
def test_audit_does_not_expand_directories():
    """`ls` 会返回一堆根目录条目，但一条都不该被算成 root 残留。"""
    dev = FakeDev(exists=(), listing="acct\nadb_keys\napex\nbin\ncache\n")
    rep = fp.audit(dev)
    fs_leaks = [x for x in rep["leaks"] if x["key"] == "fs"]
    assert fs_leaks == [], fs_leaks
    assert rep["score"] >= 60, rep["score"]


def test_audit_reports_real_su_only():
    dev = FakeDev(exists={"/system/xbin/su"}, listing="acct\nbin\n")
    rep = fp.audit(dev)
    fs_leaks = [x["value"] for x in rep["leaks"] if x["key"] == "fs"]
    assert fs_leaks == ["/system/xbin/su"], fs_leaks


def test_audit_probe_avoids_shell_metacharacters(monkeypatch):
    """探测必须把路径当**独立 argv**，不许包 `sh -c`。

    这条测试曾经反向钉住了一个错误实现（`sh -c "test -e X && echo A || echo B"`），
    而那个实现是**恒假**的：adb 把命令行按空格拆开送进设备 shell，设备执行的是
    `sh -c test`（内层拿不到参数 → 恒假）+ 外层 `|| echo TM_NO`
    → 任何路径都判"不存在"，`root 痕迹: []` 于是从来没有意义。
    用 `/system/bin/sh`（必然存在）一测就露馅。

    但**原始意图仍然要保住**：不能退回去用不带 `-d` 的 `ls <路径>`，
    那会把目录内容列出来 → 17 条幽灵残留、自检被打到 0 分。
    所以钉的是：用 `ls -d`/`ls -ld`，且不出现 shell 元字符。
    """
    dev = FakeDev(exists={"/system/bin/sh"})
    assert fp._exact_path_exists(dev, "/system/bin/sh") is True, \
        "探针又恒假了：存在的文件判不出存在"
    joined = "\n".join(dev.calls)
    assert "test -e" not in joined, "还在用 sh -c 探测（会被拆参数 → 恒假）"
    assert '"sh", "-c"' not in joined, "探测命令被包进 sh -c"
    # 反幽灵：不许出现"不带 -d/-ld 的 ls <单个路径>"
    assert "ls /system/bin/su" not in joined, "退回了会展开目录的 ls"


# ---------------------------------------------------------------------------
# 2. stealth.detect：同源 bug
# ---------------------------------------------------------------------------
def test_detect_does_not_expand_shared_dir():
    """`/mnt/shared` 常是符号链接；`ls` 会展开成根目录，不能算共享目录命中。"""
    dev = FakeDev(exists=(), listing="acct\nadb_keys\napex\nbin\n")
    rep = st.detect(dev)
    shared = [x for x in rep["emulator"] if x.startswith("shared:")]
    assert shared == [], shared
    assert rep["score"] >= 60, rep["score"]


def test_detect_reports_real_shared_dir():
    dev = FakeDev(exists={"/mnt/shared"}, listing="acct\n")
    rep = st.detect(dev)
    assert any("/mnt/shared" in x for x in rep["emulator"]), rep["emulator"]


# ---------------------------------------------------------------------------
# 3. 厂商 prop：值非空才算暴露面，清空后要算干净
# ---------------------------------------------------------------------------
def test_vendor_prop_with_value_is_leak():
    dev = FakeDev(props={"nemud.player_engine": "MUMU15"})
    rep = st.detect(dev)
    assert any("nemud" in x for x in rep["emulator"]), rep["emulator"]


def test_vendor_prop_cleared_is_not_leak():
    """清空值之后不再自报"我是 MUMU15"，就不该继续扣分。"""
    dev = FakeDev(props={"nemud.player_engine": "",
                         "nemud.player_architecture": ""})
    rep = st.detect(dev)
    assert not any("nemud" in x for x in rep["emulator"]), rep["emulator"]


def test_is_vendor_prop_ignores_system_runtime_keys():
    """`init.svc.*` 是系统运行态：删不掉，也不算厂商残留。"""
    assert st._is_vendor_prop("init.svc.nemud", "running") is False
    assert st._is_vendor_prop("init.svc_debug_pid.nemuinit", "1600") is False
    assert st._is_vendor_prop("nemud.player_engine", "MUMU15") is True
    assert st._is_vendor_prop("nemud.player_engine", "") is False


# ---------------------------------------------------------------------------
# 4. hide：没有 Magisk 也要清（用 setprop 写空）
# ---------------------------------------------------------------------------
def test_hide_clears_vendor_props_without_resetprop(monkeypatch):
    """无 Magisk 时 `resetprop` 不可用，但厂商键不是 ro.*，清空可行。"""
    dev = FakeDev(props={"nemud.player_engine": "MUMU15"})

    monkeypatch.setattr(st, "_root", lambda d: True)
    monkeypatch.setattr(st, "_magisk", lambda d: "")
    monkeypatch.setattr(st, "boot_id", lambda d: "boot-x", raising=False)

    captured = {}

    def _as_root(d, script, timeout=None):
        captured["script"] = script
        return ""
    monkeypatch.setattr(st, "as_root", _as_root)

    st.hide(dev, packages=["ctrip"])
    script = captured.get("script", "")
    assert "setprop" in script
    assert "nemud.player_engine" in script
    # 用清空（''）而不是依赖 resetprop --delete
    assert "'nemud.player_engine' ''" in script or "'' " in script


# ---- merged from tests/test_r958_argv_split.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 三段 argv 的调用形态：("shell", "sh", "-c", ...) 或 ('shell','sh','-c',...)
BAD_FORMS = (
    '"shell", "sh", "-c"',
    "'shell', 'sh', '-c'",
    '"shell", "sh", "-c"',
    "dev._sh(\"shell\", \"sh\", \"-c\"",
)
SCAN_DIRS = ("core", "crawlers", "scripts")


def _py_files():
    for base in SCAN_DIRS:
        d0 = os.path.join(ROOT, base)
        for cur, dirs, files in os.walk(d0):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in files:
                if fn.endswith(".py"):
                    yield os.path.join(cur, fn)


# ---------------------------------------------------------------------------
# 1. 全仓扫描：不许再有"三段 argv 交给设备 shell 重解析"的调用
# ---------------------------------------------------------------------------
def test_no_three_argv_sh_c_anywhere():
    bad = []
    for path in _py_files():
        s = io.open(path, encoding="utf-8").read()
        for n, line in enumerate(s.splitlines(), 1):
            code = line.split("#", 1)[0]
            for form in BAD_FORMS:
                if form in code:
                    bad.append("%s:%d  %s" % (
                        os.path.relpath(path, ROOT), n, line.strip()[:80]))
    assert not bad, (
        "adb 三段 argv 会被设备 shell 重新解析（探针恒假/写入落空）。\n"
        "请改用 device.run_script / fingerprint.sh_script：\n  "
        + "\n  ".join(bad))


def test_single_argv_entry_points_exist():
    from core.android.device import AdbDevice
    from core.android import fingerprint as fp
    assert hasattr(AdbDevice, "run_script"), "缺 AdbDevice.run_script"
    assert hasattr(fp, "sh_script"), "缺 fingerprint.sh_script"


# ---------------------------------------------------------------------------
# 2. run_script 真的把脚本作为**一个** argv 传下去
# ---------------------------------------------------------------------------
class _Rec:
    def __init__(self):
        self.calls = []

    def _sh(self, *a, timeout=None):
        self.calls.append(list(a))
        return "OUT"


def test_run_script_passes_script_as_one_arg():
    from core.android.device import AdbDevice
    d = AdbDevice.__new__(AdbDevice)          # 不跑 __init__（不需要真 adb）
    rec = _Rec()
    d._sh = rec._sh
    script = "f=$(ls -t /data/anr | head -1); [ -n \"$f\" ] && head -4 x/$f"
    got = d.run_script(script)
    assert got == "OUT"
    assert rec.calls == [["shell", script]], rec.calls   # 恰好两段，无 sh -c


def test_write_remote_still_verifies_by_readback():
    """写文件必须读回比对（`>` 落空时不能假报成功）。"""
    from core.android import fingerprint as fp

    class _W:
        def __init__(self):
            self.stored = None

        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            if cmd.startswith("shell cat"):
                return self.stored or ""
            if "echo" in cmd and ">" in cmd:
                # 模拟被本地/设备 shell 吃掉重定向：什么都没写
                return ""
            return ""

    w = _W()
    assert fp.write_remote(w, "/data/local/tmp/x.ok", "boot-1") is False, \
        "写入没落地却返回 True（假成功）"


# ---------------------------------------------------------------------------
# 3. 探针不许恒假：存在的文件必须判存在
# ---------------------------------------------------------------------------
def test_probe_detects_existing_file():
    from core.android import fingerprint as fp

    class _P:
        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            if cmd.startswith("shell ls -ld"):
                p = cmd.split()[-1]
                if p == "/system":
                    return "drwxr-xr-x 2 root root 4096 x /system"
                if p == "/system/bin":
                    return "drwxr-xr-x 2 root root 4096 x /system/bin"
                return ""
            if cmd.startswith("shell ls -d"):
                p = cmd.split()[-1]
                return p if p == "/system/bin/sh" else ""
            return ""

    assert fp._exact_path_exists(_P(), "/system/bin/sh") is True, \
        "存在的文件判不出存在 = 探针恒假（本仓栽过 55 轮的那条）"
    assert fp._exact_path_exists(_P(), "/system/bin/su") is False


# ---- merged from tests/test_r967_yield_report_reads_real_paths.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

def _seed(tmp_path, plat, ok=5, fail=1, rows=40, streak=0):
    """按**写侧的真实约定**造数据（不自己拼路径，否则测的还是想象）。"""
    yl = default_ledger(str(tmp_path), plat)
    for i in range(ok):
        yl.note(plat, "h5", True, rows=rows)
    for i in range(fail):
        yl.note(plat, "h5", False, rows=0)
    ll = default_login(str(tmp_path), plat)
    for _ in range(streak):
        ll.note(plat, False)


def test_report_sees_per_platform_ledgers(tmp_path):
    _seed(tmp_path, "qunar", ok=6, fail=2)
    _seed(tmp_path, "ctrip", ok=9, fail=0)
    data = yr.collect(str(tmp_path))
    y = data["yield"]
    assert set(y) >= {"qunar", "ctrip"}, \
        "读不到按渠道账本（以前读 user_data/yield_stats.json 那个没人写的路径）"
    assert y["ctrip"]["samples"] == 9, y["ctrip"]
    assert y["qunar"]["samples"] == 8, y["qunar"]
    assert y["ctrip"]["rate"] > y["qunar"]["rate"]


def test_advice_not_empty_when_rate_is_high(tmp_path):
    """有真实样本且下界高，就该出'有余量'的建议，而不是'各渠道都在正常区间'。"""
    _seed(tmp_path, "tuniu", ok=20, fail=0, rows=30)
    data = yr.collect(str(tmp_path), base_interval=30)
    item = data["yield"].get("tuniu") or {}
    assert item.get("samples"), item
    assert item["interval"]["minutes"] <= 30, item["interval"]


def test_broken_ledger_does_not_blank_the_whole_report(tmp_path):
    """一个渠道的账本坏掉，其余渠道必须照常出。

    以前是"读错一个路径 → 整表空"，这属于同一类脆弱。
    """
    _seed(tmp_path, "good", ok=4, fail=0)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "yield_stats.json").write_text("{ 这不是 json", encoding="utf-8")
    data = yr.collect(str(tmp_path))
    assert "good" in data["yield"], data["yield"].keys()
    assert data["yield"]["good"]["samples"] == 4


def test_profile_scopes_to_one_channel(tmp_path):
    _seed(tmp_path, "qunar", ok=7, fail=1)
    _seed(tmp_path, "ctrip", ok=3, fail=0)
    data = yr.collect(str(tmp_path), profile="qunar")
    assert set(data["yield"]) == {"qunar"}, data["yield"].keys()


def test_platform_dirs_skips_non_ledger_dirs(tmp_path):
    """渠道发现以"有没有账本文件"为准：目录清单会漏新渠道、留旧渠道。"""
    _seed(tmp_path, "tongcheng", ok=2, fail=0)
    (tmp_path / "device").mkdir()
    (tmp_path / "emptydir").mkdir()
    assert yr._platform_dirs(str(tmp_path)) == ["tongcheng"]


def test_slider_ledger_found_per_platform(tmp_path):
    plat = tmp_path / "app_qunar"
    plat.mkdir()
    (plat / "slider_ledger.json").write_text(
        json.dumps({"app_qunar": {"tries": 3, "ok": 1, "day": "2026-11-05",
                                  "day_tries": 1, "kinds": {}}}),
        encoding="utf-8")
    d = yr._slider_ledger(str(tmp_path))
    assert "app_qunar" in d, d


def test_writer_and_reader_share_one_path_convention():
    """约定只能有一份：读侧必须走 `default_ledger`，不许自己拼路径。

    这条是**结构**约束而非行为约束 —— 行为测试能过不代表下次改名时不会又漂移，
    而这次事故的正是"两边各写一遍路径"。
    """
    src = io.open(os.path.join(ROOT, "scripts", "yield_report.py"),
                  encoding="utf-8").read()
    i = src.find("def collect(")
    body = src[i:src.find("\ndef ", i + 10)]
    assert "default_ledger" in body, "collect 又自己拼账本路径了"
    assert 'os.path.join(base, "yield_stats.json")' not in body, \
        "仍在读 user_data/yield_stats.json（没有代码会写这个路径）"
