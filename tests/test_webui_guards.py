# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_battery_audit.py
- tests/test_r1063_commit_integrity.py
- tests/test_r1063_docs_families.py
- tests/test_r1063_issue15_verify_and_update.py
- tests/test_r1063_maps_cloak_pack.py
- tests/test_r1063_no_dot_strip_guard.py
- tests/test_r1063_no_missing_methods.py
- tests/test_r1063_runtime_bugs.py
- tests/test_r672_no_write_endpoint_blocked_by_our_guard.py
- tests/test_r902_no_hardcoded_channel_count.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import ast
import glob
import io
import json
import logging
import os
import pytest
import re
import sys
import time
import webui
import zipfile

from core import update as U
from core.android import consistency as C, geo
from core.android.maps_cloak_pack import build_module, load_config
from core.strategy_contract import STRATEGIES
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_webui_guards.py ----

# ---- merged from tests/test_r1063_battery_audit.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_battery_voltage_low_is_flagged_as_unfixable():
    facts = {"soc_model": "SM8650", "cpuinfo_hardware":
             "Qualcomm Technologies, Inc SM8650",
             "board": "pineapple", "hardware": "qcom",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi",
             "battery_voltage": "0"}
    rep = C.audit(facts)
    bat = [i for i in rep["items"] if i["key"].startswith("battery.")]
    assert bat, rep
    assert bat[0]["level"] == "mid"
    assert "改不掉" in bat[0]["hint"], bat[0]


def test_normal_battery_is_silent():
    facts = {"soc_model": "SM8650", "battery_voltage": "4185"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert not any(k.startswith("battery.") for k in keys), keys


def test_collect_has_battery_fields_in_source():
    src = io.open(os.path.join(ROOT, "core", "android", "consistency.py"),
                  encoding="utf-8").read()
    for k in ("battery_voltage", "battery_temp", "battery_level", "battery_ac"):
        assert k in src, k


# ---- merged from tests/test_r1063_commit_integrity.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHECKS = [
    # —— 登录 / 核验（issue #15） ——
    ("webui.py", '_pv = dict(_SLOT_VERIFY.get(key)', "PC 槽位读核验结果"),
    ("webui.py", '"verified_at": _pv.get("at", "")', "PC 槽位暴露核验时间"),
    ("webui.py", '"detail": _pv.get("detail", "")', "PC 槽位暴露核验说明"),
    ("webui.py", '"page_ok": _st == "page_ok"', "PC 槽位 page_ok 标志"),
    ("webui.py", "classify_text(body, page_url, ignore_url=True)",
     "核验忽略 URL 启发式（否则永远判需登录）"),
    ("webui.py", "_surface_detail_ok", "端面明细可用判定"),
    ("webui.py", "detail_ok 抬成 available", "detail_ok 抬成 available"),
    ("webui.py", "_State.cfg = _live_cfg", "面板保存后同步配置快照"),
    # —— 升级 / 观测 / 建议 ——
    ("webui.py", "/api/update/check", "检查更新接口"),
    ("webui.py", "/api/update/apply", "一键升级接口"),
    ("webui.py", "/api/insight", "诊断视图接口"),
    ("webui.py", 'data["distance_advice"]', "距离建议进载荷"),
    ("webui.py", "advice_distance_min_n", "建议阈值可配"),
    ("webui.py", "srxDistJump", "建议可跳转"),
    ("webui.py", "PATH_HINT", "通路口径提示"),
    ("webui.py", "_updateLine", "更新提示行"),
    ("webui.py", "insightBox", "诊断视图容器"),
    # —— 采集侧 ——
    ("crawlers/challenge.py", "ignore_url", "classify_text 支持 ignore_url"),
    ("crawlers/app_zhixing.py", "dialog_open", "日历限频后明细自开弹层"),
    ("crawlers/app_zhixing.py", "_dump_detail_fail", "明细失败取证"),
    ("crawlers/app_zhixing.py", "_route_intl", "国际标记（不计连败）"),
    ("crawlers/app_zhixing_nav.py", "_reopened", "找不到格则重开弹层"),
    ("crawlers/app_zhixing_nav.py", "1300, 450, 500",
     "日历滚动方向（上划看更早）"),
    ("crawlers/tongcheng.py", "_today_override", "窗历今天接缝"),
    # —— 工具 / 核心 ——
    ("core/update.py", 'while rel.startswith("./")', "_skip 归一化不用 lstrip"),
    ("tools/verify_release_assets.py", 'while low.startswith("./")',
     "发布包禁止项归一化"),
    ("core/advise.py", "def distance_advice", "距离建议实现"),
]


