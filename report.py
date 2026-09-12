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
PAD_L, PAD_R, PAD_T, PAD_B = 80, 30, 64, 46
C_DIRECT = (26, 115, 232)     # 直飞 蓝（与 UI 主色 #1a73e8 同族）
C_TRANSFER = (230, 126, 34)   # 中转 橙
C_TH = (214, 45, 48)          # 达标线 红
C_GRID = (225, 228, 232)
C_TEXT = (60, 64, 70)


def _font(size):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _rounds(db_path, from_city, to_city, date, arrival_max, hours=48):
    """按轮次聚类（平台时间戳相近算同一轮），回算 直飞/达标中转 最低价序列。
    仅取最近 hours 小时，防止长期运行后图表过密。"""
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
                if Alerter._arrival_ok(f, arrival_max):
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


def _daily_minima(db_path, from_city, to_city, date, arrival_max, days=14):
    """价格日历：近 days 天逐日直飞最低价 [("MM-DD", 价), ...]（升序）。

    复用 _rounds 的轮聚类与 extra 解析；数据窗口受存储清理限制（14 天）。
    纯展示函数，任何坏数据都只导致少点不导致异常。"""
    out = {}
    try:
        hist = _rounds(db_path, from_city, to_city, date, arrival_max,
                       hours=days * 24)
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
C_QUAL = (214, 45, 48)


def _fit_text(d, text, x, y, max_w, base=15, fill=C_TEXT, min_size=11):
    """列内自适应绘制：超宽先降字号，仍超则截断加省略号（防叠字）。"""
    txt = str(text)
    for size in range(base, min_size - 1, -1):
        font = _font(size)
        if d.textlength(txt, font=font) <= max_w:
            d.text((x, y), txt, font=font, fill=fill)
            return
    font = _font(min_size)
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


