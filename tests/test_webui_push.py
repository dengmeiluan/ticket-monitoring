# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r240_push.py
- tests/test_r274_push.py
- tests/test_r299_push.py
- tests/test_v15110_push.py
- tests/test_v1564_push.py
- tests/test_v202_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import core.alerter as alerter
import core.notifier as _nm
import inspect
import json
import logging
import os
import re
import report
import sys
import webui

from core.alerter import Alerter, _dw, _dw as _dw_line, _near_txt, dep_win_txt, kpi_tier_txt
from core.models import FlightPrice, Route
from core.notifier import DingTalkNotifier, EmailNotifier, _append_push_history, _banner_html, _email_shell_html, _esc_md, build_notifier, launch_is_public


# ---- merged from tests/test_r240_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r240")


def _last_rec():
    with open(os.environ["PUSH_HISTORY_FILE"], encoding="utf-8") as f:
        return json.loads(f.read().strip().splitlines()[-1])


class TestErrcodeLedger:
    def test_failure_rec_carries_errcode(self):
        _append_push_history("t", "d", False, ch="dingtalk", errcode=-1)
        rec = _last_rec()
        assert rec["ok"] is False and rec["errcode"] == -1, rec

    def test_success_rec_has_no_errcode_key(self):
        _append_push_history("t", "d", True, ch="dingtalk")
        assert "errcode" not in _last_rec()

    def test_dingtalk_send_failure_ledger_errcode(self, monkeypatch, tmp_path):
        """钉钉失败路径落账带 errcode（-1 幽灵送达信号入账本）。"""
        monkeypatch.chdir(tmp_path)   # last_push.md 落临时目录（P3-3 防覆写真档）
        recs = []
        monkeypatch.setattr(_nm, "_append_push_history",
                            lambda *a, **k: recs.append((a, k)))

        class _R:
            text = '{"errcode":-1,"errmsg":"系统繁忙"}'

            @staticmethod
            def json():
                return {"errcode": -1, "errmsg": "系统繁忙"}

        monkeypatch.setattr(_nm.httpx, "post", lambda *a, **k: _R())
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x", _LOG)
        assert d.send("t", "d") is False
        assert d.last_errcode == -1
        assert recs, "失败路径应落账"
        _a, k = recs[-1]
        assert k.get("ch") == "dingtalk" and k.get("errcode") == -1, (a, k)

    def test_dingtalk_send_success_no_errcode(self, monkeypatch, tmp_path):
        """成功路径零新键（账本 schema 零噪音）。"""
        monkeypatch.chdir(tmp_path)
        recs = []
        monkeypatch.setattr(_nm, "_append_push_history",
                            lambda *a, **k: recs.append((a, k)))

        class _R:
            text = '{"errcode":0,"errmsg":"ok"}'

            @staticmethod
            def json():
                return {"errcode": 0, "errmsg": "ok"}

        monkeypatch.setattr(_nm.httpx, "post", lambda *a, **k: _R())
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x", _LOG)
        assert d.send("t", "d") is True
        _a, k = recs[-1]
        assert k.get("errcode") is None, (a, k)


class TestTruncateNoteWrap:
    def test_note_lines_within_40_halfwidth(self):
        """截断尾注按段落级拆行后每行 ≤40 半角（40=20 全角手机行宽）。"""
        from core.notifier import _truncate_note
        note = _truncate_note(True)
        assert "\n\n" in note, "拆两行段落级换行（PC 不认单 \\n）"
        from core.alerter import _dw
        for ln in note.split("\n\n"):
            assert _dw(ln) <= 40, (ln, _dw(ln))

    def test_no_link_branch_wordform(self):
        """无链分支独立指引词面在位（test_v1589 钉面的单源锚）。"""
        from core.notifier import _truncate_note
        assert "本条已无跳转链接" in _truncate_note(no_link=True)
        assert "本条已无跳转链接" not in _truncate_note(False)