def test_all_tonight_fixes_are_present():
    missing = []
    for path, mark, desc in CHECKS:
        p = os.path.join(ROOT, path)
        try:
            # W3 模板外置：webui.py 读回填同构全文（模板词面在场）
            src = webui_full_src() if path == "webui.py"                 else io.open(p, encoding="utf-8").read()
        except OSError:
            missing.append("%s 不存在" % path)
            continue
        if mark not in src:
            missing.append("%s 缺 %r（%s）" % (path, mark, desc))
    assert not missing, "提交里缺了今晚的修复片段（分批暂存丢过）：\n  " + \
        "\n  ".join(missing)


# ---- merged from tests/test_r1063_docs_families.py ----

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "STRATEGY_CONTROL_PLANE.md")


def _doc_families():
    """从文档的族速查表里解出 `{族: [成员 id...]}`。"""
    txt = io.open(DOC, encoding="utf-8").read()
    i = txt.index("| 族 | 条数 |")
    j = txt.index("\n\n", i)
    out = {}
    for line in txt[i:j].splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("族",):
            continue
        fam, _n, _what, members = cells[0], cells[1], cells[2], cells[3]
        ids = [x.strip() for x in members.split(",") if x.strip()]
        out[fam] = ids
    return out


def test_doc_family_table_matches_the_catalog():
    cat = {}
    for s in STRATEGIES:
        cat.setdefault(s.family, []).append(s.id)
    doc = _doc_families()
    assert doc, "文档里没找到族速查表"
    assert set(doc) == set(cat), (
        "族的集合不一致：文档多 %s / 目录多 %s"
        % (sorted(set(doc) - set(cat)), sorted(set(cat) - set(doc))))
    for fam, ids in cat.items():
        assert doc[fam] == ids, (
            "族 %s 的成员不一致：\n文档 %s\n目录 %s" % (fam, doc[fam], ids))


def test_doc_counts_match():
    txt = io.open(DOC, encoding="utf-8").read()
    n_doc = len(_doc_families())
    n_cat = len({s.family for s in STRATEGIES})
    assert n_doc == n_cat
    assert ("%d 条" % len(STRATEGIES)) in txt, (
        "文档里没写当前策略总条数（%d）" % len(STRATEGIES))


def test_doc_lists_the_real_commands():
    txt = io.open(DOC, encoding="utf-8").read()
    for cmd in ("python -m core.strategy_contract --strict",
                "python -m core.fp_audit",
                "python -m core.cfg_snapshot"):
        assert cmd in txt, cmd


def test_doc_states_the_risk_boundaries():
    """行为型不自动解、换道有边界、调快＝风控代价——这三条必须写在文档里。"""
    txt = io.open(DOC, encoding="utf-8").read()
    for kw in ("风险边界", "行为分布", "每日上限", "风控代价"):
        assert kw in txt, kw


def test_doc_mentions_all_four_scopes():
    txt = io.open(DOC, encoding="utf-8").read()
    for sc in ("plat", "plat/dim", "plat/dim/path"):
        assert sc in txt, sc
    assert re.search(r"链路 → 维度 → 渠道", txt), "求值顺序没写"


# ---------------- 文案不许回潮（r1063 T41） ----------------

BANNED = ("交人工", "按性价比", "越算越像机器", "不必投入")


def test_no_restrictive_wording_in_any_doc():
    """用户明确要求：把限制这些设计的文案通通改掉。

    口径统一成「能力边界 + 范围决定」：图像型自动尝试，行为型不纳入自动尝试。
    「交人工 / 按性价比不投入 / 越算越像机器」这类**立场式禁令**不许再出现——
    它们既不是事实（点选是图像题，能自动做），也会误导接手的人。
    """
    import glob

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    for f in glob.glob(os.path.join(root, "docs", "*.md")):
        txt = io.open(f, encoding="utf-8").read()
        for w in BANNED:
            if w in txt:
                bad.append("%s：%s" % (os.path.basename(f), w))
    assert not bad, "文档里还有限制性表述：%s" % "、".join(bad)