def render_flights_table(rows, title, out_path="data/flights_table.png",
                         top_n=5, summary=""):
    """rows: [(kind, [flight dict] | [str])]  kind: direct/transfer/compare。
    direct/transfer 渲染分组明细表；compare 每行一条跨全列的比价文本。
    summary: 图顶摘要行（脱离消息上下文也能看懂当前行情）。"""
    from core.alerter import Alerter
    plat_cn = Alerter.PLATFORM_CN
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    row_h, head_h, grp_h = 40, 42, 44
    # 高度必须覆盖每组各自的表头（compare 组无表头）；漏算会导致底部被裁出画布
    def _grp_h(kind, n):
        return (grp_h + (min(n, top_n) or 1) * row_h + 18
                + (0 if kind == "compare" else head_h))
    h = 58 + sum(_grp_h(it[0], len(it[1])) for it in rows) + 8 + (30 if summary else 0)
    img = Image.new("RGB", (TBL_W, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_title, f_head, f_cell, f_grp = _font(21), _font(15), _font(15), _font(17)
    d.text((24, 16), title, font=f_title, fill=C_TEXT)
    stamp = datetime.now().strftime("%m-%d %H:%M 生成")
    d.text((TBL_W - 24 - d.textlength(stamp, font=_font(14)),
            22), stamp, font=_font(14), fill=(150, 158, 168))
    y = 58
    if summary:
        d.text((24, y + 4), summary, font=_font(16), fill=(90, 100, 112))
        y += 30

    def draw_head(y):
        d.rectangle([12, y, TBL_W - 12, y + head_h], fill=C_HEAD_BG)
        x = 12
        for name, w in TBL_COLS:
            d.text((x + 10, y + 11), name, font=f_head, fill=(90, 100, 112))
            x += w
        return y + head_h

    alt = 0
    for item in rows:
        kind, fs = item[0], item[1]
        label_override = item[2] if len(item) > 2 else None
        if kind == "compare":
            d.text((20, y + 12),
                   _no_emoji(label_override or "同班跨渠道比价（同机不同价）"),
                   font=f_grp, fill=C_QUAL)
            y += grp_h
            if not fs:
                d.text((24, y + 10), "暂无多渠道同班", font=f_cell, fill=C_TEXT)
                y += row_h
            for line in fs[:top_n]:
                if alt % 2:
                    d.rectangle([12, y, TBL_W - 12, y + row_h], fill=C_ROW_ALT)
                alt += 1
                _fit_text(d, line, 24, y + 10, TBL_W - 48, base=15)
                y += row_h
            y += 18
            continue
        label = _no_emoji(label_override or
                          ("直飞最优" if kind == "direct"
                           else "中转最优（仅当日/次日凌晨前到达）"))
        color = C_DIRECT if kind == "direct" else C_TRANSFER
        d.ellipse([20, y + 14, 30, y + 24], fill=color)   # 几何色点代 emoji
        d.text((38, y + 12), label, font=f_grp, fill=color)
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
            cells = [
                ("直飞" if not f.get("transCity") else "中转", None),
                (f.get("name", ""), None),
                (f.get("depTime", ""), None),
                (arr, None),
                ((f"{f.get('transCity','')} · 停{f['layoverT']}"
                  if f.get("layoverT") else f.get("transCity", "") or "—"),
                 None),
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
                if name == "渠道" and dot:
                    d.ellipse([x + 10, y + 13, x + 18, y + 21], fill=dot)
                    _fit_text(d, txt, x + 24, y + 10, w - 28,
                              base=15, fill=fill)
                elif name == "价格":
                    # 价格是全表视觉锚点：大两号加粗；达标红/普通深蓝
                    _fit_text(d, txt, x + 4, y + 6, w - 8, base=20,
                              fill=C_QUAL if qual else (20, 70, 160),
                              min_size=14)
                else:
                    _fit_text(d, txt, x + 10, y + 10, w - 14,
                              base=15, fill=fill)
                x += w
            if qual:
                d.rectangle([12, y, 15, y + row_h], fill=C_QUAL)
            y += row_h
        y += 18
    img.save(out_path)
    return out_path


def render_chart(series, title, thresholds=(0, 0), out_path="data/trend.png"):
    """series: [(ts, best_direct|None, best_transfer|None)]"""
    img = Image.new("RGB", (W, H), (252, 253, 254))
    d = ImageDraw.Draw(img)
    f_title = _font(22)
    f_axis = _font(14)
    f_leg = _font(15)
    f_mark = _font(15)

    vals = [v for _, dd, tt in series for v in (dd, tt) if v is not None]
    th = [x for x in thresholds if x]
    if not vals and not th:
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
    d.text((lx + 162, 24), "中转最低(达标)", font=f_leg, fill=C_TEXT)

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

    # X 轴时间刻度：均布 5 个；跨天带日期（MM-DD HH:MM），同日只有 HH:MM
    xs = sorted({round((len(series) - 1) * k / 4) for k in range(5)})
    for i in xs:
        ts_i = series[i][0]
        label = (ts_i.strftime("%m-%d %H:%M") if cross_day
                 else ts_i.strftime("%H:%M"))
        d.text((xy(i, lo)[0] - 40, H - PAD_B + 8),
               label, font=f_axis, fill=C_TEXT)

    # 跨天分隔：日期变化处画浅竖线 + 日期标签（横轴上方）
    if cross_day:
        seen = {series[0][0].date()}
        for i, (ts_i, *_r) in enumerate(series):
            if ts_i.date() not in seen:
                seen.add(ts_i.date())
                x = xy(i, lo)[0]
                d.line([(x, PAD_T), (x, H - PAD_B)],
                       fill=(235, 205, 160), width=2)
                d.text((x + 6, PAD_T + 2), ts_i.strftime("%m-%d"),
                       font=f_axis, fill=(150, 120, 60))

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
        _tw = d.textlength(_tl, font=f_axis)
        d.text((W - PAD_R - _tw - 4, y - 20), _tl,
               font=f_axis, fill=C_TH)

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
        # 末值（折线尾端，带时刻）
        last = next(s[idx] for s in reversed(series) if s[idx] is not None)
        last_ts = next(s[0] for s in reversed(series) if s[idx] is not None)
        lx_, ly_ = pts[-1]
        tail = f"￥{last:,.0f} {last_ts.strftime('%m-%d %H:%M')}"
        d.text((min(lx_ + 6, W - 150), ly_ - 20), tail, font=f_axis, fill=color)
        # 最低点：加粗圆点 + halo 描边标注（哪天几点最低）
        lo_i = min((s for s in series if s[idx] is not None),
                   key=lambda s: s[idx])
        px, py = xy(series.index(lo_i), lo_i[idx])
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=color,
                  outline=(255, 255, 255), width=2)
        tag = f"低 ￥{lo_i[idx]:,.0f} {lo_i[0].strftime('%m-%d %H:%M')}"
        tw = d.textlength(tag, font=f_mark)
        tx = min(max(px - tw / 2, PAD_L + 2), W - PAD_R - tw - 2)
        ty = max(py - 26, PAD_T + 2)
        for dx in (-1, 0, 1):        # 白色 halo 描边防压线
            for dy in (-1, 0, 1):
                if dx or dy:
                    d.text((tx + dx, ty + dy), tag, font=f_mark,
                           fill=(255, 255, 255))
        d.text((tx, ty), tag, font=f_mark, fill=color)

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
                             r.get("transfer_arrival_max", "02:00"))
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
    desp = ""
    for (fc, tc, date), url in charts.items():
        rc = next((r for r in routes_cfg
                   if r.get("from") == fc and r.get("to") == tc), {})
        names = (rc.get("from_name") or fc, rc.get("to_name") or tc)
        desp += f"## {names[0]}→{names[1]} {date}\n\n![走势]({url})\n\n"
        fs = _route_latest_flights(db_path, fc, tc, date)
        if fs:
            am = rc.get("transfer_arrival_max", "02:00") or "02:00"
            directs = [f for f in fs if not f.get("transCity")]
            ok_t = [f for f in fs if f.get("transCity")
                    and Alerter._arrival_ok(f, am)]
            out_png = f"data/flights_table_{fc}{tc}_{date}.png"
            try:
                render_flights_table(
                    [("direct", directs), ("transfer", ok_t)],
                    f"{names[0]}→{names[1]} {date} 最优明细 TOP5", out_png)
                turl = upload_freeimage(out_png, logger)
                if turl:
                    desp += f"![明细表]({turl})\n\n"
            except Exception as e:
                logger.warning("[日报] 表格图生成失败: %s", e)
    desp += f"生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
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
