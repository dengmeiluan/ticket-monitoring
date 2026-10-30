# -*- coding: utf-8 -*-
"""baggage 词面 WebUI 承载（源码钉）：载荷透传 + title 悬停 + CSV 列。

ctrip pid 数字托运额（baggage 键）三端之一。qunar/tongcheng 存量行的
baggage 词面此前在 WebUI 零透出（载荷无此键）——本轮全渠道一并对等
（report 明细图 baggage 词条注释在案的「行李词面不对等」在 WebUI 侧
补齐）。承载位遵循 cabinCode 同款判决：明细次行段容量红线 14 已满
不加段元素，title 悬停 + CSV 列零布局风险。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v202_webui.py -q
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from webui import PAGE


def test_v202_webui_baggage_payload():
    # 行载荷透传 baggage（空串归一，前端空值不占位）——载荷在 _user_state
    # 后端段（PAGE 字符串之外），源文件级钉
    import webui as _w
    with open(_w.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert '"baggage": (f.get("baggage") or "").strip(),' in src


def test_v202_webui_baggage_title():
    # title 悬停承载：进 slot 条件（baggage 单独在场也弹 title），
    # labelNote 后插入 baggage 段（分隔符按「前文有无」判，
    # 只有 baggage 时不出头部分隔符）；carryon 段随后同链（v204）
    assert "(f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null)" in PAGE
    assert ("((f.labels||f.labelNote)&&f.baggage?'｜':'')"
            "+(f.baggage?he(f.baggage):'')"
            "+((f.labels||f.labelNote||f.baggage)&&f.carryon?'｜':'')"
            "+(f.carryon?he(f.carryon):'')") in PAGE
    # baggage 与 bizPrice/儿童价段之间的分隔符条件同步（漏改会出现
    # 「20KG公务￥N」粘连或头部孤立分隔符）
    assert ("((f.labels||f.labelNote||f.baggage||f.carryon)"
            "&&f.bizPrice!=null?'｜':'')") in PAGE
    assert ("(f.labels||f.labelNote||f.bizPrice!=null||f.baggage||f.carryon"
            ")?'｜':'')") in PAGE


def test_v202_webui_baggage_csv():
    # CSV 托运额列：表头（直挂后）与数据行（bagState 表达式后）同轮
    # 两端对齐，防列错位；「手提额」列随 v204 同链插入；经停列随后
    # 携 stopWin 窗口括注（v15115：'是(19:20-20:05)' 形态）
    assert ",'直挂','托运额','手提额','经停'," in PAGE
    assert ("(f.bagState==='direct'?'是':(f.bagState==='recheck'?'需转运':''))"
            ",f.baggage||'',f.carryon||'',"
            "f.stop?('是'+(f.stopWin?'('+f.stopWin+')':'')):''") in PAGE


def test_v202_narrow_tabs_sticky():
    # ≤540 档明细 tabs 行 sticky 吸顶：筛选/分类入口原在首屏折叠线
    # 下 ~150-180px（390 档 fltBtn top≈994 / vh 844），且数百行明细
    # 滚动中随时可筛是高频路径。视图切换器 montabs 同款吸顶（top 消费
    # --hdh 贴 header 实高，fallback 保 134），明细筛选条 top 联动
    # calc(var(--hdh,134px) + --mtabsh)（吸顶双条不重叠，高度改动一处
    # 变量全联动）。置尾纪律：断点块必须晚于基础 .tabs 声明（媒体块
    # 无「更严更后胜」，同特异性源码序后者胜）
    i540 = PAGE.index("@media(max-width:540px)")
    block = PAGE[i540:i540 + 1600]
    assert "#montabs{position:sticky;top:var(--hdh,134px)" in block
    assert ("#montab-details .tabs{position:sticky;\n"
            "    top:calc(var(--hdh,134px) + var(--mtabsh))" in block)
    assert "background:var(--card)" in block
    assert i540 > PAGE.index(".tabs{display:flex")
