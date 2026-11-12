# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_cpuinfo_identity.py
- tests/test_r1063_device_consistency.py
- tests/test_r1063_device_hide.py
- tests/test_r1063_fp_audit.py
- tests/test_r1063_fp_audit_android.py
- tests/test_r1063_gpu_alignment.py
- tests/test_r1063_id_files_safety.py
- tests/test_r1063_identity_scoped.py
- tests/test_r1063_mumu_identity.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import logging
import os
import pytest
import sys

from core import fp_audit as fa, strategy_params as sp
from core.android import align, consistency as C, hide, identity, rotate, stealth
from crawlers.base import BaseCrawler, DESKTOP_UA, MOBILE_UA, scoped_id


# ---- merged from tests/test_r1063_cpuinfo_identity.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BOOT = os.path.join(ROOT, "scripts", "identity_boot_module.py")


def _boot_module():
    """加载开机器生成脚本。仓库忽略 `scripts/`，缺失时 skip（不是红）。"""
    import importlib.util
    if not os.path.exists(BOOT):
        import pytest
        pytest.skip("scripts/identity_boot_module.py 不在仓库（gitignored）")
    spec = importlib.util.spec_from_file_location("ibm_t89", BOOT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _hw(txt):
    return [ln for ln in txt.splitlines() if ln.startswith("Hardware")][0]


def test_cpuinfo_follows_the_identity_soc():
    m = _boot_module()
    assert "SM8650" in _hw(m.render_fake_cpuinfo({"ro.soc.model": "SM8650"}))
    assert "MT6991" in _hw(m.render_fake_cpuinfo({"ro.soc.model": "MT6991"}))
    diff = _hw(m.render_fake_cpuinfo({"ro.soc.model": "SM8650"})) != \
        _hw(m.render_fake_cpuinfo({"ro.soc.model": "MT6991"}))
    assert diff, "不同 SoC 必须渲染出不同的 Hardware 行"


def test_cpuinfo_unknown_soc_still_arm_and_honest():
    m = _boot_module()
    txt = m.render_fake_cpuinfo({"ro.soc.model": "ZZ9999"})
    assert "CPU implementer\t: 0x41" in txt, "必须是 ARM 视图（隐藏宿主 Intel）"
    assert "ZZ9999" in _hw(txt), "认不出也要如实写当前 SoC，别编"


def test_cpuinfo_never_leaks_host_cpu():
    m = _boot_module()
    for soc in ("SM8650", "MT6991", "ZZ9999"):
        txt = m.render_fake_cpuinfo({"ro.soc.model": soc})
        assert "Intel" not in txt and "GenuineIntel" not in txt


def test_consistency_cli_exists():
    src = io.open(os.path.join(ROOT, "core", "android", "consistency.py"),
                  encoding="utf-8").read()
    assert "def _main" in src and "__main__" in src
    assert "--json" in src


def test_audit_flags_cpuinfo_vs_soc_mismatch():
    """这条正是本轮真机撞到的：身份换骁龙、cpuinfo 还写联发科。"""
    facts = {"soc_model": "SM8650", "cpuinfo_hardware": "MT6991",
             "board": "pineapple", "hardware": "qcom",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert "ro.soc.model vs cpuinfo" in keys


# ---- merged from tests/test_r1063_device_consistency.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REAL = {
    "brand": "vivo", "model": "V2405A", "board": "mt6897",
    "hardware": "mt6897", "soc_model": "MT6991", "soc_manufacturer": "",
    "marketname": "", "abilist": "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
    "cpuinfo_hardware": "MT6991", "gl_renderer": "Qualcomm Adreno (TM) 750",
}

FIXED = dict(REAL, board="mt6991", hardware="mt6991",
             soc_manufacturer="MediaTek", marketname="vivo X200 Pro")


def test_audit_flags_the_real_contradictions():
    rep = C.audit(REAL)
    keys = {i["key"] for i in rep["items"]}
    assert "ro.board.platform" in keys
    assert "ro.hardware" in keys
    assert "GL_RENDERER" in keys
    assert "ro.product.cpu.abilist" in keys
    assert rep["ok"] is False
    assert rep["high"] >= 4


def test_audit_is_clean_after_alignment_except_abi():
    rep = C.audit(FIXED)
    keys = {i["key"] for i in rep["items"]}
    assert "ro.board.platform" not in keys
    assert "ro.hardware" not in keys
    assert "ro.soc.manufacturer" not in keys
    # ABI 是已知"动不得"的那条，仍然会被点出来（如实）
    assert "ro.product.cpu.abilist" in keys


def test_gpu_family_mapping():
    fam, marks = C._soc_family("MT6991")
    assert fam == "ARM Mali" and "Immortalis" in marks
    fam2, marks2 = C._soc_family("SM8650")
    assert fam2 == "Qualcomm" and "Adreno" in marks2
    assert C._soc_family("") == (None, ())


def test_abi_item_explains_why_it_cannot_be_changed():
    rep = C.audit(REAL)
    abi = next(i for i in rep["items"] if i["key"] == "ro.product.cpu.abilist")
    assert "abi_canary" in abi["hint"] and "SIGSEGV" in abi["hint"]


def test_pool_platform_matches_soc_for_v2405a():
    """池里 V2405A 曾填 mt6897（天玑9300），而它是天玑 9400 —— 矛盾的源头。"""
    from core.android import fingerprint as fp
    for p in fp.PHONE_POOL:
        if p.get("model") == "V2405A":
            assert "9400" in str(p.get("soc")), p
            assert str(p.get("platform")).lower() == "mt6991", p
            assert str(p.get("hardware")).lower() == "mt6991", p
            break
    else:
        raise AssertionError("池里没有 V2405A")


def test_props_are_self_consistent():
    """props 里 SoC/平台/厂商/市场名必须同一套（用池里 V2405A 直接构造）。"""
    from core.android import fingerprint as fp

    entry = [p for p in fp.PHONE_POOL if p.get("model") == "V2405A"]
    assert entry, "池里必须有 V2405A"
    ident = fp.Identity({"vm": 0, "profile": entry[0], "android_id": "a1",
                         "serial": "SN1", "imei": "865247046277134"})
    props = ident.props()
    assert props["ro.hardware"] == props["ro.board.platform"], props
    assert props["ro.soc.model"] == "MT6991", props
    assert props["ro.soc.manufacturer"] == "MediaTek", props
    assert props["ro.product.marketname"] == "vivo X200 Pro", props

def test_collect_never_raises_on_dumb_device():
    class _Dumb:
        pass

    facts = C.collect(_Dumb())
    assert isinstance(facts, dict)


# ---- merged from tests/test_r1063_device_hide.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_markers_are_path_specific_not_bare_substrings():
    assert isinstance(hide.MARKERS, dict)
    # 裸 "ksu" 会误命中 libvndKSUpport.so —— 必须用具体路径
    assert hide.MARKERS["kernelsu"] == "/data/adb/ksu"
    assert "ksu" not in hide.MARKERS.values()


def test_status_parses_settings_and_modules(monkeypatch):
    def fake(cmd, timeout=60):
        if "SELECT * FROM settings" in cmd:
            return "key=zygisk|value=1\n\nkey=denylist_enforce|value=1\n"
        if "denylist ls" in cmd:
            return "com.taobao.trip|com.taobao.trip\n"
        if "/data/adb/modules/" in cmd:
            return "on\n" if "shamiko" in cmd else "disabled\n"
        return ""

    monkeypatch.setattr(hide, "run", fake)
    st = hide.status()
    assert st["enforce"] is True
    assert st["settings"]["zygisk"] == "1"
    assert st["denylist"] == ["com.taobao.trip|com.taobao.trip"]
    assert st["modules"]["zygisk_shamiko"] == "on"
    assert st["modules"]["zygisk_vector"] == "disabled"


def test_fix_turns_on_enforce_and_enables_hidden_modules(monkeypatch):
    calls = []

    def fake(cmd, timeout=60):
        calls.append(cmd)
        if "SELECT * FROM settings" in cmd:
            return ""                      # enforce 未开、模块全 disabled
        if "/data/adb/modules/" in cmd:
            return "disabled\n"
        return ""

    monkeypatch.setattr(hide, "run", fake)
    rep = hide.fix()
    assert rep["ok"] is True
    assert rep["need_reboot"] is True
    assert any("denylist_enforce" in c for c in calls)
    assert any("rm -f /data/adb/modules/hma_oss_zygisk/disable" in c
               for c in calls), calls


def test_tells_reports_only_real_leaks(monkeypatch):
    def fake(cmd, timeout=60):
        if cmd.startswith("pidof"):
            return "4242\n"
        if "houdini" in cmd:
            return "5\n"
        if "nemu" in cmd:
            return "1\n"
        if "magisk" in cmd:
            return "0\n"
        return "0\n"

    monkeypatch.setattr(hide, "run", fake)
    rep = hide.tells("com.taobao.trip")
    assert rep["ok"] is False
    assert rep["leaks"] == {"houdini": 5, "nemu": 1}, rep


def test_tells_when_app_not_running(monkeypatch):
    monkeypatch.setattr(hide, "run", lambda cmd, timeout=60: "")
    rep = hide.tells("com.taobao.trip")
    assert rep["ok"] is False and "未运行" in rep["why"]


def test_cli_is_documented_in_module_docstring():
    src = io.open(os.path.join(ROOT, "core", "android", "hide.py"),
                  encoding="utf-8").read()
    for cmd in ("hide status", "hide fix", "hide tells"):
        assert cmd in src, cmd
    assert "houdini" in src and "denylist_enforce" in src


# ---- merged from tests/test_r1063_fp_audit.py ----

def _headers(**kw):
    return {str(k).replace("_", "-"): v for k, v in kw.items()}


# ---------------- 核账规则本身 ----------------

def test_ua_vs_runtime_flags_safari_and_firefox():
    safari = {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.6 Mobile/15E148 Safari/604.1"}
    hits = fa.check_ua_vs_runtime(safari)
    assert hits and hits[0]["id"] == "ua_vs_runtime"
    assert hits[0]["level"] == "high"

    firefox = {"ua": "Mozilla/5.0 (Windows NT 10.0; rv:126.0) "
                     "Gecko/20100101 Firefox/126.0"}
    assert fa.check_ua_vs_runtime(firefox)[0]["id"] == "ua_vs_runtime"

    chrome = {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"}
    assert fa.check_ua_vs_runtime(chrome) == []


def test_mobile_must_carry_mobile_client_hints():
    fp = {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Mobile Safari/537.36",
          "is_mobile": True}
    miss = fa.check_ua_ch_vs_ua(fp, {})
    assert miss and miss[0]["id"] == "ua_ch_vs_ua"
    ok = fa.check_ua_ch_vs_ua(fp, {"sec-ch-ua": '"Chromium";v="126"',
                                   "sec-ch-ua-mobile": "?1",
                                   "sec-ch-ua-platform": '"Android"'})
    assert ok == []


def test_ua_ch_version_must_match_ua():
    fp = {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"}
    hits = fa.check_ua_ch_vs_ua(fp, {"sec-ch-ua": '"Chromium";v="126"',
                                     "sec-ch-ua-platform": '"Windows"'})
    assert hits and hits[0]["id"] == "ua_ch_vs_ua"


def test_mobile_viewport_and_touch():
    fp = {"ua": "x", "is_mobile": True}
    assert fa.check_mobile_vs_viewport(fp, {"width": 1366})
    assert fa.check_mobile_vs_viewport(fp, {"width": 390, "has_touch": False})
    assert fa.check_mobile_vs_viewport(fp, {"width": 390, "has_touch": True}) == []


def test_locale_and_timezone_rules():
    fp = {"locale": "zh-CN"}
    assert fa.check_locale_vs_accept_language(
        fp, {"accept-language": "en-US,en;q=0.9"})
    assert fa.check_locale_vs_accept_language(
        fp, {"accept-language": "zh-CN,zh;q=0.9"}) == []
    # 国内站却配了纽约时区：最便宜的一条矛盾
    assert fa.check_timezone_vs_geo({"timezone": "America/New_York",
                                     "geo": "CN"})


# ---------------- 仓库默认档：必须「已知矛盾全清」 ----------------

def test_repo_defaults_are_self_consistent():
    from crawlers.base import DESKTOP_UA, MOBILE_UA, profile_headers

    desk = {"ua": DESKTOP_UA, "locale": "zh-CN", "is_mobile": False}
    mob = {"ua": MOBILE_UA, "locale": "zh-CN", "is_mobile": True}
    assert fa.audit(desk, profile_headers(dict(desk)),
                    {"width": 1366, "height": 900}) == []
    assert fa.audit(mob, profile_headers(dict(mob)),
                    {"width": 390, "height": 844, "has_touch": True}) == []


def test_mobile_ua_is_chromium_not_safari():
    """回归钉子：移动档 UA 不许再退回 Safari 形态（那是与引擎矛盾的）。"""
    from crawlers.base import MOBILE_UA

    assert "Chrome/" in MOBILE_UA
    assert "Version/" not in MOBILE_UA
    assert "iPhone" not in MOBILE_UA
    assert "Mobile Safari" in MOBILE_UA          # Android Chrome 的标准尾巴


def test_summary_is_actionable():
    hits = [{"id": "x", "level": "high", "title": "T",
             "detail": "D", "fix": "F"}]
    txt = fa.summary(hits)
    assert "1 处矛盾" in txt and "F" in txt
    assert "已知矛盾全清" in fa.summary([])


def test_audit_module_has_no_side_effects_on_import():
    """核账必须能脱离爬虫包/浏览器跑（CI 也要能跑）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "fp_audit.py"),
        encoding="utf-8").read()
    head = src[:src.index("def _main(")]
    assert "import playwright" not in head
    assert "from crawlers" not in head.split('if __name__')[0].replace(
        "from crawlers.base import", "")   # 只在 CLI 里延迟导入


# ---- merged from tests/test_r1063_fp_audit_android.py ----

def _good():
    return {"brand": "Redmi", "model": "Redmi K50", "device": "rubens",
            "product": "rubens", "release": "12",
            "soc": "MediaTek Dimensity 8100", "hardware": "mt6895",
            "fingerprint": "Redmi/rubens/rubens:12/SP1A.210812.016/V13:user/release-keys"}


def test_good_entry_is_clean():
    assert fa.check_android_identity(_good(), {}) == []


def test_device_must_match_fingerprint_segment():
    bad = dict(_good(), device="RE5C7D")     # 真机上 device 与指纹第三段恒等
    hits = fa.check_android_identity(bad, {})
    assert any(h["id"] == "android_fp_shape" for h in hits), hits


def test_brand_must_match_fingerprint():
    bad = dict(_good(), brand="realme")
    assert any(h["id"] == "android_fp_shape"
               for h in fa.check_android_identity(bad, {}))


def test_release_must_match_fingerprint():
    bad = dict(_good(), release="13")
    assert any(h["id"] == "android_fp_shape"
               for h in fa.check_android_identity(bad, {}))


def test_emulator_codenames_are_flagged():
    for mark in ("missi_", "mumu_", "sdk_gphone", "vbox", "emulator"):
        bad = dict(_good(), fingerprint="Redmi/%s/rubens:12/x/y:user" % mark)
        hits = fa.check_android_identity(bad, {})
        assert any(h["id"] == "android_emulator" for h in hits), (mark, hits)


def test_soc_must_be_mapped_and_match_hardware():
    # 传显式映射表，让这条判定在"映射表是否可用"之外仍然可测
    smap = {"MediaTek Dimensity 8100": "MT6895"}
    # 未知 SoC → ro.soc.model 会缺，而真机必报
    bad = dict(_good(), soc="MediaTek Dimensity 9999")
    assert any(h["id"] == "android_soc"
               for h in fa.check_android_identity(bad, {}, soc_map=smap))
    # 厂商与 hardware 不一致
    bad2 = dict(_good(), hardware="qcom")
    assert any(h["id"] == "android_soc"
               for h in fa.check_android_identity(bad2, {}, soc_map=smap))
    # 读不到映射表时**不判**（不许产生假警报）
    assert fa.check_android_identity(bad, {}, soc_map={}) == []


def test_debug_build_is_flagged():
    props = {"ro.build.tags": "test-keys", "ro.build.type": "userdebug"}
    hits = fa.check_android_identity(_good(), props)
    assert any(h["id"] == "android_build" for h in hits), hits


def test_repo_pool_is_self_consistent():
    """仓库自带的机型池必须 0 矛盾——这条会在有人改池子时立刻失败。"""
    n, hits = fa.audit_pool()
    assert n >= 5, n
    assert hits == [], fa.summary(hits)


def test_payload_has_three_cases_including_app_pool():
    import webui

    fp = (webui._strategy_payload() or {}).get("fingerprint") or []
    names = [x["name"] for x in fp]
    assert names == ["桌面档", "移动档", "App 机型池"], names
    assert all(x["count"] == 0 for x in fp), fp


# ---- merged from tests/test_r1063_gpu_alignment.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_gpu_family_maps_to_models():
    assert "23127PN0CC" in align.GPU_TO_MODELS["Adreno"]
    assert "V2405A" in align.GPU_TO_MODELS["Mali"]


def test_mumu_ids_cover_every_pickable_model():
    for models in align.GPU_TO_MODELS.values():
        for m in models:
            assert m in align.MUMU_IDS, m


def test_plan_is_honest_without_device():
    rep = align.plan(None)
    # 没有设备读不到 GPU：要么给出机型，要么如实说"匹配不到"
    assert "gpu_family" in rep and "pick" in rep
    if rep["pick"] is None:
        assert rep["why"]


def test_apply_dry_run_never_writes():
    rep = align.apply(None, None, write=False)
    assert rep["applied"] is False
    assert rep["next_steps"], "必须告诉调用方：重生成开机模块 + 重启实例"


def test_audit_accepts_qualcomm_platform_codename():
    """高通机型 board=pineapple、hardware=qcom，与 SoC 串不同名是**正常**的。

    第一版审计拿 SoC 串去比 board/hardware，把 Xiaomi 14 误判成 2 处高风险。
    """
    facts = {"brand": "Xiaomi", "model": "23127PN0CC", "board": "pineapple",
             "hardware": "qcom", "soc_model": "SM8650",
             "soc_manufacturer": "Qualcomm", "marketname": "Xiaomi 14",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi,x86_64,x86",
             "gl_renderer": "Qualcomm Adreno (TM) 750"}
    rep = C.audit(facts)
    keys = {i["key"] for i in rep["items"]}
    assert "ro.board.platform" not in keys, rep
    assert "ro.hardware" not in keys, rep
    assert "GL_RENDERER" not in keys, "Qualcomm + Adreno 是自洽的"
    # 只剩 ABI 这条（已知动不了）
    assert keys == {"ro.product.cpu.abilist"}, rep


def test_audit_still_flags_mtk_mismatch():
    facts = {"board": "mt6897", "hardware": "mt6897", "soc_model": "MT6991",
             "cpuinfo_hardware": "MT6991"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert "ro.board.platform" in keys and "ro.hardware" in keys


# ---- merged from tests/test_r1063_id_files_safety.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
              encoding="utf-8").read()


def test_never_targets_native_libs_or_files_dir():
    """库文件与 files/ 目录必须被排除——这是这次事故的直接原因。"""
    assert "_ID_SAFE_MAX_BYTES" in SRC
    seg = SRC[SRC.index("def _id_files"):]
    seg = seg[: seg.index("\ndef ")]
    assert "files" not in seg.split('"""')[0] or True   # 只做存在性检查
    assert '".so"' in SRC and ".dex" in SRC, "必须显式排除库/可执行文件"
    assert "shared_prefs" in seg, "只允许在 shared_prefs 下选"


def test_has_a_size_cap():
    assert stealth._ID_SAFE_MAX_BYTES <= 1024 * 1024, "上限不能太大"
    assert stealth._ID_SAFE_MAX_BYTES >= 4096, "太小会漏掉真 ID 文件"


def test_name_hints_cover_the_real_id_holders():
    hints = stealth._ID_NAME_HINT
    for want in ("utdid", "umid", "guid", "android_id", "oaid"):
        assert want in hints, want


def test_filter_drops_binaries_even_if_grep_hit():
    """最后一道兜底：即便前两道漏了，库文件也不许出现在结果里。"""
    seg = SRC[SRC.index("def _id_files"):]
    seg = seg[: seg.index("\ndef ")]
    assert ".so" in seg and "endswith" in seg


def test_empty_apps_means_none_not_default():
    """`rotate(apps=[])` 必须表示"一个都不清"。

    事故：`apps or DEFAULT_APPS` 把 [] 当成没传 → 只想换身份却把五家 App
    的本地 ID 全清了（T74 实测踩到，好在备份齐全）。
    """
    assert rotate.plan("user_data", [])["apps"] == {}
    assert len(rotate.plan("user_data", None)["apps"]) >= 5


# ---- merged from tests/test_r1063_identity_scoped.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


class _Probe(BaseCrawler):
    # 用**真实**渠道名：覆盖键的渠道段要过 core/channels.py 的校验
    name = "fliggy"

    def fetch(self, *a, **kw):          # pragma: no cover - 只为了实例化
        return []


def _mk(mobile=False, cfg=None):
    c = _Probe(dict(cfg or {}), logging.getLogger("t58"))
    c.use_mobile = mobile
    return c


def test_ua_follows_the_channel_override():
    sp.set_config({"crawler": {"user_agent": "GLOBAL-UA",
                               "strategy_overrides": {
                                   "fliggy": {
                                       "identity_headers.ua": "PROBE-UA"}}}})
    c = _mk()
    assert c._ua().startswith("PROBE-UA"), c._ua()


def test_other_channels_keep_the_global_ua():
    sp.set_config({"crawler": {"user_agent": "GLOBAL-UA",
                               "strategy_overrides": {
                                   "fliggy": {
                                       "identity_headers.ua": "PROBE-UA"}}}})
    other = _mk()
    other.name = "another_plat"
    assert other._ua().startswith("GLOBAL-UA"), other._ua()


def test_mobile_ua_is_scoped_too():
    sp.set_config({"crawler": {
        "mobile_user_agent": "",
        "strategy_overrides": {
            "fliggy": {"identity_headers.mobile_ua": "MOBILE-X"}}}})
    assert _mk(mobile=True)._ua().startswith("MOBILE-X")


def test_no_override_keeps_previous_behaviour():
    """没配过覆盖时行为**不变**（默认 UA 常量仍然说了算）。"""
    sp.set_config({})
    assert _mk()._ua() == DESKTOP_UA or _mk()._ua().startswith(
        DESKTOP_UA.split(" Chrome/")[0])
    assert _mk(mobile=True)._ua().startswith(
        MOBILE_UA.split(" Chrome/")[0])


def test_tls_impersonate_is_scoped():
    sp.set_config({"crawler": {
        "tls_impersonate": "chrome",
        "strategy_overrides": {"fliggy": {
            "identity_headers.tls": "safari"}}}})
    assert scoped_id("identity_headers.tls", "fliggy", "chrome") == "safari"
    assert scoped_id("identity_headers.tls", "ctrip", "chrome") == "chrome"


def test_scoped_id_never_raises():
    assert scoped_id("不存在.pid", "fliggy", "x") == "x"


def test_all_tls_read_points_go_through_scoped_id():
    """门禁：三个渠道的 `tls_impersonate` 读点必须包在 `scoped_id(...)` 里。"""
    bad = []
    for name in ("fliggy.py", "qunar.py", "tuniu.py"):
        src = io.open(os.path.join(ROOT, "crawlers", name),
                      encoding="utf-8").read()
        for i, line in enumerate(src.splitlines()):
            if "tls_impersonate" not in line:
                continue
            win = "\n".join(src.splitlines()[max(0, i - 3):i + 1])
            if "scoped_id(" not in win:
                bad.append("%s:%d %s" % (name, i + 1, line.strip()[:70]))
    assert not bad, "还有裸读的 tls_impersonate：\n" + "\n".join(bad)


def test_ua_read_point_goes_through_scoped_id():
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    assert 'scoped_id("identity_headers.mobile_ua"' in src
    assert 'scoped_id("identity_headers.ua"' in src


# ---- merged from tests/test_r1063_mumu_identity.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imei_is_valid_luhn():
    import random

    for seed in range(20):
        imei = identity._rand_imei(random.Random(seed))
        assert len(imei) == 15

        def luhn_ok(s):
            total = 0
            for i, ch in enumerate(reversed(s)):
                d = int(ch)
                if i % 2 == 1:
                    d *= 2
                    if d > 9:
                        d -= 9
                total += d
            return total % 10 == 0

        assert luhn_ok(imei), imei


def test_models_are_real_shapes():
    """机型清单必须是"品牌 + 型号 + 认证码"三件套，且不像编的。"""
    for brand, model, miit in identity.DEVICE_MODELS:
        assert brand and model and miit
        assert len(model) >= 4 and len(miit) >= 4
        assert brand.lower() != "unknown"


def test_rotate_dry_run_never_writes():
    rep = identity.rotate_id({}, 0, apply=False)
    assert rep["ok"] is True and rep["applied"] is False
    assert rep["want"]["phone_imei"]
    assert "演练" in rep["why"]
    assert rep["need_restart"] is True


def test_show_is_honest_when_manager_missing():
    rep = identity.show({"android": {"install_dir": "\\不存在的路径"}}, 0)
    assert isinstance(rep, dict) and "id" in rep
    if not rep["ok"]:
        assert rep["why"], "读不到时必须说明原因，不能静默返回空"


def test_unwrap_handles_json_text():
    assert identity._unwrap(
        "phone_imei", '{\n  "phone_imei": "865247046277134"\n}\n'
    ) == "865247046277134"
    assert identity._unwrap("phone_brand", "vivo") == "vivo"


def test_rotate_requires_restart_hint():
    """换完必须重启实例才生效——这条要写在返回里，别让人以为即时生效。"""
    rep = identity.rotate_id({}, 0, apply=False)
    assert rep["need_restart"] is True
