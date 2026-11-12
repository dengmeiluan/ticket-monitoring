# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1844_no_relogin_nag.py
- tests/test_r523_no_unconfigurable_keys.py
- tests/test_r790_no_iterate_plat_order.py
- tests/test_r904_no_duplicate_literal_keys.py
- tests/test_r948_no_hot_prop_rewrite.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

from support_webui_src import webui_full_src

import ast
import io
import os
import pytest
import re
import sys


# ---- merged from tests/test_r1844_no_relogin_nag.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p():
    return io.open(os.path.join(ROOT, "core", "pacing.py"),
                   encoding="utf-8").read()


def test_no_relogin_after_last_success():
    """判据语义：**上次成功之后有没有再撞墙**（与时间无关）。

    第一版用「60 分钟内出过数」，但渠道轮询间隔就有 25–37 分钟，
    中间没轮到它超过一小时很正常——实测 10:05 又变回 relogin。
    """
    s = _p()
    assert "_ok_recent" in s, "没有「会话是通的」判据"
    i = s.index("_ok_recent = bool(")
    seg = s[i:i + 300]
    assert "_last_login" in seg and "_last_ok" in seg, "没有比较登录与成功时间"
    assert "<=" in seg, "比较方向缺失（last_login <= last_ok 才算通）"
    assert "and not _ok_recent" in s, "判据没有接到登录墙分支上"
    j = s.index("_last_login = str(")
    assert "_sv" in s[j:j + 200], "取的不是域节点（_sp 是域的 paths 字典）"


def test_route_level_branch_reports_scope_numbers():
    s = _p()
    i = s.index("属航线级拦截")
    seg = s[max(0, i - 900):i + 300]
    assert "_scope_okish" in seg, "航线级分支仍用本路径出数（会写「出数（0 次）」）"
    assert '其他通路仍在出数' in seg


def test_live_qunar_advice_not_asking_to_relogin():
    """真实载荷：刚出过数的渠道不该再给 relogin。"""
    import json
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/pacing",
                               timeout=25).read())
    except Exception:
        return
    row = (d.get("channels") or {}).get("app_qunar") or {}
    a = row.get("advice") or {}
    if not a:
        return
    hint = str(a.get("hint") or "")
    if "其他通路仍在出数（0 次）" in hint:
        raise AssertionError("又出现了自相矛盾的 0 次：" + hint)


# ---- merged from tests/test_r523_no_unconfigurable_keys.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_KEYS = ("session_max_days", "max_concurrency", "mobile_user_agent",
         "tls_impersonate", "debug_dir", "login_desktop",
         "login_cooldown_s", "near_days", "cadence")


def _w():
    return webui_full_src()


def test_every_key_has_an_editable_control():
    """控件必须真的**渲染**（`glcell(` 调用在场），而不只是有赋值表达式。

    负控踩过：把 `glcell('会话最长可用天数','glbSessMax'…)` 删掉后，
    `GLB.session_max_days=…` 这段 onchange 代码仍在源码里，只查赋值会全绿。
    """
    w = _w()
    # 1) 每个键都要有赋值表达式（onchange 的写回）
    handled = set(re.findall(r"GLB\.([a-zA-Z0-9_]+)\s*=", w))
    for k in _KEYS:
        assert k in handled, "配置页没有 %s 的写回表达式" % k
    # 2) 每个键都必须被某个 glcell 真正渲染出来——按**控件 id** 判定。
    #    负控踩过两次：删掉 glcell 后 ①`GLB.k=` 仍在 onchange 里、
    #    ②宽泛的正则还能匹配到别的 glcell，两次都假绿。控件 id 是唯一不变量。
    _ID = {"session_max_days": "glbSessMax", "max_concurrency": "glbMaxConc",
           "mobile_user_agent": "glbMua", "tls_impersonate": "glbTls",
           "debug_dir": "glbDbgDir", "login_desktop": "glbLgd",
           "login_cooldown_s": "glbLcd", "near_days": "glbNearD"}
    for k, cid in _ID.items():
        assert "'%s'" % cid in w, \
            "%s 没有渲染控件（找不到 id=%s）" % (k, cid)
    assert "'glbCad_'+p" in w or "glbCad_" in w, "cadence 控件缺失"


