# -*- coding: utf-8 -*-
"""采集节流 / 熔断内核（1–5 区）。

纯逻辑、零 I/O、可注入时钟：所有决策都能单测，不在函数里 sleep，
也不碰浏览器与网络。三条硬约束：

1. **不在锁内睡眠**：`wait_hint()` 只返回"还要等几秒"，睡眠由调用方在
   渠道锁与全局闸门之外执行——否则慢渠道会把别的渠道一起拖住。
2. **熔断是"停手"不是"降速"**：冷却期内该渠道一个请求都不发，而不是
   拉长间隔继续试探。
3. **SessionBusyError 不算服务端拒绝**：自家锁没抢到只让位本轮，不累积
   strikes、不冷却——把它当限流退避，等于用自家 bug 惩罚对方站点。

配置全部来自 `schedule` 与 `crawler.rate / crawler.breaker`，缺省值保持
旧行为（关闭或宽松），保存即热生效。
"""
import math
import re
import threading
import time

from .models import CAL_PATH_FAMILY
from collections import deque
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

PLATFORMS = ("ctrip", "fliggy", "qunar", "tongcheng", "tuniu")
# App 渠道（可选）：需要独立节奏 key，但**不属于**内置浏览器渠道集合。
# 清单来自零依赖的 core/channels.py（曾在此本地另写一份，加渠道必然漏改）。
from core.channels import APP_CHANNELS, path_cn  # noqa: E402

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

# 失败归类关键词：按"谁的问题"分桶，顺序即优先级。
# 403/429 必须按「独立数字」匹配——路径详情里带价格（如 ￥1403）时，
# 裸子串会把正常出价当成限流信号，熔断一个健康的渠道。
_IP_CODE_RE = re.compile(r"\b(?:403|429)\b")
_IP_MARKS = ("风控", "限流", "179991", "ip封", "ip 封")
_CAPTCHA_MARKS = ("验证码", "滑块", "人机验证", "访问验证", "安全验证",
                  "challenge", "captcha")
_LOGIN_MARKS = ("请登录", "未登录", "需登录", "登录失效", "会话失效")
# 软拒：边缘节点/会话层没有正面拒绝，但也没给业务响应。它不是"真无票"，
# 也不该按 IP 限流熔断——正确动作是下一轮先养会话再查。
_SOFT_MARKS = ("软拒", "444", "202 空", "202空")

DEFAULTS = {
    "scan_quiet_start": "",
    "scan_quiet_end": "",
    "fast_ttl_min": 15,
    "slow_ttl_min": 120,
    "near_ratio": 0.15,
    "stagger_seconds": 0,
    "breaker_enabled": True,
    "breaker_base_s": 300,
    "breaker_cap_s": 3600,
    "login_cooldown_s": 900,
    "min_gap_s": 0,
    "per_minute": 0,
    "warmup_enabled": True,
    "warmup_platforms": ("qunar", "fliggy", "tuniu"),
    # 成功率保护（自动降频）开关。关掉后 set_health 仍记录 rate/attempts
    # 供界面显示，但 penalty 恒为 1.0，不再拉长 TTL——用户显式要求
    # 「宁可多打也别降频」时有办法做到（熔断/预热同理各有关闭项）。
    "health_penalty_enabled": True,
    # 成功率保护的阈值（r485：原先写死在 set_health 里，用户只能开/关，
    # 不能按自己渠道的实际情况调）。四档语义保持原样，只把数字提出来：
    #   rate >= health_ok_ratio           → ×1（不降频）
    #   rate >= health_slow_ratio         → ×health_slow_factor
    #   更低                              → ×health_slowest_factor
    #   样本 < health_min_samples         → 不判（避免首轮波动就降频）
    "health_min_samples": 5,
    "health_ok_ratio": 0.7,
    "health_slow_ratio": 0.4,
    "health_slow_factor": 1.5,
    "health_slowest_factor": 3.0,
    "cadence": {},
    # 同轮并发浏览器的硬上限（0=跟随渠道数）。同机 5 家齐发最容易被
    # 判成"同一来源的多路机器人"，2 路是实测较稳的档。
    "max_concurrency": 0,
    # 临期多少天内进入快层（默认 3 天）
    "near_days": 3,
}


def _flag(v, default):
    """把配置里的开关值解析成布尔。

    `config.yaml` 是手写的，`enabled: "false"`（带引号）在 YAML 里是**字符串**，
    而 `bool("false")` 是 True —— 开关会静默失效：界面按 `!== false` 显示
    「已关闭」，后端却仍按开启执行（r519 实测 health_penalty / breaker /
    warmup 三处全中）。字符串按常见假值词判定，与 YAML 语义一致。
    """
    if v is None:
        return bool(default)
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(v)


def _num(v, default, lo, hi, cast=int):
    try:
        n = cast(v)
    except (TypeError, ValueError):
        return default
    if n != n:                      # NaN
        return default
    return max(lo, min(hi, n))


