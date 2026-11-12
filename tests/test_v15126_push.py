# -*- coding: utf-8 -*-
"""r226 推送层：日报标题末档守卫 + 降级链死档 + 图例误杀 + legacy
分段 + 三处小守卫（调研 _scratch/r226_report_push.md P1-1/P2×4/P3×3）。

- 日报小节标题（P1-1）：else 分支（带日期超宽下沉）后标题本体仍无
  末档守卫——双侧自定义城市对 51/40 直出窄屏折行断点不受控。同族
  已修三处（_section_title/_miss_chart_line/_top3_blocks），此处是
  家族最后漏网。修法：抽 _route_section_title 模块级单源（标题构造
  +守卫+日期下沉一体），主链与测试同源。
- _l2_fallbacks 死档（P2-1）：第 2 档 base+d 恒长于第 1 档
  base+cross（cross≤6.1 半角、d≥16）＝不可达死档且档序声明倒挂。
  删死档后链档宽严格递减。
- _is_legend_line 误杀（P2-2）：mini_kpi 双段行「📍 日期　🎯 直飞…
  ｜ 🟩 中转…」含 2 个档位点被判图例，从 ntfy/短信/弹窗整行剥除
  （第 2+ 日期 KPI 在强提醒通道静默蒸发）——📍 打头行识别式排除。
- mini split 档（P2-3）：两物理行被 _fit_line 当一行计量，逐行 ≤40
  从未验证。抽 _mini_split 单源：两段各过行宽守卫再拼接。
- legacy _push/_push_flight（P2-4）：bullet 间单 \\n 违 PC 渲染律
  （十§1 粘行），digest=false 启用即复现——全部段落级 \\n\\n。
- _ensure_jump_link（P3-3）：desp 尾 \\n\\n 后补链接行产三连换行。
- _alert_body（P3-4）：段间空行占 900 字短信额度——压缩。
- _cross_compare（P3-7）：>3 家只展两端且无「等N家」标——图挂兜底
  语境下中间渠道价不可恢复（总表图死时豁免依据失效），链尾补注。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15126_push.py -q
"""
import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report as _report  # noqa: E402
from core import alerter as _al  # noqa: E402
from core.alerter import Alerter  # noqa: E402
from core.notifier import _alert_body, _is_legend_line  # noqa: E402

_LOG = logging.getLogger("t15126")


def _dw(s):
    return _al._dw(s)


# ---- P1-1 日报小节标题 ----

def test_route_section_title_short_keeps_date_inline():
    """短城市对：#### 标题带日期（现行主形态保持）。"""
    t = _report._route_section_title(("乌鲁木齐", "上海"), "2026-10-05")
    assert t.startswith("#### 乌鲁木齐→上海 10/05")
    for ln in t.split("\n"):
        if ln.strip():
            assert _dw(ln) <= 40


def test_route_section_title_long_names_clamped():
    """双侧自定义长城市对（5+22+2+22=51/40 实录形态）：标题过末档
    双侧逐字截，日期下沉引用行，地板恒 ≤40。"""
    t = _report._route_section_title(
        ("乌鲁木齐地窝堡国际机场", "上海虹桥国际机场"), "2026-10-05")
    lines = [ln for ln in t.split("\n") if ln.strip()]
    assert all(_dw(ln) <= 40 for ln in lines)
    assert "→" in lines[0]           # 箭头恒在（方向可辨）
    assert any("10/05" in ln for ln in lines[1:])   # 日期下沉不丢


def test_route_section_title_single_side_long():
    """单侧超长（无箭头名称形态回退）：整串截保地板。"""
    t = _report._route_section_title(
        ("乌鲁木齐地窝堡国际机场航站楼航站楼航站楼", "上海"), "2026-10-05")
    lines = [ln for ln in t.split("\n") if ln.strip()]
    assert all(_dw(ln) <= 40 for ln in lines)


def test_route_section_title_both_sides_saturated():
    """双侧饱和反例（Soldier C-1）：双侧 9 汉字时地板行曾 41/40
    越界——room 未扣箭头宽（_miss_chart_line 有扣 _sep 本函数照抄
    时丢失）。地板恒 ≤40（守卫链尾恒达标律）。"""
    t = _report._route_section_title(
        ("北京大兴国际机场A", "上海虹桥国际机场B"), "2026-10-05")
    lines = [ln for ln in t.split("\n") if ln.strip()]
    for ln in lines:
        assert _dw(ln) <= 40, f"地板越界 {ln!r} dw={_dw(ln)}"
    assert "→" in t


