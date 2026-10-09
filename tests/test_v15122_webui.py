# -*- coding: utf-8 -*-
"""r222 WebUI 令牌纪律五案（审计 _scratch/r222_webui_report.md P2-A~E）。

P2-A 卡头标题字号三档并存（16/15/14）→ #chartTitle/#calTitle 落 14px
    与同行 .seclab .zh 同档；
P2-B 健康图例色票 .hlb 死维度（12×6 从未生效，实渲染 .legend b 的
    18×4+环）→ 死声明删除；
P2-C 生产态 .cdt margin-right 与 .hdmeta gap 双计 16px → margin 删除
    （gap 单源）；
P2-D 微型大写标签字距五值并存（0.8/1/1.2/1.5/2）→ 两档令牌
    --ls1:1px（正文级微签）/ --ls2:2px（装饰英文签），notify 独立页
    令牌区同步（--pill 先例）；
P2-E 瓦片圆角 10px 档未令牌化（与 --r3=9px 同尺寸两值并存）→
    --r10:10px 令牌，主站+notify 全量收口，值不变零视觉漂移。

源码钉只锁「字符串在场与残留清零」；几何/computed 真相由真机探针
（control-browser 阶段）复验。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15122_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui as _w
    with open(_w.__file__, encoding="utf-8") as f:
        return f.read()


def test_p2a_cardhead_title_same_tier_as_seclab():
    s = _src()
    assert s.count('id="chartTitle" style="font-weight:700;font-size:14px"') == 1
    assert s.count('id="calTitle" style="font-weight:700;font-size:14px"') == 1
    # 旧裸 weight 无字号形态不回潮
    assert 'id="chartTitle" style="font-weight:700"></span>' not in s


def test_p2b_hlb_dead_dims_removed():
    s = _src()
    # .legend b（0,1,1）恒压过 .hlb（0,1,0）：12×6 死维度从未渲染
    assert ".hlb{display:inline-block;width:12px;height:6px" not in s
    # .hlh 维护纹修饰类保留（健康图例第四枚色票依赖）
    assert ".hlh{" in s


def test_p2c_cdt_margin_double_count_removed():
    s = _src()
    assert "margin-right:8px;font-size:11px" not in s
    # gap 单源后倒计时 chip 与 .hdmeta 相邻件同距（8px gap 唯一来源）
    assert ".hdmeta{display:inline-flex;align-items:center;gap:8px" in s


def test_p2d_letter_spacing_two_tier_tokens():
    s = _src()
    # 令牌定义：主站 + notify 独立页两处 :root（--pill 先例）；
    # r273 增设半像素档 --ls05（主站 ：root 独有，notify 无 0.5px 消费）
    assert s.count("--ls1:1px;--ls2:2px") == 2
    assert s.count("--ls05:.5px") == 1
    # 五值并轨：0.8 与 1.5 档清零
    assert "letter-spacing:.8px" not in s
    assert "letter-spacing:1.5px" not in s
    # 微签族消费点全走令牌：主站 9 + notify .top b = 10 处 --ls1
    assert s.count("letter-spacing:var(--ls1)") == 10
    # --ls2 消费四处：装饰英文签两处（.seclab .en / .grouplab .en）
    # + r273 收编的两处 15px 展示签（.pvbody .md-g 主站 / .md .g notify）
    assert s.count("letter-spacing:var(--ls2)") == 4
    assert s.count("letter-spacing:var(--ls05)") == 4
    # 裸字距声明清零（半像素/两像素档全入令牌）
    assert "letter-spacing:.5px" not in s
    assert "letter-spacing:2px" not in s
    # 14px 页题字距维持原值（h1 品牌字距非微签族，不入令牌）
    assert s.count("letter-spacing:1.2px") == 1


def test_p2e_tile_radius_token():
    s = _src()
    assert s.count("--r10:10px") == 2          # 主站 + notify
    assert s.count("border-radius:10px") == 0
    assert s.count("border-radius:0 10px 10px 10px") == 0
    # 主站 7 处 + notify 2 处 + .pldesp 单角变体 1 处
    assert s.count("border-radius:var(--r10)") == 9
    assert "border-radius:0 var(--r10) var(--r10) var(--r10)" in s
    # --r3=9px 值不动（uitest 在案钉：notify logo 9px）
    assert "--r3:9px" in s