def parse_pacing(cfg):
    """把 config.yaml 的 schedule / crawler.rate / crawler.breaker 归一成
    扁平字典；非法值回默认并钳位（宁缺勿错：坏配置不该让监控整轮停摆）。"""
    cfg = cfg or {}
    sc = cfg.get("schedule") or {}
    crw = cfg.get("crawler") or {}
    rate = crw.get("rate") or {}
    brk = crw.get("breaker") or {}

    out = dict(DEFAULTS)
    out["scan_quiet_start"] = (
        str(sc.get("scan_quiet_start") or "").strip()
        if parse_hhmm(sc.get("scan_quiet_start")) is not None else "")
    out["scan_quiet_end"] = (
        str(sc.get("scan_quiet_end") or "").strip()
        if parse_hhmm(sc.get("scan_quiet_end")) is not None else "")
    out["fast_ttl_min"] = _num(sc.get("fast_ttl_min"),
                               DEFAULTS["fast_ttl_min"], 5, 1440)
    out["slow_ttl_min"] = _num(sc.get("slow_ttl_min"),
                               DEFAULTS["slow_ttl_min"], 5, 1440)
    if out["slow_ttl_min"] < out["fast_ttl_min"]:
        out["slow_ttl_min"] = out["fast_ttl_min"]
    out["near_ratio"] = _num(sc.get("near_ratio"),
                             DEFAULTS["near_ratio"], 0.0, 1.0, float)
    out["stagger_seconds"] = _num(sc.get("stagger_seconds"),
                                  DEFAULTS["stagger_seconds"], 0, 120)
    out["breaker_enabled"] = _flag(
        brk.get("enabled"), DEFAULTS["breaker_enabled"])
    out["breaker_base_s"] = _num(brk.get("base_s"),
                                 DEFAULTS["breaker_base_s"], 30, 3600)
    out["breaker_cap_s"] = _num(brk.get("cap_s"),
                                DEFAULTS["breaker_cap_s"], 120, 86400)
    if out["breaker_cap_s"] < out["breaker_base_s"]:
        out["breaker_cap_s"] = out["breaker_base_s"]
    out["login_cooldown_s"] = _num(brk.get("login_cooldown_s"),
                                   DEFAULTS["login_cooldown_s"], 0, 86400)
    out["min_gap_s"] = _num(rate.get("min_gap_s"),
                            DEFAULTS["min_gap_s"], 0, 300, float)
    if out["min_gap_s"] == int(out["min_gap_s"]):
        out["min_gap_s"] = int(out["min_gap_s"])
    out["per_minute"] = _num(rate.get("per_minute"),
                             DEFAULTS["per_minute"], 0, 600)
    # 预热编排（L1/L3）：只对声明了 warmup_url 的渠道生效；默认三家
    # （qunar/fliggy/tuniu）——ctrip 与同程在各自 fetch 内部已自带预热
    warm = crw.get("warmup") or {}
    out["warmup_enabled"] = _flag(
        warm.get("enabled"), DEFAULTS["warmup_enabled"])
    _pl = warm.get("platforms")
    if _pl is None:
        _pl = list(DEFAULTS["warmup_platforms"])
    if isinstance(_pl, str):
        _pl = [x.strip() for x in _pl.split(",")]
    out["warmup_platforms"] = tuple(
        p for p in (_pl or []) if p in PLATFORMS)
    # 手写 config.yaml 常见 `health_penalty_enabled: "false"`（带引号）。
    # `bool("false")` 是 True —— 开关会**静默失效**：界面显示已关闭、
    # 后端却仍在降频（r519）。字符串按常见真值词判定，与 YAML 语义一致。
    out["health_penalty_enabled"] = _flag(
        crw.get("health_penalty_enabled"),
        DEFAULTS["health_penalty_enabled"])
    # 阈值可配置（r485）：把写死在 set_health 里的四档提出来。钳制保证
    # 「慢档阈值 < 合格阈值」「最慢档 ≥ 慢档」这类顺序不变式，否则用户
    # 填反了会得到「成功率越高罚得越重」的反向行为。
    out["health_min_samples"] = _num(
        crw.get("health_min_samples"), DEFAULTS["health_min_samples"], 1, 200)
    out["health_ok_ratio"] = _num(
        crw.get("health_ok_ratio"), DEFAULTS["health_ok_ratio"], 0.05, 1.0,
        float)
    out["health_slow_ratio"] = _num(
        crw.get("health_slow_ratio"), DEFAULTS["health_slow_ratio"], 0.0,
        out["health_ok_ratio"], float)
    out["health_slow_factor"] = _num(
        crw.get("health_slow_factor"), DEFAULTS["health_slow_factor"], 1.0,
        10.0, float)
    out["health_slowest_factor"] = _num(
        crw.get("health_slowest_factor"), DEFAULTS["health_slowest_factor"],
        out["health_slow_factor"], 20.0, float)
    # 每渠道独立节奏（3 区扩展）：最小采集间隔，0=跟随全局 TTL
    # App 渠道也要有 key：它们共用一台设备，节奏通常比浏览器更宽，
    # 缺 key 会让调度层在取值时退化成"无节奏"。
    cad = crw.get("cadence") or {}
    _cad = {}
    if isinstance(cad, dict):
        for _p in PLATFORMS + APP_CHANNELS:
            try:
                _v = int(cad.get(_p) or 0)
            except (TypeError, ValueError):
                _v = 0
            _cad[_p] = max(0, min(10080, _v))
    out["cadence"] = _cad
    try:
        out["max_concurrency"] = max(0, min(5, int(
            crw.get("max_concurrency") or 0)))
    except (TypeError, ValueError):
        out["max_concurrency"] = 0
    out["near_days"] = _num(sc.get("near_days"),
                            DEFAULTS["near_days"], 0, 30)
    return out


# 只把「页面本身 / 业务接口」的拒绝当渠道信号。广告、统计、埋点请求
# 的 403/429/503 很常见，拿它们熔断渠道会让一次正常采集被第三方脚本
# 误伤——这不是"保守"，是把噪声当因果。
_IGNORE_NET_HOSTS = (
    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "googlesyndication.com", "facebook.", "hotjar.", "sentry.",
    "umeng.", "cnzz.", "hm.baidu.com", "newrelic.", "bugly.",
    "tingyun.", "oneapm.",
)


def should_watch_response(resource_type, url):
    """响应监听只接受文档与 XHR/fetch，并排除已知统计/广告域。"""
    rt = str(resource_type or "").lower()
    if rt not in ("document", "xhr", "fetch"):
        return False
    host = (urlparse(str(url or "")).hostname or "").lower()
    if not host:
        return False
    return not any(k in host for k in _IGNORE_NET_HOSTS)


def parse_local_ts(ts):
    """本地时间串 → epoch 秒；失败/空返回 0。用于重启时读库续上 TTL。"""
    s = str(ts or "").strip().replace("T", " ")
    if not s:
        return 0.0
    for n, fmt in ((19, "%Y-%m-%d %H:%M:%S"),
                   (16, "%Y-%m-%d %H:%M"),
                   (10, "%Y-%m-%d")):
        try:
            return time.mktime(time.strptime(s[:n], fmt))
        except (ValueError, OverflowError):
            continue
    return 0.0


def parse_retry_after(raw, now=None):
    """`Retry-After` → 需要等待的秒数（0=没要求）。

    两种合法形态：秒数（"120"）与 HTTP-date。服务端说等多久就等多久，
    因为这是唯一"对方明确告诉你"的信号——比我们自己拍的 2^n 阶梯可信。
    向上取整（宁晚不早），并封顶一天，防异常值把渠道挂死。
    """
    s = str(raw or "").strip()
    if not s:
        return 0
    try:
        sec = float(s)
    except (TypeError, ValueError):
        try:
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError, IndexError):
            return 0
        if dt is None:
            return 0
        try:
            sec = dt.timestamp() - (time.time() if now is None else float(now))
        except (OverflowError, OSError, ValueError):
            return 0
    if sec <= 0:
        return 0
    return int(min(86400, math.ceil(sec)))


