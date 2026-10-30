# -*- coding: utf-8 -*-
"""r295 精细化轮落地钉面（波 2 WebUI 审计 + 波 3 推送审校立案）。

P3-E（推送审校）：`_section_title` 首档「时段窗整行内联」的阈值恰卡
零缓冲——#### 标题在钉钉渲染为标题样式（加粗/字号差），计宽模型按
常规字模计量，恰 40 的标题真实渲染有越线折行风险（折行断点不受控，
时段窗是出发辨识信息）。生产实锤样本 `#### ✈️ 上海→海口 01/29
（19:00后出发）` 实测 40.00。首档阈值留 2 半角缓冲（40→38），
39-40 带整段下沉引用行；短标题（≤38）仍内联（首档保持活档非恒下沉）。

P2-1（WebUI 审计）：概览渠道胶囊「全线最低」价是行情面（行级收集，
不过路由出发时段窗），明细列表是购买面（元素级过 _keep 窗）——胶囊
价对应航班被窗挡在池外时，点击「只看该渠道明细」后任何筛选复位都
找不回该价（demo 实测五渠道差 85-270 且无出口解释）。修法：点击
toast 在「该渠道全线最低不在明细池」时追加教学句（前端纯词面，零
后端语义改动）；title 词面「含未过约束班次」精确化为「含时段窗外
班次」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r295_landing.py -q
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.alerter import Alerter, _dw
from webui import PAGE


# ---------- P3-E：小节标题零缓冲 ----------

def test_p3e_window_sinks_at_zerobuffer():
    # 生产实锤样本（恰 40.00）：时段窗不再内联进 #### 行、下沉引用行；
    # #### 标题本体 ≤38（加粗字模缓冲）
    out = Alerter._section_title("上海", "海口", "01/29", "（19:00后出发）")
    assert not out.startswith("#### ✈️ 上海→海口 01/29（")
    head = out.split("\n", 1)[0]
    assert "> （19:00后出发）" in out
    assert _dw(head) <= 38


def test_p3e_short_title_still_inline():
    # 非回归：总宽 ≤38 的短标题（短城市名自定义形态）仍走内联首档
    out = Alerter._section_title("沪", "穗", "01/29", "（19:00后出发）")
    assert out.startswith("#### ✈️ 沪→穗 01/29（19:00后出发）")
    assert "> （19:00后出发）" not in out


def test_p3e_no_window_tier2_unchanged():
    # 非回归：无时段窗标题走第二档 head-only，形态不变
    out = Alerter._section_title("上海", "海口", "01/29", "")
    assert out == "#### ✈️ 上海→海口 01/29\n\n"


def test_p3e_headonly_zerobuffer_sinks(monkeypatch):
    # head-only 恰卡带按加粗投影判（P3-A 字模入模型，改写旧 38 代理
    # 钉）：投影 ≤40 内联（纯 CJK 39 带真实放得下，不再一刀切下沉）；
    # 投影破 40（因子放大构造）下沉引用行（日期随沉），地板产出过
    # 投影预算
    import core.alerter as _al
    monkeypatch.setattr(_al, "_TITLE_BOLD_ASCII", 1.0)
    out = Alerter._section_title("超长出发名呀", "超长到达名", "10/05", "")
    assert "10/05" in out.split("\n\n")[0], out
    monkeypatch.setattr(_al, "_TITLE_BOLD_ASCII", 1.6)
    out2 = Alerter._section_title("超长出发名呀", "超长到达名", "10/05", "")
    assert "> 10/05" in out2, out2
    assert _al._dw_bold(out2.split("\n\n")[0]) <= 40, out2


# ---------- P2-1：chip 点击教学 ----------

def test_p2x_chip_gap_predicate():
    # 教学判定（渲染期烘焙，onclick 运行期无 x/m 作用域——helper 形态
    # 在属性里按全局解析必 ReferenceError）：明细池非空且池内无
    # 「胶囊价同值行」才教。|f.price-m[1]|<1 容差吃 round；
    # FLIGGY_TAX_PAD>0 时垫差需并入容差（现行归零定标下成立）
    assert "!(x.flights||[]).some(" in PAGE
    assert "f=>f.plat===m[0]&&Math.abs(f.price-m[1])<1" in PAGE


def test_p2x_chip_toast_teaching():
    # 点击 toast 条件教学句：缺口在场才追加（常态零噪音）；
    # 教学句与渠道名/价格在渲染期拼为字面量注入 onclick
    assert ("_gap?'；￥'+m[1]+"
            "' 为时段窗外等未入明细班次，不在下方列表':''") in PAGE


def test_p2x_chip_title_wordface():
    # title 词面精确化：主因「时段窗外」点名；旧词面禁复活
    assert "渠道全线报价最低（含时段窗外班次，未必可出手）" in PAGE
    assert "含未过约束班次" not in PAGE
