# -*- coding: utf-8 -*-
"""智行 App 渠道（cn.suanya.zhixing）。

数据面事实（2026-10-29 实测）：
  * 64 位包 `arm64-v8a`，装到 MuMu Android 15 实例；
  * **未登录**时列表里单班票价被遮成 `¥3??`，但顶部日历条的
    每日最低价是真实数字（¥450 / ¥430 / ¥377…）；
  * 因此未登录只产出**日历族**结果：每天一条最低价、无航班号。
    这属于 `core.models.CAL_PATH_FAMILY` 语义，不能冒充明细。

登录后是否放开单班价，P3 接内嵌登录画面时再验；本文件不预设。
"""
from __future__ import annotations

import json
from typing import List

from core.models import FlightPrice

from .app_base import AppCrawler
from .app_zhixing_parse import (detect_state, parse_calendar,
                                parse_flight_rows)

import time

# 日历条上的日期是 MM-DD；换算年需要上下文（跨年时 12-31 → 01-01）
_APP_PKG = "cn.suanya.zhixing"
_APP_LABEL = "智行旅行"


def _cal_extra(price: float, ymd: str) -> str:
    """日历价行 → **单元素航班数组**（与五个浏览器渠道同一种形状）。

    旧实现把 extra 写成元信息对象（`{"calendar": true, ...}`），而所有
    消费方（webui 列表池 / Alerter 推送池 / report.recent_platform_flights）
    都是 `if not isinstance(obj, list): continue`——App 采到的日历价
    在库里有、页面与推送里一条都看不到。
    """
    return json.dumps([{
        "price": float(price), "name": "日历最低价", "code": "",
        "depDate": ymd, "depTime": "", "arrTime": "", "calendar": True,
    }], ensure_ascii=False)


def _md_to_ymd(md: str, anchor: str) -> str:
    """把 MM-DD 补成 YYYY-MM-DD，以查询日期为锚处理跨年。"""
    if not md or len(md) != 5:
        return ""
    try:
        mm, dd = int(md[:2]), int(md[3:])
    except ValueError:
        return ""
    try:
        ay, am = int(anchor[:4]), int(anchor[5:7])
    except (ValueError, IndexError):
        return ""
    year = ay
    # 日历条通常跨月，12 月查询出现 01-02 即翌年
    if am == 12 and mm == 1:
        year = ay + 1
    elif am == 1 and mm == 12:
        year = ay - 1
    return f"{year:04d}-{mm:02d}-{dd:02d}"


