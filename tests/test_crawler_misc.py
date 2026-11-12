# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1057_app_onboarding_dismiss.py
- tests/test_r1773_city_page_marks.py
- tests/test_r324_entry_cfg.py
- tests/test_r924_captcha_solver.py
- tests/test_r964_ocr_operator_confusion.py
- tests/test_r970_silent_round_is_named.py
- tests/test_r972_user_data_isolation.py
- tests/test_v160_iata_tongcheng.py
- tests/test_v196_regress.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import logging
import os
import pytest
import sys

from core.flightnorm import cabin_text
from core.yield_stats import INFRA_PATHS, statuses_ok, user_data_root
from crawlers import captcha as c, captcha as cp
from crawlers.app_base import AppCrawler
from crawlers.app_fliggy import AppFliggyCrawler
from crawlers.app_tongcheng import _CITY_PAGE_MARKS, _is_city_page
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r1057_app_onboarding_dismiss.py ----

class FakeDev:
    """按脚本依次返回 activity 与页面。"""

    def __init__(self, script):
        self._script = list(script)
        self.taps = []

    def current_activity(self):
        return self._script[0][0]

    def dump(self):
        act, xml = self._script[0]
        self._next = True
        return xml

    def tap(self, x, y):
        self.taps.append((x, y))
        if len(self._script) > 1:
            self._script.pop(0)
        return True


def _node(text, x=600, y=1400):
    return ('<node text="%s" bounds="[%d,%d][%d,%d]"/>'
            % (text, x - 30, y - 20, x + 30, y + 20))


def _crawler():
    return AppFliggyCrawler({"user_data_dir": "user_data", "android": {}},
                            logging.getLogger("t"))


def test_splash_agreement_is_clicked():
    """启动页的「同意并继续」必须被点掉（原实现只认 permission）。"""
    script = [
        ("com.ctrip/splash.CtripSplashActivity",
         "<hierarchy>" + _node("同意并继续") + "</hierarchy>"),
        ("com.ctrip/home.HomeActivity", "<hierarchy></hierarchy>"),
    ]
    c = _crawler()
    d = FakeDev(script)
    n = c._dismiss_system_prompts(d)
    assert n >= 1, "启动页协议没被点"
    assert d.taps, "没有发生点击"


def test_permission_dialog_still_handled():
    script = [
        ("com.android.permissioncontroller/.GrantPermissionsActivity",
         "<hierarchy>" + _node("允许") + "</hierarchy>"),
        ("com.ctrip/home.HomeActivity", "<hierarchy></hierarchy>"),
    ]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) >= 1


def test_normal_page_is_not_touched():
    """普通页面（非 permission/splash）一律不读不点，避免吃掉广告页序列。"""
    script = [("com.ctrip/home.HomeActivity",
               "<hierarchy>" + _node("同意") + "</hierarchy>")]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) == 0
    assert d.taps == []


def test_loading_activity_agreement_is_clicked():
    """同程首启页是 `.LoadingActivity`（文案「温馨提示 / 同意并继续」）。

    只认 `splash` 会漏掉它 —— 2026-11-06 实测：清数据后渠道卡在首启页，
    账本记「20s 内未到同程机票表单」。修好后同一条路能出 5 条明细。
    """
    script = [
        ("com.tongcheng.android/.LoadingActivity",
         "<hierarchy>" + _node("温馨提示", 600, 900)
         + _node("同意并继续", 600, 1400)
         + _node("不同意且进入游客模式", 600, 1550) + "</hierarchy>"),
        ("com.tongcheng.android/.TongchengMainActivity",
         "<hierarchy></hierarchy>"),
    ]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) >= 1, "LoadingActivity 的协议没被点"


def test_unknown_activity_is_untouched():
    """未列入首启名单的 activity 不介入（避免误点业务页上的「同意」）。"""
    script = [("com.foo/.SettingsActivity",
               "<hierarchy>" + _node("同意") + "</hierarchy>")]
    c = _crawler()
    d = FakeDev(script)
    assert c._dismiss_system_prompts(d) == 0
    assert d.taps == []


# ---- merged from tests/test_r1773_city_page_marks.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")
FORM = os.path.join(ROOT, "user_data", "app_tongcheng",
                    "app_fail_20261112_074311_043968_app-city.xml")


def test_new_city_page_wording_is_recognised():
    xml = ('<hierarchy><node text="选择目的地" bounds="[0,0][100,50]"/>'
           '<node text="你可能还想去" bounds="[0,60][100,90]"/>'
           '<node text="支持搜索城市/国家 中英文或拼音" bounds="[0,100][100,130]"/>'
           '</hierarchy>')
    assert _is_city_page(xml) is True
    assert "选择目的地" in _CITY_PAGE_MARKS


def test_train_and_form_pages_are_not_city_pages():
    train = io.open(TRAIN, encoding="utf-8", errors="replace").read()
    assert _is_city_page(train) is False, "火车票页被当成城市页"
    if os.path.exists(FORM):
        form = io.open(FORM, encoding="utf-8", errors="replace").read()
        assert _is_city_page(form) is False, "机票表单页被当成城市页"


def test_no_legacy_marker_only_checks_left():
    src = io.open(os.path.join(ROOT, "crawlers", "app_tongcheng.py"),
                  encoding="utf-8").read()
    assert '"热门城市" in x or "猜你想去" in x' not in src, \
        "仍有只认旧两个词的判据（会在新版城市页上判「没打开」）"
    assert src.count("_is_city_page(") >= 4, "没把判据统一到 helper"


# ---- merged from tests/test_r324_entry_cfg.py ----

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False






# ---------- 真实 UI 管线助手（禁止直调处理器/手工 dispatchEvent） ----------

def _to_cfg(pg):
    """监控页→真点击⚙️配置导航→等 CFG→真点击「用户与航线」cnav。
    配置视图初始面板是 login（CFGPANEL 缺省），users 面板必须经 cnav
    真点击进入——这一步本身就是 W31 入口。"""
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.locator("#navCfg").click()
    pg.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    pg.locator('.cnav[data-p="users"]').click()
    pg.wait_for_timeout(250)


def _scrollin(pg, sel):
    pg.evaluate(
        "(s)=>{const el=document.querySelector(s);"
        "if(el)el.scrollIntoView({block:'center',behavior:'instant'});}", sel)


def _click(pg, sel):
    """深位元素真点击：先瞬时滚入（平滑滚动吃预算的实锤规避）再
    locator click（完整 actionability 管线，非 JS click）。"""
    _scrollin(pg, sel)
    pg.locator(sel).first.click()


def _fill(pg, sel, val):
    """真 fill + Tab 失焦：fill 只发 input，change 由真实焦点移出触发
    （与手输后点别处同构）。seed 与 fill 恒须不同值（同值不触发）。"""
    _scrollin(pg, sel)
    loc = pg.locator(sel).first
    loc.fill(val)
    pg.keyboard.press("Tab")


