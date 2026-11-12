# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1067_fetch_packages.py
- tests/test_r1628_disabled_channel_row.py
- tests/test_r1778_flush_on_collect.py
- tests/test_r1819_horizon_doc.py
- tests/test_r292_login_watch.py
- tests/test_r556_collapsed_filter_no_residue.py
- tests/test_r563_watch_expand_button_no_shift.py
- tests/test_r653_first_run_guidance.py
- tests/test_r805t_tongcheng_pc_pacing.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import importlib.util
import io
import os
import pathlib
import re
import sys
import zipfile

from pathlib import Path


# ---- merged from tests/test_r1067_fetch_packages.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    p = os.path.join(ROOT, "scripts", "fetch_packages.py")
    spec = importlib.util.spec_from_file_location("fetch_packages", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _mkzip(tmp_path, entries):
    p = os.path.join(str(tmp_path), "m.zip")
    with zipfile.ZipFile(p, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return p


def test_packages_meta_complete():
    """清单里每个包都必须钉死 url/sha256/size/kind。"""
    m = _mod()
    assert m.PACKAGES
    for name, meta in m.PACKAGES.items():
        assert meta["url"].startswith("https://github.com/"), name
        assert len(meta["sha256"]) == 64, name
        assert meta["size"] > 0, name
        assert meta["kind"] in ("zygisk", "zygisk_impl"), name
        assert meta.get("note"), name


def test_valid_zygisk_module(tmp_path):
    m = _mod()
    p = _mkzip(tmp_path, {"module.prop": "id=x",
                          "zygisk/x86_64.so": b"\x7fELF"})
    ok, why = m.validate_zip(p, "zygisk")
    assert ok, why


def test_module_missing_zygisk_so_is_rejected(tmp_path):
    m = _mod()
    p = _mkzip(tmp_path, {"module.prop": "id=x", "service.sh": "echo"})
    ok, why = m.validate_zip(p, "zygisk")
    assert not ok and "zygisk" in why


def test_zygisk_impl_layout_is_accepted(tmp_path):
    """NeoZygisk 这类实现把库放在 lib/<abi>/libzygisk*.so，不是 zygisk/。"""
    m = _mod()
    p = _mkzip(tmp_path, {"module.prop": "id=zygisksu",
                          "lib/x86_64/libzygisk.so": b"\x7fELF"})
    ok, why = m.validate_zip(p, "zygisk_impl")
    assert ok, why
    # 用错 kind 要判错（这正是真机上踩到的第一版 bug）
    ok2, why2 = m.validate_zip(p, "zygisk")
    assert not ok2, "实现包不应被当成普通 zygisk 模块"


def test_html_error_page_is_rejected(tmp_path):
    """GitHub 出错时可能返回 HTML；不能当 zip 收下。"""
    m = _mod()
    p = os.path.join(str(tmp_path), "err.zip")
    io.open(p, "wb").write(b"<html>rate limited</html>")
    ok, why = m.validate_zip(p, "zygisk")
    assert not ok and "zip" in why.lower()


def test_missing_module_prop_is_rejected(tmp_path):
    m = _mod()
    p = _mkzip(tmp_path, {"zygisk/x86_64.so": b"\x7fELF"})
    ok, why = m.validate_zip(p, "zygisk")
    assert not ok and "module.prop" in why


def test_verify_file_size_and_sha(tmp_path):
    m = _mod()
    p = os.path.join(str(tmp_path), "a.bin")
    io.open(p, "wb").write(b"hello")
    import hashlib
    sha = hashlib.sha256(b"hello").hexdigest()
    ok, _ = m.verify_file(p, {"sha256": sha, "size": 5})
    assert ok
    ok, why = m.verify_file(p, {"sha256": sha, "size": 6})
    assert not ok and "大小" in why
    ok, why = m.verify_file(p, {"sha256": "0" * 64, "size": 5})
    assert not ok and "SHA256" in why
    ok, why = m.verify_file(os.path.join(str(tmp_path), "nope"),
                            {"sha256": sha, "size": 5})
    assert not ok and why == "缺失"


# ---- merged from tests/test_r1628_disabled_channel_row.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w(name="webui.py"):
    if name == "webui.py":
        return webui_full_src()   # W3 模板外置：回填同构全文
    return io.open(os.path.join(ROOT, name), encoding="utf-8", newline="").read()


def test_backend_advice_knows_enabled_list():
    s = _w("core/pacing.py")
    assert "enabled=None" in s, "advise 没有 enabled 参数"
    assert '"state": "disabled"' in s, "没有「不在清单」这个状态"
    assert "不在你的采集清单" in s, "没有对应的中文结论"


def test_webui_passes_enabled():
    s = _w()
    assert "enabled=_enabled_plats()" in s, "调用 advise 时没传采集清单"
    assert "def _enabled_plats(" in s, "缺少 _enabled_plats()"


def test_row_renders_disabled_state():
    s = _w()
    assert "adv.state==='disabled'" in s, \
        "节流行没处理 disabled：会落进默认分支写「正常」，与右侧 0% 自相矛盾"
    assert "未在清单" in s, "没有「未在清单」这个行文案"


# ---- merged from tests/test_r1778_flush_on_collect.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                   newline="").read()


def test_flush_helper_exists_and_is_called_per_channel():
    s = _src()
    assert "def _flush_now(" in s, "没有即时落库助手"
    i = s.index("all_prices.extend(prices)")
    assert "_flush_now(prices)" in s[i:i + 200], "渠道完成时没有即时写"


def test_failover_rows_also_flushed():
    s = _src()
    i = s.index("all_prices.extend(_pr2 or [])")
    assert "_flush_now(_pr2 or [])" in s[i:i + 200], "换道回采的行没有即时写"


def test_tail_write_only_writes_unwritten():
    s = _src()
    assert "_wrote_ids" in s, "没有已写集合"
    i = s.index("all_prices = _stable_pool(all_prices)")
    seg = s[i:i + 400]
    assert "_wrote_ids" in seg, "轮尾仍整批重写（会重复入库）"
    assert "save_many(_rest)" in seg, "轮尾没有改成只补未写的"


# ---- merged from tests/test_r1819_horizon_doc.py ----
# W2b 段3：docs/DISPATCH_HORIZON.md 已删（W1），本段 3 个用例随之删除。


# ---- merged from tests/test_r292_login_watch.py ----

SRC = Path(__file__).resolve().parent.parent / "webui.py"
src = webui_full_src()


def _switch_body():
    i = src.index("function switchView")
    j = src.index("async function loadLogin")
    return src[i:j]


def _watch_body():
    i = src.index("function lgWatchStart")
    j = src.index("async function loginStart")
    return src[i:j]


def test_switchview_starts_login_watch_on_cfg_login():
    assert "if(v==='cfg'&&CFGPANEL==='login')lgWatchStart();" in _switch_body(), \
        "switchView 进配置视图停登录分区未拉起登录轮询（P2-1 主路径缺口）"


def test_switchview_stops_login_watch_leaving_cfg():
    assert "lgWatchStop();" in _switch_body(), \
        "switchView 切回监控视图未停登录轮询（跨视图常驻）"


def test_lgwatchstop_single_source():
    assert "function lgWatchStop(){if(LGTIMER){clearInterval(LGTIMER);LGTIMER='';}}" in src, \
        "lgWatchStop 单源停点缺席"
    assert "else lgWatchStop();" in _watch_body(), \
        "interval 自灭分支未走 lgWatchStop 单源（停点分叉）"


# ---- merged from tests/test_r556_collapsed_filter_no_residue.py ----

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = webui_full_src()


def _collapsed_rule():
    m = re.search(
        r"#searchview \.srx-context\.ctx-collapsed \.srx-abar\{([^}]*)\}", TEXT)
    assert m, "缺少 .ctx-collapsed .srx-abar 规则——收起态会残留结果筛选行"
    return m.group(1)


def test_collapsed_filter_hides_result_bar():
    body = _collapsed_rule()
    assert "display:none" in body.replace(" ", ""), body


def test_result_bar_rule_sits_in_collapse_block():
    """必须在同一条「收起态」规则组里，而不是散落别处被后面的规则盖掉。"""
    i = TEXT.index("#searchview .srx-context.ctx-collapsed .srx-line:nth-child(n+2)")
    j = TEXT.index("#searchview .srx-context.ctx-collapsed .srx-abar")
    assert 0 < j - i < 900, (i, j)
    assert j > i


def test_selected_date_still_visible_when_bar_hidden():
    """收起后所选日期仍可读：列表头写「所选 YYYY-MM-DD」，按钮有数量徽标。"""
    assert "所选 '" in TEXT or "所选 " in TEXT
    tail = TEXT[TEXT.index("function srxRenderCtx()"):]
    tail = tail[:tail.index("function ", 10)]
    assert "srxCtxCount()" in tail
    assert "SRX.date" in TEXT[TEXT.index("function srxCtxCount()"):][:400]


# ---- merged from tests/test_r563_watch_expand_button_no_shift.py ----

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = webui_full_src()


def _rule(sel):
    i = TEXT.index(sel)
    j = TEXT.index("}", TEXT.index("{", i))
    return re.sub(r"/\*.*?\*/", "", TEXT[i:j + 1], flags=re.S)


def _row_html():
    """取出拼装 .ws-row 的那段源码（从 `<article class="ws-row` 到 `</article>`）。"""
    i = TEXT.index('<article class="ws-row')
    j = TEXT.index("</article>'", i)
    return TEXT[i:j + len("</article>'")]


def _main_close(seg):
    """从 `class="ws-row-main"` 起，按 div 开/闭配对找它的闭合位置。"""
    start = seg.index('class="ws-row-main"')
    # 定位这个 div 的起始 '<div'
    open_at = seg.rindex("<div", 0, start)
    depth = 0
    i = open_at
    while i < len(seg):
        if seg.startswith("<div", i):
            depth += 1
            i += 4
            continue
        if seg.startswith("</div>", i):
            depth -= 1
            if depth == 0:
                return i
            i += 6
            continue
        i += 1
    raise AssertionError("未找到 .ws-row-main 的闭合标签")


def test_action_buttons_live_inside_main_row():
    """动作钮必须是 .ws-row-main 的后代，不能是 article 的子级。"""
    seg = _row_html()
    act_at = seg.index('class="ws-row-act"')
    close_main = _main_close(seg)
    assert act_at < close_main, (
        "动作钮仍在 .ws-row-main 之外——展开后会随 article 变高而下移")


def test_main_row_is_positioning_context():
    body = _rule(".ws-row-main{")
    assert "position:relative" in body.replace(" ", ""), body


def test_action_buttons_still_vertically_centred_on_main():
    body = _rule(".ws-row-act{")
    flat = body.replace(" ", "")
    assert "position:absolute" in flat, body
    assert "top:50%" in flat, body
    assert "translateY(-50%)" in flat, body


def test_detail_stays_outside_main_row():
    """展开体必须留在 article 层，不能被塞进内容行（否则行高会被撑开）。"""
    i = TEXT.index('class="ws-row-main"')
    j = TEXT.index("</article>", i)
    seg = TEXT[i:j]
    main_start = 0
    close_main = seg.index("</div>", seg.index('class="ws-row-act"'))
    detail_at = seg.index('class="ws-detail"')
    assert detail_at > close_main, "展开体被塞进了内容行"


# ---- merged from tests/test_r653_first_run_guidance.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                   newline="").read()


def test_first_run_prints_actionable_steps():
    """无航线分支要给出三步可执行动作，而不是只丢一个 URL。"""
    w = _src()
    i = w.index("首次使用：你的浏览器会自动打开配置页")
    seg = w[i - 200:i + 900]
    assert "用户与航线" in seg, "没告诉用户去哪加航线"
    assert "勾选" in seg and "智行 App" in seg, "没提渠道勾选（含 App）"
    assert "保存并生效" in seg, "没告诉用户保存后才开始"


def test_first_run_tries_to_open_browser():
    """要真的尝试打开浏览器；只打印 URL 等于让用户自己想办法。"""
    w = _src()
    assert "def _open_console(" in w, "缺少打开控制台的实现"
    assert "webbrowser" in w, "没有尝试调用系统浏览器"
    assert "_open_console(_url" in w or "_open_console(url" in w, \
        "首次引导分支没有调用 _open_console"


def test_open_console_failure_is_non_fatal(monkeypatch):
    """无桌面环境/浏览器调用失败时，不能让监控启动挂掉。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tm_main_probe", os.path.join(ROOT, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        return          # main.py 顶层可能提前退出，跳过该断言
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError))
    assert mod._open_console("http://127.0.0.1:1", None) is False


def test_open_console_respects_opt_out(monkeypatch):
    """TICKET_NO_OPEN 用于服务器/测试，必须完全不弹窗。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tm_main_probe2", os.path.join(ROOT, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        return
    called = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: called.append(1) or True)
    monkeypatch.setenv("TICKET_NO_OPEN", "1")
    assert mod._open_console("http://127.0.0.1:1", None) is False
    assert not called, "显式关闭时仍打开了浏览器"


# ---- merged from tests/test_r805t_tongcheng_pc_pacing.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fn(src, name, end_marker):
    i = src.index("    def %s(" % name)
    j = src.index(end_marker, i)
    return src[i:j]


def test_pc_path_sleeps_between_dates():
    src = io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                  encoding="utf-8").read()
    body = _fn(src, "_fetch_pc_dom", "\n    def _pick_lowest(")
    assert "self._sleep()" in body, (
        "PC 通路没有 _sleep()：多日期连打会自招风控，"
        "而账本会把风控记成「PC 不行」")
    # 必须在 for date 循环内——用缩进判断它处在循环体里
    loop = re.search(r"\n(\s+)for date in dates:", body)
    assert loop, "找不到日期循环，判据失效需重写"
    indent = loop.group(1)
    sleep_indents = [len(m.group(1)) for m in
                     re.finditer(r"\n(\s+)self\._sleep\(\)", body)]
    assert sleep_indents, "没有找到循环内的 _sleep()"
    assert min(sleep_indents) > len(indent), (
        "self._sleep() 在 for-date 循环**外**（缩进 %s vs 循环 %s）："
        "只睡一次等于多日期连打"
        % (min(sleep_indents), len(indent)))


def test_h5_path_still_sleeps():
    """H5 主循环的节流不能因为加了 PC 通路而被顺手删掉。"""
    src = io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                  encoding="utf-8").read()
    i = src.index("    def fetch(self, from_city: str, to_city: str,")
    j = src.index("\n    def ", i + 10)
    body = src[i:j]
    assert "self._sleep()" in body, "H5 主循环的 _sleep() 没了"
