"""低价提醒 + 推送（带去抖）"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from .models import FlightPrice, Route


class Alerter:
    PLATFORM_CN = {
        "qunar": "去哪儿", "fliggy": "飞猪", "ctrip": "携程",
        "tongcheng": "同程", "tuniu": "途牛",
    }

    def __init__(self, logger: logging.Logger, notifier=None, storage=None,
                 push_drop_min: float = 30, push_rise_min: float = 50,
                 digest: bool = False, at_mobile: str = "",
                 storm_repeat: int = 3, user: str = "",
                 platforms: list = None, urgent_notifier=None,
                 quiet_start: str = "", quiet_end: str = "",
                 base_url: str = ""):
        """
        notifier:        推送器（None 表示不推送）
        storage:         用于读写 alert_state（去抖）
        push_drop_min:   触发"再次推送"的最小降幅(￥)
        push_rise_min:   触发"再次推送"的最小涨幅(￥)
        digest:          每轮推送直飞/中转 TOP3 行情报告（达标时警报式高亮）
        at_mobile:       达标强提醒时 @ 的手机号（钉钉 atMobiles）
        storm_repeat:    达标风暴推送条数（1=关闭；默认 3=即时+1min+3min）
        user:            多租户用户名（去抖状态按用户隔离）
        platforms:       该用户启用的平台（用于"本轮无数据渠道"提示）
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
        self.storm_repeat = max(1, int(storm_repeat))
        self.user = (user or "").strip()
        self.platforms = list(platforms) if platforms else list(self.PLATFORM_CN)
        self.quiet_start = (quiet_start or "").strip()
        self.quiet_end = (quiet_end or "").strip()
        # 本机控制台基址（http://127.0.0.1:端口）——Windows 弹窗点击直达单条详情页
        self.base_url = (base_url or "").rstrip("/")
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
        for route, prices in routes_prices:
            if not prices:
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
            self._push_digest_multi(built)
            return
        # 非 digest 模式：逐航线单条去抖告警
        for route, sections in built:
            for s in sections:
                if route.alert_direct > 0 and s["best_direct"] is not None:
                    self._category_alert(route, s["date"], s["best_direct"],
                                         "direct", route.alert_direct,
                                         s["n_direct"], s["src_platform"])
                if route.alert_transfer > 0 and s["best_transfer"] is not None:
                    self._category_alert(route, s["date"], s["best_transfer"],
                                         "transfer", route.alert_transfer,
                                         s["n_transfer_ok"], s["src_platform"])

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
        for p in prices:
            cur = best_by_date.get(p.depart_date)
            if cur is None or p.price < cur.price:
                best_by_date[p.depart_date] = p

        for date, bp in sorted(best_by_date.items()):
            route_key = f"{self.user}|{route.from_code}-{route.to_code}-{date}"

            if bp.price > route.alert_threshold:
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
                                     s["n_direct"], s["src_platform"])
            if route.alert_transfer > 0 and s["best_transfer"] is not None:
                self._category_alert(route, s["date"], s["best_transfer"],
                                     "transfer", route.alert_transfer,
                                     s["n_transfer_ok"], s["src_platform"])

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
                    from core.flightnorm import normalize as _fnorm
                    for f in obj:
                        if isinstance(f, dict) and "price" in f:
                            g = dict(f)
                            g["_platform"] = p.platform
                            _fnorm(g, date)
                            flights.append(g)
                    src_platform = p.platform
            if not flights:
                continue

            # 近期明细补位：当轮缺明细的平台（如去哪儿被限流回退 httpx）
            # 用其近 6 小时最后成功明细补——仅用于展示，达标判定只认当轮
            have = {f.get("_platform") for f in flights}
            try:
                from report import recent_platform_flights
                db = self.storage.db_path if self.storage else "data/prices.db"
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
                            flights.append(g)
            except Exception as e:
                self.logger.warning("近期明细补位失败: %s", e)

            # 跨源时刻仲裁：同航班号时以飞猪（结构化 JSON，可靠）时刻为准，
            # 纠正去哪儿碎片解析中残余的邻串时刻污染
            ref = {}
            for f in flights:
                if f.get("_platform") == "fliggy" and f.get("code"):
                    ref.setdefault(f["code"], f)
            for f in flights:
                if f.get("_platform") == "qunar" and f.get("code"):
                    for piece in f["code"].split("/"):
                        r = ref.get(piece)
                        if r and r["depTime"] and r["depTime"] != f["depTime"]:
                            f["depTime"] = r["depTime"]
                            f["arrTime"] = r["arrTime"] or f["arrTime"]
                            break

            # 价格统一取整（各渠道 float 携带 .0 尾巴，污染所有显示位）
            for f in flights:
                try:
                    f["price"] = round(float(f["price"]))
                except (TypeError, ValueError):
                    pass

            # 出发时段约束（如返程"10-4 只看晚间"）：窗口外班次整体剔除，
            # 明细/达标/速览/比价全链路一致
            dmin = (route.dep_time_min or "").strip()
            dmax = (route.dep_time_max or "").strip()
            if dmin or dmax:
                flights = [f for f in flights if self._dep_in_window(
                    f.get("depTime", ""), dmin, dmax)]

            directs = [f for f in flights if not f.get("transCity")]
            transfers = [f for f in flights if f.get("transCity")]
            ok_transfers = [f for f in transfers
                            if self._arrival_ok(f, route.transfer_arrival_max)]
            # 达标判定只认当轮实时数据（_stale_h 为近期补位，仅作展示）
            fresh_d = [f for f in directs if not f.get("_stale_h")]
            fresh_t = [f for f in ok_transfers if not f.get("_stale_h")]
            best_direct = min(fresh_d, key=lambda f: f["price"]) if fresh_d else None
            best_transfer = (min(fresh_t, key=lambda f: f["price"])
                             if fresh_t else None)

            if best_direct is not None:
                self.logger.info(
                    "[直飞] %s->%s %s 最低 ￥%d（%s %s-%s%s）",
                    route.from_name, route.to_name, date, best_direct["price"],
                    best_direct["name"], best_direct["depTime"],
                    best_direct["arrTime"],
                    f" {best_direct['crossDayDesc']}" if best_direct["crossDayDesc"] else "")
            if transfers:
                if best_transfer is not None:
                    # 注意措辞：这是「当前最低中转价」不是「已达标」——
                    # 是否达标由 _collect_hits 对阈值另行判定（曾误导用户
                    # 以为达标了没弹窗）
                    self.logger.info(
                        "[中转最低] %s->%s %s 最低 ￥%d（%s 经%s %s-%s%s）",
                        route.from_name, route.to_name, date,
                        best_transfer["price"], best_transfer["name"],
                        best_transfer["transCity"], best_transfer["depTime"],
                        best_transfer["arrTime"],
                        f" {best_transfer['crossDayDesc']}"
                        if best_transfer["crossDayDesc"] else "")
                else:
                    cheapest = min(transfers, key=lambda f: f["price"])
                    self.logger.info(
                        "[中转] %s->%s %s 无满足到达约束的班次；"
                        "无视约束最低 ￥%d（%s %s）",
                        route.from_name, route.to_name, date, cheapest["price"],
                        cheapest["name"], cheapest["crossDayDesc"] or "-")

            # 各平台全线最低（含中转，不筛）
            platform_mins = {}
            for p in prices:
                if p.depart_date != date:
                    continue
                cur = platform_mins.get(p.platform)
                if cur is None or p.price < cur:
                    platform_mins[p.platform] = p.price

            # 各渠道各自最低 3 条（与主 TOP3 同一套筛选：
            # 直飞全量 + 中转仅留满足到达约束的）
            by_plat = {}
            for f in directs + ok_transfers:
                by_plat.setdefault(f.get("_platform", "?"), []).append(f)
            plat_top3 = {p: sorted(v, key=lambda x: x["price"])[:3]
                         for p, v in by_plat.items()}

            sections.append({
                "date": date,
                "top_direct": sorted(directs, key=lambda f: f["price"])[:3],
                "top_transfer": sorted(ok_transfers, key=lambda f: f["price"])[:3],
                "best_direct": best_direct,
                "best_transfer": best_transfer,
                "n_direct": len(directs),
                "n_transfer_ok": len(ok_transfers),
                "platform_mins": platform_mins,
                "plat_top3": plat_top3,
                "src_platform": src_platform,
                "pool": fresh_d + fresh_t,
                "seen_plats": sorted({p.platform for p in prices
                                      if p.depart_date == date}),
            })
        return sections

    # ---------- 聚合推送（一轮一消息） ----------
    @staticmethod
    def _route_short(route) -> str:
        return f"{route.from_name[:1]}→{route.to_name[:1]}"

    @staticmethod
    def _date_short(date: str) -> str:
        return date[5:].replace("-", "/") if date else ""

    def _deltas(self, route, date: str) -> dict:
        """较上轮涨跌：走势序列倒数两轮之差（直飞/达标中转）。"""
        try:
            if self.storage:
                from report import _rounds
                hist = _rounds(self.storage.db_path, route.from_code,
                               route.to_code, date,
                               route.transfer_arrival_max)
                out = {}
                for tag, idx in (("direct", 1), ("transfer", 2)):
                    vs = [r[idx] for r in hist if r[idx]]
                    if len(vs) >= 2:
                        out[tag] = vs[-1] - vs[-2]
                return out
        except Exception:
            pass
        return {}

    @staticmethod
    def _delta_txt(deltas: dict, tag: str) -> str:
        dv = deltas.get(tag)
        if not dv:      # 无变化（0）或无上轮数据时不显示
            return ""
        arrow = "↓" if dv <= 0 else "↑"
        return f" ｜ 较上轮 {arrow}￥{abs(dv):.0f}"

    def _trend_line(self, route, date: str) -> str:
        """近 7 天趋势小结（较窗口首值）：「直飞 ↓8% ｜ 中转 ↓3%」；
        无 storage / 数据不足 / 异常 → 空串（文案静默省略，不炸推送）。"""
        if not self.storage:
            return ""
        try:
            from report import _rounds
            hist = _rounds(self.storage.db_path, route.from_code,
                           route.to_code, date, route.transfer_arrival_max,
                           hours=168)
        except Exception:
            return ""
        bits = []
        for idx, label in ((1, "直飞"), (2, "中转")):
            vs = [r[idx] for r in hist if r[idx]]
            if len(vs) >= 2 and vs[0]:
                pct = (vs[-1] / vs[0] - 1) * 100
                arrow = "↓" if pct < -0.5 else ("↑" if pct > 0.5 else "→")
                bits.append(f"{label} {arrow}{abs(pct):.0f}%")
        return " ｜ ".join(bits)

    def _suggest_line(self, route, s) -> str:
        """一句话操作建议：破线出手 / 近线蹲守（≤10%）/ 远线观望；
        直飞中转取更接近线的那条说。"""
        cands = []
        bd, bt = s.get("best_direct"), s.get("best_transfer")
        if route.alert_direct > 0 and bd:
            cands.append((bd["price"], route.alert_direct, "直飞"))
        if route.alert_transfer > 0 and bt:
            cands.append((bt["price"], route.alert_transfer, "中转"))
        if not cands:
            return ""
        price, th, label = min(cands)
        if price <= th:
            return f"✅ {label}已破线 ￥{th - price:.0f}，建议立即出手"
        gap = (price - th) / th
        if gap <= 0.10:
            return f"⏳ {label}距线仅 {gap * 100:.0f}%，可蹲守提醒"
        return f"🧘 {label}高于线 {gap * 100:.0f}%，继续观望"

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

    def _archive_notify(self, title: str, desp: str) -> str:
        """达标详情存档 → /notify/{nid} 直达链接（无 base_url 返回空）。

        Windows 弹窗与钉钉「完整详情」共用同一份单条详情页——
        轻页非控制台，点击即看全量信息。只保留最近 20 份。"""
        if not self.base_url:
            return ""
        try:
            import json as _json
            import os as _os
            nid = "N" + datetime.now().strftime("%Y%m%d%H%M%S")
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
                     launch: str = ""):
        """达标强提醒分发：阿里云电话/短信用极简精确文案（语音播报友好），
        Windows 右下角弹窗带 launch 直达单条详情页，ntfy 等用完整消息。
        仅达标调用——未达标轮次不会进来。免打扰时段电话/短信抑制。"""
        if not hits:
            return
        quiet = self._in_quiet()
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
                    ay_title = (f"机票达标 {r0.from_name}到{r0.to_name}"
                                f" {s0['date'][5:].replace('-', '月')}日"
                                f" {k0}价{f0['price']}")
                    ay_msg = (f"{f0.get('name', '')} {f0['depTime']}起飞"
                              f" 到{f0['arrTime']}"
                              f"{' 经' + f0['transCity'] if f0.get('transCity') else ''}"
                              f" 已低于{th0:.0f}元 立即下单")
                    un.send(ay_title, ay_msg)
                elif isinstance(un, WindowsToastNotifier):
                    un.send(title, desp, launch=launch)
                else:
                    un.send(title, desp)
            except Exception as e:
                self.logger.warning("[强提醒] 发送异常: %s", e)

    def _collect_hits(self, rs_list: list):
        """达标聚合（route, s, kind, f, th）——纯函数，无副作用。"""
        hits = []
        for route, sections in rs_list:
            for s in sections:
                if (route.alert_direct > 0 and s["best_direct"] is not None
                        and s["best_direct"]["price"] <= route.alert_direct):
                    hits.append((route, s, "直飞", s["best_direct"],
                                 route.alert_direct))
                if (route.alert_transfer > 0 and s["best_transfer"] is not None
                        and s["best_transfer"]["price"] <= route.alert_transfer):
                    hits.append((route, s, "中转", s["best_transfer"],
                                 route.alert_transfer))
        return hits

    def _digest_payload(self, rs_list: list, fresh: bool = True,
                        with_tables: bool = True) -> dict:
        """纯构建聚合推送文案：不发送、不拨号、不写去抖状态。

        fresh=False → 持续达标标题（🔔 而非 🚨）；
        with_tables=False → 跳过明细总表图床上传（控制台推送预览器用，
        本地渲染近似效果，不打外部网络）。"""
        hits = self._collect_hits(rs_list)
        summary = " · ".join(
            f"{self._route_short(r)} {self._date_short(s['date'])}"
            for r, secs in rs_list for s in secs)

        if hits:
            r0, s0, k0, f0, _ = hits[0]
            prefix = "🚨 达标！" if fresh else "🔔 持续达标"
            title = (f"{prefix}{self._route_short(r0)} "
                     f"{self._date_short(s0['date'])} {k0}￥{f0['price']}｜{summary}")
        else:
            # 未达标锚点：全线最接近阈值的一项（扫读一眼知道还差多少）
            anchor = None
            for route, sections in rs_list:
                for s in sections:
                    for best, th, kind in (
                            (s.get("best_direct"), route.alert_direct, "直飞"),
                            (s.get("best_transfer"), route.alert_transfer, "中转")):
                        if best and th > 0:
                            gap = best["price"] - th
                            if gap > 0 and (anchor is None
                                            or gap < anchor[0]):
                                anchor = (gap, route, s, kind)
            if anchor:
                gap, r0, s0, k0 = anchor
                title = (f"❌ 全部未达标｜最近 {self._route_short(r0)} "
                         f"{self._date_short(s0['date'])} "
                         f"{k0}差￥{gap:.0f}｜{summary}")
            else:
                title = f"❌ 全部未达标｜{summary}"

        # 达标航线小节置顶（多航线时先看最该看的）
        hit_routes = {id(r) for r, _s, _k, _f, _th in hits}
        ordered = sorted(rs_list,
                         key=lambda rp: 0 if id(rp[0]) in hit_routes else 1)

        desp = ("# 🚨 已达标——可出手\n\n" if hits
                else f"# ❌ {len(rs_list)} 条航线全部未达标\n\n")
        desp += (f"> ⏱ 数据截至 {datetime.now().strftime('%m-%d %H:%M')}"
                 f" · 每轮自动刷新\n\n")

        # 各航线小节：方向+日期大标题 + KPI 行 + 仪表 + 该航线走势图
        view_url = None
        _sec_i = 0
        for route, sections in ordered:
            url = self._build_view_url(route, sections[0]["date"], "qunar")
            view_url = view_url or url
            dep_win = ""
            if (route.dep_time_min or "").strip() or (route.dep_time_max or "").strip():
                lo = (route.dep_time_min or "00:00")[:5]
                hi = (route.dep_time_max or "24:00")[:5]
                dep_win = (f"（{lo}后出发）" if not route.dep_time_max
                           else f"（{lo}–{hi}）")
            if _sec_i:
                desp += "---\n\n"
            _sec_i += 1
            desp += (f"## ✈️ {route.from_name}→{route.to_name} "
                     f"{sections[0]['date']}{dep_win}\n\n")
            deltas = self._deltas(route, sections[0]["date"])
            bd, bt = sections[0]["best_direct"], sections[0]["best_transfer"]

            def _kpi_block(label, best, th, tag):
                """钉钉手机窄屏排版：三行制——价格行/参数行/仪表行各一行，
                每行不超屏宽（长单行在窄屏折行后仪表条与数值错位）。"""
                if best is None:
                    return ""
                d = self._delta_txt(deltas, tag)
                if th > 0:
                    diff = best["price"] - th
                    pct = (best["price"] / th - 1) * 100
                    hit_mark = "🎯 " if best["price"] <= th else ""
                    head = f"[**{hit_mark}{label} ￥{best['price']:.0f}**]({url})"
                    para = f"线 {th:.0f} ｜ 差 {diff:.0f} ({pct:.0f}%){d}"
                    # 钉钉 PC 端不认单 \n（手机端认），段落级 \n\n 两端都换行；
                    # 进度条必须独立成段，否则 PC 上与参数行粘连、随文本折行
                    return (f"{head}\n\n{para}\n\n"
                            f"{self._gauge(best['price'], th)}\n\n")
                return (f"[**{label} ￥{best['price']:.0f}**]({url})"
                        f"（未设线）{d}\n\n")

            desp += _kpi_block("直飞", bd, route.alert_direct, "direct")
            desp += _kpi_block("中转", bt, route.alert_transfer, "transfer")
            tl = self._trend_line(route, sections[0]["date"])
            sg = self._suggest_line(route, sections[0])
            if tl or sg:
                parts = []
                if tl:
                    parts.append("📉 近7天 " + tl)
                if sg:
                    parts.append("💡 " + sg)
                desp += "> " + "\n> ".join(parts) + "\n\n"
            for s in sections:
                cu = (self.round_charts or {}).get(
                    (route.from_code, route.to_code, s["date"]))
                if cu:
                    desp += f"![走势]({cu})\n\n"
        # 进度条图例：聚合版曾缺失，用户看不懂 🟦 含义
        desp += "> 🟦 进度条 = 距达标幅度，格越少越接近，清零即触发 🚨\n\n"

        # 达标明细（任一命中即高亮）
        for route, s, kind, f, th in hits:
            plat = self.PLATFORM_CN.get(f.get("_platform", ""), "")
            desp += (f"> 🔥 **{kind} ￥{f['price']} {f['name']} "
                     f"{f['depTime']}→{f['arrTime']}"
                     f"{'（' + f['crossDayDesc'] + '达）' if f.get('crossDayDesc') else '当日达'}"
                     f"（{self._route_short(route)} {self._date_short(s['date'])}"
                     f"·{plat}）低于线 ￥{th:.0f}**\n\n")

        # 明细总表（所有航线合并一张图）——预览模式跳过图床上传
        if with_tables:
            desp += self._flights_table_md_multi(rs_list)

        # 比价（每航线一组，标题带航线归属；同小节同序——达标航线在前）
        for route, sections in ordered:
            cc = self._cross_compare(
                sections,
                label=f"{self._route_short(route)} "
                      f"{self._date_short(sections[0]['date'])}")
            desp += cc

        # 无数据渠道健康行
        for route, sections in rs_list:
            for s in sections:
                missing = [p for p in self.platforms
                           if p not in (s.get("seen_plats") or [])]
                if missing:
                    desp += (f"⚠️ {self._route_short(route)} "
                             f"{self._date_short(s['date'])} 无数据："
                             + "、".join(
                                 self.PLATFORM_CN.get(p, p)
                                 + ("（维护中：官方下线旧接口）"
                                    if p == "fliggy" else "")
                                 for p in missing) + "\n\n")
        desp += (f"⏳ 更新于 {datetime.now().strftime('%H:%M')}\n\n"
                 f"[👉 去哪儿查看]({view_url})\n")

        at_mobiles = None
        if hits and self.at_mobile:
            at_mobiles = [self.at_mobile]
            desp += f"\n@{self.at_mobile} "
        return {"title": title, "desp": desp, "hits": hits,
                "at_mobiles": at_mobiles}

    def _push_digest_multi(self, rs_list: list):
        """一轮一消息：每航线一个小节（方向+日期标题，一眼可辨），
        明细合并一张总表；任一航线达标则整条消息变警报。"""
        hits = self._collect_hits(rs_list)
        # 免打扰时段：行情心跳整轮省略（达标警报链路不受限）
        if not hits and self._in_quiet():
            self.logger.info("[静默] %s–%s 免打扰时段，本轮行情推送省略"
                             "（达标警报不受限）", self.quiet_start,
                             self.quiet_end)
            return False
        fresh_hits = [h for h in hits if self._phone_should_ring(h)]
        p = self._digest_payload(rs_list, fresh=bool(fresh_hits),
                                 with_tables=True)
        title, desp, at_mobiles = p["title"], p["desp"], p["at_mobiles"]
        # 电话/强提醒不依赖钉钉成功——钉钉网关抖动时电话必须照响；
        # 但持续达标时去抖：同航线同类别 2h 内或降幅不足 ￥50 不重拨。
        # 详情页存档先行：nid 链接进钉钉文案 + Windows 弹窗 launch 共用
        if fresh_hits:
            launch = self._archive_notify(title, desp)
            if launch:
                desp += f"\n[📲 完整详情（点击直达）]({launch})\n"
            self._send_urgent(title, desp, fresh_hits, launch=launch)
        # 单次发送（send 内部已含退避重试）——不再外层加码：
        # 钉钉 -1 存在"幽灵送达"（报错但消息已入群），外层重试会造成
        # 重复消息打扰；偶发丢失由下轮心跳自然补，达标场景电话独立兜底
        sent = self.notifier.send(title, desp, at_mobiles=at_mobiles)
        if sent:
            self.logger.info("[聚合] 已推送: %s", title)
        else:
            self.logger.warning("[聚合] 本轮推送未确认（-1 幽灵送达可能已入群）")
        # 风暴与电话同去抖：仅"新达标"（首跌破或再降≥50）才 3 连推，
        # 持续达标的轮次只发主推（每 30 分钟一条 🚨 不轰炸）；
        # 免打扰时段风暴自动顺延跳过（主推已送达，不深夜轰炸）
        if sent and hits and fresh_hits and self.storm_repeat > 1:
            if self._in_quiet():
                self.logger.info("[静默] %s–%s 免打扰时段，风暴连推跳过",
                                 self.quiet_start, self.quiet_end)
            else:
                self._storm(title, desp, at_mobiles)
        return bool(hits)

    def _flights_table_md_multi(self, rs_list: list) -> str:
        """所有航线的明细合并成一张总表图（分组标题带航线缩写+日期）。"""
        try:
            from report import render_flights_table, upload_freeimage
            rows = []
            summary_bits = []
            names = []
            for route, sections in rs_list:
                short = self._route_short(route)
                names.append(f"{route.from_code}{route.to_code}")
                for s in sections:
                    dshort = self._date_short(s["date"])
                    for kind, key, th, icon in (
                            ("direct", "top_direct", route.alert_direct, "✈️ 直飞"),
                            ("transfer", "top_transfer", route.alert_transfer, "🔁 中转")):
                        fs = []
                        for f in s.get(key) or []:
                            g = dict(f)
                            ok = th > 0 and g["price"] <= th
                            if kind == "transfer":
                                ok = ok and self._arrival_ok(
                                    g, route.transfer_arrival_max)
                            g["_qual"] = ok
                            fs.append(g)
                        rows.append((kind, fs, f"{icon}最优 · {short} {dshort}"))
                    cands = self._fp_cands(sections, top_n=2)
                    if cands:
                        comp = []
                        for save, fs2 in cands:
                            best = fs2[0]
                            chain = " → ".join(
                                f"{self.PLATFORM_CN.get(f.get('_platform', ''), '?')}"
                                f"￥{f['price']:.0f}" for f in fs2)
                            label = best.get("name") or best.get("code", "同班")
                            comp.append(f"⚖️ {label} {best['depTime']}→{best['arrTime']}"
                                        f"：{chain}（可省 ￥{save:.0f}）")
                        rows.append(("compare", comp, None))
                    bd = s.get("best_direct")
                    if bd:
                        summary_bits.append(
                            f"{short} {dshort} 直飞￥{bd['price']:.0f}")
            title = " ｜ ".join(
                f"{r.from_name}→{r.to_name}" for r, _ in rs_list[:2]) \
                + (f" 等{len(rs_list)}航线" if len(rs_list) > 2 else "")
            out_png = f"data/flights_table_{''.join(names[:2])}.png"
            render_flights_table(
                rows, title, out_png, summary=" ｜ ".join(summary_bits[:4]))
            url = upload_freeimage(out_png, self.logger)
            if url:
                return f"### 📋 最优明细总表（价格彩色=达标）\n\n![明细总表]({url})\n\n"
            self.logger.warning("[总表] 上传失败")
        except Exception as e:
            self.logger.warning("[总表] 生成失败: %s", e)
        return ""

    # ---------- 行情报告（digest） ----------
    @classmethod
    def _fmt_flight_line(cls, f: dict, idx: int = None) -> str:
        cross = f.get("crossDayDesc", "")
        arrive = f"{f['arrTime']}（{cross}达）" if cross else f"{f['arrTime']} 当日达"
        trans = f" 经{f['transCity']}（全程{f.get('totalDuration') or '?'}）" \
            if f.get("transCity") else ""
        plat = cls.PLATFORM_CN.get(f.get("_platform", ""), f.get("_platform", ""))
        if f.get("_stale_h"):
            plat += f"·{f['_stale_h']:.0f}h前"
        no = f"{idx}. " if idx else "- "
        return (f"{no}**￥{f['price']}** {f['name']} {f['depTime']}→{arrive}"
                f"{trans}（{plat}）")

    def _push_digest(self, route: Route, sections: list):
        first = sections[0]
        hits = []
        for s in sections:
            if (route.alert_direct > 0 and s["best_direct"] is not None
                    and s["best_direct"]["price"] <= route.alert_direct):
                hits.append(("直飞", s["best_direct"], route.alert_direct))
            if (route.alert_transfer > 0 and s["best_transfer"] is not None
                    and s["best_transfer"]["price"] <= route.alert_transfer):
                hits.append(("中转", s["best_transfer"], route.alert_transfer))

        route_txt = f"{route.from_name}→{route.to_name}"
        dep_win = ""
        if (route.dep_time_min or "").strip() or (route.dep_time_max or "").strip():
            lo = route.dep_time_min or "00:00"
            hi = route.dep_time_max or "24:00"
            # 窄屏短格式：完整区间进日志级说明，标题用缩写
            dep_win = (f"（{lo[:5]}后出发）" if not route.dep_time_max
                       else f"（{lo[:5]}–{hi[:5]}）")
        # 详情链接固定走去哪儿触屏版（浏览器直开，无需 App/登录）
        view_url = self._build_view_url(route, first["date"], "qunar")
        chart_url = (self.round_charts or {}).get(
            (route.from_code, route.to_code, first["date"]))
        chart_md = f"![走势]({chart_url})\n\n" if chart_url else ""

        if not hits:
            # 主信息置顶：未达标状态 + 距达标仪表条；TOP3 为次级明细
            bd, bt = first["best_direct"], first["best_transfer"]
            deltas = self._deltas(route, first["date"])

            def _delta_txt(tag):
                return self._delta_txt(deltas, tag)

            title = (f"❌ 未达标｜{route_txt} {first['date']}{dep_win}｜"
                     f"直飞￥{bd['price'] if bd else '-'}·"
                     f"达标中转￥{bt['price'] if bt else '-'}")
            desp = "# ❌ 本轮未达标\n\n"
            if route.alert_direct > 0 and bd:
                desp += (f"[**直飞 ￥{bd['price']:.0f}**]({view_url})"
                         f" ｜ 线 ￥{route.alert_direct:.0f}"
                         f" ｜ 差 ￥{bd['price'] - route.alert_direct:.0f}"
                         f"（{(bd['price'] / route.alert_direct - 1) * 100:.0f}%）"
                         f"{_delta_txt('direct')}\n\n"
                         f"{self._gauge(bd['price'], route.alert_direct)}\n\n")
            if route.alert_transfer > 0 and bt:
                desp += (f"[**中转 ￥{bt['price']:.0f}**]({view_url})"
                         f" ｜ 线 ￥{route.alert_transfer:.0f}"
                         f" ｜ 差 ￥{bt['price'] - route.alert_transfer:.0f}"
                         f"（{(bt['price'] / route.alert_transfer - 1) * 100:.0f}%）"
                         f"{_delta_txt('transfer')}\n\n"
                         f"{self._gauge(bt['price'], route.alert_transfer)}\n\n")
            desp += "> 🟦 越少越接近达标，清零即触发 🚨\n\n"
            desp += chart_md
            table_md = self._flights_table_md(route, sections)
            if table_md:
                desp += table_md
                desp += self._cross_compare(sections)
                desp += self._channel_overview(sections)
            else:
                desp += self._top3_blocks(route, sections)
            desp += (f"⏳ 更新于 {datetime.now().strftime('%H:%M')}\n\n"
                     f"[👉 去哪儿查看]({view_url})\n")
            if self.notifier.send(title, desp):
                self.logger.info("[心跳] 已推送运行状态: %s", title)
            return

        kind, f, th = hits[0]
        title = (f"🚨 已达标！{route_txt} {first['date']}{dep_win}｜"
                 f"{kind}￥{f['price']}≤{th:.0f}")

        desp = "# 🚨 已达标——可出手\n\n"
        for kind, f, th in hits:
            plat = self.PLATFORM_CN.get(f.get("_platform", ""), "")
            desp += (f"> 🔥 **{kind} ￥{f['price']} {f['name']} "
                     f"{f['depTime']}→{f['arrTime']}"
                     f"{'（' + f['crossDayDesc'] + '达）' if f.get('crossDayDesc') else '当日达'}"
                     f"（{plat}）—— 低于达标线 ￥{th:.0f}**\n\n")
        desp += chart_md
        table_md = self._flights_table_md(route, sections)
        if table_md:
            desp += table_md
            desp += self._cross_compare(sections)
            desp += self._channel_overview(sections)
        else:
            desp += self._top3_blocks(route, sections)
        desp += (f"⏳ 更新于 {datetime.now().strftime('%H:%M')}\n\n"
                 f"[👉 去哪儿查看]({view_url})\n")
        # 达标强提醒：@指定人（正文含 @手机号 才会高亮）
        at_mobiles = None
        if self.at_mobile:
            at_mobiles = [self.at_mobile]
            desp += f"\n@{self.at_mobile} "
        self._send_urgent(title, desp,
                          [(route, sections[0], kind, f, th)
                           for kind, f, th in hits])   # 电话不依赖钉钉成功
        if self.notifier.send(title, desp, at_mobiles=at_mobiles):
            self.logger.info("[报告] 已推送达标报告: %s", title)
            # 达标风暴：深夜免打扰场景下的多次强提醒（+1min/+3min 再推两条）
            if self.storm_repeat > 1:
                self._storm(title, desp, at_mobiles)

    def _storm(self, title: str, desp: str, at_mobiles):
        import threading
        import time as _time
        for i, delay in enumerate((60, 180)[: max(0, self.storm_repeat - 1)], 2):
            def _push(d=delay, n=i):
                _time.sleep(d)
                try:
                    ok = self.notifier.send(f"📞达标提醒 {n}/{self.storm_repeat} {title}",
                                            desp, at_mobiles=at_mobiles)
                    self.logger.info("[风暴] 第 %d 条提醒 %s", n, "已推" if ok else "失败")
                except Exception as e:
                    self.logger.warning("[风暴] 推送异常: %s", e)
            threading.Thread(target=_push, daemon=True).start()

    def _top3_blocks(self, route: Route, sections: list) -> str:
        """直飞/达标中转 TOP3 明细（次级板块，状态头之后）。"""
        desp = ""
        for s in sections:
            d_th = (f"（达标线 ￥{route.alert_direct:.0f}）"
                    if route.alert_direct > 0 else "")
            desp += f"### ✈️ 直飞最优3班{d_th}\n\n"
            if s["top_direct"]:
                for i, fl in enumerate(s["top_direct"], 1):
                    fire = "🔥 " if (route.alert_direct > 0
                                     and fl["price"] <= route.alert_direct) else ""
                    desp += f"{fire}{self._fmt_flight_line(fl, i)}\n"
            else:
                desp += "- 暂无数据\n"
            t_th = (f"（达标线 ￥{route.alert_transfer:.0f}）"
                    if route.alert_transfer > 0 else "")
            desp += (f"\n### 🔁 中转最优3班·仅当日或次日"
                     f"{route.transfer_arrival_max}前到达{t_th}\n\n")
            if s["top_transfer"]:
                for i, fl in enumerate(s["top_transfer"], 1):
                    fire = "🔥 " if (route.alert_transfer > 0
                                     and fl["price"] <= route.alert_transfer) else ""
                    desp += f"{fire}{self._fmt_flight_line(fl, i)}\n"
            else:
                desp += "- 暂无满足到达约束的中转\n"
            desp += "\n"
        desp += self._cross_compare(sections)
        desp += self._channel_overview(sections)
        return desp

    @classmethod
    def _fp_cands(cls, sections: list, top_n: int = 4) -> list:
        """同班跨渠道分组（出发+到达+中转+跨天指纹，各渠道取最低价），
        返回 [(最大价差, [按价升序的各渠道航班])] 按可省降序。"""
        for s in sections:
            groups = {}
            for f in s.get("pool") or []:
                if not f.get("depTime") or not f.get("arrTime"):
                    continue
                key = (f["depTime"], f["arrTime"],
                       f.get("transCity", ""), f.get("crossDayDesc", ""))
                byp = groups.setdefault(key, {})
                cur = byp.get(f.get("_platform"))
                if cur is None or f["price"] < cur["price"]:
                    byp[f.get("_platform")] = f
            cands = []
            for byp in groups.values():
                if len(byp) < 2:
                    continue
                fs = sorted(byp.values(), key=lambda x: x["price"])
                cands.append((fs[-1]["price"] - fs[0]["price"], fs))
            cands.sort(key=lambda x: -x[0])
            return cands[:top_n]
        return []

    @classmethod
    def _cross_compare(cls, sections: list, top_n: int = 4,
                       label: str = "") -> str:
        """同班跨渠道比价：同一航班（出发+到达+中转指纹）在各渠道的最低价并排，
        按"最大可省"排序——交叉比价的意义：同班机买贵了多少一目了然。
        label：多航线时标注归属（如「上→乌 09/25」）。"""
        cands = cls._fp_cands(sections, top_n)
        if not cands:
            return ""
        desp = (f"### ⚖️ 同班比价{(' · ' + label) if label else ''}"
                f"（同机不同价）\n\n")
        for save, fs in cands:
            best = fs[0]
            # 超过 3 家只展示最低/最高两端：U+2026「…」在钉钉渲染成。。。；
            # 中间渠道价在明细总表图里有完整链，不丢信息
            show = fs if len(fs) <= 3 else [fs[0], fs[-1]]
            parts = [f"{cls.PLATFORM_CN.get(f.get('_platform', ''), '?')}"
                     f"{f['price']:.0f}" for f in show]
            chain = "→".join(parts)
            label = best.get("name") or best.get("code", "同班")
            # 单 bullet 单行：PC 端不认 \n 的两级缩进续行会粘连错位，
            # 超长自然按文本折行（无 emoji 块，折行无害）
            desp += (f"- **{label}** {best['depTime']}→{best['arrTime']}"
                    f"{' 经' + best['transCity'] if best.get('transCity') else ''}"
                    f"：{chain}（省 **{save:.0f}**）\n")
        return desp + "\n"

    def _channel_overview(self, sections: list) -> str:
        """各渠道速览：每渠道只列最低 1 条（一眼可读——该渠道现在多少钱；
        更全的明细已在上方表格图 TOP5/比价里，速览不再堆 3 条长行）。"""
        desp = "### 📋 各渠道最低（符合到达条件）\n\n"
        for s in sections:
            plats = set(s.get("plat_top3") or {}) | set(s.get("platform_mins") or {})
            if not plats:
                continue
            for p in sorted(plats, key=lambda x: s["platform_mins"].get(x, 9e9)):
                cn = self.PLATFORM_CN.get(p, p)
                tops = (s.get("plat_top3") or {}).get(p)
                if tops:
                    best = min(tops, key=lambda f: f.get("price", 9e9))
                    desp += f"- **{cn}** 最低 {self._fmt_brief(best)}\n"
                else:
                    v = s["platform_mins"].get(p)
                    if v is not None:
                        desp += (f"- **{cn}** 最低 **￥{v:.0f}**"
                                 f"（全线价，该渠道无明细未筛）\n")
            desp += "\n"
        for s in sections:
            missing = [p for p in self.platforms
                       if p not in (s.get("seen_plats") or [])]
            if missing:
                desp += ("⚠️ 本轮无数据渠道：" + "、".join(
                    self.PLATFORM_CN.get(p, p) for p in missing) + "\n")
                if "ctrip" in missing:
                    desp += ("（携程需本机登录态，持续无数据时请运行 "
                             "`--login ctrip` 重新登录）\n")
                desp += "\n"
        return desp

    @staticmethod
    def _gauge(price: float, threshold: float, bars: int = 5) -> str:
        """距达标进度：🟦 数量 = 超出达标线的幅度（50% 超出即满格），
        价格越接近达标线 🟦 越少，清零即达标。（▓░ 在钉钉会渲染成黑块，弃用；
        10 格 emoji 在钉钉窄屏必折行破坏完整性，实测 5 格稳定单行）"""
        if not threshold or price is None:
            return ""
        excess = max(0.0, price / threshold - 1)
        filled = min(bars, int(round(excess / 0.5 * bars)))
        return "🟦" * filled + "⬜" * (bars - filled)

    def _flights_table_md(self, route: Route, sections: list) -> str:
        """TOP 明细渲染成表格 PNG 直推（钉钉 markdown 不支持表格，
        文字列表密度高可读性差）；生成/上传失败返回空由文字版兜底。"""
        try:
            from report import render_flights_table, upload_freeimage
            rows = []
            for s in sections:
                for kind, key, th in (
                        ("direct", "top_direct", route.alert_direct),
                        ("transfer", "top_transfer", route.alert_transfer)):
                    fs = []
                    for f in s.get(key) or []:
                        g = dict(f)
                        ok = th > 0 and g["price"] <= th
                        if kind == "transfer":
                            ok = ok and self._arrival_ok(
                                g, route.transfer_arrival_max)
                        g["_qual"] = ok
                        fs.append(g)
                    rows.append((kind, fs))
            cands = self._fp_cands(sections, top_n=3)
            if cands:
                comp = []
                for save, fs in cands:
                    best = fs[0]
                    chain = " → ".join(
                        f"{self.PLATFORM_CN.get(f.get('_platform', ''), '?')}"
                        f"￥{f['price']:.0f}" for f in fs)
                    label = best.get("name") or best.get("code", "同班")
                    comp.append(f"⚖️ {label} {best['depTime']}→{best['arrTime']}"
                                f"：{chain}（可省 ￥{save:.0f}）")
                rows.append(("compare", comp))
            title = (f"{route.from_name}→{route.to_name} "
                     f"{sections[0]['date']} 最优明细 TOP5")
            bd = sections[0].get("best_direct")
            bt = sections[0].get("best_transfer")
            bits = []
            if bd:
                bits.append(f"直飞最低 ￥{bd['price']:.0f}"
                            f"（线 ￥{route.alert_direct:.0f}）"
                            if route.alert_direct > 0
                            else f"直飞最低 ￥{bd['price']:.0f}")
            if bt:
                bits.append(f"达标中转最低 ￥{bt['price']:.0f}"
                            f"（线 ￥{route.alert_transfer:.0f}）"
                            if route.alert_transfer > 0
                            else f"中转最低 ￥{bt['price']:.0f}")
            out = (f"data/flights_table_{route.from_code}{route.to_code}"
                   f"_{sections[0]['date']}.png")
            render_flights_table(
                rows, title, out, summary=" ｜ ".join(bits))
            url = upload_freeimage(out, self.logger)
            if url:
                return f"### 📋 最优明细 TOP5（价格红色=达标）\n\n![明细表]({url})\n\n"
            self.logger.warning("[表格图] 上传失败，回退文字明细")
        except Exception as e:
            self.logger.warning("[表格图] 生成失败，回退文字明细: %s", e)
        return ""

    @classmethod
    def _fmt_brief(cls, f: dict) -> str:
        """渠道速览单条：加粗价格 + 类别 + 航班 + 时刻，紧凑一屏可读。"""
        cross = f.get("crossDayDesc") or ""
        arrive = f"{f['arrTime']}（{cross}达）" if cross else f"{f['arrTime']} 当日达"
        if f.get("transCity"):
            return (f"**￥{f['price']}** 中转{f['name']} 经{f['transCity']} "
                    f"{f['depTime']}→{arrive}")
        return f"**￥{f['price']}** 直飞{f['name']} {f['depTime']}→{arrive}"

    @staticmethod
    def _dep_in_window(dep: str, dmin: str, dmax: str) -> bool:
        """出发时刻窗口判定（HH:MM 钟面，空边界不限；不含跨零点窗口）。"""
        if not dep:
            return not (dmin or dmax)
        try:
            m = int(dep[:2]) * 60 + int(dep[3:5])
        except (ValueError, IndexError):
            return True
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

    def _category_alert(self, route: Route, date: str, f: dict, category: str,
                        threshold: float, pool_size: int, src_platform: str):
        price = float(f["price"])
        label = "直飞" if category == "direct" else "中转"
        route_key = f"{self.user}|{route.from_code}-{route.to_code}-{date}-{category}"
        if price > threshold:
            if self.storage:
                self.storage.clear_alert_state(route_key)
            return
        last = self.storage.get_alert_state(route_key) if self.storage else None
        should_push, reason = self._should_push(price, last)
        self.logger.warning(
            "[低价-%s] %s->%s %s ￥%.0f %s（阈值￥%.0f, 上次推送￥%s）-> %s",
            label, route.from_name, route.to_name, date, price,
            f["name"], threshold, f"{last:.0f}" if last else "-",
            "推送" if should_push else f"跳过({reason})",
        )
        if should_push and self.notifier:
            ok = self._push_flight(route, date, f, category, threshold,
                                   last, pool_size, src_platform)
            if ok and self.storage:
                self.storage.set_alert_state(route_key, price)

    def _push_flight(self, route: Route, date: str, f: dict, category: str,
                     threshold: float, last: Optional[float], pool_size: int,
                     src_platform: str) -> bool:
        label = "直飞" if category == "direct" else "中转"
        cross = f.get("crossDayDesc", "")
        arrive_txt = f"{f['depTime']} → {f['arrTime']}"
        if cross:
            arrive_txt += f"（{cross}到达）"
        emoji = "✈️"
        diff_txt = ""
        if last is not None:
            diff = f["price"] - last
            emoji = "📉" if diff <= 0 else "📈"
            diff_txt = (f"（较上次推送降 ￥{-diff:.0f}）" if diff <= 0
                        else f"（较上次推送涨 ￥{diff:.0f}）")

        title = (f"{emoji} {label}低价 {route.from_name}→{route.to_name} "
                 f"{date} ￥{f['price']}{diff_txt} {f['name']}")

        view_url = self._build_view_url(route, date, src_platform)
        desp = (
            f"## 机票低价提醒（{label}）\n\n"
            f"- **航线**：{route.from_name}（{route.from_code}） → "
            f"{route.to_name}（{route.to_code}）\n"
            f"- **日期**：{date}\n"
            f"- **航班**：{f['name']}\n"
            f"- **起降**：{arrive_txt}\n"
        )
        if f.get("transCity"):
            desp += (f"- **中转**：{f['transCity']}"
                     f"（全程 {f.get('totalDuration', '?')}）\n")
        desp += (
            f"- **价格**：**￥{f['price']}**（阈值 ￥{threshold:.0f}）{diff_txt}\n"
            f"- **达标班次数**：{pool_size}\n"
            f"- **抓取时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"\n[👉 在{src_platform}查看详情]({view_url})\n"
        )
        return self.notifier.send(title, desp)

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

        # markdown 详细
        view_url = self._build_view_url(route, date, p.platform)
        desp = (
            f"## 机票低价提醒\n\n"
            f"- **航线**：{route.from_name}（{route.from_code}） → "
            f"{route.to_name}（{route.to_code}）\n"
            f"- **日期**：{date}\n"
            f"- **当前最低价**：**￥{p.price:.0f}**\n"
            f"- **设定阈值**：￥{route.alert_threshold:.0f}\n"
            f"- **来源**：{p.platform}\n"
            f"- **抓取时间**：{p.fetched_at}\n"
        )
        if last is not None:
            desp += f"- **上次推送价**：￥{last:.0f}\n"
        desp += f"\n[👉 在 {p.platform} 查看详情]({view_url})\n"
        return self.notifier.send(title, desp)

    def _build_view_url(self, route: Route, date: str, platform: str) -> str:
        """用户侧「查看详情」跳转链接——与各渠道爬虫已验证主路径同源。
        链接是给人点的，页面必须真的出数据：v5.0.0 渠道 PC 化时爬虫换了
        PC 主路径，用户链接必须同步（否则 qunar touch H5 风控死页 =
        挂羊头卖狗肉）。"""
        from urllib.parse import quote as _q
        fn, tn = _q(route.from_name), _q(route.to_name)
        if platform == "ctrip":
            return (
                "https://m.ctrip.com/html5/flight/taro/first?from=inner"
                "&tripType=ONE_WAY"
                f"&dcity={route.from_code}&acity={route.to_code}&ddate={date}"
            )
        if platform == "tongcheng":
            return (
                "https://m.ly.com/ft/touch/book1"
                f"?date={date}&an=1&cn=0&baby=0"
                f"&fromcitycode={route.from_code}&fromCode={route.from_code}"
                f"&tocitycode={route.to_code}&toCode={route.to_code}"
                "&cabin=0&platcode=518&frompage=HOME"
            )
        if platform == "qunar":
            # PC 版单程列表（crawlers/qunar.py PC_URL_TPL 同源——
            # wbdflightlist 主路径已实测出全量明细；touch H5 接口已风控死）
            return (
                "https://flight.qunar.com/site/oneway_list.htm?"
                f"searchDepartureAirport={fn}&searchArrivalAirport={tn}"
                f"&searchDepartureTime={date}&nextNDays=0&startSearch=true"
                f"&fromCode={route.from_code}&toCode={route.to_code}"
                "&from=flight_dom_search"
            )
        if platform == "tuniu":
            return (
                "https://m.tuniu.com/flight/domestic/new/"
                f"{route.from_code}_{route.to_code}_OW_1_0_0"
                f"?deptDate={date}&isGo=0"
            )
        # fliggy：PC SSR 列表页（crawlers/fliggy.py URL_TPL 同源——
        # 渠道本体就是 PC 直读；原 H5 outfliggys 为旧入口）
        return (
            "https://sjipiao.fliggy.com/flight_search_result.htm"
            "?tripType=0"
            f"&depCity={route.from_code}&arrCity={route.to_code}"
            f"&depDate={date}&depCityName={fn}&arrCityName={tn}"
        )