def _txt(pg, sel):
    return pg.evaluate(
        "(s)=>{const el=document.querySelector(s);"
        "return el?el.textContent.trim():null;}", sel)


def _open_dtools(pg, rk="0:0"):
    """按卡展开「＋ 添加」工具组（r339g 二合一后 dadd/加日期住在
    display:none 折叠行里；buildForm 重建会重置折叠态，每次变更后
    需再展开——LESSONS 十九§7/§8 + 十一§3 重建吞交互态）。"""
    dsel = '.rline[data-rk="%s"] .dline.dtools' % rk
    if pg.locator(dsel).first.count() \
            and not pg.locator(dsel).first.evaluate(
                "el=>el.classList.contains('open')"):
        _click(pg, '.rline[data-rk="%s"] .dtools-t' % rk)


def _open_rtadv(pg, rk="0:0"):
    """展开「筛选与时段约束」折叠组（r339 起中转/时段/筛选行默认收起——
    A1 P1 修复后 foldRoute 展开路由不再连带展开内层折叠，操作行前须
    显式展开）。"""
    pg.evaluate("""((rk) => {
      const rt=document.querySelector(
        '.rline[data-rk="'+rk+'"] .rthead');
      if(rt&&rt.getAttribute('aria-expanded')==='false')rt.click();
    })""", rk)
    pg.wait_for_timeout(120)


def _open_route(pg, rk="0:0"):
    """真点击航线卡头展开（全新 context 下 FOLD 空 → 默认折叠态确定）。"""
    sel = '.rline[data-rk="%s"] .rhead' % rk
    assert pg.locator(sel).first.get_attribute("aria-expanded") == "false", sel
    _click(pg, sel)
    assert pg.locator(sel).first.get_attribute("aria-expanded") == "true", sel
    _open_dtools(pg, rk)


def _open_ch(pg, key):
    """幂等展开通道卡：addEm 后新卡自动展开（r343），不得再强断言首态。"""
    sel = '.chcard[data-ch="%s"] .chhead' % key
    if pg.locator(sel).first.get_attribute("aria-expanded") == "false":
        _click(pg, sel)
    assert pg.locator(sel).first.get_attribute("aria-expanded") == "true", sel


_SNAP = """
(() => ({glb: JSON.parse(JSON.stringify(GLB)),
        users: JSON.parse(JSON.stringify(CFG))}))()
"""


def _restore(pg, snapshot):
    """模型快照还原 + buildForm 全量重建（测试收尾态复位；测试管线，
    非入口交互）。"""
    pg.evaluate("""((snap) => {
      CFG.length = 0;
      for (const u of snap.users) CFG.push(JSON.parse(JSON.stringify(u)));
      GLB = JSON.parse(JSON.stringify(snap.glb));
      buildForm();
    })""", snapshot)


# ================= §1 用户名（W1） =================



# ================= §2 推送行为（W2 族） =================






# ================= §3 监控渠道 chips（W3 togPlat） =================



# ============ §4 通道派生启用（W4 阿里云 / W5 ntfy / W6 Server酱） ============





# ================= §5 邮件通道（W7-W10） =================





# ================= §6 钉钉（W11） =================



# ================= §7 图床（W12） =================




# ============ §8 航线卡（W13；城市面板=C9 病灶路径，最高优先） ============






# ================= §9 航线启停（W14） =================



# ================= §10 特价（W15） =================




# ================= §11 日期（W16/W17；📅 showPicker 跳过） =================




# ================= §12 出发时段（W24/W25） =================




# ================= §13 复制/删除航线（W22/W23） =================




# ================= §14 添加/删除用户（W19/W20） =================




# ============ §15 G 区 globals（W26/W27 + glbCheck 校验面） ============

class TestW2627Globals:
    def _to_globals(self, page):
        _to_cfg(page)
        page.locator('.cnav[data-p="globals"]').click()
        page.wait_for_timeout(200)





# ===== §16 折叠/手风琴/cnav 面板/搜索（W29-W33） =====






# ===== §17 保存/放弃/导入（W34/W35/W36） =====





# ---- merged from tests/test_r924_captcha_solver.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r924")


# ---------------------------------------------------------------------------
# 1. 算数求解
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("3 + 7 = ?", 10),
    ("3+7=?", 10),
    ("3+7=0", 10),          # OCR 把 ? 认成 0 —— 仍要算对
    ("计算：12*4=", 48),
    ("12×4", 48),
    ("8÷2=？", 4),
    ("9-3", 6),
    ("12 + 34 =", 46),
    ("三加七", 10),
    ("五乘以六", 30),
    ("九减四", 5),
    ("8除以2", 4),
    ("10.5+0.5", 11),
])
def test_solve_arithmetic_variants(text, expect):
    assert cp.solve_arithmetic(text) == expect, text


@pytest.mark.parametrize("text", [
    "", "无算式", "请拖动滑块", "1+2+3",      # 三元不猜
    "8/0",                                  # 除零
])
def test_solve_arithmetic_rejects(text):
    assert cp.solve_arithmetic(text) is None, text


def test_solve_arithmetic_prefers_left_of_equal():
    """等号右边是 OCR 噪声（0/问号），不能参与运算。"""
    assert cp.solve_arithmetic("7=0") is None
    assert cp.solve_arithmetic("3+7=0+99") == 10


def test_solve_arithmetic_never_uses_eval():
    """注入串不该被执行（自己算四则）。"""
    assert cp.solve_arithmetic("__import__('os').system('echo x')") is None


# ---------------------------------------------------------------------------
# 2. 判型
# ---------------------------------------------------------------------------
def test_classify_arithmetic():
    k = cp.classify_kind("请输入计算结果：3 + 7 = ?")
    assert k.name == "arithmetic" and k.solvable is True


def test_classify_text_captcha():
    k = cp.classify_kind("请输入图中的验证码")
    assert k.name == "text" and k.solvable is True


def test_classify_slider_delegates():
    k = cp.classify_kind('<div class="slide-verify">拖动滑块完成拼图</div>')
    assert k.name == "slider" and k.solvable is True


@pytest.mark.parametrize("html", [
    "极验 智能验证", "geetest v4", "tcaptcha 天御", "baxia",
    "recaptcha", "hcaptcha",
])
def test_classify_strong_is_not_solvable(html):
    k = cp.classify_kind(html)
    assert k.name == "strong" and k.solvable is False


def test_classify_click_is_solvable_only_with_a_detector(monkeypatch):
    """点选题（r1063 T21 起）：**图像定位题**，有检测后端才可解。

    旧契约是"点选一律不可解"，那属于限制性设计（用户要求清掉）。新契约把
    判断绑定到后端是否真的可用：没有后端时仍然不可解——这样"可解"永远是
    真话，不会出现「声称能解、实际点不了」。
    """
    monkeypatch.setattr(cp, "_det_backend", lambda: None)
    k = cp.classify_kind("请按顺序点击下方文字")
    assert k.name == "click" and k.solvable is False

    monkeypatch.setattr(cp, "_det_backend", lambda: object())
    k2 = cp.classify_kind("请按顺序点击下方文字")
    assert k2.name == "click" and k2.solvable is True


