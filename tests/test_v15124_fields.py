# -*- coding: utf-8 -*-
"""r224 数据层写入端卫生双案（观测轮疑点落地）：

qunar DOM _via 写入端根治：_via 是 DOM 兜底路径状态机内部哨兵（转/停），
fliggy 同族 r223 已按「写入端直落真键」收口（normalize 读层 pop 保持
双保险）——qunar DOM 函数尾部无清洗，行携带 _via 出解析器（近 7 天
DOM 路径休眠零泄漏全靠 normalize 兜底，触发即重演 fliggy 式 extra
schema 污染，fliggy 存量 2981 条）。修法：函数尾部对 out 逐行把「停」
直落 stopover=True 后 pop（「转」语义已由状态机直落 transCity）。

stopAirports 孤儿键退役：PC binfo.stopAirports / H5 stopsAirPort 双路
在产、全仓零消费；DB 近 7 天 89947 行非空仅 3353（3.7%），7 个
distinct 值全为单机场城市机场全名，与 stopCitys（normalize 取首城落
stopCity 有消费）同层同源，机场级粒度零决策增量——载荷卫生 tam 先例，
行级删键（存量行 DB 原值不动，读层零依赖故无需清洗）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15124_fields.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

# 最小 DOM 文本（行形态照 test_core_units._DOM_SAMPLE 状态机口径）：
# 一组中转行 + 一组经停行
_DOM_MINI = """23:00

虹桥T1

10h55m

转

西安

+1天

09:55

乌鲁木齐天山

春秋9C8945 新海航｜长安航空9H8329

1836

17:05

浦东T2

7时

停

+1天

00:05

乌鲁木齐天山

南航CZ6976 波音737(中)

