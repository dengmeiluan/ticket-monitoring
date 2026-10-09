# -*- coding: utf-8 -*-
"""r235 WebUI P2 批源码钉（UI 审计 _scratch/r235_ui_audit.md 落地）：

- P2-1 图例-数据一致性（数据维度）：空系列时对应图例色票隐藏
  （r230 已做模式维度，本条补数据维度）；K线簇位句单簇条件化；
  日历档位图例仅 th>0 拼接（装饰信号在场×数据为零，二十三§6 族）。
- P2-2 亮色渠道识别色票非文字对比度 ≥3:1（WCAG 1.4.11）：飞猪
  #e07f2a→#c2661a、途牛 #d29922→#a87b16（暗色 7.8+ 本过不动）；
  改期微图低价棒 rgba(--okrgb,.45) 1.6:1 → 实色 --green。
- P2-3 `.hint` 删 opacity:.92 税（11px --mut 余量仅 0.05，渲染
  漂移即翻车；先例：斑马 .price.brk 余量 0.026 单点提档）。
- P2-4 明细 tabs 档位图例 761-860 带孤行：flex-basis:100% 左贴行首
  （十七§7 flex 孤格族）。
- P2-5 canvas 高度 clamp 加 vw 联动（1024-1919 带短视高窗口
  1246×266=4.68:1 拉扁；≥1920 的 42vh 修复未覆盖本带）。
- P2-6 表头 scope="col"（WCAG 1.3.1；aria-sort 已在而 scope 缺）。
- P2-7 .mtab roving tabIndex（选中 0 余 -1；方向键 roving 已在，
  仅改 Tab 序初值分配）。
- P2-8 配置搜索 250ms 防抖（明细 applyFltD 同款先例；cfgFilter
  每键全 DOM 重排+computed style 强制 layout）。
- P2-9（canvas 日期分隔竖线 alpha 0.45）：审计判可维持，备案不钉。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r235_webui.py -q
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_legend_series_dimension():
    """P2-1：走势图例色票 display 随系列数据维度收放（空系列隐藏）。"""
    src = _src()
    assert "$('lgDirect').style.display=(CR.mode==='kline'||!hd.length)?'none':''" in src
    assert "$('lgTrans').style.display=(CR.mode==='kline'||!ht.length)?'none':''" in src


def test_kline_ringnote_cluster_sentence_conditional():
    """P2-1：K线簇位句「左簇=直飞 · 右簇=中转」按双簇在场条件化，
    单簇时不再产生无所指的簇位注释。"""
    src = _src()
    assert "左簇=直飞 · 右簇=中转" in src
    i = src.index("左簇=直飞 · 右簇=中转")
    head = src[max(0, i - 400):i]
    assert "CD.length&&CT.length" in head, "簇位句未按双簇条件化"


def test_cal_tier_legend_only_when_th():
    """P2-1：日历档位图例仅 th>0（未设心理价永无档位色，图例空挂）。"""
    src = _src()
    assert '(CR.r.th&&CR.r.th.direct)>0?\'<span class="cs-lg">深绿=真达标' in src
    assert "else $('calStats').innerHTML='';" in src


def test_channel_dot_contrast_light():
    """P2-2：亮色渠道识别色票加深至非文字 3:1+（飞猪/途牛两枚）。"""
    src = _src()
    assert "--c-fliggy:#c2661a" in src, "亮色飞猪色票未加深"
    assert "--c-tuniu:#a87b16" in src, "亮色途牛色票未加深"
    # 暗色块本过（7.8+）不动
    assert "--c-fliggy:#e89a4d" in src
    assert "--c-tuniu:#e0b04d" in src


def test_tgb_cheap_solid_green():
    """P2-2：改期微图低价棒实色 --green（rgba α.45 对白卡 1.6:1）。"""
    assert ".tgb.cheap{background:var(--green)}" in _src()


def test_hint_no_opacity_tax():
    """P2-3：.hint 规则体不再有 opacity 弱化税。"""
    src = _src()
    i = src.index(".hint{")
    j = src.index("}", i)
    assert "opacity" not in src[i:j], src[i:j]


def test_detail_legend_no_orphan_band():
    """P2-4：761-860 带 #tabs b.muted 独占整行且左贴行首（孤行可读）。"""
    src = _src()
    assert "@media(min-width:761px) and (max-width:860px)" in src
    i = src.index("@media(min-width:761px) and (max-width:860px)")
    seg = src[i:i + 300]
    assert "#tabs b.muted" in seg and "flex-basis:100%" in seg, seg


def test_canvas_height_vw_coupled():
    """P2-5→r236 P1-1 重落：canvas 高度 clamp 联动 vw，取大语义——
    宽短带（28vw>38vh）真正抬升、窄高窗复原 38vh（旧取小式对目标带
    零实效且窄高窗反向变矮，审计 1440×700 实测与病灶逐字节同）。"""
    assert "height:clamp(240px,max(38vh,28vw),360px)" in _src()


def test_th_scope_col():
    """P2-6：表头 th 带 scope="col"（读屏表格导航）。"""
    assert 'data-k="${k}" scope="col"' in _src()