def test_classify_unknown():
    k = cp.classify_kind("正常列表页")
    assert k.name == "unknown" and k.solvable is False


# ---------------------------------------------------------------------------
# 3. 答案清洗
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expect", [
    ("AB12", "AB12"),
    ("验证码：X7K9", "X7K9"),
    ("a b 1 2", "AB12"),
    ("x7k9", "X7K9"),
    ("  3 7 0  ", "370"),
])
def test_clean_answer(raw, expect):
    assert cp.clean_answer(raw) == expect


def test_clean_answer_digits_only():
    assert cp.clean_answer("答案： 12ab34", digits_only=True) == "1234"


# ---------------------------------------------------------------------------
# 4. 预处理与 OCR（真实图片，需要 Windows OCR）
# ---------------------------------------------------------------------------
def _png(text, size=44):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", size)
    except Exception:
        pytest.skip("没有可用字体")
    im = Image.new("RGB", (460, 120), (255, 255, 255))
    ImageDraw.Draw(im).text((16, 28), text, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _has_ocr() -> bool:
    try:
        from core.android import ocr
        return bool(ocr.available())
    except Exception:
        return False


def test_preprocess_is_fail_soft():
    assert cp.preprocess(b"not-a-png") == b"not-a-png"
    assert cp.preprocess(b"") == b""


def test_preprocess_returns_png():
    out = cp.preprocess(_png("AB12"))
    assert out.startswith(b"\x89PNG")


@pytest.mark.skipif(not _has_ocr(), reason="系统 OCR 不可用")
def test_read_text_reads_plain_captcha():
    raw = cp.read_text(_png("AB12"))
    assert cp.clean_answer(raw) == "AB12", raw


@pytest.mark.skipif(not _has_ocr(), reason="系统 OCR 不可用")
def test_read_text_survives_thin_strokes():
    """预处理会抹掉细笔画：双读取更长才读得出来（实测 AB12）。"""
    assert cp.clean_answer(cp.read_text(_png("X7K9"))) == "X7K9"


# ---------------------------------------------------------------------------
# 5. 预算共用 + 强人机不动手
# ---------------------------------------------------------------------------
class _Mouse:
    def __init__(self):
        self.events = []

    def move(self, *a, **k):
        self.events.append("move")

    def down(self):
        self.events.append("down")

    def up(self):
        self.events.append("up")


class _Page:
    url = "https://example.test/challenge"

    def __init__(self, html, text=""):
        self.html = html
        self.text = text
        self.mouse = _Mouse()

    def content(self):
        return self.html

    def inner_text(self, sel=None):
        return self.text

    def query_selector(self, sel):
        return None

    def screenshot(self, full_page=False):
        return b""

    def keyboard(self):
        raise AssertionError("不该走到键盘输入")


def test_attempt_refuses_strong_without_touching(tmp_path):
    page = _Page("<div>geetest 智能验证</div>", "智能验证")
    rep = cp.attempt(page, "ctrip", {"slider": {"auto": "simple"}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert rep["kind"] == "strong"
    assert page.mouse.events == []


def test_attempt_respects_shared_budget(tmp_path):
    page = _Page("请输入图中的验证码", "验证码")
    rep = cp.attempt(page, "ctrip", {"slider": {"auto": "off"}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert "预算" in rep["detail"]


def test_attempt_reports_missing_input(tmp_path):
    page = _Page("请输入图中的验证码", "验证码")
    rep = cp.attempt(page, "ctrip", {"slider": {"auto": "simple"}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    # 没有输入框 → 明确报出来，而不是假装试过
    assert "输入框" in rep["detail"] or "空答案" in rep["detail"]


# ---------------------------------------------------------------------------
# 6. 配置开关必须真生效（配了不读 = 死配置，docs 契约测试会抓）
# ---------------------------------------------------------------------------
def test_arithmetic_switch_off_blocks(tmp_path):
    page = _Page("请输入计算结果：3+7=?", "计算")
    rep = cp.attempt(page, "ctrip",
                     {"slider": {"auto": "simple"},
                      "captcha": {"arithmetic": False}},
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert "算数题开关已关" in rep["detail"]


def test_text_switch_off_blocks(tmp_path):
    page = _Page("请输入图中的验证码", "验证码")
    rep = cp.attempt(page, "ctrip",
                     {"slider": {"auto": "simple"},
                      "captcha": {"text": "false"}},      # 字符串假值也要认
                     user_data_dir=str(tmp_path), logger=_LOG)
    assert rep["ok"] is False
    assert "文字题开关已关" in rep["detail"]


def test_ocr_scale_is_read_from_config(monkeypatch, tmp_path):
    """``captcha.ocr_scale`` 必须被读走（否则是死配置）。"""
    seen = {}

    def _fake_read(png, bbox=None, scale=3.0, crop=None):
        seen["scale"] = scale
        return "AB12"
    monkeypatch.setattr(cp, "read_text", _fake_read)

    class _P(_Page):
        def query_selector(self, sel):
            class _El:
                def is_visible(self):
                    return True

                def click(self):
                    pass

                def fill(self, v):
                    seen["filled"] = v
            return _El()
    page = _P("请输入图中的验证码", "验证码")
    cp.attempt(page, "ctrip",
               {"slider": {"auto": "simple"},
                "captcha": {"text": True, "ocr_scale": 2.0}},
               user_data_dir=str(tmp_path), logger=_LOG)
    assert seen.get("scale") == 2.0, seen


# ---------------------------------------------------------------------------
# 7. 账本：分项观测 + 总账仍是一本
# ---------------------------------------------------------------------------
def test_ledger_records_by_kind(tmp_path):
    from crawlers import slider as sl
    d = str(tmp_path)
    cfg = {"slider": {"auto": True, "max_fails": 2}}
    sl.note_result("ctrip", True, cfg, user_data_dir=d, kind="arithmetic")
    sl.note_result("ctrip", False, cfg, user_data_dir=d, kind="text")
    sl.note_result("ctrip", True, cfg, user_data_dir=d, kind="arithmetic")
    rec = sl._load(sl._ledger_path(d, "ctrip"))["ctrip"]
    assert rec["tries"] == 3
    bk = rec["by_kind"]
    assert bk["arithmetic"]["tries"] == 2 and bk["arithmetic"]["ok"] == 2
    assert bk["text"]["tries"] == 1 and bk["text"]["fail"] == 1


def test_ledger_blacklist_still_counts_total(tmp_path):
    """拉黑按**总**失败数算：分类别不能让"失败 2 次拉黑"互相抵消。"""
    from crawlers import slider as sl
    d = str(tmp_path)
    cfg = {"slider": {"auto": True, "max_fails": 2}}
    sl.note_result("ctrip", False, cfg, user_data_dir=d, kind="slider")
    sl.note_result("ctrip", False, cfg, user_data_dir=d, kind="text")
    rec = sl._load(sl._ledger_path(d, "ctrip"))["ctrip"]
    assert rec["fails"] == 2
    assert rec["blocked_until"] > 0            # 跨类别累计照样拉黑


def test_ledger_old_file_without_by_kind_still_works(tmp_path):
    """老账本没有 ``by_kind`` 字段，读进来不能炸。"""
    import json
    from crawlers import slider as sl
    d = str(tmp_path)
    p = sl._ledger_path(d, "ctrip")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"tries": 5, "fails": 1}}, f)
    cfg = {"slider": {"auto": True}}
    rec = sl.note_result("ctrip", True, cfg, user_data_dir=d, kind="text")
    assert rec["tries"] == 6
    assert rec["by_kind"]["text"]["ok"] == 1
    assert rec["fails"] == 0                    # 成功清零


# ---------------------------------------------------------------------------
# 8. 可选后端 ddddocr：装了优先用，没装退回系统 OCR（都不许抛）
# ---------------------------------------------------------------------------
def test_backend_name_is_one_of_known(tmp_path):
    assert cp.backend_name() in ("ddddocr", "windows-ocr", "none")


def test_read_text_prefers_ddddocr_when_it_reads_more(monkeypatch):
    """ddddocr 读出更多字符时采用它（它对付字符验证码通常更强）。"""
    monkeypatch.setattr(cp, "_ocr_once", lambda png: "AB1")     # 系统 OCR
    monkeypatch.setattr(cp, "_read_with_ddddocr", lambda png: "AB12")
    assert cp.read_text(b"\x89PNG fake") == "AB12"


def test_read_text_keeps_windows_result_when_ddddocr_empty(monkeypatch):
    monkeypatch.setattr(cp, "_ocr_once",
                        lambda png: "AB12" if png is not None else "")
    monkeypatch.setattr(cp, "_read_with_ddddocr", lambda png: "")
    assert cp.read_text(b"x") == "AB12"


def test_read_text_keeps_windows_result_when_ddddocr_shorter(monkeypatch):
    calls = {"n": 0}

    def _ocr(png):
        calls["n"] += 1
        return "AB12"
    monkeypatch.setattr(cp, "_ocr_once", _ocr)
    monkeypatch.setattr(cp, "_read_with_ddddocr", lambda png: "A")
    assert cp.read_text(b"x") == "AB12"


def test_ddddocr_absent_is_not_an_error(monkeypatch):
    """没装 ddddocr 时 ``_read_with_ddddocr`` 返回空串，不抛。"""
    cp._DDDDOCR_TRIED[0] = False
    cp._DDDDOCR.clear()
    monkeypatch.setitem(__import__("sys").modules, "ddddocr", None)
    assert cp._read_with_ddddocr(b"x") == ""


def test_slide_match_absent_returns_none(monkeypatch):
    cp._DDDDOCR_TRIED[0] = False
    cp._DDDDOCR.clear()
    monkeypatch.setitem(__import__("sys").modules, "ddddocr", None)
    assert cp.slide_match(b"x") is None


# ---- merged from tests/test_r964_ocr_operator_confusion.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. 本机实测的那个坏样本必须能算对
# ---------------------------------------------------------------------------
def test_measured_ocr_failure_now_solves():
    """windows-ocr 实测返回 `3爷7=`（`+` 认成"爷"）。"""
    assert c.solve_arithmetic("3爷7=") == 10
    assert c._answer_arithmetic("3爷7=") == "10"


def test_operator_confusion_variants():
    assert c.solve_arithmetic("3丁7") == 10
    assert c.solve_arithmetic("6－2") == 4        # 全角减号（_normalize 已处理）
    assert c.solve_arithmetic("8x2") == 16       # x 当乘号（既有行为）


# ---------------------------------------------------------------------------
# 2. 顺序：正常能解的输入，绝不经过字形替换
# ---------------------------------------------------------------------------
def test_clean_input_untouched():
    for txt, want in (("3+7=?", 10), ("3 + 7 = ?", 10), ("9-3", 6)):
        assert c.solve_arithmetic(txt) == want, txt


def test_fix_ops_only_between_digits():
    """题面里正常出现的汉字不许被当运算符。"""
    assert c._ocr_fix_ops("爷孙3人") == "爷孙3人"
    assert c._ocr_fix_ops("3爷7") == "3+7"
    assert c._ocr_fix_ops("") == ""


# ---------------------------------------------------------------------------
# 3. 认不出就不猜（答错比不答更危险）
# ---------------------------------------------------------------------------
def test_unknown_glyph_refuses_to_guess():
    assert c.solve_arithmetic("3?7") is None
    assert c.solve_arithmetic("3~7") is None


def test_multi_operator_still_refused():
    assert c.solve_arithmetic("1+2+3") is None
    # 纠正之后也不会把两个可疑位当作单一算式来蒙
    assert c.solve_arithmetic("1爷2爷3") is None


def test_divide_by_zero_refused():
    assert c.solve_arithmetic("8/0") is None


# ---------------------------------------------------------------------------
# 4. 真实图片链路（离线，不碰设备）
# ---------------------------------------------------------------------------
def test_real_image_pipeline_end_to_end():
    """给定 OCR 的返回，兜底必须真的能出答案；OCR 本身的质量不在断言范围内。

    第一版我拿 PIL 画的图去断言"引擎认得出 3+7"，结果同一张图两次跑出
    **不同**结果：`3爷7=` 与 `37=1`（`backend_name()` = `windows-ocr`，
    因为 `ddddocr` 没装）。把测试绑在引擎质量上，得到的是一个会随机
    变红的用例，而不是一条契约 —— **我们只能承诺"自己的那段逻辑正确"**。

    所以这里：
    * 用**实测到的**引擎输出当输入，验证我们的解析确实救得回来；
    * 对救不回来的输出（`37=1`），断言它**返回空而不是蒙一个**
      —— 蒙错答案比不答更容易触发风控，这是本模块的取舍方向。
    """
    for ocr_text, want in (("3+7=?", "10"),      # 引擎读对
                           ("3爷7=", "10"),      # 实测：+ 认成"爷"
                           ("3丁7", "10"),       # 实测：+ 认成"丁"
                           ("37=1", ""),         # 彻底读乱 → 不猜
                           ("", "")):
        assert c._answer_arithmetic(ocr_text) == want, ocr_text


def test_read_text_never_raises_and_returns_str():
    """真调引擎只验"不崩、返回 str"，不验内容。

    环境里没有 ddddocr 时会退到 windows-ocr；退到什么质量是环境属性，
    不该由本仓的单测来担保（也不该由代码假装它一定可用）。
    """
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (180, 56), "white")
    ImageDraw.Draw(im).text((16, 18), "3+7=?", fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    out = c.read_text(buf.getvalue())
    assert isinstance(out, str), type(out)


def test_vendor_path_is_appended_not_prepended():
    """`_vendor` 必须 **append** 到 sys.path 末尾。

    2026-11-04 用 `pip install --target=_vendor ddddocr` 装解码后端时，
    顺带把 `numpy 2.4.6` / `Pillow 13` / `opencv 5` 也落了进去。
    实测全局仍是 `numpy 2.2.6 / PIL 12.3.0 / cv2 4.12.0`，
    因为 `_ensure_vendor_path()` 用的是 `sys.path.append`——
    **改成 insert 的那一刻，_vendor 里那套副本就会盖掉监控进程正在用的全局库**，
    而这种事不会有任何报错，只会以"莫名崩库"的形式在几周后浮现。
    所以把 append 钉成契约。（真正需要的只有 `ddddocr` 本身，它只存在于 _vendor。）
    """
    src = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
    i = src.find("def _ensure_vendor_path")
    body = src[i:src.find("\ndef ", i + 10)]
    assert "sys.path.append(" in body, "不再是 append：会遮蔽全局 numpy/PIL/cv2"
    assert "sys.path.insert" not in body


def test_ddddocr_backend_reports_honestly():
    """装了就要真的出字；`backend_name()` 不许说 ddddocr 而实际不可用。"""
    name = c.backend_name()
    if name != "ddddocr":
        # 没装也不失败：兜底引擎照样要能返回 str（见上一个用例）
        return
    png = _tiny_png("3+7=?")
    out = c.read_text(png)
    assert isinstance(out, str) and out.strip(), \
        "报自己是 ddddocr 却读不出任何字符——后端名与实际能力不一致"


def _tiny_png(text: str) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (200, 64), "white")
    ImageDraw.Draw(im).text((12, 16), text, fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ---- merged from tests/test_r970_silent_round_is_named.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _Crawler(AppCrawler):
    """最小可运行的 App 渠道：fetch 行为由用例指定。"""

    name = "app_probe"
    package = ""
    LOGIN_FORM_MARKS = ()

    def __init__(self, rows=None, notes=None):
        super().__init__({}, _Log())
        self._rows = rows or []
        self._notes = notes or []

    def _policy_gate(self, dim=""):
        # 签名跟生产入口对齐（`crawlers/app_base.py::safe_fetch` 调
        # `self._policy_gate(dim=…)`，波次二起闸门要吃维度）：替身少这个
        # 关键字参数就当场 TypeError，测的就不是「静默轮次有没有名字」了。
        return True

    def fetch(self, from_city, to_city, dates, ret_date=""):
        for path, status in self._notes:
            self.path_note(path, status)
        return list(self._rows)


def test_silent_round_gets_a_name():
    """空结果 + 一条通路都没记 ⇒ 必须落下 app-silent，而不是留空。"""
    c = _Crawler(rows=[], notes=[])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    paths = [p.get("path") for p in c.paths]
    assert "app-silent" in paths, "静默轮次没有被命名：%r" % (paths,)
    ok, rows, best = statuses_ok(c.paths)
    assert ok is False and rows == 0
    assert best == "app-silent", "账本仍会落成 unknown(%r)" % best


def test_named_failure_is_not_overwritten():
    """已经记了通路的失败**不许**再补 app-silent（不能盖住真原因）。"""
    c = _Crawler(rows=[], notes=[("app-login", "login")])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    paths = [p.get("path") for p in c.paths]
    assert "app-silent" not in paths, "把已归因的失败又盖了一层：%r" % (paths,)
    assert "app-login" in paths


def test_success_gets_no_silent_note():
    c = _Crawler(rows=[object()], notes=[])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    assert "app-silent" not in [p.get("path") for p in c.paths]


def test_silent_note_carries_reason():
    """留痕要带得上原因（last_error 有就带上，没有也要写清"返回空且未记录"）。"""
    c = _Crawler(rows=[], notes=[])
    c.last_error = ""
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    rec = [p for p in c.paths if p.get("path") == "app-silent"][0]
    assert rec.get("status") == "error"
    assert rec.get("detail"), "静默记录必须带 detail"


def test_silent_is_not_treated_as_infra():
    """`app-silent` 不能进基础设施白名单：**不确定就按失败算**。

    进了白名单会被 §6.48 的"非采集轮不计样本"排除掉，
    成功率会虚高 —— 那比低估更危险。
    """
    assert "app-silent" not in INFRA_PATHS


def test_label_table_knows_app_silent():
    """r658 门禁会扫 `path_note` 字面量对标签表；新名字必须先在表里。

    否则健康卡上会出现一个没有中文名的裸 key。
    """
    import io
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8").read()
    assert '"app-silent"' in src, "标签表缺 app-silent（会过不了 r658 对账）"


# ---------------------------------------------------------------------------
# 浏览器渠道同一类缺口（与 App 侧对称补齐，2026-11-05）
# ---------------------------------------------------------------------------
class _WebCrawler:
    """最小浏览器渠道替身：只测 `_yield_note` 的静默留痕分支。

    直接借 `BaseCrawler` 的方法，其余依赖用最小替你补上——
    这样测的是**生产代码里那段 if**，不是我自己抄一份逻辑。
    """

    name = "web_probe"
    PATH_STATUS = ("ok", "empty", "error", "timeout", "soft_reject",
                   "login", "blocked", "paced", "unsupported")

    def __init__(self, results=None):
        self.paths = []
        self.config = {"user_data_dir": "/tmp/nonexistent_tm_ud"}
        self._results = results or []

    def path_note(self, path, status, rows=0, **kw):
        self.paths.append({"path": path, "status": status, "rows": rows})

    def _yield_ledger(self):
        return None            # 不落盘：本用例只验"有没有留痕"


def test_web_silent_note_is_added_via_real_method():
    """`base._yield_note` 在"零通路 + 零结果"时必须先补 web-silent。

    用真实方法而不是复刻逻辑：把 `BaseCrawler._yield_note` 绑到替身上跑，
    断言那段 `if not self.paths and not results` 真的会执行。
    """
    from crawlers.base import BaseCrawler

    c = _WebCrawler()
    BaseCrawler._yield_note(c, [])
    assert [p["path"] for p in c.paths] == ["web-silent"], c.paths


def test_web_silent_not_added_when_a_path_was_noted():
    from crawlers.base import BaseCrawler

    c = _WebCrawler()
    c.path_note("H5", "empty")
    BaseCrawler._yield_note(c, [])
    assert "web-silent" not in [p["path"] for p in c.paths]


def test_label_table_knows_web_silent():
    import io
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8").read()
    assert '"web-silent"' in src, "标签表缺 web-silent（r658 对账会红）"


# ---- merged from tests/test_r972_user_data_isolation.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPO_USER_DATA = os.path.join(ROOT, "user_data")


# ---------------------------------------------------------------------------
# 1. 唯一口径的优先级
# ---------------------------------------------------------------------------
def test_config_explicit_wins(monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/from_env")
    assert user_data_root({"user_data_dir": "/tmp/from_cfg"}) == "/tmp/from_cfg"


def test_env_used_when_config_silent(monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/from_env")
    assert user_data_root({}) == "/tmp/from_env"
    assert user_data_root(None) == "/tmp/from_env"


def test_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
    assert user_data_root({}) == "user_data"
    assert user_data_root({}, default="ud2") == "ud2"


def test_blank_values_fall_through(monkeypatch):
    """空串/空白必须当"没给"，不能变成空路径。"""
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
    assert user_data_root({"user_data_dir": "  "}) == "user_data"


def test_explicit_default_value_is_not_explicit_config(monkeypatch):
    """**显式传默认值 ≠ 显式配置**（本次修复的关键判据）。

    全仓 16 个测试文件、22 处都写 `{"user_data_dir": "user_data"}`；
    若把它当显式配置，集中重定向就永远漏这些用例，
    `app_dummy` / `app_probe` 这类脏账本会继续长出来。
    语义上它和不传完全等价（都是"用默认目录"），所以可被重定向。
    """
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/redirected")
    assert user_data_root({"user_data_dir": "user_data"}) == "/tmp/redirected"


def test_real_alternative_dir_is_still_respected(monkeypatch):
    """真的换了目录就要听它的——否则会破坏"显式传 tmp 并断言落点"的用例。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/redirected")
    assert user_data_root({"user_data_dir": "/tmp/explicit"}) == "/tmp/explicit"
    assert user_data_root({"user_data_dir": "ud_x"}) == "ud_x"


# ---------------------------------------------------------------------------
# 2. conftest 的隔离真的生效（这条是本次修复的核心）
# ---------------------------------------------------------------------------
def test_conftest_redirects_user_data_root():
    """测试进程里必须已经被重定向到 tmp，而不是仓库的 user_data。"""
    root = os.path.abspath(user_data_root({}))
    assert root != os.path.abspath(REPO_USER_DATA), \
        "测试仍在用真实 user_data：conftest 的 _isolate_user_data 没生效"
    assert "user_data" in root


# ---------------------------------------------------------------------------
# 3. 假渠道真的不会再写进仓库 user_data
# ---------------------------------------------------------------------------
def test_dummy_app_channel_writes_outside_repo_user_data():
    """`app_dummy` 这类假渠道必须落在隔离目录，且仓库 user_data 不长新目录。"""
    from crawlers.app_base import AppCrawler

    class _Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    class _Dummy(AppCrawler):
        name = "app_dummy"
        package = ""
        LOGIN_FORM_MARKS = ()

    c = _Dummy({}, _Log())
    led = c._ledger()
    assert led is not None
    path = os.path.abspath(getattr(led, "path", "") or "")
    if path:
        assert os.path.abspath(REPO_USER_DATA) not in path, \
            "登录账本写进了真 user_data：%s" % path
        assert os.environ.get("TM_USER_DATA_DIR") in path


def test_browser_dummy_channel_writes_outside_repo_user_data():
    from crawlers.base import BaseCrawler

    class _Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    class _Dummy(BaseCrawler):
        name = "probe"

    c = _Dummy({"enabled": True}, _Log())
    led = c._yield_ledger()
    assert led is not None
    path = os.path.abspath(getattr(led, "path", "") or "")
    if path:
        assert os.path.abspath(REPO_USER_DATA) not in path, \
            "成功率账本写进了真 user_data：%s" % path


# ---------------------------------------------------------------------------
# 4. 结构约束：四个写点都必须走唯一口径
# ---------------------------------------------------------------------------
def test_all_four_write_sites_use_the_shared_helper():
    """写点分散在 4 处 —— 任何一处漏改，下次又会悄悄写进真 user_data。"""
    import io
    for rel in ("crawlers/base.py", "crawlers/app_base.py", "core/policy.py"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "user_data_root(" in src, "%s 没用唯一口径" % rel
        assert 'get("user_data_dir") or "user_data"' not in src, \
            "%s 还留着旧的硬编码默认路径" % rel


# ---- merged from tests/test_v160_iata_tongcheng.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- tongcheng 直飞行：fl[].dac/aac（第十二批调研 dump 95/95 恒在） ----

def _tc_direct(**kw):
    f = {"fn": "CZ6981", "dt": "2026-10-06 08:00", "at": "2026-10-06 12:00",
         "atp": 1800, "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    f.update(kw)
    return TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [f]}}))


def test_tongcheng_direct_iata_codes():
    """fl[].dac/aac 与已采 dasn/aasn 同层读，iata3 守卫同 qunar/tuniu/
    ctrip 三源同律：合法落、脏值不落、缺键空串在键（与 qunar 落键
    形态一致——webui 白名单/propagate 消费空串=无值）。"""
    rows = _tc_direct(dasn="天山", aasn="虹桥", dac="URC", aac="SHA")
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "SHA"
    for bad in ("urc", "123", "URCC", "乌鲁木齐", None, ""):
        rows = _tc_direct(dac=bad, aac=bad)
        assert rows[0]["depAirportCode"] == "", bad
        assert rows[0]["arrAirportCode"] == "", bad
    rows = _tc_direct()
    assert rows[0]["depAirportCode"] == ""
    assert rows[0]["arrAirportCode"] == ""


def test_tongcheng_transfer_iata_segment_chain():
    """conn 块段链取 ss[0].dac（首段出发=整体出发）/ss[-1].aac（末段
    到达=整体到达）。陷阱键钉死：ss[0].aac=首段中转场码（YZY 形），
    误读会让 URC→SHA 航线挂出 URC→YZY——与 qunar
    binfo1.arrAirportId 同律防误读。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "aat": "T3", "dac": "URC", "aac": "YZY"},
                 {"fn": "MU5700", "dat": "T5", "dac": "YZY", "aac": "PVG"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows[0]["depAirportCode"] == "URC"
    assert rows[0]["arrAirportCode"] == "PVG"
    fp2 = dict(fp, ss=[{"fn": "CZ6981", "dac": "urc"},
                       {"fn": "MU5700", "aac": "URCC"}])
    rows2 = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp2]}}))
    assert rows2[0]["depAirportCode"] == ""
    assert rows2[0]["arrAirportCode"] == ""


# ---- 哨兵：跨渠道 IATA 码对分歧 + aptc 覆盖率比率观测 ----

def _sent(monkeypatch, tmp_path, prices, keep_supplied=False):
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    if not keep_supplied:
        _m._SENT_SUPPLIED.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    class _I:
        def info(self, *a, **k):
            pass

    rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
    _m._field_sentinel(rows, _L())
    return seen, _I, _m


def _healthy(**kw):
    """带齐比率/白名单观测字段命中值的行（排除其他桶噪音，聚焦断言）。"""
    f = {"price": 1000, "code": "9C8846", "depTime": "08:00",
         "arrTime": "12:00", "transCity": "", "arrDate": "2026-10-06",
         "cabin": "经济舱", "meal": "有餐食", "prate": "96",
         "plane": "737", "planeSize": "中型机", "depAirport": "天山",
         "depAirportCode": "URC", "arrAirportCode": "SHA"}
    f.update(kw)
    return f


def test_sentinel_iata_pair_divergence_warns(monkeypatch, tmp_path):
    """同航班号同指纹两渠道码对集合不一致=分歧（DB 全库 293 组合级
    配对 d=0 纯净基线定证的零容忍告警面）；码对一致/单源不响。"""
    qn = [_healthy() for _ in range(12)]
    ct = [_healthy(depAirportCode="URC", arrAirportCode="PVG")
          for _ in range(12)]
    seen, _I, _m = _sent(monkeypatch, tmp_path,
                         [("qunar", qn), ("ctrip", ct)])
    assert any("IATA 码对分歧" in str(a) for a in seen), seen
    # 码对一致：不响
    seen2, _I, _m = _sent(monkeypatch, tmp_path,
                          [("qunar", qn), ("ctrip", [_healthy() for _ in range(12)])])
    assert not any("IATA 码对分歧" in str(a) for a in seen2), seen2
    # 单源（对方无码不参对）：不响
    seen3, _I, _m = _sent(monkeypatch, tmp_path,
                          [("qunar", qn),
                           ("ctrip", [_healthy(depAirportCode="",
                                               arrAirportCode="")
                                      for _ in range(12)])])
    assert not any("IATA 码对分歧" in str(a) for a in seen3), seen3


def test_sentinel_iata_aptc_coverage(monkeypatch, tmp_path):
    """aptc 入比率观测（union 口径同 apt）：四源渠道码全灭 <10% 即响
    （键死会退化成单源让分歧哨兵失明——第二道防线）；fliggy|aptc 入
    死键表（页面定证无源）不响。供给基线语义（r316）：健康轮写供给，
    断链轮归零真警。"""
    coded = [_healthy() for _ in range(30)]
    seen3, _I, _m = _sent(monkeypatch, tmp_path, [("qunar", coded)])
    assert not any("aptc" in str(a) for a in seen3), seen3   # 供给轮健康
    bare = [_healthy(depAirportCode="", arrAirportCode="") for _ in range(30)]
    seen, _I, _m = _sent(monkeypatch, tmp_path, [("qunar", bare)],
                         keep_supplied=True)
    assert any("aptc" in str(a) for a in seen), seen
    seen2, _I, _m = _sent(monkeypatch, tmp_path, [("fliggy", bare)])
    assert not any("aptc" in str(a) for a in seen2), seen2


# ---- cabin_text：discount N折 形态守卫 ----

def test_cabin_text_discount_guard():
    """N折 形态保留；qunar PC 复活后 discount 槽位的纯舱名文本
    （「明珠经济舱」「商务舱」等）不进舱位描述串（语义由舱名列
    承载）；「全价+舱别」复合形态随 r289 家族档回收「全价」段
    （封闭集合三形态，DB 5,552 行三面互证）。"""
    assert cabin_text({"cabin": "经济舱", "discount": "5.6折",
                       "plane": "737"}) == "经济舱 · 5.6折 · 737"
    # 全价复合形态提取「全价」token，其余段不受影响
    assert cabin_text({"cabin": "T", "discount": "全价经济舱"}) == "T舱 · 全价"
    assert cabin_text({"cabin": "经济舱", "discount": " 5.6折 "}) == \
        "经济舱 · 5.6折"
    # 纯舱名冒充形态维持丢弃（禁复活段）
    assert cabin_text({"cabin": "经济舱", "discount": "明珠经济舱"}) == \
        "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": "商务舱"}) == "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": "全价头等舱"}) == \
        "经济舱"
    # 无 discount / 空 / 纯折扣数值缺「折」均不落
    assert cabin_text({"cabin": "经济舱"}) == "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": ""}) == "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": "5.6"}) == "经济舱"
    # 小数折与整数折皆合法
    assert cabin_text({"discount": "4折", "cabin": "经济舱"}) == \
        "经济舱 · 4折"


