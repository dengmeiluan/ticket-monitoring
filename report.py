# -*- coding: utf-8 -*-
"""价格走势：prices.db 回算分类最低价序列 → Pillow 画 PNG → 图床上传 → 钉钉图文

用法:
    python main.py --report # 立即生成并推送（无 token 则只存本地 PNG）
    每日 report_hour 定时推送（main job 末尾调用 maybe_daily_report）
"""
import base64
import json
import logging
import math
import os
import re
import sqlite3
from datetime import datetime

import httpx
from PIL import Image, ImageDraw, ImageFont

from core.alerter import (Alerter, _cabin_cn, _qual_price, FLIGGY_TAX_PAD,
                          _fit_line, _dw as _dw_line, xchan_phantom_idx,
                          NEAR_RATIO, CANCEL_RATE_ALERT, gap_txt, kpi_tier_txt,
                          TIER_FULL)
from core.models import PRICE_MAX, PRICE_MIN
from core.flightnorm import normalize, discount_txt

# 仓库根锚定（CWD 漂移免疫家族）：config 相对路径与状态文件的
# 兜底值曾按进程 CWD 解析——计划任务/手动启动 CWD 不同=另起新库/日报
# 防重发状态失效同文重推
_ROOT = os.path.dirname(os.path.abspath(__file__))


def _anchored_db(cfg):
    """cfg.output.db_path 锚定仓库根（相对值兜底 data/prices.db）。"""
    p = str((cfg.get("output") or {}).get("db_path")
            or "data/prices.db").strip()
    return p if os.path.isabs(p) else os.path.join(_ROOT, p)


