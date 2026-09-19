# -*- coding: utf-8 -*-
"""飞猪机票爬虫（PC SSR 版，2026-09-09 重写）

背景：移动端 mtop.trip.flight.flightSearch v1.0 已被官方下线
（NOT_SUPPORT），新版走 serverless 网关+强制登录，无法低成本接入。
发现：PC 搜索结果页 sjipiao.fliggy.com 为服务端直出（SSR）——
航班列表直接渲染在 HTML/DOM 中，无需接口，滚动收集 innerText
按行状态机解析即可（与 qunar DOM 兜底同套路）。

注意：PC 页价格口径为「不含税费」的展示价，与含税渠道差约
￥50-130，参与比价时天然略偏优——展示层飞猪标注税前。
页面仅含直达+经停（经停不换机视为直达），中转由其他渠道覆盖。
"""
import json
import logging
import re
from typing import List

from .base import BaseCrawler
from .qunar import QunarCrawler as _Q
from core.models import FlightPrice

_LOG = logging.getLogger(__name__)


class FliggyCrawler(BaseCrawler):
    name = "fliggy"
    use_mobile = False  # 桌面 UA（PC SSR 页面）

    URL_TPL = ("https://sjipiao.fliggy.com/flight_search_result.htm"
               "?tripType=0&depCity={fc}&arrCity={tc}&depDate={d}"
               "&depCityName={fn}&arrCityName={tn}")

    _RE_FNO = re.compile(
        r"([\u4e00-\u9fa5]{1,3})?((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})$")
    _RE_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d")

    # 共享航班实际承运采集（v1.5.48，仅展示不入指纹）：共享行挂
    # data-content=「实际乘坐航班：南方航空CZ6993」（dump 实测 14/35
    # 行），行容器 .flight-list-item 内 .J_line 文本即营销号——按行
    # 容器精确归属，不做祖先启发（错归属=误导性半假数据，宁缺勿错）
    _SHARE_JS = (
        "() => { const out = [];"
        " document.querySelectorAll('[data-content]').forEach(el => {"
        " const dc = el.getAttribute('data-content') || '';"
        " if (dc.indexOf('实际乘坐航班') < 0) return;"
        " const row = el.closest('.flight-list-item'); if (!row) return;"
        " const line = row.querySelector('.J_line');"
        " const t = line ? ((line.innerText || line.textContent) || '') : '';"
        " const m = t.match(/([A-Z][A-Z0-9]?\\d{3,4})/);"
        " if (m) out.push([m[1], dc.split(/：|:/).pop().trim()]); });"
        " return out; }")
    _RE_ARR = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d(?:\s*第(\d)天)?$")
    _RE_PRICE = re.compile(r"[¥￥]\s*(\d{1,3}(?:,\d{3})+|\d{3,5})")

    def login_url(self) -> str:
        return "https://www.fliggy.com/"

    # ==================== 主流程 ====================
    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        results: List[FlightPrice] = []
        fc, tc = from_city.upper(), to_city.upper()
        for date in dates:
            flights = self._fetch_pc(fc, tc, date)
            if flights:
                best = min(flights, key=lambda f: f["price"])
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=best.get("name", "")[:20],
                    flight_no=best.get("code", ""),
                    depart_time=best.get("depTime", ""),
                    arrive_time=best.get("arrTime", ""),
                    extra=json.dumps(flights, ensure_ascii=False),
                ))
                self.logger.info(
                    "[fliggy] %s 最低价 ￥%.0f（PC 明细 %d 条）",
                    date, best["price"], len(flights))
            else:
                self.logger.warning("[fliggy] %s PC 页未解析到航班", date)
            self._sleep()
        return results

    def _fetch_pc(self, fc: str, tc: str, date: str) -> list:
        import urllib.parse
        url = self.URL_TPL.format(
            fc=fc, tc=tc, d=date,
            fn=urllib.parse.quote(_Q.CITY_NAME.get(fc, fc)),
            tn=urllib.parse.quote(_Q.CITY_NAME.get(tc, tc)))
        texts = set()
        flights = []
        share_map = {}
        with self.browser() as ctx:
            page = self.new_page(ctx)
            try:
                page.goto(url, wait_until="load", timeout=40000)
                last_len, stale = 0, 0
                for _ in range(8):   # 虚拟列表逐屏收集，收敛即提前退出
                    page.wait_for_timeout(3000)
                    try:
                        page.mouse.wheel(0, 1200)
                    except Exception:
                        pass
                    try:
                        for code, dc in (page.evaluate(self._SHARE_JS) or []):
                            share_map.setdefault(str(code), str(dc))
                    except Exception:
                        pass
                    txt = page.inner_text("body")
                    texts.add(txt)
                    if len(txt) == last_len:
                        stale += 1
                        if stale >= 2:   # 连续两屏内容不变=列表到底
                            break
                    else:
                        stale = 0
                    last_len = len(txt)
            except Exception as e:
                self.logger.warning("[fliggy] PC 页面异常: %s", e)
            full = "\n@@@\n".join(texts)
            flights = self._parse_pc_text(full, date, share_map)
            # 快照无条件落（每轮覆盖写不膨胀）：此前仅解析为空才落——而
            # 状态机总在「成功」产出缺字段/幻影行，debug/ 至今一份快照
            # 都没有，行状态机重写无据可查（HANDOFF §9.7）。幻影价
            # （CA8564 ￥700）取证同样靠它
            self._debug_snapshot(page, f"pc_{fc}{tc}_{date}")
            if not flights:
                # 未解析到航班时另落 nopx 标记快照（ctrip/tongcheng 同
                # 目录同名约定，v1.5.37）——行状态机失效有据可查
                self._debug_snapshot(page, f"nopx_{date}")
        return flights

    # ==================== 解析：行状态机 ====================
    @classmethod
    def _parse_pc_text(cls, text: str, date: str, share_map=None) -> list:
        """PC 页 innerText 行序（实测）：
        航班名行（东航MU8369 / 9C8945）
          → 机型行（中型机 737 共享|经停|）
          → 出发 HH:MM
          → 到达 HH:MM [第N天]
          → 起飞机场 / 到达机场
          → [准点率%]
          → ¥价格 [折扣] / 余票 / 订票
        share_map：营销号→实际承运（_SHARE_JS 采集），命中行挂
        shareCarrier 透传（展示层「共享·南方航空CZ6993」）。
        """
        from datetime import datetime as _dt, timedelta as _td
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        out, cur = [], None
        d0 = _dt.strptime(date, "%Y-%m-%d")
        for i, ln in enumerate(lines):
            m = cls._RE_FNO.match(ln)
            if m and len(ln) <= 14 and not ln.startswith(("第", "星期")):
                if cur and "price" in cur:
                    out.append(cur)
                cur = {"name": ln, "code": m.group(2), "_i": i,
                       "transCity": "", "depDate": date}
                sc = (share_map or {}).get(cur["code"])
                if sc:
                    cur["shareCarrier"] = sc
                continue
            if cur is None:
                continue
            # 已定价后仅放行价格行：同航班第二价格行（CA8564 ¥9900 与
            # ¥3960 双价行实证、疑跨舱位并列）此前被 "price" in cur 整行
            # 丢弃，明细可能只剩高价行——取低者为主价（明细供比价/告警），
            # 较高者记 _alt_price 留痕；第三个价格行同理收敛。
            # 行距锚（v1.5.41 热修）：并列舱位价紧邻首价格行（≤2 行）——
            # 无锚时虚拟列表尾航班的 cur 会一直开到文本结束，把页面尾部
            # 低价日历/推荐模块的任意 ¥N 吸进来 min() 取低（生产实锤：
            # CA8564 列表价 9900/3960 被尾部动态价 820→700 逐轮污染）
            if "price" in cur:
                pm = cls._RE_PRICE.search(ln)
                if (pm and "arrTime" in cur
                        and i - cur.get("_price_i", -99) <= 2):
                    pv = float(pm.group(1).replace(",", ""))
                    if 300 <= pv <= 50000:
                        cur["_alt_price"] = max(cur.get("_alt_price", 0),
                                                cur["price"], pv)
                        cur["price"] = min(cur["price"], pv)
                        cur["_price_i"] = i
                continue
            # 机型行（docstring 实测形态「中型机 737 共享|经停|」）：原状态机
            # 无该行分支整行丢弃 → 经停班被当直飞入库。保守分支：以「X型机」
            # 前缀锚定行形态再提取，机型取型号，行内含「经停」打 _via=停
            # 标记（normalize 产出 stopover）。证据等级：无报文佐证
            # （debug/ 无 fliggy 快照），仅 docstring 自述+现有行形态
            mm = re.match(r"^[大中小]型机\s*(\S+)", ln)
            if mm:
                cur.setdefault("plane", mm.group(1))
                if "经停" in ln:
                    cur["_via"] = "停"
                continue
            if cls._RE_HHMM.match(ln) and "depTime" not in cur:
                cur["depTime"] = ln
                continue
            ma = cls._RE_ARR.match(ln) if "depTime" in cur else None
            if ma:
                cur["arrTime"] = ln[:5]
                days = int(ma.group(2)) - 1 if ma.group(2) else 0
                cur["arrDate"] = (d0 + _td(days=days)).strftime("%Y-%m-%d")
                cur["crossDayDesc"] = f"+{days}天" if days else ""
                continue
            if ln in ("经济舱", "公务舱", "头等舱", "商务舱") and "cabin" not in cur:
                cur["cabin"] = ln
                continue
            # [准点率%] 行：纯数字串入库，与 tongcheng/ctrip/tuniu 形态
            # 一致（展示层统一拼「准点N%」，1-100 守卫同 tongcheng）。
            # 放宽带小数（v1.5.43）：DOM 快照实证 flight-ontime-rate 值形
            # 如「96.67%」「100.0%」，整数正则 0/34 命中（结构性全空）；
            # 四舍五入取整入库保持全站「准点N%」整数形态
            mp = re.match(r"^(\d{1,3}(?:\.\d+)?)\s*%$", ln)
            if mp and "prate" not in cur:
                try:
                    _pv = float(mp.group(1))
                except ValueError:
                    _pv = 0
                if 0 < _pv <= 100:
                    cur["prate"] = str(int(round(_pv)))
                    continue
            pm = cls._RE_PRICE.search(ln)
            if pm and "arrTime" in cur:
                # 价格 band 校验（同 qunar close 300-50000 口径）：越界
                # 不落 price → 该行最终不 append，debug log 留痕（v1.5.37）
                pv = float(pm.group(1).replace(",", ""))
                if 300 <= pv <= 50000:
                    cur["price"] = pv
                    cur["_price_i"] = i   # 双价行行距锚基点（v1.5.41）
                    # 折扣同行提取（v1.5.43）：span.discount「5.6折」35 处
                    # 实证全未解析；N折 形态校验同明细表 discount 门槛
                    if "discount" not in cur:
                        md = re.search(r"(\d(?:\.\d)?)折", ln)
                        if md:
                            cur["discount"] = md.group(1) + "折"
                else:
                    _LOG.debug("[fliggy] 价格 %s 越界，弃用该行 %s",
                               pv, cur.get("code", ""))
                continue
        if cur and "price" in cur:
            out.append(cur)
        # 去重（多屏收集同航班）与清理
        seen, clean = set(), []
        for f in out:
            f.pop("_i", None)
            f.pop("_price_i", None)
            f.setdefault("totalDuration", "")
            key = (f["code"], f.get("depTime"), f["price"])
            if key in seen:
                continue
            seen.add(key)
            clean.append(f)
        # 幻影价守卫（v1.5.41，qunar 0.5x 同思想）：明细中位数作群体锚，
        # 单行价 < 中位×0.5 视为页面异源模块污染弃行——行距锚杀「尾部
        # 吸入」，此守卫杀「模块恰好紧邻」的漏网（CA8564 ￥700 vs 明细
        # 群 2850+ 生产实锤）。合法跨舱位双价（9900/3960）与明细群同量
        # 级不误伤
        if len(clean) >= 4:
            med = sorted(f["price"] for f in clean)[len(clean) // 2]
            kept = [f for f in clean if f["price"] >= med * 0.5]
            for f in clean:
                if f["price"] < med * 0.5:
                    _LOG.warning("[fliggy] 幻影价守卫弃行 %s ￥%.0f"
                                 "（< 明细中位 ￥%.0f 的 0.5x，页面异源"
                                 "模块污染）", f.get("code"), f["price"], med)
            clean = kept
        return clean