# ---- merged from tests/test_r1063_issue15_verify_and_update.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(p):
    return io.open(os.path.join(ROOT, p), encoding="utf-8").read()


# ---------------- ① 核验结果必须在 PC 槽位可见 ----------------

def test_pc_slot_reads_verify_result():
    """PC 分支必须读核验结果（r1063 T250）。

    r1063 T310：**不再用"定位点后 N 字符"的窗口**——后续改动（T270 的状态抬升）
    会把目标行挤出窗口，导致本地绿、CI 红（窗口宽度依赖文件行距，太脆）。
    改为整文件断言 + 单独钉住定位点本身存在。
    """
    w = webui_full_src()
    assert "_pv = dict(_SLOT_VERIFY.get(key)" in w, "PC 分支必须读核验结果"
    assert '"verified_at": _pv.get("at", "")' in w, \
        "verified_at 不能继续写死空串"
    assert '"page_ok": _st == "page_ok"' in w


def test_frontend_shows_verified_time_and_renames_button():
    w = webui_full_src()
    assert "_vtxtSide" in w and "核验于 " in w, "槽位说明要显示核验时间"
    i = w.index("st==='page_ok' ? '再核验'")
    seg = w[i:i + 500]
    assert "上次核验：页面可达但未出数" in seg, "要说明为什么还要再点一次"


# ---------------- ② 检测更新 / 热更新 ----------------

def test_version_tuple_and_skip_rules():
    assert U._vtuple("v1.7.1") > U._vtuple("1.6.0")
    assert U._vtuple("1.6.0") > U._vtuple("v1.5.307")
    assert U._skip("user_data/x") and U._skip("data/prices.db")
    assert U._skip("config.yaml") is True, "升级绝不能覆盖用户配置"
    assert U._skip("core/update.py") is False


def test_parse_rolling_release_body():
    """滚动 release：tag 恒为 v1.0，真实版本/源码在正文。"""
    body = ("**当前版本：1.6.0 · 源码 16b54ea20eff39b42ced8505cbab67c631faec76"
            " · 2026-11-09**")
    assert U._parse_release_version(body) == "1.6.0"
    assert U._parse_release_commit(body).startswith("16b54ea")


def test_local_commit_reports_source():
    h, src = U.local_commit()
    assert src in ("git", "build", ""), src
    if src == "git":
        assert len(h) >= 7


def _fake_releases(body_ver="1.6.0", commit="deadbeefcafe", tag="v1.0"):
    body = "当前版本：%s · 源码 %s · 2026-11-09" % (body_ver, commit)
    return json.dumps([{"tag_name": tag, "body": body, "draft": False,
                        "prerelease": False, "html_url": "https://x/y",
                        "published_at": "2026-11-09", "assets": []}])


def test_check_new_version(monkeypatch):
    monkeypatch.setattr(U, "local_version", lambda: "1.5.0")
    monkeypatch.setattr(U, "local_commit", lambda: ("deadbeefcafe", "build"))
    monkeypatch.setattr(U, "_get", lambda *a, **k: (
        _fake_releases(body_ver="1.6.0").encode(), "fake"))
    monkeypatch.setattr(U, "_save_cache", lambda rec: None)
    r = U.check(force=True)
    assert r["ok"] and r["has_update"], r
    assert r["latest"] == "v1.6.0", r


def test_same_version_new_build_only_for_packaged(monkeypatch):
    """同版本 + 打包安装 + 源码不同 → 有新构建；开发树不算。"""
    monkeypatch.setattr(U, "local_version", lambda: "1.6.0")
    monkeypatch.setattr(U, "_save_cache", lambda rec: None)
    monkeypatch.setattr(U, "_get", lambda *a, **k: (
        _fake_releases(body_ver="1.6.0", commit="aaaabbbbcccc").encode(),
        "fake"))
    monkeypatch.setattr(U, "local_commit", lambda: ("aaaabbbbcccc", "build"))
    assert U.check(force=True)["has_update"] is False, "源码相同不该报有更新"
    monkeypatch.setattr(U, "local_commit", lambda: ("111122223333", "build"))
    assert U.check(force=True)["has_update"] is True, "打包安装源码不同＝有新构建"
    monkeypatch.setattr(U, "local_commit", lambda: ("111122223333", "git"))
    assert U.check(force=True)["has_update"] is False, "开发树不按提交比"