def test_mtab_roving_tabindex():
    """P2-7 退役改写（r275）：roving tabIndex 随 tablist 形制退役
    （#montabs 混入非 tab 子件后降 button 形态，全员可 Tab）——旧
    roving 赋值禁复活；tabAria 助手在案（aria-pressed 回写实效档）。"""
    src = _src()
    i = src.index("function tabAria()")
    # 窗口取块边界（下一个顶层 function）而非固定字符数（三十一§3
    # 判例：窗口长度是实现细节，块内合法增厚不应红）
    j = src.find("\nfunction ", i + 10)
    seg = src[i:j if j > 0 else i + 1600]
    assert "x.tabIndex=x.classList.contains('on')?0:-1" not in seg, \
        "roving tabIndex 复活"
    assert "aria-pressed" in seg, "aria-pressed 回写缺席"


def test_cfg_search_debounce():
    """P2-8：配置搜索 250ms 防抖（applyFltD 同款先例），重建重放
    路径（buildForm 后 cfgFilter 直调）不受扰。"""
    src = _src()
    assert "function cfgFilterD(){clearTimeout(_cfgT)" in src
    assert "CFGQ=this.value;cfgFilterD()" in src


def test_line_ringnote_two_series_note_conditional():
    """推送审计 P2-2 兄弟消费点（Soldier P2-2）：折线尾注「两线均为
    行情池最低 · 中转不限直挂」按双系列在场条件化（单系列不宣称两线）。
    钉面随环注段序重组改写、语义担保保留（二十八§3）。"""
    src = _src()
    assert "(hd.length&&ht.length)?'两线均为行情池最低 · 中转不限直挂':" in src


def test_push_flight_exits_sanitized():
    """Soldier P2-1：非 digest 主路径（_push_flight/_push）出口接线
    sanitize_desp（航班名/经停城市自由文本的消毒管辖面完整）；
    r242 起出口 title 同律消毒（钉面随接线形态改写、语义担保保留
    并增强——LESSONS 二十八§3）。"""
    import pathlib as _pl
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    al = _pl.Path(os.path.join(root, "core", "alerter.py")).read_text(
        encoding="utf-8")
    # 2 处非 digest 出口（_push_flight/_push）；digest 出口的
    # "title"/"desp" 双键消毒形态由 test_sanitize_desp_exists_and_wired
    # 与 test_r242_push 锁
    assert al.count("send(sanitize_desp(title), sanitize_desp(desp))") >= 2,         "非 digest 出口消毒接线缺失"


def test_push_banner_fall_word_alignment():
    """推送 P2-2：邮件横幅 ↩️ 支词面「回落出线」与标题/正文头同语言
    （TIER_FULL['fall']='达标回落' 是图内价格档词，横幅借词曾一邮
    两词面）。"""
    from core.notifier import _TIER_BANNER
    d = dict(_TIER_BANNER)
    assert d["↩️"][2] == "回落出线", d["↩️"]


def test_daily_top3_fallback_fire_mark():
    """推送 P2-3：日报图挂兜底 TOP3 对达标行亮 🔥（与告警路径
    _top3_blocks 能力对称，三十§3；池行 _qual 预打旗标为口径）。"""
    src_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "report.py")
    src = pathlib.Path(src_path).read_text(encoding="utf-8")
    i = src.index("def _daily_top_fallback")
    seg = src[i:i + 1200]
    assert '"🔥 " if bool(fl.get("_qual"))' in seg, seg


def test_sanitize_desp_exists_and_wired():
    """推送 P2-4：desp 出口尖括号/省略号消毒单源在场，告警与日报
    两路径出口接线（八§1 尖括号全禁的构造端兜底；`<`＜ 为 HTML
    开标签源剥除，孤 `>` 是 markdown 引用记号保留，U+2026 实锤
    渲染成「。。。。」一并剥除）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    al = pathlib.Path(os.path.join(root, "core", "alerter.py")).read_text(
        encoding="utf-8")
    assert "def sanitize_desp" in al
    assert 'return {"title": sanitize_desp(title), "desp": sanitize_desp(desp),' in al,         "告警路径出口未接线"
    rp = pathlib.Path(os.path.join(root, "report.py")).read_text(
        encoding="utf-8")
    assert "sanitize_desp(" in rp, "日报路径出口未接线"


def test_wintoast_plain_space_compress():
    """推送 P3-1：WinToast _plain 双空格压缩（与 _alert_body 同律）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nt = pathlib.Path(os.path.join(root, "core", "notifier.py")).read_text(
        encoding="utf-8")
    i = nt.index("def _plain(")
    seg = nt[i:i + 2500]
    assert "{2,}" in seg, seg[:200]


def test_alert_body_md_contract_doc():
    """推送 P2-1（备案形态）：_alert_body docstring 显式声明输出仍含
    markdown 的消费者契约（ntfy/Aliyun 各自补剥在案；派生文本律的
    契约锚）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nt = pathlib.Path(os.path.join(root, "core", "notifier.py")).read_text(
        encoding="utf-8")
    i = nt.index("def _alert_body(")
    seg = nt[i:i + 1500]
    assert "markdown" in seg and "消费者" in seg, seg[:300]