# ---- fliggy recheck 观测转正（源钉：撤「N=1 先观测」备注） ----

def test_fliggy_recheck_observation_promoted():
    """转正源钉：修复生效后 DB 累计 11/11 全部 recheck、反例
    0——「N=1 先观测」备注撤除，转正结论在案；反例出现即回滚的语义
    保留。"""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(os.path.dirname(here),
                            "crawlers", "fliggy.py"), encoding="utf-8").read()
    assert "N=1 先观测" not in src
    assert "N=1 定证不足" not in src
    assert "观测转正" in src


# ---- merged from tests/test_v196_regress.py ----

# ==================== prate_txt 单源守卫 ====================

class TestPrateTxt:
    def test_placeholder_zero_family(self):
        from core.flightnorm import prate_txt
        for v in (0, 0.0, "0", "0%", "0.0", "0.0%", None, "", "   "):
            assert prate_txt(v) == "", repr(v)

    def test_real_values_passthrough(self):
        from core.flightnorm import prate_txt
        assert prate_txt(94) == "94"
        assert prate_txt("94%") == "94%"
        assert prate_txt("96.67") == "96.67"
        assert prate_txt(100) == "100"
        assert prate_txt(" 97 ") == "97"


# ==================== ctrip 读层根治 ====================

class TestCtripPrateZero:
    """组合中转行 classinfor.prate=0（生产 6 行实证形态）：读层
    置空宁缺勿错（与 563 行脏值弃同律）；真值 97 照常。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _item(prate):
        return {"mutilstn": [{"basinfo": {"flgno": "GS7486/FM9426"},
                              "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                           "adate": "2026-10-05 14:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 2050, "quantity": 1,
                                "classinfor": [
                                    {"cgrd": 0, "prate": prate,
                                     "meal": ""}]}]}

    def test_zero_placeholder_dropped(self):
        rows = self._parse(self._item(0))
        assert rows, "夹具应产出航班行"
        # r311 起 0 占位连空串键一并不落（无值不落键收口），
        # 守卫实效语义不变：不产「准点0%」词面
        assert "prate" not in rows[0], rows[0].get("prate")

    def test_real_value_kept(self):
        rows = self._parse(self._item(97))
        assert rows[0]["prate"] == "97"


# ==================== 消费端接线（源码钉） ====================

def test_webui_and_report_wired_to_single_source():
    """webui 明细次行与 report PNG 明细表必须走 prate_txt 单源
    （两消费点直读原始键，源码钉防旁路手抄回潮）。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in ("webui.py", "report.py"):
        src = io.open(os.path.join(root, path), encoding="utf-8").read()
        assert "prate_txt(" in src, f"{path} 未接 prate_txt 单源"