def test_apply_skips_user_data(tmp_path, monkeypatch):
    assert U._skip("user_data/app_zhixing/x.json")
    assert U._skip("data/prices.db")
    assert U._skip("logs/monitor.log")
    assert U._skip("debug/raw.json")

def _fake_release_with_assets(body_ver="1.6.0", tag="v1.0"):
    import json
    body = "当前版本：%s · 源码 deadbeefcafe · 2026-11-10" % body_ver
    assets = [
        {"name": "SHA256SUMS.txt",
         "browser_download_url": "https://x/SHA256SUMS.txt"},
        {"name": "ticket-monitoring-linux-x64.zip",
         "browser_download_url": "https://x/linux.zip"},
        {"name": "ticket-monitoring-win64.zip",
         "browser_download_url": "https://x/win.zip"},
    ]
    return json.dumps([{"tag_name": tag, "body": body, "draft": False,
                        "prerelease": False, "html_url": "https://x/rel",
                        "published_at": "2026-11-10", "assets": assets}])


def test_old_version_gets_update_with_zip(monkeypatch):
    """主路径：本机 1.5.x，仓库已发 1.6.0 → 应报有更新且给出**与部署形态相符**的资产。

    r1261 口径：`check()` 现在显式按 `deploy_mode()` 选资产——
    源码部署要的是源码包（zipball），发行部署才优先 windows 包。
    旧断言"永远优先 win.zip"正是 r1209 那个 bug 的一半（源码部署被喂了 exe 包）。
    """
    monkeypatch.setattr(U, "local_version", lambda: "1.5.307")
    monkeypatch.setattr(U, "_save_cache", lambda rec: None)
    monkeypatch.setattr(U, "_get", lambda *a, **k: (
        _fake_release_with_assets().encode(), "fake"))
    r = U.check(force=True)
    assert r["ok"] and r["has_update"], r
    assert r["latest"] == "v1.6.0", r
    # 夹具里既没有 source 资产、也没有 zipball_url → 退回普通 zip（linux.zip）
    assert r["zip"].endswith(".zip"), "应当仍给出一个可下载的 zip：%r" % r.get("zip")
    # 发行部署下才优先 windows 包（这是 `_pick_zip(rel, "binary")` 的契约）
    rel = {"assets": [
        {"name": "ticket-monitoring-linux.zip",
         "browser_download_url": "https://x/linux.zip"},
        {"name": "ticket-monitoring-win64.zip",
         "browser_download_url": "https://x/win.zip"}]}
    assert U._pick_zip(rel, "binary").endswith("win.zip")
    assert "1.6.0" in r["reason"]


def test_pick_zip_falls_back_when_no_win_asset():
    rel = {"assets": [{"name": "a.zip", "browser_download_url": "https://x/a.zip"},
                      {"name": "readme.txt", "browser_download_url": "https://x/r"}]}
    assert U._pick_zip(rel) == "https://x/a.zip"
    assert U._pick_zip({"assets": []}) == ""


# ---- merged from tests/test_r1063_maps_cloak_pack.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOOD = {"enabled": True, "packages": ["com.taobao.trip"],
        "markers": ["houdini", "nemu"]}


def _cfg(tmp_path, obj):
    p = tmp_path / "global.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_load_config_ok(tmp_path):
    got = load_config(_cfg(tmp_path, GOOD))
    assert got["packages"] == ["com.taobao.trip"]
    assert got["markers"] == ["houdini", "nemu"]


def test_load_config_rejects_missing_markers(tmp_path):
    with pytest.raises(ValueError):
        load_config(_cfg(tmp_path, {"enabled": True,
                                    "packages": ["com.taobao.trip"]}))


def test_load_config_rejects_missing_packages(tmp_path):
    with pytest.raises(ValueError):
        load_config(_cfg(tmp_path, {"enabled": True, "markers": ["houdini"]}))


