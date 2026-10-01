"""低价提醒 + 推送（带去抖）"""
import json
import logging
import math
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from .models import PRICE_MAX, PRICE_MIN, FlightPrice, Route, render_dir
from .flightnorm import _hhmm, cabin_clean, cabin_class

# 航班号尾码提取（name 尾部）——跨渠道合并键回退与比价头行地板档
# 共用同一口径（code 缺失回退 name 的同款收口先例）
_RE_TAIL_FNO = re.compile(r"([A-Z0-9]{2}\d{3,4})\s*$")

_LOG = logging.getLogger(__name__)

# 擦边带宽单源（收口）：擦边 = 线 < 价 ≤ 线×(1+NEAR_RATIO)。
# 禁止 0.10 字面量散落（alerter 多处 + webui 后端 near + report.py
# 本地定义 + webui 前端 JS ×1.1 ×2——前端无法 import，靠同步律注释），
# 任一端调带宽必漏。report.py / webui 后端一律 from core.alerter import
NEAR_RATIO = 0.10

# 取消率异常门控单源（第七批，仿 NEAR_RATIO 旋钮模式）：明细
# 总表次行仅 ≥ 此阈值才出「取消率N%」警示词（tongcheng sts tt=9 结构
# 化真值，生产常态 0-13%）——常态行加词会系统性抬高次行两行容量回退
# 率（_plan_sub 教训），门控后异常行信息价值最高。勿在 report/
# webui 散落字面量
CANCEL_RATE_ALERT = 15

# 跨零点出发窗口已告警对：每对 (dmin, dmax) 只告警一次
_WIN_WARNED = set()


# 舱位码 → 中文三大类（r222 上收 flightnorm.cabin_class 单源别名：
# 串舱守卫与展示映射同表同函数，字母高档码不再借双表分叉绕过守卫）
_cabin_cn = cabin_class


# 飞猪税垫重标定：12,303 对同指纹同航班样本实测
# 飞猪/其他渠道中位比 1.000（p25=p75=1.000、差值中位 ￥0）——
# 列表价已是可支付口径，按经验垫的 100 与数据不符，且系统性
# 压飞猪达标、放大去抖「幻影涨 ￥100」重推。保留常量做口径旋钮：
# 渠道口径若再变更改此处，_qual_price 全链（hits/KPI/曲线旗标）同生效
FLIGGY_TAX_PAD = 0

# 途牛价格口径标定（实测勿再疑）：同指纹同航班跨渠道配对
# n=515——tuniu/ctrip=1.000（n=139）、tuniu/fliggy=1.000（n=101）、
# tuniu/tongcheng=1.000（n=140），差值中位均 ￥0。baseFare 即可支付
# 含税口径，无需 TUNIU_TAX_PAD；对 qunar 偏高 ~3% 属 qunar minPrice
# 重摇噪声方向，非途牛低价。若未来途牛改价格字段需重标定，仿本文件
# FLIGGY_TAX_PAD 的旋钮模式接入 _qual_price


def _qual_price(f) -> float:
    """达标判定口径价 = 展示价 + 飞猪税垫；行情展示与排序仍用展示价。
    脏价（非数字）按不达标（inf）处理——若原样穿透，`<= th` 判定处
    会抛 TypeError 炸掉整轮推送。"""
    try:
        p = float(f.get("price"))
    except (TypeError, ValueError):
        return float("inf")
    if f.get("_platform") == "fliggy":
        return p + FLIGGY_TAX_PAD
    return p


# 档位词面单源（收编 审校 P1-2 挂账：_legend_line/图 markdown
# 头×2/report 两处图例/_suggest_line 手抄散点，改词只动此表）。键序=
# 判定梯度同向。四投影语义：全词=PNG 图例/图头长词面；短词=钉钉图例
# 40 半角预算压缩词（仅 🟩 有别，全词 41/40 进不来）；转写词=强提醒
# 通道 emoji 转写（尾随空格有意，空串=不入转写表）；over 无 emoji 点=
# 默认态不占语义点（定律）。fall 的 ▼ 仅图内（推送文本回落=
# ↩️ 回落出线，属航线状态非价格档，不入转写表）。webui 前端豁免区
# （跨语言无法 import，同步律注释+test 源码钉代管）与 emoji 点位三分
# 支行（判定逻辑非词面）备案不收。
_TIER_TABLE = (
    # key emoji 全词 短词 转写词
    ("qual",  "🎯",   "真达标",   "真达标",   "真达标 "),
    ("mkt",   "🟩",   "行情破线", "破线",     "行情价 "),
    ("near",  "🟨",   "擦边",     "擦边",     "擦边 "),
    ("over",  "",     "超线",     "超线",     ""),
    ("fall",  "▼",    "达标回落", "达标回落", ""),
)
TIER_EMOJI = {k: e for k, e, _f, _s, _t in _TIER_TABLE}
TIER_FULL = {k: f for k, _e, f, _s, _t in _TIER_TABLE}
TIER_SHORT = {k: s for k, _e, _f, s, _t in _TIER_TABLE}
TIER_TRANSCRIBE = {k: t for k, _e, _f, _s, t in _TIER_TABLE}
# 总表/TOP5 图 markdown 头档位片段（alerter ×2 手抄收口）
# mkt 槽用 SHORT 词（「行情破线」→ SHORT）为头注 40 半角预算所迫——
# 勿「顺手统一」成 FULL 词（走势环注/summary 用 FULL 单源投影），
# 顶破预算即折行（P3-6 备案：两种词长并存是有意设计非漂移）
_TBL_HEAD_TIER = f"深绿={TIER_FULL['qual']}·描绿={TIER_SHORT['mkt']}"  # P2-7 色面词面与 webui/图内统一（实绿→深绿）
# 「行情」短标微常量（第五词面：既非全词也非短词/转写词——_suggest_line
# 蹲守前缀与 kpi_tier_txt 破线未达标尾注同族共用）
_MKT_SHORT = "行情"
# 「*行情」短注全词：产出（KPI 降级链档、破线尾注）与剥段消费
# （_mini_split 去短注档）同出一源——词面改版日只改此处，剥段匹配
# 串不与产出分叉（触发档显形族：超宽行短注剥不掉静默烂尾）
_MKT_NOTE = "*" + _MKT_SHORT
# 「（行情价）」括注全词：alerter 降级链首档、report 日报 KPI 尾注、
# notifier 剥注表（_MKT_NOTE_DUPS）三面同源——「行情价」本体取
# TIER_TRANSCRIBE 投影，括号是标点变体
_MKT_NOTE_PAREN = "（" + TIER_TRANSCRIBE["mkt"].strip() + "）"


def tier_dot(qual_hit, diff, th):
    """KPI 档位 emoji 点单源（P3-5 收口：五处手抄散点——_kpi_block/
    _mini_kpi/_push_digest 直飞+中转分支/report._kpi——统一走
    TIER_EMOJI 投影，改点位判定只动此函数+图例）。判定式与四档
    梯度同向：🎯=达标口径破线（qual_hit 优先于 diff，判定语义由
    调用方给定——中转约束/达标口径各消费点不同）、🟩=行情破线
    未必达标（含恰达线 diff==0）、🟨=擦边（diff/th≤NEAR_RATIO）、
    超线默认态不加点（点密=噪音，差额数字自表达）。带尾空格
    （与既有词面贴法一致）。th=0（未设线）只认 qual，不做除法
    （五处消费点本都在各自 th>0 分支内，此为防御语义）。"""
    if qual_hit:
        return TIER_EMOJI["qual"] + " "
    if not th:
        return ""
    diff = float(diff)
    if diff <= 0:
        return TIER_EMOJI["mkt"] + " "
    if diff / float(th) <= NEAR_RATIO:
        return TIER_EMOJI["near"] + " "
    return ""


def _low_txt(price, th, platform):
    """达标差额文案「低￥N(税前)」：词面走 gap_txt 单源（——
    独立拼「低￥{th-price:.0f}」会成「低￥N」第二词源，恰是
    gap_txt docstring「改词必漏」警告的同病；恰达线 diff==0 顺带
    读「真达标」不再出「低￥0」）。税前注仅 pad>0 且飞猪行且严格
    破线时挂——展示价与可支付口径只在垫税启用时有差，pad=0 标注
    自动消隐（收口：legacy hits 行曾漏 pad 条件与 multi 版
    分叉，pad=0 时飞猪行恒挂「(税前)」假警示）。"""
    low = gap_txt(price, th, True)
    if FLIGGY_TAX_PAD > 0 and platform == "fliggy" and price < th:
        return low + "（税前）"   # 全角为语境定版（r1553 审档：半角在
    return low                    # 「真达标(税前)」语境语义不通，双钉在案；
                                  # 括注无全局统一体系：(截)/(等N家) 半角是
                                  # 宽度预算定版，勿以此处为据改词面


def gap_txt(price, th, qual_hit):
    """差额词单源：破线「低￥N」、超线「差￥N」；恰达线
    （diff==0）按达标口径分档——真达标「真达标」、行情价「行情破线」
    （词面与图例/档位四档「真达标」同字，旧「达标」差一字）。
    旧「恰达线=达线」与 🟩 图例=行情破线 同条推送内三重互斥
    （🟩+（行情价）+达线），日报 PNG 已收口而文本侧 5 处同病。"""
    diff = float(price) - float(th)
    if diff < 0:
        return f"低￥{abs(diff):.0f}"
    if diff > 0:
        return f"差￥{diff:.0f}"
    return TIER_FULL["qual"] if qual_hit else TIER_FULL["mkt"]


def _pct_int(pct):
    """百分比取整单源：floor(x+0.5)=前端 Math.round 语义（banker
    偶数舍入在 2.5/4.5/…中点比前端低一档——同条推送文本与图内
    两数互斥的取整收口，_near_txt 与 KPI 幅度尾注共用）。"""
    return math.floor(pct + 0.5)


def _kpi_pct_suffix(price, th):
    """KPI 行1 幅度尾注词面单源（multi _kpi_block 与单航线 direct/
    transfer 三分支同源消费）：擦边带（diff>0 且 ≤NEAR_RATIO）挂
    _near_txt「擦边N%」——与档位点/图内 summary/建议行四语言同源
    （旁路「·N%」banker 词面曾与图内「擦边3%」互斥两数并存）；
    其余档挂「N%」abs 幅度（达标行保号）；达标带 <1% 省略（「低
    ￥9（0%）」与差额矛盾读感守卫不变）；恰 0.5% 擦边带出
    「擦边不足1%」（档位词不是裸 0%）。"""
    if not th:
        return ""
    diff = float(price) - float(th)
    ratio = diff / float(th)
    if diff > 0 and ratio <= NEAR_RATIO:
        return _near_txt(ratio)
    p = abs(ratio) * 100
    return f"{_pct_int(p)}%" if p >= 1 else ""


def _near_txt(ratio):
    """擦边词面小单源：kpi_tier_txt 与 _suggest_line 共用，
    改词面（「擦边N%」）只动 _TIER_TABLE near 行（前缀挂
    TIER_FULL 投影，r230 WE 收口——字面量会在档位词改版日漂离
    图例）。ratio=超出线的比例（0-NEAR_RATIO）。
    双端同语言契约（与 webui pctTxt 同构）：≤0.5 出「擦边不足1%」
    （恰 0.5 显式含边界）；>0.5 半点向上取整（math.floor(pct+0.5)
    =JS Math.round 语义——banker 偶数舍入在 2.5/4.5/…中点比前端
    低一档，同价两端词面分叉）。「擦边0%」与档位词字面自相矛盾
    （擦边=距线 0%？读者需回看差￥N 才能解）；词面不用「<1%」——
    尖括号家族是钉钉 markdown 全禁字符（HTML 标签解析吞字风险）；
    纯读感词面，NEAR_RATIO 带宽判定不动。"""
    p = TIER_FULL["near"]
    pct = ratio * 100
    if pct <= 0.5:
        return f"{p}不足1%"
    return f"{p}{_pct_int(pct)}%"


def _stale_txt(h):
    """补位时长词面单源（文本版 plat_full 与图版 report._plat_tag
    同源同词，「两版同词面同序」承诺的词面收口）：<1h 落「刚补位」
    （:.0f 四舍五入把 0.4h 产成「0h前」——零时读感是旧数据，实为
    最新补位，语义反向）；≥1h 恒「Nh前」；空值空串（词面缺席由
    消费点 if 门控制）。"""
    if not h:
        return ""
    return "刚补位" if h < 1 else f"{h:.0f}h前"


def _rest_seg(title: str, items: list) -> str:
    """「｜另监控 …」段预算内逐条追加+「等N条」收尾（挂账①：
    3+ 航线时全串必超 60 半角，P2-1 的整段丢弃曾把多航线扫读
    信息归零——装得下几条装几条，装不下的以「等N条」留痕，纯增益）。"""
    if not items:
        return title
    shown = []
    used = len(title) + len("｜另监控 ")
    for it in items:
        rem = len(items) - len(shown) - 1   # 本条装入后的剩余条数
        tail = len(f"等{rem}条") if rem > 0 else 0
        cost = len(it) + (3 if shown else 0)   # 「 · 」分隔 3 字符
        if used + cost + tail > 60:
            break
        shown.append(it)
        used += cost
    if not shown:
        # 单条超长连第一条都装不下：整段静默丢曾让「另监控」辅信息
        # 归零且读者不知有未列入项——预算内挂「等N条」计数留痕；
        # title 本身近满时维持裸 title（整行 60 半角预算是地板约束）
        marker = f"｜另监控 等{len(items)}条"
        if used + len(marker) - len("｜另监控 ") <= 60:
            return title + marker
        return title
    seg = "｜另监控 " + " · ".join(shown)
    rest_n = len(items) - len(shown)
    if rest_n:
        seg += f" 等{rest_n}条"
    return title + seg


def kpi_tier_txt(label, price, th, qual_hit):
    """KPI 摘要词单源（日报 PNG summary 与 multi 总表图内 summary
    同语言，图脱离消息上下文也能判档）：真达标/行情破线/擦边N%/差￥N。
    PNG 无 emoji 字形，档位用文字词；恰达线同 gap_txt 口径。
     擦边词面缩短（「擦边·距线9%」→「擦边9%」）：multi 总表
    summary 4 bits 恒触 11px 字号下限的宽度预算 root fix。"""
    if not th:
        return f"{label} ￥{float(price):.0f}（未设线）"
    diff = float(price) - float(th)
    if diff > 0 and diff / float(th) <= NEAR_RATIO:
        gap = _near_txt(diff / float(th))
    else:
        gap = gap_txt(price, th, qual_hit)
        # 破线未达标=🟩行情档消歧（推送审校 P0）：「低￥N」词面
        # 在四档语言属真达标档（建议出手），图内 summary 脱离消息上下文
        # 即被读成可出手——调用方如实传的 qual_hit 在 diff<0 分支曾被丢
        # （文本侧同场景有 🟩+*行情 双消歧，PNG 裸奔）；恰达线 gap_txt
        # 内已分档不动。总表/日报 summary 三端随此收口。
        # 达标态对称显名：破线档有「·行情」单向消歧，正向档裸
        # 「低￥N」同源不显名；词面取 TIER_FULL 单源
        if diff < 0:
            gap += (f"·{TIER_FULL['qual']}" if qual_hit
                    else f"·{_MKT_SHORT}")
    return f"{label} ￥{float(price):.0f} {gap}"


# 强提醒失败警示行单源：三处手抄曾逐字耦合（主推两处追加 +
# _storm 剥离），改一词必三处同步漏。词面 34/40 半角——旧「出手前请自查」
# 恰满 40/40 零缓冲，基座任何变化即在手机引用行静默折行
URGENT_FAIL_NOTE = "> ⚠️ 电话/弹窗提醒发送失败，请自查"

# 持续达标正文头（multi 主路径与遗留单航线路径同源消费）：词面曾两处
# 裸字面量，语义统一后仍各持一份——改词面只改一处即再分叉
_SUSTAIN_HEAD = "#### 🔔 持续达标（电话已提醒过）"

# 跨渠道孤低价守卫阈值（口径旋钮，同 FLIGGY_TAX_PAD 模式）：行达标口径
# 价 < 其他渠道同类别最低价中位数 × RATIO → 孤低价。
# 阈值标定（12 天 DB 回算 n=3493 轮-类别）：直飞合法地板
# 0.908 / 幻影天花板 0.394——0.5 两侧余量 1.8×；勿上调 ≥0.75（中转
# 合法地板 0.78：qunar/ctrip 卖的转机组合不同，价差 ~22% 属合法）。
# 中转渠道覆盖少（tongcheng/tuniu/fliggy 明细恒 0）时锚退化为单一对方
# 渠道最低价（等价 2× 判定），一方缺数据即 n<2 跳过——单渠道轮零保护
# 是已知边界，可见性由「无数据渠道」对账行兜底。
# 缘起：渠道内中位锚在解析器异常窗口下失守（行内第二价格行动态价
# 820/700 混入，CA8564 挂
# _alt_price 9900），￥700 直通电话告警——渠道内锚依赖解析器健康度，
# 跨渠道中位数是独立于解析的第二道防线（纵深防御）
XCHAN_PHANTOM_RATIO = 0.5


def _flights_from_extra(obj, date, platform) -> list:
    """extra 元素数组 → 推送池航班 dict 列表（组装语义单源：normalize
    归一 + 日期滚动过滤）。推送主路径与近期明细补位路径共用——
    「渠道把过期日期查询滚动为其他日期航班」的行（行内 depDate≠查询
    日期，normalize 打 _dep_mismatch 标）不入池，防过期日期桶借推送
    复活（曲线/列表端同标同滤，三端同一可信口径）。"""
    out = []
    if not isinstance(obj, list):
        return out
    from core.flightnorm import normalize as _fnorm
    for f in obj:
        if not isinstance(f, dict) or "price" not in f:
            continue
        g = dict(f)
        g["_platform"] = platform
        _fnorm(g, date)
        if g.get("_dep_mismatch"):
            continue
        out.append(g)
    return out