class TestWebuiErrcodePin:
    """控制台推送记录的错误码面：DEMO 样例随账本新字段同步现役
    形态（教学面错一字即误导解码），渲染消费点在案。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_demo_sample_mirrors_errcode(self):
        src = self._src()
        assert '"errcode": -1' in src, "DEMO pushlog 失败样例应带 errcode"

    def test_renderer_consumes_errcode(self):
        src = self._src()
        assert "p.errcode!=null" in src, "推送记录渲染应消费 errcode"


# ---- merged from tests/test_r274_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "report.py"), encoding="utf-8").read()


# ---------- A1: LAY_SHORT 跨端同值 ----------

def test_lay_short_matches_webui_stl():
    m = re.search(r"--stl:#([0-9a-fA-F]{6})", webui.PAGE)
    assert m, "webui PAGE 找不到 --stl 令牌"
    stl = tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    assert report.DESIGN.LAY_SHORT == (168, 76, 21), \
        "LAY_SHORT 未对齐 webui 已 AA 量测值 (168,76,21)"
    assert report.DESIGN.LAY_SHORT == stl, \
        f"report LAY_SHORT {report.DESIGN.LAY_SHORT} 与 webui --stl {stl} 跨端失值"


# ---------- A2: 图例衔接词条条件化 ----------

def test_layover_legend_word_conditional():
    w = report._layover_legend_word
    # lay_min=0：灰态解码（停时恒 MUTED 灰，两色词条均不可现）
    assert w([], 0) == "停时=衔接时长（未设下限）"
    assert w([("transfer", [{"layoverM": 120}])], 0) == "停时=衔接时长（未设下限）"
    # lay_min>0 且表内全部中转行过衔接滤网：只挂绿词条
    assert w([("transfer", [{"layoverM": 90}, {"layoverM": 300}])], 90) \
        == "绿停时=衔接达标"
    # 直飞组/compare 组不参与判定
    assert w([("direct", [{"price": 1000}]), ("compare", ["旧式串", {"a": 1}])], 90) \
        == "绿停时=衔接达标"
    # 短衔接行在场（防御位激活）：双词条全形态
    assert w([("transfer", [{"layoverM": 90}, {"layoverM": 30}])], 90) \
        == "橙红=衔接不足 · 绿停时=衔接达标"
    # layoverM 缺席按 0 计（缺键行视作最保守）
    assert w([("transfer", [{}])], 90) == "橙红=衔接不足 · 绿停时=衔接达标"


def test_layover_legend_wired():
    assert "_layover_legend_word(rows, lay_min)" in SRC, \
        "总表图例首行未接线条件化词条函数"


# ---------- A3: LAY_SHORT 着色防御位保留 ----------

def test_lay_short_branch_preserved():
    # r323 重构随迁：着色表达式改经 _has_lay 门（无停时行不挂衔接
    # 语义色，仅楼号行中性灰），LAY_SHORT 警示分支本体保留
    assert ("else DESIGN.LAY_SHORT) if lay_min > 0" in SRC
            and "if _has_lay else DESIGN.MUTED" in SRC), \
        "LAY_SHORT 着色防御位被移除（上游滤网放宽时无警示着色）"


# ---- merged from tests/test_r299_push.py ----

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# ---------------- P3-A 加粗字模入模型 ----------------

def test_bold_factor_fallback_in_range():
    """校准因子在保守带内：Pillow 实测（Windows msyh）或回退常量，
    两态都须落在 [1.05, 1.15]（实测 1.111；回退档须 ≥ 实测才保守）。"""
    f = alerter._TITLE_BOLD_ASCII
    assert 1.05 <= f <= 1.15, f


def test_dw_bold_ascii_inflates_cjk_not():
    """投影模型形态：ASCII 字符乘因子、CJK 方块字与全角标点不乘
    （CJK 加粗 advance 恒等是实测结论，不是近似）。"""
    import core.alerter as _a
    mono_cjk = _a._dw_bold("上海→海口")
    assert mono_cjk == _dw_line("上海→海口"), (mono_cjk, _dw_line("上海→海口"))
    assert _a._dw_bold("01/29") > _dw_line("01/29")


def test_daily_title_known_inline_nonregression():
    """生产词面非回归：r296 案1 样本（模型 37、ASCII 10 单位）在真实
    因子下加粗投影 ≈38.1 ≤40——内联档维持。"""
    out = report._route_section_title(
        ("上海", "海口"), "2027-01-29", dep_win=dep_win_txt("19:00", ""))
    assert out.split("\n\n")[0] == "#### 上海→海口 01/29（19:00后出发）", out


def test_daily_title_digit_heavy_demoted(monkeypatch):
    """行为牙齿：因子放大后数字密集标题投影破 40 必须降档（窗下沉
    引用行）——旧模型 38 代理对此恒放行（模型积分不带字模）。"""
    monkeypatch.setattr(alerter, "_TITLE_BOLD_ASCII", 1.6)
    out = report._route_section_title(
        ("机场", "机场东"), "2027-01-29", dep_win=dep_win_txt("07:00", "09:00"))
    first = out.split("\n\n")[0]
    assert "（07:00–09:00）" not in first, out  # 窗不再内联
    assert "> " in out and "07:00" in out, out  # 窗在引用行完整保留


def test_daily_title_pure_cjk_gains_margin(monkeypatch):
    """模型变准的方向二：因子=1.0（CJK 加粗零膨胀的实测外推）时投影
    =模型宽——40 预算内模型 39 标题内联（旧 38 代理降档为标题+引用行
    两段）。"""
    monkeypatch.setattr(alerter, "_TITLE_BOLD_ASCII", 1.0)
    nm_a, nm_b = "春" * 7, "秋" * 6   # 本体 5+26+箭头 2=33，加日期 6=39
    out = report._route_section_title((nm_a, nm_b), "2027-01-29")
    assert out.split("\n\n")[0] == f"#### {nm_a}→{nm_b} 01/29", out


def test_alert_title_same_law_real_and_model(monkeypatch):
    """告警侧同律（两路 #### 标题族同源）：现行实态=带数字窗的标题
    投影 40.3>40 → 窗下沉引用行（38 代理时代同形，非回归）；因子=1.0
    （模型准确侧）投影=模型 39 ≤40 → 窗内联——降档边界随真实字模
    走而非一刀切常量。"""
    out = Alerter._section_title("上海", "海口", "01/29", "（19:00后出发）")
    assert out == "#### ✈️ 上海→海口 01/29\n\n> （19:00后出发）\n\n", out
    monkeypatch.setattr(alerter, "_TITLE_BOLD_ASCII", 1.0)
    out1 = Alerter._section_title("上海", "海口", "01/29", "（19:00后出发）")
    assert out1 == "#### ✈️ 上海→海口 01/29（19:00后出发）\n\n", out1


def test_title_floor_bold_fits():
    """地板档恒达标：病理长名双侧逐字截后，加粗投影 ≤40（裁剪房按
    投影模型扣预算——投影超预算的标题族不出地板越线形态）。"""
    long_nm = "测" * 30
    out = report._route_section_title((long_nm, long_nm), "2027-01-29")
    first = out.split("\n\n")[0]
    assert alerter._dw_bold(first) <= 40, (first, alerter._dw_bold(first))


# ---------------- P3-B 构建端字节预算 ----------------

def test_budget_all_fit_byte_identical():
    """全量档预算内：逐字节原样（生效域门控——门判据=产物变短，
    非截断轮零变形）。"""
    blocks = [("A块\n\n", "A地\n\n"), ("B块\n\n", "B地\n\n")]
    out = report._daily_byte_budget("H\n\n", blocks, "T\n\n")
    assert out == "H\n\nA块\n\nB块\n\nT\n\n"


def test_budget_degrades_to_floors_with_note():
    """超预算：装不下的全量档降级为地板档（标题+价格判据恒在场），
    留痕行说明精简面；总字节 ≤ 预算。"""
    full = "明" * 4000 + "\n\n"          # ~8001B
    floor = "#### 上海→海口 01/29\n\n> 直飞 ￥1700 差￥250\n\n[🔍 查现价](u)\n\n"
    blocks = [(full, floor), (full, floor), (full, floor)]
    out = report._daily_byte_budget("H\n\n", blocks, "T\n\n", budget=12000)
    assert out.encode("utf-8").__len__() <= 12000
    assert out.count("#### 上海→海口 01/29") == 3      # 三节标题恒在场
    assert "已精简" in out                              # 留痕行
    assert "[🔍 查现价](u)" in out                      # 链接判据恒在场


def test_budget_floor_reserve_never_swallowed():
    """预留制不变量：地板档总额先扣，全量档在剩余空间竞争——首块
    全量装得下装、末块全量必让位地板，任何一节的价格行不随载体陪葬。"""
    full = "明" * 4000 + "\n\n"
    floor = "F\n\n"
    blocks = [(full, floor), (full, floor), (full, floor)]
    out = report._daily_byte_budget("H\n\n", blocks, "T\n\n", budget=11000)
    assert out.count("F\n\n") >= 1                      # 至少一节落地板
    assert out.startswith("H\n\n") and out.endswith("T\n\n")


# ---------------- P3-C 混合池第二层 ----------------

def test_mixed_pool_second_layer_catches_cross_lift():
    """互抬对机制（与告警链同序列同函数）：分类池（直飞/中转分组）
    两毒价互相压锚双逃；混合池补层后锚供给变宽双拦。"""
    def _row(pl, price, trans):
        return {"_platform": pl, "price": price,
                "transCity": "" if not trans else "郑州"}

    directs = [_row("qunar", 700, False), _row("ctrip", 700, False)]
    trans = [_row("fliggy", 2100, True), _row("tuniu", 2200, True)]
    # 分类池两遍（日报构建器既有序列）：直飞组/中转组各自标记
    for _g in (directs, trans):
        Alerter._mark_xchan(_g)
    assert not any(f.get("_xphan") for f in directs + trans), "分类池应双逃"
    out = directs + trans
    Alerter._mark_xchan(out)                            # 混合池补层
    assert [f["_platform"] for f in out if f.get("_xphan")] == \
        ["qunar", "ctrip"], "混合池应双拦互抬对"


def test_daily_builder_wires_mixed_layer():
    """接线钉：日报池构建器的标记序列=分类循环+混合池单遍（源码钉
    ——行为面由上测与告警链同函数保证）。"""
    src = open(report.__file__, encoding="utf-8").read()
    assert src.count("Alerter._mark_xchan(out)") == 1, "混合池补层未接线"


# ---------------- P3-D 同价合并判据同构 ----------------

def _mkt_row(code, dep="15:30", arr="18:55"):
    return {"code": code, "name": "国航" + code, "price": 1700,
            "depTime": dep, "arrTime": arr, "transCity": ""}


def test_market_merge_carries_identity():
    """同价且同班（brief 逐字相等）：合并单行、身份随 brief 在行
    （「- 两渠道 最低 国航CA8573 15:30-18:55 ￥1700」族）。"""
    pmins = {"qunar": (1700, True), "ctrip": (1700, True)}
    row = _mkt_row("CA8573")
    out = report._daily_market_fallback(
        pmins, {"qunar": row, "ctrip": dict(row)})
    assert "渠道 最低" in out, out
    assert "CA8573" in out, out                          # 航班身份在行
    first = out.rstrip("\n").splitlines()[0]
    assert _dw_line(first) <= 40, (first, _dw_line(first))


def test_market_same_price_diff_flights_keeps_rows():
    """价格相等而班次不同：不合并（纯价格判据曾把不同班并成一行丢
    身份）——逐渠道行如实分列。"""
    pmins = {"qunar": (1700, True), "ctrip": (1700, True)}
    out = report._daily_market_fallback(
        pmins, {"qunar": _mkt_row("CA8573"),
                "ctrip": _mkt_row("MU5137", dep="09:00", arr="12:20")})
    assert "渠道 最低" not in out, out
    assert "CA8573" in out and "MU5137" in out, out


def test_market_merge_without_rows_falls_back_price_lines():
    """行缺席防御（best_rows=None 旧调用形态）：维持逐渠道价格行，
    不产出无身份合并行。"""
    pmins = {"qunar": (1700, True), "ctrip": (1700, True)}
    out = report._daily_market_fallback(pmins)
    assert "渠道 最低" not in out, out
    assert "￥1700" in out, out


# ---------------- W1/W2 配置页语义配色（用户实报） ----------------

def test_cfg_platform_pills_channel_colors():
    """W1：配置页渠道胶囊按渠道识别色着装——五颗同蓝不可辨（语义
    配色审计维度）。模板带 pch+p-{plat} 类与渠道点；五渠道「浅底+色
    边+原色点」三件套规则在场；--c-* 令牌全渠道齐。"""
    import webui
    src = webui.PAGE
    assert 'class="chip pch p-${p}' in src, "胶囊模板未挂渠道类"
    assert '${srxPlatIcon(p)}${PLATS[p]}' in src, "渠道官方图标缺席"
    for p in ("qunar", "fliggy", "ctrip", "tongcheng", "tuniu"):
        assert (".chip.pch.p-" + p + ".on{background:color-mix" in src), p
        assert (".chip.pch.p-" + p + ".on .pdot{background:var(--c-"
                + p + ")}") in src, p


def test_route_head_color_semantics():
    """W2：航线头颜色跟读者视线走——中文名上蓝主色、三字码弱化灰
    （旧态：rtcode 蓝占色、城市名单色黑白）。"""
    import webui
    src = webui.PAGE
    rt = [ln for ln in src.splitlines() if ln.strip().startswith(".rtcode{")]
    assert rt and "var(--mut)" in rt[0] and "var(--blue)" not in rt[0], rt
    assert ".rhead>b{color:var(--blue)}" in src, "城市名未上主色"


# ---- merged from tests/test_v15110_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_near_txt_sub_half_percent():
    """0.21%（差￥4/线￥1900 实锤形态）：「擦边不足1%」不再出
    自我否定的「擦边0%」。"""
    assert _near_txt(0.0021) == "擦边不足1%"


def test_near_txt_half_percent_banker_boundary():
    """恰 0.5%：`.0f` 半点 banker 舍入到 0 的形态同样出「擦边不足1%」
    （边界含 0.5，防「擦边0%」从半点缝里回流）。"""
    assert _near_txt(0.005) == "擦边不足1%"


def test_near_txt_normal_percent_kept():
    """≥0.5% 且能舍到非零的形态维持原词面（词面漂移最小化）：
    0.6%→「擦边1%」、9%→「擦边9%」。"""
    assert _near_txt(0.006) == "擦边1%"
    assert _near_txt(0.09) == "擦边9%"


def test_kpi_tier_txt_sub1_summary():
    """KPI 摘要（日报 PNG summary 与 multi 总表同语言单源）：
    ￥1904 对线 ￥1900 出「直飞 ￥1904 擦边不足1%」。"""
    txt = kpi_tier_txt("直飞", 1904, 1900, False)
    assert "擦边不足1%" in txt
    assert "擦边0%" not in txt
    assert "<" not in txt


def test_webui_diff_pct_and_near_span_wordface():
    """webui JS 同病同修：diffTxt 百分比与擦边 span 均走 pctTxt
    不足1 分支（「差￥4（0%）」与「擦边0% · 未达标」同源收口）；
    边界 <=0.5 与 Python _near_txt 显式含边界精确同语言（两端
    半点向上同契约）；输入式与 near 判定同式 (p-t)*100/t（先除后
    减的浮点在 x.5 中点系统性向下偏，两端一档分叉）；词面不用
    尖括号（钉钉 L1 全禁族）。"""
    import webui
    assert "function pctTxt(np){return np<=0.5?'不足1':Math.round(np);}" \
        in webui.PAGE
    assert "pctTxt((p-t)*100/t)" in webui.PAGE
    assert "pctTxt((brief.price-th)*100/th)" in webui.PAGE
    assert "pctTxt((p/t-1)*100)" not in webui.PAGE


# ---- merged from tests/test_v1564_push.py ----

# ---- 横幅副行不复读主字 ----------

def test_banner_sub_strips_pure_tier_head():
    """❌ 支（实发 91%）：首段纯档位复读，副行只剩最近/另监控信息。"""
    h = _banner_html("❌ 全部未达标｜最近 乌→上 10/05 直飞差￥400｜另监控 乌→上 10/06")
    assert "未达标" in h          # 主字仍在
    assert "全部未达标" not in h  # 副行不复读
    assert "最近 乌→上 10/05 直飞差￥400" in h
    assert "另监控 乌→上 10/06" in h


def test_banner_sub_strips_word_keeps_route():
    """🔔 支：只剥档位词面，航线价信息保留。"""
    h = _banner_html("🔔 持续达标上→乌 09/25 中转￥1790｜另监控 乌→上 10/06")
    assert "持续达标" in h                    # 主字
    assert "持续达标上→乌" not in h           # 副行不再复读词面
    assert "上→乌 09/25 中转￥1790" in h      # 航线价保留


def test_banner_sub_strips_interp_and_single_seg():
    """/：🔔「持续达标·」剥词后行首不残留间隔号；
    无「｜」单段达标 title（单航线单日期形态）同样剥档位复读。"""
    h1 = _banner_html("🔔 持续达标·上→乌 10/05 真达标￥930")
    assert "持续达标" in h1
    assert "持续达标·" not in h1 and "·上→乌" not in h1
    assert "上→乌 10/05 真达标￥930" in h1
    h2 = _banner_html("❌ 全部未达标")
    assert "未达标" in h2 and "全部未达标" not in h2


def test_banner_sub_keeps_irregular_forms():
    """🚨/📈 支：主词剥除后副行保留航线价信息（r283 P3-3 主词改
    口径词「达标」后，🚨 支「达标！」异形复读被顺带治好——旧形态
    「主词不中整串保留」禁复活；📈 默认支不误剥维持）。"""
    h1 = _banner_html("🚨 达标！乌→上 10/05 直飞￥930")
    assert "达标！" not in h1  # 异形复读剥除（主词已是「达标 · 可出手」）
    assert "乌→上 10/05 直飞￥930" in h1  # 航线价信息保留
    assert "🚨" not in h1
    h2 = _banner_html("📈 价格走势与明细｜最近 上→乌")
    assert "价格走势与明细" in h2  # 默认横幅不误剥
    h3 = _banner_html("↩️ 回落出线｜最近 上→乌 10/05")
    assert "↩️" not in h3 and "回落出线" in h3  # ↩️ 支剥 emoji 留余段


# ---- 页脚按钮指引两态 ----------

def test_shell_footer_button_hint_two_states():
    desp = "正文"
    h0 = _email_shell_html("t", desp, launch="", with_snapshot=False)
    assert "链接请点上方按钮" not in h0
    h1 = _email_shell_html("t", desp, launch="https://x.example/",
                           with_snapshot=False)
    assert "链接请点上方按钮" in h1


# ---- _esc_md 引号转义 ----------

def test_esc_md_quotes():
    assert _esc_md('a"b<c>&d') == "a&quot;b&lt;c&gt;&amp;d"
    # href 属性上下文：launch 含引号不得破属性边界
    h = _email_shell_html("t", "d", launch='https://x/"onmouseover="x',
                          with_snapshot=False)
    assert '"onmouseover' not in h


# ---- 装配门形态防御 ----------

def _lg():
    return logging.getLogger("v1564")


def test_build_notifier_emails_non_list_ignored():
    assert build_notifier({"emails": {"user": "a@x.com"}}, _lg()) is None
    assert build_notifier({"emails": "a@x.com"}, _lg()) is None


def test_build_notifier_skips_bad_items():
    ns = build_notifier({"emails": ["str-item", 42,
                                    {"enabled": True, "user": "a@x.com",
                                     "password": "pw", "to": "b@x.com"}]},
                        _lg())
    assert ns is not None and not isinstance(ns, list)
    # 唯一有效项 → 单对象而非 Composite
    assert isinstance(ns, EmailNotifier)


def test_build_notifier_to_required_and_port_fallback():
    # to 缺失：不装配（免每轮空转不落盘不计数）
    assert build_notifier({"emails": [{"enabled": True, "user": "a@x.com",
                                       "password": "pw"}]}, _lg()) is None
    n = build_notifier({"emails": [{"enabled": True, "user": "a@x.com",
                                    "password": "pw", "to": "b@x.com",
                                    "port": "abc"}]}, _lg())
    assert isinstance(n, EmailNotifier) and n.port == 465


# ---- emailshot 端口预探快速降级 ----------

def test_emailshot_port_probe_fast_fail():
    from core.emailshot import _port_rejects, render_console_png
    import logging
    # 回环未监听端口 → 拒绝 → 预探 True，render 不进 Playwright 直接 None
    assert _port_rejects("http://127.0.0.1:1/") is True
    assert _port_rejects("") is False            # 空基址不判拒（上层已短路）
    assert _port_rejects("not a url") is False   # 解析失败保守放行走 goto
    lg = logging.getLogger("v1565")
    t0 = __import__("time").monotonic()
    assert render_console_png("http://127.0.0.1:1/", lg) is None
    assert __import__("time").monotonic() - t0 < 5, "端口拒绝未快速降级"


# ---- launch_is_public 单源 + webui 源钉 ----------

def test_launch_is_public_matrix():
    assert launch_is_public("") is False
    assert launch_is_public("http://127.0.0.1:8765/") is False
    assert launch_is_public("http://localhost:8765/") is False
    assert launch_is_public("http://192.168.1.8:8765/") is True


def test_alerter_launch_public_delegates_to_single_source():
    from core.alerter import Alerter
    src = inspect.getsource(Alerter._launch_public)
    assert "launch_is_public" in src, "alerter 判定应挂单源防回潮"


def test_webui_test_email_launch_filtered():
    """源钉+执行级（/ P0+）：测试邮件 launch 必经
    _test_email_launch（内含 launch_is_public），禁裸透传回潮；
    函数本体执行断言（曾内联表达式变量名 NameError 被吞，grep 钉
    抓不到执行错误）。"""
    src = webui_full_src()
    i = src.find('self.path == "/api/test-email"')
    assert i > 0
    seg = src[i:i + 5000]
    assert "launch=_test_email_launch()" in seg
    assert 'launch="http://%s/" % host' not in seg
    # chip.on 三色已令牌化，裸 hex 不回潮
    chip_lines = [ln for ln in src.splitlines() if ".chip.on .bd" in ln]
    assert chip_lines, "chip.on 规则丢失"
    assert all("#" not in ln for ln in chip_lines), \
        "chip.on 档色应挂令牌（裸 hex 回潮）"
    assert "--chip-on-warn" in src and "--chip-on-red" in src
    import webui
    try:
        webui._State.cfg = None
        assert webui._test_email_launch() == ""     # 未配置 base_url → 不带按钮
        webui._State.cfg = {"web": {"base_url": "http://127.0.0.1:8765"}}
        assert webui._test_email_launch() == ""     # 回环 → 过滤
        webui._State.cfg = {"web": {"base_url": "http://192.168.1.8:8765"}}
        assert webui._test_email_launch() == "http://192.168.1.8:8765"
    finally:
        webui._State.cfg = None                     # 全局态还原防污染


# ---- merged from tests/test_v202_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.CRITICAL)
LOG = logging.getLogger("t202p")

_PLATS = ["qunar", "ctrip", "fliggy", "tongcheng", "tuniu"]
_AIRLINES = ["春秋9C", "国航CA", "东航MU", "南航CZ", "海航HU"]
combo12 = [("URC", "SHA", "乌鲁木齐", "上海"),
           ("SHA", "URC", "上海", "乌鲁木齐"),
           ("CTU", "PEK", "成都", "北京"),
           ("PEK", "CTU", "北京", "成都"),
           ("CAN", "SZX", "广州", "深圳"),
           ("SZX", "CAN", "深圳", "广州"),
           ("HGH", "CKG", "杭州", "重庆"),
           ("CKG", "XIY", "重庆", "西安"),
           ("XIY", "KMG", "西安", "昆明"),
           ("KMG", "HAK", "昆明", "海口"),
           ("HAK", "HRB", "海口", "哈尔滨"),
           ("HRB", "HGH", "哈尔滨", "杭州")]


def _flight(price, plat, i, trans=None):
    code = f"{8800 + i}"
    f = {"price": price, "name": _AIRLINES[i % 5] + code,
         "code": _AIRLINES[i % 5][-2:] + code,
         "depTime": f"{6 + i // 3 % 12:02d}:{(i * 15) % 60:02d}",
         "arrTime": f"{9 + i // 3 % 12:02d}:{(i * 15 + 30) % 60:02d}",
         "_platform": plat}
    if trans:
        f["transCity"] = trans
        f["layover"] = 180
        f["totalDuration"] = "18时52分"
        f["arrTime"] = f"01:{(i * 7) % 60:02d}"
        f["transferBaggage"] = "direct"
    else:
        f.update({"cabin": "Y", "meal": "有小食", "prate": 86.4,
                  "plane": "738", "baggage": "20kg", "discount": "5.5折",
                  "labels": "含免费托运", "fewTicket": "余3张"})
    return f


def _route(fc, tc, fn, tn, ad=1900, at=1700):
    return Route(from_code=fc, from_name=fn, to_code=tc, to_name=tn,
                 dates=["2026-10-05"], alert_direct=ad, alert_transfer=at,
                 transfer_arrival_max="02:00", transfer_layover_min=90)


def _prices(route):
    out = []
    for d in route.dates:
        for pi in range(5):
            plat = _PLATS[pi % 5]
            fs = []
            for i in range(12):
                base = 1500 + (i * 37) % 900
                if i == 0:
                    fs.append(_flight(base, plat, i))
                elif i % 4 == 1:
                    fs.append(_flight(base + 200, plat, i, trans="西安"))
                else:
                    fs.append(_flight(base + 400, plat, i))
            out.append(FlightPrice(
                platform=plat, from_city=route.from_code,
                to_city=route.to_code, depart_date=d, price=fs[0]["price"],
                extra=json.dumps(fs, ensure_ascii=False),
                fetched_at="2026-09-29 14:00:00"))
    return out


def _digest(routes_prices, at="13800138000", monkeypatch=None):
    import report as _report
    if monkeypatch:
        monkeypatch.setattr(_report, "render_flights_table",
                            lambda *a, **k: None)
    a = Alerter(LOG, notifier=None, digest=True, at_mobile=at,
                platforms=list(_PLATS))
    return a._digest_payload(routes_prices, fresh=True)


def _prod12(monkeypatch=None, ad=1900, at=1700):
    rs = []
    for fc, tc, fn, tn in combo12:
        r = _route(fc, tc, fn, tn, ad=ad, at=at)
        secs = Alerter(LOG, notifier=None,
                       digest=True)._build_sections(r, _prices(r))
        rs.append((r, secs))
    return rs


def test_fallback_budget_and_at_floor(monkeypatch):
    """P1-1/P1-2：图挂兜底路径总量受构建端预算约束——兜底块超预算
    竞争让位（说明行在场），@手机号段地板预留恒落位（发送端 18000B
    截断不再触发、@ 触达不再随兜底路径蒸发）。"""
    p = _digest(_prod12(monkeypatch), monkeypatch=monkeypatch)
    desp = p["desp"]
    raw = len(desp.encode("utf-8"))
    # 构建端预算：15000B 头部 + 兜底头行/说明行/表头图行容差，
    # 发送端 18000B 截断点前留足安全带（修前实测 28296B）
    assert raw <= 16200, f"兜底路径 desp {raw}B 超构建端预算"
    assert "@13800138000" in desp, "@段被兜底块顶飞（地板预留失效）"
    assert "明细总表缺失" in desp


def test_fallback_demote_note_when_over(monkeypatch):
    """兜底块竞争让位时出说明行（防「推送数据缺失」观感）：
    超预算形态必有「因超长让位」说明；预算内小数据形态不出。"""
    big = _digest(_prod12(monkeypatch), monkeypatch=monkeypatch)["desp"]
    assert "因超长让位" in big
    rs2 = _prod12(monkeypatch)[:2]
    small = _digest(rs2, monkeypatch=monkeypatch)["desp"]
    assert "因超长让位" not in small
    assert "TOP" in small or "直飞最优" in small   # 兜底明细本体在场


def test_title_no_anchor_tail_drop(monkeypatch):
    """P2-1：锚点缺席（全部未设阈值）title 超限时逐条丢清单尾条——
    钉钉 [:60] 字符静默截的切点不再落在条目中间。"""
    rs = _prod12(monkeypatch, ad=0, at=0)
    p = _digest(rs, monkeypatch=monkeypatch)
    t = p["title"]
    assert len(t) <= 60, f"title {len(t)} 字符超钉钉硬截断上限"
    # 丢尾条后末条目完整（非「上→乌 10/05」半条形态）：
    # 尾部要么是完整条目（末段含日期短语），要么是状态前缀
    assert t.endswith(("05", "06")) or "｜" not in t


def test_section_title_long_city_trim():
    """P2-2：小节标题末档（城市名本体超宽）逐侧截尾——长自定义名
    极端形态标题行 60/40 曾不受控；截后标题行与引用行均 ≤40 半角。"""
    t = Alerter._section_title(
        "十二字超长自定义城市名甲乙丙", "另一个十二字超长城市名丁戊己",
        "10/05~10/06", " 06:00-09:00 出发")
    for ln in t.split("\n\n"):
        assert _dw(ln.rstrip()) <= 40, f"超宽行: {ln!r}"


def test_legacy_price_line_fit():
    """P2-3：legacy 价格行走 _fit_line——去抖涨跌注在场曾 47/40
    （全链唯一没走守卫的动态行）。真执行：涨跌注让位、价格判据
    地板档恒落；源码钉辅助锁降级链在位。"""
    from core.alerter import _fit_line
    base = "**价格**：￥1737（线￥1700）"
    out = _fit_line(f"- {base}（较上次推送降 ￥63）",
                    fallbacks=[f"- {base}", "- ￥1737"])
    assert _dw(out) <= 40
    assert out == f"- {base}"   # 涨跌注让位、判据保全
    assert _fit_line("- ￥1737", fallbacks=["- ￥1737"]) == "- ￥1737"
    src = open("core/alerter.py", encoding="utf-8").read()
    assert "_fit_line(f\"- {_pbase}{diff_txt}\"" in src
    assert 'f"- ￥{f[\'price\']:.0f}"' in src   # 地板档在案


def test_webui_test_push_copy():
    """P2-4：webui 测试推送词面——H1 级弃用（#### 纪律）、正文行
    ≤40 半角。"""
    import webui as _w
    src = webui_full_src()
    assert '"# ✅ 测试推送成功' not in src   # 旧 H1 词面（引号锚防 #### 子串误伤）
    assert "#### ✅ 测试推送成功" in src


def test_trend_single_point_centered():
    """M-3：单轮窗数据点居中（webui JS 同场景 0.5 同语言）——
    i/(N-1) 在 N==1 退化 0 曾把单点画在左轴上。"""
    src = open("report.py", encoding="utf-8").read()
    assert "if len(series) > 1 else 0.5" in src
