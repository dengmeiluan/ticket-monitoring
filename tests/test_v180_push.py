# -*- coding: utf-8 -*-
"""v1.5.80 推送审校落地钉（audit_v180_push P1-1 + P2 精修）。

P1-1 desp 字节预算（构建端降级，非重发非重试）：24 航线极端形态
desp 20685~21701B 超钉钉 18000B 硬限，截断保头部把尾部明细总表段
（比价唯一载体）与 @手机号段结构性切掉——构建端预算降级：非达标
航线小节降为 📍 mini 行，保总表/@段先落位 + 降级说明行在场。
P2 精修：_dedup_tie 键 code-or-name 渠道写法差漏合并（生产图
HU7849 ￥2310 双行实锤）→ name 尾航班号归一参与键；(税前) 全角化；
建议行档位词粘连；恰达线 0% 括注省略；「直挂未标注」仅在直挂筛选
航线出（假警示）；NOTIFY 截断尾注语义。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v180_push.py -q
"""
from core.alerter import Alerter, _dedup_tie, _low_txt
from core.models import Route


# ---- P2-2 _dedup_tie 键归一：name 尾航班号参与键 ----

def _tie_row(code, name, plat):
    return {"code": code, "name": name, "depTime": "14:00",
            "arrTime": "00:40", "transCity": "郑州",
            "crossDayDesc": "+1天", "stopover": 0, "price": 2310.0,
            "_platform": plat}


def test_dedup_tie_name_tail_code_merges():
    """一端 code 缺失回退 name、另一端 code=HU7849 → 渠道写法差
    曾不合并（生产图双行占 TOP5 双槽）；name 尾航班号归一后合并。"""
    rows = [_tie_row("", "新海航｜天津航空HU7849", "qunar"),
            _tie_row("HU7849", "海南航空", "ctrip")]
    out = _dedup_tie(rows)
    assert len(out) == 1 and out[0]["_tie_n"] == 2


def test_dedup_tie_different_flight_not_merged():
    """真不同班（尾号不同）不合并——归一只放行写法差，不吞差异。"""
    rows = [_tie_row("", "新海航｜天津航空HU7849", "qunar"),
            _tie_row("HU7850", "海南航空", "ctrip")]
    assert len(_dedup_tie(rows)) == 2


def test_dedup_tie_price_diff_not_merged():
    """同班不同价（价差即比价信息）不合并。"""
    a = _tie_row("", "新海航｜天津航空HU7849", "qunar")
    b = _tie_row("HU7849", "海南航空", "ctrip")
    b["price"] = 2315.0
    assert len(_dedup_tie([a, b])) == 2


# ---- P2-5 (税前) 全角化（潜伏词面，pad 旋钮开启即混入） ----

def test_low_txt_fullwidth_paren(monkeypatch):
    import core.alerter as _al
    monkeypatch.setattr(_al, "FLIGGY_TAX_PAD", 100)
    out = _low_txt(1500, 1600, "fliggy")
    assert "（税前）" in out and "(税前)" not in out


# ---- P2-6 建议行档位词粘连「直飞真达标」 ----

def test_suggest_line_tier_separator():
    al = Alerter.__new__(Alerter)
    rt = Route("URC", "乌鲁木齐", "SHA", "上海", ["2026-10-05"],
               alert_direct=1600, alert_transfer=1700)
    bd = {"price": 1526.0, "name": "南航CZ6975", "depTime": "08:00",
          "arrTime": "12:20", "_platform": "ctrip", "transCity": ""}
    s = {"date": "2026-10-05", "best_direct": bd, "best_transfer": None,
         "best_transfer_mkt": None, "all_flights": [bd]}
    r = al._suggest_line(rt, s)
    assert ("直飞 真达标" in r) or ("直飞·真达标" in r), \
        "建议行 label 与档位词粘连（直飞真达标连读）"


# ---- P2-7 恰达线 0% 括注观感矛盾 ----

def test_kpi_pct_below_1pct_omitted():
    """<1% 的 pct 括注省略（「低￥5（0%）」数字真实但并排读像矛盾；
    与 _delta_txt/<1% 横盘省略同哲学）。源码钉：两处 pct 构造带
    <1% 门控。"""
    import webui as _w  # noqa: F401  占位防误删
    src = open("core/alerter.py", encoding="utf-8").read()
    n_gate = src.count("and _p >= 1") + src.count("and _pt >= 1")
    assert n_gate >= 2, f"pct <1% 省略门控缺失（命中 {n_gate}/2）"


# ---- P2-4 「直挂未标注」仅在直挂筛选航线出（假警示） ----