def test_config_page_no_longer_declares_any_key_readonly():
    """r521 的「仅可在 config.yaml 中修改」只读块必须撤掉。"""
    w = _w()
    assert "glnote('仅可在 config.yaml 中修改" not in w, \
        "仍有一块「只能改文件」的说明——按新要求这些项必须可配"


def test_every_key_is_actually_persisted():
    """控件只是前端；POST 必须真的写进 cfg 并落盘。"""
    w = _w()
    i = w.index('if self.path == "/api/config":')
    seg = w[i:i + 14000]
    # 逐个键确认出现在写入块里（含 cadence 的 dict 分发）
    for k in _KEYS:
        assert '"%s"' % k in seg, "保存路径没有写入 %s（改了存不进去）" % k


def test_every_key_is_read_back():
    """回读：保存后重开配置页要能看到自己设的值。"""
    w = _w()
    i = w.index('elif self.path == "/api/config":')
    seg = w[i:i + 13000]
    keys = set(re.findall(r'"([a-z_]+)":', seg))
    for k in _KEYS:
        assert k in keys, "/api/config 没有回读 %s" % k


def test_written_keys_are_hot_effective_not_startup_level():
    """这几项都不是启动级（启动级只有路径/host/run_on_start）。"""
    w = _w()
    i = w.index("def _startup_vals(")
    seg = w[i:i + 2600]
    for k in _KEYS:
        assert k not in seg, \
            "%s 被当成启动级却没有进重启中心（会静默不生效）" % k


def test_cadence_control_matches_backend_semantics():
    """cadence 的语义是「该渠道单独的最小采集间隔（分钟）」，整数。

    前端若按「倍率/小数」写，用户填 1.5 会被后端 `int()` 截成 1，
    控件与实际生效值对不上。两侧必须同口径：整数分钟、0..10080。
    """
    w = _w()
    i = w.index("GLB.cadence=Object.assign")
    seg = w[max(0, i - 260):i + 260]
    assert "parseInt(this.value)" in w[i:i + 260], \
        "cadence 控件没有按整数解析"
    assert "10080" in w[i:i + 260], "上限与后端不一致（后端 max 10080）"
    assert "parseFloat" not in w[i:i + 260], \
        "cadence 控件按小数解析，但后端 int() 会截断"
    assert "最小间隔" in seg, "标签没写清语义（应说明是「最小间隔 分钟」）"


def test_cadence_write_uses_the_same_clamp():
    w = _w()
    i = w.index('if isinstance(glb.get("cadence"), dict):')
    # 取整段写入逻辑到缩进回落到同级为止。原先钉 700 字符窗口，r630 给
    # 白名单补了 App 渠道（try/import 多出 6 行）后把 close 语句挤出窗口，
    # 变成「代码还在、断言够不着」的假红（门禁守意图，不守源码长度）。
    j = w.index("win_toast 缺省即开启", i)
    seg = w[i:j]
    assert "int(_cv)" in seg, "写入时没有按整数解析（与解析端 int() 不一致）"
    assert "10080" in seg, "写入上限与 core/pacing.py 不一致"


# ---- merged from tests/test_r790_no_iterate_plat_order.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")

# 按常量决定「有哪些渠道」的用法：一律禁止
FORBIDDEN = re.compile(
    r"SRX_PLAT_ORDER\s*\.\s*(forEach|map|filter|reduce|slice|concat)\s*\(")


def _lines():
    return webui_full_src().splitlines()


def _strip_comment(line: str) -> str:
    """去掉行内注释后再判——注释里提到这种写法是允许的（本文件的
    历史说明里就引用了 `SRX_PLAT_ORDER.filter(...)`）。"""
    s = line
    for opener in ("/*", "//"):
        i = s.find(opener)
        if i >= 0:
            s = s[:i]
    return s