2692
"""


def test_qunar_dom_via_never_leaves_parser():
    """_via 哨兵不得随行出解析器（fliggy 同律写入端根治）：经停语义
    函数尾部直落 stopover=True，中转语义已由状态机直落 transCity；
    normalize 读层 pop 保持双保险（幂等不翻转）。"""
    out = QunarCrawler._parse_dom_flights(_DOM_MINI, "2026-10-05")
    assert len(out) == 2, out
    st = next(f for f in out if f["code"] == "CZ6976")
    t = next(f for f in out if f["code"] == "9C8945/9H8329")
    for f in (st, t):
        assert "_via" not in f, f
    assert st["stopover"] is True, st          # 「停」直落
    assert t["transCity"] == "西安", t          # 「转」既有直落不受影响
    # normalize 幂等：写入端直落后同判不变（读层双保险不翻转语义）
    from core.flightnorm import normalize as _norm
    assert _norm(dict(st), "2026-10-05")["stopover"] is True


def test_qunar_pc_row_never_carries_stopairports():
    """PC 路 stopAirports 孤儿键退役（载荷卫生 tam 先例）：行不再携带；
    stopCitys 数组 join 出口保留（normalize 取首城落 stopCity 有消费）。"""
    pc = json.dumps({
        "ret": True, "data": {"flights": [
            {"code": "FM9223", "minPrice": "2889", "crossDayDesc": "+1天",
             "transCity": "", "transTime": "",
             "binfo": {"airCode": "FM9223", "shortName": "上航",
                       "name": "上海航空", "depTime": "19:55",
                       "arrTime": "01:25", "date": "2026-10-05",
                       "arrDate": "2026-10-06", "flightTime": "5h30m",
                       "stopCitys": ["宜昌"],
                       "stopAirports": ["宜昌三峡机场"]}},
        ]}}, ensure_ascii=False)
    rows = QunarCrawler._parse_pc_flights(pc, "2026-10-05")
    assert rows, "PC 样本应解析出行"
    assert rows[0]["stopCitys"] == "宜昌", rows[0]
    assert "stopAirports" not in rows[0], rows[0]


def test_qunar_h5_row_never_carries_stopairports():
    """H5 路 stopsAirPort 同律退役：info/binfo2 两级兜底提取链撤
    stopAirports 半边，stopsCitys 半边保留（真值「西安;库尔勒」形
    分号归一口径不受牵连）。"""
    h5 = json.dumps({"data": {"flights": [{
        "minPrice": 2692, "code": "CZ6976",
        "extparams": "{\"stopFlight\":true}",
        "binfo": {"depTime": "17:05", "arrTime": "00:05",
                  "depDate": "2026-10-05", "arrDate": "2026-10-06",
                  "stopsCitys": "宜昌", "stopsAirPort": "宜昌三峡机场"},
    }]}})
    rows = QunarCrawler._parse_response_flights(h5)
    assert rows, "H5 样本应解析出行"
    assert rows[0]["stopCitys"] == "宜昌", rows[0]
    assert "stopAirports" not in rows[0], rows[0]


# ---- WebUI 审计三案（r224）：源码钉层 ----

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui_src():
    return open(os.path.join(_ROOT, "webui.py"), encoding="utf-8").read()


def test_webui_mtabsh_defined_in_541_760_band():
    """P1-1：541-760 带切换器吸顶（L1248 专属块）但 --mtabsh 只在 ≤540
    块定义——scroll-padding 消费裸 var 整条 calc 塌 0（声明 invalid 落
    auto），锚点落点被 header+吸顶条遮挡实测 102px。定义随消费带补齐：
    与 ≤540 同值 52px（宁多勿遮既定取舍；该带 montabs 无 height 声明，
    变量只喂 scroll-padding，零视觉副作用）。"""
    src = _webui_src()
    i_band = src.index("@media(min-width:541px) and (max-width:760px)")
    i_le540 = src.index("@media(max-width:540px)")
    i_def = src.index(":root{--mtabsh:52px}", i_band)
    assert i_band < i_def < i_le540, (i_band, i_def, i_le540)


def test_webui_mkact_preserves_template_tabindex():
    """P1-2：mkact 无条件 el.tabIndex=0 打穿 roving 初态——健康格/
    脉冲柱模板带 tabindex="0/-1"（每族首格 0 其余 -1 的 roving 纪律）
    且 role="button" 命中 mkactAll，改写发生在内联 onkeydown 早退之前
    →全族 400+ 格 Tab 逐格穿越回归。写法钉：模板已带 tabindex 属性者
    不改写，仅无属性元素补 0。"""
    src = _webui_src()
    assert "if(!el.hasAttribute('tabindex'))el.tabIndex=0;" in src
    assert "\n el.tabIndex=0;el.setAttribute('role','button');" not in src


def test_webui_rngchip_on_focus_ring_override_after():
    """P2-3：.rngchip.on 选中辉光与焦点环同特异性同属性（box-shadow），
    声明序靠后者胜（LESSONS 廿一§1）——环块在前被辉光盖掉，选中态
    chip 键盘聚焦零可见环。覆写块必须置尾（声明序在 .rngchip.on 之后）。"""
    src = _webui_src()
    i_on = src.index(".rngchip.on{")
    i_fix = src.index(".rngchip.on:focus-visible{")
    assert i_fix > i_on, (i_on, i_fix)


# ---- 推送审校 P0（r224）：总表次行极端超容兜底形态 ----

def _report_src():
    return open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()


def test_subline_overflow_fallback_keeps_core_group():
    """总表次行极端超容 plan=None 兜底形态（r224 推送审校 P0）：六档
    丢档链全败回退「全字段单行省略号」时可见头部恰是低优字段（机型·
    体量·廊桥），恒保组（准点/共享/余票/取消率）整段截丢。兜底串必须
    取末档丢弃域重建（_chain[-1]）——单行截断保住的可见头部即恒保组，
    决策字段不再随兜底路径蒸发。"""
    import re
    src = _report_src()
    assert re.search(r"for _drop, _ss in _chain:", src), "丢档链未变量化"
    m = re.search(r"if plan is None:\s*\n[^:]*?_rebuild\(\*_chain\[-1\]\)", src,
                  re.S)
    assert m, "plan=None 兜底串未取末档重建（恒保组被整截）"


def test_subline_overflow_extreme_row_renders(tmp_path):
    """极端超宽行端到端渲染不炸：plan=None 兜底分支只有极端样本走到，
    常规样本全链探不到（LESSONS 十九§14 空分支同族）。全字段超长值
    构造极端行，兜底路径真实执行且产物落盘。"""
    from report import render_flights_table
    f = {
        "platform": "qunar", "depDate": "2026-10-05", "price": 1264.0,
        "depTime": "07:10", "arrTime": "13:45", "airline": "海航",
        "flight_no": "HU7844", "cabin": "经济舱", "plane": "波音737(超长机型后缀词)",
        "planeSize": "大型机·宽体双通道远程旗舰机型", "bridgeRate": 88,
        "prate": 92, "meal": "正餐·点心·饮品三式服务包",
        "baggage": "免费托运23KG·手提7KG", "carryon": "手提行李额7KG",
        "labels": "经济舱售罄·含免费托运·老客专享·新客立减·会员日特惠·联程保障",
        "age": "限青年(16-23周岁)", "risk": "高风险政策",
        "share": "共享·南方航空CZ6993", "fewTicket": "票少",
        "cancelRate": 35, "lcc": True, "black": True,
        "discount": "4.9折超值折扣优惠", "transferBaggage": "recheck",
    }
    out = tmp_path / "t.png"
    rows = [("direct", [f], "✈️ 直飞最优 · 测试 10/05", {})]
    render_flights_table(rows, "极端超容行", str(out))
    assert out.exists() and out.stat().st_size > 1000


# ---- 推送审校 P1/P2（r224）：文案形态收口源码钉 ----

def _alerter_src():
    return open(os.path.join(_ROOT, "core", "alerter.py"),
                encoding="utf-8").read()


def test_kpi_pct_second_tier_dot_joined():
    """P1-2：KPI 行1 百分比尾注第二档间隔号连接——裸空格拼 pct 出
    「低￥50 3%」悬空百分数；「·」在确定安全字符集，与第一档全角
    括号态、第三档地板态成宽→窄降级链。r225 收单源 helper
    （_pct_fallback_forms，心跳两分支同源），内联档序表达式退役。"""
    src = _alerter_src()
    assert "forms = _pct_fallback_forms(base1, pct)" in src
    assert 'base1 + "·" + pct' not in src, "内联档序残留（须走 helper）"
    assert 'base1 + " " + pct' not in src, "旧裸空格档残留"


def test_daily_kpi_bold_tier_core_whole():
    """P1-3：日报 KPI 加粗范围=档位核整体（emoji+label+价），与主链路
    _kpi_block 同律一种实现（mini_kpi 单档粗为准）——旧「仅价粗」是
    同律两种实现，粗体分段语义漂移。"""
    src = _report_src()
    assert ('base = (f"**{core}**" if mark == TIER_EMOJI["qual"] + " "\n'
            '                    else core)') in src
    assert 'px = f"**{px}**" if mark == "🎯 "' not in src, "旧仅价粗残留"


def test_channel_market_lines_multiday_dated():
    """P1-4：图挂兜底「各渠道最低」行多日期带日期短标——sections 2+
    时两日期渠道价交错无主；单日期不带（常态不加状态标识律）。"""
    src = _alerter_src()
    assert "_multi = len(sections) > 1" in src
    assert 'pre = f"- {_dpre}{cn} 最低 "' in src
    assert 'f"- {_dpre}{cn} 最低 ￥{v:.0f}（全线价）"' in src


def test_skeleton_nb_keeps_word_boundary():
    """P2-5：去括号骨架档「（」换空格——双删把「→13:50（去哪儿）」
    剥成「13:50去哪儿」两词粘连；空格替换保词界净省 3 半角仍达标。"""
    src = _alerter_src()
    assert 'skeleton.replace("（", " ").replace("）", "")' in src
    assert 'skeleton.replace("（", "").replace("）", "")' not in src


def test_legacy_ops_split_second_segment_quoted():
    """P2-6：legacy「本轮无数据渠道」拆段后第二段补引用前缀——裸名单
    段与 ⚠️ 头视觉脱钩；names 经 _fit_line ≤40 半角=短块（钉钉引用块
    拆短块定律达标）。"""
    src = _alerter_src()
    assert 'heads + "\\n\\n> " + _fit_line(' in src