class AppZhixingCrawler(AppCrawler):
    name = "app_zhixing"
    package = _APP_PKG
    label = _APP_LABEL
    # 测试用：跳过 UI 导航（真实采集必须为 False，否则会把上次的航线当结果）
    _skip_route = False

    # ---------- 对外 ----------
    def login_url(self) -> str:
        """App 渠道没有可粘贴的 URL；返回人类可读的登录入口描述。"""
        return f"android://{_APP_PKG}（App 内：我的 → 登录）"

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        rt = self.runtime()
        ok, why = rt.ensure_ready()
        if not ok:
            # 设备/运行时不可用：明确入账，绝不伪装成"没航班"
            self.path_note("android-runtime", "unsupported",
                           detail=f"runtime not ready: {why}")
            self.logger.warning("[%s] Android 运行时未就绪：%s",
                                self.name, why)
            return []

        dev = rt.device()
        if dev is None:
            self.path_note("android-device", "unsupported",
                           detail="device unavailable")
            return []

        # 「登录一次永久复用」+ 清权限框 + 清 ANR：统一前置（与其它 App
        # 渠道同源）。快照恢复会 force-stop 再解包，必须在任何 UI 操作之前，
        # 否则会把正在操作的页面顶掉；恢复后最容易撞上「无响应」死锁。
        self.prepare_device(dev)

        # 异常逃逸不在这里写：调用方统一走 `AppBaseCrawler.safe_fetch()`，
        # 它已 try/except 并记 `app-error`（含本段抛出的一切）。此处再包一层
        # 只是重复防御，且会抢在 safe_fetch 的去重判断之前多记一条。
        with rt.device_lock():
            return self._fetch_locked(dev, from_city, to_city, dates)

    # ---------- 内部 ----------
    def _fetch_locked(self, dev, from_city: str, to_city: str,
                      dates: List[str]) -> List[FlightPrice]:
        import time

        started = time.time()
        # 拦路物必须最先处理：广告弹层会盖住首页，后面所有点击都落在
        # 广告上（实测：不先关广告，设航线会点到弹层里的空白）。
        # 验证码/人脸在这里直接返回，不做任何后续操作。
        warm = dev.dump()
        if warm:
            warm, block = self._clear_blockers(dev, warm)
            if block.blocking:
                self.path_note("app-blocker", block.kind,
                               detail=block.detail)
                self.logger.warning("[%s] 页面被拦截：%s（%s）",
                                    self.name, block.kind, block.detail)
                return []

        # 必须先按配置设航线：App 会停在上次的查询页，不设就会把
        # 「上一次的航线」当成这次的结果（实机踩过：配置 SHA→BJS，
        # App 还停在上海→北京，数据看起来"正常"但根本不是这一条）。
        # 但航线没变时跳过：实测 set_flight_route 占整轮 86%（34.4s/40s），
        # 其中大半是重启 App + 重设同一对城市，纯属白跑。
        same = self._route_unchanged(dev, from_city, to_city)
        if same:
            self.logger.info("[%s] 航线未变（%s→%s），跳过重设",
                             self.name, from_city, to_city)
        else:
            ok, detail = self._set_route(dev, from_city, to_city, dates)
            if not ok:
                self.path_note("app-route", "blocked", detail=detail,
                               ms=int((time.time() - started) * 1000))
                self.logger.warning("[%s] 设置航线失败：%s", self.name, detail)
                return []
            self._remember_route(from_city, to_city)

        # 长窗口日历的入口在**首页的日期行**，一旦点了「机票查询」进了
        # 列表页就没有日历图标了（实测：列表页只有 8 天日期条、无日历
        # 入口）。所以必须在导航完成后、任何进一步跳转之前读弹层。
        #
        # 这里刻意**不**复用上面那次 dump：那次在设航线之前取的，页面
        # 可能还是旧航线/旧弹层，拿它定位日期入口会点到错的地方。
        # 省 5s 不如不错——宁可多取一次页面。
        #
        # 进日历**之前**必须再过一次拦路物：广告可能在设航线的过程中才
        # 弹出来（实测：首页无广告，点完查询才弹「新人专享」）。此时
        # open_date_dialog 会在这张广告上瞎点，日历永远打不开，而广告
        # 页还会被后续 dump 当成业务页面解析——整轮白跑且看不出原因。
        pre = dev.dump()
        if pre:
            pre, pblock = self._clear_blockers(dev, pre)
            if pblock.blocking:
                self.path_note("app-blocker", pblock.kind,
                               detail=pblock.detail)
                self.logger.warning("[%s] 日历前页面被拦截：%s（%s）",
                                    self.name, pblock.kind, pblock.detail)
                return []
        long_xml = self._try_long_calendar(dev, keep_open=True)
        cal_rows = []
        if long_xml:
            cal_rows = self._emit_from_dialog_by_xml(
                long_xml, from_city, to_city, dates,
                int((time.time() - started) * 1000))

        # 日历价只是「每天一条最低价」，没有航班号/时刻，不能当作明细。
        # 目标日在首页 8 天条之外时，_set_route 里选不上日期，必须在这里
        # 用长窗口把日期选上（_pick_date 已按 resource-id 定位），再点
        # 「机票查询」进列表页——实测 11-05 这样能拿到 6 条真实明细。
        detail, blocked = self._enter_detail_and_parse(
            dev, from_city, to_city, dates)
        if blocked:
            # 已经按拦截入账：不回退日历价，否则用户看到「有价」而
            # 实际是被人机验证挡住，问题被数据掩盖。
            self._close_calendar(dev)
            self.login_suspect = True
            return []
        if detail:
            self._park_at_home(dev)
            return detail
        if cal_rows:
            self._close_calendar(dev)
            return cal_rows
        self._close_calendar(dev)

        xml = dev.dump()
        if not xml:
            self.path_note("app-dump", "timeout",
                           detail="empty ui hierarchy",
                           ms=int((time.time() - started) * 1000))
            return []

        # 拦路物优先于数据解析：广告可自动关一次再读；验证码/人脸只能人工，
        # 记独立状态并留下现场，绝不当成"没票"或"没数据"。
        xml, block = self._clear_blockers(dev, xml)
        if block.blocking:
            self.path_note("app-blocker", block.kind, detail=block.detail)
            self.logger.warning("[%s] 页面被拦截：%s（%s）",
                                self.name, block.kind, block.detail)
            return []

        state = detect_state(xml)
        if state == "login":
            self.login_suspect = True
            self.path_note("app-list", "login",
                           detail="需要登录（未登录只能拿日历价）")
            return []
        if state == "empty":
            self.path_note("app-list", "empty", detail="页面明确无航班")
            return []
        # calendar：页面已经是「选择日期」长窗口日历，直接按它解析，
        # 不必再打开弹层（它本来就在）。
        if state == "calendar":
            return self._emit_calendar(xml, from_city, to_city, dates,
                                       int((time.time() - started) * 1000))
        if state == "unknown":
            # 有页面但既不认登录也不认空态：这是"没看懂"，不是"没航班"。
            # 记 timeout 而不是 blocked：`blocked` 在 pacing 里归 captcha
            # （300s 阶梯熔断），而"页面结构不认识"重试也不会变好，
            # 更不该让整个 App 渠道停摆——这是解析器要修，不是要躲。
            self.path_note("app-list", "timeout",
                           detail="无法识别的页面状态（可能是 App 改版）")
            return []

        # 主动打开「选择日期」弹层再读一次：弹层是跨月长窗口日历，
        # 首页条只有 8 天。打开失败不影响结果，回落到首页条解析。
        return self._emit_calendar(xml, from_city, to_city, dates,
                                   int((time.time() - started) * 1000))

    def _park_at_home(self, dev):
        """把 App 留在首页，方便下一轮跳过重设航线。

        实测：读完长窗口后 App 停在「选择日期」透明 Activity，下一轮
        首页判据为假 → 又要重启 App + 重设城市，白花 35s（占整轮 86%）。
        收尾时退回到首页，下一轮就能走"航线未变"的快路径。
        """
        try:
            for _ in range(3):
                xml = dev.dump()
                if "机票查询" in xml and "Search_Calendar_Dialog" not in xml:
                    return True
                dev.keyevent("KEYCODE_BACK")
                time.sleep(1.5)
        except Exception:
            pass
        return False

    def _emit_from_dialog_by_xml(self, xml: str, from_city: str, to_city: str,
                                 dates: List[str], ms: int):
        """从长窗口日历页 XML 产出；不是日历页时返回 []。"""
        from .app_zhixing_calendar import (has_calendar_dialog,
                                           parse_date_dialog)
        if not has_calendar_dialog(xml):
            return []
        rows = parse_date_dialog(xml)
        if not rows:
            self.path_note("日历", "parse_error",
                           detail="日历弹层未解析出格子", ms=ms)
            return []
        return self._emit_from_dialog(rows, from_city, to_city, dates, ms)

    def _try_long_calendar(self, dev, keep_open: bool = False) -> str:
        """打开日期弹层并取页面；失败返回空串（不抛）。

        必须轮询到**价格渲染出来**再取：弹层打开瞬间格子已在，但
        price 子节点还没填（实测第一帧 73 格全无价、2s 后 37 格有价）。
        取第一帧会得到一屏「有日期无价」的页面，emit 出来就是 0 条，
        表现为「长窗口日历有入口但什么也没采到」。

        keep_open=True 时不关弹层——调用方要在这个弹层里点日期进明细。
        """
        try:
            from .app_zhixing_calendar import parse_date_dialog
            from .app_zhixing_nav import close_date_dialog, open_date_dialog
            ok, detail = open_date_dialog(dev, log=self.logger)
            if not ok:
                self.logger.info("[%s] 长窗口日历未打开：%s",
                                 self.name, detail)
                return ""
            xml = ""
            deadline = time.time() + 15
            while time.time() < deadline:
                xml = dev.dump()
                if not xml:
                    time.sleep(1)
                    continue
                rows = parse_date_dialog(xml)
                if rows and any(r.get("price") for r in rows):
                    break
                time.sleep(1)
            if not keep_open:
                close_date_dialog(dev)   # 关掉，别把状态留给下一轮
            return xml
        except Exception as e:
            self.logger.info("[%s] 长窗口日历异常：%s", self.name,
                             type(e).__name__)
            return ""

    def _emit_from_dialog(self, dialog_rows, from_city: str, to_city: str,
                          dates: List[str], ms: int) -> List[FlightPrice]:
        """从「选择日期」弹层产出日历价（长窗口）。

        与首页日历条同属**日历族**：每天一条最低价、无航班号。
        差别只在覆盖长度（弹层跨月，首页约 8 天）。
        """
        wanted = set(dates or [])
        out: List[FlightPrice] = []
        for row in dialog_rows:
            ymd = row["date"]
            if wanted and ymd not in wanted:
                continue
            price = row.get("price")
            if price is None:
                continue
            out.append(FlightPrice(
                platform=self.name,
                from_city=from_city, to_city=to_city,
                depart_date=ymd, price=float(price),
                extra=_cal_extra(price, ymd),
                prov=f"app:{_APP_PKG}:calendar-dialog",
            ))

        priced = [r for r in dialog_rows if r.get("price")]
        covered = {r["date"] for r in dialog_rows}
        outside = len([d for d in wanted if d and d not in covered])
        detail = f"长窗口日历 {len(out)} 天 / 已渲染 {len(covered)} 格" \
                 f"（有价 {len(priced)}）"
        if outside:
            detail += f" · {outside} 个目标日期未渲染"
        self.path_note("日历", "calendar", rows=len(out),
                       date=(dates[0] if dates else ""), detail=detail, ms=ms,
                       url=f"android://{_APP_PKG}?view=calendar")
        if not out:
            self.logger.info("[%s] 长窗口日历命中 0 条（%s）",
                             self.name, detail)
        return out

    def _close_calendar(self, dev):
        """把可能还开着的长窗口日历关掉（收尾用，失败不算错）。"""
        try:
            from .app_zhixing_nav import close_date_dialog
            close_date_dialog(dev)
        except Exception:
            pass

    def _enter_detail_and_parse(self, dev, from_city: str, to_city: str,
                                dates: List[str]):
        """逐日期：选上该日 → 点「机票查询」→ 解析列表页明细。

        日历价只是「每天一条最低价」，没有航班号与时刻，不能当明细用。
        返回全部日期的明细；一个日期都没拿到返回 []。

        逐日期循环与其它渠道一致（ctrip/qunar 也是 `for date in dates`）：
        只处理 dates[0] 会让配置的其余日期静默丢数据。

        返回 (prices, blocked)。blocked 为真表示撞上广告/验证码/人脸：
        调用方**不得**回退到日历价——那会把「被人挡住」伪装成「有数据」。
        """
        if self._skip_route:
            return [], False
        targets = [d for d in (dates or []) if d]
        if not targets:
            return [], False
        got: List[FlightPrice] = []
        for i, target in enumerate(targets):
            rows, block = self._one_date_detail(dev, from_city, to_city,
                                                target, first=(i == 0))
            if block is not None and block.blocking:
                # 拦截要如实入账，且不强当「这天没票」继续跑完：
                # 广告可以关，验证码/人脸只能等人，继续跑只会连环误报。
                self.path_note("app-blocker", block.kind,
                               date=target, detail=block.detail)
                self.logger.warning("[%s] 明细页被拦截（%s）：%s（%s）",
                                    self.name, target, block.kind,
                                    block.detail)
                return got, True
            out = self._to_prices(rows, from_city, to_city, target)
            if not out:
                self.logger.info("[%s] 明细页没解析出带价航班：%s",
                                 self.name, target)
                # 记账走基类单源：解析不到价是「没采到」，不是「这天没票」。
                self.note_date(target, out, "no-priced-rows")
                continue
            self.note_date(target, out, "ok",
                           url=f"android://{_APP_PKG}?view=list")
            got.extend(out)
        return got, False

    def _one_date_detail(self, dev, from_city: str, to_city: str,
                         target: str, first: bool):
        """选日期 → 点查询 → 返回该日列表页的原始行。

        第一个日期时弹层可能还开着（主流程 keep_open=True）；之后的日期
        在列表页上，要先回首页才能再开日历。

        返回 (rows, blocked)。blocked 非空表示撞上广告/验证码/人脸/登录墙：
        调用方必须按拦截记账，绝不能当成「这天没票」——那会把「需要人操作」
        伪装成「没有航班」，是最容易误导用户的一类。
        """
        try:
            from .app_zhixing_nav import _pick_date, find, nodes
        except Exception:
            return [], None
        try:
            if not first:
                self._park_at_home(dev)
                xml0 = self._try_long_calendar(dev, keep_open=True)
                if not xml0:
                    return [], None
                xml0, block0 = self._clear_blockers(dev, xml0)
                if block0.blocking:
                    return [], block0
            xml = dev.dump() or ""
            xml, block = self._clear_blockers(dev, xml)
            if block.blocking:
                return [], block
            if "Search_Calendar_Dialog" not in xml:
                return [], None
            ok, detail = _pick_date(dev, nodes(xml), target,
                                    log=self.logger, xml=xml)
            if not ok:
                self.logger.info("[%s] 明细前置选日期失败：%s",
                                 self.name, detail)
                return [], None
            # 只点查询，不重跑整段导航（重跑会重启 App，白花 30s+）
            xml = dev.dump() or ""
            btn = find(nodes(xml), "机票查询")
            if btn is None:
                return [], None
            if not dev.tap(btn.cx, btn.cy):
                return [], None
            deadline = time.time() + 30
            while time.time() < deadline:
                xml = dev.dump() or ""
                if not xml:
                    time.sleep(2)
                    continue
                xml, block = self._clear_blockers(dev, xml)
                if block.blocking:
                    return [], block
                if detect_state(xml) == "ok":
                    rows = parse_flight_rows(xml)
                    if any(r.get("price") for r in rows):
                        return rows, None
                time.sleep(2)
            return [], None
        except Exception as e:
            self.logger.info("[%s] 明细路径异常：%s", self.name,
                             type(e).__name__)
            return [], None

    def _to_prices(self, rows: List[dict], from_city: str, to_city: str,
                   date: str) -> List[FlightPrice]:
        """该日期全部航班 → **一条** FlightPrice（extra 携带全部航班）。

        「一渠道一日期一行」是既有契约：webui 列表池按
        (platform, 航线, 日期, real/cal) 去重，同日期多行会被整批丢掉；
        浏览器五渠道也都是「一行 + extra 数组」。App 曾写成「每班一行
        + extra 元信息对象」，两边都对不上——库里有数据，页面一条不见。
        """
        flights, best = [], None
        for r in rows or []:
            price = r.get("price")
            if price is None:
                continue
            flight_no = r.get("flight_no", "")
            airline = r.get("airline", "")
            trans = r.get("trans_city", "")
            dep, arr = r.get("depart_time", ""), r.get("arrive_time", "")
            # 国际页没有航班号：code 留空、name 用航司名（下游按 depTime+
            # arrTime 判真实班次，不要求 code；编一个假航班号才是缺陷）。
            item = {"price": float(price), "code": flight_no,
                    "name": airline or flight_no, "depDate": date,
                    "depTime": dep, "arrTime": arr}
            # 经停城市：中转卡片不带航班号，若不标明经停，下游会把
            # 「青岛 20h35m」的中转当成直飞塞进直飞最优池（r682 实测）。
            if trans:
                item["transCity"] = trans
            flights.append(item)
            # 行头价取**最低直飞**；只有全部是中转时才退回中转最低价。
            # 行头是列表池判断「这渠道当天什么价」的那一格，拿中转低价
            # 顶上去会让「直飞多少」的读数凭空变便宜（r682 真机：青岛
            # 中转 ￥450 顶掉了直飞 ￥552）。
            if trans:
                if best is None or (best.get("transCity")
                                    and price < best["price"]):
                    best = item
            elif best is None or best.get("transCity") or price < best["price"]:
                best = item
        if not flights:
            return []
        return [FlightPrice(
            platform=self.name,
            from_city=from_city, to_city=to_city,
            depart_date=date, price=best["price"],
            flight_no=best["code"], depart_time=best["depTime"],
            arrive_time=best["arrTime"],
            extra=json.dumps(flights, ensure_ascii=False),
            prov=f"app:{_APP_PKG}:list",
        )]

    def _emit_calendar(self, xml: str, from_city: str, to_city: str,
                       dates: List[str], ms: int) -> List[FlightPrice]:
        # 页面可能是「选择日期」弹层（长窗口，跨两个月）或首页日历条
        # （短期，7–8 天）。前者优先——同样一次读页面，覆盖长得多。
        from .app_zhixing_calendar import (has_calendar_dialog, month_range,
                                           parse_date_dialog)
        dialog_rows = []
        if has_calendar_dialog(xml):
            dialog_rows = parse_date_dialog(xml)

        if dialog_rows:
            return self._emit_from_dialog(dialog_rows, from_city, to_city,
                                          dates, ms)

        rows = parse_calendar(xml)
        if not rows:
            self.path_note("日历", "parse_error",
                           detail="日历条未解析出价格", ms=ms)
            return []

        wanted = set(dates or [])
        anchor = (dates[0] if dates else "")
        out: List[FlightPrice] = []
        masked_days = 0
        for row in rows:
            ymd = _md_to_ymd(row["date"], anchor)
            if not ymd:
                continue
            if wanted and ymd not in wanted:
                continue
            price = row.get("price")
            if price is None:
                masked_days += 1
                continue
            out.append(FlightPrice(
                platform=self.name,
                from_city=from_city, to_city=to_city,
                depart_date=ymd, price=float(price),
                extra=_cal_extra(price, ymd),
                prov=f"app:{_APP_PKG}:calendar",
            ))

        detail = f"日历 {len(out)} 天"
        if masked_days:
            detail += f" · {masked_days} 天无价"
        # 「目标日期在日历窗口外」必须单独说明：智行日历条只覆盖首屏
        # 约 7–8 天，配置里的远期日期永远命中 0 条。若只记「日历 0 天」，
        # 读者分不清是"这几天没价"还是"这条航线压根不在窗口内"——
        # 前者是数据、后者是能力边界，处置完全不同（改配置 vs 改实现）。
        outside = 0
        if wanted and rows:
            inwin = {_md_to_ymd(r["date"], anchor) for r in rows}
            inwin.discard("")
            outside = len([d for d in wanted if d not in inwin])
        if outside:
            detail += f" · {outside} 个目标日期在日历窗口外"
            self.logger.info(
                "[%s] %d/%d 个目标日期不在智行日历窗口内（该窗口仅约 %d 天）",
                self.name, outside, len(wanted), len(rows))
        status = "calendar" if out else ("empty" if outside == 0 else "calendar")
        self.path_note("日历", status, rows=len(out),
                       date=anchor, detail=detail, ms=ms,
                       url=f"android://{_APP_PKG}")
        if not out:
            # 有日历但目标日期都没价：这是"没拿到价"，不是"无票"
            self.logger.info("[%s] 日历条命中 0 条（%s）", self.name, detail)
        return out

    def _boot_wait(self) -> float:
        """冷启动后等待首页的时间；测试里会被压到 0。"""
        return float(self.config.get("app_boot_wait_s", 10) or 0)

    def _remember_route(self, from_city: str, to_city: str):
        """记下本轮设过的航线（仅供日志/诊断；判据始终以界面为准）。"""
        self._last_route = (from_city, to_city)

    def read_route(self, dev):
        """从首页读当前航线 (出发名, 到达名)；不在首页/读不到返回 None。

        判据是屏幕上的城市行文案（基类 `_route_unchanged` 据此比对）。
        """
        try:
            from .app_zhixing_nav import _city_row, nodes
            xml = dev.dump()
            if not xml or "机票查询" not in xml:
                return None
            ns = nodes(xml)
            cur_from = _city_row(ns, "from")
            cur_to = _city_row(ns, "to")
            if cur_from is None or cur_to is None:
                return None
            return (cur_from.text, cur_to.text)
        except Exception:
            return None

    def is_login_wall(self, xml: str) -> bool:
        """智行的登录墙是「立即登录」这类文案，不是手机号表单。"""
        if super().is_login_wall(xml):
            return True
        try:
            from .app_zhixing_parse import detect_state
            return detect_state(xml) == "login"
        except Exception:
            return False

    def _set_route(self, dev, from_city: str, to_city: str,
                   dates: List[str]):
        """按配置设置 App 内的航线与日期。"""
        if self._skip_route:
            return True, "skipped"
        try:
            from .app_zhixing_nav import set_flight_route
        except Exception as e:
            return False, f"导航模块不可用：{type(e).__name__}"

        target_date = dates[0] if dates else ""
        # 国际/国内是 App 内两个不同表单（国际档多返程日期+舱位行）；
        # 判据与浏览器渠道同源：任一端在大陆码集外即国际。
        try:
            from core.intl import is_intl_route
            intl = bool(is_intl_route(from_city, to_city))
        except Exception:
            intl = False
        # 停在首页：下一步要读「选择日期」长窗口日历，进列表页就没入口了
        return set_flight_route(dev, self._city_name(from_city),
                                self._city_name(to_city),
                                target_date, log=self.logger,
                                stop_before_search=True, intl=intl)