def _code_lines():
    """返回 [(行号, 去注释后的代码)]。

    块注释要跨行跟踪：本文件的历史说明里就成段引用了
    `SRX_PLAT_ORDER.filter(...)` 这类旧写法（解释为什么改掉），
    按单行剥注释会把这些**续行**误判成真代码。
    """
    out, in_block = [], False
    for i, ln in enumerate(_lines(), 1):
        s = ln
        buf = ""
        while s:
            if in_block:
                j = s.find("*/")
                if j < 0:
                    s = ""
                    break
                s = s[j + 2:]
                in_block = False
            else:
                j = s.find("/*")
                k = s.find("//")
                if j >= 0 and (k < 0 or j < k):
                    buf += s[:j]
                    s = s[j + 2:]
                    in_block = True
                elif k >= 0:
                    buf += s[:k]
                    s = ""
                else:
                    buf += s
                    s = ""
        out.append((i, buf))
    return out


def test_no_for_each_over_the_five_channel_order():
    bad = []
    for i, code in _code_lines():
        if FORBIDDEN.search(code):
            bad.append((i, code.strip()[:100]))
    assert not bad, (
        "用 SRX_PLAT_ORDER 决定渠道集合会把两款 App 漏掉"
        "（它只有 5 家浏览器渠道）；集合应以数据/声明为准，它只用于排序：%s"
        % bad[:5])


def test_order_is_still_used_for_sorting():
    """反向守：排序仍要靠它——否则上面那条会被「干脆不用」绕过，
    渠道顺序又回到各处各排一套。"""
    src = webui_full_src()
    assert src.count("SRX_PLAT_ORDER.indexOf(") >= 3, (
        "SRX_PLAT_ORDER 应继续用于排序（indexOf 参与 sort 比较）")


def test_channel_set_comes_from_data_or_declaration():
    """正面守：产物条这类「列出渠道」的地方，集合来自数据或探针 want。"""
    src = webui_full_src()
    assert "_capPlats" in src, (
        "产物条的渠道集合应显式从数据/请求派生（_capPlats），而不是常量")


@pytest.mark.parametrize("needle", [
    "SRX_PLAT_ORDER.forEach(", "SRX_PLAT_ORDER.filter(",
    "SRX_PLAT_ORDER.map(",
])
def test_forbidden_patterns_are_actually_detectable(needle):
    """负控：确认正则真的能抓到自己禁止的写法（否则门禁恒绿）。"""
    assert FORBIDDEN.search("  const a = " + needle + "x=>x);"), needle


# ---- merged from tests/test_r904_no_duplicate_literal_keys.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOP_LEVEL = ("webui.py", "main.py", "report.py", "wizard.py")


def _product_files():
    files = [os.path.join(ROOT, name) for name in TOP_LEVEL
             if os.path.exists(os.path.join(ROOT, name))]
    for folder in ("core", "crawlers"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, folder)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            files.extend(os.path.join(dirpath, name)
                         for name in filenames if name.endswith(".py"))
    return sorted(files)