# ==================== transCity 裸码补录 ====================

class TestAirportCnGaps:
    """transCity 机场码补录（数据观测 P2：7 天 DB 实测 4 码漏网——
    WDS 704/UYN 133/LYA 77/YCU 22 行以 IATA 码原样落库，中转城市
    渲染成英文码）。城市级映射与 AIRPORT_CN 现表同风格（城市名）。"""

    def test_normalize_maps_new_codes(self):
        from core.flightnorm import normalize
        for code, cn in (("WDS", "十堰"), ("UYN", "鄂尔多斯"),
                         ("LYA", "洛阳"), ("YCU", "运城")):
            f = {"transCity": code}
            normalize(f, "")
            assert f["transCity"] == cn, code


# ==================== 弹层在途令牌（Soldier P2-1 源码钉） ====================

def test_pv_cancel_seq_token_wired():
    """取消/换代统一走 _PV_SEQ 令牌：单布尔 _PV_CANCEL 曾被新请求
    重置——「Esc 取消→立刻重触发」后被取消请求的迟到响应仍会开层。
    源码钉锁六处同构（fetch 后失配检查 ×3：showLog/previewPush/
    pushLog〔r226 补齐第三入口〕、Esc 令牌递增、finally 按 _sq 清
    pending ×3）；行为面由 uitest「弹层在途 Esc 取消」钉锁。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = webui_full_src()
    assert "let _PV_PENDING=false,_PV_SEQ=0;" in src
    assert src.count("if(_sq!==_PV_SEQ)return;") == 3, \
        "showLog/previewPush/pushLog 三入口失配检查"
    assert "if(_PV_PENDING){++_PV_SEQ;_PV_PENDING=false;return;}" in src
    assert src.count("if(_sq===_PV_SEQ)_PV_PENDING=false;") == 3, \
        "迟到响应不得清新请求 pending"
    assert "_PV_CANCEL" not in src, "旧单布尔取消标志应已退役"


# ==================== 邮件图链本地直嵌 + 降级留痕 ====================

class TestLocalPushImage:
    """P1 邮件图链（推送审校+数据观测双立案）：jsDelivr 与 raw 直链
    同路由间歇可达（各 1/4 成功率，3.5 天失败 241 次）——不稳在路由
    级，换域名无效。cid 内嵌改本地直嵌优先：图在推送前几秒刚渲染落
    盘（URL 尾段 {stem}_{HHMM}.png ↔ 本地 data/{stem}.png），零网络
    失败面。防陈旧：mtime 超 30 分钟（风暴延迟重发时本地文件已被下
    轮覆盖=图文不同源，比丢图更糟）不直嵌走下载，宁慢勿错。
    铁律：仅下载资产层，钉钉消息单发零重试不受影响。"""

    def test_local_hit(self, monkeypatch, tmp_path):
        import os
        monkeypatch.chdir(tmp_path)
        os.makedirs("data")
        (tmp_path / "data" / "trend_URC_SHA_2026-10-05.png").write_bytes(
            b"\x89PNG fake")
        from core.notifier import _local_push_image
        data = _local_push_image(
            "https://cdn.jsdelivr.net/gh/o/r@main/charts/20260928/"
            "trend_URC_SHA_2026-10-05_2018.png")
        assert data == b"\x89PNG fake"

    def test_stale_local_miss(self, monkeypatch, tmp_path):
        import os
        import time
        monkeypatch.chdir(tmp_path)
        os.makedirs("data")
        p = tmp_path / "data" / "trend_X.png"
        p.write_bytes(b"\x89PNG")
        old = time.time() - 3600
        os.utime(p, (old, old))
        from core.notifier import _local_push_image
        assert _local_push_image(
            "https://cdn.jsdelivr.net/gh/o/r@main/charts/20260928/"
            "trend_X_1234.png") == b""

    def test_non_chart_url_miss(self):
        from core.notifier import _local_push_image
        assert _local_push_image("https://sm.ms/x.png") == b""

    def test_inline_prefers_local_no_network(self, monkeypatch, tmp_path):
        import os
        monkeypatch.chdir(tmp_path)
        os.makedirs("data")
        (tmp_path / "data" / "t.png").write_bytes(b"\x89PNGxxxx")
        import core.notifier as nm
        from core.notifier import _inline_push_images

        def _boom(url):
            raise AssertionError("本地命中时不应走网络下载")

        monkeypatch.setattr(nm, "_fetch_push_image", _boom)
        out, parts = _inline_push_images(
            "![走势](https://cdn.jsdelivr.net/gh/o/r@main/charts/"
            "20260928/t_1200.png)", logging.getLogger("t"))
        assert len(parts) == 1 and parts[0][0] == "push-img-1"
        assert "cid:push-img-1" in out

    def test_stats_reports_fallback(self, monkeypatch, tmp_path):
        """降级留痕出参（P2-1）：本地 miss+网络失败 → total=1
        inlined=0，控制台「推送记录」对图挂不再失明（332 发全 ok=true
        曾让 3.5 天丢图完全不可见）。"""
        monkeypatch.chdir(tmp_path)   # 无 data/ 本地文件 → miss
        import core.notifier as nm
        from core.notifier import _inline_push_images
        monkeypatch.setattr(nm, "_fetch_push_image",
                            lambda u: (_ for _ in ()).throw(
                                RuntimeError("boom")))
        st = {}
        out, parts = _inline_push_images(
            "![总表](https://cdn.jsdelivr.net/gh/o/r@main/charts/"
            "20260928/f_1300.png)", logging.getLogger("t"), st)
        assert parts == [] and "cid:" not in out   # 外链保留旧行为
        assert st == {"total": 1, "inlined": 0}, st

    def test_email_history_carries_img_note(self, monkeypatch, tmp_path):
        """email 落账带 img 注（降级时），全成功/无图不带——
        push_history 消费端整条透传，前端按值渲染。last_img_note 由
        _build_msg 每轮重算（防跨轮残留），故走真实降级路径驱动：
        本地 miss+网络炸 → note='图0/1内嵌' 随落账带出。"""
        monkeypatch.chdir(tmp_path)   # 无 data/ 本地文件
        import core.notifier as nm
        captured = []

        def _fake_hist(title, desp, ok, ch="serverchan", img=None):
            captured.append((ch, img))

        monkeypatch.setattr(nm, "_append_push_history", _fake_hist)
        monkeypatch.setattr(
            nm, "_fetch_push_image",
            lambda u: (_ for _ in ()).throw(RuntimeError("boom")))
        n = nm.EmailNotifier.__new__(nm.EmailNotifier)
        n.host, n.port, n.user = "smtp.test", 465, "a@test"
        n.password, n.to = "x", ["b@test"]
        n.sender_name = "机票监控"
        n.logger = logging.getLogger("t")
        n._fail_streak = 0
        n.snapshot_base = None
        monkeypatch.setattr(nm, "smtplib", _FakeSMTPModule())
        desp = ("![总表](https://cdn.jsdelivr.net/gh/o/r@main/charts/"
                "20260928/f_1300.png)")
        assert n.send("t", desp) is True
        assert captured == [("email", "图0/1内嵌")], captured

        # 无图 desp：重算回 None，落账不带 img（防跨轮残留面）
        captured.clear()
        assert n.send("t", "纯文本") is True
        assert captured == [("email", None)], captured


class _FakeSMTP:
    """SMTP_SSL 替身：with 协议 + login/sendmail 零操作。"""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def sendmail(self, *a, **k):
        pass


class _FakeSMTPModule:
    """smtplib 模块替身（send 调 smtplib.SMTP_SSL(...)）。"""

    SMTP_SSL = _FakeSMTP
