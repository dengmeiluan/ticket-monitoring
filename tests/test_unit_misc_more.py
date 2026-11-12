# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1056_fliggy_reset_probe.py
- tests/test_r1179_err_codes_page.py
- tests/test_r1303_stale_tab_build_stamp.py
- tests/test_r1310_gutter_and_anchor.py
- tests/test_r1721_advice_states_covered.py
- tests/test_r1783_parked_apps.py
- tests/test_r304_imghost_domains.py
- tests/test_r522_reset_shows_progress.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import importlib.util
import io
import os
import re
import sys

import pytest


# ---- merged from tests/test_r1056_fliggy_reset_probe.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    p = os.path.join(ROOT, "scripts", "fliggy_app_reset.py")
    spec = importlib.util.spec_from_file_location("fliggy_app_reset", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


HOME_XML = (
    '<hierarchy><node text="酒店" bounds="[100,760][200,810]"/>'
    '<node text="机票" bounds="[360,760][410,810]"/>'
    # 顶部营销 banner 里的「机票」，y1 < 300，必须被排除
    '<node text="机票" bounds="[900,100][1000,150]"/>'
    "</hierarchy>")


class FakeDev:
    def __init__(self, act_after, xml=HOME_XML):
        self._act = ".home.HomeActivity"
        self._after = act_after
        self._xml = xml
        self.taps = []

    def current_activity(self):
        return self._act

    def dump(self):
        return self._xml

    def tap(self, x, y):
        self.taps.append((x, y))
        self._act = self._after
        return True


def test_blocked_when_flight_module_returns_container():
    m = _mod()
    d = FakeDev("com.taobao.trip/com.alibaba.wireless.security.open."
                "middletier.fc.ui.ContainerActivity")
    ok, why = m.flight_module_ok(d, wait_s=0)
    assert ok is False
    assert "仍被拦" in why, why


def test_ok_when_flight_form_reached():
    m = _mod()
    d = FakeDev("com.taobao.trip/.flutter.TripFlutterActivity")
    ok, why = m.flight_module_ok(d, wait_s=0)
    assert ok is True, why


def test_taps_lower_tile_not_banner():
    """必须点下半屏的宫格（y1>=300），不能点顶部营销 banner 里的「机票」。"""
    m = _mod()
    d = FakeDev("com.taobao.trip/.flutter.TripFlutterActivity")
    m.flight_module_ok(d, wait_s=0)
    assert d.taps, "没点任何东西"
    x, y = d.taps[0]
    assert y >= 700, "点到了顶部 banner：%s" % (d.taps,)


def test_home_without_tile_is_not_ok():
    m = _mod()
    d = FakeDev(".home.HomeActivity",
                xml='<hierarchy><node text="酒店" bounds="[0,700][100,800]"/>'
                    "</hierarchy>")
    ok, why = m.flight_module_ok(d, wait_s=0)
    assert ok is False
    assert "找不到" in why, why


# ---- merged from tests/test_r1179_err_codes_page.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_endpoints_exist():
    assert '"/api/err-codes"' in WEBUI
    assert '"/api/err-codes/explain"' in WEBUI
    assert "from core import err_codes as _ec" in WEBUI


def test_page_container_and_loader():
    assert 'id="errCodeCard"' in WEBUI
    assert 'id="errCodeBody"' in WEBUI
    assert "function loadErrCodes(" in WEBUI
    assert "function toggleErrCodes(" in WEBUI
    assert "onclick=\"toggleErrCodes()\"" in WEBUI


def test_page_does_not_duplicate_the_table():
    """负控：页面里不许出现码 → 说法的第二份拷贝。"""
    assert "环境存在风险" not in WEBUI, "webui.py 里又写了一份 50003 的解释"
    assert "阿里 NC 滑块" not in WEBUI, "webui.py 里又写了一份 x2VW8 的解释"


def test_default_collapsed():
    """密度契约：默认收起，一行摘要即可。"""
    i = WEBUI.find('id="errCodeBody"')
    seg = WEBUI[i:i + 80]
    assert 'display:none' in seg, "错误码表默认必须是收起的：%r" % seg


# ---- merged from tests/test_r1303_stale_tab_build_stamp.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_page_has_build_placeholder():
    assert "const PGBUILD='__PAGEBUILD__';" in SRC, "页面没注入构建戳占位符"
    assert '.replace("__PAGEBUILD__", _build_stamp())' in SRC, "服务端没替换构建戳"


def test_state_carries_build():
    assert '"build": _build_stamp(),' in SRC, "state 没带 build 字段"


def test_banner_compares_build_too():
    """横幅判据必须包含构建戳失配（只比版本号时，同日多次重启判不出来）。"""
    i = SRC.find("if((s.version&&PGVER&&s.version!==PGVER)")
    assert i > 0, "找不到横幅判据"
    seg = SRC[i:i + 200]
    assert "s.build" in seg and "PGBUILD" in seg, seg


def test_build_stamp_is_12_hex():
    """构建戳的**语义**：12 位十六进制；webui.py 或任一模板资产变了都必须变。

    （r1924：不再钉"实现写在哪儿"——实现已收口到 `core.buildstamp`，
    钉文本的写法会让正常的重构误红；这里钉的是可观察行为。）
    """
    import shutil
    import tempfile

    from core.buildstamp import stamp_of

    stamp = stamp_of(ROOT)
    assert re.fullmatch(r"[0-9a-f]{12}", stamp), "构建戳形态变了：%r" % stamp

    # 副本树：只放 webui.py + webui_assets，改动任一文件后戳必须变
    tmp = tempfile.mkdtemp(prefix="stamp_")
    try:
        shutil.copy2(os.path.join(ROOT, "webui.py"), os.path.join(tmp, "webui.py"))
        src_assets = os.path.join(ROOT, "webui_assets")
        if os.path.isdir(src_assets):
            shutil.copytree(src_assets, os.path.join(tmp, "webui_assets"))
        base = stamp_of(tmp)
        assert re.fullmatch(r"[0-9a-f]{12}", base), base

        # 改 webui.py
        with open(os.path.join(tmp, "webui.py"), "ab") as f:
            f.write(b"\n# stamp probe\n")
        assert stamp_of(tmp) != base, "改了 webui.py 构建戳却没变"
        changed = stamp_of(tmp)

        # 改一个模板资产（只挑文件——webui_assets 下还有 icons/ 子目录，
        # 目录项不可 "ab" 追加；stamp_of 也只哈希文件层）
        if os.path.isdir(os.path.join(tmp, "webui_assets")):
            _wa = os.path.join(tmp, "webui_assets")
            assets = sorted(a for a in os.listdir(_wa)
                            if os.path.isfile(os.path.join(_wa, a)))
            assert assets, "webui_assets 是空的？模板外置后不该为空"
            with open(os.path.join(_wa, assets[0]), "ab") as f:
                f.write(b"\n/* probe */\n")
            assert stamp_of(tmp) != changed, "改了模板资产构建戳却没变"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 接线：服务端委托唯一实现，不许自己再算一份
    assert "core.buildstamp" in SRC, "webui._build_stamp 应委托 core.buildstamp"


# ---- merged from tests/test_r1310_gutter_and_anchor.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_all_three_views_share_one_wrap():
    """三视图必须**在同一个 `.wrap` 里**——留白与页头吸顶都由此而来。

    用户原话：「正常应该有留边的啊」「都得跟监控页面一样对齐，左边是有留白的」。

    r1404：之前 searchview/cfgview 曾被一个多余的 `</div>` 挤出 `.wrap`，
    于是它们既没留白、页头 sticky 也没有行程（配置页一滚页头就消失）。
    当时的补救是**各自复制一份外壳样式**（max-width+padding+margin auto），
    那是补丁：断点一抄错就差 6–11px。现在改成结构正确 + 单一外壳：
      · 三个视图同父（.wrap）；
      · 不允许再给 #searchview/#cfgview 单独写 max-width/padding 外壳
        （否则等于承认它们又跑到 wrap 外面去了）。
    """
    # 1) 源码层：三视图的 div 深度必须相同（同父）
    LINES = SRC.splitlines()
    wrap_i = next(i for i, ln in enumerate(LINES) if 'class="wrap"' in ln)

    def _depth_of(needle):
        depth = 0
        for ln in LINES[wrap_i:]:
            depth += ln.count("<div") - ln.count("</div>")
            if needle in ln:
                return depth
            if depth <= 0:
                return -1
        return -1

    d_mon = _depth_of('id="monview"')
    d_search = _depth_of('id="searchview"')
    d_cfg = _depth_of('id="cfgview"')
    assert d_mon == d_search == d_cfg == 2, (
        "三视图不在同一个 .wrap 里：monview=%s searchview=%s cfgview=%s"
        "（多/少一个 </div> 就会把后两个挤出外壳）" % (d_mon, d_search, d_cfg))

    # 2) 不许再有各写一份的外壳
    assert "#searchview,#cfgview{max-width" not in SRC, \
        "又给检索/配置页单独复制了一份外壳（应当在 .wrap 里统一）"


def test_popover_has_no_fixed_corner_pin():
    """弹层不许写死 right/bottom 贴视口角落（那就是"不跟按钮"）。"""
    i = SRC.find("#updPop{position:fixed")
    assert i > 0, "找不到弹层基础样式"
    seg = SRC[i:i + 300]
    assert "right:16px" not in seg and "bottom:64px" not in seg, seg


def test_popover_places_itself_from_trigger():
    assert "function _placeUpdPop()" in SRC, "没有按按钮定位的函数"
    i = SRC.find("function _placeUpdPop()")
    seg = SRC[i:i + 900]
    assert "verChip" in seg, "定位没读触发按钮"
    assert "getBoundingClientRect" in seg
    assert "'--ax'" in seg or '"--ax"' in seg, "没有小尖角锚点"


def test_popover_repositions_after_async_fill():
    """内容异步填充会改高度 → 必须二次定位，否则离按钮很远。"""
    i = SRC.find("setTimeout(_placeUpdPop")
    assert i > 0, "没有二次定位"
    assert SRC.count("_placeUpdPop") >= 3


def test_stale_tab_detection_uses_build():
    assert 'const PGBUILD=' in SRC and '_build_stamp()' in SRC


def test_app_entry_row_has_no_middle_void():
    """渠道入口的 App 行不许再用 space-between 把两个动作拉到两端。

    用户实测圈出中间那片空白问「排版坏了？」——它不是坏（App 没有 PC/H5 入口），
    但读作空洞。改为相邻靠左 + 固定 18px 间距，左侧空档留给行尾。
    作用域必须限定 `:not(.special)`：特价雷达那块窄板有自己的排布。
    """
    i = SRC.find(".chboard:not(.special) .chband-approw{")
    assert i > 0, "App 行的排布覆盖不见了（会退回 space-between 的中间空腔）"
    seg = SRC[i:i + 220]
    assert "justify-content:flex-start" in seg, seg
    assert "space-between" not in seg, "又变回两端对齐了"
    assert "gap:18px" in seg, seg


# ---- merged from tests/test_r1721_advice_states_covered.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _adv_states():
    s = io.open(os.path.join(ROOT, "core", "pacing.py"), encoding="utf-8").read()
    i = s.index("def advise(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j if j > i else len(s)]
    return sorted(set(re.findall(r'"state":\s*"([a-z_]+)"', body)))


def _ui_states():
    w = webui_full_src()
    return sorted(set(re.findall(r"adv\.state==='([a-z_]+)'", w)))


def test_every_advice_state_has_a_row_branch():
    miss = [x for x in _adv_states() if x not in _ui_states()]
    assert not miss, "这些 state 没有专属行文案（会落到默认，读作正常）：%s" % miss


def test_cooldown_branch_shows_remaining():
    w = webui_full_src()
    i = w.index("adv.state==='cooldown'")
    seg = w[i:i + 420]
    assert "冷却中" in seg, "冷却中没写「冷却中」"
    assert "remain_s" in seg or "分钟" in seg, "冷却中没有剩余时间"


# ---- merged from tests/test_r1783_parked_apps.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doc():
    if not os.path.exists(os.path.join(ROOT, "docs", "CHANNEL_PARKED.md")):
        pytest.skip("CHANNEL_PARKED 已删（W7 docs 二次精简），本门禁失去检查对象")
    return io.open(os.path.join(ROOT, "docs", "CHANNEL_PARKED.md"),
                   encoding="utf-8").read()


def test_decision_is_documented():
    d = _doc()
    for k in ("app_ctrip", "app_fliggy", "登录风控", "暂时放弃",
              "恢复", "浏览器通路"):
        assert k in d, "落档缺 " + k


def test_halt_hint_carries_note_and_readable_duration():
    w = webui_full_src()
    assert "人工停手中：%s · 剩 %s" in w, "停手建议没把理由拼进去"
    assert '_hrow3.get("note")' in w, "没读停手的 note"
    assert "_mins >= 48 * 60" in w, "没有「天」这一档时长"
    assert "_mins >= 120" in w, "没有「小时」这一档时长"


def test_browser_lanes_untouched():
    """App 停手不该牵连浏览器通路（两条独立 platform 键）。"""
    d = _doc()
    assert "ctrip" in d and "fliggy" in d
    assert "正常出数" in d or "不受影响" in d


# ---- merged from tests/test_r304_imghost_domains.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8").read()


PROVIDERS = ("ghimg", "freeimage", "smms")


def test_webui_chips_cover_all_providers():
    s = webui_full_src()
    for p in PROVIDERS:
        assert 'data-p="%s"' % p in s, \
            "webui 图床 chip 缺 %s（选项域 < 消费域=配置盲区回归）" % p


def test_report_consumes_all_providers():
    s = _src("report.py")
    for p in PROVIDERS:
        assert 'provider == "%s"' % p in s, \
            "report.upload_chart 消费分支缺 %s（消费域漂移）" % p


def test_testimghost_whitelist_covers_all_providers():
    s = webui_full_src()
    m = re.search(r'provider not in \(([^)]*)\)', s)
    assert m, "/api/test-imghost provider 白名单缺席"
    for p in PROVIDERS:
        assert '"%s"' % p in m.group(1), \
            "通路验证白名单缺 %s（验证域 < 消费域=测试按钮对主通路报「未知图床服务」）" % p


def test_ghimg_label_and_fields_present():
    s = webui_full_src()
    assert "GitHub 图库" in s, "ghimg 词面（GitHub 图库）缺席"
    assert "ih-repo" in s, "ghimg repo 行缺席"
    assert "ih-proxy" in s, "ghimg 代理行缺席（直连失败重试代理无 UI 面）"


def test_chhead_chev_no_inline_auto_margin():
    s = webui_full_src()
    n = s.count('<span class="chev open" style="margin-left:auto">')
    assert n == 0, \
        "chhead chev 内联 margin-left:auto 复活 %d 处（与 .muted 的 auto " \
        "平分自由空间，状态词面被顶到卡/面板中央）" % n


def test_chgrid_action_button_last():
    """通道网格语义序钉：全部配置卡一组，动作按钮（添加邮箱通道）收尾。

    动作按钮曾被图床卡隔在中间（邮件卡→添加按钮→图床卡），配置组里
    插动作件=顺序语义破相（用户立案）。"""
    s = webui_full_src()
    i_card = s.find('data-ch="imghost"')
    i_btn = s.find('onclick="addEm(${i})"')
    assert i_card >= 0 and i_btn >= 0, "图床卡/添加邮箱通道模板缺席"
    assert i_card < i_btn, \
        "图床配置卡在动作按钮之后——chgrid 配置组未收拢、动作按钮未收尾"


# ---- merged from tests/test_r522_reset_shows_progress.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def _fn(src, name):
    i = src.index("async function %s(" % name)
    j = src.index("\n}", i)
    return src[i:j]


def test_reset_shows_progress_text_while_in_flight():
    seg = _fn(_w(), "paceReset")
    assert "解除中…" in seg, "解除没有进行中文案（只置灰看不出在干活）"
    assert "10–60 秒" in seg, "没有给出可等待的时长量级"
    # 必须真的写进按钮
    assert "textContent='解除中…" in seg.replace(" ", ""), \
        "文案没有赋给按钮"


def test_reset_restores_the_original_label():
    seg = _fn(_w(), "paceReset")
    assert "_rTxt" in seg, "没有保存原按钮文案"
    assert "_rb.textContent=_rTxt" in seg, "结束时没有还原按钮文案"


def test_every_slow_intervention_has_visible_progress():
    """四个入口里，凡是会跑长链路的都要有可见进度（verify 开窗即时返回除外）。"""
    src = _w()
    for fn, needle in (("warmNow", "中…"), ("probeNow", "正在自检"),
                       ("paceReset", "解除中…")):
        seg = _fn(src, fn)
        assert needle in seg, "%s 没有「进行中」文案" % fn
        assert "aria-busy" in seg, "%s 没有标记 aria-busy" % fn


def test_progress_text_is_restored_not_left_stuck():
    """在途文案必须能在结束时消失——否则按钮会永久显示「…中」。"""
    src = _w()
    for fn in ("paceReset", "warmNow", "probeNow"):
        seg = _fn(src, fn)
        assert "finally" in seg, "%s 没有 finally 兜底（异常时会卡在…中）" % fn