def xchan_phantom_idx(entries) -> set:
    """entries: [(达标口径价, platform)] → 孤低价行下标集合（纯函数，
    告警池/走势池/webui 三端共用同一判定）。

    锚=各渠道最低价（同渠道多行取最低参锚），逐行与其「其他渠道」
    最低价集合的中位数比。独立渠道 <2 不判（无独立锚）；5 渠道下
    1-2 渠道整体污染也拖不歪其余行的锚（中位数稳健性）。"""
    idx = set()
    if len(entries) < 2:
        return idx
    pmin = {}
    for v, pl in entries:
        cur = pmin.get(pl)
        if cur is None or v < cur:
            pmin[pl] = v
    if len(pmin) < 2:
        return idx
    # 中位数只依赖「本行渠道」（pmin 恒定，与 v 无关）→ 按渠道缓存一次。
    # 原实现在行循环内逐行重建 sorted(...)：渠道数 ≤5 时单次不贵，但
    # 调用方一旦退化（曲线侧曾写成列表推导条件表达式 → O(n²)），
    # 每秒被放大到数百万次 sorted（cProfile：7.9M 次、14s）。
    med_by_pl = {}
    for i, (v, pl) in enumerate(entries):
        med = med_by_pl.get(pl)
        if med is None:
            others = sorted(pmin[q] for q in pmin if q != pl)
            m = len(others)
            med = (others[m // 2] if m % 2
                   else (others[m // 2 - 1] + others[m // 2]) / 2)
            med_by_pl[pl] = med
        if v < med * XCHAN_PHANTOM_RATIO:
            idx.add(i)
    return idx


def _dw_raw(s: str) -> float:
    """显示宽原始值（浮点，不取整）：截断循环的逐字符累计必须用本函数
    ——ceil 后的单字符值会把数字 1.125 放大成 2（放大 78%），截断点
    系统性提前、词面烂尾（校准当日实测）。行级判定才取整（_dw）。"""
    import unicodedata as _ud
    w = 0.0
    for ch in s:
        cp = ord(ch)
        if cp == 0xFE0F:
            continue
        if cp >= 0x1F000 or 0x2190 <= cp <= 0x2BFF \
                or _ud.east_asian_width(ch) in ("W", "F"):
            w += 2
        elif ch.isdigit():
            w += 1.125
        elif ch == '%':
            w += 1.75
        else:
            w += 1
    return w


def _dw(s: str) -> int:
    """钉钉手机端显示宽度（半角列）：CJK/全角/emoji/箭头记 2、其余记 1。
    推送行宽自检用——单行 >20 全角（40 半角）窄屏必折行且断点不受控
    （「🟩 与其后文字被拆两行」实锤同源）。变体选择符零宽。
    ASCII 校准（推送审校 P2-2）：msyh16 实测数字 advance 9px、% 14px，
    8px 半角基准下按 1.125/1.75 计——旧模型对数字串系统性低估 6-12%，
    贴线 40/40 行真实渲染 20.5 全角超 20 红线；行级向上取整=守卫只可
    高估不可低估。截断/累计场景用 _dw_raw（勿取整后逐字累加）。"""
    import math as _m
    return _m.ceil(_dw_raw(s))


def _clip_dw(s: str, limit: int) -> str:
    """逐字截到 limit 半角内（_dw_raw 浮点累计——ceil 后单字符值把
    数字 1.125 放大成 2，逐字累加必须走浮点，P-3 同律）。"""
    out, _w = [], 0.0
    for _ch in s:
        _cw = _dw_raw(_ch)
        if _w + _cw > limit:
            break
        out.append(_ch)
        _w += _cw
    return "".join(out)


def _disp_dw(s: str) -> int:
    """渲染显示宽：markdown 链接 [t](u) 还原为纯文字 t（钉钉渲染只占
    t 的宽，方括号/URL 均不显示）、加粗 ** 与行内码 ` 为零宽语法符，
    剥完再按 _dw 计列——**/[ ]/URL 残片计入宽度会系统性高估加粗链接行，
    KPI「差￥N（P%）」设计形态因虚估超宽恒降级。"""
    import re as _re
    t = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return _dw(t.replace("**", "").replace("`", ""))


def _dedup_tie(rows: list) -> list:
    """同价同航班多渠道合并：TOP5 文本版的渠道维度恰
    在超宽降级末档被剥，exact-tie 市场 + 图挂兜底下 5 槽位曾是同一航班
    的 5 渠道逐字复读（09-21 01:26 实发）——按 (航班号, 时刻, 链型,
    价格) 合并为一行，同价渠道数以首行 `_tie_n` 承载（渲染为「同价×N」
    角标）。合并后再截断，槽位让给不同航班；返新 dict 不污染原行。
    键首元归一：一端 code 缺失回退 name
    （「新海航｜天津航空HU7849」）、另一端 code=HU7849 → 键不等漏
    合并（生产总表图同班同价双行实锤）——code 缺失时从 name 尾部
    正则提取航班号参与键（report 同款收口先例）；同班不同价不吞
    （价差即比价信息，价格仍在键内）。达标判定组 OR 语义见
    _tie_any_ok（成员快照 _tie_rows 随行，第 2+ 成员）。"""
    import re as _re

    def _fk(f):
        code = str(f.get("code") or "").strip()
        if code:
            return code
        m = _re.search(r"([A-Z0-9]{2}\d{3,4})\s*$",
                       str(f.get("name") or ""))
        return m.group(1) if m else f.get("name")

    groups = {}
    out = []
    for f in rows:
        key = (_fk(f), f.get("depTime"),
               f.get("arrTime"), f.get("transCity", ""),
               f.get("crossDayDesc", ""), bool(f.get("stopover")),
               f.get("price"))
        if key in groups:
            g = groups[key]
            g["_tie_n"] += 1
            g["_tie_plats"].append(
                f.get("_platform") or "?")
            # 达标组 OR（行级判定单源收口）：同价同班「这个价能不能
            # 合规买到」=任一成员合规即真（同价时点哪家都一样，
            # _fmt_flight_line 同价×N 角标语义自认）——transferBaggage
            # 渠道差是成员间唯一实质差（arrTime/depTime/code/price 全
            # 在合并键内恒同），首成员不合规≠组不合规（曾按池序首
            # 渠道单判：日报绿行/总表图/🔥 三处齐暗）。report 路径
            # _qual 在 dedup 前逐成员预打，此处 OR 聚合即收口；
            # alerter 路径 dedup 时 _qual 未打，仅在一侧已在场时写
            # （普通行不添 _qual 键防键面污染），快照供 _tie_any_ok
            # 后设重算（第 2+ 成员；本体即首成员）。
            if "_qual" in g or "_qual" in f:
                g["_qual"] = bool(g.get("_qual")) or bool(f.get("_qual"))
            g.setdefault("_tie_rows", []).append(
                (f.get("_platform") or "?",
                 f.get("transferBaggage") or "",
                 f.get("layoverM")))
        else:
            g = dict(f)
            g["_tie_n"] = 1
            g["_tie_plats"] = [f.get("_platform") or "?"]
            groups[key] = g
            out.append(g)
    return out


def _tie_grp_flagged(f: dict) -> bool:
    """tie 组直挂标注感知：本体或 _tie_rows 成员快照任一带
    transferBaggage 即真——对账注的「标注缺失」按头成员单判曾与
    组 OR 达标判定同屏矛盾（S-P2-2）。"""
    if f.get("transferBaggage"):
        return True
    return any(tbg for _p, tbg, _lm in (f.get("_tie_rows") or []))


def _tie_any_ok(g: dict, th, route, transfer: bool) -> bool:
    """tie 组达标判定（组 OR 单源）：合并行本体+全部成员快照任一
    合规即真。transferBaggage 渠道差是成员间唯一实质差——直挂筛选
    下首渠道无标注而组内有曾漏标达标（读者以为不可出手）。无快照
    行（普通行/单渠道行）按本体判定零漂移。三消费点（multi 总表/
    单航线总表/文本 🔥）一律经此，勿回退 _qual_price 单行判定。"""
    ok = th > 0 and _qual_price(g) <= th
    if transfer:
        ok = ok and Alerter._transfer_ok(g, route)
    if ok or not g.get("_tie_rows"):
        return ok
    for _plat, _tbg, _lm in g["_tie_rows"]:
        shadow = dict(g)
        shadow["_platform"] = _plat
        shadow["transferBaggage"] = _tbg
        shadow["layoverM"] = _lm
        ok2 = th > 0 and _qual_price(shadow) <= th
        if transfer:
            ok2 = ok2 and Alerter._transfer_ok(shadow, route)
        if ok2:
            return True
    return False


def _row_qual(f: dict, th, route, transfer: bool) -> bool:
    """总表行达标旗标（总表图消费单源）：补位行（_stale_h）不参——
    近 6h 补位价照打真达标绿=「可出手」指向过期价（达标判定只认
    当轮，KPI fresh 门同律），行带「·Nh前」角标自明；当轮行回落
    _tie_any_ok 组 OR 零漂移。
    不变量备案：代表行恒为当轮行（_dedup_tie fresh 先入池+稳定排序
    ——补位行仅在无当轮行时才入代表位），故 stale 短路不会压制组内
    当轮成员的组 OR 达标；若未来 tie 合并次序变更，须先把 stale 判定
    升级为组级聚合（任一成员 fresh 即走 _tie_any_ok）。"""
    if f.get("_stale_h"):
        return False
    return _tie_any_ok(f, th, route, transfer)


def _fit_line(s: str, limit: int = 40, fallbacks=()) -> str:
    """行宽守卫（手机 ≤20 全角 = 40 半角）：s 超宽时逐级降级到
    fallbacks 中首个不超宽的形态；全超则取最后一个 fallback
    （调用方保证末档是最简可读形态，信息按重要性从前往后丢）。
    宽度按 _disp_dw 渲染宽计，五处超宽重灾区（图例/KPI 行1/行2/
    hits 行/比价辅行）统一走这里，不各写一遍。"""
    if _disp_dw(s) <= limit:
        return s
    for fb in fallbacks:
        if _disp_dw(fb) <= limit:
            return fb
    return fallbacks[-1] if fallbacks else s


def _trend_bits_str(hist) -> str:
    """近 7 天趋势词面单源（「直飞 ↓16%｜中转 ↓3%」形态）：告警
    _trend_line 与日报 build_and_push 同消费（能力对称三十§3——日报
    曾只有 48h 图无 7 天趋势文字，每日唯一综合视图信息容量反低于
    告警）。hist=report._rounds 序列（r[1]=直飞最低、r[2]=达标中转
    最低）；数据不足/横盘 <1% 省略（「→0%」是噪音，线上实锤）。"""
    bits = []
    for idx, label in ((1, "直飞"), (2, "中转")):
        vs = [r[idx] for r in hist if r[idx]]
        if len(vs) >= 2 and vs[0]:
            pct = (vs[-1] / vs[0] - 1) * 100
            if abs(pct) < 1:
                continue
            arrow = "↓" if pct < 0 else "↑"
            bits.append(f"{label} {arrow}{abs(pct):.0f}%")
    # 标签后单空格、段间 ｜ 直连（两段词面 ~20-24 半角在预算内；
    # 钉钉超宽折行断点不受控的教训同源——不加衬垫防再增宽）
    return "｜".join(bits)


def _trend_block(tl) -> str:
    """趋势行组装单源（告警与日报同消费）：有值 →「> 📉/📈 近7天 …」
    段落（判向取直飞段：直飞↑中转↓混合时按全文含箭头判向曾整条误
    标）；空串/None → 空串（无数据静默省略；异常「暂缺」标注由
    告警调用点补——日报侧查询异常与 _p7_note 同律静默）。"""
    if not tl:
        return ""
    _down = "↓" in tl.split("｜")[0]
    return f"> {'📉' if _down else '📈'} 近7天 {tl}\n\n"


def _trend_line_str(db_path, from_c, to_c, date, arrival_max,
                    layover_min, dep_win):
    """近 7 天趋势查询+词面（168h 窗超出走势图 48h 承载、图内无同源
    信息）。查询异常向上抛（调用点定档：告警补「暂缺」/日报静默）。"""
    from report import _rounds   # 延迟防循环（report 顶层 import 本模块）
    hist = _rounds(db_path, from_c, to_c, date, arrival_max, hours=168,
                   layover_min=layover_min, dep_win=dep_win)
    return _trend_bits_str(hist)


def _pct_fallback_forms(base: str, pct: str) -> list:
    """KPI 行1 百分比尾注三档降级链（单源，主链 _kpi_block 与心跳
    两分支同源消费）：全角括号态 → 间隔号态 → 地板态。间隔号「·」
    在确定安全字符集（共享·航司号同源），读作「低￥50·3%」语义自明；
    pct 空（<1% 省略，与日报 pct 守卫同律）三档同形=首档恒达标。
    调用点内联 fallback 列表是档序悄悄回退的温床（源码钉锁调用点
    必须走 helper）。"""
    if not pct:
        return [base, base, base]
    return [base + f"（{pct}）", base + "·" + pct, base]


_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def sanitize_desp(text: str) -> str:
    """desp 出口字符消毒单源（八§1 尖括号全禁的构造端兜底）：
    `<`/`＜` 是 HTML 开标签源（markdown 层按标签解析吞掉后续文字，
    渠道自由文本字段 name/城市/经停若含将原样进 desp），剥除；
    全角 `＞` 一并剥（家族一致性：左向剥右向不剥是半盲区，钉钉
    渲染器对全角尖括号行为不可实测——宁剥勿赌）；孤 `>` 是
    markdown 引用记号（构造端合法产出）保留——HTML 标签需 `<>`
    配对，左尖括号剥除后右尖括号恒为孤字符无害；U+2026「…」
    在钉钉渲染实锤成「。。。。」一并剥除。PNG 侧光栅化无害不在
    此收口。
    词面备案（安全集补充登记，r268 推送审校连续第二轮建议落档）：
    en-dash U+2013「–」（dep_win「（06:00–22:00）」词面）生产真账
    179 次实发零渲染事故——事实安全集成员；U+00D7「×」、U+2014
    「——」同族已在案。"""
    t = str(text or "")
    for ch in ("<", "＜", "＞", "\u2026"):
        t = t.replace(ch, "")
    return t


def _png_user_tag(user: str) -> str:
    """总表 PNG 产物名的 user 段：多租户同 OD 时本地文件曾同名互覆
    （邮件 cid 30 分钟门内反推直读会嵌到别家图）。空 user（单用户
    默认部署）返空串文件名不变零回归；user 是配置自由文本，路径
    分隔/非法字符剥除。反推链 _local_push_image 是通用 stem 还原
    （URL 尾段 stem ↔ data/{stem}.png），产物名带段后消费端零改动。"""
    tag = re.sub(r'[\\/:*?"<>|\s]+', "", str(user or ""))
    return f"{tag}_" if tag else ""


def _trunc_tokens(text: str, budget: float, sep: str = " ") -> str:
    """地板档 token 边界贪心截断（三十一§2 单源：行3 引用块与
    _mini_split 拆行档共用——逐字截对「短注/差额词」这类直连复合
    词面会截出「*行」半截与金额悬垂，token 语义下要么完整要么缺席）。
    浮点逐字累计找截点；截点
    落 token 中部时回退到 token 起点（整 token 丢弃——半截金额
    「￥190」会被读成错误值，token 要么完整要么缺席）；截点落首
    token 自身（病理长词面）时保持逐字截保前缀（地板档恒落位律：
    内容不得净失）。budget<=0 返回空串由调用方兜底（两消费点的
    头缀固定短，预算恒正）。"""
    if budget <= 0:
        return ""
    toks = text.split(sep)
    joined = sep.join(toks)
    cut, w = len(joined), 0.0
    for i, ch in enumerate(joined):
        cw = _dw_raw(ch)
        if w + cw > budget:
            cut = i
            break
        w += cw
    if cut < len(joined):
        pos = 0
        for t in toks:
            if pos < cut < pos + len(t):
                if pos > 0:
                    cut = pos
                break
            pos += len(t) + len(sep)
    return joined[:cut].rstrip(sep)


def _mini_split(head: str, segs: list) -> str:
    """第 2+ 日期精简 KPI 行构造（拆行档单源）：窄形态「 ｜ 」联接；
    超宽先去「*行情」短注（丢注不丢数）；仍超宽拆行档**两物理行各自**
    过行宽守卫——_fit_line 按 _disp_dw 整行计量不认段内换行（行级判定
    与字符级累计不可混用）。段级降级链：原样→去短注→拆行档；拆行后
    单段仍超宽走 _trunc_tokens token 贪心地板（差额词/短注要么完整
    要么缺席，首 token 病理超预算才逐字截——链尾恒达标律）。
    首档必须原样：_disp_dw 本就把 [t](url) 还原为 t 计宽、URL 不占
    渲染宽——先剥再量会把「可达预算内」的链接白白剥掉（链接是该
    日期唯一文本跳转入口，图挂兜底日尤甚）；地板截只对剥链接后的
    裸文本做（对原文截会截出 markdown 半截）。段间 \\n\\n（PC 渲染律）。"""
    line = head + " ｜ ".join(segs)
    if _disp_dw(line) <= 40:
        return line + "\n\n"
    no_note = head + " ｜ ".join(
        s.replace(_MKT_NOTE, "") for s in segs)
    if _disp_dw(no_note) <= 40:
        return no_note + "\n\n"
    parts = []
    for s in segs:
        if _disp_dw(head + s) <= 40:
            parts.append(head + s)
            continue
        bare = _RE_MD_LINK.sub(r"\1", s)
        # 「剥链接保裸价」判定档已撤（死档判据：_disp_dw 对 [t](url)
        # 只计链接文字宽，head+s 与 head+bare 渲染宽恒等——「剥后
        # 达标」分支数学不可达，程序实证 48==48）；bare 只作下方
        # 地板截的输入，不是独立降级档。地板档走 token 边界贪心
        # （_trunc_tokens 单源，与行3 引用块同律）：差额词/短注要么
        # 完整要么缺席，首 token 病理超预算才逐字截
        parts.append(head + _trunc_tokens(bare, 40 - _disp_dw(head)))
    return "\n\n".join(parts) + "\n\n"


def _l2_fallbacks(l2_base: str, cross: str, d: str) -> list:
    """KPI 行2（航班身份行）降级链：跨天括注档先于涨跌档——跨天
    班无「+1天」会被误读当日达（决策级辨识信息），涨跌是次要信号；
    地板档=航班身份本体，超预算逐字截（守卫链尾恒达标律：
    身份本体连超时全超取末档原样吐出=行宽守卫静默失效）。
    双名剥档（校准 P2-2 补）：base 本身超预算时（「新海航｜海南航空
    HU7849 …」双名形态），先剥「A｜」营销名段保时刻完整——营销名
    次要于时刻/跨天辨识信息，硬截曾把到达时刻截成 21:10→0（比丢
    括注更糟）。联程剥首段档（r235 推送 P1）：中转联程名常态形态
    「海南航空 HU7849/春秋9C8845」以「/」分段、无「｜」营销名——
    剥名档对其不可达，超宽直落地板逐字截曾把到达时刻截成
    「08:30→01:3」且跨天括注整体消失（「｜」形态当年修过，「/」
    形态漏网）；档序在「｜」档之后（混合形态先剥营销名再剥联程
    首段，两段皆次要于时刻/跨天）。逐字截按 _dw_raw 浮点累计
    （ceil 后逐字累加放大 78%）。
    档序即语义优先级声明（十九§9）：涨跌注 d（≥16 半角）恒宽于
    cross（括注态 ≤7）＝「base+d」「short+d」恒为不可达死档且档序倒挂，
    已删——d 是次要信号，地板档前自然丢失；跨天辨识信息保序在前。
    d 形参保留（调用点形态稳定）但已不入链。base/short 裸档（无
    cross 的防御位）也未采纳：base 裸档与地板档恒同串或同为死档、
    short 裸档需 short∈(34,40] 才与地板分叉而航司名词面不可达——
    勿以「补防御位」为名重加死档。"""
    tiers = [l2_base + cross]
    i = l2_base.find("｜")
    if i >= 0:
        short = l2_base[i + 1:]
        tiers += [short + cross]
    j = l2_base.find("/")
    if j > 0:
        tiers += [l2_base[j + 1:] + cross]
    floor, _w = [], 0.0
    for _ch in l2_base:
        _cw = _dw_raw(_ch)
        if _w + _cw > 40:
            break
        floor.append(_ch)
        _w += _cw
    tiers.append("".join(floor))
    return tiers


def _ops_fallbacks(n: str, pre: str = "> ⚠️ ") -> list:
    """ops 回退行降级链（推送审校 P2-2，取代 「冒号后
    清零+截断」——2+ 渠道缺失常态下对账价值归零成病句）：有渠道清单
    的形态逐渠道剥尾保名单头（首渠道名优先入 40 半角预算），末档地板
    分叉——冒号形态保前缀，无冒号形态按「40−前缀−标记」渲染宽预算
    逐字截（终审：直挂标注缺失等无冒号形态若末档仅存截断标记则
    路由/日期/事由全灭，恢复地板语义）。模块级纯函数：tests/test_v170_push.py 真执行级。
    截断标记统一半角 (截)（推送审校：全角「（截）」6 半角曾把
    k=1 档挤到 42/40 全超，5 渠道缺失形态塌裸地板渠道清单全灭）。"""
    i = n.find("：")
    head, rest = ((n[:i + 1], n[i + 1:]) if i >= 0 else ("", n))
    parts = rest.split("、")
    tiers = [pre + head + "、".join(parts[:k])
             + ("(截)" if k < len(parts) else "")
             for k in range(max(len(parts) - 1, 1), 0, -1)]
    if head and parts and parts[0]:
        # 首渠道名让位档（校准 P2-2 补）：(截) 标记与首渠道名争预算时
        # 渠道名优先——「哪个渠道无数据」是对账起点，(截) 缺席由「渠道
        # 全量对账循控制台」备案语义兜底（本函数既有设计）
        tiers.append(pre + head + parts[0])
    # 地板档按渲染宽预算截（字符数截对全 CJK 注曾 47 半角
    # 超宽——地板档必须恒达标，按最终渲染宽计量）；逐字宽走 _dw_raw
    # 浮点累计（ceil 后逐字累加把数字放大成 2，截断点提前烂尾）
    _budget = max(1.0, 40 - _disp_dw(pre) - _disp_dw("(截)"))
    _keep = head or n
    _cut, _w = [], 0.0
    for _ch in _keep:
        _cw = _dw_raw(_ch)
        if _w + _cw > _budget:
            break
        _cut.append(_ch)
        _w += _cw
    return tiers + [pre + "".join(_cut) + "(截)"]


# 携程登录指引第二行（推送审校 P2-3：旧长词面 43 半角是拆段后仍
# 唯一没走守卫的裸行）——词面收模块常量（调用点内联字面是守卫失效
# 温床），34 半角恒达标
_CTIP_LOGIN_NOTE = "（持续无数据请运行 --login ctrip）"


def _storm_title(n: int, total: int, title: str) -> str:
    """风暴连推标题：前缀计入 60 字符预算（notifier title[:60] 按
    Python 字符数截）——满额主推 title 直拼曾静默截尾丢「｜另监控」
    段（推送审校 P2-4）。模块级纯函数：tests 真执行级。"""
    pre = f"📞 达标提醒 {n}/{total} "
    return pre + title[:max(0, 60 - len(pre))]


def _storm_desp(n: int, total: int, desp: str) -> str:
    """风暴连推正文：首行带序号标记（钉钉聊天窗口不显示标题——重发
    标记只进标题=用户不可见位，须落正文首行；词面与 _storm_title 同
    语言）。模块级纯函数：tests 真执行级。"""
    return f"📞 达标提醒 {n}/{total}\n\n{desp}"


def _demote_note(demoted: bool, hit_demoted: bool) -> str:
    """降级说明行（`> ⚠️` 引用块，推送审校 P2-1）：曾直拼是全 desp
    唯一没走 _fit_line 的引用行——双词条形态（多航线+命中降级同现）
    55/40 超宽必现窄屏折行。降级链中档等义压缩保 hit 丢失面语义
    （「命中行仅价格」——hit 详情被降级为价格判据行这一丢失面必须
    说明，行为钉在案；全形态「仅价格判据」5 字之差换 39/40 守宽），
    地板档保「明细见总表」对账语义。模块级纯函数：tests 真执行级。"""
    full = ("> ⚠️ 航线较多，仅列关键价"
            + ("，命中行仅价格判据" if hit_demoted else "")
            + "，明细见总表")
    mid = ("> ⚠️ 航线较多，命中行仅价格，明细见总表" if hit_demoted
           else "> ⚠️ 航线较多，仅列关键价，明细见总表")
    return _fit_line(full, fallbacks=[
        mid, "> ⚠️ 航线较多，明细见总表"])


class Alerter:
    PLATFORM_CN = {
        "qunar": "去哪儿", "fliggy": "飞猪", "ctrip": "携程",
        "tongcheng": "同程", "tuniu": "途牛",
    }
    # 上一推送轮是否有达标（进程内记忆）：达标→无达标的那轮给「↩️ 回落
    # 出线」语义，用户不再对着 ❌ 猜是不是失效了（新增）
    _prev_hit = False

    def __init__(self, logger: logging.Logger, notifier=None, storage=None,
                 push_drop_min: float = 30, push_rise_min: float = 50,
                 digest: bool = False, at_mobile: str = "",
                 storm_repeat: int = 3, user: str = "",
                 platforms: list = None, urgent_notifier=None,
                 quiet_start: str = "", quiet_end: str = "",
                 base_url: str = "", image_host: dict = None):
        """
        notifier: 推送器（None 表示不推送）
        storage: 用于读写 alert_state（去抖）
        push_drop_min: 触发"再次推送"的最小降幅(￥)
        push_rise_min: 触发"再次推送"的最小涨幅(￥)
        digest: 每轮推送直飞/中转 TOP3 行情报告（达标时警报式高亮）
        at_mobile: 达标强提醒时 @ 的手机号（钉钉 atMobiles）
        storm_repeat: 达标风暴推送条数（1=关闭；默认 3=即时+1min+3min；
        取值域 1-5，5=即时+1/3/5/8min 四重推，与 webui 配置域一致）
        user: 多租户用户名（去抖状态按用户隔离）
        platforms: 该用户启用的平台（用于"本轮无数据渠道"提示）
        urgent_notifier: 达标专用强提醒通道（ntfy 等；心跳不触发，避免每轮吵）
        quiet_start/end: 免打扰时段 HH:MM（支持跨零点，如 23:00–07:00）：
                         时段内省略行情心跳、风暴连推与电话/短信；
                         达标主推与 ntfy 照发（出手警报不被吞）
        """
        self.logger = logger
        self.notifier = notifier
        self.urgent_notifier = urgent_notifier
        self.storage = storage
        self.push_drop_min = push_drop_min
        self.push_rise_min = push_rise_min
        self.digest = digest
        self.at_mobile = (at_mobile or "").strip()
        self.storm_repeat = max(1, min(5, int(storm_repeat)))   # 上限 5=webui 声明域（max(1) 曾只钳下限，8 实发 5 而标题写 n/8）
        self.user = (user or "").strip()
        self.platforms = list(platforms) if platforms else list(self.PLATFORM_CN)
        self.quiet_start = (quiet_start or "").strip()
        self.quiet_end = (quiet_end or "").strip()
        # 本机控制台基址（http://127.0.0.1:端口）——Windows 弹窗点击直达单条详情页
        self.base_url = (base_url or "").rstrip("/")
        # 图床配置（用户级 notifier.image_host，main.py 注入）——
        # 推送表格图走 report.upload_chart 统一入口，provider 可切
        # smms；上传失败返回 None 交图挂文本兜底（显示端不可达的
        # 死链床不入降级链）
        self.image_host = image_host or {}
        # 本轮走势图 URL（{(from,to,date): url}，main.job 每轮填充，推送时附带）
        self.round_charts = {}

    def _in_quiet(self, now=None) -> bool:
        """免打扰窗口判定（支持跨零点；未配置/解析失败一律 False）。
        now 可注入（单测）。"""
        def _m(t):
            try:
                return int(t[:2]) * 60 + int(t[3:5])
            except (ValueError, IndexError):
                return None
        s, e = _m(self.quiet_start), _m(self.quiet_end)
        if s is None or e is None or s == e:
            return False
        n = now or datetime.now()
        m = n.hour * 60 + n.minute
        return (s <= m < e) if s < e else (m >= s or m < e)

    def check_and_alert(self, route: Route, prices: List[FlightPrice]):
        if not prices:
            return
        # 控制台/日志：三平台对比 + 多日期对比
        self._compare_platforms(route, prices)
        self._compare_dates(route, prices)

        # 低价阈值提醒
        if route.alert_threshold and route.alert_threshold > 0:
            self._handle_threshold(route, prices)

        # 直飞/中转分类阈值（航班明细来自采集器 extra 字段）
        if route.alert_direct > 0 or route.alert_transfer > 0:
            self._handle_categories(route, prices)

    def check_multi(self, routes_prices: list):
        """一轮一消息：聚合该用户本轮全部航线后推送一条。

        连续多条结构雷同的消息在钉钉流里无法辨识方向/日期——
        每航线一个小节（方向+日期标题），明细合并一张总表。"""
        if not routes_prices:
            return
        built = []
        no_data = []   # 配置了但本轮全渠道零条（采集层一个渠道都没回）
        for route, prices in routes_prices:
            if not prices:
                no_data.append(route)
                continue
            self._compare_platforms(route, prices)
            self._compare_dates(route, prices)
            if route.alert_threshold and route.alert_threshold > 0:
                self._handle_threshold(route, prices)
            sections = self._build_sections(route, prices)
            if sections:
                built.append((route, sections))
        if not built:
            return
        if self.digest and self.notifier:
            self._push_digest_multi(built, no_data)
            return
        # 非 digest 模式：逐航线单条去抖告警
        for route, sections in built:
            for s in sections:
                if route.alert_direct > 0 and s["best_direct"] is not None:
                    self._category_alert(route, s["date"], s["best_direct"],
                                         "direct", route.alert_direct,
                                         s["n_direct"], s["src_platform"],
                                         pool=s.get("all_flights"))
                if route.alert_transfer > 0 and s["best_transfer"] is not None:
                    self._category_alert(route, s["date"], s["best_transfer"],
                                         "transfer", route.alert_transfer,
                                         s["n_transfer_ok"], s["src_platform"],
                                         pool=s.get("all_flights"))

    # ---------- 控制台对比 ----------
    def _compare_platforms(self, route: Route, prices: List[FlightPrice]):
        by_date = {}
        for p in prices:
            by_date.setdefault(p.depart_date, []).append(p)
        for date, lst in sorted(by_date.items()):
            lst = sorted(lst, key=lambda x: x.price)
            best = lst[0]
            line = " | ".join(f"{p.platform}: ￥{p.price:.0f}" for p in lst)
            self.logger.info(
                "[对比] %s->%s %s 全线最低(含中转)=%s ￥%.0f  (%s)",
                route.from_name, route.to_name, date,
                best.platform, best.price, line,
            )

    def _compare_dates(self, route: Route, prices: List[FlightPrice]):
        if len(route.dates) <= 1:
            return
        best_by_date = {}
        for p in prices:
            cur = best_by_date.get(p.depart_date)
            if cur is None or p.price < cur.price:
                best_by_date[p.depart_date] = p
        ordered = sorted(best_by_date.items(), key=lambda kv: kv[1].price)
        if not ordered:
            return
        cheapest_date, cheapest_p = ordered[0]
        self.logger.info(
            "[多日期] %s->%s 最便宜日期=%s ￥%.0f (%s)",
            route.from_name, route.to_name, cheapest_date,
            cheapest_p.price, cheapest_p.platform,
        )

    # ---------- 阈值提醒 + 推送 ----------
    def _handle_threshold(self, route: Route, prices: List[FlightPrice]):
        # 按日期取最低
        best_by_date = {}
        by_date = {}
        for p in prices:
            # 裸价行（渠道半截响应：有价无明细）不参与阈值判定——qunar
            # 已「无明细拒落价」，这里再挡一层：「没抓到」与「没票」
            # 必须区分，残值价曾触发推送并污染去抖基准
            if not p.extra:
                continue
            by_date.setdefault(p.depart_date, []).append(p)
        for date, cand in by_date.items():
            # 跨渠道孤低价守卫：与 digest 路径同防线，legacy
            # 阈值路径不豁免（幻影渠道最低直通电话告警的最后一道门）
            entries = [(p.price + (FLIGGY_TAX_PAD if p.platform == "fliggy"
                                   else 0), p.platform) for p in cand]
            ph = xchan_phantom_idx(entries)
            for i in ph:
                self.logger.warning(
                    "[孤低价守卫] %s→%s %s %s ￥%.0f 拦截（阈值路径）",
                    route.from_code, route.to_code, date,
                    cand[i].platform, cand[i].price)
            for i, p in enumerate(cand):
                if i in ph:
                    continue
                cur = best_by_date.get(date)
                if cur is None or p.price < cur.price:
                    best_by_date[date] = p

        for date, bp in sorted(best_by_date.items()):
            route_key = f"{self.user}|{route.from_code}-{route.to_code}-{date}"

            # 阈值判定用达标口径价（飞猪税前展示价加税垫）；日志/推送仍报
            # 页面价——用户打开页面看到多少就是多少
            eff = bp.price + (FLIGGY_TAX_PAD if bp.platform == "fliggy" else 0)
            if eff > route.alert_threshold:
                # 涨出阈值：清除去抖状态，下次跌破按"首次"重新推
                if self.storage:
                    self.storage.clear_alert_state(route_key)
                continue

            last = self.storage.get_alert_state(route_key) if self.storage else None
            should_push, reason = self._should_push(bp.price, last)

            # 控制台始终打印当前命中低价的状态
            self.logger.warning(
                "[低价] %s->%s %s ￥%.0f (阈值￥%.0f, 上次推送￥%s) -> %s",
                route.from_name, route.to_name, date,
                bp.price, route.alert_threshold,
                f"{last:.0f}" if last else "-",
                "推送" if should_push else f"跳过({reason})",
            )

            if should_push and self.notifier:
                ok = self._push(route, date, bp, last)
                if ok and self.storage:
                    self.storage.set_alert_state(route_key, bp.price)

    def _should_push(self, cur: float, last: Optional[float]):
        if last is None:
            return True, "首次"
        diff = cur - last
        if diff <= -self.push_drop_min:
            return True, f"降￥{-diff:.0f}"
        if diff >= self.push_rise_min:
            return True, f"涨￥{diff:.0f}"
        return False, f"波动￥{diff:+.0f}(<阈值)"

    # ---------- 直飞/中转分类提醒 ----------
    @staticmethod
    def _stale_sane(f: dict) -> bool:
        """补位数据自洽校验：totalDuration 与 起止时刻 必须吻合
        （±10 分钟）。旧提取器编造的错时刻（如 9C8945 的 01:25
        对 10h55m 行程）在此被拦截。"""
        dur = f.get("totalDuration") or ""
        import re as _re
        dm = _re.match(r"(\d+)时(\d+)分?", dur) or _re.match(r"(\d+)h(\d+)m", dur)
        dep, arr = f.get("depTime") or "", f.get("arrTime") or ""
        if not (dm and dep and arr and ":" in dep and ":" in arr):
            return True  # 无时长可校验，放行（真实时刻字段本身可信）
        try:
            total = (int(dep[:2]) * 60 + int(dep[3:])
                     + int(dm.group(1)) * 60 + int(dm.group(2)))
        except ValueError:
            return True
        calc = f"{total // 60 % 24:02d}:{total % 60:02d}"
        ah, am = int(arr[:2]), int(arr[3:])
        diff = abs((int(calc[:2]) * 60 + int(calc[3:])) - (ah * 60 + am))
        diff = min(diff, 1440 - diff)  # 环形差
        return diff <= 10

    def _handle_categories(self, route: Route, prices: List[FlightPrice]):
        sections = self._build_sections(route, prices)
        if not sections:
            return

        if self.digest:
            if self.notifier:
                self._push_digest(route, sections)
            return

        # 非 digest 模式：沿用单条去抖告警
        for s in sections:
            if route.alert_direct > 0 and s["best_direct"] is not None:
                self._category_alert(route, s["date"], s["best_direct"],
                                     "direct", route.alert_direct,
                                     s["n_direct"], s["src_platform"],
                                     pool=s.get("all_flights"))
            if route.alert_transfer > 0 and s["best_transfer"] is not None:
                self._category_alert(route, s["date"], s["best_transfer"],
                                     "transfer", route.alert_transfer,
                                     s["n_transfer_ok"], s["src_platform"],
                                     pool=s.get("all_flights"))

    def _build_sections(self, route: Route, prices: List[FlightPrice]) -> list:
        """构建该航线的分类明细 sections（补位/仲裁/窗口过滤/达标判定），
        无推送副作用——供单航线与聚合两条链路共用。"""
        sections = []
        for date in sorted({p.depart_date for p in prices}):
            flights = []
            src_platform = "qunar"
            for p in prices:
                if p.depart_date != date or not p.extra:
                    continue
                try:
                    obj = json.loads(p.extra)
                except Exception:
                    continue
                if isinstance(obj, list):
                    flights.extend(_flights_from_extra(obj, date, p.platform))
                    src_platform = p.platform
            if not flights:
                continue

            # 近期明细补位：当轮缺明细的平台（如去哪儿被限流回退 httpx）
            # 用其近 6 小时最后成功明细补——仅用于展示，达标判定只认当轮
            have = {f.get("_platform") for f in flights}
            try:
                from report import recent_platform_flights
                from core.flightnorm import normalize as _fnorm
                # 兜底路径锚定仓库根（CWD 家族，同 main._SENT_PATH）
                db = self.storage.db_path if self.storage else os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "prices.db")
                recent = recent_platform_flights(
                    db, route.from_code, route.to_code, date, hours=6)
                for p, (age, fl) in recent.items():
                    if p in have:
                        continue
                    for f in fl:
                        if isinstance(f, dict) and "price" in f:
                            if not self._stale_sane(f):
                                continue  # 补位数据自洽校验不过，弃
                            g = dict(f)
                            g["_platform"] = p
                            g["_stale_h"] = round(age, 1)
                            # 补位行同样过 normalize：主路径
                            # 逐行 _fnorm，补位行曾裸进——layoverM/layoverT/
                            # stopover/transferBaggage 兜底全缺，明细表
                            # 补位行的停留/经停/直挂徽标必空
                            _fnorm(g, date)
                            if g.get("_dep_mismatch"):
                                continue  # 渠道滚动行不入池（同主路径）
                            flights.append(g)
            except Exception as e:
                self.logger.warning("近期明细补位失败: %s", e)

            # 跨源时刻仲裁：同航班号时以飞猪（结构化 JSON，可靠）时刻为准，
            # 纠正去哪儿碎片解析中残余的邻串时刻污染。
            # 仅直飞行（code 无 /）参战：中转链的任一段号都可能恰是 fliggy
            # 在售直飞（热门中转 OD 常见），按段匹配会用第二段时刻覆盖整行
            # 起降，且整链时刻与 layoverM 级联耦合、逐段重算得不偿失——整链禁入
            ref = {}
            for f in flights:
                if f.get("_platform") == "fliggy" and f.get("code"):
                    ref.setdefault(f["code"], f)
            for f in flights:
                if (f.get("_platform") == "qunar" and f.get("code")
                        and "/" not in f["code"]):
                    r = ref.get(f["code"])
                    if r and r["depTime"] and r["depTime"] != f["depTime"]:
                        f["depTime"] = r["depTime"]
                        f["arrTime"] = r["arrTime"] or f["arrTime"]
                        # 跨天随真源同步：时刻被纠正后若跨天
                        # 翻转，旧 arrDate 会让 normalize 的日期优先推导
                        # 产出与时刻矛盾的 durM——fliggy arrDate 恒在场
                        if r.get("arrDate"):
                            f["arrDate"] = r["arrDate"]
                        # 仲裁改时刻后重算派生字段：normalize
                        # 各守卫均幂等，重跑即得与新时刻自洽的 durM/跨天
                        # （注释必须与实现自洽，禁「durM 不重算，行内自相矛盾」式自认）
                        from core.flightnorm import normalize as _rf
                        _rf(f, date)

            # 价格统一取整（各渠道 float 携带 .0 尾巴，污染所有显示位）
            for f in flights:
                try:
                    f["price"] = round(float(f["price"]))
                except (TypeError, ValueError):
                    pass

            # 同指纹衔接补全：qunar 列表页不渲染停留时长且响应混淆体
            # 实测不可挖（0/24 锚定命中）——同班次在携程测得的真实停留
            # 补到缺行（停留是航线属性，非渠道属性）
            self._propagate_layover(flights)
            # 同指纹决策字段补全（cabin/meal/prate/plane）：
            # 明细次行/推送图决策行的信息密度不再随渠道解析能力起伏
            self._propagate_fields(flights)

            # 出发时段约束（如返程"10-4 只看晚间"）：窗口外班次整体剔除，
            # 明细/达标/速览/比价全链路一致
            dmin = (route.dep_time_min or "").strip()
            dmax = (route.dep_time_max or "").strip()
            if dmin or dmax:
                flights = [f for f in flights if self._dep_in_window(
                    f.get("depTime", ""), dmin, dmax)]

            directs = [f for f in flights if not f.get("transCity")]
            transfers = [f for f in flights if f.get("transCity")]
            # 跨渠道孤低价守卫：直飞/中转分别按「其他渠道最低
            # 价中位数 ×XCHAN_PHANTOM_RATIO」判 _xphan，剔除发生在一切
            # 选择之前——达标/告警/电话、TOP5、行情最优、同班比价（pool）
            # 全在下游。渠道内锚（fliggy/qunar 0.5x）依赖解析器健康度，
            # 解析器异常窗口下渠道内锚失守时 ￥700 级低价可直通电话告警；跨渠道中位
            # 数是独立第二道防线。补位行（_stale_h）参锚：qunar 是中转
            # 仅有的两个锚供给方之一又最常补位，排除会频繁退化到 n<2
            # 全盲（6h 价漂压不穿 0.5 阈值）。原始行仍在存储与控制台
            # 明细（保真），digest 尾部有拦截留痕
            for _lst in (directs, transfers):
                self._mark_xchan(_lst)
            # 第二层：明细混合池守卫（直飞+中转合并，与曲线端 _rounds
            # 行级守卫同判据同函数）——分类池的锚是「其他渠道同类最低
            # 中位」，双渠道同轮毒价互抬锚可穿透：中转池锚供给方少时
            # 两毒价互相进 others 压住中位、双双逃过比率线直通达标
            # 推送（实锤轮毒价对在分类池面对的 others 中位 1647.5、
            # 0.5×=823；进混合池后健康锚供给变宽——直飞行价进池把
            # 中位抬过 2241——1100 越过 1120 线被拦）。分类池拦「单
            # 渠道毒」，混合池拦「低价渠道对互抬」；全史 60 天 18 万
            # 中转明细误杀 11 条（0.006%）且全部落毒价家族，真降价
            # 案（五渠道同水位）零误杀——宁拦促销勿放毒价（不可购价
            # 幻影达标的伤害大于错失促销，产品定论）。
            # 单遍定版不做迭代：互抬对的解救机理是锚供给变宽，不是
            # 「拦一个再拦另一个」——薄锚池首轮全逃时无标可收敛、
            # 迭代无起点（死锁），厚锚池首轮即双拦无需第二轮；pmin
            # 锚模型下迭代与单遍行为等价，宁删机制勿留假迭代外衣。
            # 健康锚 <2 供给时互抬属纯统计无解的数学边界（测试钉在
            # 案），宁漏勿假守卫；且 ≥2 健康锚也非安全线——能否互抬
            # 取决于毒价与健康锚的价格几何（probe 实证 2 锚仍可逃），
            # 盲区随价格几何浮动，不存在恒安全的锚数门槛。
            self._mark_xchan(directs + transfers)
            xphans = [(f.get("_platform"), f.get("price"))
                      for f in flights if f.get("_xphan")]
            if xphans:
                self.logger.warning(
                    "[孤低价守卫] %s→%s %s 拦截 %d 行（%s，< 其他渠道最低"
                    "中位的 %.0f%%）",
                    route.from_code, route.to_code, date, len(xphans),
                    "、".join(f"{p}￥{v:.0f}" for p, v in xphans[:4]),
                    XCHAN_PHANTOM_RATIO * 100)
            directs = [f for f in directs if not f.get("_xphan")]
            transfers = [f for f in transfers if not f.get("_xphan")]
            # 行情口径 vs 达标口径分离：明细总表/走势曲线展示
            # 「中转行情」（到达+衔接约束，不限直挂——与走势橙线同口径，
            # 曲线与列表含义一致）；达标判定（best_transfer/hits）仍用
            # _transfer_ok 全口径（含行李直挂配置）
            ok_transfers = [f for f in transfers if self._transfer_ok(f, route)]
            top_transfers = [
                f for f in transfers
                if self._arrival_ok(f, route.transfer_arrival_max)
                and (not route.transfer_layover_min
                     or (isinstance(f.get("layoverM"), int)
                         and f["layoverM"] >= route.transfer_layover_min))]
            # 达标判定只认当轮实时数据（_stale_h 为近期补位，仅作展示）
            fresh_d = [f for f in directs if not f.get("_stale_h")]
            fresh_t = [f for f in ok_transfers if not f.get("_stale_h")]
            # 达标口径最优：按 _qual_price 取最小——按页面价取最低曾让
            # 高页面价但达标口径更优的行被遮蔽（页面最低行税垫/口径修正
            # 后超线，次低行真达标却永不参判，达标漏报）
            best_direct = (min(fresh_d, key=_qual_price)
                           if fresh_d else None)
            best_transfer = (min(fresh_t, key=_qual_price)
                             if fresh_t else None)
            # 行情口径最优（不限直挂）：KPI 展示/建议行差值基——与达标链
            # 同治先认当轮：6h 补位旧价曾无标注进 KPI 差值，
            # 渠道瞬断时「距线N%」实为数小时前旧价的差值；全 stale 才
            # 回落补位行（表格/明细行的补位行均带「·Nh前」角标）。
            # mkt 池先过 _dedup_tie：同价同班合并行携 _tie_rows 快照，
            # KPI/summary 的组 OR 判定（_tie_any_ok）才有成员域可查
            # （P1-1 五处口径收齐的取数侧）
            mkt_pool = _dedup_tie(top_transfers)
            fresh_mt = [f for f in mkt_pool if not f.get("_stale_h")]
            best_transfer_mkt = (
                min(fresh_mt, key=lambda f: f["price"])
                if fresh_mt else
                (min(mkt_pool, key=lambda f: f["price"])
                 if mkt_pool else None))

            if best_direct is not None:
                self.logger.info(
                    "[直飞] %s->%s %s 最低 ￥%d（%s %s-%s%s）",
                    route.from_name, route.to_name, date, best_direct["price"],
                    best_direct["name"], best_direct["depTime"],
                    best_direct["arrTime"],
                    # .get 形态（键可缺席双源：r241 爬虫侧无值不落 +
                    # normalize 缺起降时刻的早退路径不写 crossDayDesc；
                    # 键在场时输出逐字节不变）
                    f" {best_direct.get('crossDayDesc') or ''}"
                    if best_direct.get("crossDayDesc") else "")
            if transfers:
                if best_transfer is not None:
                    # 注意措辞：这是「当前最低中转价」不是「已达标」——
                    # 是否达标由 _collect_hits 对阈值另行判定（曾误导用户
                    # 以为达标了没弹窗）
                    self.logger.info(
                        "[中转最低] %s->%s %s 最低 ￥%d（%s 经%s %s-%s%s）",
                        route.from_name, route.to_name, date,
                        best_transfer["price"], best_transfer["name"],
                        best_transfer.get("transCity", ""),
                        best_transfer["depTime"],
                        best_transfer["arrTime"],
                        f" {best_transfer.get('crossDayDesc') or ''}"
                        if best_transfer.get("crossDayDesc") else "")
                else:
                    cheapest = min(transfers, key=lambda f: f["price"])
                    self.logger.info(
                        "[中转] %s->%s %s 无满足到达约束的班次；"
                        "无视约束最低 ￥%d（%s %s）",
                        route.from_name, route.to_name, date, cheapest["price"],
                        cheapest["name"], cheapest.get("crossDayDesc") or "-")

            # 各平台全线最低（含中转，不筛）——行级混合池守卫先行
            # （与 webui _state 行级守卫同判据同输入）：毒渠道轮最低
            # （10-04 实锤 qunar 1034）曾直出图挂兜底「各渠道最低」
            # 文本行。渠道行价被拦时回落该渠道剔毒明细的最低——渠道
            # 仍有可信行情，不整渠道从行情面消失
            _dprices = [p for p in prices if p.depart_date == date]
            _pdrop = xchan_phantom_idx(
                [(p.price + (FLIGGY_TAX_PAD if p.platform == "fliggy"
                             else 0), p.platform) for p in _dprices])
            platform_mins = {}
            for _i, p in enumerate(_dprices):
                if _i in _pdrop:
                    continue
                cur = platform_mins.get(p.platform)
                if cur is None or p.price < cur:
                    platform_mins[p.platform] = p.price
            for f in directs + transfers:
                if f.get("_xphan"):
                    continue
                _pl = f.get("_platform")
                cur = platform_mins.get(_pl)
                if cur is None or f["price"] < cur:
                    platform_mins[_pl] = f["price"]

            # 各渠道各自最低 3 条（与主 TOP3 同一套筛选：
            # 直飞全量 + 中转仅留满足到达约束的）
            by_plat = {}
            for f in directs + ok_transfers:
                by_plat.setdefault(f.get("_platform", "?"), []).append(f)
            plat_top3 = {p: sorted(v, key=lambda x: x["price"])[:3]
                         for p, v in by_plat.items()}

            sections.append({
                "date": date,
                "top_direct": _dedup_tie(
                    sorted(directs, key=lambda f: f["price"]))[:5],
                "top_transfer": _dedup_tie(
                    sorted(top_transfers, key=lambda f: f["price"]))[:5],
                "best_direct": best_direct,
                "best_transfer": best_transfer,
                "best_transfer_mkt": best_transfer_mkt,
                "n_direct": len(directs),
                "n_transfer_ok": len(ok_transfers),
                "platform_mins": platform_mins,
                "plat_top3": plat_top3,
                "src_platform": src_platform,
                "pool": fresh_d + fresh_t,
                "all_flights": directs + transfers,
                "seen_plats": sorted({p.platform for p in prices
                                      if p.depart_date == date}),
                "xphans": xphans,
            })
        return sections

    @staticmethod
    def _mark_xchan(rows):
        """行级打 _xphan 标（跨渠道孤低价，xchan_phantom_idx 纯函数判定；
        脏价按 inf 参锚=永不判孤、但也拖不低本渠道锚之外任何锚）。"""
        entries = []
        for f in rows:
            try:
                entries.append((_qual_price(f), f.get("_platform") or ""))
            except Exception:
                entries.append((float("inf"), f.get("_platform") or ""))
        for i in xchan_phantom_idx(entries):
            rows[i]["_xphan"] = True

    @staticmethod
    def _pref_platform(f: dict, pool: list) -> str:
        """跳转链接渠道选择：同价同班（时刻+经停+到达日+价格指纹）多渠道
        在售时优先去哪儿/携程——出票覆盖面与稳定性最好；无同价优选则
        回落最低价所在渠道（链接落点价与文案一致，不挂羊头）。
        指纹用 arrDate 不用 crossDayDesc：跨天写法渠道不一致（实锤
        qunar「+1天」vs ctrip 空）曾令跨天班（中转常态）同价优选恒失效。"""
        plat = f.get("_platform") or "qunar"
        try:
            key = (f.get("depTime"), f.get("arrTime"),
                   f.get("transCity") or "", f.get("arrDate") or "",
                   round(float(f.get("price", 0))))
        except (TypeError, ValueError):
            return plat
        for p in ("qunar", "ctrip"):
            if p == plat:
                return plat
            for g in pool or []:
                if g is f or not g.get("_platform"):
                    continue
                try:
                    gk = (g.get("depTime"), g.get("arrTime"),
                          g.get("transCity") or "",
                          g.get("arrDate") or "",
                          round(float(g.get("price", 0))))
                except (TypeError, ValueError):
                    continue
                if gk == key and g["_platform"] == p:
                    return p
        return plat

    # ---------- 聚合推送（一轮一消息） ----------
    @staticmethod
    def _route_short(route) -> str:
        return f"{route.from_name[:1]}→{route.to_name[:1]}"

    @staticmethod
    def _date_short(date: str) -> str:
        return date[5:].replace("-", "/") if date else ""

    @staticmethod
    def _dep_win(route):
        """出发窗口元组：走势/日报取数链与列表同窗（否则曲线最低点可
        来自列表已整体剔除的班次——「图和列表对不上」）；未配置=None。"""
        dmin = (getattr(route, "dep_time_min", "") or "").strip()
        dmax = (getattr(route, "dep_time_max", "") or "").strip()
        return (dmin, dmax) if (dmin or dmax) else None

    def _deltas(self, route, date: str) -> dict:
        """较上轮涨跌：走势序列倒数两轮之差（直飞/达标中转）。"""
        try:
            if self.storage:
                from report import _rounds
                hist = _rounds(self.storage.db_path, route.from_code,
                               route.to_code, date,
                               route.transfer_arrival_max,
                               layover_min=route.transfer_layover_min,
                               dep_win=self._dep_win(route))
                out = {}
                for tag, idx in (("direct", 1), ("transfer", 2)):
                    vs = [r[idx] for r in hist if r[idx]]
                    if len(vs) >= 2:
                        out[tag] = vs[-1] - vs[-2]
                return out
        except Exception:
            # 查询异常（如磁盘满窗）静默省略涨跌注——与 _trend_line
            # 的「暂缺」分档不同律：涨跌是次要信号（±10 起报门，
            # _delta_txt），缺行零决策损失且下行 KPI 价格仍在；
            # 趋势行是 7 天窗唯一文本载体才要求可观测
            pass
        return {}

    @staticmethod
    def _delta_txt(deltas: dict, tag: str) -> str:
        dv = deltas.get(tag)
        # ￥1-9 的轮间抖动是渠道重摇噪音（线上实锤「较上轮 ↑￥1」），
        # 不值得占一行行宽；±10 元起报
        if not dv or abs(dv) < 10:
            return ""
        arrow = "↓" if dv <= 0 else "↑"
        return f" ｜ 较上轮 {arrow}￥{abs(dv):.0f}"

    def _trend_line(self, route, date: str):
        """近 7 天趋势小结（较窗口首值）：「直飞 ↓8% ｜ 中转 ↓3%」；
        词面单源 _trend_line_str（日报 build_and_push 同消费，能力
        对称三十§3）；无 storage / 数据不足 → 空串（文案静默省略，
        不炸推送）；查询异常 → None（调用点补「暂缺」标注——异常
        省略曾是静默形态，磁盘满窗 19 条推送趋势行无声消失无任何缺
        标）。"""
        if not self.storage:
            return ""
        try:
            return _trend_line_str(
                self.storage.db_path, route.from_code, route.to_code,
                date, route.transfer_arrival_max,
                route.transfer_layover_min, self._dep_win(route))
        except Exception as e:
            self.logger.warning(
                "[趋势] 近7天趋势行生成失败（本轮省略标注）: %r", e)
            return None

    def _suggest_line(self, route, s) -> str:
        """一句话操作建议：破线出手 / 近线蹲守（≤10%）/ 远线观望；
        直飞中转取「相对距线比例」最近的那条说（曾按 qual 价绝对值
        取 min——高价线绝对差更大但比例更近时选错条）。
        出手判定用达标口径价（飞猪税垫）——「建议出手」必须是可支付价；
        蹲守/观望档用行情原价（中转取 best_transfer_mkt 行情口径，与同
        消息 🟨 擦边/走势琥珀环同基——曾全程用税后价，飞猪最优时 KPI
        说擦边可蹲守、建议行却说观望，同一条推送自相矛盾）。
        日期选择由调用方跨 sections 决定，本函数只看单 section。
        超线返回空：选档=min 距线比例，最近的一条都超线 >10%
        即全部超线——「继续观望」与 KPI 差额、仪表条三重冗余零增量，
        撤行减段；出手/蹲守档保留。"""
        cands = []
        bd, bt = s.get("best_direct"), s.get("best_transfer")
        if route.alert_direct > 0 and bd:
            cands.append((_qual_price(bd), route.alert_direct, "直飞",
                          bd["price"], bd.get("_platform")))
        if route.alert_transfer > 0 and bt:
            bt_mkt = s.get("best_transfer_mkt") or bt
            cands.append((_qual_price(bt), route.alert_transfer, "中转",
                          bt_mkt["price"], bt_mkt.get("_platform")))
        if not cands:
            return ""
        price, th, label, mkt, mkt_plat = min(
            cands, key=lambda c: abs(c[1] - c[0]) / max(c[1], 1))
        # 不带 emoji：调用处统一加 💡 前缀（曾出现 💡🧘 双 emoji 连排）。
        # 不说「破线」：图例 🟩破线=行情破线未必达标，此处是达标口径
        # （_qual_price），同词两义曾让用户误读（措辞收口）。
        # 短式定版：常见形态本就 41-48 半角、_fit_line 末档
        # 兜底形同虚设——建议行恰是折行断点最不可控的行，改 25-30 半角
        # 短式（含调用处 "> 💡 " 前缀仍 ≤20 全角）
        if price < th:
            # 「真达标」词面（与恰达线分支/四档图例同字——
            # 旧「达标」是 正名的漏网）；「低￥N」走 gap_txt 单源；
            # label 与档位词间空格分隔（
            # 「直飞真达标」粘连连读）
            return (f"{label} {TIER_FULL['qual']} "
                    f"{gap_txt(price, th, True)}，建议出手")
        if price == th:
            # 恰达线：旧词「达标 低￥0」（差额词手拼旁路，收口）
            return f"{label} {TIER_FULL['qual']}，建议出手"
        gap = (mkt - th) / th
        # 税前注仅垫税启用且行情行是飞猪（收口：曾按「两价不等」
        # 判——中转档行情最优与达标最优常是两个航班，注的实为航班差非
        # 税差，误导）；
        tax_pad = ("（税前价）" if FLIGGY_TAX_PAD > 0
                   and mkt_plat == "fliggy" else "")
        # 蹲守档与行情同基（定律，补完实现另一半）：
        # 判定用行情价、金额曾是达标口径价——同消息 KPI 行1「低￥10」
        # 与建议行「差￥50」两数互斥。差额词走 gap_txt 单源（行情口径
        # qual_hit=False：恰达线出「行情破线」不与 🟩 图例互斥）
        if gap < 0:
            return f"{label}{_MKT_SHORT}{gap_txt(mkt, th, False)}，蹲守{tax_pad}"
        if gap == 0:
            return f"{label}{gap_txt(mkt, th, False)}，蹲守{tax_pad}"
        if gap <= NEAR_RATIO:
            # 「擦边N%」词面单源（推送审校：与 kpi_tier_txt:107
            # 同形重复构造，改词面必漏其一——抽 _near_txt 小单源两处共用）
            return f"{label}{_near_txt(gap)}，蹲守提醒{tax_pad}"
        return ""

    @staticmethod
    def _sect_gap_ratio(route, s) -> Optional[float]:
        """单日期 section 对各线的最小相对距线比例（达标口径价，与出手
        判定同基）：调用方跨日期选「距线比例最近」的建议发言用；
        该日期无线可比（无班次/未设线）返回 None。"""
        ratios = []
        bd, bt = s.get("best_direct"), s.get("best_transfer")
        if route.alert_direct > 0 and bd:
            ratios.append(abs(route.alert_direct - _qual_price(bd))
                          / max(route.alert_direct, 1))
        if route.alert_transfer > 0 and bt:
            ratios.append(abs(route.alert_transfer - _qual_price(bt))
                          / max(route.alert_transfer, 1))
        return min(ratios) if ratios else None

    def _phone_should_ring(self, hit) -> bool:
        """电话去抖：首拨必响；同键 2 小时内不重拨，除非再降 ≥￥50。"""
        route, s, kind, f, _th = hit
        key = (f"{self.user}|phone|{route.from_code}-{route.to_code}-"
               f"{s['date']}-{kind}")
        now = datetime.now()
        if self.storage:
            try:
                import sqlite3
                conn = sqlite3.connect(self.storage.db_path)
                row = conn.execute(
                    "SELECT last_price, last_sent_at FROM alert_state "
                    "WHERE route_key=?", (key,)).fetchone()
                if row:
                    prev_price, last_at = float(row[0] or 0), row[1]
                    t = datetime.strptime(last_at[:19], "%Y-%m-%d %H:%M:%S")
                    if (now - t).total_seconds() < 2 * 3600 \
                            and (prev_price - f["price"]) < 50:
                        return False
                conn.execute(
                    "INSERT INTO alert_state (route_key, last_price, last_sent_at) "
                    "VALUES (?,?,?) ON CONFLICT(route_key) DO UPDATE SET "
                    "last_price=excluded.last_price, last_sent_at=excluded.last_sent_at",
                    (key, float(f["price"]), now.strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                conn.close()
            except Exception:
                pass
        return True

    def _launch_public(self) -> bool:
        """base_url 是否公网可点：127.0.0.1/localhost/::1 回环仅本机
        Windows 弹窗 launch 用——钉钉 desp 不追加「📲 完整详情」链接
        （手机点回环地址必死链）。判定单源收编 core.notifier
        （webui 测试邮件同挂防回潮）。"""
        from core.notifier import launch_is_public
        return launch_is_public(self.base_url)

    def _archive_notify(self, title: str, desp: str) -> str:
        """达标详情存档 → /notify/{nid} 直达链接（无 base_url 返回空）。

        Windows 弹窗与钉钉「完整详情」共用同一份单条详情页——
        轻页非控制台，点击即看全量信息。只保留最近 20 份。"""
        if not self.base_url:
            return ""
        try:
            import json as _json
            import os as _os
            # uuid 尾巴：多用户同秒归档时 nid 相同曾互相覆盖（后写删前写）。
            # 全大写：webui /notify 侧净化正则当时是
            # [^A-Z0-9]（已放宽 [^A-Za-z0-9] 双保险），hex 小写
            # 字母曾被剥掉——约 94% 的 nid 落点 404（弹窗/ntfy/钉钉
            # 「完整详情」三条出口大面积死链，测试用全大写样例恰掩蔽）
            nid = ("N" + datetime.now().strftime("%Y%m%d%H%M%S")
                   + uuid.uuid4().hex[:6].upper())
            _os.makedirs("data/notify", exist_ok=True)
            with open(f"data/notify/{nid}.json", "w", encoding="utf-8") as f:
                _json.dump({"nid": nid, "title": title, "desp": desp,
                            "ts": datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S")},
                           f, ensure_ascii=False)
            olds = sorted(_os.listdir("data/notify"))
            for old in olds[:-20]:
                try:
                    _os.remove(_os.path.join("data/notify", old))
                except OSError:
                    pass
            return f"{self.base_url}/notify/{nid}"
        except Exception as e:
            self.logger.warning("[详情存档] 失败: %s", e)
            return ""

    def _send_urgent(self, title: str, desp: str, hits: list,
                     launch: str = "") -> bool:
        """达标强提醒分发：阿里云电话/短信用极简精确文案（语音播报友好），
        Windows 右下角弹窗带 launch 直达单条详情页，ntfy 等用完整消息。
        仅达标调用——未达标轮次不会进来。免打扰时段电话/短信抑制。
        返回全部通道是否成功—— 实锤：通道挂了只留一行 WARNING
        （WinToast 先成功掩盖电话哑弹两天无人察觉），失败必须浮出水面
        到钉钉主推（告警系统自身的故障要能被看见）。"""
        if not hits:
            return True
        quiet = self._in_quiet()
        all_ok = True
        for un in (self.urgent_notifier or []):
            try:
                from core.notifier import (AliyunAlertNotifier,
                                           WindowsToastNotifier)
                if isinstance(un, AliyunAlertNotifier):
                    if quiet:
                        self.logger.info("[静默] %s–%s 免打扰时段，"
                                         "电话/短信提醒抑制（ntfy 照发）",
                                         self.quiet_start, self.quiet_end)
                        continue
                    r0, s0, k0, f0, th0 = hits[0]
                    # 电话/短信词面同律构造端消毒（r242 审校 Minor-3）：
                    # name/transCity 是渠道自由文本，TTS 词面读出尖括号
                    # 形态不可接受；route 配置名同理
                    ay_title = sanitize_desp(
                        f"机票达标 {r0.from_name}到{r0.to_name}"
                        f" {s0['date'][5:].replace('-', '月')}日"
                        f" {k0}价{f0['price']:.0f}")
                    # 电话价=展示价、判定线=达标口径线：飞猪命中时展示
                    # 价为税前，可支付差额被夸大 ￥100——「已低于」注
                    # 「税前」与钉钉 hits 行同词（口径收口）
                    _ay_tax = ("税前" if FLIGGY_TAX_PAD > 0
                               and f0.get("_platform") == "fliggy" else "")
                    ay_msg = sanitize_desp(
                        f"{f0.get('name', '')} {f0['depTime']}起飞"
                        f" 到{f0['arrTime']}"
                        f"{' 经' + f0['transCity'] if f0.get('transCity') else ''}"
                        f" 已低于{th0:.0f}元{_ay_tax} 立即下单")
                    all_ok = un.send(ay_title, ay_msg) and all_ok
                elif isinstance(un, WindowsToastNotifier):
                    all_ok = bool(un.send(title, desp, launch=launch)) \
                        and all_ok
                else:
                    # ntfy click 跳转仅公网可达时携带：回环
                    # base_url（默认 127.0.0.1）在手机上点开必死——钉钉
                    # desp 侧早有 _launch_public 守卫，ntfy 侧对齐；本机
                    # WinToast 点回环合法不受影响
                    all_ok = bool(un.send(
                        title, desp,
                        launch=(launch if self._launch_public() else ""))) \
                        and all_ok
            except Exception as e:
                self.logger.warning("[强提醒] 发送异常: %s", e)
                all_ok = False
        # 分发落账（备2）：钉钉主推单发有 push_history，电话/弹窗/ntfy
        # 三通道曾不入账——控制台「推送记录」对强提醒失明，失败可见性
        # 只剩 desp 内警示行（依赖钉钉通道本身活着）
        try:
            from core.notifier import _append_push_history
            _append_push_history(title, desp, all_ok, ch="urgent")
        except Exception:
            pass
        return all_ok

    def _heartbeat_gate(self) -> bool:
        """未达标心跳退避闸：文本通道连败
        ≥6 轮后跳过心跳、每 4 轮放行一次探测（退避语义见
        notifier._HeartbeatBackoff）。达标轮与回落出线轮由调用方的
        hits/_prev_hit 条件结构性排除——必达不可吞；无 heartbeat_allow
        属性的通道（ntfy/弹窗）恒放行。"""
        allow = getattr(self.notifier, "heartbeat_allow", None)
        if allow and not allow():
            self.logger.warning(
                "[退避] 推送通道连败，未达标心跳跳过本轮（每 %d 轮探测一次）",
                getattr(self.notifier, "HB_PROBE_EVERY", 4))
            return False
        return True

    def _collect_hits(self, rs_list: list):
        """达标聚合（route, s, kind, f, th）——纯函数，无副作用。"""
        hits = []
        for route, sections in rs_list:
            for s in sections:
                if (route.alert_direct > 0 and s["best_direct"] is not None
                        and _qual_price(s["best_direct"])
                        <= route.alert_direct):
                    hits.append((route, s, "直飞", s["best_direct"],
                                 route.alert_direct))
                if (route.alert_transfer > 0 and s["best_transfer"] is not None
                        and _qual_price(s["best_transfer"])
                        <= route.alert_transfer):
                    hits.append((route, s, "中转", s["best_transfer"],
                                 route.alert_transfer))
        return hits

    def _ops_notes(self, rs_list: list, no_data: list = None) -> list:
        """运维对账注组装（总表 PNG 小注主路径 / 图挂兜底文本回退共用）：
        无数据渠道、中转直挂标注缺失、孤低价拦截、全渠道无数据航线。
        渠道名直出；「维护中」语义=官方下线预期管理，按平台名硬编码
        会把健康渠道的限流单轮缺失误标为维护态（实况=下轮自然回）；
        废弃态如需再标注应挂爬虫侧维护标志位。"""
        notes = []
        for route, sections in rs_list:
            for s in sections:
                missing = [p for p in self.platforms
                           if p not in (s.get("seen_plats") or [])]
                if missing:
                    notes.append(
                        f"{self._route_short(route)} "
                        f"{self._date_short(s['date'])} 当轮无数据："
                        + "、".join(self.PLATFORM_CN.get(p, p)
                                    for p in missing))
        for route_bg, secs_bg in rs_list:
            if str(getattr(route_bg, "transfer_baggage", "")
                   or "") != "direct":
                continue
            for s_bg in secs_bg:
                t_bg = s_bg.get("top_transfer") or []
                # 组感知：dedup 合并行任一成员（本体或 _tie_rows 快照）
                # 有标注即不算缺——头成员单判曾与组 OR 达标判定同屏矛盾
                if t_bg and not any(_tie_grp_flagged(f) for f in t_bg):
                    notes.append(
                        f"{self._route_short(route_bg)} "
                        f"{self._date_short(s_bg['date'])} "
                        f"中转直挂标注缺失·按未标注判不达标")
        for route, sections in rs_list:
            for s in sections:
                xp = s.get("xphans") or []
                if not xp:
                    continue
                byp = {}
                for p, v in xp:
                    byp[p] = min(byp.get(p, 9e9), v if v else 9e9)
                names = "、".join(
                    f"{self.PLATFORM_CN.get(p, p)}￥{v:.0f}"
                    for p, v in sorted(byp.items(), key=lambda kv: kv[1]))
                notes.append(
                    f"{self._route_short(route)} "
                    f"{self._date_short(s['date'])} "
                    f"孤低价拦截×{len(xp)}：{names}")
        for r_nd in (no_data or []):
            notes.append(
                f"{self._route_short(r_nd)} 本轮全渠道无数据")
        return notes

    def _digest_payload(self, rs_list: list, fresh: bool = True,
                        with_tables: bool = True, fell: bool = False,
                        no_data: list = None, with_charts: bool = True) -> dict:
        """纯构建聚合推送文案：不发送、不拨号、不写去抖状态。

        fresh=False → 持续达标标题（🔔 而非 🚨）；
        fell=True → 上一推送轮有达标、本轮转无达标：标题/正文给
        「↩️ 回落出线」显式语义（禁静默变 ❌——用户无从知何时失效）；
        with_tables=False → 跳过明细总表图床上传（控制台推送预览器用，
        本地渲染近似效果，不打外部网络）；
        with_charts=False → 整段跳过走势图块（预览器无本轮图 URL，
        走势分支曾恒出「⚠️ 走势图…」假警告误导用户）；
        no_data → 配置了但本轮全渠道零条的航线（desp 补对账行）。"""
        hits = self._collect_hits(rs_list)

        def _summary_excl(r_x=None, d_x=None):
            """航线清单（条目列表），可排除标题锚点已单独示出的那条（标题
            去重：「最近 上→乌 09/25 …｜上→乌 09/25 · 乌→上 10/05」曾重复）。
            列表形态供 _rest_seg 逐条预算（挂账①）。"""
            return [f"{self._route_short(r)} {self._date_short(s['date'])}"
                    for r, secs in rs_list for s in secs
                    if not (r is r_x and s["date"] == d_x)]

        if hits:
            r0, s0, k0, f0, _ = hits[0]
            # 「·」分隔（推送审校 P1-2）：「达标！」分支有！
            # 天然分隔，「持续达标」曾直拼航线缩写读成「持续达标上→乌」
            # （push_history 实发），标题扫读第一眼歧义
            prefix = "🚨 达标！" if fresh else "🔔 持续达标·"
            rest = _summary_excl(r0, s0["date"])
            title = _rest_seg(
                f"{prefix}{self._route_short(r0)} "
                f"{self._date_short(s0['date'])} {k0}￥{f0['price']:.0f}",
                rest)
        elif fell:
            # 回落出线：保留「最近差多少」锚点信息，档位换 ↩️
            anchor_gap = None
            for route, sections in rs_list:
                for s in sections:
                    for best, th, kind in (
                            (s.get("best_direct"), route.alert_direct, "直飞"),
                            (s.get("best_transfer_mkt")
                             or s.get("best_transfer"),
                             route.alert_transfer, "中转")):
                        if best and th > 0:
                            gap = best["price"] - th
                            if gap > 0 and (anchor_gap is None
                                            or gap < anchor_gap[0]):
                                # 差额词单源：标题差额词曾第三份
                                # 手抄，改词必漏——随选中锚一并带 gap_txt 词
                                anchor_gap = (gap, route, s, kind,
                                              gap_txt(best["price"], th, False))
            if anchor_gap:
                gap, r0, s0, k0, gw0 = anchor_gap
                rest = _summary_excl(r0, s0["date"])
                title = _rest_seg(
                    f"↩️ 回落出线｜最近 {self._route_short(r0)} "
                    f"{self._date_short(s0['date'])} "
                    f"{k0}{gw0}", rest)
            else:
                title = f"↩️ 回落出线｜{' · '.join(_summary_excl())}"
        else:
            # 未达标锚点：全线最接近阈值的一项（扫读一眼知道还差多少）
            anchor = None
            # 行情破线锚（审校 P2-1）：价已破线（≤线）却未达标（直挂
            # 等约束未过）的独占轮，两「差￥」分支全跳过曾塌缩为
            # 「❌ 全部未达标｜清单」——「其实已低过线」只存在于正文
            # KPI。无超线锚时挂 |gap| 最大的破线锚（价最低=最有希望），
            # 词面走 gap_txt 单源（低￥N/恰线=行情破线）；超线锚优先
            # 维持既有行为（超线轮讲「还差多少」零回归）。
            anchor_break = None
            for route, sections in rs_list:
                for s in sections:
                    for best, th, kind in (
                            (s.get("best_direct"), route.alert_direct, "直飞"),
                            # 锚点与 KPI 行情口径一致（不限直挂）——
                            # 差多少看的是行情价，不是合规筛选后的价
                            (s.get("best_transfer_mkt")
                             or s.get("best_transfer"),
                             route.alert_transfer, "中转")):
                        if best and th > 0:
                            gap = best["price"] - th
                            if gap > 0 and (anchor is None
                                            or gap < anchor[0]):
                                # 差额词单源：同回落锚
                                anchor = (gap, route, s, kind,
                                          gap_txt(best["price"], th, False))
                            elif gap <= 0 and (anchor_break is None
                                               or abs(gap) > anchor_break[0]):
                                # 首元素存 |gap|：选择比较是「|gap| 最大」，
                                # 存原始负 gap 曾让比较恒真退化为
                                # 「最后扫到的赢」（审查 P1-1）
                                anchor_break = (
                                    abs(gap), route, s, kind,
                                    gap_txt(best["price"], th, False))
            sel = anchor or anchor_break
            if sel:
                gap, r0, s0, k0, gw0 = sel
                rest = _summary_excl(r0, s0["date"])
                title = _rest_seg(
                    f"❌ 全部未达标｜最近 {self._route_short(r0)} "
                    f"{self._date_short(s0['date'])} "
                    f"{k0}{gw0}", rest)
            else:
                title = f"❌ 全部未达标｜{' · '.join(_summary_excl())}"

        # 标题 60 半角是钉钉/ServerChan 硬截断上限（notifier [:60] 静默
        # 丢尾，push_history 62 字符实发截断实证）——超限时「另监控」
        # 段整段降级：锚点信息保全优先于多航线清单（三航线三日期
        # 形态下曾批量触发截断丢锚）
        if len(title) > 60 and "｜另监控 " in title:
            title = title.split("｜另监控 ")[0]
        # 锚点缺席分支（全清单直拼）超限逐条丢尾条（审校 P2-1）：
        # 钉钉 [:60] 字符静默截的切点曾落在条目中间（「…重→西 10/05」
        # 半条）；条目完整性优先于清单全量（全量可循控制台正文），
        # 状态前缀「❌ 全部未达标」为地板档恒落位
        while len(title) > 60 and " · " in title:
            title = title.rsplit(" · ", 1)[0]

        # 达标航线小节置顶（多航线时先看最该看的）；同航线多日期时
        # 达标日期同置前（组内稳定排序，日期序不破坏）——标题锚达标
        # 日期而未达标日期小节占首屏曾拉长决策动线
        hit_routes = {id(r) for r, _s, _k, _f, _th in hits}
        hit_secs = {id(s) for _r, s, _k, _f, _th in hits}
        ordered = [
            (r, sorted(secs, key=lambda s: 0 if id(s) in hit_secs else 1))
            for r, secs in sorted(rs_list,
                                  key=lambda rp: 0 if id(rp[0]) in hit_routes
                                  else 1)]

        # 计数语义：rs_list 每航线一条（sections 每日期一条），按「航线对」
        # 去重才是用户心里的「几条航线」；日期数多于航线数时如实标注
        # （乌→上双日期曾显示「2 条航线」，实为 1 条航线 2 个日期）
        n_r = len({(r.from_code, r.to_code) for r, _s in rs_list})
        n_d = sum(len(s) for _r, s in rs_list)
        date_bit = f" {n_d} 个日期" if n_d > n_r else ""
        # 标题用 ####（接近正文字号）：# 级在钉钉渲染成大标题，推送里
        # 喧宾夺主（用户实锤「字体太大」）；持续达标轮电话已提醒过、
        # 已去抖静默——正文头同步降档 🔔，文档位与触达强度一致
        if hits:
            desp = ("#### 🚨 已达标——可出手\n\n" if fresh
                    else _SUSTAIN_HEAD + "\n\n")
        elif fell:
            desp = "#### ↩️ 已回落出线（本轮无达标班次）\n\n"
        else:
            desp = f"#### ❌ {n_r} 条航线{date_bit}全部未达标\n\n"
        # 头部一行（手机引用行 ~20 全角字符宽，超宽钉钉会折行且断点
        # 不受控——实测「🟩 与其后文字被拆两行」）：短格式时刻（HH:MM）
        # + 半角空格分隔。日期不进图例（标题/小节已有）——带 M/D 时
        # 数学上放不下（push_history 实锤「图例从未渲染过 🎯」）；
        # 🎯 置基座，超宽从最次要段开始逐段丢；档序与点位判定梯度
        # 同向：🎯真达标→🟩破线→🟨擦边；超线是默认态不占语义点
        # （🟦 文本点已撤——满屏蓝=噪音，差额数字自表达）；
        # 钉钉 PC 不认单 \n，引用块独立成段
        # 钉钉 PC 不认单 \n，引用块独立成段（图例行见 _legend_line）
        desp += self._legend_line() + "\n\n"

        # 各航线小节：方向+日期小标题 + KPI 行 + 仪表 + 该航线走势图
        # （小节间不加 `---`：钉钉 markdown 子集无 hr，会直出三个横线
        # 字符——#### 小节标题自身就是分节结构）
        # 推送审校：小节先收集后按字节预算组装——钉钉 18000B
        # 硬限截断保头部，曾把尾部明细总表段（比价唯一载体）与
        # @手机号段结构性切掉；预算内原样、超限后非达标航线整节降为
        # 📍 mini 行（价格/差额/链接核心判据保留）。纯构建端降级，
        # 无任何重发/重试语义（终局裁决不动）
        sec_parts = []
        for route, sections in ordered:
            sec = ""
            dep_win = ""
            if (route.dep_time_min or "").strip() or (route.dep_time_max or "").strip():
                lo = (route.dep_time_min or "00:00")[:5]
                hi = (route.dep_time_max or "24:00")[:5]
                dep_win = (f"（{lo}后出发）" if not route.dep_time_max
                           else f"（{lo}–{hi}）")
            # 标题 ####（正文字号）+ 短日期（多日期航线带日期跨度——
            # 只标首日期会让第 2+ 日期行情看起来无主）；跨度按日历序
            # （sections 按达标置前重排后，首尾取值改排序日期，防
            # 「10/06-10/05」倒挂）；整行超 20 全角时段位下沉到标题
            # 下的独立引用行（窄屏标题折行断点不受控）
            ds_all = sorted(s["date"] for s in sections)
            d_span = self._date_short(ds_all[0])
            if len(ds_all) > 1:
                d_span += f"-{self._date_short(ds_all[-1])}"
            sec += self._section_title(route.from_name, route.to_name,
                                       d_span, dep_win)
            deltas = self._deltas(route, sections[0]["date"])
            bd, bt = sections[0]["best_direct"], sections[0]["best_transfer"]
            # 中转 KPI 用行情口径（不限直挂）：仅直挂配置过滤后常为空，
            # 行情信息不应跟着消失（否则 KPI 消失）
            bt = sections[0].get("best_transfer_mkt") or bt

            def _win_empty(s):
                """出发窗口过滤后该日期班次全空（窗口外整体剔除）的短注：
                KPI 全空时小节只剩走势图无解释。窗口未配置/有班次→空。
                ⏳（U+23F3）安全集定谳（与下方 _stale_note 同词面共用）：
                在案常规款——与 ⏱ U+23F1 同族、图例行数月零事故；强提醒
                通道（_alert_body/_plain）对 ⏳ 行整行滤除，TTS/短信零
                触达。派生文本新增词面逐字审纪律的补录备案。"""
                if not dep_win:
                    return ""
                if s.get("top_direct") or s.get("top_transfer"):
                    return ""
                lo = (route.dep_time_min or "00:00")[:5]
                hi = (route.dep_time_max or "24:00")[:5]
                txt = (f"窗口 {lo}–{hi} 内本轮暂无班次"
                       if route.dep_time_max
                       else f"{lo} 后窗口内本轮暂无班次")
                return f"> ⏳ {txt}\n\n"

            def _stale_note(s):
                """仅补位形态短注（与日报空小节补偿行能力对称）：该日期
                当轮无最优（best 双空）而 top 只剩近 6h 补位行时，小节
                只剩标题+图零解释——读者无从分辨「已起飞无班次/数据
                缺失/全补位」。有当轮最优→KPI 即解释不出注。"""
                if (s.get("best_direct") or s.get("best_transfer_mkt")
                        or s.get("best_transfer")):
                    return ""
                tops = list(s.get("top_direct") or []) \
                    + list(s.get("top_transfer") or [])
                if not tops or not all(f.get("_stale_h") for f in tops):
                    return ""
                return "> ⏳ 本轮无当轮明细，下为近6h补位价\n\n"

            sec += _stale_note(sections[0]) or _win_empty(sections[0])

            def _kpi_block(label, best, th, tag, non_direct=False):
                """钉钉排版三行制：价格 / 航班 / 决策（行间 \\n\\n 独立成段），
                每行渲染宽 ≤40 半角（20 全角）窄屏不折行；仪表条独立成段
                （emoji 行 ≤5 格铁律，随文本折行会破坏完整性）。
                🎯 判「这个价能不能合规买到」组 OR 口径（_tie_any_ok
                单源，同价同班任一渠道成员合规即真）——曾判展示班自身：
                行情班￥2500 未过直挂/衔接而组内成员￥2600 恰达线时判定
                错位，同消息总表绿行/🔥/KPI 三语言并存（P1-1 收口）；
                普通行（无 _tie_rows 快照）回落本体单判零漂移，判定错位
                时自然落 🟩+行情注，与图例「🟩=行情破线未必达标」精确对应。
                行宽守卫（_fit_line 统一降级）：行1 尾注超宽依次降级
                （（行情价）→ *行情 → 并入行3 引用块 → 丢弃；百分比与
                行情注互斥同链）；行2 依次丢较上轮涨跌、跨天括注
                （跨天=当日达/次日达辨识信息，降级优先级高于涨跌，
                _l2_fallbacks 单源）；
                行3 依次丢行情注、舱位，保经停/直挂判据；删单外仍超宽
                （病理长 transCity/直挂组合）逐字截地板恒达标。"""
                if best is None:
                    return ""
                d = self._delta_txt(deltas, tag)
                # 链接随最优航班实际渠道，同价多渠道优先去哪儿/携程
                # （曾固定去哪儿：最低价在携程时点过去看到的价与文案不符）
                kurl = self._build_view_url(
                    route, sections[0]["date"],
                    self._pref_platform(best,
                                        sections[0].get("all_flights")
                                        or [best]))
                gauge = ""
                l3_note = ""
                if th > 0:
                    diff = best["price"] - th
                    # 🎯=「这个价能不能合规买到」组 OR 口径（_tie_any_ok
                    # 单源，与总表行/日报绿行/🔥 同语言）——「展示班自身
                    # 达标口径」的旧论据已被 P-1 终局裁决覆盖（同价时点
                    # 哪家都一样，首成员不合规≠组不合规）
                    if best.get("transCity"):
                        qual_hit = _tie_any_ok(best, th, route, True)
                    else:
                        qual_hit = _tie_any_ok(best, th, route, False)
                    # 行情注仅「低￥N」需解释为何没弹窗时挂（
                    # 收紧为严格破线）：恰达线 diff==0 时 gap_txt 已出
                    # 完整词面「行情破线」，再叠「*行情/（行情价）」
                    # 同屏双行情标（「行情破线*行情」实测曾直出行1）
                    mkt_note = best["price"] < th and not qual_hit
                    # 差额词单源（收口）：恰达线非达标口径读
                    # 「行情破线」不读「达线」（与 🟩 图例同语言）。
                    # 刻意不挂 hits 行的「(税前)」注（对账）：
                    # 行1 宽度按 20 全角纪律已贴上限，飞猪税前披露由
                    # hits 行「低￥N(税前)」与行3 pad token 承载
                    gap = gap_txt(best["price"], th, qual_hit)
                    # 行1：最优价（可点）+ 线 + 差额——一行看全；语义点
                    # 与图例/mini KPI/日报同语言：🎯=达标口径破线、
                    # 🟩=行情破线未必达标、🟨=擦边（≤10%）；超线是
                    # 默认态不加点（点密=噪音，用户实锤「蓝色标识太多」，
                    # 差额数字自表达，撤 🟦 文本点）
                    # 语义点与图例/mini KPI/日报同语言：点位走 tier_dot
                    # 单源（判定语义=本消费点的达标口径 qual_hit）
                    dot = tier_dot(qual_hit, diff, th)
                    # 未知平台 _build_view_url 返回空：剥链接壳出纯文本
                    # （不给 [..]() 空壳坏链）。加粗=「该出手」扫读梯度
                    # （三处统一仅 🎯 粗——曾有点即粗/仅🎯粗两种
                    # 并存，🟩/🟨 粗稀释主次；mini_kpi 单档粗为准）
                    _core = f"{dot}{label} ￥{best['price']:.0f}"
                    _em = f"**{_core}**" if qual_hit else _core
                    base1 = ((f"[{_em}]({kurl})" if kurl else _em)
                             + f"　线￥{th:.0f}　{gap}")
                    # 尾注二选一（百分比+行情注并排 >20 全角必折行），
                    # 超宽降级链见 docstring
                    if mkt_note:
                        forms = [base1 + _MKT_NOTE_PAREN,
                                 base1 + _MKT_NOTE, base1]
                        # 行3 注与括注同出转写表投影（词面改版日自动
                        # 跟随；裸字面量曾与转写表值耦合，ntfy/短信/TTS
                        # 侧剥注表按同词面剥注，分叉即叠词残留）
                        l3_note = TIER_TRANSCRIBE["mkt"].strip()
                    else:
                        # 尾注幅度词面单源 _kpi_pct_suffix（擦边带挂
                        # 「擦边N%」四语言同源，banker 旁路词面曾与
                        # 图内互斥）；三档降级链单源 _pct_fallback_forms
                        pct = _kpi_pct_suffix(best["price"], th)
                        forms = _pct_fallback_forms(base1, pct)
                    l1 = _fit_line(forms[0], fallbacks=forms[1:])
                    # 仪表条=档位第三信号（撤达标行；撤
                    # 超线行）：真达标行已有 🎯+「低￥N」+hits 🔥 三重同义，
                    # 超线行 🟦 成串是「有图无例」噪音（行1 百分比已表达
                    # 幅度）——只给行情破线行留 🟩 满格强化，版面更短、
                    # 主次更分明
                    _g = "" if qual_hit else self._gauge(
                        best['price'], th, ok=qual_hit)
                    gauge = f"{_g}\n\n" if _g else ""
                else:
                    # 未设线不是档位：不加点不加粗（加粗=档位信号，
                    # 非档位内容加粗稀释扫读梯度，收口）
                    _core = f"{label} ￥{best['price']:.0f}"
                    l1 = ((f"[{_core}]({kurl})" if kurl
                           else _core) + "（未设线）")
                # 行2：航班身份——最低价是哪班几点走；超宽降级链单源
                # _l2_fallbacks（跨天括注档先于涨跌档：+1 天是「当日达
                # 还是次日达」的决策辨识信息，涨跌是次要信号）
                l2_base = (f"{best.get('name', '')} "
                           f"{best.get('depTime', '')}"
                           f"→{best.get('arrTime', '')}")
                # 跨天括注态（与 hits 行 base_seg「(+)」同贴法——
                # 同屏 bare/括注双形态曾并存，统一读感）
                _cx = best.get("crossDayDesc") or ""
                if _cx:
                    _cx = f"({_cx})"
                l2 = _fit_line(
                    l2_base + _cx + d,
                    fallbacks=_l2_fallbacks(l2_base, _cx, d))
                # 行3 决策行（有内容才渲染）：经哪/停多久/行李/舱位——
                # 直挂配置下这些是达标判据，必须可自查
                toks = []
                tc = self._trans_city(best)
                if tc:
                    lay = str(best.get("layoverT") or "").strip()
                    # 经/停分 token（审校 P3-2）：合一段被地板逐字
                    # 截曾产「停2:」半截时刻（噪音）——拆开后地板
                    # 装载按 token 整删，时刻要么完整要么缺席；
                    # 经停城市（主要辨识信息）优先保
                    toks.append(f"经{tc}")
                    if lay:
                        toks.append(f"停{lay}")
                elif str(best.get("stopCity") or "").strip():
                    # 占位/无中转城市但带经停城市：经停词面 + 经停停留
                    # 配对（审查 P2-2 占位洞——原真值门在此仍取 layoverT）
                    sc = str(best.get("stopCity")).strip()
                    st = str(best.get("stopTimeT") or "").strip()
                    toks.append(f"经停{sc}" + (f" 停{st}" if st else ""))
                else:
                    lay = str(best.get("layoverT") or "").strip()
                    if lay:
                        toks.append(f"停{lay}")
                if tc or str(best.get("stopCity") or "").strip():
                    # 直挂词面三态（P2-4）：直挂筛选航线
                    # 「行李直挂/直挂未标注」（判据缺失警示合理）；未配置
                    # 筛选时渠道未标注→中性省略（「直挂未标注」是假警示，
                    # 「行李直挂」则把未标注谎报成真值——两侧都不许）
                    _bag_direct = str(best.get("transferBaggage") or "") == "direct"
                    if str(getattr(route, "transfer_baggage", "") or "") == "direct":
                        toks.append("直挂未标注" if non_direct else "行李直挂")
                    elif _bag_direct:
                        toks.append("行李直挂")
                # 飞猪展示价为税前（仅 pad>0 启用时两口径有差，需解释）；
                # 超宽降级在行情注之后、舱位之前丢
                pad_tok = ("税前价" if FLIGGY_TAX_PAD > 0
                           and best.get("_platform") == "fliggy" else "")
                if pad_tok:
                    toks.append(pad_tok)
                cn = _cabin_cn(cabin_clean(best))
                if cn:
                    toks.append(cn)
                # 行1 尾注被降光 → 行情注并入行3 引用块兜底（仍超宽时
                # 依次丢行情注/税前注/舱位 token，优先保经停/直挂判据）
                if l3_note and l1 == base1:
                    toks.insert(0, l3_note)
                for extra in ([l3_note] if l3_note else []) \
                        + ([pad_tok] if pad_tok else []) \
                        + ([cn] if cn else []):
                    if _disp_dw("> " + "　".join(toks)) <= 40:
                        break
                    if extra and extra in toks:
                        toks.remove(extra)
                # 行间 \n\n：PC 端不认单 \n（会粘成一行长文），每行独立成段；
                # 行3 决策字段走引用块（灰底辅档）——主（价格）次（航班）
                # 辅（经停/直挂/舱位）三层视觉分级
                out = f"{l1}\n\n{l2}"
                if toks:
                    l3 = "> " + "　".join(toks)
                    if _disp_dw(l3) > 40:
                        # 病理长 transCity（渠道外部字段）等丢注循环
                        # extras 删单外的超宽形态（直挂词删不动）：
                        # 地板档恒达标。装载按 token 边界贪心（
                        # _trunc_tokens 单源，与 _mini_split 拆行档
                        # 同律）：截点落 token 中部回退 token 起点
                        # （半截「停2:」是噪音）；截点落首 token 自身
                        # （病理长城市名）保持逐字截保前缀（地板档
                        # 恒落位律：行3 内容不得净失）
                        l3 = ("> " + _trunc_tokens(
                            "　".join(toks), 40 - _disp_dw("> "),
                            sep="　"))
                    out += "\n\n" + l3
                return out + (f"\n\n{gauge}" if gauge else "\n\n")

            sec += _kpi_block("直飞", bd, route.alert_direct, "direct")
            sec += _kpi_block(
                "中转", bt, route.alert_transfer, "transfer",
                non_direct=(bt.get("transferBaggage") != "direct")
                if bt else False)

            def _mini_kpi(s):
                """第 2+ 日期精简 KPI 行（多日期航线第 2+ 日期不得零文案覆盖——
                否则只剩一张无标注走势图）：
                「📍 10/06　🎯 直飞 ￥2630 真达标 ｜ 中转 ￥2650 差￥950」。
                语义点口径与首日期 KPI 一致（点后补空格——mini
                KPI 曾无空格、主 KPI/legacy 带空格，同体系两种贴法）：
                🎯=达标口径破线、🟩=行情破线
                （带 *行情 短注）、🟨=擦边（距线≤10%）；超线默认态
                不加点（差额数字自表达）。价格带同款跳转链接。单行超
                40 半角先丢 *行情 注（丢注不丢数）、再拆成每类一行。"""
                d_short = self._date_short(s["date"])
                segs = []
                for label, best, th, _tr in (
                        ("直飞", s.get("best_direct"), route.alert_direct,
                         False),
                        ("中转", s.get("best_transfer_mkt")
                         or s.get("best_transfer"),
                         route.alert_transfer, True)):
                    if best is None:
                        continue
                    url = self._build_view_url(
                        route, s["date"],
                        self._pref_platform(best,
                                            s.get("all_flights") or [best]))
                    if th > 0:
                        diff = best["price"] - th
                        # 🎯=组 OR 口径（_tie_any_ok 单源，与首日期
                        # _kpi_block 同判定；曾判达标班另一班，行情班
                        # 破线挂 🎯 误导出手）；点位走 tier_dot 单源
                        qual_hit = _tie_any_ok(best, th, route, bool(_tr))
                        dot = tier_dot(qual_hit, diff, th)
                        # 加粗只在 🎯 最高档（「粗=该出手」扫读梯度）：
                        # 🟩/🟨 维持 emoji 单信号、超线裸文本（
                        # 加粗档位多=主次稀释，删旧律陈词）
                        _pv = f"￥{best['price']:.0f}"
                        if qual_hit:
                            px = (f"[**{_pv}**]({url})" if url
                                  else f"**{_pv}**")
                        else:
                            px = f"[{_pv}]({url})" if url else _pv
                        gap = gap_txt(best["price"], th, qual_hit)
                        # 语义点前置（与 KPI 行1/日报同式，档位扫读同位）；
                        # 「直飞 ￥N」空格与主 KPI 同形态（对齐，
                        # 同消息内 KPI 曾两种贴法）
                        seg = f"{dot}{label} {px} {gap}"
                        # 🟩=行情破线未必达标：补「*行情」短注解释
                        # 「价低却没弹窗」（与主 KPI mkt_note 同语义；
                        # 收紧为严格破线——恰达线 gap_txt 已出
                        # 「行情破线」完整词面，再叠注=同屏双行情标）
                        if diff < 0 and not qual_hit:
                            seg += _MKT_NOTE
                    else:
                        _pv = f"￥{best['price']:.0f}"
                        px = f"[{_pv}]({url})" if url else _pv
                        # label 与价格间空格同 th 分支（未设线裸贴
                        # 「中转[￥N]」曾与主 KPI 两种贴法并存）
                        seg = f"{label} {px}"
                    segs.append(seg)
                if not segs:
                    return ""
                head = f"📍 {d_short}　"
                # 行构造走 _mini_split 单源：窄联接→去短注→拆行（拆行
                # 档两物理行各自过守卫），不再在闭包内联拼 split 串
                return _mini_split(head, segs)

            # 第 2+ 日期精简 KPI：插在首日期完整块之后、走势图之前
            # （窗口过滤后全空的日期 KPI 为空 → 补窗口/仅补位短注，不静默）
            for _s in sections[1:]:
                sec += _mini_kpi(_s) or _stale_note(_s) or _win_empty(_s)
            tl = self._trend_line(route, sections[0]["date"])
            # 建议跨日期选「距线比例最近」的日期发言（曾静默只看首日期
            # ——次日更近线时建议失真）；选中非首日期时措辞带日期限定，
            # 整行超宽丢日期前缀（行宽铁律：丢注不丢数）
            _gaps = [(self._sect_gap_ratio(route, s), s) for s in sections]
            _gaps = [(g, s) for g, s in _gaps if g is not None]
            sg = ""
            if _gaps:
                _gr, sg_s = min(_gaps, key=lambda x: x[0])
                sg = self._suggest_line(route, sg_s)
            # 建议独占短引用块（与趋势合块曾超手机行宽，钉钉折行后
            # `> ` 缩进丢失）；趋势行常驻：近 7 天窗（168h）超出走势
            # 图 48h 承载，图内无同源信息——曾以「与图完全重复」撤
            # 常驻系依据失实，正常有图轮的 7 天趋势随之彻底消失
            # （图内容量≥被撤文本版）；判向取直飞（主档）段：直飞↑
            # 中转↓混合时按全文含箭头判向曾整条误标 📉
            if sg:
                sg_line = f"> 💡 {sg}"
                if len(sections) > 1 and sg_s is not sections[0]:
                    sg_line = (f"> 💡 {self._date_short(sg_s['date'])} {sg}")
                sec += _fit_line(sg_line, fallbacks=[f"> 💡 {sg}"]) + "\n\n"
            if tl is None:
                # 查询异常（磁盘满窗实锤）：补缺失标注防「静默消失」
                # （无数据空串仍静默省略——异常才提示，常态零噪音）
                sec += "> ⚠️ 近7天趋势暂缺\n\n"
            else:
                # 组装单源 _trend_block（日报 build_and_push 同消费，
                # 能力对称三十§3）；空串返回时 += '' 无害
                sec += _trend_block(tl)
            # 走势图逐日期标注：多日期航线图注+alt 带日期（相邻两张
            # 不再难分辨）；单日期维持无标注。with_charts=False（预览）
            # 整段跳过——无 round_charts 时缺图分支恒走「缺失」，
            # 预览器里是假警告
            _multi_d = len(sections) > 1
            for s in sections if with_charts else ():
                cu = (self.round_charts or {}).get(
                    (route.from_code, route.to_code, s["date"]))
                if not cu:
                    # 缺图显式标注（曾静默 continue：该日期只剩 KPI
                    # 没图，读者不知是没生成还是没传上）；词面中性
                    # 「缺失」——生成失败与上传失败在本层不可分辨
                    # （具体归因看监控日志，词面猜测曾误导 ops 对账）；
                    # 趋势行已常驻本小节前部，此处不再补位防双份
                    sec += (f"> ⚠️ {self._date_short(s['date'])} "
                             f"走势图缺失\n\n")
                    continue
                if _multi_d:
                    sec += (f"> 🗓 {self._date_short(s['date'])} 走势\n\n"
                             f"![走势 {self._date_short(s['date'])}]({cu})\n\n")
                else:
                    sec += f"![走势]({cu})\n\n"
            # 节收集：达标航线恒全量；mini 行按各日期预生成（降级时
            # 价格/差额/链接核心判据由总表图与 mini 行双承载）
            hit_flag = any(r is route for r, *_x in hits)
            minis = "".join(_mini_kpi(s) or "" for s in sections)
            sec_parts.append((sec, hit_flag, minis))

        # hits 行先收集（full/head 双形态,字节预算组装的优先项）,
        # 在降级说明行后按决策落位
        hit_rows = []
        for route, s, kind, f, th in hits:
            cross = f.get("crossDayDesc") or ""
            # seg 降级链：超宽依次丢停留时长 → 丢经停/中转城市 → 保时刻跨天。
            # （推送审校 P2-1）：`> ` 前缀（2 半格）入量纲——
            # _fit_line 守 40 必须连同拼行前缀一起计，否则实渲染 41-42，
            # 与 KPI 行3/图例/建议行（前缀计入）同消息两套预算
            base_seg = (f"{f['depTime']}→{f['arrTime']}"
                        + (f"({cross})" if cross else ""))
            via = self._via_txt(f)
            lay = str((f.get("layoverT") if self._trans_city(f)
                       else f.get("stopTimeT")) or "").strip()
            seg = _fit_line(
                "> " + base_seg + (f" {via}" if via else "")
                + (f" 停{lay}" if lay else ""),
                fallbacks=["> " + base_seg + (f" {via}" if via else ""),
                           "> " + base_seg])
            # 行3：航线日期一组，渠道/差额/渠道直达链接 · 分隔（用户被
            # 叫来最想点的就是这条）；链接渠道同价优先去哪儿/携程；
            # 超宽降级：先丢渠道名裸文本（保「打开XX」链接）→ 丢链接
            # → 航线+差额兜底
            plat_key = self._pref_platform(f, s.get("all_flights") or [f])
            plat_cn = self.PLATFORM_CN.get(plat_key, plat_key)
            rd = f"{self._route_short(route)} {self._date_short(s['date'])}"
            # 展示价差额文案共用 _low_txt（税前注 pad>0 条件单源，两版
            # 曾分叉）；pad=0（重标定）标注自动消失
            low = _low_txt(f["price"], th, f.get("_platform"))
            # 未知平台 _build_view_url 返回空：跳过链接只出纯文本
            _jump_url = self._build_view_url(route, s["date"], plat_key)
            if _jump_url:
                jump = f"[打开{plat_cn}]({_jump_url})"
                tail = _fit_line(
                    f"> {rd} · {plat_cn} · {low} · {jump}",
                    fallbacks=[f"> {rd} · {low} · {jump}",
                               f"> {rd} · {plat_cn} · {low}",
                               f"> {rd} · {low}"])
            else:
                tail = _fit_line(f"> {rd} · {plat_cn} · {low}",
                                 fallbacks=[f"> {rd} · {low}"])
            # 每行独立引用短块（\n\n 分隔）：PC 端单 \n 会把引用行粘成
            # 一整段、`> ` 缩进丢失（钉钉渲染铁律）
            # 首行套行宽守卫（超长航司名可破 40 半角，补）；
            # 达标命中=🎯 档：档位词加粗与 legacy 单航线版统一（两版
            # 曾一粗一不粗，加粗=档位信号在 hits 首行断档）。
            # 双名剥档（审校 P3-1）：「新海航｜金鹏航空 Y87519」超宽
            # 曾整名直落去名档（head 自身无航班号=身份净失）——先试
            # 剥「A｜」营销名段（_l2_fallbacks 双名剥档同律），去名档
            # 仍为末档地板（全超取末档恒落位）
            _head_base = f"> 🔥 **{kind} ￥{f['price']:.0f}**"
            _nm = str(f.get("name") or "")
            _bar = _nm.find("｜")
            _head_fbs = [_head_base]
            if _bar >= 0:
                _head_fbs.insert(0, f"{_head_base} {_nm[_bar + 1:]}")
            head = _fit_line(f"{_head_base} {_nm}", fallbacks=_head_fbs)
            hit_rows.append((
                f"{head}\n\n{seg}\n\n{tail}\n\n", head + "\n\n"))
        # 预算组装（推送审校）：hits 行与 sec 节共用预算——
        # 地板档（hit head 价格判据行 + sec mini 关键价行）总额预留制
        # （预算先扣全部地板档，全量档在剩余共享池竞争——LESSONS
        # 「地板档恒落位」的正确实现是设计预算使其恒可落）。尾部
        # 明细总表是比价唯一载体、@段是触达载体，字节无上限的节
        # 会把切点以上的尾段顶飞：hit head 无条件落位（判据地板档）；
        # sec mini 上限扣 heads_total——hit 全量档在共享池先竞争，
        # 已升级 full 的 head 在 used 里按全额计入、mini 判定上限又
        # 扣一次 heads_total（双重预留），故 mini 整体让位的触发域
        # 远早于单纯容量估计：单航线日期数×命中规模合计 ~30 即可
        # 触发（30 hit/30 date、heads_total≈2.1KB 实测让位）。让位后
        # 三层兜底：hit 判据行（head 地板档）+降级说明行+明细总表图，
        # 读者不致信息真空（现实钉 1 航线×2 日期内不触发）。尾段
        # 预留 1800B 含总表图行/跳转链接/@提醒段
        used = len(desp.encode("utf-8"))
        budget_total = max(4000, 15000 - used - 1800)
        demoted = False
        hit_demoted = False
        minis_total = sum(len(minis.encode("utf-8"))
                          for _t, _h, minis in sec_parts if minis)
        heads_total = sum(len(h.encode("utf-8")) for _f, h in hit_rows)
        budget_shared = budget_total - minis_total - heads_total
        # 决策一：hits 行——命中详情最高优先，预算内全量，超出转
        # head 地板档（判据保住，丢的是时刻/链接，由总表图承接）
        hit_out = []
        for full, head in hit_rows:
            fb = len(full.encode("utf-8"))
            if used + fb <= budget_shared:
                hit_out.append(full)
                used += fb
            else:
                hit_out.append(head)
                used += len(head.encode("utf-8"))
                hit_demoted = True
        # 决策二：sec 节——同一共享池竞争，超限转 mini（mini 落位
        # 上限扣 heads_total：判据行预留不可被 mini 倒挂顶穿）
        sec_out = []
        for sec_txt, _hf, minis in sec_parts:
            b = len(sec_txt.encode("utf-8"))
            if used + b <= budget_shared:
                sec_out.append(sec_txt)
                used += b
            elif minis:
                mb = len(minis.encode("utf-8"))
                if used + mb <= budget_total - heads_total:
                    sec_out.append(minis)
                    used += mb
                demoted = True
            else:
                demoted = True
        desp += "".join(sec_out)
        if demoted or hit_demoted:
            desp += _demote_note(demoted, hit_demoted) + "\n\n"
        desp += "".join(hit_out)
        # 明细总表（所有航线合并一张图）——预览模式跳过图床上传；
        # 生成/上传失败时补独立引用短块兜底（总表是比价唯一载体，
        # 静默缺失曾让读者以为本轮无明细）
        # 运维对账注（自文本段撤入总表 PNG 小注——「跳转文案
        # 才用文本」定律：无数据渠道/直挂标注缺失/孤低价拦截/全渠道
        # 无数据均无跳转需求，文本直出曾占推送首屏；仅图挂兜底回退文本）
        ops_notes = self._ops_notes(rs_list, no_data)
        if with_tables:
            table_md = self._flights_table_md_multi(
                rs_list, ops_notes=ops_notes)
            if table_md:
                desp += table_md
            else:
                # 图挂兜底（与 legacy 单航线同律：信息不能跟图一起消失，
                # 补齐 multi 生产主路径的不对称）：各航线 TOP 明细
                # + 各渠道最低行情退回文本；_fmt_flight_line 无链接，符合
                # 「跳转文案才用文本」定律（此处是图挂兜底区，与 legacy 同）；
                # 运维对账注一并回退（入图主路径的文本副本）。
                # 总额预留制（审校 P1-1/P1-2）：兜底块曾无预算直拼，
                # 大数据形态 28K 顶到发送端截断、被切的恰是兜底明细自身
                # 且垫底的 @段一并蒸发——兜底头/说明行/@段先全额预留，
                # ops 注与航线明细块在剩余预算竞争，挤出转让位说明行
                _at_seg = (f"\n\n@{self.at_mobile} "
                           if (hits and self.at_mobile) else "")
                _fb_head = "> ⚠️ 明细总表缺失，完整明细见控制台\n\n"
                _fb_note = "⚠️ 部分航线明细因超长让位，见控制台\n\n"
                fb_budget = (15000 - len((desp + _fb_head).encode("utf-8"))
                             - len(_at_seg.encode("utf-8"))
                             - len(_fb_note.encode("utf-8")))
                fb_used = 0
                fb_out = []
                fb_demoted = False
                for _n in ops_notes:
                    # 回退行同受 40 半角铁律（推送审校）：注内
                    # 「孤低价拦截×N：飞猪￥9900、去哪儿￥9500」形态可
                    # 超宽——超宽截尾（无 fallback 语义=超宽原样，故补
                    # 空尾档截到不超宽），对账全量可循控制台。
                    # 尾注「（截）」（推送审校 P1）：U+2026「…」
                    # 钉钉渲染成。。（:2256 自定律），ntfy/短信侧
                    # 已去 …，文本回退路径同律收口
                    # （推送审校 P1-1）：「> ⚠️ 」前缀（5 半格）
                    # 入 _fit_line 量纲——重放实测 41 半角超宽行（
                    # hits 三行同病漏网），前缀拼进候选串真修
                    _pre = "> ⚠️ "
                    # 推送审校 P2-2：渠道清单逐字截（推导收口
                    # _ops_fallbacks 单源，测试真执行级）
                    _ln = _fit_line(_pre + _n,
                                    fallbacks=_ops_fallbacks(_n, _pre)) + "\n\n"
                    _lb = len(_ln.encode("utf-8"))
                    if fb_used + _lb <= fb_budget:
                        fb_out.append(_ln)
                        fb_used += _lb
                    else:
                        fb_demoted = True
                for rt, secs in rs_list:
                    for blk in (self._top3_blocks(rt, secs),
                                self._channel_market_lines(secs)):
                        if not blk:
                            continue
                        bb = len(blk.encode("utf-8"))
                        if fb_used + bb <= fb_budget:
                            fb_out.append(blk)
                            fb_used += bb
                        else:
                            fb_demoted = True
                desp += _fb_head + "".join(fb_out)
                if fb_demoted:
                    desp += _fb_note

        # 同班比价不再出文本段：纯数据无跳转需求，总表 PNG
        # 已含同数据三列比价表且渠道链完整不截断（文本版超 3 家只展两端
        # 曾被用户视为「推送数据缺失」）；文本只保留需跳转的文案。
        # 无数据渠道/直挂标注/孤低价/全渠道无数据四类对账注同定律撤入
        # 总表 PNG 小注（ops_notes 见上）——文本直出曾占首屏，
        # 运维对账无跳转需求不属「跳转文案」豁免区

        # 全消息无任何可点链接时兜底一个查价入口（判定收编
        # _ensure_jump_link 单源：multi 曾内联一份、单航线版整段缺失）
        if ordered:
            desp = self._ensure_jump_link(desp, ordered[0][0],
                                          ordered[0][1][0])

        at_mobiles = None
        if hits and self.at_mobile:
            at_mobiles = [self.at_mobile]
            # @段前空段归一：上游尾部形态不一（表格/兜底块/跳转链接
            # 各自带 0-2 个尾 \n），直接拼 \n\n 会出双空段（钉钉折叠成
            # 大空白）、裸拼单 \n 又让 PC 端 @ 段与上一行粘连——rstrip
            # 后补段落级分隔，恒恰一个空段
            desp = desp.rstrip("\n") + f"\n\n@{self.at_mobile} "
        return {"title": sanitize_desp(title), "desp": sanitize_desp(desp),
                "hits": hits, "at_mobiles": at_mobiles}

    def _ensure_jump_link(self, desp: str, route, section: dict) -> str:
        """全消息无任何可点链接时兜底一个查价入口（单源委托模块级
        _ensure_jump_link——r257-P3-2 日报侧同源消费，platforms 走
        参数，能力对称让单源免费）。"""
        return _ensure_jump_link(desp, route, section, self.platforms)

    def _push_digest_multi(self, rs_list: list, no_data: list = None):
        """一轮一消息：每航线一个小节（方向+日期标题，一眼可辨），
        明细合并一张总表；任一航线达标则整条消息变警报。
        no_data：配置了但本轮全渠道零条的航线（desp 补对账行）。"""
        hits = self._collect_hits(rs_list)
        # 免打扰时段：行情心跳整轮省略（达标警报链路不受限）
        if not hits and self._in_quiet():
            self.logger.info("[静默] %s–%s 免打扰时段，本轮行情推送省略"
                             "（达标警报不受限）", self.quiet_start,
                             self.quiet_end)
            return False
        # 未达标心跳退避：纯心跳轮才入闸——hits（达标）与
        # _prev_hit（回落出线）轮结构性必达，详见 _heartbeat_gate
        if not hits and not self._prev_hit and not self._heartbeat_gate():
            return False
        fresh_hits = [h for h in hits if self._phone_should_ring(h)]
        p = self._digest_payload(rs_list, fresh=bool(fresh_hits),
                                 with_tables=True,
                                 fell=bool(self._prev_hit and not hits),
                                 no_data=no_data)
        title, desp, at_mobiles = p["title"], p["desp"], p["at_mobiles"]
        # 电话/强提醒不依赖钉钉成功——钉钉网关抖动时电话必须照响；
        # 但持续达标时去抖：同航线同类别 2h 内或降幅不足 ￥50 不重拨。
        # 详情页存档先行：nid 链接进钉钉文案 + Windows 弹窗 launch 共用
        # （仅达标轮有详情页；非达标轮置空串=邮件「打开控制台」按钮
        # 不渲染，与 desp 侧「📲 完整详情」仅 fresh_hits 追加同口径）
        launch = ""
        if fresh_hits:
            launch = self._archive_notify(title, desp)
            # 回环 base_url（127.0.0.1）只供本机弹窗 launch：desp 追加
            # 该链接手机点必死链
            if launch and self._launch_public():
                desp += f"\n\n[📲 完整详情（点击直达）]({launch})\n\n"
            # 通道失败浮出水面（电话哑弹两天无人察觉的教训）：
            # 失败警告进钉钉主推，读者知道该去查电话/弹窗通道
            if not self._send_urgent(title, desp, fresh_hits, launch=launch):
                desp += "\n\n" + URGENT_FAIL_NOTE + "\n\n"
        # 单次发送（send 内部零重试）——不外层加码：
        # 钉钉 -1 存在"幽灵送达"（报错但消息已入群），外层重试会造成
        # 重复消息打扰；偶发丢失由下轮心跳自然补，达标场景电话独立兜底
        sent = self.notifier.send(
            title, desp, at_mobiles=at_mobiles,
            # 邮件按钮是 launch 的消费者之一（钉钉/ServerChan 收下即忽略）：
            # 回环 base_url 时按钮 href 点开必死链，与 desp 文本链/ntfy 同律过滤
            launch=(launch if self._launch_public() else ""))
        if sent:
            self.logger.info("[聚合] 已推送: %s", title)
        else:
            self.logger.warning("[聚合] 本轮推送未确认（-1 幽灵送达可能已入群）")
        # 记录本轮达标态供下轮「↩️ 回落出线」判定（免打扰静默轮不更新，
        # 语义锚在「上一次实际推送给用户看的消息」上）
        if not (not hits and self._in_quiet()):
            self._prev_hit = bool(hits)
        # 风暴与电话同去抖：仅"新达标"（首跌破或再降≥50）才 3 连推，
        # 持续达标的轮次只发主推（每 30 分钟一条 🚨 不轰炸）；
        # 免打扰时段风暴跳过（不补发；主推已送达，不深夜轰炸）
        if sent and hits and fresh_hits and self.storm_repeat > 1:
            if self._in_quiet():
                self.logger.info("[静默] %s–%s 免打扰时段，风暴连推跳过",
                                 self.quiet_start, self.quiet_end)
            else:
                self._storm(title, desp, at_mobiles, launch=launch)
        return bool(hits)

    def _flights_table_md_multi(self, rs_list: list,
                                ops_notes: list = None) -> str:
        """所有航线的明细合并成一张总表图（分组标题带航线缩写+日期）。
        ops_notes：运维对账注列表，直挂图内小注（自文本段撤入
        ——「跳转文案才用文本」定律）。"""
        try:
            from report import render_flights_table, upload_chart
            rows = []
            summary_bits = []
            names = []
            for route, sections in rs_list:
                short = self._route_short(route)
                od = f"{route.from_code}{route.to_code}"
                if od not in names:   # 同航线多日期独立 entry：OD 去重保序（曾拼 URCSHAURCSHA 型重复文件名）
                    names.append(od)
                for s in sections:
                    dshort = self._date_short(s["date"])
                    for kind, key, th, icon in (
                            ("direct", "top_direct", route.alert_direct, "✈️ 直飞"),
                            ("transfer", "top_transfer", route.alert_transfer, "🔁 中转")):
                        fs = []
                        for f in s.get(key) or []:
                            g = dict(f)
                            # tie 组达标 OR（_tie_any_ok 单源）：同价
                            # 合并行按首成员单判曾漏标达标；
                            # 补位行不参达标色（_row_qual 单源——
                            # 补位低价照打真达标绿=「可出手」指向
                            # 过期价，达标判定只认当轮）
                            g["_qual"] = _row_qual(g, th, route,
                                                   kind == "transfer")
                            g["_th"] = th   # 表格图价格三档（擦边琥珀档）判定用
                            fs.append(g)
                        lbl = f"{icon}最优 · {short} {dshort}"
                        # 中转组头必须带到达时限（判据不得仅限 label_override
                        # 为空时渲染——那样 multi 总表不可见）；超宽省略小字
                        if kind == "transfer" and route.transfer_arrival_max:
                            _tag = f" · 次日{route.transfer_arrival_max}前到"
                            if _dw(lbl + _tag) <= 60:
                                lbl += _tag
                        # plat_mins：组尾「各渠道最低」子节（自钉钉
                        # 文本段撤入图——无链接行情一律入图的定律）。
                        # 只挂中转组尾（曾直飞/中转两组各挂一份同值子节，
                        # 版面重复渲染 ×4）；词条「含直飞」消歧——列的是
                        # 全类合并口径，非中转渠道最低（与日报路径同构）
                        meta4 = {"layover_min": route.transfer_layover_min,
                                 "arrival_max": route.transfer_arrival_max}
                        if kind == "transfer":
                            meta4["plat_mins"] = self._plat_mins_for(s)
                        rows.append((kind, fs, lbl, meta4))
                    bd = s.get("best_direct")
                    if bd:
                        # 图内 summary 带档位词（与日报 summary
                        # 同语言 kpi_tier_txt 单源）：图脱离消息上下文
                        # 时无线无档的「直飞￥1580」无法判档
                        _qd = _qual_price(bd) <= route.alert_direct
                        summary_bits.append(
                            f"{short} {dshort} "
                            + kpi_tier_txt("直飞", bd['price'],
                                           route.alert_direct, _qd))
                    bt = s.get("best_transfer_mkt") or s.get("best_transfer")
                    if bt:
                        # 摘要补中转最低（单航线版已有，多航线版曾漏——
                        # 图脱离消息上下文时中转行情不可见）；口径与 KPI 行
                        # 一致（_tie_any_ok 组 OR 单源）
                        _qt = _tie_any_ok(bt, route.alert_transfer, route,
                                          True)
                        summary_bits.append(
                            f"{short} {dshort} "
                            + kpi_tier_txt("中转", bt['price'],
                                           route.alert_transfer, _qt))
                # 同班比价候选（跨全部日期，每航线一组）：候选组带日期，
                # 多日期航线 label 标日期区分（曾只取首日期，且候选块
                # 在逐日期循环里被整份重复插入）
                # top_n=4：文本比价段已撤（无跳转需求的内容只出图），
                # 图是比价唯一载体，候选容量对齐原文本版
                cands = self._fp_cands(sections, top_n=4)
                if cands:
                    # 单源组装（multi 曾保留第三份内联组装，
                    # chain/outlier 加字段必漏本端）；label 日期段由
                    # date_labels 开关在单源内补
                    comp = self._compare_rows(
                        cands, date_labels=len(sections) > 1)
                    # 组头带航线归属（多航线总表里比价组曾无主）+ 日期段
                    # （候选可来自任一日期，取法同小节标题 d_span）
                    c_span = self._date_short(sections[0]["date"])
                    if len(sections) > 1:
                        c_span += f"-{self._date_short(sections[-1]['date'])}"
                    rows.append(("compare", comp,
                                 f"同班比价 · {short} {c_span}"))
            # 同 OD 多日期去重（rs_list 每航线一条、sections 每日期一条，
            # 曾拼「乌鲁木齐→上海 ｜ 乌鲁木齐→上海」重复标题）
            ods = []
            for r, _ in rs_list:
                od = f"{r.from_name}→{r.to_name}"
                if od not in ods:
                    ods.append(od)
            title = " ｜ ".join(ods[:2]) + (f" 等{len(ods)}航线" if len(ods) > 2 else "")
            out_png = (f"{render_dir()}/flights_table_{_png_user_tag(self.user)}"
                       f"{''.join(names[:2])}.png")
            render_flights_table(
                rows, title, out_png, summary=summary_bits,
                stamp_note="当轮+近6h补位",
                ops_notes=ops_notes or [])
            url = upload_chart(out_png, None, self.logger,
                               ih=self.image_host)
            if url:
                return (f"#### 📋 明细总表 {_TBL_HEAD_TIER}\n\n"
                        f"![明细总表]({url})\n\n")
            self.logger.warning("[总表] 上传失败")
        except Exception as e:
            self.logger.warning("[总表] 生成失败: %s", e)
        return ""

    # ---------- 行情报告（digest） ----------
    @classmethod
    def _fmt_flight_line(cls, f: dict, idx: int = None, mark: str = "") -> str:
        cross = f.get("crossDayDesc", "")
        arrive = f"{f['arrTime']}（{cross}达）" if cross else f"{f['arrTime']} 当日达"
        # 中转行补停留时长（「经哪+停多久」缺一不可）；经停行（同机号）
        # 补经停城市。配对门走 _trans_city 单源（与 _via_txt 同门）——
        # 占位「中转」行落经停词面时停留同取 stopTimeT（审查 P2-2）
        trans = ""
        if cls._trans_city(f):
            via = cls._via_txt(f)
            trans = f" {via}" if via else ""
            lay = str(f.get("layoverT") or "").strip()
            if lay:
                trans += f" 停{lay}"
            dur = str(f.get("totalDuration") or "").strip()
            if dur:
                trans += f"（全程{dur}）"    # 缺省整段省略（不直出 ?）
        else:
            sc = str(f.get("stopCity") or "").strip()
            if sc:
                trans = f"（经停{sc}）"
            elif f.get("stopover"):
                trans = "（经停）"
        plat = cls.PLATFORM_CN.get(f.get("_platform", ""), f.get("_platform", ""))
        if f.get("_platform") == "fliggy" and FLIGGY_TAX_PAD > 0:
            plat += "·税前"    # PC 页展示价为税前（达标判定已加税垫）
        # 同价多渠道合并行（_dedup_tie）：渠道名价值最低（同价时点哪家
        # 都一样），计数「×N」才是决策信息——全形态带「·同价×N」，骨架
        # 档渠道名让位给计数；tie 段殿前于 stale 段（与图版 _plat_tag
        # 同序：超宽截断只吃 stale 尾，N 计数恒保）
        tie = f.get("_tie_n", 1)
        plat_full = (plat + (f"·同价×{tie}" if tie > 1 else "")
                     + (f"·{_stale_txt(f['_stale_h'])}"
                        if f.get("_stale_h") else ""))
        # mark（🔥）在列表序号之后：前缀式「🔥 1. 」会破坏 markdown
        # 列表（PC 端两行粘连）
        no = f"{idx}. {mark}" if idx else f"- {mark}"
        # 价格加粗仅在 🔥 档行（加粗=档位信号）；普通行情行裸文本。
        # :.0f 单源自守（r242 审校 Minor-1）：上游取整门是远程守卫
        # （十九§2 守卫离位族），float 价直达曾产「￥12345.0」且
        # bare 地板档 42/40 超预算
        px = f"**￥{f['price']:.0f}**" if mark else f"￥{f['price']:.0f}"
        full = (f"{no}{px} {f['name']} {f['depTime']}→{arrive}"
                f"{trans}（{plat_full}）")
        # TOP3 明细行同受 20 全角铁律约束（全链唯一无守卫的行：中转+经
        # 停+全程时长+角标曾轻松超宽，手机断点失控）：超宽依次丢全程
        # 时长→税前/补位角标→经停城市→当日达；骨架档「№ ￥x code
        # dep→arr（+1天/停X）（渠道/同价×N）」辨识信息跟入，渠道名
        # 让位两档后逐字截码地板恒 ≤40
        if _disp_dw(full) <= 40:
            return full
        slim1 = full.replace(
            f"（全程{str(f.get('totalDuration') or '').strip()}）", "")
        slim2 = slim1.replace("·税前", "")
        if f.get("_stale_h"):
            # 词面单源消费（含「刚补位」新形态）——裸 :.0f 表达式
            # 曾与新词面失配致剥段失效（兄弟消费点判例）
            slim2 = slim2.replace(f"·{_stale_txt(f['_stale_h'])}", "")
        slim3 = slim2
        via = cls._via_txt(f)
        if via and f" {via}" in slim3:
            slim3 = slim3.replace(f" {via}", "", 1)
        slim4 = slim3.replace(" 当日达", "") if not cross else slim3
        # 末档=骨架行：原末档回传 full 本身，_fit_line 全超时
        # 返回末档即原样输出超宽行、守卫形同虚设（与上方 docstring「骨架
        # 保底」自相矛盾）。骨架保留 no+px——序号/🔥 档位/价格加粗是
        # 档位信号，骨架也不能掉档（曾只剩裸价时刻，TOP3 亮 🔥 语义丢失）
        code = f.get('code') or f.get('name') or ''
        # 辨识信息骨架档跟入（档序律：辨识信息最后丢）：跨天（+1天）
        # 曾在骨架档整体消失——跨天班按到达时刻误判当日达；停X=中转
        # 判据。渠道名/同价计数价值最低（_dedup_tie 同注）让位一档
        sk_id = f"（{cross}）" if cross else ""
        if cls._trans_city(f):
            lay_sk = str(f.get("layoverT") or "").strip()
            if lay_sk:
                sk_id += f" 停{lay_sk}"
        skeleton = (f"{no}{px} {code} {f['depTime']}→{f['arrTime']}{sk_id}"
                    f"（{f'同价×{tie}' if tie > 1 else plat}）"
                    ).replace("  ", " ")
        # 去括号骨架档（校准 P2-2 补）：骨架带全角括号对恰卡 41 的形态
        # （「（同价×N）」4 半角括号）曾塌 bare 丢同价计数——括号是包装
        # 不是信息，先于逐字截剥。「（」换空格而非双删（推送审校 P2-5）：
        # 尾段「→13:50（去哪儿）」双删后时刻与渠道名贴成「13:50去哪儿」
        # 两词粘连；空格替换保留词界且净省 3 半角仍达标
        skeleton_nb = (skeleton.replace("（", " ").replace("）", "")
                       .replace("  ", " ").strip())
        # 硬保底（bare）：骨架带渠道段在极端长航班号下仍可能超宽，
        # _fit_line 全超会原样吐末档——末档必须恒 ≤40。code 缺码回落
        # 长航司名（f.get('name')，「海南航空HU7849」形）时裸拼可破 40
        # （重放 44/41，理论边：生产 25,255 行缺码 0）——
        # 超预算逐字截码段保恒 ≤40（缺码本就零生产样本，纯兜底兜兜底）；
        # 码截空仍超（病理组合：5 位价×跨天×长停留）才舍 停X——
        # 跨天恒保到地板（价格+时刻+跨天=误判当日达防线最小集）。
        # 渠道段在 bare 整体剥除（渠道维度由明细总表图兜底）；不设
        # 「剥渠道保完整码」独立档——与 bare 在码放得下时输出逐字
        # 相同、码放不下时同超，数学死档（两方向都推不出可辨输出）
        head = f"{no}{px} "
        tail_b = f" {f['depTime']}→{f['arrTime']}{sk_id}"
        # 联程双码剥后段（推送审校 P1-1）：双码行逐字截先截码产出
        # 悬垂「UQ2509/」乃至码截空让航班号整体消失（图挂兜底轮
        # 文本=明细唯一载体）——「剥「/」后段保首段」零损耗，先于
        # 逐字截（同构先例 r235 P1 _l2_fallbacks）。档序折入 bare
        # 地板：全码→首段→舍停保码→逐字截——独立档置 bare 前曾吞
        # 「bare 全码可放下」档（Soldier P1-1）；剥段后仍超时舍停
        # 先于截码（码=取票辨识信息，停X=中转判据次要；跨天括注
        # 恒保到地板=误判当日达防线不动）
        trimmed = code
        if ("/" in code and trimmed
                and _disp_dw(head + trimmed + tail_b) > 40):
            trimmed = code.split("/")[0]
        if _disp_dw(head + trimmed + tail_b) > 40 and " 停" in tail_b:
            tail_b = tail_b.split(" 停")[0]
        while trimmed and _disp_dw(head + trimmed + tail_b) > 40:
            trimmed = trimmed[:-1]
        # 半截码回退（r257 备案②）：截点两侧都是字母数字=切在码段中
        # （「川航3U8」形，真函数网格实证）——三十一§2 token 边界律
        # 投影：整 token 丢弃优于半截噪音，回退到该段起点（全字母数字
        # 码=裸航班号行整码丢弃，价格+时刻+跨天地板恒落位不受影响）。
        # 理论边备案：码内连字符形态（截到「UQ-」悬垂段）不触发本
        # 回退也不误截——生产航班码域无连字符词面，走查只认字母数字
        if (trimmed and trimmed != code and len(code) > len(trimmed)
                and trimmed[-1].isascii() and trimmed[-1].isalnum()
                and code[len(trimmed)].isascii()
                and code[len(trimmed)].isalnum()):
            _i = len(trimmed)
            while _i > 0 and code[_i - 1].isascii() \
                    and code[_i - 1].isalnum():
                _i -= 1
            trimmed = code[:_i]
        bare = (head + trimmed + tail_b).replace("  ", " ")
        return _fit_line(full, fallbacks=[slim1, slim2, slim3, slim4,
                                          skeleton, skeleton_nb,
                                          bare])

    def _push_digest(self, route: Route, sections: list):
        # 生产不可达路径备案：调度唯一入口是 _push_digest_multi
        # （main.check_multi）——本单航线版运维对账行只有两族
        # （_channel_ops_lines），缺主路径 _ops_notes 的直挂标注缺失/
        # 孤低价拦截两族（能力对称律残留面）。若未来复活接入调度，
        # 须先按 _ops_notes 同构补齐对账行再上线
        first = sections[0]
        hits = []
        for s in sections:
            # 达标判定用 _qual_price 口径（飞猪税垫，对齐 _collect_hits
            # 与 multi 主路径）——直用展示价曾产「假达标」电话；
            # 元组带所属 s：多日期监控第 2+ 日期命中时，
            # 链接日期/同价优选池用 per-hit 的 section（曾固定取首
            # section，跳转打开的是第一个日期的搜索页）
            if (route.alert_direct > 0 and s["best_direct"] is not None
                    and _qual_price(s["best_direct"])
                    <= route.alert_direct):
                hits.append(("直飞", s["best_direct"], route.alert_direct, s))
            if (route.alert_transfer > 0 and s["best_transfer"] is not None
                    and _qual_price(s["best_transfer"])
                    <= route.alert_transfer):
                hits.append(("中转", s["best_transfer"], route.alert_transfer, s))

        route_txt = f"{route.from_name}→{route.to_name}"
        dep_win = ""
        if (route.dep_time_min or "").strip() or (route.dep_time_max or "").strip():
            lo = route.dep_time_min or "00:00"
            hi = route.dep_time_max or "24:00"
            # 窄屏短格式：完整区间进日志级说明，标题用缩写
            dep_win = (f"（{lo[:5]}后出发）" if not route.dep_time_max
                       else f"（{lo[:5]}–{hi[:5]}）")
        # 详情链接同价优选（qunar→ctrip，与聚合链路同规则）：直飞/中转各按
        # 其最优班次所在渠道开链接；qunar 本轮无数据时不再空挂去哪儿
        # （落点价与文案价一致）
        def _best_url(best):
            if not best:
                return None
            return self._build_view_url(
                route, first["date"],
                self._pref_platform(best, first.get("all_flights") or [best]))

        view_d = _best_url(first["best_direct"])
        view_t = _best_url(first.get("best_transfer_mkt")
                           or first["best_transfer"])
        # 宁缺勿错：qunar 硬编码兜底曾是全仓最后一处「挂羊头」
        # latent——未知/空平台 _build_view_url 返回 ""，链接壳改按需渲染。
        # view_d/view_t 不再互相兜底——跨类别兜底是「文案渠道
        # ≠落点渠道」的挂羊头变种（直飞链接落中转渠道页），违背自家律
        chart_url = (self.round_charts or {}).get(
            (route.from_code, route.to_code, first["date"]))
        chart_md = f"![走势]({chart_url})\n\n" if chart_url else ""

        if not hits:
            # 主信息置顶：未达标状态 + 超线仪表条；TOP3 为次级明细。
            # 中转展示与主链路 KPI 同为行情口径（best_transfer 是合规
            # 筛选口径，两口径曾同屏打架）
            bd = first["best_direct"]
            bt = first.get("best_transfer_mkt") or first["best_transfer"]
            deltas = self._deltas(route, first["date"])

            def _delta_txt(tag):
                return self._delta_txt(deltas, tag)

            # 价格词面 :.0f 单源自守（_fmt_brief/_fmt_flight_line 同族
            # 收口末点）：float 价直达曾产「￥1950.7」；生产双取整门
            # 挡住不可达，纵深防御同律
            _pd = f"{bd['price']:.0f}" if bd else "-"
            _pt = f"{bt['price']:.0f}" if bt else "-"
            title = (f"❌ 未达标｜{route_txt} "
                     f"{self._date_short(first['date'])}{dep_win}｜"
                     f"直飞￥{_pd}·中转￥{_pt}")
            desp = "#### ❌ 本轮未达标\n\n"
            # 图例与主链路同款（_legend_line 公共函数，收敛——
            # 两处各自拼接触发过措辞分叉）
            desp += self._legend_line() + "\n\n"
            if route.alert_direct > 0 and bd:
                _diff_d = bd['price'] - route.alert_direct
                # 档位点与 _kpi_block 同式（本分支曾恒裸文本，
                # 破线/擦边档在演示态与主链路两种语言）；点才粗（粗=档位
                # 信号），超线默认态裸；仪表条同 撤达标行。
                # 组 OR 单源（_tie_any_ok，直飞无 _tie_rows 回落本体）
                _qd = _tie_any_ok(bd, route.alert_direct, route, False)
                # 差额词单源：恰达线非达标读「行情破线」
                _gap_d = gap_txt(bd['price'], route.alert_direct, _qd)
                _dot = tier_dot(_qd, _diff_d, route.alert_direct)
                _core = f"{_dot}直飞 ￥{bd['price']:.0f}"
                _t1 = f"**{_core}**" if _qd else _core
                base1 = ((f"[{_t1}]({view_d})"
                          if view_d else _t1)
                         + f"　线￥{route.alert_direct:.0f}　{_gap_d}")
                # 尾注幅度词面单源（主链同源）；<1% 达标带省略律在
                # 单源内；涨跌注为次要信号挂首档随超宽先丢
                _pct = _kpi_pct_suffix(bd['price'], route.alert_direct)
                _forms = _pct_fallback_forms(base1, _pct)
                _g = ("" if _qd else
                      self._gauge(bd['price'], route.alert_direct, ok=_qd))
                desp += (_fit_line(_forms[0] + _delta_txt("direct"),
                                   fallbacks=_forms) + "\n\n"
                         + (f"{_g}\n\n" if _g else ""))
            if route.alert_transfer > 0 and bt:
                _diff_t = bt['price'] - route.alert_transfer
                # 组 OR 单源（_tie_any_ok，与主链 KPI/summary 同口径）
                _qt = _tie_any_ok(bt, route.alert_transfer, route, True)
                # 差额词单源：恰达线非达标读「行情破线」
                _gap_t = gap_txt(bt['price'], route.alert_transfer, _qt)
                _dot = tier_dot(_qt, _diff_t, route.alert_transfer)
                _core = f"{_dot}中转 ￥{bt['price']:.0f}"
                _t1 = f"**{_core}**" if _qt else _core
                base1 = ((f"[{_t1}]({view_t})"
                          if view_t else _t1)
                         + f"　线￥{route.alert_transfer:.0f}　{_gap_t}")
                # 尾注幅度词面单源（直飞同律）
                _pct_t = _kpi_pct_suffix(bt['price'], route.alert_transfer)
                _forms_t = _pct_fallback_forms(base1, _pct_t)
                _g = ("" if _qt else
                      self._gauge(bt['price'], route.alert_transfer, ok=_qt))
                desp += (_fit_line(_forms_t[0] + _delta_txt("transfer"),
                                   fallbacks=_forms_t) + "\n\n"
                         + (f"{_g}\n\n" if _g else ""))
            desp += chart_md
            table_md = self._flights_table_md(route, sections)
            if table_md:
                # 收口：明细图成功不出文本比价（跳转文案才用
                # 文本；总表 PNG 已含三列比价且渠道链完整不截断）；
                # 各渠道最低行情也撤入图内子节，文本只留运维行
                desp += table_md
                desp += self._channel_ops_lines(sections)
            else:
                desp += self._top3_blocks(route, sections)
                # 图挂：行情退回文本兜底（信息不能跟图一起消失）
                desp += self._channel_market_lines(sections)
                desp += self._channel_ops_lines(sections)
            # 兜底查价入口（收编 _ensure_jump_link 单源——multi
            # 版有判定而本版整段缺失，窗口全空+图挂+表挂曾整条零可点链接）
            desp = self._ensure_jump_link(desp, route, first)
            # 未达标心跳退避（与 multi 主路径同闸同语义）
            if not self._prev_hit and not self._heartbeat_gate():
                return
            if self.notifier.send(sanitize_desp(title), sanitize_desp(desp)):
                self.logger.info("[心跳] 已推送运行状态: %s", title)
            return

        kind, f, th, s0 = hits[0]
        f0 = f   # 循环体会重绑定 f：尾部「查看详情」链接必须用首 hit 航班
        # 差额词走 gap_txt 单源（与聚合路径标题同语言）：手拼「≤」
        # 曾让白名单外字符入正文、价格未 :.0f 曾出「￥1850.0」
        title = (f"🚨 已达标！{route_txt} "
                 f"{self._date_short(first['date'])}{dep_win}｜"
                 f"{kind}￥{f['price']:.0f} {gap_txt(f['price'], th, True)}")

        desp = "#### 🚨 已达标——可出手\n\n"
        for kind, f, th, s_h in hits:
            # 与 multi 版 _digest_payload 三行制同形态（对齐：
            # 单行拼接超 40 半角必折行且整行无渠道直达链接，禁同型
            # 信息两种形态）；seg 降级链与 tail 链接降级链同款
            cross = f.get("crossDayDesc") or ""
            base_seg = (f"{f['depTime']}→{f['arrTime']}"
                        + (f"({cross})" if cross else ""))
            via = self._via_txt(f)
            lay = str((f.get("layoverT") if self._trans_city(f)
                       else f.get("stopTimeT")) or "").strip()
            seg = _fit_line(
                "> " + base_seg + (f" {via}" if via else "")
                + (f" 停{lay}" if lay else ""),
                fallbacks=["> " + base_seg + (f" {via}" if via else ""),
                           "> " + base_seg])
            plat_key = self._pref_platform(f, s_h.get("all_flights") or [f])
            plat_cn = self.PLATFORM_CN.get(plat_key, plat_key)
            # 差额文案与 multi 版共用 _low_txt（收口：本行曾漏
            # pad 条件恒挂「(税前)」假警示，两版分叉）
            low = _low_txt(f["price"], th, f.get("_platform"))
            _jump = self._build_view_url(route, s_h["date"], plat_key)
            if _jump:
                jump = f"[打开{plat_cn}]({_jump})"
                tail = _fit_line(
                    f"> {plat_cn} · {low} · {jump}",
                    fallbacks=[f"> {low} · {jump}", f"> {plat_cn} · {low}"])
            else:
                tail = _fit_line(f"> {plat_cn} · {low}",
                                 fallbacks=[f"> {low}"])
            # 每行独立引用短块（\n\n 分隔）：PC 端单 \n 会把引用行粘成
            # 一整段、`> ` 缩进丢失（钉钉渲染铁律）；首行套行宽守卫
            # （超长航司名可破 40 半角，补）。粗体范围与
            # multi 版统一：仅「直飞 ￥N」档位信号，航班名不进粗体。
            # `> ` 前缀入量纲（multi 版审校 P2-1 同律同修）
            # 双名剥档（审查 P2-4 同步 multi 版）：「新海航｜金鹏航空
            # Y87519」超宽曾整名直落地板（身份净失）——与 hits head
            # 同款 fallbacks（剥营销名 A｜档 → 裸判据地板）
            _lg_base = f"> 🔥 **{kind} ￥{f['price']:.0f}**"
            _lg_nm = str(f.get("name") or "")
            _lg_bar = _lg_nm.find("｜")
            _lg_fbs = [_lg_base]
            if _lg_bar >= 0:
                _lg_fbs.insert(0, f"{_lg_base} {_lg_nm[_lg_bar + 1:]}")
            head = _fit_line(f"{_lg_base} {_lg_nm}", fallbacks=_lg_fbs)
            desp += (f"{head}\n\n"
                     f"{seg}\n\n"
                     f"{tail}\n\n")
        desp += chart_md
        table_md = self._flights_table_md(route, sections)
        if table_md:
            # 收口：明细图成功不出文本比价（跳转文案才用文本）；
            # 各渠道最低行情撤入图内子节，文本只留运维行
            desp += table_md
            desp += self._channel_ops_lines(sections)
        else:
            desp += self._top3_blocks(route, sections)
            desp += self._channel_market_lines(sections)
            desp += self._channel_ops_lines(sections)
        # 查看链接随达标航班实际渠道（同价多渠道优先去哪儿/携程）；
        # 未知平台空 URL：剥链接壳只出纯文本。f0=首 hit 航班（禁用循环
        # 尾值航班配 hits[0] 日期池——多 hit 时渠道与日期错配）
        hit_plat = self._pref_platform(f0, s0.get("all_flights") or [f0])
        _hit_url = self._build_view_url(route, s0["date"], hit_plat)
        _hit_cn = self.PLATFORM_CN.get(hit_plat, hit_plat)
        if _hit_url:
            desp += f"[👉 在{_hit_cn}查看详情]({_hit_url})\n"
        else:
            desp += f"👉 在{_hit_cn}查看详情\n"
        # 达标强提醒：@指定人（正文含 @手机号 才会高亮）。空段归一
        # 同 multi 主路径（rstrip 后补段落级分隔，恒恰一个空段）
        at_mobiles = None
        if self.at_mobile:
            at_mobiles = [self.at_mobile]
            desp = desp.rstrip("\n") + f"\n\n@{self.at_mobile} "
        # desp 出口消毒单源（与 multi 主路径 _digest_payload 返回口
        # 同律）：本分支 desp 同嵌爬虫自由文本，下游三消费端（详情页
        # 存档/_send_urgent→短信/主推）在存档前单点收口；title 同律
        # （r242 审校 Minor-3：r236 只收了 desp——title 载体=route
        # 配置自由文本，存档页标题/主推/urgent 全链随本点收口）
        title = sanitize_desp(title)
        desp = sanitize_desp(desp)
        # 详情页存档先行：Windows 弹窗 launch 直达（与 multi 主路径同闭环，
        # 此路径弹窗点击曾无任何反应）
        launch = self._archive_notify(title, desp)
        # 回环 base_url 只供本机弹窗 launch：desp 追加该链接手机点必死链
        if launch and self._launch_public():
            desp += f"\n\n[📲 完整详情（点击直达）]({launch})\n\n"
        # 通道失败浮出水面（教训）：失败警告进钉钉主推。
        # 修雷：hits 是 4 元组，曾按 3 元解包——本分支一旦有
        # 达标 hit 整轮推送在发送前抛 ValueError 哑弹；per-hit section
        # 同步对齐 hits 元组第 4 位（曾写死 sections[0]，复刻
        # 修过的「固定取首 section」病）
        # fresh_hits 上移（与 multi 主路径同门）：先算去抖再分发——
        # _send_urgent 曾在去抖计算之前执行，2h 内持续达标每轮重拨。
        # 本路径 hits 是 4 元组 (kind,f,th,s)，_phone_should_ring 说
        # 5 元组 (route,s,kind,f,th) 语——按位桥接（直拼曾 ValueError
        # 哑弹，tests/test_v1549_regress.py 钉守护）
        fresh_hits = [h for h in hits if self._phone_should_ring(
            (route, h[3], h[0], h[1], h[2]))]
        # 持续达标档：hits 在而 fresh 空=首拨已响过的持续达标轮——
        # 标题/正文头换 🔔（与 multi 主路径同语义，恒 🚨 曾像每轮首报）
        if hits and not fresh_hits:
            title = title.replace("🚨", "🔔", 1)
            desp = desp.replace("#### 🚨 已达标——可出手",
                                _SUSTAIN_HEAD, 1)
        if not self._send_urgent(title, desp,
                                 [(route, s_h, kind, f, th)
                                  for kind, f, th, s_h in fresh_hits],
                                 launch=launch):
            desp += "\n\n" + URGENT_FAIL_NOTE + "\n\n"
        sent = self.notifier.send(title, desp, at_mobiles=at_mobiles,
                                  launch=(launch if self._launch_public()
                                          else ""))
        if sent:
            self.logger.info("[报告] 已推送达标报告: %s", title)
        # 风暴与电话同去抖（与 multi 主路径同门）：仅"新达标"才 3 连推，
        # 持续达标的轮次只发主推；免打扰时段风暴跳过（不补发）
        if sent and hits and fresh_hits and self.storm_repeat > 1:
            if self._in_quiet():
                self.logger.info("[静默] %s–%s 免打扰时段，风暴连推跳过",
                                 self.quiet_start, self.quiet_end)
            else:
                self._storm(title, desp, at_mobiles, launch=launch)

    def _storm(self, title: str, desp: str, at_mobiles, launch: str = ""):
        import threading
        import time as _time
        # 风暴复用主推文案前剥离「发送失败」警示行（单源 URGENT_FAIL_NOTE
        # 的两种换行形态）——该行只描述主推当时的通道状态，+1min/+3min
        # 重推仍带着会误导（通道或已自愈）
        desp = desp.replace("\n\n" + URGENT_FAIL_NOTE, "").replace(
            "\n" + URGENT_FAIL_NOTE, "")
        # 延迟表四档（60/180/300/480s）：webui 配置域已声明 max=5，
        # 表硬编码两档时 repeat>3 静默无效（配置域与实现失配——
        # storm_repeat 语义=总条数，切片上限随表长）
        for i, delay in enumerate(
                (60, 180, 300, 480)[: max(0, self.storm_repeat - 1)], 2):
            def _push(d=delay, n=i):
                _time.sleep(d)
                try:
                    ok = self.notifier.send(
                        _storm_title(n, self.storm_repeat, title),
                        _storm_desp(n, self.storm_repeat, desp),
                        at_mobiles=at_mobiles,
                        launch=(launch if self._launch_public() else ""))
                    self.logger.info("[风暴] 第 %d 条提醒 %s", n, "已推" if ok else "失败")
                except Exception as e:
                    self.logger.warning("[风暴] 推送异常: %s", e)
            threading.Thread(target=_push, daemon=True).start()

    def _top3_blocks(self, route: Route, sections: list) -> str:
        """直飞/达标中转 TOP3 明细（次级板块，状态头之后）。"""
        desp = ""
        for s in sections:
            d_th = (f"（线￥{route.alert_direct:.0f}）"
                    if route.alert_direct > 0 else "")
            # 多日期航线组头带日期段：两块「直飞最优
            # TOP5」同题头曾只能靠价格猜归属（与 multi 主表 lbl 同款）
            d_tag = (f" · {s['date'][5:].replace('-', '/')}"
                     if len(sections) > 1 and s.get("date") else "")
            head = f"#### ✈️ 直飞最优TOP5{d_th}{d_tag}"
            if _disp_dw(head) > 40:
                # 5 位数阈值+多日期曾 41 半角超宽（推送审校 P2-2）：
                # 线价下沉引用行（_section_title 两分支同律，信息守恒）
                desp += f"#### ✈️ 直飞最优TOP5{d_tag}\n\n"
                if route.alert_direct > 0:
                    desp += f"> 线￥{route.alert_direct:.0f}\n\n"
            else:
                desp += head + "\n\n"
            if s.get("top_direct"):
                for i, fl in enumerate(s["top_direct"], 1):
                    # 🔥 与明细表/_qual 同口径（_qual_price 含飞猪税垫）：
                    # 展示价判定曾让飞猪税前价亮 🔥 而表图/明细不绿——
                    # 文字 TOP3 是图挂唯一兜底载体，恰是口径最易走样处。
                    # tie 组 OR 单源（首成员超线而组内合规曾漏 🔥）；
                    # 补位行不参 🔥（_row_qual 单源，与总表图同律——
                    # 补位低价照亮 🔥=「可出手」指向过期价）
                    fire = "🔥 " if _row_qual(fl, route.alert_direct,
                                              route, False) else ""
                    # 🔥 放进列表项内（序号后）：前缀式会破坏 markdown 列表；
                    # 行间 \n\n（推送审校 P1-1）：兜底区行间裸单 \n 在钉钉
                    # PC 粘段墙（十§1 渲染铁律，图挂日恰是明细唯一载体日）
                    desp += f"{self._fmt_flight_line(fl, i, fire)}\n\n"
            else:
                desp += "- 暂无数据\n\n"
            # 标题 ####（正文字号）；到达约束+达标线挪到下一行短引用
            # （标题行超 20 全角窄屏必折行）；前导 \n 随行间 \n\n 化退役
            # （曾产三连空行）
            desp += f"#### 🔁 中转最优TOP5{d_tag}\n\n"
            if route.alert_transfer > 0:
                desp += (f"> 仅当日/次日{route.transfer_arrival_max}前到 ｜ "
                         f"线￥{route.alert_transfer:.0f}\n\n")
            if s.get("top_transfer"):
                for i, fl in enumerate(s["top_transfer"], 1):
                    # tie 组 OR 单源（含 _transfer_ok 全口径，直飞版同
                    # 律）；补位行不参 🔥（_row_qual 单源，直飞版同律）
                    fire = "🔥 " if _row_qual(fl, route.alert_transfer,
                                              route, True) else ""
                    desp += f"{self._fmt_flight_line(fl, i, fire)}\n\n"
            else:
                desp += "- 暂无满足到达约束的中转\n\n"
            # 组尾空行不再追加（行间已 \n\n 化，组尾再追加即三连空行）
        desp += self._cross_compare(sections)
        # 各渠道最低行情行：调用方（图挂兜底分支）已显式追加
        # _channel_market_lines/_channel_ops_lines——此处曾残留已删除的
        # _channel_overview 调用，图挂路径 AttributeError 整轮推送丢失
        # （实锤，修复）
        return desp

    @classmethod
    def _fp_cands(cls, sections: list, top_n: int = 4) -> list:
        """同班跨渠道分组（日期+出发+到达+中转+跨天+经停指纹，各渠道取
        最低价），返回 [(最大价差, [按价升序的各渠道航班], 日期)] 按可省
        降序。全部日期都参与分组（曾首轮 return 只比首日期——多日期航线的
        第 2+ 日期比价候选被整段丢弃）；指纹含日期与经停标志：不同日期
        的同刻班次、同刻的直飞/经停班都是不同物理班，不得合并比价。"""
        groups = {}
        for s in sections:
            date = s.get("date") or ""
            for f in s.get("pool") or []:
                if not f.get("depTime") or not f.get("arrTime"):
                    continue
                key = (date, f["depTime"], f["arrTime"],
                       f.get("transCity", ""), f.get("crossDayDesc", ""),
                       bool(f.get("stopover")))
                byp = groups.setdefault(key, {})
                cur = byp.get(f.get("_platform"))
                if cur is None or f["price"] < cur["price"]:
                    byp[f.get("_platform")] = f
        cands = []
        for key, byp in groups.items():
            if len(byp) < 2:
                continue
            fs = sorted(byp.values(), key=lambda x: x["price"])
            save = fs[-1]["price"] - fs[0]["price"]
            # 小额差价（<30 元且 <1%）是渠道重摇噪音，不值得占版面——
            # 「省￥21」与「省￥430」同权重曾淹没主档（降噪）
            if save < max(30, fs[0]["price"] * 0.01):
                continue
            cands.append((save, fs, key[0]))
        cands.sort(key=lambda x: -x[0])
        return cands[:top_n]

    @staticmethod
    def _outlier(fs: list) -> bool:
        """比价组离群判定：最高价 > 2×最低价，或组内舱位大类（_cabin_cn
        ×cabin_clean 串舱守卫）不止一种——「可省」大概率是跨舱位/报价
        口径差异而非真实可省（1-2× 跨舱假可省曾被当真实省额推送；
        串舱存量行的假高档标签不清污会误触本判定）。"""
        cabs = {_cabin_cn(cabin_clean(f)) for f in fs}
        cabs.discard("")
        return fs[-1]["price"] > fs[0]["price"] * 2 or len(cabs) > 1

    @classmethod
    def _compare_rows(cls, cands: list, date_labels: bool = False) -> list:
        """_fp_cands 候选 → 总表 compare 组结构化行。实时推送与日报
        共用同一组装（两端行结构曾各写一份，漂移风险——单一事实源；
         multi 总表第三份内联组装也收编于此，加字段不再漏端）。
        date_labels：多日期航线候选行 label 追加日期段（候选可来自
        任一日期；单日期日报不加）。"""
        comp = []
        for save, fs, cdate in cands:
            best = fs[0]
            label = best.get("name") or best.get("code", "同班")
            if date_labels and cdate:
                label += f" {cls._date_short(cdate)}"
            comp.append({
                "label": label,
                "dep": best["depTime"], "arr": best["arrTime"],
                "trans": best.get("transCity") or "",
                "cross": best.get("crossDayDesc") or "",
                "lay": next((f.get("layoverT") for f in fs
                             if f.get("layoverT")), ""),
                "stopCity": re.sub(r"[(（]中国[)）]$", "", next(
                    (f.get("stopCity") for f in fs if f.get("stopCity")),
                    "")),
                "chain": [(cls.PLATFORM_CN.get(
                            f.get("_platform", ""), "?"),
                           f["price"],
                           _cabin_cn(cabin_clean(f))) for f in fs],
                # 第七批：公务舱最低价随行入比价组（qunar H5
                # extparams.businessClassMinPrice 正数口径；升舱差由读者
                # 对照链内现价——渲染端链尾「公务￥N」词条消费）。同班
                # 各渠道报价同机，取首个带值者（五渠道有源，完整枚举
                # 见 _cross_compare 注）。bool 显式排除：isinstance(x, int)
                # 对 True 为真，「公务￥True」词条假数据。
                # bizCab 与 biz 同一行取源（首个带值行），舱别词面
                # 「公务/头等」随胜出政策，存量行空串由渲染端回退「公务」
                "biz": next((f["bizPrice"] for f in fs
                             if isinstance(f.get("bizPrice"), int)
                             and not isinstance(f.get("bizPrice"), bool)
                             and f["bizPrice"] > 0), ""),
                "bizCab": next((str(f.get("bizCabin") or "") for f in fs
                                if isinstance(f.get("bizPrice"), int)
                                and not isinstance(f.get("bizPrice"), bool)
                                and f["bizPrice"] > 0), ""),
                "save": save,
                "outlier": cls._outlier(fs)})
        return comp

    @classmethod
    def _cross_compare(cls, sections: list, top_n: int = 4,
                       label: str = "") -> str:
        """同班跨渠道比价：同一航班（日期+出发+到达+中转指纹）在各渠道
        的最低价并排，按"最大可省"排序——交叉比价的意义：同班机买贵了
        一目了然。label：多航线时标注归属（如「上→乌 09/25」）；
        多日期航线的候选行各自带日期标注（候选可来自任一日期）。"""
        cands = cls._fp_cands(sections, top_n)
        if not cands:
            return ""
        multi = len({s.get("date") for s in sections if s.get("date")}) > 1
        desp = f"#### ⚖️ 同班比价{(' · ' + label) if label else ''}\n\n"
        for save, fs, cdate in cands:
            best = fs[0]
            # 超过 3 家只展示最低/最高两端：U+2026「…」在钉钉渲染成。。。；
            # 中间渠道价在明细总表图里有完整链，不丢信息
            show = fs if len(fs) <= 3 else [fs[0], fs[-1]]
            # 舱位码标注（渠道覆盖低，有则标：Y 经济/J 公务/F 头等）
            def _cabin_tag(f):
                cn = _cabin_cn(cabin_clean(f))
                return f"({cn})" if cn else ""
            chain = "→".join(
                f"{cls.PLATFORM_CN.get(f.get('_platform', ''), '?')}"
                f"￥{f['price']:.0f}{_cabin_tag(f)}" for f in show)
            chain_nc = "→".join(
                f"{cls.PLATFORM_CN.get(f.get('_platform', ''), '?')}"
                f"￥{f['price']:.0f}" for f in show)
            # >3 家只展两端：链尾补家数注（图挂兜底语境中间渠道价在
            # 文本不可恢复，(等N家) 是「链非全量」的对账锚；mini 档
            # 已有等N家同源语义）
            _more = f"(等{len(fs)}家)" if len(fs) > 3 else ""
            chain += _more
            chain_nc += _more
            # 辅行终极降级形态：最低价渠道 + 家数（价格链整条放不下时）
            mini = (f"　{cls.PLATFORM_CN.get(best.get('_platform', ''), '?')}"
                    f"￥{best['price']:.0f} 等{len(fs)}家")
            name = best.get("name") or best.get("code", "同班")
            date_tag = (f"（{cls._date_short(cdate)}）"
                        if multi and cdate else "")
            # 同班指纹的衔接时长是航线属性：组内任一渠道有真实值即用
            lay = next((f.get("layoverT") for f in fs if f.get("layoverT")), "")
            # 离群警示（>2× 或组内跨舱位）：「可省」大概率是跨舱位/报价
            # 口径差异而非真实可省——如实改口径并标注（判定见 _outlier）
            outlier = cls._outlier(fs)
            # 两行制语义分层（主/辅两档）：头行=航班身份+经停+结论（列表
            # 行不加粗：加粗=档位信号，比价头行非档位内容），辅行=价格链
            # （全角空格缩进辅档）——单行塞全部曾在手机端把「￥60」结论
            # 孤行折断（20 全角不受控折行实锤）。头行超宽才把经停下沉
            # 辅行；辅行超 40 依次降级：去舱位括注→「最低价 等 N 家」；
            # PC 不认单 \n：两行间必须 \n\n
            via_full = cls._via_txt(best) + (f" 停{lay}" if lay else "")
            tail = (f" 💰{'差' if outlier else '可省'}￥{save:.0f}"
                    f"{' ⚠️口径差异' if outlier else ''}")
            head = (f"- {name}{date_tag}"
                    f"{(' ' + via_full) if via_full else ''}{tail}")
            if _dw(head) > 40 and via_full:   # 头行超 20 全角：经停下移辅行
                head = f"- {name}{date_tag}{tail}"
                sub = _fit_line(
                    f"　{via_full} ｜ {chain}",
                    fallbacks=[f"　{via_full} ｜ {chain_nc}", f"　{chain}",
                               f"　{chain_nc}", mini])
            else:
                sub = _fit_line(f"　{chain}",
                                fallbacks=[f"　{chain_nc}", mini])
            # 头行终档守卫：经停下移后仍超宽（双航司长名「新海航｜
            # 海南航空HU7849」实发形态 45 半角）依次降级——去日期
            # 标注→截航司名保航班号；地板档=航班号+结论（价格结论是
            # 核心判据最小集，链尾恒达标）
            _fm = _RE_TAIL_FNO.search(name)
            head = _fit_line(
                head,
                fallbacks=[f"- {name}{tail}",
                           f"- {_fm.group(1)}{tail}" if _fm
                           else f"- {tail.strip()}",
                           f"- {tail.strip()}"])
            desp += f"{head}\n\n{sub}\n\n"
        return desp

    def _channel_market_lines(self, sections: list) -> str:
        """各渠道最低行情行（纯数据无链接）—— 起仅作图失败时的
        文本兜底：图成功时该信息已入总表 PNG「各渠道最低」子节（定律：
        无跳转文案一律入图；原段曾是定律最直接违反者且超宽无守卫）。"""
        desp = ""
        # 多日期航线行前缀带日期短标（推送审校 P1-4）：sections 2+ 时
        # 两日期渠道价交错无主；单日期不带（零噪音常态不加状态标识律）
        _multi = len(sections) > 1
        for s in sections:
            plats = set(s.get("plat_top3") or {}) | set(s.get("platform_mins") or {})
            if not plats:
                continue
            _dpre = (f"{self._date_short(s.get('date') or '')} "
                     if _multi and s.get("date") else "")
            for p in sorted(plats, key=lambda x: s["platform_mins"].get(x, 9e9)):
                # 渠道名进预算：未知长平台键（病理形态）曾让前缀自身
                # 超预算，整行恒破 40——cn 截到前缀预算内（「让前缀
                # 自身进预算」，地板档恒达标律的取数侧）。limit 23=
                # tops 分支整行恒达标约束：pre(2+cn+6)+brief 地板
                # 7.6（「￥12345」五位数价词面，1.125 校准；词面
                # :.0f 收口后地板自浮点形态 9 收窄，max(8) 同步放宽）
                # ≤40（多日期 _dpre 另扣；
                # 正常渠道名 5 半角零回归）
                cn = _clip_dw(self.PLATFORM_CN.get(p, p),
                              max(2, 23 - _disp_dw(_dpre)))
                tops = (s.get("plat_top3") or {}).get(p)
                if tops:
                    best = min(tops, key=lambda f: f.get("price", 9e9))
                    # 前缀进预算（推送审校 P1）：brief 本体守卫
                    # 40 但拼「- {渠道} 最低 」后整行恒 44-48，图挂兜底轮
                    # 20/2546 行全超（else 直出分支 P2-2 同病先修）
                    # max(8,…)：地板 8 ≥ 价格词面 7.6 半角（地板档恒可落）
                    pre = f"- {_dpre}{cn} 最低 "
                    desp += pre + self._fmt_brief(
                        best, budget=max(8, 40 - _dw(pre))) + "\n\n"
                else:
                    # （推送审校 P2-2）：图挂兜底路径唯一漏网守卫
                    # （收口 _channel_ops_lines 时的同病漏网）——
                    # 长渠道名+长尾注可破 40 半角；短尾档「（全线价）」
                    # 保渠道+价格核心判据，解释性长注按重要性丢弃；
                    # 链尾地板档「￥价格」（渠道名已截进预算，恒达标）
                    v = s["platform_mins"].get(p)
                    if v is not None:
                        desp += (_fit_line(
                            f"- {_dpre}{cn} 最低 ￥{v:.0f}"
                            f"（全线价，该渠道无明细未筛）",
                            fallbacks=[
                                f"- {_dpre}{cn} 最低 ￥{v:.0f}（全线价）",
                                f"- {_dpre}{cn} ￥{v:.0f}"]) + "\n\n")
            # 组尾空行不再追加（行间已 \n\n 化，组尾再追加即三连空行）
        return desp

    def _channel_ops_lines(self, sections: list) -> str:
        """运维行：无数据渠道对账 + 携程登录指引（操作指引类文本，
        非行情数据，文本合法留区）。"""
        desp = ""
        for s in sections:
            missing = [p for p in self.platforms
                       if p not in (s.get("seen_plats") or [])]
            if missing:
                # 与主链路「无数据渠道」同款行宽守卫（渠道多时整行曾
                # 超 20 全角窄屏折行）；行间 \n\n 独立成段
                heads = "⚠️ 本轮无数据渠道："
                names = "、".join(self.PLATFORM_CN.get(p, p)
                                  for p in missing)
                # else 段同走守卫（推送审校 P2）：5 渠道长名
                # ≈44 半角直出曾超 20 全角窄屏折行失控；地板档
                # （「(截)」半角括号 _dw 实值 4 半角〔推送审校
                # P3-7 半角化在案〕；实况 5 渠道 names 最宽 30
                # 半角 fallback 不可达，地板档自身恒 ≤limit 纪律在案）
                desp += (heads + names if _dw(heads + names) <= 40
                         else heads + "\n\n> " + _fit_line(
                             names, limit=40 - _dw("> "),
                             # 引用行前缀并入量纲（推送审校 P3-1）：
                             # "> "+40 半角本体=42 曾绕过守卫；地板档
                             # 随限收紧 16×2+4=36 本体，+前缀 2=38
                             # =limit 恰满
                             fallbacks=[names[:16] + "(截)"])
                         ) + "\n\n"
                if "ctrip" in missing:
                    # 拆两段：整句 ~63 半角是全库唯一没走守卫
                    # 的裸行，>20 全角窄屏折行断点失控（第二行词面
                    # 收 _CTIP_LOGIN_NOTE 单源，34 半角恒达标）
                    desp += ("（携程需本机登录态）\n\n"
                             + _CTIP_LOGIN_NOTE + "\n\n")
        return desp

    @staticmethod
    def _gauge(price: float, threshold: float, bars: int = 5,
               ok: Optional[bool] = None) -> str:
        """行情破线行的档位强化条：🟩 满格。超线行返空——🟦 进度格
        曾是全推送体系唯一「有图无例」的信号（🟦 数量=超出线幅度与
        行1「差￥N（N%）」同一数字两次编码，生产 200 条 185 条成串
        蓝块无解码；定律「超线是默认态不占语义点」），撤除
        后仪表条只在破线时出现，与图例「🟩=破线」同义强化。
        同消息同色单义：🟨 已钦定为擦边档（图例），仪表条再借 🟨 表达
        「破线但约束未满足」曾与图例两义打架——仪表条只表达行情价
        破线，达标口径差异由 KPI 行 🎯/（行情价）注承担（相邻
        自解释，收口）。
        ok 参数保留（调用方传达标口径命中），不再影响颜色。
        （▓░ 在钉钉会渲染成黑块，弃用；10 格 emoji 在钉钉窄屏必折行
        破坏完整性，实测 5 格稳定单行）"""
        if not threshold or price is None:
            return ""
        if price <= threshold:
            return "🟩" * bars   # 行情价破线（达标与否见 KPI 🎯/行情价注）
        return ""   # 超线默认态不占语义点：行1 差额百分比已表达幅度

    def _flights_table_md(self, route: Route, sections: list) -> str:
        """TOP 明细渲染成表格 PNG 直推（钉钉 markdown 不支持表格，
        文字列表密度高可读性差）；生成/上传失败返回空由文字版兜底。"""
        try:
            from report import render_flights_table, upload_chart
            rows = []
            for s in sections:
                for kind, key, th in (
                        ("direct", "top_direct", route.alert_direct),
                        ("transfer", "top_transfer", route.alert_transfer)):
                    fs = []
                    for f in s.get(key) or []:
                        g = dict(f)
                        # tie 组达标 OR（_tie_any_ok 单源，multi 版同律：
                        # 全量 _transfer_ok 曾把衔接/直挂不达标的中转染绿）；
                        # 补位行不参达标色（_row_qual 单源，与 multi 版
                        # 同律——单航线图曾旁路回潮）
                        g["_qual"] = _row_qual(g, th, route,
                                               kind == "transfer")
                        g["_th"] = th   # 表格图价格三档（擦边琥珀档）判定用
                        fs.append(g)
                    # plat_mins 只挂中转组尾（曾两组各挂一份同值重复，
                    # 与 multi 版同型）
                    meta4 = {"layover_min": route.transfer_layover_min,
                             "arrival_max": route.transfer_arrival_max}
                    if kind == "transfer":
                        meta4["plat_mins"] = self._plat_mins_for(s)
                    rows.append((kind, fs, None, meta4))
            cands = self._fp_cands(sections, top_n=4)
            if cands:
                # 结构化行：明细总表按三列表格渲染（预拼 ⚖️ 字符串
                # 曾在 PIL 里渲染成「口」方块）；组装单源 _compare_rows
                # （日报 compare 组共用，防两端行结构漂移）
                rows.append(("compare", self._compare_rows(cands)))
            title = (f"{route.from_name}→{route.to_name} "
                     f"{sections[0]['date'][5:].replace('-', '/')} 最优明细 TOP5")
            bd = sections[0].get("best_direct")
            bt = (sections[0].get("best_transfer_mkt")
                  or sections[0].get("best_transfer"))
            bits = []
            if bd:
                # 图内 summary 档位词单源（与 multi 总表/日报
                # summary 同语言 kpi_tier_txt）：旧「直飞最低 ￥N（线￥N）」
                # 无档位词，恰达线时图上读不出达标口径
                _qd = (route.alert_direct > 0
                       and _qual_price(bd) <= route.alert_direct)
                bits.append(kpi_tier_txt(
                    "直飞", bd['price'], route.alert_direct, _qd)
                    if route.alert_direct > 0
                    else f"直飞最低 ￥{bd['price']:.0f}")
            if bt:
                # 组 OR 单源（_tie_any_ok，与总表行/文本 KPI 同语言——
                # 单判曾让遗留路径 tie 组三语言并存）
                _qt = _tie_any_ok(bt, route.alert_transfer, route, True)
                bits.append(kpi_tier_txt(
                    "中转", bt['price'], route.alert_transfer, _qt)
                    if route.alert_transfer > 0
                    else f"中转最低 ￥{bt['price']:.0f}")
            out = (f"{render_dir()}/flights_table_{_png_user_tag(self.user)}"
                   f"{route.from_code}{route.to_code}"
                   f"_{sections[0]['date']}.png")
            render_flights_table(
                rows, title, out, summary=" ｜ ".join(bits),
                stamp_note="当轮+近6h补位")
            url = upload_chart(out, None, self.logger, ih=self.image_host)
            if url:
                return (f"#### 📋 明细TOP5 {_TBL_HEAD_TIER}\n\n"
                        f"![明细表]({url})\n\n")
            self.logger.warning("[表格图] 上传失败，回退文字明细")
        except Exception as e:
            self.logger.warning("[表格图] 生成失败，回退文字明细: %s", e)
        return ""

    @staticmethod
    def _trans_city(f: dict) -> str:
        """中转真实城市单源（占位「中转」与缺席同归空串）——「经哪+
        停多久」的配对取数门：凡按 transCity 真值决定「配 layoverT
        （中转停留）还是 stopTimeT（经停停留）」的消费点一律经此判定，
        与 _via_txt 词面优先序同门。占位行（tuniu 只给「中转」）若带
        stopCity，词面落「经停X」时停留必须同取 stopTimeT——配对门
        仍按真值 transCity 判曾让 layoverT（中转停留）拼到经停城市后
        （审查 P2-2 占位洞，与主病灶同形）。"""
        c = str(f.get("transCity") or "").strip()
        return c if c and c != "中转" else ""

    @staticmethod
    def _via_txt(f: dict) -> str:
        """经停词组：中转行（transCity 为真实城市）→「经XX」优先——
        中转行可同带 stopCity（第一段经停城市），经停词面若优先会把
        消费点的 layoverT（中转停留）拼到经停城市后（「经停庆阳
        停22:55」把中转停留错配给庆阳，与 KPI 行3/总表 PNG 同屏
        矛盾——经停细节由总表徽标与 stopTimeT 配对承载，不经本词面）；
        纯经停行（无 transCity）→「经停西安」；渠道给不出城市
        （tuniu「中转」占位）时返回空——避免「经中转」病句。"""
        c = Alerter._trans_city(f)
        if c:
            return f"经{c}"
        sc = str(f.get("stopCity") or "").strip()
        return f"经停{sc}" if sc else ""

    @staticmethod
    def _plat_mins_for(s: dict) -> dict:
        """组级「各渠道最低」数据（总表 PNG 子节用）：plat_top3
        有明细取其最低；否则 platform_mins 全线价标「全线」（未筛到达/
        衔接，同旧文本段「全线价」口径词）。按价升序（dict 保序）。"""
        out = {}
        for p, tops in (s.get("plat_top3") or {}).items():
            if tops:
                lo = min((f.get("price") or 0) for f in tops)
                # 价格带 PRICE_MIN–PRICE_MAX 单源（与曲线/列表
                # 同带）：异常值宁缺勿错（9e9 兜底曾可入图直出，
                # 审查补；旧注释「300–50000」与代码双失真一并收口）
                if PRICE_MIN <= lo <= PRICE_MAX:
                    out[p] = (lo, True)
        for p, v in (s.get("platform_mins") or {}).items():
            if p not in out and v is not None:
                out[p] = (float(v), False)
        return dict(sorted(out.items(), key=lambda kv: kv[1][0]))

    @staticmethod
    def _section_title(from_name: str, to_name: str,
                       d_span: str, dep_win: str) -> str:
        """小节标题行（#### ✈️ 城市→城市 日期[时段窗]）：时段窗整行
        ≤40 内联、超宽下沉引用行（既有两分支）；标题本体曾无守卫——
        长自定义城市名双侧+日期跨度可破 40（推送审校 P3-1），本体
        超宽时日期段与时段段合并下沉同一条引用行（窄屏标题折行
        断点不受控，日期是跨天辨识信息不可丢）。"""
        head_txt = f"✈️ {from_name}→{to_name} {d_span}"
        if dep_win and _dw("#### " + head_txt + dep_win) <= 40:
            return f"#### {head_txt}{dep_win}\n\n"
        if _dw("#### " + head_txt) <= 40:
            sec = f"#### {head_txt}\n\n"
            if dep_win:
                sec += f"> {dep_win}\n\n"
            return sec
        sub = d_span + (dep_win or "")
        head = f"#### ✈️ {from_name}→{to_name}"
        if _dw(head) > 40:
            # 末档城市名本体超宽逐侧逐字截（审校 P2-2：长自定义名
            # 极端形态标题行 60/40 曾不受控）——两侧均分预算（6 半角
            # 地板防负），截尾不加省略号（U+2026 禁令），完整名见
            # 正文小节/控制台；日期/时段窗在引用行不受扰
            room = max(6, (40 - _dw("#### ✈️ →")) // 2)

            def _trim(nm):
                out, w = [], 0.0
                for ch in nm:
                    cw = _dw_raw(ch)
                    if w + cw > room:
                        break
                    out.append(ch)
                    w += cw
                # 剥未配对「（」（推送审校 P2-1）：逐字截可停在括号
                # 对中间产出「乌鲁木齐（地窝」半截括号——剥档判据计数
                # 式（开>闭即从末个开括号连残段剥，r250 P2-1r）：
                # 「末个（右侧有任一）即 break」在双层开括号名（北京
                # （首都（T3）区）形）跨「内闭外开」窗早停，外层开括
                # 号悬垂；现实单层形态平衡时循环体一次不进零回归
                while out.count("（") > out.count("）"):
                    del out[len(out) - 1 - out[::-1].index("（"):]
                return "".join(out)
            head = f"#### ✈️ {_trim(from_name)}→{_trim(to_name)}"
        return f"{head}\n\n> {sub}\n\n"

    @staticmethod
    def _legend_line() -> str:
        """头部图例行（两条 digest 链路共用，提取——两处各自
        拼接曾触发措辞分叉）：🎯 基座 + 档序与判定梯度同向（🟩破线→
        🟨擦边→超线），超宽从末段逐段丢（手机引用行 ~20 全角宽，
        钉钉折行断点不受控；日期不进图例——标题/小节已有）。
        基座压缩留缓冲：原「⏱ HH:MM 空」恰满 40 半角零
        缓冲，任何基座变化即静默丢末段——去 ⏱ 后空格得 39，留 1。
         换四档正名短词面：🎯真达标 + 超线=37/40，缓冲反增 2
        （「行情破线」全词 41/40 进不来；🟩破线在 🟩 语境无歧义）。"""
        leg = (f"> ⏱{datetime.now():%H:%M} "
               f"{TIER_EMOJI['qual']}{TIER_SHORT['qual']}")
        for _seg in (f" {TIER_EMOJI['mkt']}{TIER_SHORT['mkt']}",
                     f" {TIER_EMOJI['near']}{TIER_SHORT['near']}",
                     f" {TIER_SHORT['over']}"):
            if _dw(leg + _seg) <= 40:
                leg += _seg
        return leg

    @classmethod
    def _fmt_brief(cls, f: dict, budget: int = 40) -> str:
        """渠道速览单条（图挂时的文本兜底路径）：类别 + 航班 + 时刻；
        整行套 _fit_line 守卫（裸拼中转行可超 40 半角、钉钉窄屏
        折行断点不受控，收口）——降级链逐级剥停留/时刻保价格。
        价格不加粗：加粗=档位信号，兜底行情行非档位内容。
        budget=整行预算：消费点拼「- {渠道} 最低 」前缀后
        整行恒 44-48 超宽（守卫只对 brief 本体负责不知道前缀，图挂
        兜底轮 20/2546 行全超）——消费点按 40-前缀宽传入，默认 40
        保持无前缀调用点行为不变。地板档「￥价格」：超长航班名
        （双程「航司｜航司号」36+ 半角）连末档也超预算时保价格核心
        判据（「渠道+价格优先」同哲学）。价格词面 :.0f 单源自守
        （r242 Minor-1 家族收口）：float 价直达曾产「￥12345.0」且
        地板档超预算。"""
        cross = f.get("crossDayDesc") or ""
        arrive = f"{f['arrTime']}（{cross}达）" if cross else f"{f['arrTime']} 当日达"
        if cls._trans_city(f):
            via = cls._via_txt(f)
            lay = str(f.get("layoverT") or "").strip()
            if lay:
                via = f"{via} 停{lay}" if via else f"停{lay}"
            line = (f"￥{f['price']:.0f} 中转{f['name']} {via} "
                    f"{f['depTime']}→{arrive}").replace("  ", " ")
            return _fit_line(line, limit=budget, fallbacks=[
                # 中档剥 arrive 尾注（「 当日达」/「（cross达）」7 半角）：
                # 复用 arrive 曾令常规行恒 41/40 直落末档，兜底行时刻
                # 永远进不了文本（推送审校 P2-1）
                f"￥{f['price']:.0f} 中转{f['name']} {f['depTime']}→{f['arrTime']}",
                f"￥{f['price']:.0f} 中转{f['name']}",
                f"￥{f['price']:.0f}"])
        sc = str(f.get("stopCity") or "").strip()
        stop = (f"（经停{sc}）" if sc else "（经停）") \
            if f.get("stopover") else ""
        line = f"￥{f['price']:.0f} 直飞{f['name']}{stop} {f['depTime']}→{arrive}"
        return _fit_line(line, limit=budget, fallbacks=[
            f"￥{f['price']:.0f} 直飞{f['name']} {f['depTime']}→{f['arrTime']}",   # 中档剥尾注，同 P2-1
            f"￥{f['price']:.0f} 直飞{f['name']}",
            f"￥{f['price']:.0f}"])

    @staticmethod
    def _dep_in_window(dep: str, dmin: str, dmax: str) -> bool:
        """出发时刻窗口判定（HH:MM 钟面，空边界不限；不含跨零点窗口）。
        时刻用正则解析而非切片：DB 补位行可能带 "6:30" 未补零
        格式，切片 int("6:") 抛异常被吞按窗口内保留——而曲线侧（report
        _rounds 过滤前过 _pad_hhmm）正确剔除，同一班次「列表含、曲线
        不含」的图文分叉根因。"""
        if not dep:
            return not (dmin or dmax)
        # 跨零点窗口检测：dmin>dmax 的钟面窗口在本语义下恒
        # False（任一时刻要么 <dmin 要么 >dmax），整航线静默零数据——
        # 用户视角即「这条航线永远没数据」。每对窗口只告警一次
        if dmin and dmax and (dmin, dmax) not in _WIN_WARNED:
            try:
                if (int(dmin[:2]) * 60 + int(dmin[3:5])
                        > int(dmax[:2]) * 60 + int(dmax[3:5])):
                    _WIN_WARNED.add((dmin, dmax))
                    _LOG.warning("[配置] 出发窗口 %s-%s 跨零点，当前窗口"
                                 "语义恒为空（不支持跨零点），该航线将"
                                 "静默无数据——请改用同侧窗口",
                                 dmin, dmax)
            except (ValueError, IndexError):
                pass
        hm = _hhmm(dep)
        if hm is None:
            return True
        m = hm[0] * 60 + hm[1]
        if dmin:
            try:
                if m < int(dmin[:2]) * 60 + int(dmin[3:5]):
                    return False
            except (ValueError, IndexError):
                pass
        if dmax:
            try:
                if m > int(dmax[:2]) * 60 + int(dmax[3:5]):
                    return False
            except (ValueError, IndexError):
                pass
        return True

    @staticmethod
    def _arrival_ok(f: dict, deadline: str) -> bool:
        """中转到达约束：当日达，或次日 deadline 前到达。"""
        dep, arr, t = f.get("depDate", ""), f.get("arrDate", ""), f.get("arrTime", "")
        if dep and arr:
            try:
                d0 = datetime.strptime(dep, "%Y-%m-%d")
                d1 = datetime.strptime(arr, "%Y-%m-%d")
                if d1 == d0:
                    return True
                return d1 == d0 + timedelta(days=1) and bool(t) and t <= deadline
            except ValueError:
                pass
        cross = f.get("crossDayDesc", "")
        if cross == "":
            return True
        return cross == "+1天" and bool(t) and t <= deadline

    @classmethod
    def _propagate_layover(cls, flights: list) -> None:
        """同指纹衔接补全：同(出发,到达,经停)指纹的班次是同一物理
        衔接——任一渠道测得真实停留即补到缺行；多渠道值冲突（>15 分钟）
        视为数据错误不补（保守：宁缺勿错，禁止估算值入池）。
        指纹含 arrDate 但不含 crossDayDesc：首段出发+末段到达+城市+到达日
        已唯一定位一条链；只差 arrDate 则会撞链——同航班号两个物理链
        （当日达 vs +1天达）时钟时刻完全相同，缺到达日时 ctrip 的
        1520 分钟停留被补到 7 小时全程的当日链上（停留>全程，物理不可能）。
        跨天写法仍不可入指纹（渠道写法不一致：qunar '+1天' vs ctrip ''，
         上线以来一条未补过的根因），由 arrDate 承担跨天区分。"""
        from core.flightnorm import fmt_dur
        groups = {}
        for f in flights:
            if f.get("transCity"):
                key = (f.get("depDate"), f.get("depTime"),
                       f.get("arrTime"), f.get("transCity"), f.get("arrDate"))
                groups.setdefault(key, []).append(f)
        for rows in groups.values():
            vals = {r["layoverM"] for r in rows
                    if isinstance(r.get("layoverM"), int) and r["layoverM"] > 0}
            if len(vals) != 1:
                continue          # 无测得值或值冲突，都不补
            v = vals.pop()
            for r in rows:
                if isinstance(r.get("layoverM"), int) and r["layoverM"] > 0:
                    continue
                # 二次守卫：补全绕过了 normalize 的不可能值检查，
                # 停留 ≥ 全程、或两段合计飞行 < 60 分钟（停留无限逼近
                # 全程的擦边毒值）一律拒写
                dur = r.get("durM")
                if isinstance(dur, int) and dur > 0 and (
                        v >= dur or dur - v < 60):
                    continue
                r["layoverM"] = v
                r["layoverT"] = f"{v // 60}:{v % 60:02d}"

    @classmethod
    def _propagate_fields(cls, flights: list) -> None:
        """同指纹决策字段补全：
        cabin/meal/prate/plane 渠道间结构性缺失悬殊（实测近 48h——
        qunar DOM 兜底 cabin 缺 96%/prate 缺 100%、fliggy 舱位列表页
        结构性无源缺 100%，而它们常贡献全线最低价），同指纹(+航班号)
        =同一物理航班，组内恰好一个非空值才补、值冲突不补（宁缺勿错，
        与 _propagate_layover 同保守语义）。航班号入键防同刻度异航班
        张冠李戴；代码共享航班（营销号≠承运号）配不上属可接受漏。
        实测补全潜力：qunar 缺失行 cabin 74%/prate 70% 可补。"""
        groups = {}
        for f in flights:
            code = (f.get("code") or "").strip()
            if not code:
                continue
            key = (code, f.get("depDate"), f.get("depTime"),
                   f.get("arrTime"), f.get("arrDate"))
            groups.setdefault(key, []).append(f)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            # fewTicket 刻意不入列（审查后定论）：cabin/plane/
            # shareCarrier 是物理属性（同航班全渠道同值）可补；余票紧张
            # 是渠道本地库存语义，qunar「仅剩5张」安到携程行=误导半假数据。
            # planeSize（机型体量）/depAirport/arrAirport（机场
            # 定位）同为物理属性入列——qunar 中转行 arrAirport 仅中转有源
            # 、tuniu/ctrip/tongcheng 全量在场，跨渠道互补正合此机制。
            # depAirportCode/arrAirportCode（IATA 码）同物理属性
            # 入列——调研定证跨渠道 48 共同航班号 48/48 同码对，互补安全
            # bizPrice 五渠道全有源（qunar extparams/tuniu 高档舱政策
            # /tongcheng pts/fliggy 双价行高档舱词/ctrip policyinfo
            # 高档舱政策——首元素 cgrd∈{1,2} 取最低 tprice；早前
            # 「psprices 恒 [] 无源」备案经 policyinfo 新证据推翻。
            # fliggy 补全列不含 bizPrice：双价行非全渠道
            # 同现形态，跨渠道补全不适用）
            # airlineCode（航司二字码）/distance（航程公里）/
            # shareAirline（共享承运航司名）同为物理属性入列——
            # 同一物理航班全渠道同值，跨渠道互补正合此机制；
            # stdFare（公布运价）是报价属性不补（同 fewTicket 语义族）
            # depTerminal/arrTerminal（航站楼）同物理属性入列——
            # 机场定位的细化（T1/T2/T3，同城多场决策信息）；
            # tuniu dTerminal 间歇下发（有值才落键），低出勤正靠
            # 此机制跨渠道互补
            for field in ("cabin", "meal", "prate", "plane", "shareCarrier",
                          "planeSize", "depAirport", "arrAirport",
                          "depAirportCode", "arrAirportCode",
                          "airlineCode", "distance", "shareAirline",
                          "depTerminal", "arrTerminal"):
                if field == "cabin":
                    # 补全源过清污门（cabin_clean 单源）：渠道会把低价
                    # 政策标成高档舱名（tuniu 在案），这种价位矛盾行不
                    # 得作补全源——被传染行常无 bizPrice，渲染门「不可
                    # 内证」放行即假高档词上推送；真高档选中行恒
                    # price==bizPrice 不受影响
                    vals = {cabin_clean(r) for r in rows if r.get("cabin")}
                    vals.discard("")
                else:
                    vals = {r[field] for r in rows if r.get(field)}
                if len(vals) != 1:
                    # airlineCode 值冲突 DEBUG 留痕（派生值入补全源后
                    # codeshare 分歧面变化——fliggy code[:2] 派生 vs
                    # tongcheng/tuniu 原生源；行为保守跳过不变，分歧
                    # 频率与形态靠此观测，实证后再议排除派生源）
                    if field == "airlineCode" and len(vals) > 1:
                        _LOG.debug("[补全] airlineCode 值冲突跳过 %s: %s",
                                   sorted({r.get("code") or "" for r in rows}),
                                   sorted(vals))
                    continue          # 无测得值或值冲突，都不补
                v = vals.pop()
                for r in rows:
                    if not r.get(field):
                        # shareAirline/shareCarrier 补全环内互斥（审查
                        # P2-3）：非共享行的段承运名（「南航|东航」）补到
                        # 共享行会与其 shareCarrier 拼出
                        # 「共享·南航|东航川航3U1599」混淆词——收方已有
                        # 对应键即不补（渲染门只防同源两键同屏，
                        # 防不了补全后共存）
                        if (field == "shareAirline" and r.get("shareCarrier")) \
                                or (field == "shareCarrier"
                                    and r.get("shareAirline")):
                            continue
                        r[field] = v

    @classmethod
    def _transfer_ok(cls, f: dict, route) -> bool:
        """中转合法性统一判定：到达约束 + 最短衔接时长 + 两段免费托运。

        route 兼容 Route 对象与 dict 配置。三个维度：
        ① 到达时刻约束（_arrival_ok）；
        ② 衔接时长 ≥ transfer_layover_min 分钟（0=不限）——托运行李需
           重新值机时 90 分钟起步，数据取 flightnorm 规范的 layoverM；
        ③ transfer_baggage="direct" 时仅认两段均含免费托运的班次——
           以渠道「中转行李免提」联程标签为准（联程产品两段直挂），
           未标注的班次按不满足处理（保守：需托运的人只信明确标注）。
        layoverM/transferBaggage 缺失时按不满足处理——「未知 ≠ 适合」，
        宁可漏掉不虚报（与实现语义对齐）。"""
        def _rk(key, default):
            if isinstance(route, dict):
                return route.get(key, default)
            return getattr(route, key, default)

        if not cls._arrival_ok(f, _rk("transfer_arrival_max", "02:00")):
            return False
        lay_min = int(_rk("transfer_layover_min", 0) or 0)
        if lay_min > 0:
            lm = f.get("layoverM")
            if not isinstance(lm, int) or lm <= 0 or lm < lay_min:
                return False
        if _rk("transfer_baggage", "") == "direct" \
                and f.get("transferBaggage") != "direct":
            return False
        return True

    def _category_alert(self, route: Route, date: str, f: dict, category: str,
                        threshold: float, pool_size: int, src_platform: str,
                        pool: Optional[list] = None):
        price = float(f["price"])
        # 阈值判定用达标口径价（飞猪税垫）；展示/去抖仍记录页面价
        eff = _qual_price(f)
        label = "直飞" if category == "direct" else "中转"
        route_key = f"{self.user}|{route.from_code}-{route.to_code}-{date}-{category}"
        if not isinstance(eff, (int, float)) or eff > threshold:
            if self.storage:
                self.storage.clear_alert_state(route_key)
            return
        last = self.storage.get_alert_state(route_key) if self.storage else None
        should_push, reason = self._should_push(eff, last)
        self.logger.warning(
            "[低价-%s] %s->%s %s ￥%.0f %s（阈值￥%.0f, 上次推送￥%s）-> %s",
            label, route.from_name, route.to_name, date, price,
            f["name"], threshold, f"{last:.0f}" if last else "-",
            "推送" if should_push else f"跳过({reason})",
        )
        if should_push and self.notifier:
            ok = self._push_flight(route, date, f, category, threshold,
                                   last, pool_size, src_platform, pool=pool)
            if ok and self.storage:
                # 去抖基准与判定同口径存 eff：曾存页面价，飞猪税垫差
                # 恒被 `_should_push` 视作「涨 ￥100」幻影重推
                # （push_rise_min=50 必触发）；pad 常量时 eff 差=页面价差，
                # _push_flight 涨跌文案不失真
                self.storage.set_alert_state(route_key, eff)

    def _push_flight(self, route: Route, date: str, f: dict, category: str,
                     threshold: float, last: Optional[float], pool_size: int,
                     src_platform: str, pool: Optional[list] = None) -> bool:
        label = "直飞" if category == "direct" else "中转"
        cross = f.get("crossDayDesc", "")
        arrive_txt = f"{f['depTime']} → {f['arrTime']}"
        if cross:
            arrive_txt += f"（{cross}到达）"
        emoji = "✈️"
        diff_txt = ""
        if last is not None:
            # 涨跌差同口径（eff-eff）：pad 为常量时与页面价差相等
            diff = _qual_price(f) - last
            emoji = "📉" if diff <= 0 else "📈"
            diff_txt = (f"（较上次推送降 ￥{-diff:.0f}）" if diff <= 0
                        else f"（较上次推送涨 ￥{diff:.0f}）")

        title = (f"{emoji} {label}低价 {route.from_name}→{route.to_name} "
                 f"{date} ￥{f['price']:.0f}{diff_txt} {f['name']}")

        # 链接渠道同价优选（qunar→ctrip）：池由调用点传入（同轮全航班）；
        # 无池时退化为原渠道——落点价与文案价一致，不挂羊头。
        # desp 段落级 \n\n：PC 端不认单 \n 会把相邻行粘成一行长文
        # （digest=false 遗留路径同样守渲染律）
        plat = (self._pref_platform(f, pool)
                if pool else (f.get("_platform") or src_platform))
        view_url = self._build_view_url(route, date, plat)
        desp = (
            f"#### 机票低价提醒（{label}）\n\n"
            f"- **航线**：{route.from_name}（{route.from_code}） → "
            f"{route.to_name}（{route.to_code}）\n\n"
            f"- **日期**：{date}\n\n"
            f"- **航班**：{f['name']}\n\n"
            f"- **起降**：{arrive_txt}\n\n"
        )
        if self._trans_city(f):
            # 「经哪+停多久」是达标判据：配对门走 _trans_city 单源
            # （占位行走经停词面时停留同取 stopTimeT，审查 P2-2）；
            # 全程时长缺省整段省略（不直出 ?）
            via = self._via_txt(f)
            lay = str((f.get("layoverT") if self._trans_city(f)
                       else f.get("stopTimeT")) or "").strip()
            if lay:
                via = f"{via} 停{lay}" if via else f"停{lay}"
            dur = str(f.get("totalDuration") or "").strip()
            desp += (f"- **中转**：{via}"
                     + (f"（全程{dur}）" if dur else "") + "\n\n")
        # 价格值不加粗：加粗=档位信号，旧路径无档位点，
        # 粗价格稀释扫读梯度；:.0f 与全库价格格式统一。
        # 价格行走 _fit_line（审校 P2-3）：去抖涨跌注在场曾 47/40
        # （全链唯一没走守卫的动态行）；降级链尾地板档=裸价格判据
        # （守卫链尾恒达标律）
        _pbase = f"**价格**：￥{f['price']:.0f}（线￥{threshold:.0f}）"
        desp += (
            _fit_line(f"- {_pbase}{diff_txt}",
                      fallbacks=[f"- {_pbase}",
                                 f"- ￥{f['price']:.0f}"]) + "\n\n"
            f"- **在售班次**：{pool_size}\n\n"
            f"- **抓取时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        )
        # 未知平台 _build_view_url 返回空：跳过链接行（不给空壳坏链）
        if view_url:
            desp += (f"[👉 在{self.PLATFORM_CN.get(plat, plat)}"
                     f"查看详情]({view_url})\n\n")
        return self.notifier.send(sanitize_desp(title), sanitize_desp(desp))

    def _push(self, route: Route, date: str, p: FlightPrice,
              last: Optional[float]) -> bool:
        diff_txt = ""
        emoji = "✈️"
        if last is not None:
            diff = p.price - last
            if diff <= 0:
                emoji = "📉"
                diff_txt = f"（较上次降 ￥{-diff:.0f}）"
            else:
                emoji = "📈"
                diff_txt = f"（较上次涨 ￥{diff:.0f}）"

        title = (f"{emoji} {route.from_name}→{route.to_name} {date} "
                 f"￥{p.price:.0f}{diff_txt}")

        # markdown 详细（段落级 \n\n：PC 渲染律同上）
        view_url = self._build_view_url(route, date, p.platform)
        desp = (
            f"#### 机票低价提醒\n\n"
            f"- **航线**：{route.from_name}（{route.from_code}） → "
            f"{route.to_name}（{route.to_code}）\n\n"
            f"- **日期**：{date}\n\n"
            f"- **当前最低价**：￥{p.price:.0f}\n\n"
            f"- **设定阈值**：￥{route.alert_threshold:.0f}\n\n"
            f"- **来源**：{self.PLATFORM_CN.get(p.platform, p.platform)}\n\n"
            f"- **抓取时间**：{p.fetched_at}\n\n"
        )
        if last is not None:
            desp += f"- **上次推送价**：￥{last:.0f}\n\n"
        # 未知平台 _build_view_url 返回空：跳过链接行（不给空壳坏链）
        if view_url:
            desp += (f"[👉 在{self.PLATFORM_CN.get(p.platform, p.platform)}"
                     f"查看详情]({view_url})\n\n")
        return self.notifier.send(sanitize_desp(title), sanitize_desp(desp))

    def _build_view_url(self, route: Route, date: str, platform: str) -> str:
        """用户侧「查看详情」跳转链接——与各渠道爬虫已验证主路径同源。
        链接是给人点的，页面必须真的出数据：主路径在 PC↔H5 间任一
        向摆动都要复核链接指向（只按正向执行过会漏反向回退面）。
        qunar 现指 PC 列表页：爬虫侧接口层对无头指纹软拒（code:-1
        空壳、每轮回落 H5 兜底出数），但页面壳对真人浏览器在线（外网
        复核 HTTP 200 正常体量），真人列表由站点自身 JS 调接口出数，
        维持不切；软拒转持久（页面壳也死）再评估切 H5。"""
        from urllib.parse import quote as _q
        # 城市名归一：曾直用 route 原文——用户非规范写法时
        # 用户搜索词 ≠ 爬虫搜索词（爬虫侧统一 CITY_NAME.get(code)），
        # 页面行情与推送价有差=所见非所点。三字码统一大写（爬虫全
        # .upper()，config 小写码曾失配）
        try:
            from crawlers.qunar import QunarCrawler as _QC
            fn = _QC.CITY_NAME.get(
                route.from_code.upper(), route.from_name)
            tn = _QC.CITY_NAME.get(route.to_code.upper(), route.to_name)
        except Exception:
            fn, tn = route.from_name, route.to_name
        fn, tn = _q(fn), _q(tn)
        fc_up, tc_up = route.from_code.upper(), route.to_code.upper()
        if platform == "ctrip":
            # 与 crawlers/ctrip.py URL_TPL 同参：缺 dcityName/acityName 时
            # taro 页需按三字码反查，渠道改版即空列表（同型事故预防）
            return (
                "https://m.ctrip.com/html5/flight/taro/first?from=inner"
                "&tripType=ONE_WAY"
                f"&dcity={fc_up}&dcityName={fn}"
                f"&acity={tc_up}&acityName={tn}&ddate={date}"
            )
        if platform == "tongcheng":
            # 与 crawlers/tongcheng.py URL_TPL 同参：book1 页缺中文城市名
            # 参数（fromCity/toCity/acn/dcn）时曾不出列表——挂羊头预防
            return (
                "https://m.ly.com/ft/touch/book1"
                f"?date={date}&childticket=0,0&an=1&cn=0&baby=0"
                f"&fromCity={fn}&toCity={tn}"
                f"&fromcitycode={fc_up}&fromCode={fc_up}"
                f"&tocitycode={tc_up}&toCode={tc_up}"
                f"&acn={tn}&dcn={fn}"
                "&refId=&cabin=0&platcode=518&direct=0&thirdMemberId="
                "&fPassType=&nametype=0,0&frompage=HOME&outrefid="
            )
        if platform == "qunar":
            # PC 版单程列表（crawlers/qunar.py PC_URL_TPL 同源——
            # wbdflightlist 主路径已实测出全量明细；touch H5 接口已
            # 风控死）。爬虫侧 PC 软拒时每轮回落 H5 兜底出数，但真人
            # 浏览器页面壳在线（docstring 复核备案），链接维持 PC 页；
            # 切 H5 前须先复核 H5 页壳对真人在线（H5 接口死≠页壳死）
            return (
                "https://flight.qunar.com/site/oneway_list.htm?"
                f"searchDepartureAirport={fn}&searchArrivalAirport={tn}"
                f"&searchDepartureTime={date}&nextNDays=0&startSearch=true"
                f"&fromCode={fc_up}&toCode={tc_up}"
                "&from=flight_dom_search"
            )
        if platform == "tuniu":
            return (
                "https://m.tuniu.com/flight/domestic/new/"
                f"{fc_up}_{tc_up}_OW_1_0_0"
                f"?deptDate={date}&isGo=0"
            )
        if platform == "fliggy":
            # fliggy：PC SSR 列表页（crawlers/fliggy.py URL_TPL 同源——
            # 渠道本体就是 PC 直读；原 H5 outfliggys 为旧入口）
            return (
                "https://sjipiao.fliggy.com/flight_search_result.htm"
                "?tripType=0"
                f"&depCity={fc_up}&arrCity={tc_up}"
                f"&depDate={date}&depCityName={fn}&arrCityName={tn}"
            )
        # 未知平台不再静默落飞猪 URL（链接落点与文案渠道一致，挂羊头
        # 曾让「在途牛查看」点开飞猪）：宁缺链接勿给错链，调用方对
        # 空 URL 跳过链接只出纯文本
        return ""


def _ensure_jump_link(desp: str, route, section: dict,
                      platforms=None) -> str:
    """全消息无任何可点链接时（无 KPI/图表数据轮）兜底一个查价入口。
    判定前先剥 ![..](..) 图片 markdown：走势图链曾被误当可点链接
    而跳过兜底（图片在推送里不是给人点的东西）。兜底落点走同价优选
    （与消息内其它链接同口径，曾硬编码 qunar——对未启用去哪儿的
    用户是挂羊头）；优选无据时退用户启用平台首位。
    模块级单源（r257-P3-2）：告警链 Alerter._ensure_jump_link 与日报
    build_and_push 同源消费，能力对称让单源免费。"""
    import re as _re
    desp_txt = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "", desp)
    if "](http" in desp_txt:
        return desp
    best = (section.get("best_direct")
            or section.get("best_transfer_mkt")
            or section.get("best_transfer"))
    plat = (Alerter._pref_platform(best,
                                   section.get("all_flights") or [best])
            if best else (platforms or [""])[0])
    url = Alerter._build_view_url(None, route,
                                  section.get("date") or "", plat)
    if not url:
        return desp
    # 文案带平台名：优选落点非 qunar 时「打开渠道
    # 查价」曾让读者猜是哪家的链接。
    # 前置剥尾换行：desp 尾 \n\n 后再拼 \n 产三连换行
    # （钉钉折叠为空白段）
    cn = Alerter.PLATFORM_CN.get(plat, plat)
    return desp.rstrip("\n") + f"\n\n[→ 打开{cn}查价]({url})\n\n"