def parse_hhmm(s):
    """'01:00' -> 60；空/非法/越界一律 None（宁缺勿错：错的时间窗会
    把全天静默或全天不静默，两种都比"不配置"更糟）。"""
    m = _HHMM.match(str(s or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def in_window(now_min, start_min, end_min):
    """左闭右开；start==end 视为关闭（不把"都填 01:00"误读成全天）。"""
    if start_min is None or end_min is None or start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min


def tier_of(age_min, near, fast_ttl, slow_ttl):
    """接近心理价位→快层；远离→慢层；未到 TTL→skip。"""
    ttl = fast_ttl if near else slow_ttl
    if age_min >= ttl:
        return "fast" if near else "slow"
    return "skip"


def stagger_offset(plat, base_seconds):
    """渠道起跑偏移：按固定顺序均分，保证 5 家不挤在同一秒。
    固定（非随机）是刻意的——同一渠道每轮偏移一致，便于复现与对账；
    周期本身的随机性由调度层的 jitter 负责。"""
    base = float(base_seconds or 0)
    if base <= 0:
        return 0.0
    order = list(PLATFORMS)
    step = base / len(order)
    if plat in order:
        return round(order.index(plat) * step, 1)
    import zlib
    return round((zlib.crc32(str(plat).encode("utf-8")) % 1000) / 1000 * base, 1)


# 统一异常词表：code → (中文名, 建议动作, 是否自动自愈)
# UI/日志/建议引擎共用一套，避免"同一个 444 在三处说三种话"。
FAILURE_KINDS = {
    "ip": ("IP/频率限流", "等冷却，必要时换出口", False),
    "captcha": ("人机验证", "用采集同一会话去验证", False),
    "login": ("登录态失效", "重登该渠道", False),
    "soft": ("会话层软拒", "下一轮自动预热（无需人工）", True),
    "timeout": ("请求超时", "等下一轮；连续出现再降频", True),
    "parse_error": ("解析失败", "多为页面改版，需排查", False),
    "empty": ("真无票", "无需处理", True),
    # 渠道边界（非法航线/超窗/无该日价/往返无源）：不是故障也不是
    # 待办，标成"需人工"会把人推去做无用功
    "unsupported": ("渠道不支持", "无需处理（能力边界）", True),
    "error": ("未知错误", "看现场；连续出现再干预", False),
}


def failure_kind(code):
    """code → (中文名, 建议动作, 自动自愈?)，未知码如实返回。"""
    c = str(code or "")
    return FAILURE_KINDS.get(c, ("未分类", "看日志", False))


def classify_failure(statuses, note=""):
    """把一次采集的路径状态归成 ip/captcha/login/""。

    空串=不是"对方拒绝"（超时、解析失败、真无票都归这里）——这类不该
    触发冷却，重试也不会变好，但没有理由停手整个渠道。
    """
    low = str(note or "").lower()
    sts = {str(s or "") for s in (statuses or [])}
    # 软拒优先短路：它常带 444/202 字样，不能先被下面的 IP 规则吃掉，
    # 否则"会话没养熟"会被当成"IP 被限流"冷却整家渠道。
    if "soft_reject" in sts or any(k in str(note or "") for k in _SOFT_MARKS):
        return "soft"
    if _IP_CODE_RE.search(low) or any(k in low for k in _IP_MARKS):
        return "ip"
    # **结构化状态优先于 note 文本**（r625）：路径状态是采集器给出的结论，
    # note 只是给人看的说明。实测一条 status=login、note 写成
    # 「需要登录，可能会弹验证码」的样本会被下面的 captcha 关键词吃掉，
    # 于是「该去重登」被判成「验证挑战」→ 冷却 300 秒而不是引导用户登录。
    # 顺序反过来也同样危险（登录墙里出现「风控」字样会被判 ip）。
    if "login" in sts:
        return "login"
    if "blocked" in sts:
        return "captcha"
    if any(k.lower() in low for k in _CAPTCHA_MARKS):
        return "captcha"
    if any(k in str(note or "") for k in _LOGIN_MARKS):
        return "login"
    return ""


class ChannelBreaker:
    """渠道级熔断：指数退避 + 封顶，成功即复位。

    kind:
      ip / captcha → 阶梯退避（base·2^(n-1)，封顶 cap），累积 strikes
      login        → 固定冷却（默认 15min），不累积 strikes，打 needs_login
      busy         → 0 秒（自家锁冲突，本轮让位即可）
    """

    def __init__(self, base_s=300, cap_s=3600, enabled=True,
                 login_cooldown_s=900):
        self._lock = threading.Lock()
        self._st = {}
        self.configure(base_s, cap_s, enabled, login_cooldown_s)

    def configure(self, base_s=None, cap_s=None, enabled=None,
                  login_cooldown_s=None):
        with self._lock:
            if base_s is not None:
                self.base_s = max(30, int(base_s))
            if cap_s is not None:
                self.cap_s = max(120, int(cap_s))
            if self.cap_s < self.base_s:
                self.cap_s = self.base_s
            if enabled is not None:
                self.enabled = bool(enabled)
            if login_cooldown_s is not None:
                self.login_cooldown_s = max(0, int(login_cooldown_s))

    def mark_cause(self, plat, kind):
        """只记「这轮被什么拦的」，不改变任何节流动件（r626）。

        用于「功能已被用户关掉」的场景：事实要留痕，但不该再要求一个
        不会执行的动作（如 needs_warmup）。
        """
        with self._lock:
            st = self._rec(str(plat))
            st["reason"] = str(kind or "")

    def _rec(self, plat):
        return self._st.setdefault(str(plat), {
            "strikes": 0, "until": 0.0, "reason": "", "needs_login": False,
            "needs_warmup": False, "ok_streak": 0})

    def allow(self, plat, now=None):
        now = time.time() if now is None else now
        with self._lock:
            if not self.enabled:
                return True, 0
            st = self._rec(plat)
            if st["until"] > now:
                return False, int(round(st["until"] - now))
            return True, 0

    def trip(self, plat, kind, now=None, retry_after=0):
        now = time.time() if now is None else now
        kind = str(kind or "ip")
        if kind == "busy":
            return 0
        with self._lock:
            st = self._rec(plat)
            if kind == "soft":
                # 软拒只要求下一轮先预热，不冷却、不计 strikes：
                # 用整家熔断去惩罚"会话没养好"会错杀已能出数的渠道。
                st["needs_warmup"] = True
                st["reason"] = "soft"
                return 0
            if kind == "login":
                st["needs_login"] = True
                st["reason"] = "login"
                st["until"] = max(st["until"], now + self.login_cooldown_s)
                return self.login_cooldown_s
            if not self.enabled:
                return 0
            st["strikes"] = min(16, st["strikes"] + 1)
            cd = min(self.cap_s, self.base_s * (2 ** (st["strikes"] - 1)))
            try:
                ra = int(retry_after or 0)
            except (TypeError, ValueError):
                ra = 0
            if ra > 0:
                # 服务端指令优先：比阶梯长就照它（哪怕超过自设封顶），
                # 比阶梯短则取长的——提前回来只会再撞一次
                cd = min(86400, max(cd, ra))
            st["until"] = now + cd
            st["reason"] = kind
            return cd

    def note_ok(self, plat, need=2):
        """连续成功 need 次才清 strikes；软拒标记单独清零。

        - strikes/冷却：连续成功才复位，避免抖动渠道反复横跳；
        - needs_warmup：成功出数本身就是"会话已养熟"的最强证据，
          立即清（否则面板会一直提示"软拒待预热"）。
        """
        with self._lock:
            st = self._rec(plat)
            st["ok_streak"] = int(st.get("ok_streak") or 0) + 1
            st["needs_warmup"] = False
            if st.get("reason") == "soft":
                st["reason"] = ""
            if st["ok_streak"] >= max(1, int(need or 2)):
                st["strikes"] = 0
                st["until"] = 0.0
                st["reason"] = ""
                st["needs_login"] = False
            return st["ok_streak"]

    def note_warmup_ok(self, plat):
        """预热真的拿到风控 cookie 才清软拒标记。

        只访问首页不算数——没下发风控 cookie 的预热，深链仍会被 444。
        """
        with self._lock:
            st = self._rec(plat)
            st["needs_warmup"] = False
            if st["reason"] == "soft":
                st["reason"] = ""

    def reset(self, plat):
        with self._lock:
            self._st[str(plat)] = {
                "strikes": 0, "until": 0.0, "reason": "",
                "needs_login": False, "needs_warmup": False,
                "ok_streak": 0}

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        out = {}
        with self._lock:
            for p in PLATFORMS:
                st = self._st.get(p) or {}
                until = float(st.get("until") or 0)
                out[p] = {
                    "state": "cooldown" if until > now else "ok",
                    "remain_s": max(0, int(round(until - now))),
                    "strikes": int(st.get("strikes") or 0),
                    "reason": str(st.get("reason") or ""),
                    "needs_login": bool(st.get("needs_login")),
                    "needs_warmup": bool(st.get("needs_warmup")),
                    "ok_streak": int(st.get("ok_streak") or 0),
                }
            for p in self._st:
                if p in out:
                    continue
                st = self._st[p]
                until = float(st.get("until") or 0)
                out[p] = {
                    "state": "cooldown" if until > now else "ok",
                    "remain_s": max(0, int(round(until - now))),
                    "strikes": int(st.get("strikes") or 0),
                    "reason": str(st.get("reason") or ""),
                    "needs_login": bool(st.get("needs_login")),
                    "needs_warmup": bool(st.get("needs_warmup")),
                    "ok_streak": int(st.get("ok_streak") or 0),
                }
        return out


class TokenBucket:
    """渠道级请求预算：最小间隔 + 每分钟上限。

    `wait_hint` 只算不睡。分钟窗口是滑动的（deque），因为站点的限流
    窗口几乎都不是整分钟对齐的，固定窗口会放过 2 倍突发。
    """

    def __init__(self, min_gap_s=0, per_minute=0):
        self._lock = threading.Lock()
        self._last = {}
        self._win = {}
        self.configure(min_gap_s, per_minute)

    def configure(self, min_gap_s=None, per_minute=None):
        with self._lock:
            if min_gap_s is not None:
                self.min_gap_s = max(0.0, float(min_gap_s))
            if per_minute is not None:
                self.per_minute = max(0, int(per_minute))

    def wait_hint(self, plat, now=None):
        now = time.time() if now is None else now
        with self._lock:
            wait = 0.0
            last = self._last.get(str(plat))
            if self.min_gap_s > 0 and last is not None:
                wait = max(wait, last + self.min_gap_s - now)
            if self.per_minute > 0:
                dq = self._win.get(str(plat)) or deque()
                while dq and now - dq[0] >= 60:
                    dq.popleft()
                if len(dq) >= self.per_minute:
                    wait = max(wait, dq[0] + 60 - now)
            return max(0.0, round(wait, 1))

    def record(self, plat, now=None):
        now = time.time() if now is None else now
        with self._lock:
            p = str(plat)
            self._last[p] = now
            dq = self._win.setdefault(p, deque())
            dq.append(now)
            while dq and now - dq[0] >= 60:
                dq.popleft()

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            out = {}
            for p in set(list(self._last) + list(PLATFORMS)):
                dq = list(self._win.get(p) or ())
                recent = sum(1 for t in dq if now - t < 60)
                last = self._last.get(p)
                out[p] = {
                    "last_ago_s": (max(0, int(round(now - last)))
                                   if last is not None else -1),
                    "per_min_used": recent,
                }
            return out


def _age_min(ts, now):
    try:
        t = time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError, TypeError):
        return None
    return max(0.0, (now - t) / 60.0)


def shadow_path_preference(paths, min_samples=5, low=0.3):
    """影子模式：只算"若启用路径偏好，会把哪条路排前"，不改变采集。

    返回 {"prefer": [(path, rate, attempts)...], "avoid": [...]}。
    - 仅比较同平台内各入口（PC/H5/API/日历）的路径成功率；
    - 样本 < min_samples 不参与（防首轮波动误判）；
    - 日历路径不参与（它本来就不是明细路径；窗历同属日历族）。
    """
    ranked = []
    for name, v in (paths or {}).items():
        v = v or {}
        n = int(v.get("attempts") or 0)
        if n < min_samples or str(name).startswith(("日历", "窗历")):
            continue
        ranked.append((str(name), float(v.get("rate") or 0.0), n))
    ranked.sort(key=lambda x: (-x[1], -x[2]))
    avoid = [x for x in ranked if x[1] < low]
    return {"prefer": ranked[:2], "avoid": avoid}


def _with_channel(hint, effect, lead):
    """分域结论后补一句渠道全貌（r630）。

    实测 qunar：国际域 48%→53%（几乎没动）而渠道整体 44%→84%（大好）。
    只给前者，读者会一直折腾国际；两句一起给才判断得出「该换域」。
    渠道级与域级等价时（非域 scope、或数字相同）不追加，避免噪音。
    """
    if not lead:
        return hint
    cb, ca = effect.get("before"), effect.get("after")
    if cb is None or ca is None:
        return hint
    dsb, dsa = effect.get("scope_before"), effect.get("scope_after")
    if cb == dsb and ca == dsa:
        return hint
    rel = ("同期渠道整体 %.0f%% → %.0f%%"
           % (cb * 100, ca * 100))
    # 只有「该域确实没跟上」时才解释「整体已可用」；域本身已达标
    # （如 tongcheng 30%→100%）时说这句会自相矛盾。
    dsa_v = dsa if dsa is not None else 0.0
    dsb_v = dsb if dsb is not None else 0.0
    if ca >= 0.7 and dsa_v < 0.7:
        rel += "（整体已可用，是这个域没跟上——可换域或先观察）"
    elif ca > cb and ca - cb > 0.1 and dsa_v - dsb_v < 0.1:
        rel += "（改善主要来自别的域）"
    return hint + "；" + rel


def effect_verdict(effect):
    """把干预前后对比翻译成一句可执行结论（供建议引擎/面板复用）。

    effect: storage.intervention_effect() 的返回。
    返回 (state, hint, severity)；无干预或样本不足时如实说"还不能判断"。

    分域口径（r619）：这次干预的 scope 是 dom/intl 时，结论必须按**该域**
    的 before/after 判。原先只读渠道级数字，实测形态是：
    国际自检后国际仍 0%，但渠道级因国内一直很好而 100% → 判「干预有效」
    → 调用方（webui）据此把「路径劣化」的 advice 改写成「恢复中」，
    用户于是不再处理一个仍然全红的域。数字难看只是表象，这里关掉的是
    「可判断 + 可干预」。
    """
    e = effect or {}
    if not e.get("has"):
        return "none", "", "ok"
    b, a = e.get("before"), e.get("after")
    # 该域口径优先。非域名 scope（重登槽位等）没有 scope_* 字段，走渠道级。
    _sc = str(e.get("scope") or "").strip().lower()
    _domain = ""
    if _sc in ("dom", "intl") and ("scope_after" in e
                                   or "scope_before" in e):
        _domain = ("国际" if _sc == "intl" else "国内")
        b, a = e.get("scope_before"), e.get("scope_after")
        _an = int(e.get("scope_after_n") or 0)
    else:
        _an = int(e.get("after_n") or 0)
    _lead = (_domain + "域：") if _domain else ""
    # 回落优先于一切：干预后先好后坏，一致性已不成立，不该被
    # "干预前无样本"或"样本不足"掩盖。
    if e.get("regressed"):
        return "regressed", ("%s干预后出现过恢复但最近一个窗口回落到 %.0f%%："
                            "一致性不成立，建议复查会话/入口"
                            % (_lead, (a or 0) * 100)), "act"
    if a is None:
        # 该域零样本时说清是「这个域还没有」，不拿渠道级的数字顶替
        return "pending", ("%s干预后还没有新样本（%s）：等下一轮采集再判断"
                           % (_lead, e.get("action") or "干预")), "wait"
    # 样本护栏：干预后只有 1-2 次就宣布"已恢复"是过度自信。
    if _an < 3:
        return "provisional", ("%s干预后仅 %d 个样本（成功率 %.0f%%）："
                               "再观察一轮再定论" % (_lead, _an, a * 100)), "wait"
    if b is None:
        return "unknown_before", ("%s干预后成功率 %.0f%%（%d 次）；干预前窗口"
                                  "无样本，无法对比" % (_lead, a * 100, _an)), "ok"
    if a >= 0.7 and a > b:
        return ("improved", _with_channel(("%s干预有效：%.0f%% → %.0f%%"
                                  % (_lead, b * 100, a * 100)),
                                 e, _lead), "ok")
    if a >= 0.7:
        return ("recovered", _with_channel(("%s干预后已回到 %.0f%%（干预前 %.0f%%）"
                                   % (_lead, a * 100, b * 100)),
                                  e, _lead), "ok")
    if a > b:
        return ("partial", _with_channel(("%s有改善但仍偏低：%.0f%% → %.0f%%，"
                                          "建议再自检一次"
                                          % (_lead, b * 100, a * 100)),
                                         e, _lead), "wait")
    return ("no_effect", _with_channel(("%s干预未见改善：%.0f%% → %.0f%%，"
                                       "换路径/重登后再试"
                                       % (_lead, b * 100, a * 100)),
                                      e, _lead), "act")


def advise(plat, ch=None, paths=None, now=None, node=None,
           quiet=None):
    """把一个渠道的现状翻译成「用户该做什么」。

    返回 {"state","action","hint","eta_s","severity"}：
      severity=ok      不用管
      severity=wait    等就行（冷却到期会自动恢复）
      severity=auto    已自动处理/可自动处理（路径劣化）
      severity=act     必须人工（重登 / 换出口 / 解封）

    `node` 是 path_stats 的平台级节点（query_* / last_ok_at）。有它时
    用查询口径判健康；没有再退回路径口径（兼容旧调用）。
    """
    ch = ch or {}
    paths = paths or {}
    node = node or {}
    now = time.time() if now is None else now
    if ch.get("needs_warmup") and ch.get("state") != "cooldown":
        return {"state": "soft_reject", "action": "probe", "severity": "auto",
                "hint": "上一轮被软拒（202 空体/444 关连接，不是真无票）："
                        "本轮已安排先预热再查；若连续出现，点「自检」看路径",
                "eta_s": 0}
    if ch.get("needs_login"):
        return {"state": "login", "action": "relogin", "severity": "act",
                "hint": "登录态失效：点「去验证」用采集同一会话过验证，"
                        "关窗即落库，别用死 cookie 继续打",
                "eta_s": 0}
    if ch.get("state") == "cooldown":
        left = int(ch.get("remain_s") or 0)
        if (ch.get("reason") or "") in ("ip", "captcha"):
            hint = ("冷却中（%s）：点「去验证」在采集同一会话里过验证，"
                    "或等倒计时自动恢复" % ch.get("reason"))
        else:
            hint = "冷却中：到点自动恢复，不建议手动解除（会再撞一次）"
        return {"state": "cooldown", "action": "wait", "severity": "wait",
                "hint": hint, "eta_s": left}
    attempts = sum(int((v or {}).get("attempts") or 0)
                   for v in paths.values())
    # 优先用「在用口径」（r406）：退役通路（如被「窗历」取代的旧「日历」）
    # 留在窗口里的必败历史不该把健康渠道判成劣化。`query_attempts_live`
    # 只在确实识别出退役路径时才有值，否则回落到原口径，行为不变。
    _qa_live = node.get("query_attempts_live")
    if _qa_live is not None and int(_qa_live) > 0:
        q_attempts = int(_qa_live)
        _r_live = node.get("query_rate_live")
        q_ok = (int(round(float(_r_live) * q_attempts))
                if _r_live is not None else int(node.get("query_ok") or 0))
    else:
        q_attempts = int(node.get("query_attempts") or 0) or sum(
            int((v or {}).get("query_attempts") or 0) for v in paths.values())
        q_ok = int(node.get("query_ok") or 0) or sum(
            int((v or {}).get("query_ok") or 0) for v in paths.values())
    if not attempts and not q_attempts:
        # 「近 24h 无样本」有两种原因（r516，对应用户反馈「登录配好了但渠道
        # 全红」）：① 刚启动、还没轮到这一轮；② **采集根本没在跑**。
        # 只看窗口内计数分不出这两者，一律说「先跑一轮再判断」会让第二种
        # 情形的人一直进行无效等待——而真正要看的是采集进程/调度。
        # 用该渠道最近一条样本的时间兜底：存在且已很旧，就是停了。
        _last = str(node.get("last_seen_at") or node.get("last_at")
                    or node.get("last_ok_at") or "")
        _age_h = 0.0
        if _last:
            _m = _age_min(_last, now)
            _age_h = (_m or 0.0) / 60.0
        if _last and _age_h >= 6:
            return {"state": "stalled", "action": "scan", "severity": "act",
                    "hint": "该渠道已 %.0f 小时没有采集样本（最后一条 %s）——"
                            "不是「先跑一轮」，而是采集没在跑：检查监控进程与"
                            "扫描周期是否在运行，登录状态本身无需重做"
                            % (_age_h, _last[5:16]),
                    "eta_s": 0}
        return {"state": "unknown", "action": "scan", "severity": "ok",
                "hint": "近 24h 无样本：先跑一轮再判断", "eta_s": 0}
    # 域级劣化优先：国内好、国际被登录墙拦住时，不应该把整家渠道
    # 判成"路径劣化"（用户会误以为国内也不能用）。
    scopes = node.get("scopes") or {}
    # 日历族（日历/窗历）是同一类数据的不同通路：窗历（r384）上线后
    # 旧「日历」恒 444，此时不该一边显示窗历成功、一边喊日历劣化。
    # 但抑制只对「被替代的那条」成立——不能让窗历自己的低成功率也
    # 被它自己掩掉（那会把 2/50 的窗历报成正常）。族表与复发账共用
    # 同一份定义，避免两处各写一遍后漂移。
    _CAL_FAMILY = CAL_PATH_FAMILY

    def _cal_family_ok(_sp, skip_name):
        for _n2, _v2 in (_sp or {}).items():
            if str(_n2) == str(skip_name):
                continue
            if not str(_n2).startswith(_CAL_FAMILY):
                continue
            v = _v2 or {}
            if int(v.get("calendar_ok") or 0) <= 0:
                continue
            # 替代通路自己也得像样：1 次成功不足以判"替代到位"
            _r2 = v.get("rate_excl_empty", v.get("rate"))
            if _r2 is not None and float(_r2 or 0) >= 0.5:
                return True
        return False

    for _sk, _sv in scopes.items():
        _sp = (_sv or {}).get("paths") or {}
        for _name, _v in _sp.items():
            # 提示里给人看的名字：账本键名对 App 渠道是英文 id
            # （app-list/android-runtime），原样入句读者不知道卡在哪一步。
            _shown = path_cn(_name)
            _n = int((_v or {}).get("attempts") or 0)
            _valid = max(0, _n - int((_v or {}).get("empty") or 0)
                         - int((_v or {}).get("unsupported") or 0))
            if _valid < 3:
                continue
            # 这条日历族路径已被同域另一条健康通路替代：它的历史
            # 失败不再是"待修的路"
            if (str(_name).startswith(_CAL_FAMILY)
                    and _cal_family_ok(_sp, _name)):
                continue
            # 这一域的失败如果主要是「登录墙」（login 拦截≥10 且占该路尝试
            # 半数以上），根因是会话而不是限流/路径选择：再观察、再降频、
            # 再换路径都没用，只有重登能救。实测去哪儿国际 H5 24h 内
            # 18 次 login / 0 成功，advise 却给「观察一轮」，白等 9 小时。
            # 必须放在「陈旧样本不判」之前：那条规则防的是「这条路没在用」，
            # 而 login 拦截恰恰证明它一直在被尝试（只是进不去）。
            #
            # **但登录失败占多数还不够**：得确认这条路本身几乎不出数。
            # 实测同一通路（国际 H5）24h 内 BKK 3/22 全被 login 挡，而
            # 同会话的 HAK 27/29、LHR 9/12 正常——非 BKK 记录 44/50 成功。
            # 那种情形是「单条航线被拦」，重登解决不了，让用户去重登
            # 等于把人引去做无效操作。判据：本路 ok+calendar 占比 < 20%。
            _login_n = int((_v or {}).get("login") or 0)
            _okish = (int((_v or {}).get("ok") or 0)
                      + int((_v or {}).get("calendar") or 0))
            # 判据优先用**最近一次成功之后**的登录墙连击数（r479）：
            # 24h 窗口是全量的，重登后旧行不会消失，只用「登录数/总数」
            # 会让用户刚登完又被要求再登一次（实测重登后 3 次全成功，
            # 仍判 login）。连击数一出数就清零，直接回答「现在通不通」。
            # 缺该字段（旧载荷/单测）时退回总登录数，行为不变。
            _ln_run = int((_v or {}).get("login_since_ok", -1))
            if _ln_run < 0:
                _ln_run = _login_n
            if _ln_run >= 8 and _okish * 5 <= _n:
                _dom = "国内" if _sk == "dom" else "国际"
                # scope/path 回传给界面选登录端：飞猪 PC 与 H5 是两套
                # cookie，「国际 H5 被拦」必须去登 H5；只按厂商开窗
                # （verify）打开的是 PC 窗，登完 H5 依然进不去。
                return {"state": "login", "action": "relogin",
                        "severity": "act", "scope": _sk, "path": _name,
                        "hint": "%s %s 近 24h 被登录墙拦 %d/%d 次、仅 %d 次"
                                "出数——根因是会话失效，限流与换路都无效；"
                                "点「去登录」重存该渠道会话"
                                % (_dom, _shown, _login_n, _n, _okish),
                        "eta_s": 0}
            # 登录拦截占多数、但这条路其他航线仍在正常出数 → 会话是好的，
            # 是航线级拦截。不要提重登（无效），如实说明并给可行动作。
            if _ln_run >= 8:
                _dom = "国内" if _sk == "dom" else "国际"
                return {"state": "path_degraded", "action": "probe",
                        "severity": "wait",
                        "hint": "%s %s 有 %d/%d 次被登录墙拦，但同一会话其他"
                                "航线仍在出数（%d 次）——会话是好的，属航线级"
                                "拦截；先点「自检」核实，别急着重登"
                                % (_dom, _shown, _login_n, _n, _okish),
                        "eta_s": 0}
            # r388：只对"最近真的在试"的路下结论。某条兜底路径可能几小时
            # 没被用到（主路径一直成功就不走它），拿半天前的旧样本报
            # 「路径劣化」等于催用户去修一条根本没在用的路。
            _age = _age_min((_v or {}).get("last_at"), now)
            if _age is not None and _age > 180:
                continue
            _raw = _v.get("rate_excl_empty", _v.get("rate"))
            if _raw is None:
                continue
            if float(_raw or 0) < 0.3:
                _dom = "国内" if _sk == "dom" else "国际"
                return {"state": "path_degraded", "action": "route",
                        "severity": "auto",
                        "hint": "%s %s 近 24h 有效率 %.0f%%（%d 次有效）"
                                "——已在日志记录路径偏好（影子模式，暂不改变"
                                "采集顺序）；可点「自检」验证这条域的路"
                                % (_dom, _shown, float(_raw) * 100, _valid),
                        "eta_s": 0}
    bad = None
    for name, v in paths.items():
        v = v or {}
        n = int(v.get("attempts") or 0)
        if n < 5:
            continue
        if (str(name).startswith(_CAL_FAMILY)
                and _cal_family_ok(paths, name)):
            continue
        # r388：陈旧样本不判劣化（见上）
        _age2 = _age_min(v.get("last_at"), now)
        if _age2 is not None and _age2 > 180:
            continue
        # 优先用"排除售罄空结果"的比率：真无票不等于路径坏了。
        # None = 有效样本为 0，不参与判定（既非 0% 也非 100%）。
        _raw = v.get("rate_excl_empty", v.get("rate"))
        if _raw is None:
            continue
        # 有效样本护栏：分母里至少 3 次"非售罄"尝试才下路径结论，
        # 否则 1 次拦截 + 4 次售罄会把一条正常的路判成劣化。
        _valid = max(0, n - int(v.get("empty") or 0)
                     - int(v.get("unsupported") or 0))
        if _valid < 3:
            continue
        _r = float(_raw or 0)
        if _r < 0.3 and (bad is None or n > bad[1]):
            bad = (name, n, _r, _valid)
    if bad:
        return {"state": "path_degraded", "action": "route",
                "severity": "auto",
                "hint": "%s 近 24h 有效率 %.0f%%（%d 次有效 / %d 次尝试）"
                        "——已在日志记录路径偏好（影子模式，暂不改变采集"
                        "顺序）；可点「自检」验证这条路"
                        % (bad[0], bad[2] * 100, bad[3], bad[1]),
                "eta_s": 0}
    ok_n = sum(int((v or {}).get("ok") or 0) for v in paths.values())
    rate = (q_ok / q_attempts if q_attempts
            else (ok_n / attempts if attempts else 0.0))
    det = int(node.get("detail_ok") or 0) or sum(
        int((v or {}).get("detail_ok") or 0) for v in paths.values())
    cal = int(node.get("calendar_ok") or 0) or sum(
        int((v or {}).get("calendar_ok") or 0) for v in paths.values())
    q_det = int(node.get("query_detail_ok") or 0)
    q_cal = int(node.get("query_calendar_only") or 0)
    if q_attempts and q_det == 0 and q_cal > 0:
        return {"state": "calendar_only", "action": "probe",
                "severity": "wait",
                "hint": "近 24h 只拿到日历价（%d 次查询），没有航班明细——"
                        "明细路径可能被拦或改版；点「自检」看具体路径"
                        % q_cal,
                "eta_s": 0}
    if attempts and det == 0 and cal > 0:
        return {"state": "calendar_only", "action": "probe",
                "severity": "wait",
                "hint": "近 24h 只拿到日历价（%d 次），没有航班明细——"
                        "明细路径可能被拦或改版；点「自检」看具体路径"
                        % cal,
                "eta_s": 0}
    if rate < 0.5:
        return {"state": "degraded", "action": "watch", "severity": "wait",
                "hint": "近 24h 成功率 %.0f%%，观察一轮；连续两轮再干预"
                        % (rate * 100), "eta_s": 0}
    # 新鲜度：成功率好看但数据很旧 = 看起来正常其实没在采。
    # 只看「最近一次成功」，不看最近一次尝试——连续失败会刷新尝试时间，
    # 用尝试时间会把"一直没成功"误报成"刚刚更新"。
    ages = []
    if node.get("last_ok_at"):
        a = _age_min(node.get("last_ok_at"), now)
        if a is not None:
            ages.append(a)
    for v in paths.values():
        v = v or {}
        t = v.get("last_ok_at") if "last_ok_at" in v else v.get("last_at")
        a = _age_min(t, now)
        if a is not None:
            ages.append(a)
    if ages and min(ages) > 120:
        # 静默窗内也照样建议「立即扫描」：手动入口注入的是
        # sweep(force=True)，实测能绕过窗（05:28 手动触发，五个渠道各写
        # 3 条新行）。窗内多一句说明，让人知道不点的话要等到几点。
        if isinstance(quiet, dict) and quiet.get("active"):
            return {"state": "stale", "action": "probe", "severity": "wait",
                    "hint": "最近一次成功已 %d 分钟；当前在夜间静默窗"
                            "（%s–%s），点「立即扫描」可立即采，否则窗口"
                            "结束后自动补采"
                            % (int(min(ages)), quiet.get("start") or "?",
                               quiet.get("end") or "?"), "eta_s": 0}
        return {"state": "stale", "action": "probe", "severity": "wait",
                "hint": "最近一次成功已 %d 分钟，点「立即扫描」或等下一轮"
                        % int(min(ages)), "eta_s": 0}
    # 口径要写明：这里是**查询口径**（一次查询有一条路径出数就算成功），
    # 与健康面板的轮次口径会不同（同程 query 76% vs 轮次 13% 曾让人
    # 以为两个面板互相矛盾）。有退役通路时一并说明，否则用户看到
    # 「76%」不知道旧的坏通路已经被剔除。
    _retired = [n for n in (node.get("retired_paths") or [])]
    _live = node.get("query_rate_live")
    _tail = ""
    if _retired:
        _tail = "；已排除退役通路 %s" % "、".join(str(x) for x in _retired)
        if _live is not None:
            _tail += "（在用 %.0f%%）" % (float(_live) * 100)
    return {"state": "ok", "action": "none", "severity": "ok",
            "hint": "近 24h 查询成功率 %.0f%%（明细 %d / 日历 %d）%s，无需操作"
                    % (rate * 100, det, cal, _tail),
            "eta_s": 0}


class Pacing:
    """一轮扫描共享的节流上下文：静默窗 + 分层 TTL + 熔断 + 令牌桶。

    实例挂在 `rt["pacing"]`，与进程同寿命——熔断状态跨轮保留，热重载
    只换阈值不丢已验证过的"这家现在不能碰"。
    """

    def __init__(self, cfg=None, clock=time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self.cfg = parse_pacing(cfg or {})
        self._breaker = ChannelBreaker(
            self.cfg["breaker_base_s"], self.cfg["breaker_cap_s"],
            self.cfg["breaker_enabled"], self.cfg["login_cooldown_s"])
        self._bucket = TokenBucket(self.cfg["min_gap_s"],
                                   self.cfg["per_minute"])
        self._last = {}
        self._health = {}
        # 最近一次失败归类（熔断关闭时也要能说清被什么拦的）
        self._cause = {}
        self._plan = []
        self._round = {"at": "", "fast": 0, "slow": 0, "skip": 0,
                       "trips": [], "busy": [],
                       "sent": 0, "paced": 0, "sent_by": {}, "paced_by": {}}

    # ---------- 配置热更新 ----------
    def refresh(self, cfg):
        new = parse_pacing(cfg or {})
        with self._lock:
            self.cfg = new
        # 锁外下发：Pacing→Breaker 的嵌套加锁在 refresh 与 observe 之间
        # 构成反向顺序，虽当前无环，但保持「同一时刻只持一把锁」最省心
        self._breaker.configure(
            new["breaker_base_s"], new["breaker_cap_s"],
            new["breaker_enabled"], new["login_cooldown_s"])
        self._bucket.configure(new["min_gap_s"], new["per_minute"])
        return new

    # ---------- 1 区：静默窗 ----------
    def seconds_until_quiet_end(self, now=None):
        """距静默窗结束还有多少秒；不在窗内/未配置返回 None。

        供调度把下一轮重排到窗口刚结束（r391）：否则跳过轮按 24–37 分钟
        接力，窗口结束后最坏再陈旧半小时。
        """
        now = self._clock() if now is None else now
        if not self.quiet_now(now):
            return None
        _s = parse_hhmm(self.cfg["scan_quiet_start"])
        _e = parse_hhmm(self.cfg["scan_quiet_end"])
        if _s is None or _e is None:
            return None
        lt = time.localtime(now)
        cur = lt.tm_hour * 60 + lt.tm_min
        # 窗口结束时刻在「今天」还是「明天」：_e > _s 时同一天（cur<_e
        # 才在窗内），否则跨午夜窗且 cur 已过午夜 → 结束在今天。
        if _e > _s:
            left = _e - cur
        else:
            # 跨午夜：cur >= _s 说明还在午夜前（结束在明天），否则已过
            # 午夜（结束在今天）
            left = ((24 * 60 - cur) + _e) if cur >= _s else (_e - cur)
        return float(max(0, left) * 60)

    def quiet_now(self, now=None):
        now = self._clock() if now is None else now
        lt = time.localtime(now)
        return in_window(lt.tm_hour * 60 + lt.tm_min,
                         parse_hhmm(self.cfg["scan_quiet_start"]),
                         parse_hhmm(self.cfg["scan_quiet_end"]))

    # ---------- 2 区：熔断 ----------
    def allow(self, plat, now=None):
        return self._breaker.allow(plat, now)

    def trip(self, plat, kind, now=None, retry_after=0):
        return self._breaker.trip(plat, kind, now, retry_after)

    def reset(self, plat):
        self._breaker.reset(plat)

    def note_ok(self, plat, need=2):
        return self._breaker.note_ok(plat, need)

    def note_warmup_ok(self, plat):
        self._breaker.note_warmup_ok(plat)

    # ---------- 5 区：令牌桶 ----------
    def wait_hint(self, plat, now=None):
        return self._bucket.wait_hint(plat, now)

    def record(self, plat, now=None):
        self._bucket.record(plat, now)

    # ---------- 3 区：分层 TTL ----------
    def set_health(self, plat, rate, attempts):
        """按近 24h 成功率自动加罚（成功率保护，不是熔断）。

        熔断只管"对方明确拒绝"；持续解析失败/空结果不会触发它，却同样
        烧请求。这里按账本自动拉长该渠道的 TTL：0.4 以下 ×3、0.7 以下
        ×1.5，样本 <5 次不判（避免首轮波动就误降频）。
        """
        try:
            r = float(rate or 0)
            n = int(attempts or 0)
        except (TypeError, ValueError):
            return
        # 用户关掉「成功率保护」时：仍然记账（界面要显示 rate/attempts），
        # 但不产生任何降频。宁可多打几次，也不接受自动拉长 TTL。
        _pen_on = bool(self.cfg.get("health_penalty_enabled", True))
        if not _pen_on:
            with self._lock:
                self._health[str(plat)] = {"rate": round(r, 3),
                                           "attempts": n, "penalty": 1.0,
                                           "disabled": True}
            return
        if n < int(self.cfg.get("health_min_samples", 5)):
            penalty = 1.0
        elif r >= float(self.cfg.get("health_ok_ratio", 0.7)):
            penalty = 1.0
        elif r >= float(self.cfg.get("health_slow_ratio", 0.4)):
            penalty = float(self.cfg.get("health_slow_factor", 1.5))
        else:
            penalty = float(self.cfg.get("health_slowest_factor", 3.0))
        with self._lock:
            self._health[str(plat)] = {"rate": round(r, 3), "attempts": n,
                                       "penalty": penalty}

    def note_fetch(self, plat, key, price, ok=True):
        """只有"真拿到价"才刷新 TTL；失败/空结果不刷新，下一轮照常重试
        （否则一次软失败会让该查询静默两小时）。"""
        if not ok:
            return
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        if p <= 0:
            return
        with self._lock:
            self._last[(str(plat),) + tuple(key)] = (self._clock(), p)

    def seed_fetch(self, plat, key, price, at_ts):
        """用库里的最近一次真实明细续上 TTL（重启不重新全量打站）。

        只升不降：同一键已有更新的内存记录时保留内存值。时间来自库的
        fetched_at，不是"现在"——否则重启会把两天前的数据当刚采过。
        """
        try:
            p = float(price)
            ts = float(at_ts or 0)
        except (TypeError, ValueError):
            return False
        if p <= 0 or ts <= 0:
            return False
        k = (str(plat),) + tuple(key)
        with self._lock:
            old = self._last.get(k)
            if old and float(old[0]) >= ts:
                return False
            self._last[k] = (ts, p)
        return True

    def plan_query(self, plat, key, threshold=0, days_ahead=None):
        """返回 (tier, 原因)。tier ∈ fast/slow/skip。

        `days_ahead` 是出发日距今天数：临期行程价格变化快，给一个更短的
        TTL；远期只做低频基线。它只缩短 TTL，不会让本该跳过的查询变快。
        """
        now = self._clock()
        with self._lock:
            last = self._last.get((str(plat),) + tuple(key))
            near_ratio = float(self.cfg["near_ratio"])
            fast_ttl = int(self.cfg["fast_ttl_min"])
            slow_ttl = int(self.cfg["slow_ttl_min"])
            pen = float((self._health.get(str(plat)) or {}).get("penalty")
                        or 1.0)
        # 成功率保护：账本差就自动拉长 TTL，而不是等它撞出 429 再熔断
        fast_ttl = max(5, int(round(fast_ttl * pen)))
        slow_ttl = max(5, int(round(slow_ttl * pen)))
        # 临期加密：3 天内快层减半（不低于 5 分钟），30 天外慢层翻倍。
        # 只改本键 TTL，不改变健康惩罚的方向（penalty 仍然只加不减）。
        try:
            _d = int(days_ahead) if days_ahead is not None else None
        except (TypeError, ValueError):
            _d = None
        if _d is not None and _d >= 0:
            if _d <= int(self.cfg.get("near_days") or 3):
                fast_ttl = max(5, int(round(fast_ttl / 2.0)))
            elif _d >= 30:
                slow_ttl = min(1440, int(round(slow_ttl * 2.0)))
        if not last:
            return "fast", "无历史基线"
        ts, price = last
        age = max(0.0, (now - ts) / 60.0)
        floor = int((self.cfg.get("cadence") or {}).get(str(plat), 0) or 0)
        if floor and age < floor:
            # 渠道节奏是硬地板：这家慢，就别用全局 30 分钟的节奏催它
            return "skip", "渠道节奏 %.0f/%d 分钟" % (age, floor)
        th = float(threshold or 0)
        near = True
        if th > 0 and price > 0:
            near = abs(price - th) / th <= near_ratio
        tier = tier_of(age, near, fast_ttl, slow_ttl)
        if tier == "skip":
            ttl = fast_ttl if near else slow_ttl
            return tier, "TTL 内（%.0f/%.0f 分钟）" % (age, ttl)
        return tier, ("贴近阈值" if near else "远离阈值") + "，%.0f 分钟未采" % age

    # ---------- 观测 ----------
    def begin_round(self, at=""):
        with self._lock:
            self._round = {"at": at, "fast": 0, "slow": 0, "skip": 0,
                           "trips": [], "busy": [],
                           # 请求预算：计划数 vs 实际发出，以及按渠道
                           # 计的实际发送/被预算挡下的次数
                           "sent": 0, "paced": 0, "sent_by": {},
                           "paced_by": {}, "ok_by": {}, "soft_by": {}}
            self._plan = []

    def note_plan(self, plat, key, tier, why):
        with self._lock:
            self._round[tier] = int(self._round.get(tier) or 0) + 1
            if len(self._plan) < 200:
                self._plan.append({
                    "plat": plat, "key": "-".join(str(x) for x in key),
                    "tier": tier, "why": why})

    def note_sent(self, plat):
        """真正发出一次渠道请求（不含预热；预热另计）。"""
        with self._lock:
            self._round["sent"] = int(self._round.get("sent") or 0) + 1
            _b = self._round.setdefault("sent_by", {})
            _b[plat] = int(_b.get(plat) or 0) + 1

    def note_result(self, plat, ok=False, soft=False):
        """记录本轮该渠道是否真的出数（一轮一渠道只记最终结果）。

        这是"本轮成功率"的直接口径：有数渠道数 / 实发渠道数。
        与路径账不同，它不受一次查询多路径影响。
        """
        with self._lock:
            if ok:
                _b = self._round.setdefault("ok_by", {})
                _b[plat] = int(_b.get(plat) or 0) + 1
            elif soft:
                _b = self._round.setdefault("soft_by", {})
                _b[plat] = int(_b.get(plat) or 0) + 1

    def note_paced(self, plat, why=""):
        """因 TTL/熔断/预算等待超限而主动没发。"""
        with self._lock:
            self._round["paced"] = int(self._round.get("paced") or 0) + 1
            _b = self._round.setdefault("paced_by", {})
            _b[plat] = int(_b.get(plat) or 0) + 1

    def note_busy(self, plat):
        with self._lock:
            if plat not in self._round["busy"]:
                self._round["busy"].append(plat)

    def note_trip(self, plat, kind, cooldown_s, retry_after=0):
        with self._lock:
            self._round["trips"].append(
                {"plat": plat, "kind": kind, "cooldown_s": int(cooldown_s),
                 "retry_after": int(retry_after or 0)})

    def observe(self, plat, statuses, note="", retry_after=0):
        """一次采集落地后调用：真拒绝→熔断；拿到数据→复位。

        `retry_after` 来自响应头（秒）。有它就以它为准，没有才用自算阶梯。
        返回 (kind, cooldown_s)；kind 空串表示"不算拒绝"。

        熔断开关关闭时（r625）：分类照做（`cause` 仍记在通道状态里供界面
        显示「这次是被什么拦的」），但**不返回 kind**——调用方拿 kind 当
        「已熔断」的信号（写 auto_trip 台账、打「命中…熔断 Ns」、自动弹窗）。
        原实现在此只让 trip() 返回 0，kind 照旧返回，于是关掉开关后界面仍
        宣称「已熔断」、账本仍写一条自动干预 —— 开关看起来生效了，实际没有。
        """
        kind = classify_failure(statuses, note)
        if not kind:
            if any(str(s) == "ok" or str(s) == "calendar"
                   for s in (statuses or [])):
                self.reset(plat)
            return "", 0
        if not self.cfg["breaker_enabled"] and kind not in ("soft", "login"):
            # 未熔断，但把归因留在 Pacing 上（可见性不因开关而消失）：
            # 面板仍能说「这次是被验证码拦的」，只是不再宣称已熔断。
            with self._lock:
                self._cause[str(plat)] = kind
            return "", 0
        if kind == "soft" and not self.cfg.get("warmup_enabled"):
            # 预热开关关闭（r626）：不置 needs_warmup。那个标志只有
            # note_warmup_ok()（预热成功）才会清，而预热被关掉就永远不执行
            # ——标记会**永久挂着**；等用户哪天重开预热，一个几小时前的软拒
            # 会立刻触发一次"强制预热"。事实照旧留痕（reason / _cause），
            # 面板仍能说「这轮是软拒」，只是不再要求一个被关掉的动作。
            # 不调 trip()：它的 soft 分支会置 needs_warmup，而预热被关掉
            # 之后没有任何代码会清它。这里只留归因。
            self._breaker.mark_cause(str(plat), "soft")
            with self._lock:
                self._cause[str(plat)] = "soft"
            return "soft", 0
        # 软拒不清 needs_warmup：预热成功（拿到风控 cookie）后由
        # note_warmup_ok() 清；否则下一轮继续先预热。
        cd = self.trip(plat, kind, retry_after=retry_after)
        self.note_trip(plat, kind, cd, retry_after)
        return kind, cd

    def snapshot(self, now=None):
        now = self._clock() if now is None else now
        lt = time.localtime(now)
        start = parse_hhmm(self.cfg["scan_quiet_start"])
        end = parse_hhmm(self.cfg["scan_quiet_end"])
        with self._lock:
            rnd = dict(self._round)
            plan = list(self._plan)
            cfg = dict(self.cfg)
        with self._lock:
            _sent = sorted((rnd.get("sent_by") or {}).keys())
            _ok = sorted((rnd.get("ok_by") or {}).keys())
            _soft = sorted((rnd.get("soft_by") or {}).keys())
        channels = self._breaker.snapshot(now)
        with self._lock:
            health = {k: dict(v) for k, v in self._health.items()}
            cause = dict(self._cause)
        # 熔断关闭时的归因（r625）：未熔断不等于没被拦。把它挂到通道上，
        # 界面才能说「这轮被验证码拦了，熔断已关」而不是一片正常。
        for p, k in cause.items():
            if p in channels and not channels[p].get("reason"):
                channels[p]["blocked_but_open"] = k
        for p, b in self._bucket.snapshot(now).items():
            if p in channels:
                channels[p]["bucket"] = b
        for p, h in health.items():
            if p in channels:
                channels[p]["health"] = h
        return {
            "cfg": cfg,
            "quiet": {
                "start": cfg["scan_quiet_start"],
                "end": cfg["scan_quiet_end"],
                "active": in_window(lt.tm_hour * 60 + lt.tm_min, start, end),
            },
            "channels": channels,
            "bucket": self._bucket.snapshot(now),
            "last_round": rnd,
            "coverage": {
                "sent": _sent, "ok": _ok, "soft": _soft,
                # r388：本轮没有任何实发时 ratio=None（不是 0%）——
                # 0% 会让「刚重启/静默窗跳过」看起来像"全军覆没"。
                "ratio": (round(len(_ok) / len(_sent), 3) if _sent
                          else None),
            },
            "plan": plan,
        }