def _pad_hhmm(t) -> str:
    """渠道时刻补零（"9:30"→"09:30"），供窗口判定用；解析失败原样。"""
    m = re.match(r"^(\d{1,2}):(\d{2})", str(t or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else str(t or "").strip()

# ---- 画图 ----
# 色板与 webui PAGE :root 同值（跨端同一色系：推送图与控制台同源质感）
W, H = 936, 460
PAD_L, PAD_R, PAD_T, PAD_B = 80, 30, 64, 60
C_DIRECT = (11, 98, 214)      # 直飞 蓝（--blue #0b62d6）
C_TRANSFER = (201, 106, 16)   # 中转 橙（--orange #c96a10）
C_TRANSFER_TX = (166, 84, 8)  # 中转 文字 深橙（#a65408，push P2-1）：
                              # C_TRANSFER 对浅橙胶囊底 3.47:1 欠 AA、全图
                              # 最低文本对——文字面换深橙 4.95:1；色条/描边
                              # 等图形消费保持 C_TRANSFER 本体（图形 3.78:1
                              # 合格，且与 webui --orange 同值纪律不破）
C_TH = (194, 42, 46)          # 直飞达标线 红（--red #c22a2e）
C_TH_T = (138, 109, 31)       # 中转达标线 棕金（--thline #8a6d1f 同值）：
                              # 两线同红曾只能靠右缘文字区分（webui 侧
                              # 红金双色早已分档，对齐同语言）
C_GRID = (225, 228, 232)
C_TEXT = (60, 64, 70)

# 擦边带宽 NEAR_RATIO 已收口 core.alerter 单源（本文件本地
# 定义曾与 alerter/webui 各写一份）。webui 前端 JS ×1.1 无法 import，
# 靠 webui TIER/fl 两处同步律注释。

_FONTS = {}


class _ScaledDraw:
    """2x 超采样代理：包装 ImageDraw，坐标与半径自动乘 S；文字字体由
    调用方用放大字号传入，textlength 返回放大值保证定位计算自洽。"""
    def __init__(self, draw, s):
        self._d, self.s = draw, s

    def _pts(self, pts):
        pts = list(pts)
        # 兼容 PIL 两种形式：[(x,y),...] 点对 与 [x0,y0,x1,y1] 扁平
        if len(pts) == 4 and all(isinstance(v, (int, float)) for v in pts):
            return [v * self.s for v in pts]
        return [(x * self.s, y * self.s) for x, y in pts]

    def text(self, xy, t, **k):
        x, y = xy
        self._d.text((x * self.s, y * self.s), t, **k)

    def textlength(self, t, font=None):
        # 传入的 font 已是放大字体，返回逻辑域宽度供布局计算（与坐标同域）
        v = self._d.textlength(t, font=font)
        return v / self.s if font else v

    def line(self, pts, **k):
        self._d.line(self._pts(pts), **k)

    def rectangle(self, pts, **k):
        self._d.rectangle(self._pts(pts), **k)

    def rounded_rectangle(self, pts, radius=0, **k):
        self._d.rounded_rectangle(self._pts(pts), radius=radius * self.s, **k)

    def ellipse(self, pts, **k):
        self._d.ellipse(self._pts(pts), **k)

    def polygon(self, pts, **k):
        self._d.polygon(self._pts(pts), **k)

    def point(self, pts, **k):
        self._d.point(self._pts(pts), **k)

    def font(self, n, bold=False):
        """逻辑域字号取字体：n 为最终视觉字号（此处统一乘 S 放大），
        bold=True 取粗体——外部直取 _font_bold(物理字号) 会漏乘 S
        （「可省」曾因此视觉缩半成 11px，根治）。"""
        return _font_bold(n * self.s) if bold else _font(n * self.s)


def _font_bold(size):
    key = ("bold", size)
    if key not in _FONTS:
        try:
            _FONTS[key] = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", size)
        except Exception:
            _FONTS[key] = _font(size)
    return _FONTS[key]


def _font(size):
    key = ("ui", size)
    if key not in _FONTS:
        for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
            try:
                _FONTS[key] = ImageFont.truetype(p, size)
                break
            except Exception:
                continue
        else:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def _rounds(db_path, from_city, to_city, date, arrival_max, hours=48,
            layover_min=0, dep_win=None, rc=None, th_d=0.0, th_t=0.0):
    """按轮次聚类（平台时间戳相近算同一轮），回算 直飞/达标中转 最低价序列。

    仅取最近 hours 小时，防止长期运行后图表过密。layover_min：中转衔接
    时长下限。extra 是爬虫原始输出（layover/transitServiceLabel 未归一化），
    必须先 normalize 再按与达标推送同口径过滤，否则 layoverM 恒缺、
    中转序列恒空（根治「中转走势线消失」）。行李直挂约束不参与
    曲线取值：transferBaggage 标签渠道覆盖极低且历史数据查不到，会画出
    长段空窗——直挂仅用于达标推送与明细表。

    dep_win=(dmin,dmax)：出发时刻窗口——列表/达标链已整体剔除窗口外
    班次，曲线不同窗则图上最低点可来自已剔除班次（曲线与列表含义
    不一致的最大实例），必须与 alerter._dep_in_window 同参同过滤。

    返回 (ts, d, t, qd, qt)：qd/qt 为该轮最低点的达标口径旗标
    （价 ≤ 阈值 且 飞猪税垫修正 且 中转 _transfer_ok 全口径）——
    走势绿环据此只标「真达标」点，行情破线未达标点画描绿环区分
    （与明细表「价格绿=达标」同一语义，口径收口）。
    th_d/th_t 未传时旗标恒 False（仅旧式取值方使用，无环渲染）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, extra, fetched_at FROM flight_prices "
        "WHERE from_city=? AND to_city=? AND depart_date=? AND extra != '' "
        "AND fetched_at >= datetime('now', 'localtime', ?) "
        "ORDER BY fetched_at",
        (from_city, to_city, date, f"-{int(hours)} hours")).fetchall()
    conn.close()
    buckets = []  # [[ts, directs[(price, platform)], transfers_raw[(row, price, platform)]]]
    for r in rows:
        try:
            ts = datetime.strptime(r["fetched_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        try:
            obj = json.loads(r["extra"])
        except Exception:
            continue
        if not isinstance(obj, list):
            continue
        if buckets and (ts - buckets[-1][0]).total_seconds() <= 420:
            b = buckets[-1]
        else:
            b = [ts, [], []]
            buckets.append(b)
        for f in obj:
            if not isinstance(f, dict) or "price" not in f:
                continue
            try:
                p = round(float(f["price"]))
            except (TypeError, ValueError):
                continue
            # 价格带与爬虫端同带（PRICE_MIN–PRICE_MAX 单源，——
            # 曲线侧曾独用 300 下界而列表无下界，100–299 真实低价
            # 「列表可见、图上不可见」恰是曲线-列表含义一致的破口）：
            # 单靠爬虫端过滤不够，任何漏网毒行（0 价/异常值）直入
            # 曲线/日历口径
            if not PRICE_MIN <= p <= PRICE_MAX:
                continue
            if dep_win and not Alerter._dep_in_window(
                    _pad_hhmm(f.get("depTime")), dep_win[0], dep_win[1]):
                continue
            if f.get("transCity"):
                normalize(f, date)
                # 到达约束不在此滤（与列表链同序）：幻影锚池判定
                # 必须先于到达/衔接过滤——先滤后判曾让同一毒行列表侧拉低
                # 锚中位、曲线侧反被排除抬锚多判（两端同轮两价两档）
                b[2].append((f, p, r["platform"]))
            else:
                b[1].append((p, r["platform"]))
    rc_full = {
        "transfer_arrival_max": arrival_max,
        "transfer_layover_min": layover_min,
        "transfer_baggage": (rc or {}).get("transfer_baggage", ""),
    }
    series = []
    for ts, ds, tsf in buckets:
        d = t = None
        qd = qt = False
        # 跨渠道孤低价守卫（与告警池同一 xchan_phantom_idx）：
        # 幻影轮最低点曾把 y 轴压到地板（￥700 vs 群 2500+）全线失真，
        # 且曲线点永被日历/日报 KPI 复用——曲线与列表必须同一可信口径
        ds = [x for i, x in enumerate(ds)
              if i not in xchan_phantom_idx(
                  [(p + (FLIGGY_TAX_PAD if pl == "fliggy" else 0), pl)
                   for p, pl in ds])]
        if ds:
            drow = min(ds, key=lambda x: x[0])
            d = drow[0]
            qd = bool(th_d and d + (FLIGGY_TAX_PAD if drow[1] == "fliggy"
                                    else 0) <= th_d)
        if tsf:
            # 同指纹衔接补全先于一切过滤（桶内就地）：与明细表/
            # 推送池同预处理——qunar 中转行 90% 缺停留时长，不补全则被
            # layover_min 整行剔除、曲线比列表偏高（实锤同轮 2164 vs
            # 2190 两价的曲线侧残留病灶）
            Alerter._propagate_layover([f for f, _p, _pl in tsf])
            # 幻影锚池判定先于到达/衔接过滤（与列表链 alerter
            # 「先 _mark_xchan 后过滤」同序）：曾对过滤后残池判幻影，
            # 同一毒行列表侧拉低锚中位、曲线侧反被排除抬锚多判
            _no_x = [x for i, x in enumerate(tsf)
                     if i not in xchan_phantom_idx(
                         [(p + (FLIGGY_TAX_PAD if pl == "fliggy" else 0), pl)
                          for _f, p, pl in tsf])]
            # 到达 + 衔接过滤（与列表 top_transfers 同参同序）
            ok_t = [(f, p, pl) for f, p, pl in _no_x
                    if Alerter._arrival_ok(f, arrival_max)
                    and (layover_min <= 0
                         or (isinstance(f.get("layoverM"), int)
                             and f["layoverM"] >= layover_min))]
            if ok_t:
                trow = min(ok_t, key=lambda x: x[1])
                t = trow[1]
                qt = bool(th_t and t + (FLIGGY_TAX_PAD if trow[2] == "fliggy"
                                        else 0) <= th_t
                          and Alerter._transfer_ok(trow[0], rc_full))
        if d is not None or t is not None:
            series.append((ts, d, t, qd, qt))
    return series


def _daily_minima(db_path, from_city, to_city, date, arrival_max, days=14,
                  layover_min=0, dep_win=None, th_d=0.0):
    """价格日历：近 days 天逐日直飞最低价 [("MM-DD", 价, 档), ...]（升序）。

    档位与 webui _pts/renderCal 解码同语言：2=真达标（价 ≤ 阈值 且
    飞猪税垫修正，与明细 🔥/推送 🎯 同口径）、1=行情破线未达标、
    -1=擦边（线 < 价 ≤ 线×(1+NEAR_RATIO)，补档——与走势环/表格图三档
    同语言，日历必须有擦边档）、0=线外。只发 {0,1} 布尔旗标而
    消费端按三档解码会让日历上「真达标」永不出现、达标日反被标
    「行情破线，未必可出手」——三档必须齐发。数据窗口受存储清理限制（14 天）。
    纯展示函数，任何坏数据都只导致少点不导致异常。"""
    out = {}
    try:
        hist = _rounds(db_path, from_city, to_city, date, arrival_max,
                       hours=days * 24, layover_min=layover_min,
                       dep_win=dep_win, th_d=th_d)
    except Exception:
        return []
    for t, d, _x, qd, *_r in hist:
        if not d:
            continue
        k = t.strftime("%m-%d")
        cur = out.get(k)
        if cur is None or d < cur[0]:
            out[k] = (d, _tier_of(d, th_d, qd))
    return sorted((k, round(v), int(q)) for k, (v, q) in out.items())


def _tier_of(price: float, th: float, qual: bool) -> int:
    """档位结构单源（Python 侧）：2=真达标 / 1=行情破线 / -1=擦边 /
    0=超线。日历(_daily_minima)/价格色(_price_color)/破线空心
    (_price_hollow) 曾各自重演同一结构，加档必漏其一——擦边下界
    严格 >th（与 webui near 同式）。webui TIER JS 为第 3 份（前端
    侧，有同步律注释管着）。"""
    if qual:
        return 2
    if th and price <= th:
        return 1
    if th and th < price <= th * (1 + NEAR_RATIO):
        return -1
    return 0


# ---- 明细表（钉钉 markdown 不支持表格，渲染 PNG 直推） ----
# 列和 912 + 24 内边距 = TBL_W 936，与走势图 W=936 对齐（两图同宽不跳变；
# 航班列加宽 16 后表格 936、走势仍 920 曾破同宽不变量，
# 走势侧跟齐）。：全程列 78→88——「13时40分」5 字形态在 78px
# 列实测 66px 超 64px 可用宽、几乎每行触发降号（15→14/13px 与同行
# 微差），航班列让 10px 找平
TBL_COLS = [("类别", 62), ("航班", 238), ("出发", 60), ("到达", 100),
            ("中转", 124), ("全程", 88), ("渠道", 120), ("价格", 120)]
TBL_W = sum(w for _, w in TBL_COLS) + 24
# C_HEAD_BG/C_ROW_ALT 死令牌已删（收敛）：值是 色值对齐
# 前漂移的旧值（与 DESIGN.HEAD_BG/ROW_ALT 各差一档），引用处统一 DESIGN.*
# ——与 webui --headbg/--rowalt 同源，令牌单一事实
C_QUAL = (14, 131, 69)         # 达标=可出手 绿（与网页 --green 同值；红会
                               # 与达标行浅绿底语义打架，故网页侧定绿）
C_NEAR = (138, 108, 0)         # 擦边=价距线≤10% 琥珀（走势环/表格图价格/日历
                               # 三媒质同值同义；与衔接警示分色 ——原
                               # 与 LAY_SHORT 同值两义，同图琥珀只表擦边）。
                               # 加深 (176,137,0)→(154,120,0)：
                               # 白底对比 3.3:1→4.2:1；再加深
                               # →(138,108,0)：白卡 4.97:1、斑马行 4.65:1
                               # 过 AA（webui --warn #8a6c00 成对改值，
                               # 暗色 #d9b34a 不动）
C_CMP = (194, 42, 46)          # 比价「差」=跨渠道价差警示 红（--red 同值）
C_SAVE = C_QUAL                # 比价「可省」=正向 绿（省=好事，与达标绿同族；
                               # 曾随组头沿用警示红——红=警示、绿=正向，
                               # 语义分档互斥，收口）

class DESIGN:
    """设计令牌（单一事实源）：与 webui PAGE 的 CSS 变量同值同注释。
    改设计两处同步——report.py 本文件 + webui.py 的 <style> 变量。
     起色值实测对齐 :root（同值以实测对齐为准、不得只做声称：
    BG/蓝/红/橙/MUTED 四处是偏差风险点）。"""
    BG = (236, 239, 244)            # 画布底（--bg #eceff4）
    CARD = (255, 255, 255)          # 白卡
    CARD_LINE = (203, 212, 222)     # 卡片描边（--line2 #cbd4de）
    HEAD_BG = (238, 242, 247)       # 表头底（--headbg #eef2f7）
    HEAD_TX = (44, 56, 72)          # 表头字
    HEAD_LINE = (196, 206, 220)     # 表头底线
    ROW_ALT = (245, 248, 251)       # 斑马纹（--rowalt #f5f8fb）
    HAIRLINE = (238, 241, 245)      # 行分隔
    SUMMARY_BG = (247, 248, 250)    # 摘要条底
    SUMMARY_LINE = (232, 236, 241)  # 摘要条描边
    SUMMARY_TX = (70, 78, 90)       # 摘要/次级正文
    MUTED = (97, 115, 132)          # 弱化（--mut #617384）——白卡上 4.5:1
    CAP_DIRECT_BG = (234, 242, 252) # 直飞胶囊浅底
    CAP_TRANSFER_BG = (253, 244, 232)  # 中转胶囊浅底
    PRICE_PLAIN = (20, 70, 160)     # 非达标价格深蓝
    LAY_SHORT = (192, 86, 26)       # 衔接偏短警示 暗橙红（原 (176,137,0)
                                    # 与擦边琥珀同色两义，分色；webui
                                    # --stl 同步改值——两处同值同注释纪律）
    CHAIN_TX = (64, 76, 92)         # 比价渠道链
    TIP_LINE = (214, 222, 232)      # 空态卡/提示框描边（收编：曾
                                    # 3 处裸值两套灰 (226,230,235)/
                                    # (214,222,232) 各自散落）


def _tbl_align(name, x, w, text_w):
    """表格列对齐基调：时刻/全程窄列居中，价格右对齐，其余居左——
    表头与数据同向，全表左右轴对称协调。"""
    if name in ("出发", "到达", "全程", "中转"):
        return x + max(4, (w - text_w) // 2)
    if name == "价格":
        return x + w - 10 - text_w
    return x + 10


def _fit_text(d, text, x, y, max_w, base=15, fill=C_TEXT, min_size=11,
              anchor="la"):
    """列内自适应绘制：超宽先降字号，仍超则截断加省略号（防叠字）。
    anchor 直传 PIL（起行内元素统一 "lm" 锚行中线）。"""
    txt = str(text)
    # 代理 textlength 已返回逻辑域宽（物理/S），max_w 保持逻辑域直接比较；
    # 若在此再乘 S，判定恒过→长名永不截断、溢出列界（复现实锤）
    get_font = getattr(d, "font", None) or _font
    for size in range(base, min_size - 1, -1):
        font = get_font(size)
        if d.textlength(txt, font=font) <= max_w:
            d.text((x, y), txt, font=font, fill=fill, anchor=anchor)
            return
    font = get_font(min_size)
    while txt and d.textlength(txt + "…", font=font) > max_w:
        txt = txt[:-1]
    d.text((x, y), txt + ("…" if txt else ""), font=font, fill=fill,
           anchor=anchor)


PLAT_DOT = {"qunar": (26, 115, 232), "fliggy": (230, 126, 34),
            "ctrip": (46, 164, 79), "tongcheng": (130, 80, 223),
            "tuniu": (210, 153, 34)}
# 箭头区（←-⇿ U+2190-21FF、⬀-⯿ U+2B00-2BFF）不剥：箭头是正文字符非
# emoji（msyh 有字形），组名「上→乌」/时刻「08:30→13:50」的航线语义依赖
# ——曾整段入类被剥成「上乌」「08:3013:50」（修正）
_EMJI = re.compile(
    "[🀀-🫿☀-➿🇦-🇿"
    "️]+")


def _no_emoji(t):
    """PNG 字体无 emoji 字形（渲染成方块）：图内文本统一剥离。"""
    return _EMJI.sub("", str(t or "")).strip()


def _plat_tag(f, plat_cn):
    tag = plat_cn.get(f.get("_platform", ""), f.get("_platform", ""))
    if f.get("_stale_h"):
        tag += f"·{f['_stale_h']:.0f}h前"
    return tag


def it_has_transfer(rows):
    return any(it[0] == "transfer" and it[1] for it in rows)


def _price_color(f: dict, qual: bool, price: float):
    """价格四档色：达标实心绿 / 行情破线空心绿 / 擦边琥珀（线 < 价 ≤
    线×(1+NEAR_RATIO)）/ 超线深蓝——与走势环同档同色（表格图不得缺
    擦边档，否则同一次推送两种分档语言）。擦边区间下界严格 >th（收窄，与 webui near 同式）。阈值由调用方写 f["_th"]，缺省退
    两档兼容旧调用。
    破线未达标（价≤线但口径不符：飞猪税前/中转衔接欠）曾落入超线同款
    深蓝——同表「更便宜反默认色」梯度倒挂；归 C_QUAL 空心
    （_price_hollow），与走势环「实心=达标/○描绿=行情破线」同构：
    同色系、空心=行情口径未必可出手。 档位结构收 _tier_of 单源。"""
    t = _tier_of(price, f.get("_th") or 0, qual)
    if t >= 1:            # 2=真达标 1=行情破线（空心由 _price_hollow 表达）
        return C_QUAL
    return C_NEAR if t == -1 else DESIGN.PRICE_PLAIN


def _price_hollow(f: dict, qual: bool, price: float) -> bool:
    """行情破线未达标 → 价格空心绿字。档位与 _price_color 同出
    _tier_of（色归 _price_color、空心归本函数，消费端只此一处渲染）。"""
    return _tier_of(price, f.get("_th") or 0, qual) == 1


def _summary_join(measure, bits, budget):
    """summary 宽度预算逐条取：调用端 [:4] 静态截断曾把
    第 5+ 条 KPI 丢出图外（两航线×两日期=8 bits 时后日期档位图上无从
    可见）——按 base14 字尺度量能放几条放几条，至少 1 条（单条超宽
    仍交 _fit_text 降号兜底）。measure(t)=像素宽回调；bits 为空返回空串。"""
    out = []
    for _b in bits or []:
        _cand = " ｜ ".join(out + [str(_b)])
        if not out or measure(_cand) <= budget:
            out.append(str(_b))
        else:
            break
    return " ｜ ".join(out)


def render_flights_table(rows, title, out_path="data/flights_table.png",
                         top_n=5, summary="", stamp_note="", ops_notes=""):
    """rows: [(kind, [flight dict] | [compare dict | str])] kind: direct/transfer/compare。
    direct/transfer 渲染分组明细表；compare 渲染三列小表
    （航班+时刻 ｜ 渠道价格链 ｜ 可省），旧式预拼字符串仍兼容直落。
    组第 4 元可带 meta dict：layover_min（衔接下限，着色绿/琥珀）、
    plat_mins（{platform: 最低价}——组尾「各渠道最低」子节，
    自钉钉文本段撤入）、
    summary: 图顶摘要行（脱离消息上下文也能看懂当前行情）。
    stamp_note: 时效口径注（数据窗因调用方而异：告警=当轮+近6h补位、
    日报=近2.5时；共用一句曾让告警图把 6h 补位价谎报成 2.5h 内）。
    ops_notes: 运维对账注（自钉钉文本段撤入图——「跳转文案
    才用文本」定律：无数据渠道/直挂标注缺失/孤低价拦截均无跳转需求，
    文本直出曾占推送首屏）。中性灰盒+灰字，勿用档位语义色。"""
    from core.alerter import Alerter
    plat_cn = Alerter.PLATFORM_CN
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    row_h, head_h, grp_h = 44, 42, 44
    cmp_h = 64   # 比价行两行式：航班+可省 / 渠道链整行（信息零截断）

    # 航班列决策次行容量规划器（行高自适应 44/60）：次行（机型·舱位·
    # 准点·餐食）放不下时按「·」拆两行小字、该行行高 44→60——
    # 「准点100…」式省略曾把餐食/准点截丢（用户实锤「详细信息省略，
    # 无法决策」）。徽标（直挂/经停）占次行右缘，拆分行选边让位。
    # 用 1x 字体测量（_ScaledDraw.textlength 同为逻辑域，等价）
    d_meas = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    _fx = 12 + TBL_COLS[0][1]      # 航班列 x
    _fw = TBL_COLS[1][1]           # 航班列宽

    def _plan_sub(f):
        """返回 (badge, bx, bw, f13, plan, bad_idx, rh)。
        plan=None：sub 为空或两行仍放不下（回退老路单行+省略号）；
        plan=[(txt, avail)]：单行直绘；[(l1,a1),(l2,a2)]：两行直绘。
        bad_idx：徽标让位的行下标（0=首行）。
         容量重组：全字段行 ~489px 曾击穿两行容量（无徽标上限
        436）→ plan=None 整体回退单行省略，准点/餐食/托运/共享/余票被
        截丢（决策字段零省略铁律破口）——按优先级逐档丢弃重试（先丢
        折扣、再丢机型），高优决策字段保住。"""
        def _parts():
            # 字段键值对（保留展示序），空值剔除——键供按优先级丢弃。
            # 第七批：bridgeRate（廊桥率，ctrip extendinfos/
            # tongcheng sts tt=6）随机型体量展示；cancelRate 异常门控
            # （仅 ≥CANCEL_RATE_ALERT 出词，阈值单源 core.alerter，常态
            # 零容量损耗）；lcc 仅在餐食/托运缺位时出词（廉航 tag 的
            # 存在意义是解释空缺，字段齐全=噪音）；cabinCode 单字母
            # 括注「经济舱(Y)」（退改等级根，+15px 落第 4 丢档档位）。
            # bizPrice 不进次行——compare 组链尾「公务￥N」词条消费
            _cabin_w = _cabin_cn(f.get("cabin"))
            _cc = str(f.get("cabinCode") or "").strip()
            if (_cabin_w == "经济舱" and len(_cc) == 1
                    and _cc.isalpha() and _cc.isupper()):
                _cabin_w = f"{_cabin_w}({_cc})"
            _lcc = ("廉航" if (f.get("lcc")
                               and (not str(f.get("meal") or "").strip()
                                    or not str(f.get("baggage") or "").strip()))
                    else "")
            return [(k, t) for k, t in (
                ("plane", (f.get("plane") or "").strip()),
                ("planeSize", (f.get("planeSize") or "").strip()),
                # bridge/cancel int 门（口径备案）：webui
                # 侧 _int_or_none 收整显示，本图 isinstance(int) 丢浮型
                # （80.0 不显）——当前爬虫 sts/kind 只产 int 无实害，勿
                # 单侧放宽致两表口径漂移
                ("bridge", (f"廊桥{f['bridgeRate']}%"
                            if isinstance(f.get("bridgeRate"), int) else "")),
                ("cabin", _cabin_w),
                # 黑卡价透明标记（渠道调研 B）：与 discount 同档解释
                # 价格（实付以渠道页为准），超宽行同档可丢
                ("black", ("黑卡价" if f.get("blackCard") else "")),
                # ctrip 资格限制专享价（推送审校）：与 webui 价格格徽标
                # 同词面「限青年价」（PNG 端无 ⚠——U+26A0 在 msyh 无
                # 字形渲染 tofu 方框，词面自带「限」字醒目）；该价误购
                # 无法出行，是「能不能买」的决策信息
                ("age", (f"{f['agePolicy']}价"
                         if str(f.get("agePolicy") or "").strip() else "")),
                # fliggy 中转机建燃油（推送审校）：裸价口径
                # 的实付差额，webui 次行同词面（去 + 号同信息）
                ("transferTax",
                 (f"机建燃油￥{f['transferTax']}"
                  if isinstance(f.get("transferTax"), int) else "")),
                # 折扣/托运额入图（决策信息补全）：折扣词面守卫
                # discount_txt 单源（「N.N折」/「全价」两形态，与
                # cabin_text 同源）；托运额是比价隐性成本（廉航对比
                # 显式更关键）
                ("discount", discount_txt(f.get("discount"))),
                ("prate", (f"准点{str(f['prate']).strip()}%"
                           if str(f.get("prate") or "").strip() else "")),
                ("lcc", _lcc),
                ("meal", str(f.get("meal") or "").strip()),
                ("baggage", str(f.get("baggage") or "").strip()),
                # 资格/权益标签族入图（推送审校）：经济舱售罄/含免费
                # 托运/老客专享等决策词走 labels 既有键——此前零落位，
                # 且 qunar/tongcheng 托运额走 baggage 键入图而 ctrip
                # 行李词在 labels，同图比价行李词面不对等在此补齐；
                # 「·」串整槽透传（超宽极端行由丢档链末档同丢保恒保
                # 组成行，见丢档链注）
                ("labels", str(f.get("labels") or "").strip()),
                # 共享实际承运/余票标签（决策字段入图）：共享=营销
                # 号非实际执飞（买前知执飞航司），票少=该班余票紧张。
                # 余票紧张度双源同槽：fewTicket 文本（qunar/fliggy）
                # 优先，leftTickets 数值（ctrip quantity/tongcheng atpt
                # 同键同协议，值域 1-9=渠道只对稀缺行发标签，10=充足不
                # 发）转「余N张」——与 webui 次行余票语境同语言
                ("share", (f"共享·{str(f['shareCarrier']).strip()}"
                           if str(f.get("shareCarrier") or "").strip()
                           else "")),
                ("few", (str(f.get("fewTicket") or "").strip()
                         or (f"余{f['leftTickets']}张"
                             if isinstance(f.get("leftTickets"), int)
                             and 0 < f["leftTickets"] < 10 else ""))),
                ("cancel", (f"取消率{f['cancelRate']}%"
                            if isinstance(f.get("cancelRate"), int)
                            and f["cancelRate"] >= CANCEL_RATE_ALERT
                            else "")),
            ) if t]

        badge = ""
        if f.get("transferBaggage") == "direct":
            badge = "直挂"
        elif f.get("transferBaggage") == "recheck":
            # 需转运（fliggy 真实值域）：直挂筛选航线上「达标失效」的
            # 判据——WebUI 明细行有此标签，图缺则两表不同语言；绘制色
            # 走下方非「直挂」分派的 MUTED 中性（勿用达标绿，语义打架）
            badge = "需转运"
        elif f.get("stopover"):
            badge = "经停" + (f.get("stopCity") or "")
            if f.get("stopTimeT"):
                badge += f"·停{f['stopTimeT']}"
        bx, bw, f13 = 0, 0, None
        if badge:
            # f13=字号 int（绘制处 d.font(f13) 统一乘 S）——曾直返
            # _font(13) 物理字体漏乘 S，2x 画布缩回后徽标视觉缩半
            # （「可省」同型事故的漏网实例）
            f13 = 13
            if d_meas.textlength(badge, font=_font(13)) > 150:
                while badge and d_meas.textlength(
                        badge + "…", font=_font(13)) > 150:
                    badge = badge[:-1]
                badge += "…"
            bw = int(d_meas.textlength(badge, font=_font(13))) + 14
            bx = _fx + _fw - 10 - bw

        def _try(kvs):
            sub = " · ".join(t for _k, t in kvs)
            if not sub:
                return None
            sf = _font(12)
            sx0 = _fx + 10
            sw = _fw - 20
            w1 = (bx - 8 - sx0) if badge else sw   # 徽标所在行文本让位
            if d_meas.textlength(sub, font=sf) <= w1:
                return [(sub, w1)], 0, row_h
            # 按「 · 」三字符分隔拆行：字段间分隔是三字符，
            # 共享标签内部裸「·」不参与断行——曾按单「·」拆，把
            # 「共享·南方航空CZ6993」拦腰截成「…·共享 / 南方航空…」
            ps = [p for p in sub.split(" · ") if p]
            for bad, (wa, wb) in ((0, (w1, sw)), (1, (sw, w1))):
                for k in range(1, len(ps)):
                    l1, l2 = " · ".join(ps[:k]), " · ".join(ps[k:])
                    if (d_meas.textlength(l1, font=sf) <= wa
                            and d_meas.textlength(l2, font=sf) <= wb):
                        return [(l1, wa), (l2, wb)], bad, 60
            return None

        kvs = _parts()
        sub = " · ".join(t for _k, t in kvs)
        if not kvs:
            return sub, badge, bx, bw, f13, None, 0, row_h
        plan = _try(kvs)
        if plan is None:
            # 丢档/缩档链（实测标定）：全字段 489px 击穿两行容量 436 →
            # 逐档重试拆行，准点/餐食/托运恒保住。缩共享标签=留执飞
            # 航班号去航司名（决策核心=营销号≠执飞），比丢舱位损耗小。
            # planeSize（机型体量词）随 discount 首档同丢——
            # 体量词信息量低于机型型号（曾只入 parts 不入
            # 丢档链，超宽行全程背着它重试、回退率上升）。
            # bridgeRate 舒适字段随首档同丢；lcc 与 cabin 同档
            # （第 4 档）丢弃——恒保组（准点/餐食/托运/共享/余票）之外
            # 门控在显的 cancelRate 不参与丢弃（警示词零省略）。
            # 末档（第 6 档）丢 labels/age：增益标签族串长恒占槽
            # （labels 可 15+ 全角），五档全败的极端超宽行若直接回退
            # 单行整截，恒保组一并蒸发——丢增益词保恒保组，次行仍可
            # 决策
            def _rebuild(drop, short_share):
                out = []
                for k2, t2 in kvs:
                    if k2 in drop:
                        continue
                    if short_share and k2 == "share":
                        # （推送审校 P0）：[A-Z] 开头会吞数字头
                        # 二字码首位（9C8845→C8845，3U/8L 同病）——缩档
                        # 产出错值非截断，违反宁缺勿错；改 [A-Z0-9]{2}
                        m = re.search(r"([A-Z0-9]{2}\d{3,4})$", t2)
                        if m:
                            t2 = "共享·" + m.group(1)
                    out.append((k2, t2))
                return out

            for _drop, _ss in ((("discount", "planeSize", "bridge",
                                  "black"), False),
                               (("discount", "planeSize", "bridge",
                                 "plane", "black"), False),
                               (("discount", "planeSize", "bridge",
                                 "plane", "black"), True),
                               (("discount", "planeSize", "bridge",
                                 "plane", "cabin", "lcc", "black"), False),
                               (("discount", "planeSize", "bridge",
                                 "plane", "cabin", "lcc", "black"), True),
                               (("discount", "planeSize", "bridge",
                                 "plane", "cabin", "lcc", "black",
                                 "labels", "age"), True)):
                _kvs2 = _rebuild(_drop, _ss)
                if len(_kvs2) < len(kvs) or _ss:
                    plan = _try(_kvs2)
                    if plan is not None:
                        break
        if plan is None:
            return sub, badge, bx, bw, f13, None, 0, row_h
        plist, bad, rh = plan
        return sub, badge, bx, bw, f13, plist, bad, rh

    # 高度必须覆盖每组各自的表头（compare 组无表头）；漏算会导致底部被裁出画布。
    # 次行拆两行的行（44→60）逐行 +16 计入；plat_mins「各渠道最低」子节
    # （自钉钉文本段撤入图）+24
    def _grp_h(kind, n, meta=None):
        pm = 24 if (meta or {}).get("plat_mins") else 0
        return (grp_h + (min(n, top_n) or 1) * (cmp_h if kind == "compare"
                                                else row_h) + 22 + pm
                + (0 if kind == "compare" else head_h))

    def _row_extra(it):
        if it[0] == "compare":
            return 0
        fsx = sorted(it[1], key=lambda f: f.get("price", 9e9))[:top_n]
        return sum(16 for f in fsx if _plan_sub(f)[7] == 60)
    # 图例条件与 meta 解耦：旧条件 meta_any and it_has_transfer
    # 在告警路径（rows 无第 4 元 meta）恒 False→整图无图例，但图上照样有
    # 达标绿行/「可省/差」/直挂徽标需要解码——改按内容扫描：达标行/
    # compare 组/transfer 组任一出现即显示（图例内容渲染逻辑不变）。
    # 补琥珀判据：纯直飞小节出现琥珀擦边价时曾 legend_h=0，
    # 图内琥珀价无任何解码词条（与 补橙红词条同型病灶）——
    # 任一行价格着非默认色即 worthy
    def _colored(f):
        try:
            return _price_color(f, bool(f.get("_qual")),
                                float(f["price"])) not in (
                DESIGN.PRICE_PLAIN, C_TEXT)
        except (TypeError, ValueError):
            return False
    legend_worthy = (
        any(f.get("_qual") for it in rows if it[0] != "compare"
            for f in it[1] if isinstance(f, dict))
        or any(it[0] == "compare" for it in rows)
        or it_has_transfer(rows)
        or any(_colored(f) for it in rows if it[0] != "compare"
               for f in it[1] if isinstance(f, dict)))
    # summary 预排（两行式）：列表入参按宽度预算逐条取行，
    # 余量折下一行（盒高 30→每加一行 +16）——[:4] 静态截断曾把第 5+
    # 条 KPI 丢出图外，容量只增不减、字号不降；字符串入参（日报）单行
    _sm_lines = []
    if isinstance(summary, (list, tuple)):
        _rest = [str(_b) for _b in summary]
        _measure = lambda t: d_meas.textlength(t, font=_font(14))
        for _ in range(3):        # 至多 3 行，再溢出接受丢弃（罕见）
            if not _rest:
                break
            _ln = _summary_join(_measure, _rest, TBL_W - 56)
            if not _ln:
                break
            _sm_lines.append(_ln)
            _rest = _rest[_ln.count(" ｜ ") + 1:]
    elif summary:
        _sm_lines.append(str(summary))
    sm_h = ((30 + 16 * (len(_sm_lines) - 1)) + 8) if _sm_lines else 0
    # 运维对账注预排：同 summary 的宽度预算逐条取行，至多
    # 3 行；仍溢出尾行挂「等N条」——对账信息不允许静默丢失
    _ops_lines = []
    if isinstance(ops_notes, (list, tuple)):
        _rest = [str(_b) for _b in ops_notes if str(_b).strip()]
        _measure13 = lambda t: d_meas.textlength(t, font=_font(13))
        for _ in range(3):
            if not _rest:
                break
            _ln = _summary_join(_measure13, _rest, TBL_W - 56)
            if not _ln:
                break
            _ops_lines.append(_ln)
            _rest = _rest[_ln.count(" ｜ ") + 1:]
        if _rest and _ops_lines:
            # 尾注「等N条」过量宽（推送审校）：直接尾拼曾
            # 不再走预算，_fit_text 渲染截断时它恰在行尾最先丢（对账
            # 留痕失效）——并回 _summary_join 度量，装不下独立成行
            # （ops_h 按行数参数化天然支持）
            _tail = f"等{len(_rest)}条"
            _merged = _summary_join(
                _measure13, _ops_lines[-1].split(" ｜ ") + [_tail],
                TBL_W - 56)
            if _merged:
                _ops_lines[-1] = _merged
            else:
                _ops_lines.append(_tail)
    elif str(ops_notes or "").strip():
        _ops_lines.append(str(ops_notes))
    ops_h = ((24 + 15 * (len(_ops_lines) - 1)) + 8) if _ops_lines else 0
    legend_h = 48 if legend_worthy else 0   # 两行（补橙红词条后
    # 单行 14px 实测 873/888 无降级余量，拆两行各携半数词条；48=2 行
    # 14px 视觉高 + 卡底缘 h-7 上方净空——38 曾让次行压线被裁）
    h = 58 + sum(_grp_h(it[0], len(it[1]),
                        it[3] if len(it) > 3 and isinstance(it[3], dict) else None)
                 + _row_extra(it) for it in rows) \
        + 8 + sm_h + ops_h + legend_h
    # 白卡浮在浅灰底上：圆角+细边框，PNG 在钉钉里立刻脱离"平铺表格"感
    S = 2
    img = Image.new("RGB", (TBL_W * S, h * S), DESIGN.BG)
    d = _ScaledDraw(ImageDraw.Draw(img), S)
    d.rounded_rectangle([6, 6, TBL_W - 7, h - 7], radius=14,
                        fill=DESIGN.CARD, outline=DESIGN.CARD_LINE, width=2)
    f_title, f_head, f_cell, f_grp = (d.font(21), d.font(16),
                                      d.font(16), d.font(19))
    # 顶栏标题/时间戳统一 anchor 中线锚（收口，同锚 y=30 行中线）。
    # 标题限宽：多航线长城市对裸落曾右溢压时间戳，与走势侧
    # _fit_text（890）对称
    stamp = datetime.now().strftime("%m/%d %H:%M 生成 · ") + (
        stamp_note or "近2.5时各渠道最新")
    _sw = d.textlength(stamp, font=d.font(14))
    _fit_text(d, title, 24, 30, TBL_W - 28 - _sw - 40, base=21, min_size=14,
              fill=C_TEXT, anchor="lm")
    d.text((TBL_W - 28, 30), stamp, font=d.font(14), fill=DESIGN.MUTED,
           anchor="rm")
    y = 62
    if _sm_lines:
        # 摘要盒（多行式）：行数决定盒高，anchor 逐行均分盒高
        _box_h = 30 + 16 * (len(_sm_lines) - 1)
        d.rounded_rectangle([16, y, TBL_W - 16, y + _box_h], radius=8,
                            fill=DESIGN.SUMMARY_BG, outline=DESIGN.SUMMARY_LINE)
        _step = _box_h / len(_sm_lines)
        for _i, _ln in enumerate(_sm_lines):
            # 多航线摘要必超宽：自适应降号+截断，直落曾溢出白卡右缘
            _fit_text(d, _ln, 28, y + _step * (_i + 0.5), TBL_W - 56,
                      base=14, min_size=11,
                      fill=DESIGN.SUMMARY_TX, anchor="lm")
        y += _box_h + 8
    if _ops_lines:
        # 运维对账盒：中性灰系——档位色（绿/琥珀/红）各有
        # 语义，对账注借用会引发档位误读；灰=系统注记无档位含义
        _box_h = 24 + 15 * (len(_ops_lines) - 1)
        d.rounded_rectangle([16, y, TBL_W - 16, y + _box_h], radius=8,
                            fill=(245, 247, 250), outline=(214, 220, 228))
        _step = _box_h / len(_ops_lines)
        for _i, _ln in enumerate(_ops_lines):
            _fit_text(d, _ln, 28, y + _step * (_i + 0.5), TBL_W - 56,
                      base=13, min_size=11, fill=DESIGN.MUTED, anchor="lm")
        y += _box_h + 8

    def draw_head(y):
        d.rectangle([12, y, TBL_W - 12, y + head_h], fill=DESIGN.HEAD_BG)
        d.line([(12, y + head_h - 1), (TBL_W - 12, y + head_h - 1)],
               fill=DESIGN.HEAD_LINE, width=2)
        x = 12
        for name, w in TBL_COLS:
            tw = d.textlength(name, font=f_head)
            tx = _tbl_align(name, x, w, tw)
            d.text((tx, y + head_h / 2), name, font=f_head, fill=DESIGN.HEAD_TX,
                   anchor="lm")
            x += w
        return y + head_h

    alt = 0
    for item in rows:
        kind, fs = item[0], item[1]
        label_override = item[2] if len(item) > 2 else None
        if kind == "compare":
            # compare 区块同样遵守统一 anchor 中线纪律（收口）。
            # 组语义配色随结论：「可省」组浅绿底+绿条（省=好事），组内
            # 全为「差」行（离群口径警示）才整组红系；行级结论仍各自着色
            grp_bad = all(l.get("outlier") for l in fs if isinstance(l, dict))
            grp_c = C_CMP if grp_bad else C_SAVE
            grp_bg = (251, 240, 240) if grp_bad else (240, 250, 244)
            d.rounded_rectangle([12, y, TBL_W - 12, y + grp_h - 4], radius=8,
                                fill=grp_bg)
            d.rectangle([12, y, 16, y + grp_h - 4], fill=grp_c)
            d.text((26, y + (grp_h - 4) / 2),
                   _no_emoji(label_override or "同班跨渠道比价"),
                   font=f_grp, fill=grp_c, anchor="lm")
            if fs:
                # 组头右侧候选数角标（与 TOP 角标同款：标实际行数）
                tag_txt = f"{len(fs)}选"
                d.text((TBL_W - 28, y + (grp_h - 4) / 2), tag_txt,
                       font=f_head, fill=DESIGN.MUTED, anchor="rm")
            y += grp_h
            if not fs:
                d.text((24, y + 10), "暂无多渠道同班", font=f_cell, fill=C_TEXT)
                y += row_h
            for line in fs[:top_n]:
                if alt % 2:
                    d.rectangle([12, y, TBL_W - 12, y + cmp_h],
                                fill=DESIGN.ROW_ALT)
                alt += 1
                if isinstance(line, str):      # 旧调用方：预拼文本直接落
                    # 直落 _fit_text 不过 _no_emoji——现役调用方均已结构化，
                    # 预拼串可能含未剥离的 emoji（箭头误剥问题已在
                    # 正则收口，此保守直落保持不变）
                    _fit_text(d, line, 24, y + 10, TBL_W - 48, base=15)
                else:
                    # 两行式行卡：航班+时刻（左）与 可省（右）一行，
                    # 渠道价格链独占整行——5 渠道链在半宽列曾截尾丢信息
                    # 「中转」占位过滤（tuniu 占位，与文案 _via_txt 同规则，
                    # 曾在总表渲染出「经中转」病句）；衔接/跨天补齐信息；
                    # 经停组（stopCity 有数据）显示「经停西安」
                    stop_city = line.get("stopCity") or ""
                    trans = line.get("trans") or ""
                    tr = (f" 经停{stop_city}" if stop_city
                          else (f" 经{trans}" if trans and trans != "中转" else ""))
                    lay = line.get("lay") or ""
                    if lay:
                        tr += f" 停{lay}"
                    if line.get("cross"):
                        tr += f" {line['cross']}"
                    # 首行：航班+航线+时刻 加粗17px，anchor="lm" 锚行中线
                    # y+18（收口）；右缘「可省」大字同中线（见下）
                    _fit_text(d, f"{line['label']}  {line['dep']}→{line['arr']}{tr}",
                              24, y + 18, TBL_W - 240, base=17, anchor="lm")
                    # 离群组（最高价 > 2×最低价）：「可省」大概率是跨舱位/报价
                    # 口径差异而非真实可省——如实改口径并加警示角标
                    outlier = bool(line.get("outlier"))
                    save = f"{'差' if outlier else '可省'} ￥{line['save']:.0f}"
                    # 语义分档：「可省」正向绿（省=好事）、「差」
                    # 保留警示红；anchor="rm" 右缘对齐价格列右缘
                    # （12+列和-10=TBL_W-22，与明细价格列右对齐同轴），
                    # y+18 垂直锚首行中线
                    f_sv = d.font(22, bold=True)   # 逻辑域 22px 粗体（rm 锚
                    # 只需右缘 x，不再手减 textlength——PIL 自算宽度）
                    d.text((TBL_W - 22, y + 18), save, font=f_sv,
                           fill=C_CMP if outlier else C_SAVE, anchor="rm")
                    # 渠道链：逐段绘制（重构）——飞猪价后附小号
                    # MUTED「税前」（税前假低可辨识；chain 元素只存中文
                    # 渠道名——构造端已把 _platform 映射为中文名，按
                    # PLATFORM_CN["fliggy"] 反查比对）。渠道+价格链不可截丢：
                    # 超宽先剥「(经济舱)」舱位括注（括注可从明细行的双行
                    # 舱位文案获得）、再整链统一降号（16→11，链内字号一致），
                    # 仍超宽输出保底形态「最低价渠道￥价 等N家」——
                    # 绝不以 … 截尾丢最低价
                    ch = line.get("chain") or []
                    fliggy_cn = plat_cn.get("fliggy", "飞猪")
                    segs = []
                    for ci, c in enumerate(ch):
                        if ci:
                            segs.append((" → ", 16, DESIGN.CHAIN_TX))
                        cab = c[2] if len(c) > 2 else ""
                        segs.append((f"{c[0]} ￥{c[1]:.0f}"
                                     + (f"({cab})" if cab else ""),
                                     16, DESIGN.CHAIN_TX))
                        if c[0] == fliggy_cn and FLIGGY_TAX_PAD > 0:
                            # 税前小标仅在税垫启用（两口径有差）时出——
                            # pad=0（重标定）飞猪价与可支付同口径，
                            # 「税前」标注成了假警示
                            segs.append((" 税前", 13, DESIGN.MUTED))
                    # 高档舱价词条（链尾小字灰）：同班升舱差决策
                    # （读者对照链内现价），随整链统一降号/保底形态
                    # 自然降级；舱别词面随 bizCab 源（公务/头等），
                    # 存量行缺省回退「公务」
                    if line.get("biz"):
                        segs.append((f" · {line.get('bizCab') or '公务'}"
                                     f"￥{line['biz']:.0f}",
                                     13, DESIGN.MUTED))

                    def _segs_w(ofs):
                        return sum(d.textlength(t, font=d.font(max(11, sz + ofs)))
                                   for t, sz, _c in segs)
                    ofs = 0
                    if ch and _segs_w(0) > TBL_W - 48:
                        segs = [(re.sub(r"\([^)]*\)", "", t), sz, c)
                                for t, sz, c in segs]      # 剥舱位括注
                        while ofs > -5 and _segs_w(ofs) > TBL_W - 48:
                            ofs -= 1                       # 整链统一降号 16→11
                        if _segs_w(ofs) > TBL_W - 48:
                            lo = min(ch, key=lambda c: c[1])
                            segs = [(f"{lo[0]}￥{lo[1]:.0f} 等{len(ch)}家",
                                     16, DESIGN.CHAIN_TX)]
                            ofs = 0
                    sx = 24
                    for t, sz, c in segs:
                        f_seg = d.font(max(11, sz + ofs))
                        d.text((sx, y + 46), t, font=f_seg, fill=c,
                               anchor="lm")
                        sx += d.textlength(t, font=f_seg)
                y += cmp_h
            y += 18
            continue
        meta = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
        lay_min = int(meta.get("layover_min", 0) or 0)
        if kind == "direct":
            label = label_override or "直飞最优"
        else:
            # 组头到达约束动态化：meta 带 arrival_max（配置的
            # transfer_arrival_max）则拼实际时刻，缺省保持「凌晨前」兜底
            # （旧版硬编码，与配置不一致时两张皮）
            label = label_override or (
                f"中转行情最优（仅当日/次日 {meta.get('arrival_max')} 前到达）"
                if meta.get("arrival_max")
                else "中转行情最优（仅当日/次日凌晨前到达）")
        label = _no_emoji(label)
        color = C_DIRECT if kind == "direct" else C_TRANSFER
        tx_c = color if kind == "direct" else C_TRANSFER_TX   # 文字面 AA（P2-1）
        band = DESIGN.CAP_DIRECT_BG if kind == "direct" else DESIGN.CAP_TRANSFER_BG
        d.rounded_rectangle([12, y, TBL_W - 12, y + grp_h - 4], radius=8,
                            fill=band)
        d.rectangle([12, y, 16, y + grp_h - 4], fill=color)   # 左色条
        d.text((26, y + 20), label, font=f_grp, fill=tx_c, anchor="lm")
        # 组头右侧：TOP 标 + 直挂筛选标注（配置可读性）；标实际行数
        # （组不足 top_n 时「TOP5」实画 3 行数字失真），空组不标
        if fs:
            tag_txt = f"TOP{min(len(fs), top_n)}"
            d.text((TBL_W - 28, y + 20), tag_txt, font=f_head,
                   fill=DESIGN.MUTED, anchor="rm")
        y += grp_h
        y = draw_head(y)
        fs = sorted(fs, key=lambda f: f.get("price", 9e9))[:top_n]
        if not fs:
            # 空态按约束归因：「该轮未回中转数据」与「有班但被衔接/到达
            # 约束滤掉」是两种成因，恒写前者曾让配置了衔接下限的用户对
            # 着明细找「为什么图上没有」（日报语境亦无「轮」概念）
            empty = ("暂无满足约束的班次（衔接≥%d 分钟·%s 前到达）"
                     % (lay_min, meta.get("arrival_max") or "次日 02:00")
                     if lay_min > 0 or meta.get("arrival_max")
                     else "暂无数据（该轮渠道未回中转班次，下轮自动补上）")
            d.text((24, y + row_h / 2), empty, font=f_cell, fill=C_TEXT,
                   anchor="lm")
            y += row_h
        for f in fs:
            qual = bool(f.get("_qual"))
            sub, badge, bx, bw, f13, plan, bad_i, rh = _plan_sub(f)
            if qual:
                d.rectangle([12, y, TBL_W - 12, y + rh], fill=(238, 249, 242))
            elif alt % 2:
                d.rectangle([12, y, TBL_W - 12, y + rh],
                            fill=DESIGN.ROW_ALT)
            alt += 1
            price = f.get("price", 0)
            cross = f.get("crossDayDesc") or ""
            arr = f"{f.get('arrTime','')}" + (f" {cross}" if cross else "")
            is_tr = bool(f.get("transCity"))
            cells = [
                ("直飞" if not is_tr else "中转", None),
                (f.get("name", ""), None),
                (f.get("depTime", ""), None),
                (arr, None),
                (f.get("transCity", "") or "—", None),
                (f.get("totalDuration", "") or "—", None),
                (_plat_tag(f, plat_cn), None),
                (f"￥{price:.0f}", _price_color(f, qual, price)),
            ]
            x = 12
            dot = PLAT_DOT.get(f.get("_platform", ""))
            yc = y + rh / 2   # 行统一中线：全列元素（文字/药丸/圆点/徽标）
            for (txt, _), (name, w) in zip(cells, TBL_COLS):
                fill = C_TEXT
                if name == "价格":
                    fill = cells[-1][1]
                if qual and name in ("类别",):
                    fill = C_QUAL
                if name == "类别":
                    # 类别画胶囊：浅底深字粗体（实底白字在 2x 缩放下曾显廉价），
                    # 直飞蓝系/中转橙系；达标行 C_QUAL 绿描边+绿字强化
                    # （与价格绿同语义，注释写了就必须实现）。
                    # 描边/文字引 C_DIRECT/C_TRANSFER（色值单源：禁再出现
                    # (26,115,232)/(224,127,42)/(196,110,20) 三个漂移副本
                    # ——中转胶囊自身描边与文字两种橙，组头色条另一橙）
                    cap_w, cap_h = 46, 22
                    cx, cy = x + 8, yc - cap_h / 2
                    cap_c = (C_QUAL if qual else
                             (C_DIRECT if not is_tr else C_TRANSFER))
                    cap_tx = (C_QUAL if qual else
                              (C_DIRECT if not is_tr else C_TRANSFER_TX))
                    d.rounded_rectangle(
                        [cx, cy, cx + cap_w, cy + cap_h], radius=cap_h // 2,
                        fill=DESIGN.CAP_DIRECT_BG if not is_tr else DESIGN.CAP_TRANSFER_BG,
                        outline=cap_c,
                        width=2)
                    d.text((cx + cap_w / 2, yc), txt, font=d.font(12),
                           fill=cap_tx, anchor="mm")
                elif name in ("出发", "到达", "全程"):
                    d.text((x + w / 2, yc), txt, font=d.font(16), fill=fill,
                           anchor="mm")
                elif name == "价格":
                    # 价格是全表视觉锚点：大号右对齐；达标实心绿/破线
                    # 空心绿（描边同 C_QUAL，与走势环描绿环同构）/普通深蓝
                    if _price_hollow(f, qual, price):
                        # stroke_width 不经 _ScaledDraw 缩放（物理 px）：
                        # 2=缩回后 1 逻辑 px；push P2-2（旧值 1 缩回
                        # 0.5 逻辑 px，手机缩放下四档色断档最弱）
                        d.text((x + w - 10, yc), txt, font=d.font(20),
                               fill=(255, 255, 255), anchor="rm",
                               stroke_width=2, stroke_fill=C_QUAL)
                    else:
                        d.text((x + w - 10, yc), txt, font=d.font(20),
                               fill=fill, anchor="rm")
                elif name == "航班":
                    # 决策字段双行（行高44内）：首行航班名通栏，次行左
                    # 「机型 · 舱位」小字（有一个画一个，都空维持单行）——
                    # 与中转列同款「跨行中线」锚法；徽标（直挂/经停）沉到
                    # 次行右侧、宽随文本自适应并封顶——徽标再长也不侵占
                    # 航班名与邻列（首行右缘锚定长徽标曾左溢压到类别胶囊）。
                    # 容量规划（_plan_sub）：次行放不下拆两行小字、行高
                    # 44→60——「准点100…」式省略曾截丢餐食/准点（决策
                    # 字段零省略）
                    if rh == 60:
                        _fit_text(d, txt, x + 10, yc - 16, w - 20,
                                  base=16, fill=fill, anchor="lm")
                        _offs = (yc + 2, yc + 18)
                    else:
                        _fit_text(d, txt, x + 10,
                                  yc - 9 if (sub or badge) else yc,
                                  w - 20, base=16, fill=fill, anchor="lm")
                        _offs = (yc + 11,)
                    if plan:
                        for _off, (_t, _av) in zip(_offs, plan):
                            if _t:
                                _fit_text(d, _t, x + 10, _off, _av,
                                          base=12, min_size=11,
                                          fill=DESIGN.MUTED, anchor="lm")
                    elif sub:
                        # 规划失败兜底：老路单行 fit_text（降号→省略号）
                        sub_right = (bx - 8) if badge else (x + w - 10)
                        if sub_right - (x + 10) >= 30:
                            _fit_text(d, sub, x + 10, yc + 11,
                                      sub_right - (x + 10), base=12,
                                      min_size=11, fill=DESIGN.MUTED,
                                      anchor="lm")
                    if badge:
                        _bc = _offs[bad_i] if (plan and bad_i < len(_offs)
                                               and rh == 60) else _offs[0]
                        d.rounded_rectangle([bx, _bc - 9, bx + bw, _bc + 9],
                                            radius=9,
                                            outline=C_QUAL if badge == "直挂"
                                            else DESIGN.MUTED, width=2)
                        d.text((bx + bw / 2, _bc), badge,
                               font=d.font(f13),
                               fill=C_QUAL if badge == "直挂"
                               else DESIGN.MUTED, anchor="mm")
                elif name == "渠道" and dot:
                    d.ellipse([x + 10, yc - 4, x + 18, yc + 4], fill=dot)
                    _fit_text(d, txt, x + 24, yc, w - 28,
                              base=16, fill=fill, anchor="lm")
                elif name == "中转":
                    # 两行制：有衔接小字（行尾第二行，同款判定键）时城市
                    # 上移对称跨行中线；无则城市独占行中线——恒 yc-9 曾让
                    # 无衔接信息的行与相邻列居中字错位（收口）
                    trans_cx, trans_cw = x, w
                    d.text((x + w / 2,
                            yc - 9 if (is_tr and f.get("layoverT")) else yc),
                           txt or "—", font=d.font(15), fill=fill, anchor="mm")
                else:
                    _fit_text(d, txt, x + 10, yc, w - 14,
                              base=15, fill=fill, anchor="lm")
                x += w
            if is_tr and f.get("layoverT") and trans_cw:
                # 中转衔接（第二行）始终显示——时长是决策关键，不依赖配置；
                # 着色：配置了下限且达标=绿，未配置下限=中性灰
                lay = f"停{f['layoverT']}"
                lc = (C_QUAL if (f.get("layoverM") or 0) >= lay_min
                      else DESIGN.LAY_SHORT) if lay_min > 0 else DESIGN.MUTED
                l2 = str(f.get("lay2dep") or "").strip()
                if l2:
                    # 二段起飞时刻（衔接风险最直接指标，入图；
                    # webui 明细「二段 HH:MM 起飞」同款同词）；中转列窄
                    # 整行自适应降号，仍超截断（信息补全非必需字段）
                    _fit_text(d, f"{lay}·二段{l2}",
                              trans_cx + trans_cw / 2, yc + 9, trans_cw - 6,
                              base=12, min_size=10, fill=lc, anchor="mm")
                else:
                    d.text((trans_cx + trans_cw / 2, yc + 9), lay,
                           font=d.font(13), fill=lc, anchor="mm")
            if qual:
                d.rectangle([12, y, 16, y + rh], fill=C_QUAL)
            # 行间 hairline（达标行浅绿线）
            lc = (226, 240, 231) if qual else (238, 241, 245)
            d.line([(12, y + rh - 1), (TBL_W - 12, y + rh - 1)],
                   fill=lc, width=1)
            y += rh
        pmins = meta.get("plat_mins") or {}
        if pmins:
            # 「各渠道最低」子节（撤自钉钉文本段：纯行情无链接，
            # 定律一律入图）：渠道色点+中文名+最低价按价升序；无明细
            # 只有全线价的渠道价后注「全线」（未筛到达/衔接，同旧文本
            # 「全线价」口径词）。超宽（渠道名长）逐段截断不折行——顺序
            # 即价格序，前段永远是最便宜渠道
            py_ = y + 11
            px_ = 24
            f_pm = d.font(13)
            hd = "各渠道最低（含直飞）："   # 挂中转组尾，词条消歧防误读为中转口径
            d.text((px_, py_), hd, font=f_pm, fill=DESIGN.MUTED, anchor="lm")
            px_ += d.textlength(hd, font=f_pm)
            for _i, (p_, pv) in enumerate(pmins.items()):
                v_, has_dtl = (pv if isinstance(pv, tuple)
                               else (pv, True))
                if _i:
                    d.text((px_, py_), " ｜ ", font=f_pm,
                           fill=DESIGN.MUTED, anchor="lm")
                    px_ += d.textlength(" ｜ ", font=f_pm)
                t_ = (f"{plat_cn.get(p_, p_)} ￥{v_:.0f}"
                      + ("" if has_dtl else "（全线）"))
                tw_ = d.textlength(t_, font=f_pm)
                if px_ + 10 + tw_ > TBL_W - 24:
                    # 「等N家」按未渲染家数计（总渠道数
                    # 曾把已显示的也算进「等」，数字失真）
                    d.text((px_, py_), f"… 等{len(pmins) - _i}家",
                           font=f_pm, fill=DESIGN.MUTED, anchor="lm")
                    break
                d.ellipse([px_, py_ - 3, px_ + 6, py_ + 3],
                          fill=PLAT_DOT.get(p_, DESIGN.MUTED))
                d.text((px_ + 10, py_), t_, font=f_pm,
                       fill=DESIGN.CHAIN_TX, anchor="lm")
                px_ += 10 + tw_
            y += 24
        y += 18
    if legend_h:
        # 两行图例：首行=价格档色+衔接警示色（决策色全部
        # 有解码——橙红 LAY_SHORT 着色的「停X·二段HH:MM」必须有词条，
        # 否则首见者只能猜）；次行=徽标与比价词条。「真达标/描边绿/擦边」
        # 词面与走势环小注、webui 明细档位同语言（总长较旧
        # 词面更短，14px 档无降号风险）。 词面改挂 TIER_FULL
        # 投影（色绑前缀与「衔接不足」留点位本地）
        _fit_text(d, f"深绿={TIER_FULL['qual']} · 描绿={TIER_FULL['mkt']}"
                     f" · 琥珀={TIER_FULL['near']} · 深蓝={TIER_FULL['over']}"
                     " · 橙红=衔接不足 · 绿停时=衔接达标",
                  24, h - 44, TBL_W - 48, base=14, min_size=11,
                  fill=DESIGN.MUTED)
        _fit_text(d, "经停=同机号中途落地 · 「直挂」=两段免费托运 · "
                     "「可省」绿「差」红=渠道价差",
                  24, h - 26, TBL_W - 48, base=14, min_size=11,
                  fill=DESIGN.MUTED)
    img = img.resize((TBL_W, h), Image.LANCZOS)
    img.save(out_path)
    return out_path


def render_chart(series, title, thresholds=(0, 0), out_path="data/trend.png",
                 hours=48):
    """series: [(ts, best_direct|None, best_transfer|None, qd, qt)]
    （qd/qt 为该轮最低点达标口径旗标，5 元组——3 元组旧数据由
    len 守卫兼容，旗标缺省按无环渲染）"""
    # 与明细总表同视觉基准：白卡浮浅灰底（rounded_rectangle 圆角细边）。
    # 2x 超采样与明细表 _ScaledDraw 同一模式：内部画布
    # 1872×920、末尾 LANCZOS 缩回 936×460 对外尺寸不变——文字/圆点
    # 高分屏不再锯齿。_ScaledDraw 只缩放坐标、不缩放 width（明细表同款），
    # 线宽字面量统一按 S 放大保证缩回后与原 1x 等宽；字体一律取
    # d.font(n)（内部乘 S，明细表同款），直调 _font 会漏乘渲染减半
    S = 2
    img = Image.new("RGB", (W * S, H * S), DESIGN.BG)
    d = _ScaledDraw(ImageDraw.Draw(img), S)
    if not series:
        # 空序列守卫：阈值非零+无数据曾穿透下方「暂无数据」空态
        # （该态要求 vals、th 双空），在 series[-1] 取跨度处 IndexError
        # ——不得只靠调用方 prepare_round_charts 的 if not series 挡住。
        # 空态统一白卡（曾灰底裸字与下方双空分支两态两张皮）
        d.rounded_rectangle([6, 6, W - 7, H - 7], radius=14,
                            fill=DESIGN.CARD, outline=DESIGN.CARD_LINE,
                            width=2)
        d.text((20, 20), "暂无数据", font=d.font(21), fill=C_TEXT,
               anchor="lm")   # 与 direct/transfer 空态同 lm 中线锚
        img.resize((W, H), Image.LANCZOS).save(out_path)
        return out_path
    d.rounded_rectangle([6, 6, W - 7, H - 7], radius=14,
                        fill=DESIGN.CARD, outline=DESIGN.CARD_LINE, width=2)
    f_title = d.font(21)
    f_axis = d.font(14)
    f_leg = d.font(16)
    f_mark = d.font(16)

    vals = [v for row in series for v in row[1:3] if v is not None]
    th = [x for x in thresholds if x]
    if not vals and not th:
        # 与上方空序列守卫同皮（曾 TIP_LINE 描边 + 默认 la 锚
        # 字位低 ~10px，注释自称「统一白卡」实未统一）
        d.rounded_rectangle([6, 6, W - 7, H - 7], radius=14,
                            fill=DESIGN.CARD, outline=DESIGN.CARD_LINE,
                            width=2)
        d.text((20, 20), "暂无数据", font=f_title, fill=C_TEXT, anchor="lm")
        img.resize((W, H), Image.LANCZOS).save(out_path)
        return out_path
    lo = min(vals + th) - max(40, (max(vals + th) - min(vals + th)) * 0.06)
    hi = max(vals + th) + max(40, (max(vals + th) - min(vals + th)) * 0.06)

    def xy(i, v):
        x = PAD_L + (W - PAD_L - PAD_R) * (i / max(1, len(series) - 1))
        y = PAD_T + (H - PAD_T - PAD_B) * (1 - (v - lo) / (hi - lo))
        return x, y

    # 标题 + 图例（标题限宽防压图例：图例固定 lx=W-300 起，长城市对/
    # 自定义航线名曾直落压上「直飞最低」线标）
    _fit_text(d, title, PAD_L, 20, W - 300 - PAD_L - 16,
              base=21, min_size=14, fill=C_TEXT)
    lx = W - 300
    d.line([(lx, 32), (lx + 26, 32)], fill=C_DIRECT, width=6)
    d.text((lx + 32, 24), "直飞最低", font=f_leg, fill=C_TEXT)
    d.line([(lx + 130, 32), (lx + 156, 32)], fill=C_TRANSFER, width=6)
    # 图例统一「中转最低」：曲线是行情最低（不限直挂），达标语义由
    # 达标虚线与点环分档表达——「(达标)」字样曾与列表仅直挂口径打架
    d.text((lx + 162, 24), "中转最低", font=f_leg, fill=C_TEXT)
    # 口径小注改写：两线均为行情池最低、中转不限直挂——旧注「行情最低·
    # 不限直挂」曾误读成只修饰直飞线（张冠李戴）
    d.text((lx + 32, 46), "两线均为行情池最低·中转不限直挂",
           font=d.font(13), fill=DESIGN.MUTED)
    # 点环分档小注（与推送文字 🎯达标/🟩破线/🟨擦边 同档同语言）；
    # ▼红=达标回落词条：红下箭头 入图后图面无解释，
    # 首见者只能猜。 词面与 webui 环标逐字同语言（真达标/擦边）
    nx = PAD_L
    f_ring = d.font(13)
    for t, c in (("●深绿", C_QUAL), (f"={TIER_FULL['qual']}　", DESIGN.MUTED),
                 ("○描绿", C_QUAL), (f"={TIER_FULL['mkt']}　", DESIGN.MUTED),
                 ("○琥珀", C_NEAR),
                 (f"={TIER_FULL['near']}　", DESIGN.MUTED),
                 ("▼红", C_CMP), (f"={TIER_FULL['fall']}", DESIGN.MUTED)):
        d.text((nx, 46), t, font=f_ring, fill=c)
        nx += d.textlength(t, font=f_ring)

    # 跨天判定：首末数据点日期不同即跨天（18.3h 窗曾因 <20h 阈值
    # 无分隔线无日期标识，用户只能靠「低」标签里的日期推断）
    cross_day = series[0][0].date() != series[-1][0].date()

    # 竖直参考网格（均布 4 条）：帮助对齐下方时间刻度
    plot_w = W - PAD_L - PAD_R
    for k in range(1, 4):
        gx = PAD_L + plot_w * k / 4
        d.line([(gx, PAD_T), (gx, H - PAD_B)], fill=C_GRID, width=2)

    # 网格 + Y 轴刻度（右对齐贴线、行中线锚，——旧 la 锚
    # y-8 数字视觉中心偏离网格线 2-3px，全图其余文字已统一中线锚）。
    # nice-step 整价锚：step 曾 (hi-lo)/4 浮点直出，网格线
    # 落在 ￥2183.75 类非整值——数据价几乎永不落线，对齐扫读形同虚设；
    # step 吸附 1/2/5×10^n 且 ≥(hi-lo)/4（经典 nice 阶梯，步长恒 10 的
    # 整十倍，标签永远 ×00 收尾）
    step = (hi - lo) / 4
    _mag = 1.0
    while _mag * 10 <= step:
        _mag *= 10
    _nice = next(m * _mag for m in (1, 2, 5, 10) if m * _mag >= step)
    _k0 = int(math.ceil(lo / _nice - 1e-9))
    _k1 = int(math.floor(hi / _nice + 1e-9))
    for k in range(_k0, _k1 + 1):
        v = _nice * k
        y = xy(0, v)[1]
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=C_GRID, width=2)
        d.text((PAD_L - 10, y), f"￥{v:.0f}", font=f_axis, fill=C_TEXT,
               anchor="rm")

    # 单轮空态提示（挪到网格后）：原先画在网格之前，横竖网格
    # 线曾横穿提示卡（2x 下明显割裂）；挪后网格让卡片、珠点压卡可读
    # （新增监控日期只有 1 轮数据时画不出线——用户实锤误判「图坏了」，
    # 中央空态说明让「数据积累中」自己说话）
    if len(series) < 2:
        tip = f"新增监控日期 · 已积累 {len(series)} 轮 · 下一轮起显示曲线"
        f_tip = d.font(17)
        tw = d.textlength(tip, font=f_tip)
        cx, cy = (W - tw) / 2, H / 2 - 40
        d.rounded_rectangle([cx - 22, cy - 16, cx + tw + 22, cy + 16],
                            radius=10, fill=(241, 244, 248),
                            outline=DESIGN.TIP_LINE, width=2)
        d.text((cx, cy), tip, font=f_tip, fill=(90, 102, 118), anchor="lm")

    # X 轴时间刻度：均布 5 个；跨天带日期（MM-DD HH:MM），同日只有 HH:MM。
    # 按实测宽度居中 + 右缘夹紧 + 避让跳过：相邻刻度绝不互撞
    xs = sorted({round((len(series) - 1) * k / 4) for k in range(5)})
    last_r = -1.0
    for i in xs:
        ts_i = series[i][0]
        label = (ts_i.strftime("%m/%d %H:%M") if cross_day
                 else ts_i.strftime("%H:%M"))
        lw = d.textlength(label, font=f_axis)
        lx = min(max(xy(i, lo)[0] - lw / 2, PAD_L - 46), W - PAD_R - lw)
        if lx < last_r + 10:
            continue
        d.text((lx, H - PAD_B + 8), label, font=f_axis, fill=C_TEXT)
        last_r = lx + lw

    # 渐变面积：每逻辑列一竖条、条内 12 段矩形近似 alpha 渐变（质感填充）。
    # 2x 超采样下逐像素 d.point 物理量翻 4 倍过慢，且逻辑域隔行采样经
    # LANCZOS 缩回会稀释色强——列矩形物理无缝（gx+1→物理+2 恰接下列），
    # 缩回后阶梯不可见；alpha 公式与原逐像素版逐字一致
    bg = (252, 253, 254)
    for idx, color in ((1, C_DIRECT), (2, C_TRANSFER)):
        pts = [(xy(i, s[idx])[0], xy(i, s[idx])[1])
               for i, s in enumerate(series) if s[idx] is not None]
        if len(pts) < 2:
            continue
        base_y = H - PAD_B
        for gx in range(int(PAD_L), int(W - PAD_R)):
            cy = None
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                if x0 <= gx <= x1:
                    t = (gx - x0) / max(1, x1 - x0)
                    cy = y0 + (y1 - y0) * t
                    break
            if cy is None or cy >= base_y:
                continue
            seg_h = max(1.0, (base_y - cy) / 12)
            yy = cy
            while yy < base_y:
                t = (yy - cy) / max(1, base_y - cy)
                a = 0.22 * (1 - t)
                col = tuple(int(bg[k] + (color[k] - bg[k]) * a) for k in range(3))
                d.rectangle([gx, yy, gx + 1, min(yy + seg_h, base_y)], fill=col)
                yy += seg_h

    # 跨天分隔：日期变化处画浅竖线 + 底部日期标签。整体放在渐变面积
    # 之后、折线之前——渐变逐像素混色不看底下已有像素，先画线曾被
    # 盖掉下半截（实锤）
    day_labels = []   # [(x, w)] 底部日期标签位置（生成窗口小注避让用）
    if cross_day:
        seen = {series[0][0].date()}
        for i, (ts_i, *_r) in enumerate(series):
            if ts_i.date() not in seen:
                seen.add(ts_i.date())
                x = xy(i, lo)[0]
                d.line([(x, PAD_T), (x, H - PAD_B)],
                       fill=(235, 205, 160), width=4)
                lab = ts_i.strftime("%m/%d")
                lw = d.textlength(lab, font=f_axis)
                lx = min(max(x - lw / 2, PAD_L - 46), W - PAD_R - lw)
                d.text((lx, H - PAD_B + 26), lab, font=f_axis,
                       fill=(150, 120, 60))
                day_labels.append((lx, lw))

    # 生成窗口小注（口径声明：曲线是近 48 时回算窗，与明细表「近2.5时
    # 各渠道最新」、当轮推送三种时间口径图面可区分）；右缘锚定，与跨天
    # 日期标签同行相撞则左移到标签左侧
    gen_note = f"近{hours}时 · {datetime.now().strftime('%m/%d %H:%M')} 生成"
    f_note = d.font(13)
    nw = d.textlength(gen_note, font=f_note)
    nx = W - 24 - nw
    for _ in range(len(day_labels) + 1):
        for dlx, dlw in day_labels:
            if not (nx > dlx + dlw + 12 or dlx > nx + nw + 12):
                nx = dlx - nw - 20
    if nx >= PAD_L - 60:
        d.text((nx, H - PAD_B + 26), gen_note, font=f_note,
               fill=DESIGN.MUTED)

    # 悬浮文本标注（达标线/末值/最低点）先登记、末尾统一排布绘制：
    # 右缘多标签同域会叠成一团，末尾统一排布防遮挡
    labels = []

    # 达标线（虚线；直飞红/中转棕金与 webui --red/--thline 同语言，
    # 两线同红时靠右缘标签文字区分）
    for ti, (tv, lab) in enumerate(zip(thresholds,
                                       ("直飞达标线", "中转达标线"))):
        if not tv or not (lo <= tv <= hi):
            continue
        _thc = C_TH if ti == 0 else C_TH_T
        y = xy(0, tv)[1]
        x = PAD_L
        while x < W - PAD_R:
            d.line([(x, y), (min(x + 7, W - PAD_R), y)], fill=_thc, width=4)
            x += 12
        _tl = f"{lab} ￥{tv:.0f}"
        labels.append({"txt": _tl, "c": _thc, "f": f_axis,
                       "x": W - PAD_R - d.textlength(_tl, font=f_axis) - 4,
                       "y": y - 20})

    # 两条折线 + 达标点旗标 + 末值 + 最低点标注
    th_d, th_t = (thresholds + (0, 0))[:2]
    plotted = []          # 双系列全部绘制点：最低点标签做数据避让用
    ring_pts = []         # 落档位环的点（push P2-3）：环是档位语义
                          # 载体（真达标/破线/擦边），标注候选位打分对压环
                          # 加罚——密集角落白底块曾把真达标实心环裁 60%，
                          # 压普通点候选须优先于压环候选
    mins = []
    lasts = []
    for idx, color in ((1, C_DIRECT), (2, C_TRANSFER)):
        pts = [(xy(i, s[idx])[0], xy(i, s[idx])[1])
               for i, s in enumerate(series) if s[idx] is not None]
        ringed = set()        # 本系列落档位环的下标（最低点让环用）
        if not pts:
            continue
        plotted.extend(pts)
        d.line(pts, fill=color, width=6, joint="curve")
        # 珠化降密：48h/15min ≈192 点/线，r3 珠点把线宽视觉
        # 加粗成串珠——密集窗半径 3→2，稀疏窗维持
        _rp = 2 if len(pts) > 120 else 3
        for p in pts:
            d.ellipse([p[0] - _rp, p[1] - _rp, p[0] + _rp, p[1] + _rp],
                      fill=color)
        # 达标数据点环三档（与文字 🎯达标/🟩破线/🟨擦边 分档同语言，
        # 且与明细表「价格绿=达标」同一语义；webui 曲线同款：真达标=
        # 实心绿点、行情破线=描绿空心环——两档曾只差 1px 线宽不可分）
        th_v = th_d if idx == 1 else th_t
        if th_v:
            prev_qual = False
            prev_tier = 0
            # 系列真实末点：n_ser-1 曾只认全窗最后下标——
            # 某线中途断流（如中转断供）时其真实末点不落档位环
            _last_i = max(i for i, s2 in enumerate(series)
                          if s2[idx] is not None)
            for i, s2 in enumerate(series):
                v = s2[idx]
                if v is None:
                    continue
                # 旧式 3 元组（无旗标）按 「无旗标不标档」画细环
                # （纯价格口径=行情破线语义）——曾缺省 True 画粗环冒充真达标
                qual = bool(s2[idx + 2]) if len(s2) >= idx + 3 else False
                # ↩️ 回落出线图内表达（与文本建议行 ↩️ 同义）：
                # 上轮达标口径命中、本轮不再命中——回落点上方红色下箭头，
                # 曲线与列表含义一致：回落必须在图上有显式语义点，不许只在标题文字里
                if prev_qual and not qual:
                    ax, ay = xy(i, v)
                    # 顶缘钳制：点近顶部时 ay-21 曾探入标题/
                    # 小注带
                    ay = max(ay, PAD_T + 21)
                    d.polygon([(ax - 5, ay - 21), (ax + 5, ay - 21),
                               (ax, ay - 11)], fill=C_CMP)
                prev_qual = qual
                # 档位结构走 _tier_of 单源（曾内联重演=加档必漏家族
                # 第 4 副本；环段入口 `if th_v:` 守卫保证 th>0，与
                # 单源的 th 防御等价）。环色/线宽是本图渲染层映射：
                # 达标实心/破线空心同绿、擦边琥珀
                tier = _tier_of(v, th_v, qual)
                if tier == 2:
                    ring, rw = C_QUAL, 2
                elif tier == 1:
                    ring, rw = C_QUAL, 1
                elif tier == -1:
                    ring, rw = C_NEAR, 2
                else:
                    prev_tier = 0
                    continue
                # 状态入场点降密（与 webui 曲线同律）：整段躺在
                # 破线/擦边带时逐点密铺曾糊成一串环链——仅档位切换点与
                # 末点落环（▼回落箭头仍逐转换绘制）
                if tier != prev_tier or i == _last_i:
                    px, py = xy(i, v)
                    ringed.add(i)
                    ring_pts.append((px, py))
                    if tier == 2:
                        # ●实心绿=真达标（白描边防曲线穿心）
                        d.ellipse([px - 5, py - 5, px + 5, py + 5],
                                  fill=C_QUAL, outline=(255, 255, 255),
                                  width=2 * S)
                    else:
                        d.ellipse([px - 5, py - 5, px + 5, py + 5],
                                  fill=(255, 255, 255), outline=ring,
                                  width=rw * S)
                prev_tier = tier
        # 末值（折线尾端）：时刻与 X 轴末端刻度重复，只报价格；
        # 末值恰为全窗最低时与「低」标注合并（同值两条曾显冗余拥挤）。
        # 标签登记挪到双系列画完后做数据避让（与最低点同法）
        last = next(s[idx] for s in reversed(series) if s[idx] is not None)
        lo_s = min((s for s in series if s[idx] is not None), key=lambda s: s[idx])
        lx_, ly_ = pts[-1]
        merged = (lo_s[idx] == last)
        lasts.append({"idx": idx, "color": color, "lx": lx_, "ly": ly_,
                      "last": last, "merged": merged})
        # 最低点：加粗圆点 + 白环（哪天几点最低；标签挪到双系列画完后
        # 用全点集合避让选位——固定偏移在小屏/密集窗曾盖在线上）。
        # 下标显式记录：series.index 按值相等找下标，同价
        # 同旗标不同时刻会标错点
        lo_i = min((i for i, s in enumerate(series) if s[idx] is not None),
                   key=lambda i: series[i][idx])
        px, py = xy(lo_i, lo_s[idx])
        # 最低点落在档位环上时缩径让环：恒 r5 实心曾把同坐标
        # 的真达标/擦边环整个压掉——最低价是决策锚点，档位信息不可被
        # 渠道色点吞没（「列表最低带 🔥、图上最低无档」的破口）
        if lo_i in ringed:
            d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=color,
                      outline=(255, 255, 255), width=3)
        else:
            d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=color,
                      outline=(255, 255, 255), width=4)
        mins.append({"idx": idx, "color": color, "lo_s": lo_s,
                     "px": px, "py": py, "merged": merged})
    # 末值标签：右侧纵向候选位（默认点上/点下/再上）取盒内压点最少者
    for m in lasts:
        if m["merged"]:
            continue          # 与「低」同值已合并，末值不单画
        tag = f"￥{m['last']:.0f}"
        tw = d.textlength(tag, font=f_mark)
        tx = min(m["lx"] + 6, W - 100)
        best = None
        for dy in (-26, 12, -48):
            ty = m["ly"] + dy
            if ty < PAD_T + 2 or ty + 20 > H - PAD_B:
                continue
            box = (tx - 4, ty - 2, tx + tw + 4, ty + 20)
            n = sum(1 for (qx, qy) in plotted
                    if box[0] <= qx <= box[2] and box[1] <= qy <= box[3])
            n += 2 * sum(1 for (qx, qy) in ring_pts
                         if box[0] <= qx <= box[2] and box[1] <= qy <= box[3])
            cand = (n, abs(dy + 26), tx, ty)
            if best is None or cand < best:
                best = cand
        if best is None:
            best = (0, 0, tx, m["ly"] - 26)
        labels.append({"txt": tag, "c": m["color"], "f": f_mark,
                       "x": best[2], "y": best[3]})

    # 最低点标签：候选位（点下/点上 × 居中/侧偏）取「盒内压到的数据点」
    # 最少者；同分优先点下（下方常是渐变淡区）。避让不了仍走白底块兜底
    for m in mins:
        lo_s, idx, color = m["lo_s"], m["idx"], m["color"]
        tag = f"低 ￥{lo_s[idx]:.0f} {lo_s[0].strftime('%m/%d %H:%M')}"
        tw = d.textlength(tag, font=f_mark)
        px, py = m["px"], m["py"]
        best = None
        for dy in (8, -26):
            for dx in (0, tw * 0.35, -tw * 0.35):
                if dy > 0 and py + 30 > H - PAD_B + 6:
                    continue          # 下方贴底轴，放弃下方候选
                if dy < 0 and py - 26 < PAD_T + 2:
                    continue          # 上方贴顶，放弃上方候选
                tx = min(max(px - tw / 2 + dx, PAD_L + 2),
                         W - PAD_R - tw - 2)
                ty = py + dy
                box = (tx - 4, ty - 2, tx + tw + 4, ty + 20)
                n = sum(1 for (qx, qy) in plotted
                        if box[0] <= qx <= box[2] and box[1] <= qy <= box[3])
                n += 2 * sum(1 for (qx, qy) in ring_pts
                             if box[0] <= qx <= box[2] and box[1] <= qy <= box[3])
                cand = (n, abs(dy), abs(dx), tx, ty)
                if best is None or cand < best:
                    best = cand
        if best is None:
            tx = min(max(px - tw / 2, PAD_L + 2), W - PAD_R - tw - 2)
            ty = max(py - 26, PAD_T + 2)
        else:
            _, _, _, tx, ty = best
        labels.append({"txt": tag, "c": color, "f": f_mark, "x": tx, "y": ty})

    # 统一纵向避让：按 y 排序，与已放置标签相交（矩形级）则 +6px 下推。
    # 绘制用「白底圆角块 + 描字」替代 3×3 halo——密集折线区 halo 柔边仍花，
    # 底块彻底隔开背景（先画全部底块再画字，后块不压先字）
    for a in labels:
        a["w"] = d.textlength(a["txt"], font=a["f"])
    labels.sort(key=lambda a: a["y"])

    def _hit(a, b):
        # 标签底块矩形（左右各留 4、高 21 + 2 间距）相交检测
        return not (a["x"] + a["w"] + 4 < b["x"] - 4 or
                    b["x"] + b["w"] + 4 < a["x"] - 4 or
                    a["y"] + 23 <= b["y"] or b["y"] + 23 <= a["y"])

    # 顶部两行小注（图例口径注 + 点环分档注，固定 @y46）登记为静态障碍
    # 避让系统原本只见已放置标签、不见固定小注，白底标签
    # 下推曾压到小注上。障碍矩形 [PAD_L, W-24] 全宽覆盖，y=44 略高于
    # 字顶——标签下限 PAD_T+2=66 仍会判撞、自动再下推一档绕行
    placed = [{"x": PAD_L, "w": W - PAD_L - 24, "y": 44}]
    for a in labels:
        for _ in range(60):
            if not any(_hit(a, b) for b in placed):
                break
            a["y"] += 6
        a["y"] = min(max(a["y"], PAD_T + 2), H - PAD_B - 20)
        # 夹逼可能把下推成果压回重叠区（末尾硬夹逼后曾无二次校验，实锤
        # 产出叠字图）：矩形级校验——仍撞则水平错开（贴到撞击标签左侧），
        # 左侧放不下再纵向逐行扫描找空位，保证两两不相交
        for _ in range(30):
            b0 = next((p for p in placed if _hit(a, p)), None)
            if b0 is None:
                break
            ax2 = b0["x"] - a["w"] - 16
            if (ax2 >= PAD_L + 2 and not any(
                    _hit({"x": ax2, "w": a["w"], "y": a["y"]}, p)
                    for p in placed)):
                a["x"] = ax2
                continue
            if a["y"] + 6 > H - PAD_B - 20:
                for ty in range(PAD_T + 2, H - PAD_B - 19, 6):
                    if not any(_hit({"x": a["x"], "w": a["w"], "y": ty}, p)
                               for p in placed):
                        a["y"] = ty
                        break
                break   # 全域扫描过一轮即终局（标注数 << 可放行数，必有解）
            a["y"] += 6
        placed.append(a)
    for a in labels:
        d.rounded_rectangle([a["x"] - 4, a["y"] - 2, a["x"] + a["w"] + 4,
                             a["y"] + 19], radius=5, fill=DESIGN.CARD,
                            outline=DESIGN.TIP_LINE, width=2)
    for a in labels:
        # 标注白底块上的文字面：中转线色 C_TRANSFER 作文字 3.78:1 欠 AA
        # ——换文字面 C_TRANSFER_TX（白卡 5.40:1，P2-1 文字/图形
        # 分离的第三消费点：组头/胶囊、总表副行之外的标注文字）；线体、
        # 珠点等图形消费保 C_TRANSFER 本体不动
        d.text((a["x"], a["y"]), a["txt"], font=a["f"],
               fill=C_TRANSFER_TX if a["c"] == C_TRANSFER else a["c"])

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img = img.resize((W, H), Image.LANCZOS)   # 2x 缩回对外尺寸 936×460
    img.save(out_path)
    return out_path


# ---- 图床上传 ----
# freeimage.host 官方文档公开的匿名上传 key（免注册、永久保存、直链 iili.io）
FREEIMAGE_KEY = "6d207e02198a847aa98d0a2a901485a5"

# freeimage 上传端点已封禁（全量 400/111），
# 每轮先打注定失败的请求再降级=每轮多一次失败请求+日志噪音。连败 ≥3
# 跳过主床直走 pixhost，此后每 10 次上传重探一次（恢复即自动回归——
# pixhost 直链有保存期，freeimage 才是长期载体，次序不可反转只可退避）
_FREEIMG_STATE = {"n": 0, "probe": 0}


def _upload_pixhost(png_path, logger):
    """备用图床 pixhost v2（免 API key）：上传后从 show 页解析原图直链
    （imgN.pixhost.to/images/…，t3./thumbs/ 是缩略图）。freeimage
    对 key 上传全量 400/111，此为自动降级通道。"""
    try:
        import re as _re
        with open(png_path, "rb") as _f:
            r = httpx.post(
                "https://api.pixhost.cc/images",
                data={"content_type": "0", "max_th_size": "500"},
                files={"img": (os.path.basename(png_path),
                               _f, "image/png")},
                timeout=60, trust_env=False,
                headers={"Accept": "application/json",
                         "User-Agent": "Mozilla/5.0"})
        show = ((r.json() or {}).get("show_url") or "").replace(
            "pixhost.cc", "pixhost.to")
        if not show:
            logger.warning("[图床] pixhost 无 show_url: %s", r.text[:120])
            return None
        page = httpx.get(show, timeout=40, trust_env=False,
                         headers={"User-Agent": "Mozilla/5.0"})
        m = _re.search(
            r'https://img\d+\.pixhost\.to/images/[^"\']+?\.(?:png|jpg)',
            page.text)
        return m.group(0) if m else None
    except Exception as e:
        logger.warning("[图床] pixhost 上传异常: %s", e)
        return None


def upload_freeimage(png_path, logger):
    st = _FREEIMG_STATE
    if st["n"] >= 3:
        st["probe"] += 1
        if st["probe"] % 10 != 1:   # 1, 11, 21… 重探
            return _upload_pixhost(png_path, logger)
    try:
        with open(png_path, "rb") as f:
            # trust_env=False：绕过系统代理直连——公司代理对 iili.io
            # 系图床的 HTTPS 会随机掐断（EOF in violation of protocol），
            # 历次"上传异常"均为代理干扰所致
            r = httpx.post(
                "https://freeimage.host/api/1/upload",
                data={"key": FREEIMAGE_KEY, "action": "upload", "type": "file"},
                files={"source": f}, timeout=60, trust_env=False,
            )
        url = ((r.json().get("image") or {}).get("url"))
        if url:
            st["n"] = 0
            return url
    except Exception as e:
        st["n"] += 1
        logger.warning("[走势] freeimage 上传异常: %s", e)
        return _upload_pixhost(png_path, logger)
    st["n"] += 1
    logger.warning("[走势] freeimage 上传失败（%s），降级 pixhost",
                   r.text[:120])
    return _upload_pixhost(png_path, logger)


def upload_ghimg(png_path, ih, logger):
    """GitHub 图库上传（Contents API 单文件 PUT，公开库）。

    显示 URL=jsDelivr（cdn.jsdelivr.net/gh/<repo>@main/<path>）：
    路径含日期目录+时分戳，文件名唯一即无 CDN 陈旧缓存（新文件
    首取即回源）。api.github.com 直连失败按 ih.proxy 重试一次——
    上传端可有代理，显示端必须读者网络直连可达（双端约束）。
    repo=owner/name，token=GitHub PAT（contents:write 权限）。"""
    repo = (ih.get("repo") or "").strip()
    token = (ih.get("token") or "").strip()
    if not repo or not token:
        return None
    stem, ext = os.path.splitext(os.path.basename(png_path))
    now = datetime.now()
    path = (f"charts/{now.strftime('%Y%m%d')}/"
            f"{stem}_{now.strftime('%H%M')}{ext}")
    with open(png_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    payload = {"message": f"chart: {stem}", "content": content}
    proxy = (ih.get("proxy") or "").strip() or None
    try:
        r = httpx.put(url, json=payload, headers=headers,
                      timeout=20, trust_env=False)
        if r.status_code not in (200, 201) and proxy:
            r = httpx.put(url, json=payload, headers=headers,
                          timeout=60, proxy=proxy)
    except Exception as e:
        if not proxy:
            logger.warning("[图床] GitHub 上传异常: %s", e)
            return None
        try:
            r = httpx.put(url, json=payload, headers=headers,
                          timeout=60, proxy=proxy)
        except Exception as e2:
            logger.warning("[图床] GitHub 上传异常(代理): %s", e2)
            return None
    if r.status_code in (200, 201):
        return f"https://cdn.jsdelivr.net/gh/{repo}@main/{path}"
    logger.warning("[图床] GitHub 上传失败 %s: %s",
                   r.status_code, r.text[:120])
    return None


def upload_smms(png_path, token, logger):
    try:
        with open(png_path, "rb") as _f:
            r = httpx.post(
                "https://sm.ms/api/v2/upload",
                headers={"Authorization": token},
                files={"smfile": _f},
                timeout=60, trust_env=False,
            )
        obj = r.json()
    except Exception:
        logger.warning("[走势] 图床响应异常")
        return None
    if str(obj.get("code")) in ("success", "0") and (obj.get("data") or {}).get("url"):
        return obj["data"]["url"]
    logger.warning("[走势] 图床上传失败: %s", str(obj)[:200])
    return None


def upload_chart(png_path, cfg, logger, ih=None):
    """按配置选图床（image_host.provider）：ghimg（GitHub 图库，
    主通路）/ freeimage（免注册，上传端已死备案）/ smms（官方停止
    活跃更新，不推荐）。上传失败统一降级 pixhost 终极兜底。

    图床选型双端约束：上传端在服务器（可有代理），显示端在读者手机
    （必须读者网络直连可达）——两端网络条件不同，同一图床两端结论
    可以相反，验证显示端必须绕代理直连实测（服务器走代理取到 200
    证明不了手机拉得到），读者实报看不到图是一手证据。pixhost 上传
    可达但大陆显示端直连不可达（手机钉钉拉不到图），仅作上传兜底；
    freeimage 上传端直连超时且经代理被掐；sm.ms 官方停止活跃更新。
    ghimg=Contents API 传公开图库、显示走 jsDelivr（路径含时分戳防
    CDN 陈旧缓存），api.github.com 直连失败按 ih.proxy 重试一次。
    ：调用方可直传已解析的 image_host 配置（alerter 无 cfg 全量，
    main.py 注入用户级 notifier.image_host）。
    注意 ih 空 dict=「未配置」语义（直走 pixhost），勿用 or 判空。"""
    if ih is None:
        ih = _image_host_cfg(cfg or {})
    provider = (ih.get("provider") or "").strip().lower()
    if provider == "freeimage":
        return upload_freeimage(png_path, logger)
    if provider == "ghimg" and (ih.get("repo") or "").strip() \
            and (ih.get("token") or "").strip():
        url = upload_ghimg(png_path, ih, logger)
        if url:
            return url
        logger.warning("[走势] GitHub 图库失败，降级 pixhost")
    if provider == "smms" and (ih.get("token") or "").strip():
        url = upload_smms(png_path, ih["token"].strip(), logger)
        if url:
            return url
        logger.warning("[走势] sm.ms 失败，降级 pixhost")
    return _upload_pixhost(png_path, logger)


# ---- 近期明细合并（供告警/控制台补位被限流平台） ----
def recent_platform_flights(db_path, from_city, to_city, date, hours=6):
    """返回 {platform: (age_hours, flights)}——各平台最近一次成功航班明细。

    当轮某平台被限流无明细时，用其近 N 小时最后成功明细补位展示
    （航班班期/时刻日内不变，价格可能滞后，调用方须标注并只用于展示）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, extra, fetched_at FROM flight_prices "
        "WHERE from_city=? AND to_city=? AND depart_date=? AND extra != '' "
        "ORDER BY id DESC", (from_city, to_city, date)).fetchall()
    conn.close()
    now = datetime.now()
    out = {}
    for r in rows:
        p = r["platform"]
        if p in out:
            continue
        try:
            ts = datetime.strptime(r["fetched_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        age = (now - ts).total_seconds() / 3600
        if age > hours:
            continue
        try:
            obj = json.loads(r["extra"])
        except Exception:
            continue
        if isinstance(obj, list) and obj:
            out[p] = (age, obj)
    return out


# ---- 组合出口 ----
def _user_scope(cfg, user=""):
    """返回 (notifier配置, 原始routes列表)：按用户名定位，兼容旧单用户格式。"""
    for u in (cfg.get("users") or []):
        if str(u.get("name")) == user:
            return (u.get("notifier") or {}), u.get("routes") or []
    return (cfg.get("notifier") or {}), cfg.get("routes") or []


def _image_host_cfg(cfg: dict) -> dict:
    """图床配置：全局 notifier.image_host 为准，缺失时回落第一用户
    （多租户改造把 image_host 挪进了用户级，读全局导致走势图静默跳过）。"""
    ih = (cfg.get("notifier") or {}).get("image_host") or {}
    if (ih.get("provider") or "").strip():
        return ih
    for u in cfg.get("users") or []:
        ih2 = (u.get("notifier") or {}).get("image_host") or {}
        if (ih2.get("provider") or "").strip():
            return ih2
    return ih


def _chart_routes(cfg):
    """走势图/日报覆盖的航线 = 全部用户航线去重，剔除已停用（enabled:false）。

    扫描端（main._build_users）同样过滤——两处独立关口缺一不可：停用航线的
    历史数据仍被画进日报时，用户会收到「无渠道明细」空小节+一张过期走势图
    （实锤形态：SHA→URC 停用后日报仍在报它）。"""
    _, all_routes = _user_scope(cfg)
    for u in (cfg.get("users") or []):  # 多租户：合并所有用户航线（去重）
        for r in (u.get("routes") or []):
            if r not in all_routes:
                all_routes.append(r)
    return [r for r in all_routes if r.get("enabled") is not False]


def prepare_round_charts(cfg, logger, route_override=None):
    """生成并上传走势图。route_override=(from,to,date) 时只画该航线
    （多租户扫描按航线调用，一次上传多用户复用）。返回 {(from,to,date): url}。"""
    ih = _image_host_cfg(cfg)
    if not (ih.get("provider") or "").strip():
        return {}
    all_routes = _chart_routes(cfg)
    db_path = _anchored_db(cfg)
    charts = {}
    seen = set()
    for r in all_routes:
        for date in r.get("dates", []):
            key = (r["from"], r["to"], date)
            if key in seen:
                continue
            if route_override and key != tuple(route_override):
                continue
            seen.add(key)
            # 单航线隔离：一条航线的脏数据/上传异常曾中断
            # 整个循环，日报整批丢图（对账循环有 try，此处漏）
            try:
                dmin = (r.get("dep_time_min") or "").strip()
                dmax = (r.get("dep_time_max") or "").strip()
                series = _rounds(
                    db_path, r["from"], r["to"], date,
                    r.get("transfer_arrival_max", "02:00"),
                    layover_min=int(r.get("transfer_layover_min", 0) or 0),
                    dep_win=(dmin, dmax) if (dmin or dmax) else None,
                    rc=r,
                    th_d=float(r.get("alert_direct", 0) or 0),
                    th_t=float(r.get("alert_transfer", 0) or 0))
                if not series:
                    continue
                png = os.path.join("data", f"trend_{r['from']}_{r['to']}_{date}.png")
                render_chart(series,
                             f"{r.get('from_name', r['from'])}→{r.get('to_name', r['to'])} {date[5:].replace('-', '/')} 价格走势",
                             thresholds=(float(r.get("alert_direct", 0) or 0),
                                         float(r.get("alert_transfer", 0) or 0)),
                             out_path=png, hours=48)   # 与 _rounds hours 同源，改窗两处同步
                url = upload_chart(png, cfg, logger)
                if url:
                    charts[key] = url
            except Exception as e:
                logger.warning("[走势] %s→%s %s 生成失败（跳过不影响其余航线）: %s",
                               r["from"], r["to"], date, e)
    return charts


def _route_latest_flights(db_path, fc, tc, date, max_age_min=150,
                          dep_win=None):
    """该航线各平台最近一次有明细的 extra 合并池（仅新鲜数据，不带补位）。

    dep_win=(dmin,dmax)：出发窗口与列表链同参过滤——日报 KPI/🎯 若不
    同窗，会与当轮推送各说各话（窗口外班次上「达标」）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, extra, fetched_at FROM flight_prices "
        "WHERE extra != '' AND from_city=? AND to_city=? AND depart_date=? "
        "ORDER BY id DESC", (fc, tc, date)).fetchall()
    conn.close()
    out, got = [], set()
    for r in rows:
        p = r["platform"]
        if p in got:
            continue
        try:
            ts = datetime.strptime(r["fetched_at"][:19], "%Y-%m-%d %H:%M:%S")
            age_h = (datetime.now() - ts).total_seconds() / 3600
            if age_h * 60 > max_age_min:
                continue
        except Exception:
            continue
        got.add(p)
        try:
            obj = json.loads(r["extra"])
        except Exception:
            continue
        if isinstance(obj, list):
            from core.flightnorm import normalize as _fnorm
            for f in obj:
                if isinstance(f, dict) and "price" in f:
                    g = dict(f)
                    g["_platform"] = p
                    # 时效角标（_plat_tag 自动渲染「·Nh前」）：日报池是
                    # 近 2.5 时每平台最新一份，最旧行与刚抓价图上无区分
                    # 曾是信息密度短板——告警池补位行同款角标对齐；
                    # ≥1h 才标（0.5h 渲染成「0h前」是负信息）
                    g["_stale_h"] = round(age_h, 1) if age_h >= 1 else 0
                    _fnorm(g, date)
                    if dep_win and not Alerter._dep_in_window(
                            _pad_hhmm(g.get("depTime")),
                            dep_win[0], dep_win[1]):
                        continue
                    try:
                        g["price"] = round(float(g["price"]))
                    except (TypeError, ValueError):
                        pass
                    out.append(g)
    # 同指纹衔接补全：qunar 列表页无停留时长，缺 layoverM 的链在配置了
    # 衔接下限时会被 _split_market_pool 滤掉——日报「中转最低」因此比
    # 同轮心跳/控制台偏高（实锤 2164 vs 2190 同轮两价）
    try:
        Alerter._propagate_layover(out)
        # 决策字段同步补全（cabin/meal/prate/plane）：日报
        # 明细次行信息密度与告警池对齐
        Alerter._propagate_fields(out)
    except Exception:
        pass
    # 跨渠道孤低价守卫（第五消费端）：日报 KPI/明细表/查现价
    # 选台同一防线——防幻影窗口内的异源低价推进
    # KPI 与明细（池各平台「最新行」可错峰 ≤2.5h，锚语义弱于同轮，
    # 但「单渠道整行异源」的幻影场景仍成立）
    _dgrp = {}
    for f in out:
        _dgrp.setdefault(bool(f.get("transCity")), []).append(f)
    for _g in _dgrp.values():
        Alerter._mark_xchan(_g)
    out = [f for f in out if not f.get("_xphan")]
    return out


def _split_market_pool(fs, rc):
    """日报表格行池拆分（与走势 _rounds 同参同口径）：
    directs=直飞行情池；mkt_t=中转行情池——到达约束+衔接下限过滤，
    不限直挂（直挂仅达标判定参与，否则历史数据长段空窗）。
    中转行就地打绿旗 _qual=价格≤阈值 且 全口径 _transfer_ok（含直挂），
    行情与达标两层语义各自表达、互不混池。"""
    # 脏价守卫：非数值/越界价行不入池——曾穿透到 min(key=
    # price) 抛 TypeError、￥{:.0f} 抛 ValueError，整张日报明细表图被
    # 外层 try 跳过只剩「生成失败」文本（查现价池第五消费端已守，此处漏）
    fs = [f for f in fs
          if isinstance(f.get("price"), (int, float))
          and PRICE_MIN <= f["price"] <= PRICE_MAX]
    am = rc.get("transfer_arrival_max", "02:00") or "02:00"
    lay_min = int(rc.get("transfer_layover_min", 0) or 0)
    at_ = float(rc.get("alert_transfer", 0) or 0)
    ad = float(rc.get("alert_direct", 0) or 0)
    directs = [f for f in fs if not f.get("transCity")]
    for f in directs:   # 直飞行同打绿旗：全表「价格绿=达标」同一语义
        f["_th"] = ad   # 琥珀擦边档判定（_price_color）——曾从不写，
        f["_qual"] = bool(ad > 0 and _qual_price(f) <= ad)   # 日报表
        # 恒两档色、与同日报走势环/KPI 两套分档语言（修复）
    mkt_t = []
    for f in fs:
        if not f.get("transCity") or not Alerter._arrival_ok(f, am):
            continue
        lm = f.get("layoverM")
        if not (lay_min <= 0 or (isinstance(lm, int) and lm >= lay_min)):
            continue
        f["_th"] = at_
        f["_qual"] = bool(at_ > 0 and _qual_price(f) <= at_
                          and Alerter._transfer_ok(f, rc))
        mkt_t.append(f)
    return directs, mkt_t


def build_and_push(cfg, logger, notifier, user=""):
    """为该用户的航线生成走势图并推送；返回是否成功。"""
    ih = _image_host_cfg(cfg)
    if not (ih.get("provider") or "").strip():
        logger.info("[走势] 未配置图床 provider，跳过图文报告")
        return False
    ncfg, routes_cfg = _user_scope(cfg, user)
    charts = prepare_round_charts(cfg, logger)
    # 过滤为该用户自己的航线
    mine = {(r["from"], r["to"], d) for r in routes_cfg for d in r.get("dates", [])}
    charts = {k: v for k, v in charts.items() if k in mine}
    if not charts:
        logger.info("[走势] 暂无可画数据或上传失败")
        return False
    db_path = _anchored_db(cfg)
    desp = "#### 📈 每日价格日报\n\n"
    # 图例行撤入走势图（图内点环分档小注与本行同款四档，双份
    # 冗余；无链接信息一律入图的定律）——文本只留口径时间戳。短式
    # 原行 47 半角无守卫手机必折行；「档位图例见图内」
    # 与图内小注双份冗余删
    desp += f"> ⏱ {datetime.now().strftime('%m/%d %H:%M')} · 近2.5时口径\n\n"
    first = True
    for (fc, tc, date), url in sorted(charts.items(), key=lambda kv: kv[0]):
        # 日期精确匹配优先（同一城市对多日期各自配阈值/窗口是明示场景，
        # 按城市对取首条曾让第 2+ 日期小节的 KPI 阈值/明细 meta 用错配置
        # ——同屏走势图对、KPI 错），无精确匹配再回退城市对
        rc = next((r for r in routes_cfg
                   if r.get("from") == fc and r.get("to") == tc
                   and date in (r.get("dates") or [])),
                  next((r for r in routes_cfg
                        if r.get("from") == fc and r.get("to") == tc), {}))
        # 双保险：charts 端已按 enabled 过滤，这里再挡一次热载中途停用
        # 后的残留图（扫描端不采停用航线，其小节只会是空数据+过期图）
        if rc.get("enabled") is False:
            continue
        names = (rc.get("from_name") or fc, rc.get("to_name") or tc)
        first = False
        # 短日期 MM/DD 与主推送 _date_short 同式；H2 曾渲染成大标题。
        # 行宽守卫与主链路同法（长城市对 #### 直落 >20 全角
        # 窄屏折行断点不受控——日期下沉独立引用行）
        _d_md = date[5:].replace("-", "/")
        if _dw_line(f"#### {names[0]}→{names[1]} {_d_md}") <= 40:
            desp += f"#### {names[0]}→{names[1]} {_d_md}\n\n"
        else:
            desp += f"#### {names[0]}→{names[1]}\n\n> {_d_md}\n\n"
        dmin = (rc.get("dep_time_min") or "").strip()
        dmax = (rc.get("dep_time_max") or "").strip()
        dep_win = (dmin, dmax) if (dmin or dmax) else None
        fs = _route_latest_flights(db_path, fc, tc, date, dep_win=dep_win)

        def _p7_note(long=True):
            """近 7 天直飞最低参照（空小节补偿/未设线 KPI 共用，一次回算）"""
            try:
                _h7 = _rounds(db_path, fc, tc, date,
                              rc.get("transfer_arrival_max", "02:00") or "02:00",
                              hours=168,
                              layover_min=int(rc.get("transfer_layover_min", 0) or 0),
                              dep_win=dep_win, rc=rc,
                              th_d=float(rc.get("alert_direct", 0) or 0),
                              th_t=float(rc.get("alert_transfer", 0) or 0))
                _p7 = [(r[1], r[0]) for r in _h7 if r[1]]
                if _p7:
                    _v, _t = min(_p7)
                    return (f" · 近7天直飞最低 ￥{_v}（{_t:%m/%d %H:%M}）"
                            if long else f"　近7天最低 ￥{_v:.0f}")
            except Exception:
                pass
            return ""

        if not fs:
            # 空明细不再静默：整节只剩一张裸图曾让用户以为日报坏了一半；
            # 补近 7 天直飞最低做参照（数据现成，仅空小节时多一次回算）。
            # 行宽守卫：补偿行裸拼近 50 半角必折行、断点不受控
            desp += (_fit_line(
                "> 该日期近 2.5 时无渠道明细，KPI 与明细表省略" + _p7_note(),
                fallbacks=["> 该日期近 2.5 时无渠道明细" + _p7_note(),
                           "> 该日期近 2.5 时无渠道明细"]) + "\n\n"
                + f"![走势]({url})\n\n")
            continue
        directs, mkt_t = _split_market_pool(fs, rc)
        if not directs and not mkt_t:
            # 明细在但全被到达/衔接约束滤掉：同款补偿——「标题+裸图」
            # 空小节曾直接推到群里，与空明细小节不对称
            desp += (_fit_line(
                "> 该日期明细均不满足到达/衔接约束，KPI 与明细表省略"
                + _p7_note(),
                fallbacks=["> 该日期明细均不满足到达/衔接约束" + _p7_note(),
                           "> 该日期明细均不满足到达/衔接约束"]) + "\n\n"
                + f"![走势]({url})\n\n")
            continue
        # KPI 图内化（定律收口）：行情数字撤文本、进明细表图
        # summary 行（脱离上下文也能看懂当前行情——该参数本就为此设计）；
        # 图生成/上传失败时退回文本 KPI（信息不能跟图一起消失）。
        # 档位词与走势环四档同义：真达标/行情破线/擦边/差￥N
        # （统一词序「行情破线」=环标小注同词；diff==0 曾不问
        # 口径直读「达线」，同价时文本兜底 🟩（行情价）而图内已读达标）
        ad = float(rc.get("alert_direct", 0) or 0)
        at_ = float(rc.get("alert_transfer", 0) or 0)

        def _kpi_txt(label, price, th, qual_hit):
            """图内 KPI 摘要（PNG 无 emoji 字形，档位用文字词）——
             单源 core.alerter.kpi_tier_txt（multi 总表图内
            summary 同语言）；恰达线/擦边词面随单源收口。"""
            return kpi_tier_txt(label, price, th, qual_hit)

        def _kpi_summary():
            out = []
            if directs:
                d_low = min(directs, key=lambda f: f["price"])
                out.append(_kpi_txt("直飞", d_low["price"], ad,
                                    bool(d_low.get("_qual"))))
            if mkt_t:
                m_low = min(mkt_t, key=lambda f: f["price"])
                out.append(_kpi_txt("中转", m_low["price"], at_,
                                    bool(m_low.get("_qual"))))
            return " · ".join(out)

        def _kpi_fallback():
            """图挂时的文本 KPI 兜底（emoji 档位，主推送同语言）"""
            t = ""
            if directs:
                d_low = min(directs, key=lambda f: f["price"])
                t += _kpi("直飞", d_low["price"], ad,
                          bool(d_low.get("_qual"))) + "\n\n"
            if mkt_t:
                m_low = min(mkt_t, key=lambda f: f["price"])
                t += _kpi("中转", m_low["price"], at_,
                          bool(m_low.get("_qual"))) + "\n\n"
            return t

        def _kpi(label, price, th, qual_hit):
            """千分位去掉；差额「低/差￥N」；行情价破线但达标口径
            未破（非直挂/衔接不达标）附「（行情价）」短注——与主
            推送「低价却没弹窗」同款解释、同措辞；行宽守卫与主链
            路同款（>40 半角依次丢注→百分比→裸价）。"""
            mark, gap, tail = "", "", ""
            if th:
                diff = price - th
                # 差额词单源：恰达线非达标读「行情破线」
                gap = gap_txt(price, th, qual_hit)   # 与主推送 KPI 同式
                # 尾注仅严格破线挂（与主链路 mkt_note 同律）：
                # 恰达线 diff==0 时 gap 已是完整词面「行情破线」，
                # 再叠「（行情价）」同屏双行情标
                if price < th:
                    mark, tail = (("🎯 ", "") if qual_hit
                                  else ("🟩 ", "（行情价）"))
                elif price == th:
                    mark = "🎯 " if qual_hit else "🟩 "
                else:
                    # 超线默认态不加点（🟦 满屏蓝=噪音，差额自表达）；
                    # 🟨 只给擦边（≤10%）
                    mark = "🟨 " if diff / th <= NEAR_RATIO else ""
            # 加粗=「该出手」扫读梯度（与主链路统一仅 🎯 粗，
            # 🟩/🟨 emoji 单信号——三处三律曾稀释主次）
            px = f"￥{price:.0f}"
            px = f"**{px}**" if mark == "🎯 " else px
            base = f"{mark}{label} {px}"
            if not th:
                # 未设线也给参照值（裸「（未设线）」无从判断贵贱）
                return _fit_line(base + "（未设线）" + _p7_note(False),
                                 fallbacks=[base + "（未设线）"])
            mid = base + f"　线￥{th:.0f}　{gap}"
            return _fit_line(mid + tail, fallbacks=[mid, base])

        # 走势是日报主角（与 title「走势与明细」同序）：走势在前、明细表图随后
        desp += f"![走势]({url})\n\n"
        if fs:
            out_png = f"data/flights_table_{fc}{tc}_{date}.png"
            # 「各渠道最低」子节补齐：告警单/总表已有，日报
            # 整篇必须有渠道分解。数据源=近 2.5 时各平台最新池（有明细
            # 才入池，无「全线价」形态——如实只列有明细渠道），组态与
            # 告警路径 _plat_mins_for 同构 (价, has_dtl) 元组按价升序
            _pmins = {}
            for _f2 in (directs + mkt_t):
                _p2 = _f2.get("_platform") or "?"
                _v2 = _f2.get("price")
                if not isinstance(_v2, (int, float)) or not PRICE_MIN <= _v2 <= PRICE_MAX:
                    continue
                if _p2 not in _pmins or _v2 < _pmins[_p2][0]:
                    _pmins[_p2] = (_v2, True)
            _pmins = dict(sorted(_pmins.items(), key=lambda kv: kv[1][0]))
            _meta = {"layover_min": int(rc.get("transfer_layover_min", 0) or 0),
                     "arrival_max": rc.get("transfer_arrival_max",
                                           "02:00") or "02:00",
                     "plat_mins": _pmins}
            # 日报补同班比价组：实时总表已有 compare，日报
            # 缺席=比价离群警示在日报不可见。与实时同源：同一指纹分组
            # + _compare_rows 同一行组装 + 渲染端 compare 分支零改动
            _comp = []
            try:
                _cands = Alerter._fp_cands(
                    [{"date": date, "pool": directs + mkt_t}], top_n=4)
                if _cands:
                    _comp = Alerter._compare_rows(_cands)
            except Exception as _e:
                logger.debug("[日报] 比价组组装失败（不阻塞明细表）: %s", _e)
            _rows = [("direct", directs), ("transfer", mkt_t, None, _meta)]
            if _comp:
                _rows.append(("compare", _comp))
            try:
                render_flights_table(
                    _rows,
                    f"{names[0]}→{names[1]} {date[5:].replace('-', '/')} 最优明细 TOP5", out_png,
                    summary=_kpi_summary(),
                    stamp_note="近2.5时各渠道最新")
                turl = upload_freeimage(out_png, logger)
                if turl:
                    desp += f"![明细表]({turl})\n\n"
                else:
                    # 后图是明细唯一载体，挂了必须留痕；KPI 同步
                    # 退回文本（本轮 KPI 已随 summary 沉入失败的图里）
                    desp += ("> ⚠️ 明细表上传失败，本节无明细图\n\n"
                             + _kpi_fallback())
            except Exception as e:
                logger.warning("[日报] 表格图生成失败: %s", e)
                desp += ("> ⚠️ 明细表生成失败，本节无明细图\n\n"
                         + _kpi_fallback())
        # 小节尾「打开渠道查现价」：日报整篇零可点链接时，用户想看
        # 某航线只能回翻聊天记录——可点链接必须随小节给出。渠道与主推送同规则（同价指纹优选
        # 去哪儿/携程，无则最低价所在渠道），链接与爬虫主路径同源
        try:
            from types import SimpleNamespace
            _pool = directs + mkt_t
            # 选台基带价合法守卫：price=0/异常行曾被 min 选为
            # 「最低价所在渠道」（同函数 _pmins 有 0<v≤50000 守卫，此处漏）
            _pool = [f for f in _pool
                     if isinstance(f.get("price"), (int, float))
                     and PRICE_MIN <= f["price"] <= PRICE_MAX]
            _plat = (Alerter._pref_platform(
                min(_pool, key=lambda f: f["price"]), _pool)
                if _pool else "")
            # 无合法行不再兜底 qunar（拔除 清理漏网：
            # 用户未启用去哪儿仍给去哪儿入口=挂羊头；_build_view_url
            # 对空平台返回 ""，下方 if _vu 自然跳过——宁缺勿错）
            _vs = SimpleNamespace(from_code=fc, to_code=tc,
                                  from_name=names[0], to_name=names[1])
            # None 占 self（方法体不消费 self；webui._view_url 同范式在
            # 案）—— P1 修复：原 3 参调用恒 TypeError，被下方
            # except 吞成静默，🔍 链接自引入从未产出过（72 条日报 0 次）
            _vu = Alerter._build_view_url(None, _vs, date, _plat)
            if _vu:   # 空 URL 剥壳出纯文本曾产出死链 [文字]()，直接跳过
                _pcn = Alerter.PLATFORM_CN.get(_plat, _plat)
                desp += f"[🔍 打开{_pcn}查现价]({_vu})\n\n"
        except Exception as _vu_exc:
            logger.debug("日报「查现价」链接构建失败: %s", _vu_exc)
    # 缺图对账：图床失败曾让整条航线小节静默蒸发——有数据
    # 却无图无提示（与主推送 ⚠️ 缺图行不对称）。只对「有扫描数据但图
    # 缺失」的日期补对账行，纯新航线（48h 无数据）不制造噪音
    for r in routes_cfg:
        if r.get("enabled") is False:
            continue
        am = r.get("transfer_arrival_max", "02:00") or "02:00"
        _dmin = (r.get("dep_time_min") or "").strip()
        _dmax = (r.get("dep_time_max") or "").strip()
        _dw = (_dmin, _dmax) if (_dmin or _dmax) else None
        for date in r.get("dates") or []:
            if (r["from"], r["to"], date) in charts:
                continue
            try:
                has = _rounds(db_path, r["from"], r["to"], date, am,
                              layover_min=int(r.get("transfer_layover_min", 0) or 0),
                              dep_win=_dw, rc=r,
                              th_d=float(r.get("alert_direct", 0) or 0),
                              th_t=float(r.get("alert_transfer", 0) or 0))
            except Exception:
                has = []
            if has:
                nm = (f"{r.get('from_name') or r['from']}"
                      f"→{r.get('to_name') or r['to']}")
                # 全库 `> ` 引用行统一走行宽守卫（曾唯一漏网残留：
                # 长航线名 50+ 半角必折行且断点不受控）。（推送
                # 审校 P2-5）：「> 」前缀（2 半格）入 _fit_line 量纲，
                # 39-40 半角过关行实渲染 41-42 的残留带收口
                desp += _fit_line(
                    f"> ⚠️ {nm} {date[5:].replace('-', '/')} "
                    f"走势图上传失败，本期无图",
                    fallbacks=[
                        f"> ⚠️ {nm} {date[5:].replace('-', '/')} "
                        f"上传失败，本期无图",
                        f"> ⚠️ {nm} 本期走势无图"]) + "\n\n"
    return notifier.send(f"📈 价格走势与明细｜{datetime.now().strftime('%m/%d %H:%M')}", desp)


def maybe_daily_report(cfg, logger, notifier, user=""):
    """sweep 末尾调用：过了每日 report_hour 给该用户补推一次（当天已推则跳过）。

    判据用 hour ≥ report_hour 的当次扫描即补推，禁用
    now.hour != report_hour 的等值比较——服务整点未运行（宕机/重启/
    挂起恢复）时等值比较会静默丢掉当天日报。当天是否已推记在 data/report_state.json（按 user 分 key，值=
    已推日期 YYYY-MM-DD），推送成功后才写入——失败下次扫描自动重试。"""
    ncfg, routes_cfg = _user_scope(cfg, user)
    hour = ncfg.get("report_hour")
    if hour is None or hour == "" or not ncfg.get("digest"):
        return
    now = datetime.now()
    if now.hour < int(hour):
        return
    today = now.strftime("%Y-%m-%d")
    key = user or "default"
    # 锚定仓库根（CWD 家族）：CWD 漂移=当日防重发失效同文重推
    state_path = os.path.join(_ROOT, "data", "report_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            states = json.load(f)
    except Exception:
        states = {}
    if not isinstance(states, dict):
        states = {}
    if states.get(key) == today:
        return
    if not build_and_push(cfg, logger, notifier, user=user):
        # 钉钉 -1「系统繁忙」是幽灵送达（报错但消息已入群）：日报内容
        # 固定，失败重试=同文重复推送（09-18 实锤 -1 日均 ghost 重推
        # 12+ 份、且重推风暴放大限流）——按已推落账防重发，真丢失由
        # 次日日报自然补；网络异常等其他失败仍走下轮重试
        if getattr(notifier, "last_errcode", None) == -1:
            logger.warning("[%s] 钉钉 -1 疑似幽灵送达，日报按已推落账防重发",
                           user or "default")
        else:
            return
    states[key] = today
    try:
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(states, f, ensure_ascii=False)
        logger.info("[%s] 每日图文走势已推送", user or "default")
    except Exception as e:
        logger.warning("[日报] report_state.json 写入失败: %s", e)