class TestDigestBudget:
    """P1-1 字节预算降级（真执行级，with_tables=False 预览同路径）。"""

    @staticmethod
    def _al():
        al = Alerter.__new__(Alerter)
        al.platforms = ["ctrip", "qunar"]
        al.at_mobile = "13800138000"
        al.round_charts = {}
        al.storage = None
        return al

    @staticmethod
    def _flight(price, plat="ctrip", trans=False):
        f = {"price": float(price), "name": "南航CZ6975",
             "code": "CZ6975", "depTime": "08:00", "arrTime": "12:20",
             "_platform": plat, "transCity": "", "crossDayDesc": "",
             "stopover": 0, "transferBaggage": "", "stopCity": ""}
        if trans:
            f.update({"transCity": "郑州", "arrTime": "00:40",
                      "crossDayDesc": "+1天", "layoverT": "2:15"})
        return f

    def _rs_list(self, n=24, hit_first=True):
        """n 条航线（首条达标、其余超线）；直挂筛选未配置。"""
        out = []
        for i in range(n):
            rt = Route(f"U{i:02d}", f"城市{i}", f"S{i:02d}", f"目的{i}",
                       ["2026-10-05"], alert_direct=1600,
                       alert_transfer=1700)
            bd = self._flight(1500 if (hit_first and i == 0) else 2410)
            bt = self._flight(1520 if (hit_first and i == 0) else 2470,
                              trans=True)
            sec = {"date": "2026-10-05", "best_direct": bd,
                   "best_transfer": bt, "best_transfer_mkt": bt,
                   "all_flights": [bd, bt], "seen_plats": ["ctrip"],
                   "xphans": [], "top_transfer": [bt]}
            out.append((rt, [sec]))
        return out

    def test_desp_within_dingtalk_budget(self):
        """24 航线 desp 字节数收敛到钉钉 18000B 硬限内（留 notifier
        截断缓冲）。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        size = len(p["desp"].encode("utf-8"))
        assert size <= 17500, f"desp {size}B 仍超预算（截断丢总表/@段）"

    def test_demotion_note_and_mini_rows(self):
        """降级发生时：说明行在场 + 非达标航线出 📍 mini 行。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        # 词面 v181 起压缩 ≤40 半角（原「部分航线仅列关键价（明细见
        # 总表）」47 半角超手机行宽红线，P1-1 修复）
        assert "仅列关键价" in p["desp"], "降级说明行缺失"
        assert "📍" in p["desp"], "非达标航线 mini 行缺失"

    def test_hit_route_full_block_kept(self):
        """达标航线小节恒全量（🎯 档加粗价格在场），永不降级。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        assert "￥1500" in p["desp"] and "城市0" in p["desp"], \
            "达标航线 KPI 被误降级"

    def test_at_mobiles_tail_kept(self):
        """@手机号段恒在 desp 尾部（截断高危段先落位）。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        assert p["at_mobiles"] == ["13800138000"]
        assert "@13800138000" in p["desp"][-400:], "@段未保尾部"

    def test_small_payload_untouched(self):
        """3 航线常规形态不触发降级（无说明行，KPI 全量）。"""
        p = self._al()._digest_payload(self._rs_list(3), with_tables=False,
                                       with_charts=False)
        assert "部分航线仅列关键价" not in p["desp"], "常规形态误降级"
        assert p["desp"].count("￥2410") >= 2, "常规形态 KPI 缺失"

    def test_direct_note_not_on_unfiltered_route(self):
        """「直挂未标注」仅在 transfer_baggage=direct 航线出——
        未配置直挂筛选时它是中性信息却长着警示脸（假警示）。"""
        p = self._al()._digest_payload(self._rs_list(3), with_tables=False,
                                       with_charts=False)
        assert "直挂未标注" not in p["desp"], \
            "未配置直挂筛选的航线出「直挂未标注」假警示"


# ---- report.py 源码钉：图内词面单源与新字段承载 ----

def test_tbl_ring_legend_unified():
    """P2-1 环注形状词与表图图例统一「描绿」（「细绿」是旁路词面，
    跨图扫读需两次翻译）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "细绿" not in src, "「细绿」旁路词面残留"
    assert "○描绿" in src, "环注描绿词面缺失"


def test_agepolicy_and_transfertax_in_png():
    """决策字段进总表图（webui 有、图无）：agePolicy 词面「限青年价」
    （PNG 端无 ⚠——U+26A0 在 msyh 无字形渲染 tofu，webui 浏览器端
    保留 ⚠）；transferTax 进次行槽。"""
    src = open("report.py", encoding="utf-8").read()
    assert "agePolicy" in src, "agePolicy 未进总表图"
    assert "⚠" not in src.split('("age"')[1][:120], \
        "PNG 端 agePolicy 词面带 ⚠（msyh 无字形渲染 tofu）"
    assert "transferTax" in src, "transferTax 未进总表图"


def test_ops_suffix_measured():
    """P2-9 ops「等N条」尾注过量宽度量（直接尾拼在 _fit_text 截断时
    最先丢，对账留痕失效）。"""
    src = open("report.py", encoding="utf-8").read()
    assert '_ops_lines[-1] += f" 等{len(_rest)}条"' not in src, \
        "ops 尾注仍直接尾拼（不度量）"


def test_notifier_truncate_note_semantics():
    """P1-1 配套：截断尾注点明丢失面（泛化「已截断」不说丢了什么）。"""
    src = open("core/notifier.py", encoding="utf-8").read()
    # v185 审校补 @提醒段：@高亮结构性垫底，被切即触达蒸发
    assert "尾部明细总表/@提醒/对账段未收入" in src, "截断尾注缺丢失面语义"
