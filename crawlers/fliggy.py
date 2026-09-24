# -*- coding: utf-8 -*-
"""飞猪机票爬虫（PC SSR 版）

背景：移动端 mtop.trip.flight.flightSearch 已被官方下线
（NOT_SUPPORT），新版走 serverless 网关+强制登录，无法低成本接入。
发现：PC 搜索结果页 sjipiao.fliggy.com 为服务端直出（SSR）——
航班列表直接渲染在 HTML/DOM 中，无需接口，滚动收集 innerText
按行状态机解析即可（与 qunar DOM 兜底同套路）。

注意：PC 页价格口径为「不含税费」的展示价，与含税渠道差约
￥50-130，参与比价时天然略偏优——展示层飞猪标注税前。
页面仅含直达+经停+折叠中转块（中转行一期解析见 _parse_pc_text：
两段一转，起「XX中转」定证行入库；更多段异形块宁缺勿错弃）。
"""
import json
import logging
import re
from typing import List

from .base import BaseCrawler
from .qunar import QunarCrawler as _Q
from core.models import PRICE_MAX, PRICE_MIN, FlightPrice

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

    # 共享航班实际承运采集（仅展示不入指纹）：共享行挂
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
    # 中转换乘楼号采集（第九批，调研 dump 10-05 实证 1/1 中转
    # 块）：.transfer-city-label[data-content] 是 HTML 实体转义的 DOM
    # 片段（innerText 不渲染=仅报文内真值），解包后 <p class=
    # "transfer-p1">正定国际机场T2</p>——楼号在中转块内页面不直接
    # 可见。行容器 .flight-list-item + .J_line 取首段航班号归属（与
    # _SHARE_JS 同律：按行容器精确归属不做祖先启发），解析侧合并处
    # 以首段/二段号配对。 备注：上线后部署代际 4/4 在场已健康
    # （DB 低占比=中转行稀疏 0.6% 属供给侧量级），先观测期结束
    _TRANSFER_JS = (
        "() => { const out = [];"
        " document.querySelectorAll('[data-tooltip-type=\"transferCityInfo\"]')"
        ".forEach(el => {"
        " const dc = el.getAttribute('data-content') || '';"
        " const m = dc.match(/transfer-p1[^>]*>([^<]+)</);"
        " if (!m) return;"
        " const row = el.closest('.flight-list-item'); if (!row) return;"
        " const line = row.querySelector('.J_line');"
        " const t = line ? ((line.innerText || line.textContent) || '') : '';"
        " const fm = t.match(/((?:[A-Z][A-Z0-9]?|\\d[A-Z])\\d{3,4})/);"
        " if (fm) out.push([fm[1], m[1]]); });"
        " return out; }")
    # 中转说明图例（调研 R4，10-05 dump 实证 1/1 中转块在场）：
    # dd.transfer_note 是页面级筛选区图例（全页唯一，不在行容器内——与
    # tongcheng doc.check「转机免安检」同性质），HTML 实体转义 innerText
    # 不可见，须读属性。全文「2.转机过程需旅客自行处理，请预留足够时间
    # 处理行李和重新办理登机手续」= 需重新值机/托运语义，解析侧对
    # transCity 定证的中转行落 transferBaggage='recheck'（ctrip
    # 「行李代转运」同语义位，补全五渠道协议缺口）。守卫见
    # _parse_pc_text。 观测转正（撤先观测备注）：修复生效后
    # DB 累计 11/11 全部 recheck、值域单一、与 transCity/transTerminal
    # 严格配对、「图例在场而行实为直挂」反例 0。
    # 必修（调研三份独立 HTML+活页探针双实证）：data-content
    # 实际挂在内层 div.body.J_Content 上，dd 开标签恒无此属性——首版读
    # dd 自身 getAttribute 恒 null→守卫子串永假，自上线零生效（DB 部署
    # 后 recheck 0/204，零脏值零危害故不回滚）；页面 2 个同构图例 dd
    # 全部水合同一文案，取首个非空
    _RECHECK_JS = (
        "() => { const els = document.querySelectorAll("
        "'dd.transfer_note [data-content]');"
        " for (const el of els) { const t = el.getAttribute('data-content')"
        " || ''; if (t) { return t; } } return ''; }")
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
        transfer_map = {}
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
                    try:
                        for code, tt in (page.evaluate(self._TRANSFER_JS) or []):
                            transfer_map.setdefault(str(code), str(tt))
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
            # 页面级中转说明图例（滚屏后读一次：筛选区元素不随虚拟列表
            # 销毁；无中转块页面元素不存在返回空串）
            recheck_note = ""
            try:
                recheck_note = str(page.evaluate(self._RECHECK_JS) or "")
            except Exception:
                pass
            flights = self._parse_pc_text(full, date, share_map,
                                          transfer_map, recheck_note)
            # 快照必须无条件落（每轮覆盖写不膨胀）：仅解析为空才落不可行
            # ——状态机总在「成功」产出缺字段/幻影行，行状态机重写
            # 无据可查。幻影价
            # （CA8564 ￥700）取证同样靠它
            self._debug_snapshot(page, f"pc_{fc}{tc}_{date}")
            if not flights:
                # 未解析到航班时另落 nopx 标记快照（ctrip/tongcheng 同
                # 目录同名约定）——行状态机失效有据可查
                self._debug_snapshot(page, f"nopx_{date}")
        return flights

    # ==================== 解析：行状态机 ====================
    @classmethod
    def _parse_pc_text(cls, text: str, date: str, share_map=None,
                       transfer_map=None, recheck_note: str = "") -> list:
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
        recheck_note：页面级中转说明图例（dd.transfer_note[data-content]，
        _RECHECK_JS 采集），含「重新办理登机手续」精确子串时对中转定证
        行落 transferBaggage='recheck'（页面级图例非行级归属，只对中转
        行生效；不覆盖已有值——未来若现 direct 证据不得被图例翻转）。
        """
        from datetime import datetime as _dt, timedelta as _td
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        out, cur = [], None
        # 中转块首段暂存（一期）：中转块=首段航班名行+机型行 →
        # 二段航班名行+机型行 → 4 条「N月N日 HH:MM」→ 出发机场 →「城市
        # 中转」→ 到达机场 → … → ¥价。二段行头会把未定价的 cur（首段）
        # 重置——暂存 pend，「XX中转」行定证中转块时回捞合并；普通直飞
        # 流 pend 恒被下一轮 append/head 覆盖丢弃，行为不变
        pend = None
        d0 = _dt.strptime(date, "%Y-%m-%d")
        for i, ln in enumerate(lines):
            m = cls._RE_FNO.match(ln)
            if m and len(ln) <= 14 and not ln.startswith(("第", "星期")):
                if cur and "price" in cur and not cur.get("_drop"):
                    out.append(cur)
                    pend = None
                elif cur is not None:
                    pend = cur
                cur = {"name": ln, "code": m.group(2), "_i": i,
                       "transCity": "", "depDate": date}
                sc = (share_map or {}).get(cur["code"])
                if sc:
                    cur["shareCarrier"] = sc
                continue
            if cur is None:
                continue
            # 已定价后仅放行价格行：同航班第二价格行（CA8564 ¥9900 与
            # ¥3960 双价行实证、疑跨舱位并列）不得被 "price" in cur 整行
            # 丢弃——否则明细可能只剩高价行。取低者为主价（明细供比价/告警），
            # 较高者记 _alt_price 留痕；第三个价格行同理收敛。
            # 行距锚（热修）：并列舱位价紧邻首价格行（≤2 行）——
            # 无锚时虚拟列表尾航班的 cur 会一直开到文本结束，把页面尾部
            # 低价日历/推荐模块的任意 ¥N 吸进来 min() 取低（生产实锤：
            # CA8564 列表价 9900/3960 被尾部动态价 820→700 逐轮污染）
            if "price" in cur:
                # 中转机建燃油行（第八批 dump 实证）：transferItem
                # 中转行价格行 +1 行独立成行「¥240机建燃油」（=两段机建+
                # 燃油合计，中转行内 100% 在场）——第七批挂起注「需点击
                # 展开」被证伪，SSR/innerText 静态可见。行距锚同余票行；
                # 值域守卫 60-600（单段 60-190、两段 120-380、三段上限
                # 放宽，拒绝 k 量级脏值）。前置判（税行含 ¥ 会被 _RE_PRICE
                # 命中，后置 elif 永不可达——首版实跑 0 命中根因）；守卫
                # 拒收的税行也不得落入价格分支（¥560 类会当副价 min 吞）。
                # 首版只采+展示：FLIGGY_TAX_PAD 已于 归零重标定
                # （12,303 对中位比 1.000），无配对样本证据不接达标口径
                _taxm = re.match(r"^[¥￥](\d{2,4})机建燃油$", ln)
                if (_taxm and i - cur.get("_price_i", -99) <= 2
                        and "transferTax" not in cur
                        and 60 <= int(_taxm.group(1)) <= 600):
                    cur["transferTax"] = int(_taxm.group(1))
                elif not _taxm:
                    pm = cls._RE_PRICE.search(ln)
                    if (pm and "arrTime" in cur
                            and i - cur.get("_price_i", -99) <= 2):
                        pv = float(pm.group(1).replace(",", ""))
                        if PRICE_MIN <= pv <= PRICE_MAX:
                            # 高档舱词跟随它所在价格行的报价：首行词
                            # （cur["cabin"]）配首行价、本行行尾词配本行
                            # 价——高价带词（公务/商务/头等）落 bizPrice
                            # （与 qunar/tuniu/tongcheng 同键同协议 int，
                            # dump 实证 CA8564 9900 与 tongcheng 同值跨
                            # 渠道互证）；无词高价（同舱双价/「全价」）
                            # 与经济舱词宁缺勿错不落；单报价行主价即
                            # 高档舱价，不重复记账（只在本分支可达）
                            _hi_mc = re.search(r"(公务舱|商务舱|头等舱)$", ln)
                            if pv > cur["price"]:
                                _hi_p, _hi_c = pv, (
                                    _hi_mc.group(1) if _hi_mc else None)
                                _lo_p = cur["price"]
                            else:
                                _hi_p, _hi_c = cur["price"], cur.get("cabin")
                                _lo_p = pv
                                # 首价格行折扣词（N折/「全价」）描述的
                                # 是被撤高价——保留价来自低者，词不随
                                # 行，撤键宁缺勿错（与 cabin 撤键同律）
                                cur.pop("discount", None)
                            if (_hi_c in ("公务舱", "商务舱", "头等舱")
                                    and _hi_p > _lo_p):
                                # 多带词高档行取最低（协议=「高档舱最低
                                # 参考价」，qunar businessClassMinPrice/
                                # tuniu ADT 最低 baseFare 同语义；取
                                # max 会成「公务￥头等价」舱名数值双误）。
                                # 旧主价对（cur["cabin"]+cur["price"]）
                                # 是另一带词高档行——首行词在 cabin 未及
                                # 落 bizPrice，须一并入 min 候选
                                _cands = [int(_hi_p)]
                                if cur.get("cabin") in (
                                        "公务舱", "商务舱", "头等舱"):
                                    _cands.append(int(cur["price"]))
                                cur["bizPrice"] = min(_cands)
                            cur["_alt_price"] = max(cur.get("_alt_price", 0),
                                                    cur["price"], pv)
                            cur["price"] = min(cur["price"], pv)
                            cur["_price_i"] = i
                            # 跨舱位并列价：保留价来自低者，首价格行的舱位
                            # 词不再描述它——撤键宁缺勿错（词对高价的
                            # 归属已由 bizPrice 记账）
                            cur.pop("cabin", None)
                    # 余票紧张行：.less-tag 文本「少量/紧张/N张」
                    # 在 innerText 序列位于价格行后 ≤2 行（docstring「¥价格/
                    # 余票/订票」，dump 26/32 行在场）——已定价后仅放行价格
                    # 行的状态机在此唯一可达点收；行距锚防吸入其他模块同形
                    # 短行。落既有键 fewTicket 与 qunar「票少」同名同义
                    elif (i - cur.get("_price_i", -99) <= 2
                          and "fewTicket" not in cur
                          and re.match(r"^(少量|紧张|\d+张)$", ln)):
                        cur["fewTicket"] = ln
                continue
            # 机型行（docstring 实测形态「中型机 737 共享|经停|」）：原状态机
            # 无该行分支整行丢弃 → 经停班被当直飞入库。保守分支：以「X型机」
            # 前缀锚定行形态再提取，机型取型号，行内含「经停」打 _via=停
            # 标记（normalize 产出 stopover）。证据等级：debug/ 有快照
            # （起），行形态与快照一致。
            # 前缀体量词入 planeSize（「大型机/中型机/小型机」，
            # 宽体舒适度信号——fliggy 报文/页面均无 planeModelName 类
            # 结构化源，DOM 行首词是唯一真值）
            mm = re.match(r"^([大中小])型机\s*(\S+)", ln)
            if mm:
                cur.setdefault("plane", mm.group(2))
                cur.setdefault("planeSize", mm.group(1) + "型机")
                # has-food-label 双态标签：机型行同 <p> 容器的
                # label 文本随 innerText 落行尾（「中型机 737 有餐
                # 食」/「中型机 320 无餐食」同位同构，dump 实证两态
                # 均有实发）——负向无营销虚增动机、正向是航司如实
                # 披露，出现即真；落既有 meal 键与 ctrip/tuniu 同值域
                if "无餐食" in ln:
                    cur.setdefault("meal", "无餐食")
                elif "有餐食" in ln:
                    cur.setdefault("meal", "有餐食")
                if "经停" in ln:
                    cur["_via"] = "停"
                continue
            # 机场行：「乌鲁木齐天山国际机场」（出发侧单航站
            # 楼无 T 码）/「虹桥国际机场T2」（到达侧 35/35 带码）——
            # 首个机场行挂 depTerminal、第二个挂 arrTerminal（qunar DOM
            # 同序状态机口径），T 码取行尾全匹配、无码如实留空不造。
            # depTime 守卫防页面异源模块（日历/推荐）含「机场」文本吸入。
            # 行文本剥尾部 T 码即机场名，落 depAirport/
            # arrAirport（「虹桥国际机场」原值，渲染端统一剥后缀）
            if ("机场" in ln and ("depTime" in cur or cur.get("_dtl"))
                    and "price" not in cur):
                tm = re.search(r"(T\d+)\s*$", ln)
                t = tm.group(1) if tm else ""
                air_name = ln[:tm.start()].strip() if tm else ln.strip()
                if "depTerminal" not in cur:
                    cur["depTerminal"] = t
                    cur["depAirport"] = air_name
                elif "arrTerminal" not in cur:
                    cur["arrTerminal"] = t
                    cur["arrAirport"] = air_name
                continue
            # 中转块日期时刻行（一期）：「10月05日 15:15」形态
            # 每段起降一条（两段 4 条：首段起/落+二段起/落），与直飞行
            # 裸 HH:MM 形态互斥（_RE_HHMM 锚定不匹配）——先行暂存 _dtl，
            # 「XX中转」定证行处统一定日期（月日无年份，按航线日期年份
            # 推算、跨年进位）；不足 4 条（折叠半截块）宁缺勿错不定时刻，
            # 该行随后无 arrTime 自然不落价（与既有丢弃行为一致）
            md = re.match(r"^(\d{1,2})月(\d{1,2})日\s*(\d{1,2}:\d{2})$", ln)
            if md and cur is not None and "price" not in cur:
                cur.setdefault("_dtl", []).append(
                    (int(md.group(1)), int(md.group(2)), md.group(3)))
                continue
            # 中转定证行：「石家庄中转」（城市+中转，行序在两机场行之间，
            # 不含「机场」二字不触上行分支）——此刻 cur=二段行、pend=首
            # 段行，合并成统一 schema 中转行（code「A/B」tongcheng 同形、
            # name 取首段；时刻取 _dtl 首末条=整体起降，衔接=首段落−二段
            # 起结构化真值，layoverSrc=transInfo 豁免 flightnorm 1440
            # 回绕判伪，同 qunar/tongcheng 协议）
            mt = re.match(r"^([\u4e00-\u9fa5]{2,8})中转$", ln)
            if mt and cur is not None and "price" not in cur:
                # 二次定证=三段两转异形块（实跑复现：
                # 「城1中转」已消费 _dtl 定盘，后续「中转机场」行错占
                # arr 位、「城2中转」覆写 transCity、pend 顶成二段——
                # 产出丢首段/中转机场当到达场/末城当经停的多字段错值行，
                # 看似正常入库最脏）——整行宁缺勿错弃，_drop 挡两侧 append
                if cur.get("transCity"):
                    cur["_drop"] = True
                    pend = None
                    continue
                cur["transCity"] = mt.group(1)
                _dtl = cur.pop("_dtl", None) or []
                if len(_dtl) >= 4:
                    try:
                        _mk = lambda m, d, t: _dt(
                            d0.year + (1 if (m, d) < (_dtl[0][0],
                                                      _dtl[0][1]) else 0),
                            m, d, int(t[:2]), int(t[3:]))
                        _d_dep, _d_arr = _mk(*_dtl[0]), _mk(*_dtl[-1])
                        _d_l1a, _d_l2d = _mk(*_dtl[1]), _mk(*_dtl[2])
                        cur["depTime"] = _dtl[0][2]
                        cur["arrTime"] = _dtl[-1][2]
                        cur["depDate"] = _d_dep.strftime("%Y-%m-%d")
                        cur["arrDate"] = _d_arr.strftime("%Y-%m-%d")
                        _xd = (_d_arr.date() - _d_dep.date()).days
                        cur["crossDayDesc"] = f"+{_xd}天" if _xd > 0 else ""
                        _lay = int((_d_l2d - _d_l1a).total_seconds() // 60)
                        if _lay > 0:
                            cur["layover"] = _lay
                            cur["layoverSrc"] = "transInfo"
                            cur["lay2dep"] = _dtl[2][2]
                    except ValueError:
                        pass
                if pend is not None:
                    cur["code"] = f"{pend['code']}/{cur['code']}"
                    cur["name"] = pend["name"]
                    if pend.get("shareCarrier"):
                        cur.setdefault("shareCarrier", pend["shareCarrier"])
                    # 首段餐食标签随段合并（卫生约束：不得只
                    # 搬 code/name/shareCarrier——首段「无餐食/有
                    # 餐食」二段未标时标签整段丢失；meal 值域={有
                    # 餐食,无餐食}双态，两段异值时保守仲裁为「无
                    # 餐食」（一段无餐食=全程存在无餐食段，正向
                    # 优先会掩蔽该事实），同值/单侧照搬）
                    if pend.get("meal"):
                        if cur.get("meal") and cur["meal"] != pend["meal"]:
                            cur["meal"] = "无餐食"
                        else:
                            cur.setdefault("meal", pend["meal"])
                    # 中转换乘楼号（第九批，_TRANSFER_JS 采集）：
                    # 以首段/二段号配对（行容器归属首段号，二段号兜底）；
                    # 「正定国际机场T2」剥「国际机场/机场」后缀对齐
                    # qunar「咸阳T3」/ctrip transTerminal 同形
                    _tt = ((transfer_map or {}).get(pend["code"])
                           or (transfer_map or {}).get(
                               cur["code"].split("/")[-1]) or "")
                    if _tt:
                        cur["transTerminal"] = re.sub(
                            r"国际机场|机场", "", _tt, count=1)
                    # （调研 R4）：页面级图例守卫三 AND——(a) 本行
                    # 中转已定证（此处 transCity 刚落）；(b) 图例含「重新
                    # 办理登机手续」精确子串（渠道改文案即静默不落）；
                    # (c) 不覆盖已有值。 观测转正（撤先观测备
                    # 注）：修复生效后累计 11/11 全部 recheck、反例 0，
                    # 反例出现即回滚该置值
                    if ("重新办理登机手续" in recheck_note
                            and not cur.get("transferBaggage")):
                        cur["transferBaggage"] = "recheck"
                    pend = None
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
            # 放宽带小数：DOM 快照实证 flight-ontime-rate 值形
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
                # 价格 band 校验（全链路价带单源 PRICE_MIN=100）：越界
                # 不落 price → 该行最终不 append，debug log 留痕
                pv = float(pm.group(1).replace(",", ""))
                if PRICE_MIN <= pv <= PRICE_MAX:
                    cur["price"] = pv
                    cur["_price_i"] = i   # 双价行行距锚基点
                    # 折扣同行提取：span.discount「5.6折」35 处
                    # 实证全未解析；N折 形态校验同明细表 discount 门槛
                    if "discount" not in cur:
                        md = re.search(r"(\d(?:\.\d)?)折", ln)
                        if md:
                            cur["discount"] = md.group(1) + "折"
                        elif "全价" in ln:
                            # 「全价」=无折扣可售（SSR span.discount 词
                            # 域 10-06 17/31=55%）；qunar/tuniu/tongcheng
                            # 同域已在产，消费端 discount_txt 单源放行。
                            # 双价行归属由合并分支裁决（词不随行）
                            cur["discount"] = "全价"
                    # 行尾舱位词（调研实证「¥9900 商务舱」span.discount
                    # 形态）：单报价行的裸价无从辨识舱位；$ 锚行尾，
                    # 「全价」类非舱位词天然不匹配（discount「N折」值域
                    # 协议与 cabin 双零误配路径）。双价行（跨舱位并列）
                    # 不保此键——取低者为主价时首行舱位词不再描述保留价
                    if "cabin" not in cur:
                        mc = re.search(r"(经济舱|公务舱|头等舱|商务舱)$", ln)
                        if mc:
                            cur["cabin"] = mc.group(1)
                else:
                    _LOG.debug("[fliggy] 价格 %s 越界，弃用该行 %s",
                               pv, cur.get("code", ""))
                continue
        if cur and "price" in cur and not cur.get("_drop"):
            out.append(cur)
        # 去重（多屏收集同航班）与清理
        seen, clean = set(), []
        for f in out:
            f.pop("_i", None)
            f.pop("_price_i", None)
            f.pop("_dtl", None)   # 异形块半截暂存
            f.pop("_drop", None)
            # _alt_price 是双价行留痕内部键，无任何消费端（_via 有
            # normalize/main 哨兵消费故保留）——不 pop 则双价行
            # 一出现即泄漏进 extra（卫生语义）
            f.pop("_alt_price", None)
            # totalDuration 不再 setdefault 空串（调研占位键卫生：
            # PC 无时长源，7,464/7,464 全空=永久空键纯 DB 噪音）——有值
            # 才落键，与 leftTickets 稀疏落键同口径；消费端全 .get() 风格
            # +normalize 空值安全，缺键无行为差
            key = (f["code"], f.get("depTime"), f["price"])
            if key in seen:
                continue
            seen.add(key)
            clean.append(f)
        # 幻影价守卫（qunar 0.5x 同思想）：明细中位数作群体锚，
        # 单行价 < 中位×0.5 视为页面异源模块污染弃行——行距锚杀「尾部
        # 吸入」，此守卫杀「模块恰好紧邻」的漏网（CA8564 ￥700 vs 明细
        # 群 2850+ 生产实锤）。合法跨舱位双价（9900/3960）与明细群同量
        # 级不误伤。
        # 中转真值豁免（实跑复现）：layoverSrc=
        # transInfo 行的时刻/衔接是渠道结构化真值非页面猜测，其价也是
        # 独立报价——低价中转恰是本批核心价值行（¥900 中转 vs 直飞群
        # 2020 曾被 0.5x 中位锚误杀弃行），守卫只服务猜测值（与
        # flightnorm 1440 回绕判伪豁免同哲学）
        if len(clean) >= 4:
            med = sorted(f["price"] for f in clean)[len(clean) // 2]
            kept = [f for f in clean if f["price"] >= med * 0.5
                    or f.get("layoverSrc") == "transInfo"]
            for f in clean:
                if (f["price"] < med * 0.5
                        and f.get("layoverSrc") != "transInfo"):
                    _LOG.warning("[fliggy] 幻影价守卫弃行 %s ￥%.0f"
                                 "（< 明细中位 ￥%.0f 的 0.5x，页面异源"
                                 "模块污染）", f.get("code"), f["price"], med)
            clean = kept
        return clean
