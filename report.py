# -*- coding: utf-8 -*-
"""价格走势：prices.db 回算分类最低价序列 → Pillow 画 PNG → 图床上传 → 钉钉图文

用法:
    python main.py --report    # 立即生成并推送（无 token 则只存本地 PNG）
    每日 report_hour 定时推送（main job 末尾调用 maybe_daily_report）
"""
import json
import logging
import os
import re
import sqlite3
from datetime import datetime

import httpx
from PIL import Image, ImageDraw, ImageFont

from core.alerter import Alerter

# ---- 画图 ----
W, H = 920, 460
PAD_L, PAD_R, PAD_T, PAD_B = 80, 30, 64, 60
C_DIRECT = (26, 115, 232)     # 直飞 蓝（与 UI 主色 #1a73e8 同族）
C_TRANSFER = (230, 126, 34)   # 中转 橙
C_TH = (214, 45, 48)          # 达标线 红
C_GRID = (225, 228, 232)
C_TEXT = (60, 64, 70)


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

    def point(self, pts, **k):
        self._d.point(self._pts(pts), **k)

    def font(self, n):
        return _font(n * self.s)


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
            layover_min=0, need_direct=False):
    """按轮次聚类（平台时间戳相近算同一轮），回算 直飞/达标中转 最低价序列。
    仅取最近 hours 小时，防止长期运行后图表过密。layover_min/need_direct：
    中转合法性增强（衔接时长下限 / 仅行李直挂），与当轮判定同规则，
    历史序列与最新值口径不一致会让「较上轮」对比错位。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT extra, fetched_at FROM flight_prices "
        "WHERE from_city=? AND to_city=? AND depart_date=? AND extra != '' "
        "AND fetched_at >= datetime('now', 'localtime', ?) "
        "ORDER BY fetched_at",
        (from_city, to_city, date, f"-{int(hours)} hours")).fetchall()
    conn.close()
    buckets = []  # [[ts, directs, transfers]]
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
        if buckets and (ts - buckets[-1][0]).total_seconds() <= 600:
            b = buckets[-1]
        else:
            b = [ts, [], []]
            buckets.append(b)
        for f in obj:
            if not isinstance(f, dict) or "price" not in f:
                continue
            try:
                p = float(f["price"])
            except (TypeError, ValueError):
                continue
            if f.get("transCity"):
                ok = Alerter._arrival_ok(f, arrival_max)
                if ok and layover_min > 0:
                    lm = f.get("layoverM")
                    ok = isinstance(lm, int) and lm >= layover_min
                if ok and need_direct:
                    ok = f.get("transferBaggage") == "direct"
                if ok:
                    b[2].append(p)
            else:
                b[1].append(p)
    series = []
    for ts, ds, tsf in buckets:
        d = min(ds) if ds else None
        t = min(tsf) if tsf else None
        if d is not None or t is not None:
            series.append((ts, d, t))
    return series


def _daily_minima(db_path, from_city, to_city, date, arrival_max, days=14,
                  layover_min=0, need_direct=False):
    """价格日历：近 days 天逐日直飞最低价 [("MM-DD", 价), ...]（升序）。

    复用 _rounds 的轮聚类与 extra 解析；数据窗口受存储清理限制（14 天）。
    纯展示函数，任何坏数据都只导致少点不导致异常。"""
    out = {}
    try:
        hist = _rounds(db_path, from_city, to_city, date, arrival_max,
                       hours=days * 24, layover_min=layover_min,
                       need_direct=need_direct)
    except Exception:
        return []
    for t, d, _x in hist:
        if not d:
            continue
        k = t.strftime("%m-%d")
        out[k] = min(out.get(k, float("inf")), d)
    return sorted((k, round(v)) for k, v in out.items())


# ---- 明细表（钉钉 markdown 不支持表格，渲染 PNG 直推） ----
TBL_COLS = [("类别", 62), ("航班", 164), ("出发", 60), ("到达", 116),
            ("中转", 116), ("全程", 80), ("渠道", 128), ("价格", 112)]
TBL_W = sum(w for _, w in TBL_COLS) + 24
C_HEAD_BG = (240, 244, 249)
C_ROW_ALT = (249, 251, 253)
C_QUAL = (14, 131, 69)         # 达标=可出手 绿（与网页 --green 同值；曾用红与
                               # 达标行浅绿底语义打架，v110.4 网页侧已统一绿）
C_CMP = (214, 45, 48)          # 比价组=跨渠道价差警示 红（组带/组头/可省）

class DESIGN:
    """设计令牌（单一事实源）：与 webui PAGE 的 CSS 变量同值同注释。
    改设计两处同步——report.py 本文件 + webui.py 的 <style> 变量。"""
    BG = (243, 244, 246)            # 画布底（--bg 系浅灰）
    CARD = (255, 255, 255)          # 白卡
    CARD_LINE = (226, 230, 235)     # 卡片描边（--line2）
    HEAD_BG = (228, 234, 243)       # 表头底
    HEAD_TX = (44, 56, 72)          # 表头字
    HEAD_LINE = (196, 206, 220)     # 表头底线
    ROW_ALT = (249, 251, 253)       # 斑马纹
    HAIRLINE = (238, 241, 245)      # 行分隔
    SUMMARY_BG = (247, 248, 250)    # 摘要条底
    SUMMARY_LINE = (232, 236, 241)  # 摘要条描边
    SUMMARY_TX = (70, 78, 90)       # 摘要/次级正文
    MUTED = (107, 119, 131)         # 弱化（时间戳/图例/衔接灰）——白卡上 4.5:1
    CAP_DIRECT_BG = (234, 242, 252) # 直飞胶囊浅底
    CAP_TRANSFER_BG = (253, 244, 232)  # 中转胶囊浅底
    PRICE_PLAIN = (20, 70, 160)     # 非达标价格深蓝
    LAY_SHORT = (176, 137, 0)       # 衔接偏短琥珀
    CHAIN_TX = (64, 76, 92)         # 比价渠道链


def _tbl_align(name, x, w, text_w):
    """表格列对齐基调：时刻/全程窄列居中，价格右对齐，其余居左——
    表头与数据同向，全表左右轴对称协调。"""
    if name in ("出发", "到达", "全程", "中转"):
        return x + max(4, (w - text_w) // 2)
    if name == "价格":
        return x + w - 10 - text_w
    return x + 10


def _fit_text(d, text, x, y, max_w, base=15, fill=C_TEXT, min_size=11):
    """列内自适应绘制：超宽先降字号，仍超则截断加省略号（防叠字）。"""
    txt = str(text)
    # 代理 textlength 已返回逻辑域宽（物理/S），max_w 保持逻辑域直接比较；
    # 若在此再乘 S，判定恒过→长名永不截断、溢出列界（复现实锤）
    get_font = getattr(d, "font", None) or _font
    for size in range(base, min_size - 1, -1):
        font = get_font(size)
        if d.textlength(txt, font=font) <= max_w:
            d.text((x, y), txt, font=font, fill=fill)
            return
    font = get_font(min_size)
    while txt and d.textlength(txt + "…", font=font) > max_w:
        txt = txt[:-1]
    d.text((x, y), txt + ("…" if txt else ""), font=font, fill=fill)


PLAT_DOT = {"qunar": (26, 115, 232), "fliggy": (230, 126, 34),
            "ctrip": (46, 164, 79), "tongcheng": (130, 80, 223),
            "tuniu": (210, 153, 34)}
_EMJI = re.compile(
    "[🀀-🫿☀-➿🇦-🇿"
    "⬀-⯿←-⇿️]+")


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


def render_flights_table(rows, title, out_path="data/flights_table.png",
                         top_n=5, summary=""):
    """rows: [(kind, [flight dict] | [compare dict | str])]  kind: direct/transfer/compare。
    direct/transfer 渲染分组明细表；compare 渲染三列小表
    （航班+时刻 ｜ 渠道价格链 ｜ 可省），旧式预拼字符串仍兼容直落。
    组第 4 元可带 meta dict：layover_min（衔接下限，着色绿/琥珀）、
    need_direct（开启时组头标「仅直挂」）。
    summary: 图顶摘要行（脱离消息上下文也能看懂当前行情）。"""
    from core.alerter import Alerter
    plat_cn = Alerter.PLATFORM_CN
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    row_h, head_h, grp_h = 44, 42, 44
    cmp_h = 64   # 比价行两行式：航班+可省 / 渠道链整行（信息零截断）
    # 高度必须覆盖每组各自的表头（compare 组无表头）；漏算会导致底部被裁出画布
    def _grp_h(kind, n):
        return (grp_h + (min(n, top_n) or 1) * (cmp_h if kind == "compare"
                                                else row_h) + 22
                + (0 if kind == "compare" else head_h))
    meta_any = [it[3] for it in rows if len(it) > 3 and isinstance(it[3], dict)]
    has_direct_badge = any(
        f.get("transferBaggage") == "direct"
        for it in rows if it[0] != "compare" for f in it[1])
    legend_h = 22 if (meta_any and it_has_transfer(rows)) else 0
    h = 58 + sum(_grp_h(it[0], len(it[1])) for it in rows) + 8 \
        + (30 if summary else 0) + legend_h
    # 白卡浮在浅灰底上：圆角+细边框，PNG 在钉钉里立刻脱离"平铺表格"感
    S = 2
    img = Image.new("RGB", (TBL_W * S, h * S), DESIGN.BG)
    d = _ScaledDraw(ImageDraw.Draw(img), S)
    d.rounded_rectangle([6, 6, TBL_W - 7, h - 7], radius=14,
                        fill=DESIGN.CARD, outline=DESIGN.CARD_LINE, width=1)
    f_title, f_head, f_cell, f_grp = (d.font(21), d.font(16),
                                      d.font(16), d.font(19))
    d.text((24, 18), title, font=f_title, fill=C_TEXT)
    stamp = datetime.now().strftime("%m-%d %H:%M 生成")
    d.text((TBL_W - 28 - d.textlength(stamp, font=d.font(14)),
            26), stamp, font=d.font(14), fill=DESIGN.MUTED)
    y = 62
    if summary:
        d.rounded_rectangle([16, y, TBL_W - 16, y + 30], radius=8,
                            fill=DESIGN.SUMMARY_BG, outline=DESIGN.SUMMARY_LINE)
        d.text((28, y + 8), summary, font=d.font(15), fill=DESIGN.SUMMARY_TX)
        y += 38

    def draw_head(y):
        d.rectangle([12, y, TBL_W - 12, y + head_h], fill=DESIGN.HEAD_BG)
        d.line([(12, y + head_h - 1), (TBL_W - 12, y + head_h - 1)],
               fill=DESIGN.HEAD_LINE, width=2)
        x = 12
        for name, w in TBL_COLS:
            tw = d.textlength(name, font=f_head)
            tx = _tbl_align(name, x, w, tw)
            d.text((tx, y + 11), name, font=f_head, fill=(44, 56, 72))
            x += w
        return y + head_h

    alt = 0
    for item in rows:
        kind, fs = item[0], item[1]
        label_override = item[2] if len(item) > 2 else None
        if kind == "compare":
            d.rounded_rectangle([12, y, TBL_W - 12, y + grp_h - 4], radius=8,
                                fill=(251, 240, 240))
            d.rectangle([12, y, 16, y + grp_h - 4], fill=C_CMP)
            d.text((26, y + 11),
                   _no_emoji(label_override or "同班跨渠道比价"),
                   font=f_grp, fill=C_CMP)
            y += grp_h
            if not fs:
                d.text((24, y + 10), "暂无多渠道同班", font=f_cell, fill=C_TEXT)
                y += row_h
            for line in fs[:top_n]:
                if alt % 2:
                    d.rectangle([12, y, TBL_W - 12, y + cmp_h],
                                fill=C_ROW_ALT)
                alt += 1
                if isinstance(line, str):      # 旧调用方：预拼文本直接落
                    # 注意不可过 _no_emoji——其区间含 →(U+2192)，会把
                    # 「08:30→13:50」的箭头剥掉；唯一现役调用方已结构化
                    _fit_text(d, line, 24, y + 10, TBL_W - 48, base=15)
                else:
                    # 两行式行卡：航班+时刻（左）与 可省（右）一行，
                    # 渠道价格链独占整行——5 渠道链在半宽列曾截尾丢信息
                    tr = f" 经{line['trans']}" if line.get("trans") else ""
                    # 首行：航班+航线+时刻 加粗17px；右缘「可省」18px 粗红——
                    # 比价的核心结论是省多少，按视觉锚点待遇（右缘不再空旷）
                    _fit_text(d, f"{line['label']}  {line['dep']}→{line['arr']}{tr}",
                              24, y + 10, TBL_W - 240, base=17)
                    save = f"可省 ￥{line['save']:.0f}"
                    f_sv = _font_bold(20)
                    d.text((TBL_W - 26 - d.textlength(save, font=f_sv),
                            y + 8), save, font=f_sv, fill=C_CMP)
                    # 渠道链：关键价格信息，字号加大、颜色加深（不再浅灰弱化）
                    chain = " → ".join(f"{cn} ￥{p:.0f}"
                                       for cn, p in line.get("chain") or [])
                    _fit_text(d, chain, 24, y + 40, TBL_W - 48,
                              base=16, fill=DESIGN.CHAIN_TX)
                y += cmp_h
            y += 18
            continue
        label = _no_emoji(label_override or
                          ("直飞最优" if kind == "direct"
                           else "中转最优（仅当日/次日凌晨前到达）"))
        color = C_DIRECT if kind == "direct" else C_TRANSFER
        band = DESIGN.CAP_DIRECT_BG if kind == "direct" else DESIGN.CAP_TRANSFER_BG
        meta = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
        lay_min = int(meta.get("layover_min", 0) or 0)
        only_direct = kind == "transfer" and bool(meta.get("need_direct"))
        d.rounded_rectangle([12, y, TBL_W - 12, y + grp_h - 4], radius=8,
                            fill=band)
        d.rectangle([12, y, 16, y + grp_h - 4], fill=color)   # 左色条
        d.text((26, y + 11), label, font=f_grp, fill=color)
        # 组头右侧：TOP 标 + 直挂筛选标注（配置可读性）
        tag_txt = f"TOP{top_n}" + (" · 仅直挂" if only_direct else "")
        d.text((TBL_W - 28 - d.textlength(tag_txt, font=f_head),
                y + 13), tag_txt, font=f_head, fill=DESIGN.MUTED)
        y += grp_h
        y = draw_head(y)
        fs = sorted(fs, key=lambda f: f.get("price", 9e9))[:top_n]
        if not fs:
            d.text((24, y + 10), "暂无数据", font=f_cell, fill=C_TEXT)
            y += row_h
        for f in fs:
            qual = bool(f.get("_qual"))
            if qual:
                d.rectangle([12, y, TBL_W - 12, y + row_h], fill=(238, 249, 242))
            elif alt % 2:
                d.rectangle([12, y, TBL_W - 12, y + row_h], fill=C_ROW_ALT)
            alt += 1
            price = f.get("price", 0)
            cross = f.get("crossDayDesc") or ""
            arr = f"{f.get('arrTime','')}" + (f" +{cross[1]}" if cross else "")
            is_tr = bool(f.get("transCity"))
            cells = [
                ("直飞" if not is_tr else "中转", None),
                (f.get("name", ""), None),
                (f.get("depTime", ""), None),
                (arr, None),
                (f.get("transCity", "") or "—", None),
                (f.get("totalDuration", "") or "—", None),
                (_plat_tag(f, plat_cn), None),
                (f"￥{price:.0f}", C_QUAL if qual else (30, 34, 40)),
            ]
            x = 12
            dot = PLAT_DOT.get(f.get("_platform", ""))
            for (txt, _), (name, w) in zip(cells, TBL_COLS):
                fill = C_TEXT
                if name == "价格":
                    fill = cells[-1][1]
                if qual and name in ("类别",):
                    fill = C_QUAL
                if name == "类别":
                    # 类别画胶囊：浅底深字粗体（实底白字在 2x 缩放下曾显廉价），
                    # 直飞蓝系/中转橙系；达标行绿描边强化
                    cap_w, cap_h = 46, 22
                    cx, cy = x + 8, y + (row_h - cap_h) // 2
                    d.rounded_rectangle(
                        [cx, cy, cx + cap_w, cy + cap_h], radius=cap_h // 2,
                        fill=DESIGN.CAP_DIRECT_BG if not is_tr else DESIGN.CAP_TRANSFER_BG,
                        outline=(26, 115, 232) if not is_tr else (224, 127, 42),
                        width=1)
                    f_cap = d.font(12)
                    d.text((cx + cap_w / 2 - d.textlength(txt, font=f_cap) / 2,
                            cy + 5), txt, font=f_cap,
                           fill=(26, 115, 232) if not is_tr else (196, 110, 20))
                elif name in ("出发", "到达", "全程"):
                    tw = d.textlength(txt, font=d.font(16))
                    d.text((x + max(4, (w - int(tw)) // 2), y + 10), txt,
                           font=d.font(16), fill=fill)
                elif name == "价格":
                    # 价格是全表视觉锚点：大号右对齐；达标绿/普通深蓝
                    pw = d.textlength(txt, font=d.font(20))
                    d.text((x + w - 10 - int(pw), y + 6), txt,
                           font=d.font(20), fill=fill)
                elif name == "航班" and f.get("transferBaggage") == "direct":
                    # 「直挂」徽标：中转联程两段均含免费托运（行李直挂）
                    _fit_text(d, txt, x + 10, y + 10, w - 66,
                              base=16, fill=fill)
                    bx = x + w - 58
                    d.rounded_rectangle([bx, y + 10, bx + 48, y + 30],
                                        radius=10, outline=C_QUAL, width=1)
                    d.text((bx + 9, y + 14), "直挂",
                           font=d.font(13), fill=C_QUAL)
                elif name == "渠道" and dot:
                    d.ellipse([x + 10, y + 13, x + 18, y + 21], fill=dot)
                    _fit_text(d, txt, x + 24, y + 10, w - 28,
                              base=16, fill=fill)
                elif name == "中转":
                    # 两行制：城市（本行居中）+ 衔接时长（行尾统一画第二行）
                    f_city = d.font(15)
                    twc = d.textlength(txt or "—", font=f_city)
                    d.text((x + (w - int(twc)) // 2, y + 3), txt or "—",
                           font=f_city, fill=fill)
                    trans_cx, trans_cw = x, w
                else:
                    _fit_text(d, txt, x + 10, y + 10, w - 14,
                              base=15, fill=fill)
                x += w
            if is_tr and f.get("layoverT") and trans_cw:
                # 中转衔接（第二行）始终显示——时长是决策关键，不依赖配置；
                # 着色：配置了下限且达标=绿，未配置下限=中性灰
                lay = f"停{f['layoverT']}"
                lw = d.textlength(lay, font=d.font(13))
                lc = (C_QUAL if (f.get("layoverM") or 0) >= lay_min
                      else DESIGN.LAY_SHORT) if lay_min > 0 else DESIGN.MUTED
                d.text((trans_cx + (trans_cw - int(lw)) // 2, y + 22), lay,
                       font=d.font(13), fill=lc)
            if qual:
                d.rectangle([12, y, 16, y + row_h], fill=(14, 131, 69))
            # 行间 hairline（达标行浅绿线）
            lc = (226, 240, 231) if qual else (238, 241, 245)
            d.line([(12, y + row_h - 1), (TBL_W - 12, y + row_h - 1)],
                   fill=lc, width=1)
            y += row_h
        y += 18
    if legend_h:
        d.text((24, h - 22),
               "中转衔接达到航线配置下限以绿色标示 · 「直挂」= 两段均含免费托运（行李直挂）",
               font=d.font(14), fill=DESIGN.MUTED)
    img = img.resize((TBL_W, h), Image.LANCZOS)
    img.save(out_path)
    return out_path


def render_chart(series, title, thresholds=(0, 0), out_path="data/trend.png"):
    """series: [(ts, best_direct|None, best_transfer|None)]"""
    # 与明细总表同视觉基准：白卡浮浅灰底（rounded_rectangle 圆角细边）
    img = Image.new("RGB", (W, H), (243, 244, 246))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, W - 7, H - 7], radius=14,
                        fill=DESIGN.CARD, outline=DESIGN.CARD_LINE, width=1)
    f_title = _font(21)
    f_axis = _font(14)
    f_leg = _font(16)
    f_mark = _font(16)

    vals = [v for _, dd, tt in series for v in (dd, tt) if v is not None]
    th = [x for x in thresholds if x]
    if not vals and not th:
        d.rounded_rectangle([6, 6, W - 7, H - 7], radius=14,
                            fill=(255, 255, 255), outline=(226, 230, 235), width=1)
        d.text((20, 20), "暂无数据", font=f_title, fill=C_TEXT)
        img.save(out_path)
        return out_path
    lo = min(vals + th) - max(40, (max(vals + th) - min(vals + th)) * 0.06)
    hi = max(vals + th) + max(40, (max(vals + th) - min(vals + th)) * 0.06)

    def xy(i, v):
        x = PAD_L + (W - PAD_L - PAD_R) * (i / max(1, len(series) - 1))
        y = PAD_T + (H - PAD_T - PAD_B) * (1 - (v - lo) / (hi - lo))
        return x, y

    # 标题 + 图例
    d.text((PAD_L, 20), title, font=f_title, fill=C_TEXT)
    lx = W - 300
    d.line([(lx, 32), (lx + 26, 32)], fill=C_DIRECT, width=3)
    d.text((lx + 32, 24), "直飞最低", font=f_leg, fill=C_TEXT)
    d.line([(lx + 130, 32), (lx + 156, 32)], fill=C_TRANSFER, width=3)
    # 「(达标)」仅在该航线确实配置了中转阈值时标注（未设线=无达标语义）
    t_t = thresholds[1] if len(thresholds) > 1 else 0
    d.text((lx + 162, 24), "中转最低" + ("(达标)" if t_t > 0 else ""),
           font=f_leg, fill=C_TEXT)

    span_h = max(0.5, (series[-1][0] - series[0][0]).total_seconds() / 3600)
    cross_day = span_h >= 20  # 跨天窗口：刻度带日期，且画日期分隔线

    # 竖直参考网格（均布 4 条）：帮助对齐下方时间刻度
    plot_w = W - PAD_L - PAD_R
    for k in range(1, 4):
        gx = PAD_L + plot_w * k / 4
        d.line([(gx, PAD_T), (gx, H - PAD_B)], fill=C_GRID, width=1)

    # 网格 + Y 轴刻度
    step = (hi - lo) / 4
    for k in range(5):
        v = lo + step * k
        y = xy(0, v)[1]
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=C_GRID, width=1)
        d.text((10, y - 8), f"￥{v:,.0f}", font=f_axis, fill=C_TEXT)

    # X 轴时间刻度：均布 5 个；跨天带日期（MM-DD HH:MM），同日只有 HH:MM。
    # 按实测宽度居中 + 右缘夹紧 + 避让跳过：相邻刻度绝不互撞
    xs = sorted({round((len(series) - 1) * k / 4) for k in range(5)})
    last_r = -1.0
    for i in xs:
        ts_i = series[i][0]
        label = (ts_i.strftime("%m-%d %H:%M") if cross_day
                 else ts_i.strftime("%H:%M"))
        lw = d.textlength(label, font=f_axis)
        lx = min(max(xy(i, lo)[0] - lw / 2, PAD_L - 46), W - PAD_R - lw)
        if lx < last_r + 10:
            continue
        d.text((lx, H - PAD_B + 8), label, font=f_axis, fill=C_TEXT)
        last_r = lx + lw

    # 跨天分隔：日期变化处画浅竖线；日期标签放底部独立行（H-PAD_B+26），
    # 居中挂线上——旧版画图内顶部（PAD_T+2），被折线/散点压住不可读
    if cross_day:
        seen = {series[0][0].date()}
        for i, (ts_i, *_r) in enumerate(series):
            if ts_i.date() not in seen:
                seen.add(ts_i.date())
                x = xy(i, lo)[0]
                d.line([(x, PAD_T), (x, H - PAD_B)],
                       fill=(235, 205, 160), width=2)
                lab = ts_i.strftime("%m-%d")
                lw = d.textlength(lab, font=f_axis)
                lx = min(max(x - lw / 2, PAD_L - 46), W - PAD_R - lw)
                d.text((lx, H - PAD_B + 26), lab, font=f_axis,
                       fill=(150, 120, 60))

    # 渐变面积：折线下方每像素竖线，alpha 随深度衰减（质感填充）
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
            for yy in range(int(cy), int(base_y)):
                t = (yy - cy) / max(1, base_y - cy)
                a = 0.22 * (1 - t)
                col = tuple(int(bg[k] + (color[k] - bg[k]) * a) for k in range(3))
                d.point((gx, yy), fill=col)

    # 悬浮文本标注（达标线/末值/最低点）先登记、末尾统一排布绘制：
    # 右缘多标签同域曾叠成一团（2026-09-13 遮挡反馈根治）
    labels = []

    # 达标线（虚线）
    for tv, lab in zip(thresholds, ("直飞达标线", "中转达标线")):
        if not tv or not (lo <= tv <= hi):
            continue
        y = xy(0, tv)[1]
        x = PAD_L
        while x < W - PAD_R:
            d.line([(x, y), (min(x + 7, W - PAD_R), y)], fill=C_TH, width=2)
            x += 12
        _tl = f"{lab} ￥{tv:,.0f}"
        labels.append({"txt": _tl, "c": C_TH, "f": f_axis,
                       "x": W - PAD_R - d.textlength(_tl, font=f_axis) - 4,
                       "y": y - 20})

    # 两条折线 + 达标点旗标 + 末值 + 最低点标注
    th_d, th_t = (thresholds + (0, 0))[:2]
    for idx, color in ((1, C_DIRECT), (2, C_TRANSFER)):
        pts = [(xy(i, s[idx])[0], xy(i, s[idx])[1])
               for i, s in enumerate(series) if s[idx] is not None]
        if not pts:
            continue
        d.line(pts, fill=color, width=3, joint="curve")
        for p in pts:
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=color)
        # 达标数据点：价格低于阈值的点画白心绿环旗标（达标时刻可视化）
        th_v = th_d if idx == 1 else th_t
        if th_v:
            for i, s2 in enumerate(series):
                if s2[idx] is not None and s2[idx] <= th_v:
                    px, py = xy(i, s2[idx])
                    d.ellipse([px - 5, py - 5, px + 5, py + 5],
                              fill=(255, 255, 255), outline=(14, 131, 69),
                              width=2)
        # 末值（折线尾端）：时刻与 X 轴末端刻度重复，只报价格；
        # 末值恰为全窗最低时与「低」标注合并（同值两条曾显冗余拥挤）
        last = next(s[idx] for s in reversed(series) if s[idx] is not None)
        lo_s = min((s for s in series if s[idx] is not None), key=lambda s: s[idx])
        lx_, ly_ = pts[-1]
        merged = (lo_s[idx] == last)
        labels.append({"txt": f"￥{last:,.0f}", "c": color, "f": f_mark,
                       "x": min(lx_ + 6, W - 100), "y": ly_ - 26})
        # 最低点：加粗圆点 + 白环 + 标注（哪天几点最低；未合并才画）。
        # 文字优先放点下方渐变淡区（上方常是折线密集区），贴底轴才翻到上方
        px, py = xy(series.index(lo_s), lo_s[idx])
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=color,
                  outline=(255, 255, 255), width=2)
        if not merged:
            tag = f"低 ￥{lo_s[idx]:,.0f} {lo_s[0].strftime('%m-%d %H:%M')}"
            tw = d.textlength(tag, font=f_mark)
            tx = min(max(px - tw / 2, PAD_L + 2), W - PAD_R - tw - 2)
            ty = py + 8 if py + 30 < H - PAD_B else max(py - 26, PAD_T + 2)
            labels.append({"txt": tag, "c": color, "f": f_mark,
                           "x": tx, "y": ty})

    # 统一纵向避让：按 y 排序，与任一横向相交的已放置标签间距 <20px 则下推。
    # 绘制用「白底圆角块 + 描字」替代 3×3 halo——密集折线区 halo 柔边仍花，
    # 底块彻底隔开背景（先画全部底块再画字，后块不压先字）
    for a in labels:
        a["w"] = d.textlength(a["txt"], font=a["f"])
    labels.sort(key=lambda a: a["y"])
    placed = []
    for a in labels:
        for _ in range(60):
            if not any(not (a["x"] + a["w"] < b["x"] - 4 or
                            b["x"] + b["w"] < a["x"] - 4)
                       and abs(a["y"] - b["y"]) < 20 for b in placed):
                break
            a["y"] += 6
        a["y"] = min(max(a["y"], PAD_T + 2), H - PAD_B - 20)
        placed.append(a)
    for a in labels:
        d.rounded_rectangle([a["x"] - 4, a["y"] - 2, a["x"] + a["w"] + 4,
                             a["y"] + 19], radius=5, fill=(255, 255, 255),
                            outline=(226, 230, 235), width=1)
    for a in labels:
        d.text((a["x"], a["y"]), a["txt"], font=a["f"], fill=a["c"])

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    return out_path


# ---- 图床上传 ----
# freeimage.host 官方文档公开的匿名上传 key（免注册、永久保存、直链 iili.io）
FREEIMAGE_KEY = "6d207e02198a847aa98d0a2a901485a5"


def _upload_pixhost(png_path, logger):
    """备用图床 pixhost v2（免 API key）：上传后从 show 页解析原图直链
    （imgN.pixhost.to/images/…，t3./thumbs/ 是缩略图）。2026-09-12 起
    freeimage 对 key 上传全量 400/111，此为自动降级通道。"""
    try:
        import re as _re
        r = httpx.post(
            "https://api.pixhost.cc/images",
            data={"content_type": "0", "max_th_size": "500"},
            files={"img": (os.path.basename(png_path),
                           open(png_path, "rb"), "image/png")},
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
    try:
        with open(png_path, "rb") as f:
            # trust_env=False：绕过系统代理直连——公司代理对 iili.io
            # 系图床的 HTTPS 会随机掐断（EOF in violation of protocol），
            # 09-07 以来的历次"上传异常"均为代理干扰所致
            r = httpx.post(
                "https://freeimage.host/api/1/upload",
                data={"key": FREEIMAGE_KEY, "action": "upload", "type": "file"},
                files={"source": f}, timeout=60, trust_env=False,
            )
        url = ((r.json().get("image") or {}).get("url"))
        if url:
            return url
    except Exception as e:
        logger.warning("[走势] freeimage 上传异常: %s", e)
        return _upload_pixhost(png_path, logger)
    logger.warning("[走势] freeimage 上传失败（%s），降级 pixhost",
                   r.text[:120])
    return _upload_pixhost(png_path, logger)


def upload_smms(png_path, token, logger):
    try:
        r = httpx.post(
            "https://sm.ms/api/v2/upload",
            headers={"Authorization": token},
            files={"smfile": open(png_path, "rb")},
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


def upload_chart(png_path, cfg, logger):
    """按配置选图床：freeimage（免注册，默认）/ smms（需 token）。"""
    ih = _image_host_cfg(cfg)
    provider = (ih.get("provider") or "").strip().lower()
    if provider == "freeimage":
        return upload_freeimage(png_path, logger)
    if provider == "smms" and (ih.get("token") or "").strip():
        return upload_smms(png_path, ih["token"].strip(), logger)
    return None


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


def prepare_round_charts(cfg, logger, route_override=None):
    """生成并上传走势图。route_override=(from,to,date) 时只画该航线
    （多租户扫描按航线调用，一次上传多用户复用）。返回 {(from,to,date): url}。"""
    ih = _image_host_cfg(cfg)
    if not (ih.get("provider") or "").strip():
        return {}
    _, all_routes = _user_scope(cfg)
    for u in (cfg.get("users") or []):  # 多租户：合并所有用户航线（去重）
        for r in (u.get("routes") or []):
            if r not in all_routes:
                all_routes.append(r)
    db_path = (cfg.get("output") or {}).get("db_path", "data/prices.db")
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
            series = _rounds(db_path, r["from"], r["to"], date,
                             r.get("transfer_arrival_max", "02:00"),
                             layover_min=int(r.get("transfer_layover_min", 0) or 0),
                             need_direct=r.get("transfer_baggage", "") == "direct")
            if not series:
                continue
            png = os.path.join("data", f"trend_{r['from']}_{r['to']}_{date}.png")
            render_chart(series,
                         f"{r.get('from_name', r['from'])}→{r.get('to_name', r['to'])} {date} 价格走势",
                         thresholds=(float(r.get("alert_direct", 0) or 0),
                                     float(r.get("alert_transfer", 0) or 0)),
                         out_path=png)
            url = upload_chart(png, cfg, logger)
            if url:
                charts[key] = url
    return charts


def _route_latest_flights(db_path, fc, tc, date, max_age_min=150):
    """该航线各平台最近一次有明细的 extra 合并池（仅新鲜数据，不带补位）。"""
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
            if (datetime.now() - ts).total_seconds() / 60 > max_age_min:
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
                    _fnorm(g, date)
                    out.append(g)
    return out


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
    db_path = (cfg.get("output") or {}).get("db_path", "data/prices.db")
    desp = "# 📈 每日走势与明细\n\n"
    desp += f"> ⏱ 数据截至 {datetime.now().strftime('%m-%d %H:%M')}\n\n"
    first = True
    for (fc, tc, date), url in sorted(charts.items(), key=lambda kv: kv[0]):
        rc = next((r for r in routes_cfg
                   if r.get("from") == fc and r.get("to") == tc), {})
        names = (rc.get("from_name") or fc, rc.get("to_name") or tc)
        if not first:
            desp += "---\n\n"
        first = False
        desp += f"## {names[0]}→{names[1]} {date}\n\n"
        fs = _route_latest_flights(db_path, fc, tc, date)
        if fs:
            am = rc.get("transfer_arrival_max", "02:00") or "02:00"
            directs = [f for f in fs if not f.get("transCity")]
            ok_t = [f for f in fs if f.get("transCity")
                    and Alerter._transfer_ok(f, rc)]
            # KPI 摘要行（与达标推送同语言：最优价 + 距心理线）
            ad = float(rc.get("alert_direct", 0) or 0)
            at_ = float(rc.get("alert_transfer", 0) or 0)

            def _kpi(label, price, th):
                s = f"{label} ￥{price:,.0f}"
                if th:
                    d = price - th
                    s += (f"（线 ￥{th:,.0f}，"
                          f"{'低于' if d <= 0 else '超'}线 ￥{abs(d):,.0f}）")
                return s

            kpis = []
            if directs:
                kpis.append(_kpi("直飞最优",
                                 min(f["price"] for f in directs), ad))
            if ok_t:
                kpis.append(_kpi("中转最优",
                                 min(f["price"] for f in ok_t), at_))
            if kpis:
                desp += "**" + " ｜ ".join(kpis) + "**\n\n"
        # 走势是日报主角（与 title「走势与明细」同序）：走势在前、明细表图随后
        desp += f"![走势]({url})\n\n"
        if fs:
            out_png = f"data/flights_table_{fc}{tc}_{date}.png"
            try:
                render_flights_table(
                    [("direct", directs),
                     ("transfer", ok_t, None,
                      {"layover_min": int(rc.get("transfer_layover_min", 0) or 0),
                       "need_direct": rc.get("transfer_baggage", "") == "direct"})],
                    f"{names[0]}→{names[1]} {date} 最优明细 TOP5", out_png)
                turl = upload_freeimage(out_png, logger)
                if turl:
                    desp += f"![明细表]({turl})\n\n"
            except Exception as e:
                logger.warning("[日报] 表格图生成失败: %s", e)
    return notifier.send(f"📈 价格走势与明细｜{datetime.now().strftime('%m-%d %H:%M')}", desp)


def maybe_daily_report(cfg, logger, notifier, user=""):
    """sweep 末尾调用：到每日 report_hour 给该用户推一次（当天已推则跳过）。"""
    ncfg, routes_cfg = _user_scope(cfg, user)
    hour = ncfg.get("report_hour")
    if hour is None or hour == "" or not ncfg.get("digest"):
        return
    hour = int(hour)
    now = datetime.now()
    if now.hour != hour:
        return
    db_path = (cfg.get("output") or {}).get("db_path", "data/prices.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    key = f"daily-report|{user}"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS alert_state "
            "(route_key TEXT PRIMARY KEY, last_price REAL NOT NULL, last_sent_at TEXT NOT NULL)")
        row = conn.execute(
            "SELECT last_sent_at FROM alert_state WHERE route_key=?", (key,)
        ).fetchone()
        if row and row[0] == now.strftime("%Y-%m-%d"):
            return
        sent = build_and_push(cfg, logger, notifier, user=user)
        if sent:
            conn.execute(
                "INSERT INTO alert_state (route_key, last_price, last_sent_at) "
                "VALUES (?, 0, ?) ON CONFLICT(route_key) DO UPDATE SET "
                "last_sent_at=excluded.last_sent_at",
                (key, now.strftime("%Y-%m-%d")))
            conn.commit()
            logger.info("[%s] 每日图文走势已推送", user or "default")
    finally:
        conn.close()
