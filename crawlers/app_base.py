# -*- coding: utf-8 -*-
"""App 渠道基类：不依赖 Playwright，但复用既有账本契约。

为什么另起一个基类而不是继承 BaseCrawler：BaseCrawler 的
`browser()` / `_browser_context()` 全是 Playwright 实现，App 渠道继承
它会把一整套用不上的浏览器路径带进来，且 `fetch` 里误调 `self.browser()`
会静默开一个 Chromium。这里只保留真正共享的部分：

  * `PATH_STATUS` / `path_reset()` / `path_note()` —— 账本字段与
    BaseCrawler **逐键一致**（test_app_crawler_base 钉住），这样探针
    面板、复发账、健康解析都能无差别消费；
  * `safe_fetch()` —— 同签名、同「吞异常返回 []」语义；
  * 日志行 `[<plat>] ...` —— 健康解析的唯一数据源格式。

差异点：`login_url()` 对 App 渠道返回的是**登录入口描述**而非真实 URL
（App 没有可粘贴的登录页），由 webui 走内嵌画面流程。
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from typing import List

from core.models import FlightPrice

# 冻结态用 exe 所在目录：否则 user_data（登录态）会落进 _internal，
# 用户找不到、升级即丢。与 main.py 同源（core.paths.app_root）。
if getattr(sys, "frozen", False):
    from core.paths import app_root as _app_root
    _REPO_ROOT = _app_root()
else:
    _REPO_ROOT = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))


class AppCrawler:
    """Android App 渠道基类（单设备串行采集）。"""

    name: str = "app_base"
    package: str = ""          # Android 包名
    # 与 BaseCrawler 保持一致（另有 calendar 表达"只出每日最低价"），
    # 并补 App 特有的三类拦路物：广告弹层 / 验证码 / 人脸核验。
    # 它们必须能独立入账——把"被挡住"记成 empty 或 error，等于让账本说谎。
    PATH_STATUS = ("ok", "empty", "login", "blocked", "timeout",
                   "error", "parse_error", "unsupported", "calendar",
                   "soft_reject", "ad", "captcha", "face")
    # 会话是否可疑（webui 登录卡分层用），实例级每轮复位
    login_suspect: bool = False

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = dict(config or {})
        self.logger = logger
        self.timeout_s = int(self.config.get("action_timeout_s", 60) or 60)
        self.paths: list = []
        self.last_path = ""
        self.last_status = ""
        self.last_error = ""
        self._runtime = None
        # 与浏览器渠道同一条约定：资料目录按仓库根解析，不随 cwd 漂移
        # （登录态快照要落在这里，chdir 后写错位置用户会找不到自己的凭证）。
        root = str(self.config.get("user_data_dir") or "user_data").strip() \
            or "user_data"
        self.user_data_root = os.path.abspath(os.path.join(_REPO_ROOT, root))
        # 登录态快照：进程内只尝试恢复一次（每个渠道各一次）。
        # 只导出不恢复等于白存——用户「登录一次」后换次进程又得重登。
        self._snapshot_restored = False

    # ---------- 登录态快照 ----------
    def _snapshot_manager(self, dev):
        """构造快照管理器；配置关闭或包名为空时返回 None。"""
        android = self.config.get("android") or {}
        if android.get("snapshot") is False:
            return None
        if not self.package:
            return None
        try:
            from core.android.snapshot import SnapshotManager, SnapshotStore
            store = SnapshotStore(
                os.path.join(self.user_data_root, "android_snapshots"))
            return SnapshotManager(dev, store, self.package)
        except Exception:
            return None

    # 登录墙判据（子类覆盖）：默认认手机号表单 + 「立即登录」类文案。
    # 各渠道登录墙形态不同，但「恢复快照后仍在登录页」这件事必须能判出来。
    LOGIN_FORM_MARKS = ("请输入手机号", "获取验证码")

    def is_login_wall(self, xml: str) -> bool:
        """当前页面是不是登录墙（子类可加自己的判据）。"""
        return any(m in (xml or "") for m in self.LOGIN_FORM_MARKS)

    def _clear_blockers(self, dev, xml: str):
        """处理页面拦路物。返回 (xml, Block)。

        策略分级（与 PC/H5 渠道的处置规范一致）：
          * **广告**：只是遮挡 → 自动点关闭，最多两次；关不掉就上报 `ad`，
            让用户看到"被广告挡住"，而不是记成没数据。
          * **验证码**（含滑块/图形点选）：风控已触发，**不自动破解**，
            记 `captcha`；这对应 CAPTCHA_SOLUTION 的人工接管边界。
          * **人脸识别**：生物特征核验，自动化无法也不应伪造 → 记 `face`，
            明确告知用户必须本人操作，且不会被重试掩盖。
          * **登录**：记 `login`，由内嵌登录画面处理。
        """
        from .app_blockers import Block, detect_block

        for _ in range(2):
            block = detect_block(xml)
            if block.kind != "ad" or not block.close_xy:
                return xml, block
            # 广告可关：点掉后重取一次页面
            self.logger.info("[%s] 关闭广告弹层 %s", self.name, block.close_xy)
            dev.tap(*block.close_xy)
            time.sleep(1.5)
            xml = dev.dump()
            if not xml:
                return "", Block("", "no-ui")
        # 关两次还在：当作关不掉的广告上报，不再纠缠
        return xml, detect_block(xml)

    @staticmethod
    def _looks_blank(xml: str) -> bool:
        """页面是不是还没渲染出来（白屏中间态）。

        真机：force-stop 后立刻发深链，会停在 `TabHomeActivity` 的白屏，
        dump 一个节点都没有，等多久也不自愈。把这种状态当成「已登录」
        会让快照恢复被跳过，整轮跑在空页面上。
        """
        return (xml or "").count("<node") < 6

    def restore_login_snapshot(self, dev) -> bool:
        """首次采集前恢复登录态；返回 True 表示这次真的恢复了。

        - 没有快照、配置关闭、设备不可用，都**静默跳过**（不是错误）；
        - 一个进程内只尝试一次，避免每轮都重启 App 白花时间；
        - 恢复失败要留痕：`snap-restore` 记一条，用户能看到是「恢复失败」
          而不是「明明登录过却还要重登」。

        **设备上已经登录着就绝不恢复**：快照是某一时刻的副本，用完即旧。
        去哪儿的会话凭据还带服务端刷新（真机实测：刚登录完导出快照，
        立刻恢复 → App 回登录墙；不恢复、直接重启 → 登录态正常）。用旧
        副本盖掉设备上更新的会话，等于每次采集都把用户踢下线。
        """
        if self._snapshot_restored:
            return False
        self._snapshot_restored = True
        # 没有快照就没有恢复可谈：**绝不能为此重启 App 去探测页面**。
        # 旧实现先 app_stop + 启动 + 轮询 dump 判断「是否已登录」，再去看
        # 有没有快照——没快照的用户每轮白重启一次 App，而且这次 dump 会
        # 吞掉启动首屏的广告/弹层，后面 `_clear_blockers` 再也看不到它，
        # 广告就那么盖着页面（实测：整轮零数据且看不出原因）。
        try:
            _mgr0 = self._snapshot_manager(dev)
            if _mgr0 is None or not _mgr0.store.exists(self.name):
                return False
        except Exception:
            return False
        # 设备已登录：保持现状，不动它的数据。
        try:
            dev.app_stop(self.package)
            time.sleep(1.5)
            if getattr(self, "home_uri", ""):
                dev.deep_link(self.home_uri)
            else:
                dev.app_start(self.package)
            deadline = time.time() + 30
            xml = ""
            while time.time() < deadline:
                time.sleep(2.5)
                xml = dev.dump() or ""
                if xml and not self._looks_blank(xml):
                    # 登录页是**启动首屏**，不等于未登录（去哪儿实测：
                    # 停在 UCLoginByPhoneActivity 时深链能进首页且是登录态）。
                    # 首屏就是登录墙时再发一次深链，能进首页就算已登录。
                    if self.is_login_wall(xml) and getattr(self, "home_uri", ""):
                        dev.deep_link(self.home_uri)
                        time.sleep(6)
                        xml = dev.dump() or ""
                    break
            if xml and not self._looks_blank(xml) and \
                    not self.is_login_wall(xml):
                self.logger.info("[%s] 设备上已登录，跳过快照恢复", self.name)
                return False
        except Exception:
            pass
        mgr = self._snapshot_manager(dev)
        if mgr is None:
            return False
        try:
            if not mgr.store.exists(self.name):
                return False
            ok, detail = mgr.restore(self.name)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        if ok:
            self.logger.info("[%s] 已恢复登录态快照（%s）", self.name, detail)
            # 恢复了快照但这台设备仍停在登录墙 → 快照**已失效**（会话过期 /
            # 被风控注销）。这跟「恢复失败」是两件事，用户要的处置也不同：
            # 前者该重新登录，后者该查文件。不判这一下，账本只会有
            # 「恢复 ok」+「要求登录」，读者看不出到底哪一步出了问题。
            expired = ""
            try:
                wall = dev.dump() or ""
                if wall and self.is_login_wall(wall):
                    expired = "；快照已失效（仍停在登录墙，需重新登录）"
            except Exception:
                pass
            # r640c：账本契约是「ok 必须带行数」——快照恢复本身不取数，
            # 显式 rows=0 并写明这是登录态恢复、不是一次成功取数，
            # 免得被读成「恢复了快照 = 查到了航班」。
            self.path_note("snap-restore", "ok", rows=0,
                           detail="登录态恢复（非取数）："
                                  + str(detail)[:100] + expired)
            # 恢复里刚 app_start 过，等界面稳定再让调用方继续判断；
            # 否则紧接着的 dump 可能还是旧的（权限框/首页都读不到）。
            time.sleep(2)
            return True
        self.logger.warning("[%s] 登录态快照恢复失败：%s", self.name, detail)
        # 「设备上的登录态比快照新」不是失败，是刻意保留——记成 error 会
        # 让健康卡显示「快照恢复失败」，而实际情况正相反（用户在 App 里
        # 刚登过，恢复才是错的）。这类记录用 skipped 语义单独标注。
        if "比快照新" in str(detail):
            self.path_note("snap-restore", "ok", rows=0,
                           detail="跳过恢复（非失败）：" + str(detail)[:120])
            return False
        self.path_note("snap-restore", "error", detail=str(detail)[:150])
        return False

    def _dismiss_system_prompts(self, dev) -> int:
        """点掉系统权限弹窗（通知/定位等）。返回处理次数。

        换机、重装、`pm clear` 之后，智行每次启动都可能弹系统级权限框，
        它盖在首页上——采集会读成「首页未就绪 / 页面认不出」，被误判成
        App 改版。这不是风控，可以代点「允许」。

        只看 **activity** 决定要不要介入：不在权限控制器时**不读页面**。
        读页面会消耗调用方的页面序列（实测把广告页吃掉，导致广告关不掉）。
        """
        from .app_zhixing_nav import nodes
        allow = ("允许", "始终允许", "仅在使用中允许", "确定", "知道了")
        handled = 0
        deadline = time.time() + 12
        while time.time() < deadline and handled < 6:
            try:
                act = (dev.current_activity() or "").lower()
            except Exception:
                act = ""
            if "permission" not in act:
                return handled
            xml = dev.dump() or ""
            hit = None
            for n in nodes(xml):
                if (n.text or "").strip() in allow:
                    hit = n
                    break
            if hit is None:
                time.sleep(1)
                continue
            self.logger.info("[%s] 关闭系统权限弹窗：%s", self.name, hit.text)
            dev.tap(hit.cx, hit.cy)
            handled += 1
            time.sleep(1.5)
        return handled

    def path_reset(self):
        self.paths = []
        self.last_path = ""
        self.last_status = ""

    def path_note(self, path: str, status: str, rows: int = 0,
                  date: str = "", detail: str = "", ms: int = 0,
                  http_status: int = 0, url: str = ""):
        if status not in self.PATH_STATUS:
            status = "error"
        rec = {"path": str(path), "status": status,
               "rows": int(rows or 0), "date": str(date or ""),
               "detail": str(detail or "")[:160], "ms": int(ms or 0),
               "http": int(http_status or 0),
               "mobile": True}
        if url:
            rec["url"] = str(url)[:500]
        if not hasattr(self, "paths"):
            self.path_reset()
        self.paths.append(rec)
        self.last_path = rec["path"]
        self.last_status = rec["status"]
        return rec

    # ---------- 运行时 ----------
    def runtime(self):
        if self._runtime is None:
            from core.android.runtime import get_runtime
            self._runtime = get_runtime(self.config, self.logger)
        return self._runtime

    # ---------- 调用入口 ----------
    #: 渠道是否支持往返（App 渠道目前都只做单程）。不支持时**必须显式
    #: unsupported 落账并返回空**——静默忽略 ret_date 会把单程价当成往返
    #: 总价，推送/走势据此报警（浏览器渠道 TRIP 同款口径）。
    supports_round_trip: bool = False

    def safe_fetch(self, from_city: str, to_city: str, dates: List[str],
                   ret_date: str = "") -> List[FlightPrice]:
        self.path_reset()
        self.last_error = ""
        try:
            if ret_date and not self.supports_round_trip:
                self.logger.warning(
                    "[%s] 往返明细暂不支持（返程 %s），未发起单程查询",
                    self.name, ret_date)
                self.path_note("TRIP", "unsupported",
                               detail="往返明细暂不支持，未发起单程查询")
                return []
            self.logger.info("[%s] 开始抓取 %s->%s 日期=%s",
                             self.name, from_city, to_city, dates)
            results = self.fetch(from_city, to_city, dates,
                                 ret_date=ret_date) or []
            self.logger.info("[%s] 抓取完成，得到 %d 条记录",
                             self.name, len(results))
            return results
        except Exception as e:  # 设备掉线/解析失败都走这里
            self.last_error = f"{type(e).__name__}: {e}"
            self.logger.warning("[%s] 抓取失败: %s", self.name, self.last_error)
            if not any(p.get("status") == "error" for p in self.paths):
                self.path_note("app-error", "error", detail=self.last_error)
            return []

    # ---------- 航线 / 城市名 / 逐日期记账（所有 App 渠道同一套语义） ----------
    #
    # 这三件事曾各自写在单个渠道里：城市名映射只在智行有一份、去哪儿另抄
    # 12 条别名表；「航线未变就跳过重设」只有智行有；逐日期记账两个渠道
    # 各写一遍，措辞与 empty 判据还不一致。新增渠道必然再抄一遍——所以
    # 收进基类，子类只实现 `read_route` 这一个「从屏幕读事实」的钩子。

    @staticmethod
    def _city_name(code: str) -> str:
        """三字码 → App 里显示的中文城市名（全渠道单源）。

        配置里常用机场码（PEK/NRT），而 App 的城市是城市级（北京/东京）；
        先过项目的 airport_city_code 归一，再取中文名。查不到就原样
        传下去——宁可让它显式失败，也不要瞎猜一个城市。
        """
        try:
            from core.citydata import CODE_NAME
        except Exception:
            return code
        c = (code or "").upper()
        try:
            from core.intl import airport_city_code
            c = (airport_city_code(c) or c).upper()
        except Exception:
            pass
        nm = CODE_NAME.get(c) or ""
        if not nm:
            # 国际城市（NRT/PVG 之类）不在国内表里：走 core.intl 的城市名表，
            # 浏览器渠道用的是同一张表（PC/H5 已覆盖国际，App 必须同名）。
            try:
                from core.intl import city_name_of
                nm = city_name_of(c) or ""
                if nm == c:          # 查不到时它会原样返回，别当成真名
                    nm = ""
            except Exception:
                nm = ""
        for suf in ("市", "自治州", "地区"):
            nm = nm.replace(suf, "")
        return nm or code

    def read_route(self, dev):
        """App 当前停留的航线 (出发名, 到达名)；读不出返回 None。

        子类实现。判据必须是**屏幕上的字**，不是记忆：App 可能被用户手动
        改过、被系统回收后恢复成别的航线；只有屏幕才是事实。
        """
        return None

    def _route_unchanged(self, dev, from_city: str, to_city: str) -> bool:
        """App 当前是否已停在目标航线上（按界面文案判，不靠记忆）。"""
        try:
            cur = self.read_route(dev)
        except Exception:
            return False        # 判不了就当「需要重设」，宁慢勿错
        if not cur:
            return False
        return cur == (self._city_name(from_city), self._city_name(to_city))

    def note_date(self, date: str, got, why: str, ms: int = 0,
                  url: str = "", path: str = "航班明细"):
        """逐日期记账的**单源**：ok / empty / timeout 的判据与措辞只在这里。
        `empty` 只允许表示「列表页确实打开且该日无航班」；其余一律
        timeout 并写明卡点——「没采到」不等于「没票」，这是账本红线。
        各 App 渠道传同一种 reason 词汇，健康卡/节流才读得懂同一件事。
        """
        if got:
            return self.path_note(path, "ok", rows=len(got), date=date,
                                  detail="%d 条真实航班/时刻/价格" % len(got),
                                  ms=ms, url=url)
        if why == "empty":
            return self.path_note(path, "empty", date=date,
                                  detail="列表已打开，该日无可售航班")
        if why == "login":
            return self.path_note(path, "login", date=date,
                                  detail="该日被要求登录")
        return self.path_note(path, "timeout", date=date,
                              detail="未取到可用结果：%s" % (why or "unknown"))

    # ---------- 子类必须实现 ----------
    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        raise NotImplementedError

    def login_url(self) -> str:
        """App 渠道返回登录入口描述（无真实 URL）。"""
        raise NotImplementedError

    # ---------- 自愈：App 卡死（ANR） ----------
    def diagnose_anr(self, dev) -> str:
        """读 ANR 现场，返回一句可读结论（读不到返回空串）。

        实测两类原因，处置完全不同：
          * **动态 so 与设备 ABI 不匹配**：`/data/anr/*` 主线程 Blocked 在
            `Runtime.load0`，等 `DynamicSoManager` 下载/加载锁；而设备是
            x86_64、so 是 arm64（去哪儿 `libbnfacesdk.so` 实测）。这类是
            **环境缺陷**，重启也只会再撞一次，必须换 32/64 位匹配的包或
            让该模块不加载；采集端能做的是如实上报，不是无限重试。
          * **临时卡顿**：重启通常能恢复。
        """
        try:
            out = dev._sh("shell", "sh", "-c",
                          "f=$(ls -t /data/anr/ 2>/dev/null | head -1); "
                          "[ -n \"$f\" ] && head -40 /data/anr/$f",
                          timeout=30) or ""
        except Exception:
            return ""
        if not out:
            return ""
        for line in out.splitlines():
            if "is not responding" in line or "isn't responding" in line:
                return line.strip()[:160]
        return ""

    def prepare_device(self, dev) -> None:
        """设备就绪后的**统一前置**：恢复登录态 → 清系统权限框 → 清 ANR。

        三个 App 渠道共用同一条前置顺序（不要各写一份）：快照恢复会重启
        App，而重启后最容易撞上「没有响应」死锁（实证：主线程等 so 下载
        锁）。放在这里，任何渠道第一轮都不会因为卡死白跑。
        """
        self.restore_login_snapshot(dev)
        self._dismiss_system_prompts(dev)
        self.recover_anr(dev, wait_s=30)

    def recover_anr(self, dev, attempts: int = 1, wait_s: int = 45,
                    restart_after: bool = True) -> bool:
        """处理系统「没有响应」对话框；恢复成功返回 True。

        ANR 由 App 自身造成（实证：主线程 Blocked 在 Runtime.load0，等
        DynamicSoManager 下载 so 时持有的锁），与我们的点击无关，但**会一直
        挡着**——不处理就是整轮「打不开首页」。

        实测：点「等待」后 **186s 依然卡着**（死锁不会自己解开），所以
        「等待」只能当第一手；等不回来就必须 force-stop 冷启动。点
        「关闭应用」等同于重启，但由系统杀进程更不可控，因此自己 stop。
        """
        from .app_blockers import BLOCK_ANR, _ANR_WAIT, detect_block
        # **不 dump 就不可能有 ANR**：dump 会消耗调用方的页面序列（实测
        # 把广告页吃掉，导致关不掉广告）。所以先用 activity 粗筛——ANR
        # 对话框挂在 Dispatcher/启动页上，正常业务页面不会。只有像 ANR
        # 时才读页面做精确判定。
        try:
            act = (dev.current_activity() or "").lower()
        except Exception:
            # 读不到当前 Activity = 无法判断有没有 ANR。此时**不能**下探
            # `dump()`：dump 会消耗调用方的页面序列（实测把广告页吃掉，
            # 于是关不掉广告、整轮白跑）。判不了就不动手。
            return True
        if act and ("dispatcher" not in act and "splash" not in act
                    and "launcher" not in act):
            return True
        xml = dev.dump() or ""
        if not xml or detect_block(xml).kind != BLOCK_ANR:
            return True
        xy = None
        for m in re.finditer(
                r'<node[^>]*?text="([^"]*)"[^>]*?bounds='
                r'"\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
            if m.group(1).strip() in _ANR_WAIT:
                xy = ((int(m.group(2)) + int(m.group(4))) // 2,
                      (int(m.group(3)) + int(m.group(5))) // 2)
                break
        if xy is not None:
            self.logger.warning("[%s] App 无响应，先点「等待」（最多等 %ds）",
                                self.name, wait_s)
            dev.tap(*xy)
            end = time.time() + wait_s
            while time.time() < end:
                time.sleep(4)
                xml = dev.dump() or ""
                if xml and detect_block(xml).kind != BLOCK_ANR:
                    return True
        if not restart_after or not self.package:
            return False
        # 死锁等不回来：自己重启（不点「关闭应用」，避免系统侧不可控杀进程）
        why = self.diagnose_anr(dev)
        self.logger.warning("[%s] App 卡死未恢复，重启 App%s", self.name,
                            ("（现场：%s）" % why) if why else "")
        self._anr_reason = why
        dev.app_stop(self.package)
        time.sleep(2)
        ok = dev.deep_link(getattr(self, "home_uri", "") or "") \
            if getattr(self, "home_uri", "") else False
        if not ok:
            ok = dev.app_start(self.package)
        if not ok:
            return False
        end = time.time() + 90
        while time.time() < end:
            time.sleep(4)
            xml = dev.dump() or ""
            if xml and detect_block(xml).kind != BLOCK_ANR:
                return True
        return False