def test_route_section_title_middle_branch_sinks_date():
    """中分支钉（去日期下沉档：带日期超宽、标题本体达标窗口）：
    日期下沉引用行、标题行不含日期、逐行 ≤40——该分支此前无钉
    （十九§14 空分支盲区家族）。"""
    t = _report._route_section_title(
        ("乌鲁木齐地窝堡国际机场", "虹桥机场"), "2026-10-05")
    lines = t.split("\n")
    assert lines[0] == "#### 乌鲁木齐地窝堡国际机场→虹桥机场"
    assert any(ln.strip() == "> 10/05" for ln in lines)
    for ln in lines:
        if ln.strip():
            assert _dw(ln) <= 40, ln


# ---- P2-1 _l2_fallbacks 死档 ----

def test_l2_fallbacks_strictly_narrowing():
    """死档删除：d 档（涨跌注 ≥16 半角）恒宽于 cross 档（≤6.1）
    ——不可达死档且档序声明倒挂，删除后链上无 d 档；跨天辨识信息
    （十九§9 档序：辨识信息先于次要信号被丢）在剥名档中保序。"""
    tiers = _al._l2_fallbacks(
        "新海航｜海南航空 HU7849 07:10→13:45", "(+1天)",
        " ｜ 较上轮 ↑￥50")
    assert not any("较上轮" in t for t in tiers), tiers
    assert any("(+1天)" in t for t in tiers), tiers
    assert _dw(tiers[-1]) <= 40, tiers


def test_l2_fallbacks_short_and_floor():
    """剥名档与逐字截地板仍在链上（双名形态的地板=身份本体截断）。"""
    tiers = _al._l2_fallbacks(
        "新海航｜海南航空 HU7849 07:10→13:45", "(+1天)",
        " ｜ 较上轮 ↑￥50")
    assert any(t.startswith("海南航空") for t in tiers)   # 剥营销名档
    assert _dw(tiers[-1]) <= 40                            # 地板恒达标


# ---- P2-2 图例误杀 mini 行 ----

def test_legend_line_mini_kpi_double_dot_not_legend():
    """mini_kpi 双段双点行（第 2+ 日期 KPI）：📍 打头=正文行，
    不得判图例（判图例即从弹窗/电话/短信整行剥除）。"""
    assert not _is_legend_line(
        "📍 10/06　🎯 直飞[￥1987](https://x) ｜ 🟩 中转[￥1752](https://y)")


def test_mini_split_text_floor_clamps():
    """无链接可剥的超长段（病理形态）：段级逐字截地板恒达标
    （守卫链尾恒达标律——无地板时 _fit_line 全超原样吐=静默失效）。"""
    segs = ["🎯 直飞￥1987（行情价较上轮上涨幅度很大需要长注解释）",
            "🟩 中转￥1752（行情价较上轮上涨幅度很大需要长注解释）"]
    out = _al._mini_split("📍 10/06　", segs)
    for ln in out.split("\n"):
        if ln.strip():
            assert _al._disp_dw(ln) <= 40, ln


def test_legend_line_still_detected():
    """真图例行（聚合头行后的档位词条行）识别不回归。"""
    assert _is_legend_line("🎯 真达标 · 🟩 行情破线 · 🟨 擦边")
    assert _is_legend_line("> 🎯 真达标 · 🟩 行情破线")


def test_alert_body_keeps_mini_kpi():
    """强提醒通道正文：第 2+ 日期 KPI 行不再被剥（潜伏误杀收口；
    📍 装饰符在转写层剥离、日期与档位内容保留）。"""
    desp = "#### 头\n\n📍 10/06　🎯 直飞￥1987 ｜ 🟩 中转￥1752\n\n"
    body = _alert_body(desp)
    assert "10/06" in body and "直飞" in body and "中转" in body


# ---- P2-3 mini split 档逐行守卫 ----

def test_mini_split_each_line_in_budget():
    """超宽双段：拆行档两物理行各自过行宽守卫（渲染宽按 _disp_dw
    单源口径——markdown 链接剥算 text 宽；旧码把含 \\n\\n 的 split
    整行计量，两行 ≤40 从未被逐行验证）。"""
    segs = ["🎯 直飞[￥1987](https://flight.example.com/very/long/url1)",
            "🟩 中转[￥1752](https://flight.example.com/very/long/url2)"]
    out = _al._mini_split("📍 10/06　", segs)
    assert out.count("\n\n") >= 1          # 拆行=两物理行
    for ln in out.split("\n"):
        if ln.strip():
            assert _al._disp_dw(ln) <= 40, ln