def test_load_config_rejects_empty_markers(tmp_path):
    """空词表 = 过滤器不删任何行 = 静默失效，必须拒绝。"""
    with pytest.raises(ValueError):
        load_config(_cfg(tmp_path, {"enabled": True,
                                    "packages": ["a"], "markers": []}))


def test_build_module_layout(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    names = set(zipfile.ZipFile(out).namelist())
    assert {"module.prop", "zygisk/arm64-v8a.so", "zygisk/x86_64.so",
            "config/global.json"} <= names, names


def test_module_prop_has_required_keys(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    prop = zipfile.ZipFile(out).read("module.prop").decode("utf-8")
    for key in ("id=tm_maps_cloak", "name=", "version=", "description="):
        assert key in prop, prop


def test_config_inside_zip_matches_input(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    got = json.loads(zipfile.ZipFile(out).read("config/global.json")
                     .decode("utf-8"))
    assert got == GOOD


def test_build_requires_both_abis(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    with pytest.raises(ValueError):
        build_module(str(tmp_path / "o.zip"), {"arm64-v8a": str(so)}, GOOD)

def test_zip_contains_service_sh_and_packages_list(tmp_path):
    """开机自动生效的两件东西必须在包里：service.sh 与 packages.list。"""
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    z = zipfile.ZipFile(out)
    names = set(z.namelist())
    assert {"service.sh", "config/packages.list"} <= names, names
    svc = z.read("service.sh").decode("utf-8")
    assert "setprop wrap.$pkg" in svc
    assert "/data/adb/modules" in svc and "disable" in svc
    assert z.read("config/packages.list").decode().strip() == "com.taobao.trip"


# ---- merged from tests/test_r1063_no_dot_strip_guard.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("core/*.py", "crawlers/*.py", "tools/*.py", "scripts/*.py",
        "*.py")


def _strip_calls(tree):
    """产出 (行号, 参数字符串)：所有 `.lstrip(...)` / `.strip(...)` 调用。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute):
            continue
        if fn.attr not in ("lstrip", "strip", "rstrip"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield node.lineno, fn.attr, arg.value


def test_no_dot_stripping_normalisation():
    bad = []
    for pat in SCAN:
        for path in glob.glob(os.path.join(ROOT, pat)):
            if os.sep + "_scratch" + os.sep in path:
                continue
            try:
                src = open(path, encoding="utf-8").read()
                tree = ast.parse(src)
            except Exception:
                continue
            for lineno, meth, chars in _strip_calls(tree):
                # 危险特征：参数里含 "./" 或以 "." 开头（会剥掉 .git/.env 的点）
                if "./" in chars or (chars.startswith(".") and "/" in chars):
                    bad.append("%s:%d  .%s(%r)"
                               % (os.path.relpath(path, ROOT), lineno,
                                  meth, chars))
    assert not bad, ("禁止用 lstrip/strip 剥 './'（会静默破坏 .git/.env 等保护）；"
                     "改用 while startswith('./') 循环：\n  " + "\n  ".join(bad))


def test_guard_detects_the_pattern():
    """负控：守卫自己必须能识别这种写法（否则门禁是摆设）。"""
    src = ("import os\n"
           "def f(p):\n"
           "    return p.lstrip('./')\n")
    found = list(_strip_calls(ast.parse(src)))
    assert found and found[0][2] == "./", found


# ---- merged from tests/test_r1063_no_missing_methods.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "crawlers")


def _classes(files):
    out = {}
    for path in files:
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {n.name for n in node.body
                       if isinstance(n, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))}
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            rec = out.setdefault(node.name, {"methods": set(), "bases": [],
                                             "file": path})
            rec["methods"] |= methods
            rec["bases"] += bases
    return out


def _all_methods(name, classes, seen=None):
    seen = set() if seen is None else seen
    if name in seen or name not in classes:
        return set()
    seen.add(name)
    got = set(classes[name]["methods"])
    for b in classes[name]["bases"]:
        got |= _all_methods(b, classes, seen)
    return got


def _files():
    out = []
    for base, _dirs, names in os.walk(PKG):
        for n in names:
            if n.endswith(".py"):
                out.append(os.path.join(base, n))
    return out


def test_no_missing_self_method_calls():
    files = _files()
    assert files, "没扫到 crawlers/ 下的文件"
    classes = _classes(files)
    bad = []
    for path in files:
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            have = _all_methods(node.name, classes)
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                if not (isinstance(fn, ast.Attribute)
                        and isinstance(fn.value, ast.Name)
                        and fn.value.id == "self"):
                    continue
                if fn.attr in have or fn.attr.startswith("__"):
                    continue
                bad.append("%s:%d %s.%s()"
                           % (os.path.basename(path), sub.lineno, node.name,
                              fn.attr))
    assert not bad, ("这些 self.x() 在本类与继承链里都找不到定义——"
                     "只会在运行时炸，而且往往只走某条分支才炸：\n  "
                     + "\n  ".join(sorted(set(bad))))


def test_far_date_guard_exists_on_the_app_base():
    """飞猪 App 一进门就调 `reject_far_dates`：基类必须有它（HEAD 曾缺失）。"""
    src = io.open(os.path.join(PKG, "app_base.py"), encoding="utf-8").read()
    assert "def reject_far_dates(" in src
    assert "date_horizon_days" in src
    i = src.index("def reject_far_dates(")
    seg = src[i:i + 1200]
    assert "unsupported" in seg, "超视野的日期要记 unsupported，不能记失败"


# ---- merged from tests/test_r1063_runtime_bugs.py ----

@pytest.fixture(autouse=True)
def _reset():
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    QunarCrawler._WAIT_BACKOFF_STREAK = 0
    yield
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    QunarCrawler._WAIT_BACKOFF_STREAK = 0


def test_wait_backoff_escalates_and_caps():
    c = QunarCrawler({}, logging.getLogger("t59"))
    seen = [c._open_wait_backoff() for _ in range(8)]
    # r952 起窗口按 1x/2x/3x 增长（默认 1200s 起步、3600s 封顶）；
    # 旧的 15/30/60/600 固定梯已在 r952 废弃。
    assert seen[:4] == [1200, 2400, 3600, 3600], seen
    assert max(seen) <= QunarCrawler.WAIT_BACKOFF_MAX_S
    assert QunarCrawler._WAIT_BACKOFF_UNTIL > time.time()


def test_wait_backoff_resets_when_data_returns():
    c = QunarCrawler({}, logging.getLogger("t59"))
    c._open_wait_backoff()
    c._reset_wait_backoff()
    assert QunarCrawler._WAIT_BACKOFF_STREAK == 0
    assert QunarCrawler._WAIT_BACKOFF_UNTIL == 0.0


class _ShDevice:
    """真实 `AdbDevice` 的形状：只有 `_sh(*args)`。"""

    def __init__(self):
        self.calls = []

    def _sh(self, *args, timeout=None):
        self.calls.append(" ".join(str(a) for a in args))
        return "OK"


class _ScriptDevice:
    """只有 `run_script(script)` 的瘦设备。"""

    def __init__(self):
        self.calls = []

    def run_script(self, script, timeout=None):
        self.calls.append(str(script))
        return "OK"


def test_geo_uses_the_real_device_api():
    dev = _ShDevice()
    rep = geo.fix(dev, {"android": {"geo": {"enabled": True}}})
    assert rep["ok"] is True, rep
    joined = " | ".join(dev.calls)
    # 经度在前（写反就钉到海里）
    assert "emu geo fix 121.4921 31.1874" in joined, joined
    assert "location_mode 3" in joined, joined


def test_geo_falls_back_to_run_script_for_shell_commands():
    dev = _ScriptDevice()
    rep = geo.fix(dev, None)
    # emu 命令走不了 run_script（不是 shell 形式），但定位开关应该尽力打开
    assert any("location_mode 3" in c for c in dev.calls), dev.calls
    assert rep.get("providers") is True, rep


def test_geo_reports_a_clear_error_when_the_device_has_no_adb():
    class Bad:
        pass

    rep = geo.fix(Bad(), None)
    assert rep["ok"] is False
    assert "adb" in str(rep.get("detail") or ""), rep


# ---- merged from tests/test_r672_no_write_endpoint_blocked_by_our_guard.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BLOCKED = (403, 415)


def _endpoints():
    src = webui_full_src()
    eps = set()
    for m in re.finditer(r"fetch\('(/api/[^']*)',\s*\{\s*method:\s*'POST'",
                         src):
        eps.add(m.group(1))
    # 拼接式：fetch('/api/'+act, {method:'POST'}) —— 取 act 的全部字面量
    for m in re.finditer(r"fetch\('/api/'\+act,\s*\{\s*method:\s*'POST'", src):
        for lit in re.finditer(r"act\s*=\s*'([a-z-]+)'", src):
            eps.add("/api/" + lit.group(1))
    return sorted(eps)


def test_endpoint_census_is_not_empty():
    eps = _endpoints()
    assert len(eps) >= 20, "端点清单只扫到 %d 个，判据失效：%s" % (len(eps), eps)


@pytest.fixture(scope="module")
def live():
    import shutil
    import socket
    import tempfile
    import time
    import urllib.request

    import webui

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp(prefix="r672_")
    cfg = os.path.join(tmp, "c.yaml")
    # 复制到临时目录：任何写配置的端点都不许碰仓库里的配置文件
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg)
    # 强制回环监听；夹具退出时**必须**还原——直接赋值会永久改掉模块属性，
    # 后续 test_r675 的「TM_WEB_HOST 生效」断言会读到替身而恒得 127.0.0.1。
    old_bind = webui._bind_host
    webui._bind_host = lambda c: "127.0.0.1"
    try:
        webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                        job=None, report_push=None, config_path=cfg)
    except Exception:
        webui._bind_host = old_bind
        raise
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(160):
        try:
            op.open(base + "/api/state", timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip("控制台未在期限内起来")
    yield base
    _w = sys.modules.get("webui")
    if _w is not None:
        _w._bind_host = old_bind
    shutil.rmtree(tmp, ignore_errors=True)




# ---- merged from tests/test_r902_no_hardcoded_channel_count.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAGE = webui.PAGE


def _strip_comments(src: str) -> str:
    """剥掉 /* */ 与 // 行注释（只处理 JS/CSS 风格，够用）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out = []
    for line in src.split("\n"):
        # 只剥「整行以 // 开头」与「代码后面的 // 注释」，跳过 http://
        if line.strip().startswith("//"):
            continue
        out.append(re.sub(r"(?<![:\w])//.*$", "", line))
    return "\n".join(out)


BODY = _strip_comments(PAGE)


def test_no_hardcoded_channel_count_in_visible_copy():
    bad = []
    # 同类写死还有「四渠道 / 四平台」——接入 App 后同样过期。
    # 注意「四源」不在此列：它是一个**视图名**（four 视图把四种来源形态并排），
    # 不是渠道数量，扫进来会造出与渠道数无关的假红。
    for pat in ("五渠道", "五平台", "七个渠道", "七渠道",
                "四渠道", "四平台"):
        for m in re.finditer(re.escape(pat), BODY):
            ctx = BODY[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
            bad.append("%s ← ...%s..." % (pat, ctx))
    assert not bad, (
        "界面文案写死了渠道数量（渠道数会随接入变化，应写「所选渠道/全部渠道」"
        "或按实际数量动态拼）：\n" + "\n".join(bad[:6]))


def test_coverage_denominator_is_not_a_literal_five():
    """渠道覆盖类读数：分母不许是字面量 5。"""
    assert "dataPlats+'/5'" not in BODY, "渠道覆盖分母仍写死 5（7 家时会出现 7/5）"
    assert "dataPlats/5*100" not in BODY, "渠道覆盖百分比仍写死分母 5"


def test_probe_result_renders_every_channel_with_data():
    """探针结果按**数据里的渠道集合**渲染，而不是每渠道白名单过滤。"""
    assert "SRX_PLAT_ORDER.filter(p=>(j.channels||{})[p])" not in BODY, (
        "探针结果仍用固定渠道表过滤——App 渠道的产物永远不会显示")
    assert "SRX_PLAT_ORDER.filter(p=>(lg.channels||{})[p])" not in BODY, (
        "组合探针结果仍用固定渠道表过滤，App 渠道结果会被丢掉")