def _duplicates(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:  # {**spread}
                continue
            try:
                key = ast.literal_eval(key_node)
                hash(key)
            except Exception:
                continue
            if key in seen:
                out.append((key, seen[key], getattr(value_node, "lineno", "?")))
            else:
                seen[key] = getattr(key_node, "lineno", "?")
    return out


def test_no_duplicate_literal_keys_in_product_code():
    files = _product_files()
    assert len(files) >= 60, (
        "只扫到 %d 个产品文件，扫描根可能失效：%s" % (len(files), files[:5]))
    bad = []
    for path in files:
        for key, first, duplicate in _duplicates(path):
            bad.append("%s[%r] 首写行 %s / 覆盖行 %s"
                       % (os.path.relpath(path, ROOT), key, first, duplicate))
    assert not bad, (
        "重复字典键会静默覆盖前值：\n" + "\n".join(bad))


# ---- merged from tests/test_r948_no_hot_prop_rewrite.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _canary() -> str:
    return io.open(os.path.join(ROOT, "core", "android", "abi_canary.py"),
                   encoding="utf-8").read()


def _fp() -> str:
    return io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                   encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. 危险键黑名单必须在，且必须包含曾把设备搞挂的那几个
# ---------------------------------------------------------------------------
def test_no_delete_blocklist_exists():
    s = _canary()
    assert "_NO_DELETE" in s, "没有 delete 黑名单（会再次把设备搞挂）"
    seg = s[s.find("_NO_DELETE"):s.find("_NO_DELETE") + 900]
    for k in ("ro.adb.secure", "ro.serialno", "ro.boot.serialno",
              "ro.bootmode", "ro.boot.verifiedbootstate", "ro.bootloader"):
        assert k in seg, "黑名单缺 %s" % k


def test_no_delete_guard_applied():
    """delete-then-set 分支必须带 `k not in _NO_DELETE` 判定。"""
    s = _canary()
    assert "k not in _NO_DELETE" in s, "黑名单没真的生效"


def test_blocklist_records_both_incidents():
    """两处事故都要在注释里留痕（否则下次还会"值对就敢改"）。"""
    s = _canary() + _fp()
    assert "ro.adb.secure" in s and "offline" in s.replace(" ", "")
    assert "system_server" in s or "运行中" in s, \
        "没记录『值对也不能热改』这条认知"


# ---------------------------------------------------------------------------
# 2. 只允许改"没人运行时依赖"的键
# ---------------------------------------------------------------------------
def test_hot_write_guard_present():
    """必须有一道"运行中不许热改机型/构建字段"的闸。"""
    s = _canary()
    assert "_HOT_WRITE_SAFE" in s or "_NO_HOT_WRITE" in s, \
        "没有热改白名单/黑名单"


def test_hot_write_blocks_product_and_build():
    """`ro.product.device` / `ro.build.*` 这类必须被拦下并说明替代路径。"""
    s = _canary()
    i = s.find("_NO_HOT_WRITE =")
    if i < 0:
        i = s.find("_NO_HOT_WRITE")
    assert i > 0
    seg = s[i:i + 3200]
    assert "ro.product.device" in seg or "ro.product." in seg
    assert "phone_miit" in seg or "官方键" in seg, \
        "没指出正确路径（官方键 + 重启）"


# ---------------------------------------------------------------------------
# 3. `_magisk` 必须做 ro.* 探针（只看文件在不在会被静默失败骗）
# ---------------------------------------------------------------------------
def test_magisk_probe_uses_ro_key():
    s = _fp()
    i = s.find("def _magisk(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    assert "ro.boot.revision" in body, "探针没用 ro.* 键"
    assert "tmprobe" in body, "没有 delete-then-set 探针"
    # 明确记录 persist.* 不可当探针
    assert "persist." in body, "没记录『persist.* 能写不代表 ro.* 能写』"


def test_adb_path_candidates_include_mumu():
    """`as_root` 现在走 adb push，必须有 MuMu 的 adb 绝对路径。"""
    s = io.open(os.path.join(ROOT, "scripts", "magisk_bootstrap.py"),
                encoding="utf-8").read()
    assert "Netease\\MuMu" in s or "Netease/MuMu" in s, \
        "没带 MuMu adb 路径（裸 `adb` 会静默失败）"


# ---------------------------------------------------------------------------
# 4. as_root 不许再用管道/重定向（Windows 会被本地 shell 吃掉）
# ---------------------------------------------------------------------------
def test_as_root_avoids_pipe_and_redirect():
    """真正的调用参数里不许出现管道/重定向（docstring 提到它们是解释原因）。"""
    s = _fp()
    i = s.find("def as_root(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    # 只看传给 _call / sh 的实际参数行
    for ln in body.splitlines():
        code = ln.split("#", 1)[0]
        if "_call(" in code or '"shell"' in code:
            assert "| base64 -d | sh" not in code, \
                "还在用管道（Windows 上 stdout 会丢）：%s" % code.strip()
            assert " > " not in code, \
                "实际参数里还有重定向：%s" % code.strip()
    assert "push" in body and "mkstemp" in body, "没走 adb push 方案"