def test_mini_split_narrow_single_line():
    """窄形态（≤40）：单行「 ｜ 」联接原样（拆行是超宽才走的档）。"""
    segs = ["🎯 直飞￥987", "🟩 中转￥752"]
    out = _al._mini_split("📍 10/06　", segs)
    assert "｜" in out and "\n" not in out.rstrip()


# ---- P2-4 legacy 推送分段 ----

class _FakeN:
    def __init__(self):
        self.calls = []

    def send(self, title, desp, **kw):
        self.calls.append((title, desp))
        return True


def _mk_alerter():
    n = _FakeN()
    a = Alerter(_LOG, notifier=n, storage=None, digest=True,
                platforms=["qunar"])
    return a, n


def _route(**kw):
    base = dict(from_code="URC", to_code="SHA",
                from_name="乌鲁木齐", to_name="上海",
                dates=["2026-10-05"], alert_threshold=1500.0)
    base.update(kw)
    return SimpleNamespace(**base)


def _no_lone_newlines(desp: str) -> bool:
    """段落律（十§1）：正文每个 \\n 都必须是 \\n\\n 的组成部分。"""
    i = 0
    while i < len(desp):
        if desp[i] == "\n":
            j = i
            while j < len(desp) and desp[j] == "\n":
                j += 1
            if j - i != 2:
                return False
            i = j
        else:
            i += 1
    return True


def test_push_flight_paragraph_breaks():
    a, n = _mk_alerter()
    f = {"name": "南航CZ6901", "price": 1400.0, "depTime": "10:00",
         "arrTime": "22:10", "transCity": "北京", "layoverT": "1:20",
         "totalDuration": "12时10分", "crossDayDesc": "", "_platform":
         "qunar"}
    ok = a._push_flight(_route(), "2026-10-05", f, "transfer", 1500.0,
                        None, 5, "qunar")
    assert ok and n.calls
    assert _no_lone_newlines(n.calls[0][1]), repr(n.calls[0][1])


def test_push_paragraph_breaks():
    a, n = _mk_alerter()
    p = SimpleNamespace(price=1400.0, platform="qunar",
                        fetched_at="2026-10-05 10:00")
    ok = a._push(_route(), "2026-10-05", p, None)
    assert ok and n.calls
    assert _no_lone_newlines(n.calls[0][1]), repr(n.calls[0][1])


# ---- P3-3 跳转链接三连换行 ----

def test_jump_link_no_triple_newline():
    a, _n = _mk_alerter()
    route = _route()
    desp = "#### 头\n\n- 行\n\n"
    out = a._ensure_jump_link(
        desp, route,
        {"date": "2026-10-05", "best_direct": None,
         "best_transfer_mkt": None, "best_transfer": None,
         "all_flights": []})
    assert "\n\n\n" not in out
    assert "](http" in out


# ---- P3-4 短信额度空行压缩 ----

def test_alert_body_squeezes_blank_lines():
    body = _alert_body("MU1234 ￥500\n\n- 行A\n\n- 行B\n\n")
    assert "\n\n" not in body
    assert "行A" in body and "行B" in body


# ---- P3-7 同班比价家数注 ----

def test_cross_compare_count_tag_over_three():
    """>3 家只展最低/最高两端：链尾补半角 (等N家)——图挂兜底语境
    中间渠道价在文本不可恢复，家数注是「链非全量」的对账锚。"""
    fs = []
    for plat, px in (("ctrip", 1700.0), ("qunar", 1800.0),
                     ("tongcheng", 1900.0), ("fliggy", 2000.0)):
        fs.append({"_platform": plat, "price": px, "name": "MU1234",
                   "depTime": "08:00", "arrTime": "11:20",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05"})
    sections = [{"date": "2026-10-05", "pool": fs}]
    desp = Alerter._cross_compare(sections, top_n=4)
    assert "(等4家)" in desp


def test_cross_compare_three_families_no_count_tag():
    """≤3 家负分支：链全量直出、无家数注（(等N家) 只在 >3 家
    图挂兜底语境出现；恒拼误改由此钉抓红）。"""
    fs = []
    for plat, px in (("ctrip", 1700.0), ("qunar", 1800.0),
                     ("tongcheng", 1900.0)):
        fs.append({"_platform": plat, "price": px, "name": "MU1234",
                   "depTime": "08:00", "arrTime": "11:20",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05"})
    sections = [{"date": "2026-10-05", "pool": fs}]
    desp = Alerter._cross_compare(sections, top_n=4)
    assert "(等" not in desp
