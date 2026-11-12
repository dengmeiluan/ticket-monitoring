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
import warnings

from .models import CAL_PATH_FAMILY
from collections import deque
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

# 浏览器渠道与 App 渠道都来自零依赖的 core/channels.py（曾在此另写一份，
# 加渠道必然漏改；r813 起直接用别名，不再手抄）。
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, path_cn  # noqa: E402

# 策略参数的**唯一求值入口**（r1063 T7）。链路闸门必须在这里现读，否则
# `crawler.strategy_overrides` 里的 `渠道/维度/链路` 覆盖配了不生效——
# 那是本仓库列为头号缺陷的一类问题。模块级导入不成环：strategy_params
# 只依赖 channels 与 strategy_contract，后者不反向依赖 pacing。
from core import strategy_params as sp  # noqa: E402

# 策略开关（`<sid>.enabled`）的读法在参数层（`sp.switch_on`，r1063 fix-wave 2）：
# 读点跨模块（节流/熔断在这里，统一闸门在两个采集器基类），私有名 import 会
# 把「私有」当装饰。这里只留 import，读法本身不在这里再抄一份。
from core.strategy_params import switch_on  # noqa: E402

# 布尔词表只有**一份**（参数层 `switch_on()` 与本文件的 `_path_enabled()` 共用
# 同一批词）：绑别名，不是第二份抄本——抄两份迟早分叉，而 r519 那三类「界面
# 显示已关闭、后端照旧执行」正是从「两处各自理解 false」开始的。
_TRUE_WORDS = sp.TRUE_WORDS
_FALSE_WORDS = sp.FALSE_WORDS

PLATFORMS = BROWSER_CHANNELS

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

# 失败归类关键词：按"谁的问题"分桶，顺序即优先级。
# 403/429 必须按「独立数字」匹配——路径详情里带价格（如 ￥1403）时，
# 裸子串会把正常出价当成限流信号，熔断一个健康的渠道。
_IP_CODE_RE = re.compile(r"\b(?:403|429)\b")
_IP_MARKS = ("风控", "限流", "179991", "ip封", "ip 封")
_CAPTCHA_MARKS = ("验证码", "滑块", "人机验证", "访问验证", "安全验证",
                  "challenge", "captcha")
_LOGIN_MARKS = ("请登录", "未登录", "需登录", "登录失效", "会话失效")
# **硬风控标记**（2026-11-06）：这些不是"解个验证码就过去"的挑战，而是
# 服务端对该设备/账号的限制。实测：携程 50003「环境存在风险」、飞猪
# 「账号风险检测 / 需实名核验」、阿里 `ContainerActivity` 白屏。
# 对它们按小时重试**本身就在加重风险分**，所以单独给长时间冷却。
_HARD_BLOCK_MARKS = ("安全容器", "限制登录", "已被限制", "实名核验",
                     "账号风险", "行为异常", "环境存在风险", "baxia",
                     "ContainerActivity", "无线安全")
# 软拒：边缘节点/会话层没有正面拒绝，但也没给业务响应。它不是"真无票"，
# 也不该按 IP 限流熔断——正确动作是下一轮先养会话再查。
_SOFT_MARKS = ("软拒", "444", "202 空", "202空")

def round_backoff_minutes(interval_minutes, trips=0, blocked=0,
                           cap_min=240):
    """本轮受阻后，下一轮该**额外延后**多少分钟（纯函数）。

    为什么需要（2026-11-06）：`interval_minutes` 是固定节奏（默认 30 分钟），
    不管上一轮是被风控拦了 5 家还是全绿，下一轮照常半小时后再来。
    环境已经不友好时，这种"照常节奏"正是风险继续累积的来源。

    规则（可预测、有界）：
      * 本轮完全顺利（trips=0 且 blocked=0）→ 0，立刻回到正常节奏；
      * 有 1–2 次受阻 → 延后一个正常间隔（等于把节奏减半）；
      * ≥3 次受阻 → 延后两个正常间隔；
      * 统一封顶 `cap_min`（默认 240 分钟），不让一次坏运气把监控冻住。

    `trips` 是本轮熔断次数，`blocked` 是处于硬风控/限流冷却的渠道数。
    纯函数：不读时钟、不碰全局，调用方决定何时用它。
    """
    try:
        iv = max(0, int(interval_minutes or 0))
        n = max(0, int(trips or 0)) + max(0, int(blocked or 0))
    except (TypeError, ValueError):
        return 0
    if n <= 0 or iv <= 0:
        return 0
    extra = iv if n < 3 else iv * 2
    return int(min(max(0, int(cap_min or 0) or 240), extra))


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
    # r1592：反复命中登录墙时的**封顶**（900→1800→…→此值）。
    # 偶发一次 15 分钟就回来；反复撞则逐步冷到 4 小时，
    # 避免"每 15 分钟撞一次 × App+浏览器两个端"把账号撞进风控。
    "login_cooldown_max_s": 14400,
    # 硬风控（安全容器/限制登录/实名核验）的冷却。默认 6 小时：
    # 这类拦截按小时重试会加重风险分，宁可停久一点等它自然衰减。
    "challenge_cooldown_s": 21600,
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


# 策略开关（`<sid>.enabled`）的**读法本身**在参数层：`sp.switch_on(pid,
# *, plat=…, dim=…, path=…)`（r1063 fix-wave 2 从这里的 `_strat_on()` 搬过去）。
# 为什么搬：消费方跨模块（本文件的节奏/限速/熔断，与两个采集器基类的统一
# 闸门），`from core.pacing import _strat_on` 这种私有名 import 是把「私有」
# 当装饰；而契约的可开启轴认的正是「pid 交给一个能走到 `resolve(` 的函数」。
# 三条边界没有变，只是跟着函数搬走了：默认 True / 读不懂 fail-open 留痕 /
# 每次决策现读、绝不缓存成实例属性。
#
# 这一族读点仍在**决策点**上（节奏/限速/熔断/静默/并发）；另一族在
# `core/policy.py`（倍率/停手/风险姿态）。审计逐条核 pid 字面量。

# 同一个坏值只喊一次：链路闸门是每请求必经的路径，逐次告警会刷爆日志。
# `switch_on()` 搬走时带走了它自己的去重集合（`strategy_params._SWITCH_WARNED`），
# 这一份留给 `_path_enabled()`：它的告警词不同（「已按启用处理，要停用请写
# false」），合并成一条反而分不清是哪个键写错了。
_WARNED: set = set()


def _warn_once(tag, msg):
    """读不懂的配置值留痕（同一个值只喊一次）。

    为什么不能只是「按启用处理」了事：拼错的 `flase` 会让用户以为通路
    已经停了，而它照常跑——「配了不生效」最难查的一类。
    """
    key = repr(tag)
    if key in _WARNED:
        return
    _WARNED.add(key)
    warnings.warn(msg, RuntimeWarning, stacklevel=3)


def _degraded_snapshot() -> dict:
    """能力降级读数（r1063 T60）。账本坏了就当没有，不影响排期。"""
    try:
        from core import degraded as _dg
        return _dg.snapshot()
    except Exception:
        return {}


def parse_pacing(cfg):
    """把 config.yaml 的 schedule / crawler.rate / crawler.breaker 归一成
    扁平字典；非法值回默认并钳位（宁缺勿错：坏配置不该让监控整轮停摆）。"""
    cfg = cfg or {}
    sc = cfg.get("schedule") or {}
    crw = cfg.get("crawler") or {}
    rate = crw.get("rate") or {}
    brk = crw.get("breaker") or {}

    out = dict(DEFAULTS)
    # 静默窗策略关掉 = 不静默（`quiet_window.enabled=False`）。关掉时把起止清空：
    # `quiet_now()`/`in_window()` 见到空串就当「不在窗内」，于是整条链路（含
    # 调度重排 `seconds_until_quiet_end`）一次都不用改判据——一处开关收口。
    _quiet_on = switch_on("quiet_window.enabled")
    out["scan_quiet_start"] = (
        str(sc.get("scan_quiet_start") or "").strip()
        if _quiet_on and parse_hhmm(sc.get("scan_quiet_start")) is not None else "")
    out["scan_quiet_end"] = (
        str(sc.get("scan_quiet_end") or "").strip()
        if _quiet_on and parse_hhmm(sc.get("scan_quiet_end")) is not None else "")
    out["fast_ttl_min"] = _num(sc.get("fast_ttl_min"),
                               DEFAULTS["fast_ttl_min"], 5, 1440)
    out["slow_ttl_min"] = _num(sc.get("slow_ttl_min"),
                               DEFAULTS["slow_ttl_min"], 5, 1440)
    if out["slow_ttl_min"] < out["fast_ttl_min"]:
        out["slow_ttl_min"] = out["fast_ttl_min"]
    out["near_ratio"] = _num(sc.get("near_ratio"),
                             DEFAULTS["near_ratio"], 0.0, 1.0, float)
    out["stagger_seconds"] = (
        _num(sc.get("stagger_seconds"), DEFAULTS["stagger_seconds"], 0, 120)
        # 调度时钟策略关掉 = **不错峰起跑**（整点齐发在这条开关下是用户的明示
        # 选择）。周期与随机扰动不在这条开关的管辖内：它们由调度层读配置，
        # 关掉「错峰」不会顺手把定时也停掉——那是另一条策略。
        if switch_on("schedule_clock.enabled") else 0)
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
    out["login_cooldown_max_s"] = _num(
        brk.get("login_cooldown_max_s"),
        DEFAULTS["login_cooldown_max_s"], 0, 86400)
    out["challenge_cooldown_s"] = _num(brk.get("challenge_cooldown_s"),
                                       DEFAULTS["challenge_cooldown_s"],
                                       0, 604800)
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
    # 并发策略关掉 = **不限并发**（0 的语义就是「跟随渠道数」，`main.py` 按这个
    # 值分批开浏览器）。为什么读点在这：并发上限的那一份值就是在这里成型的，
    # 关掉开关必须让**下游拿到的数**变，而不是在别处再判一次（两处判就会打架）。
    if not switch_on("concurrency.enabled"):
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


def stagger_offset(plat, base_seconds, channels=None):
    """渠道起跑偏移：按给定渠道顺序均分（默认浏览器渠道表）。

    调用方应传本轮实际渠道集（含启用的 App）；不传时保留旧行为。
    固定（非随机）是刻意的——同一渠道每轮偏移一致，便于复现与对账；
    周期本身的随机性由调度层的 jitter 负责。"""
    base = float(base_seconds or 0)
    if base <= 0:
        return 0.0
    order = list(channels) if channels else list(PLATFORMS)
    if not order:
        order = list(PLATFORMS)
    step = base / len(order)
    if plat in order:
        return round(order.index(plat) * step, 1)
    import zlib
    return round((zlib.crc32(str(plat).encode("utf-8")) % 1000) / 1000 * base, 1)


# 统一异常词表：code → (中文名, 建议动作, 是否自动自愈)
# UI/日志/建议引擎共用一套，避免"同一个 444 在三处说三种话"。
# r1804：App 渠道的中文名（登录建议要说清"在哪个 App 里登录"）。
_APP_CN = {"app_ctrip": "携程 App", "app_fliggy": "飞猪 App",
           "app_qunar": "去哪儿 App", "app_tongcheng": "同程 App",
           "app_zhixing": "智行 App"}


FAILURE_KINDS = {
    "ip": ("IP/频率限流", "等冷却，必要时换出口", False),
    "captcha": ("人机验证", "用采集同一会话去验证", False),
    "login": ("登录态失效", "重登该渠道", False),
    "soft": ("会话层软拒", "下一轮自动预热（无需人工）", True),
    # r1657：账本里写的是 `soft_reject`（完整状态码），表里只有分类码 `soft`，
    # 于是「反复出现」里软拒也显示成「未分类」。两个都收。
    "soft_reject": ("会话层软拒", "下一轮自动预热（无需人工）", True),
    "timeout": ("请求超时", "等下一轮；连续出现再降频", True),
    "parse_error": ("解析失败", "多为页面改版，需排查", False),
    "empty": ("真无票", "无需处理", True),
    # 渠道边界（非法航线/超窗/无该日价/往返无源）：不是故障也不是
    # 待办，标成"需人工"会把人推去做无用功
    "unsupported": ("渠道不支持", "无需处理（能力边界）", True),
    "error": ("未知错误", "看现场；连续出现再干预", False),
    # r1656：以下是**账本里真的会出现**的状态码，原先全落进「未分类」。
    # 被拦（blocked）最常见：滑块/风控/限流都会写它，却说「未分类·看日志」，
    # 用户拿不到任何方向。
    "blocked": ("被拦", "查拦截原因（验证码/限流/风控）；必要时人工过一次", False),
    "challenge": ("人机验证", "用采集同一会话去验证", False),
    "waf": ("访问校验", "等冷却；多为站点风控拦截", False),
    "ad": ("广告弹层", "自动关闭，无需处理", True),
    "anr": ("App 无响应", "自动点「等待」，无需处理", True),
    "face": ("人脸/活体核验", "需本人操作，自动化不可行", False),
    "paced": ("主动让位", "我方没发请求，不算失败", True),
    "skipped": ("跳过", "无需处理", True),
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


def classify_evidence(statuses, note="") -> str:
    """给 ``classify_failure`` 的结论**留证**：说清是哪一条证据判的。

    为什么需要：2026-11-04 翻日志发现「智行 22 次命中captcha」里绝大多数
    根本没有验证码——是"设置航线失败/没取到首页"被归成了验证挑战。但日志
    只打「命中captcha」，**看不到是哪一条证据**，于是根因查不动、只能靠猜。

    这里返回一句话证据（写进日志/案发现场），例如：

    * ``status=blocked``            → 采集器自己判的拦截
    * ``note~=安全验证``            → 文本关键词命中（可能是误判来源）
    * ``soft_reject``               → 软拒
    """
    sts = [str(s or "") for s in (statuses or [])]
    low = str(note or "").lower()
    if "soft_reject" in sts:
        return "status=soft_reject"
    if "login" in sts:
        return "status=login"
    if "blocked" in sts:
        return "status=blocked"
    for k in _CAPTCHA_MARKS:
        if k.lower() in low:
            return "note~=%s" % k
    for k in _LOGIN_MARKS:
        if k in str(note or ""):
            return "note~=%s" % k
    return "status=%s" % (",".join(sorted(set(sts))) or "none")


def _book_key(plat, path=""):
    """限速/熔断的记账键：不带链路 → `渠道`；带链路 → `渠道|链路`。

    为什么是字符串而不是元组：既有快照、日志、界面都把键当字符串用
    （`snapshot()["channels"][plat]`、`paced_by[plat]`），复合键必须能一眼
    拆开；拆的时候**只切一刀**（`split("|", 1)`），因为链路名自己可能带
    `/`（`core/channels.py` 里有真实通路 `H5/API`）。

    缺省 `path=""` 时返回的就是渠道本身——所以既有的渠道级调用
    （`main.py` 的 `record(platform)` / `wait_hint(platform)`）行为一字未变。

    分隔符用 `|` 而不是 `/`：`/` 在通路名里真的出现过（`H5/API`），而
    `core/channels.py::PATH_CN` 的通路名里没有 `|`，所以「只切一刀」是安全的。
    """
    p = str(plat or "")
    q = str(path or "")
    return p if not q else "%s|%s" % (p, q)


def _book_base(key):
    """复合键 → 渠道段（快照按渠道聚合时用）。"""
    return str(key or "").split("|", 1)[0]


def _bucket_keys(plat, path="", channel=True):
    """一次外发要记进哪些桶：默认渠道桶**总是**记；带链路时再记链路桶。

    渠道桶是「这家站点看到的总请求量」的账，链路桶是「这条路自己发了几次」
    的账。只记后者会把「渠道每分钟 N 次」放大成「每条链路 N 次」。

    `channel=False`（r1063 T8）时**只写链路桶**：渠道桶的账由
    `main.py` 为每条查询记过一次（`pac.record(c.name)`），采集器在链路
    闸门里再记一次就是**同一个请求记两遍**——`per_minute` 当场减半、
    `min_gap` 当场翻倍，两个数字都还是"合法值"，查起来只能靠猜。
    默认 `True` 保持既有调用方逐位不变。
    """
    p = str(plat or "")
    q = str(path or "")
    if not q:
        return (p,) if channel else ()
    return (p, _book_key(p, q)) if channel else (_book_key(p, q),)


# 链路被策略停用的说明前缀。T8/T9 的 `path_gate` 拿 `allow=False` 的
# `why` 直接写进 `path_note(path, "paced", detail=…)`：**禁用是"没发"，
# 不是"失败"**——记成 failed 会让一条被停用的链路把整家渠道熔断。
PATH_DISABLED = "链路被策略停用"
# 人工停手（r1063 T18）的说明前缀。与 `PATH_DISABLED` 分开：一个是**配置**
# 决定的（改参数就能恢复），一个是**人**按下的（到点自动恢复，或点恢复）。
PATH_HALTED = "链路被人工停手"


class ChannelBreaker:
    """渠道级熔断：指数退避 + 封顶，成功即复位。

    kind:
      ip / captcha → 阶梯退避（base·2^(n-1)，封顶 cap），累积 strikes
      login        → 固定冷却（默认 15min），不累积 strikes，打 needs_login
      busy         → 0 秒（自家锁冲突，本轮让位即可）

    记账键（r1063 T7）：不带 `path` 时键就是渠道（旧行为）；带 `path` 时是
    `渠道|链路`，于是「PC 这条路被风控」不会把同渠道的 H5 一起停掉。
    `snapshot()` 仍**按渠道聚合**输出——界面与既有门禁只认 `[plat]` 那一层。
    """

    def __init__(self, base_s=300, cap_s=3600, enabled=True,
                 login_cooldown_s=900, challenge_cooldown_s=21600,
                 login_cooldown_max_s=14400):
        self._lock = threading.Lock()
        self._st = {}
        self.configure(base_s, cap_s, enabled, login_cooldown_s,
                       challenge_cooldown_s, login_cooldown_max_s)

    def configure(self, base_s=None, cap_s=None, enabled=None,
                  login_cooldown_s=None, challenge_cooldown_s=None,
                  login_cooldown_max_s=None):
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
            if login_cooldown_max_s is not None:
                self.login_cooldown_max_s = max(0, int(login_cooldown_max_s))
            if challenge_cooldown_s is not None:
                self.challenge_cooldown_s = max(0, int(challenge_cooldown_s))

    def mark_cause(self, plat, kind, *, path=""):
        """只记「这轮被什么拦的」，不改变任何节流动件（r626）。

        用于「功能已被用户关掉」的场景：事实要留痕，但不该再要求一个
        不会执行的动作（如 needs_warmup）。

        `path=""` 的语义与 `reset`/`note_ok` 一致：**这一渠道的全部层级**
        （`_targets`）——归因是人对整家的观察；给了 `path` 才只落那一层。
        """
        with self._lock:
            for key in self._targets(plat, path):
                st = self._rec(key)
                st["reason"] = str(kind or "")

    def _rec(self, plat):
        return self._st.setdefault(str(plat), {
            "strikes": 0, "until": 0.0, "reason": "", "needs_login": False,
            "needs_warmup": False, "ok_streak": 0})

    @staticmethod
    def _keys(plat, path=""):
        """**读取**一次判定要查的键：不带链路只查渠道；带链路**两级都查**。

        渠道级冷却是一次「整家被风控」的结论，对它下面的每条链路都成立；
        链路级冷却只停那一条。少查渠道级会让停手信号在链路粒度的调用里
        凭空消失（T10 验收的就是这条）。
        """
        p = str(plat or "")
        q = str(path or "")
        return (p,) if not q else (p, _book_key(p, q))

    def _targets(self, plat, path=""):
        """**写入/清除**要落到的键。

        `path=""` 的语义统一为**「这一渠道的全部层级」**：渠道级键 + 该渠道
        下所有 `plat|链路` 键（复核 2026-11-06 裁决）。因为不带 path 的调用方
        （`/api/pacing/reset`、`note_ok`、`note_warmup_ok`、`mark_cause`）都是
        「人对整家渠道的动作」：只清 `plat` 会让链路级冷却与标记**永远清不掉**
        ——面板显示「冷却中」，操作员点「解除」台账写成功、行马上又变回冷却；
        或者一次链路级软拒把整家渠道钉在「每轮强制预热」上。

        带 `path` 时**只**落到那一层（不动渠道层）：调用方点名了哪条链路，
        就不该顺手免掉整家渠道的冷却。今天没有 `plat|*` 键，所以单层行为逐位不变。
        """
        p = str(plat or "")
        q = str(path or "")
        if q:
            return (_book_key(p, q),)
        keys = [p]
        for k in self._st:
            k = str(k)
            if k.startswith(p + "|"):
                keys.append(k)
        return tuple(keys)

    def _enabled_for(self, plat, path="", dim=""):
        """总开关 `breaker_switch.enabled` 在**这个作用域**生效与否。

        读点在判定那一刻、按 `渠道[/维度][/链路]` 求值，而不是只认
        `self.enabled`：后者是 `parse_pacing` 从 `crawler.breaker.enabled`
        算出来的**全局层**旧值（`configure()` 装进来的），它永远看不见
        `crawler.strategy_overrides` 里的渠道/维度/链路覆盖。只读它，界面
        会按 `source=channel/dimension` 渲染成「已停用（本层覆盖）」而熔断
        照旧——正是本项目列为头号缺陷的「配了不生效」（复核 2026-11-06
        Critical）。

        `dim`（r1063 fix-wave 2）：`渠道/维度` 层要命中它才查得到；只递
        `path` 不给 `dim` 时链路层同样命不中（键的第二段永远是维度）。缺省
        空串 = 只看渠道层，与迁移前逐位相同。

        `fallback=self.enabled` 保证**没有覆盖**时逐位等于旧行为（含只给
        `crawler:` 段构造实例的单测/嵌入方）。
        """
        return switch_on("breaker_switch.enabled", plat=plat, dim=dim,
                         path=path, fallback=self.enabled)

    def allow(self, plat, now=None, *, path="", dim=""):
        """`dim` 只影响**开关求值**（`_enabled_for`），不影响记账键：
        熔断的键仍是 `渠道` / `渠道|链路`（`_keys`），维度不单独建键——
        同一维度的冷却本来就是同一家渠道的结论，多一层键会让「解除」点不完。
        """
        now = time.time() if now is None else now
        with self._lock:
            if not self._enabled_for(plat, path, dim):
                return True, 0
            wait = 0
            for key in self._keys(plat, path):
                until = float((self._st.get(key) or {}).get("until") or 0)
                if until > now:
                    wait = max(wait, int(round(until - now)))
            if wait > 0:
                return False, wait
            return True, 0

    def trip(self, plat, kind, now=None, retry_after=0, note="", *, path="",
             dim=""):
        """记一次熔断。`path` 是 **keyword-only**：`note` 与 `path` 都是字符串，
        位置调用会把「PC」绑成 note（复核 2026-11-06 指出）。`dim` 同样是
        keyword-only，只参与**开关求值**（熔断键仍是 `渠道[/链路]`）：`渠道/
        维度` 层写的 `breaker_switch.enabled: false` 要在这一层被看到，否则
        界面上「这个维度已停熔断」只是文案。"""
        now = time.time() if now is None else now
        kind = str(kind or "ip")
        if kind == "busy":
            return 0
        with self._lock:
            st = self._rec(_book_key(plat, path))
            # **硬风控：单独给长时间冷却**（2026-11-06）。
            # 安全容器 / 限制登录 / 需实名核验这类拦截不是"解个验证码"能过的，
            # 按 1 小时阶梯重试只会持续加重风险分。命中证据就停 challenge_cooldown_s，
            # 且**不计 strikes**（这不是普通限流，累积次数没有意义）。
            #
            # r1063 T12c：这条长冷却受**两条策略开关**管辖，缺省即今天的行为——
            # `challenge_cooldown.enabled` 关掉 = 退回普通阶梯（用户自担风险）；
            # `captcha_solve.enabled` 关掉 = 程序不再"解个验证码就继续"，
            # 验证码一律按硬风控长冷却处理（不识别就别硬试，越试分越高）。
            _hard_cd = (self.challenge_cooldown_s
                        if switch_on("challenge_cooldown.enabled", plat=plat,
                                     dim=dim, path=path) else 0)
            _solve_on = switch_on("captcha_solve.enabled", plat=plat, dim=dim,
                                  path=path)
            if kind == "captcha" and _hard_cd > 0:
                _note = str(note or "")
                if not _solve_on or any(k in _note for k in _HARD_BLOCK_MARKS):
                    st["reason"] = "challenge"
                    st["until"] = max(st["until"], now + _hard_cd)
                    return _hard_cd
            if kind == "soft":
                # 软拒只要求下一轮先预热，不冷却、不计 strikes：
                # 用整家熔断去惩罚"会话没养好"会错杀已能出数的渠道。
                st["needs_warmup"] = True
                st["reason"] = "soft"
                return 0
            if kind == "login":
                # `login_cooldown.enabled` 关掉 = 登录墙后不再固定冷却（重登入口
                # 仍在，`needs_login` 照旧置位：关的是**等待**，不是「该重登」）。
                _lc = (self.login_cooldown_s
                       if switch_on("login_cooldown.enabled", plat=plat,
                                    dim=dim, path=path) else 0)
                st["needs_login"] = True
                st["reason"] = "login"
                # r1592：**升级式**冷却——偶发一次 15 分钟就回来，
                # 反复撞则逐次翻倍到封顶。2026-11-11 携程/飞猪就是
                # 被"每 15 分钟撞一次 × 两个端"撞到无法登录的。
                if _lc > 0:
                    st["login_strikes"] = min(
                        8, int(st.get("login_strikes") or 0) + 1)
                    _lc = min(int(getattr(self, "login_cooldown_max_s",
                                          14400) or 14400),
                              _lc * (2 ** (st["login_strikes"] - 1)))
                st["until"] = max(st["until"], now + _lc)
                return _lc
            if not self._enabled_for(plat, path, dim):
                return 0
            # `slider_guard.enabled` 关掉 = 滑块/验证码失败**不再逐次拉黑**：
            # 失败照旧留证、照旧给一档基础冷却，但清除 strikes → 冷却不再
            # 2^n 升级（一个手抖连点不会把整家锁到封顶）。
            if kind == "captcha" and not switch_on(
                    "slider_guard.enabled", plat=plat, dim=dim, path=path):
                st["strikes"] = 0
            st["strikes"] = min(16, st["strikes"] + 1)
            # `breaker_ladder.enabled` 关掉 = **不按阶梯升级**（恒 base_s）。
            # 封顶仍在：它属于同一条策略的参数，关掉开关不等于允许无限长冷却。
            if switch_on("breaker_ladder.enabled", plat=plat, dim=dim, path=path):
                cd = min(self.cap_s, self.base_s * (2 ** (st["strikes"] - 1)))
            else:
                cd = min(self.cap_s, self.base_s)
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

    def note_ok(self, plat, need=2, *, path="", dim=""):
        """连续成功 need 次才清 strikes；软拒标记单独清零。

        - strikes/冷却：连续成功才复位，避免抖动渠道反复横跳；
        - needs_warmup：成功出数本身就是"会话已养熟"的最强证据，
          立即清（否则面板会一直提示"软拒待预热"）。

        不带 `path` 时**对所有层级都记一次成功**（见 `_targets`）：否则一次
        链路级软拒写下的 `needs_warmup` 没有任何代码会清，`_merge` 再把它抬成
        渠道级——整家渠道就被钉在「每轮强制预热」上（`r626` 要杀的那种粘滞标记）。

        **`path` 给的是哪条链路成功（r1063 fix-wave 1 把范围写死）**：
        `path=""` 的语义是「这一渠道的**全部层级**」（`_targets`）；给了
        `path` 时只清 **渠道层 + 这一条链路层**（`_keys` 的读集），**不动别的
        链路层**——`H5` 的实时冷却不许被 `PC` 的一次成功顺手免掉（复核
        2026-11-06 第 3 条）。渠道层照清是对的：一次成功出数就证明整家还活着，
        软拒标记留着就会变成上面那种粘滞标记；而读取侧（`_keys`）本来就把
        渠道级冷却算到每条链路上，整家冷却期间根本发不出成功请求，所以清渠道
        层不会放宽任何真实拦截。

        `dim`（r1063 fix-wave 2）**在这一层不参与任何决策**：成功复位不读
        参数层的开关，记账键也只有 `渠道` / `渠道|链路`。它被接受是为了让
        「决策家族」（`allow` / `trip` / `observe` / `note_ok`）签名一致——
        调用方（`main.py` 的落地归因）手上就一个 `dim`，不该为了这一句去
        背哪个方法吃它、哪个不吃。传进来不会改变任何行为，也不会被拿去
        改键布局。
        """
        with self._lock:
            streak = 0
            keys = self._keys(plat, path) if str(path or "") \
                else self._targets(plat, path)
            for key in keys:
                st = self._rec(key)
                st["ok_streak"] = int(st.get("ok_streak") or 0) + 1
                st["needs_warmup"] = False
                if st.get("reason") == "soft":
                    st["reason"] = ""
                if st["ok_streak"] >= max(1, int(need or 2)):
                    st["strikes"] = 0
                    st["until"] = 0.0
                    st["reason"] = ""
                    st["needs_login"] = False
                    st["login_strikes"] = 0
                streak = max(streak, st["ok_streak"])
            return streak

    def note_warmup_ok(self, plat, *, path=""):
        """预热真的拿到风控 cookie 才清软拒标记。

        只访问首页不算数——没下发风控 cookie 的预热，深链仍会被 444。
        不带 `path` 时清该渠道**所有层级**的标记（理由见 `_targets`）；带
        `path` 时范围与 `note_ok` 同一条（渠道层 + 这一条链路层），别的链路的
        标记不碰。
        """
        with self._lock:
            keys = self._keys(plat, path) if str(path or "") \
                else self._targets(plat, path)
            for key in keys:
                st = self._rec(key)
                st["needs_warmup"] = False
                if st["reason"] == "soft":
                    st["reason"] = ""

    def reset(self, plat, *, path=""):
        """复位（成功即复位、人工「解除」也走这里）。

        不带 `path` 时清**这一渠道的全部层级**（渠道级 + 所有 `plat|链路`）：
        面板给操作员的只有渠道级「解除」按钮，只清 `plat` 会让链路级冷却
        点完立刻回红（复核 2026-11-06 Important 1）。带 `path` 时只清那一层
        ——调用方点名了哪条链路，就不该顺手免掉整家渠道的冷却。
        """
        with self._lock:
            for key in self._targets(plat, path):
                self._st[key] = {
                    "strikes": 0, "until": 0.0, "reason": "",
                    "needs_login": False, "needs_warmup": False,
                    "ok_streak": 0}

    @staticmethod
    def _row(st, now):
        until = float((st or {}).get("until") or 0)
        return {
            "state": "cooldown" if until > now else "ok",
            "remain_s": max(0, int(round(until - now))),
            "strikes": int((st or {}).get("strikes") or 0),
            "reason": str((st or {}).get("reason") or ""),
            "needs_login": bool((st or {}).get("needs_login")),
            "needs_warmup": bool((st or {}).get("needs_warmup")),
            "ok_streak": int((st or {}).get("ok_streak") or 0),
        }

    @staticmethod
    def _merge(rows):
        """多条链路 → 一条渠道视图（快照兼容层）。

        主行取「冷却最长」的那条（`reason` 跟着它，否则界面会显示一个早就
        到期了的原因）；`strikes` 取最大、`needs_*` 取或、`ok_streak` 取最小
        ——三个都朝「更保守」的方向合，避免几条链路里最差的那条被掩盖。

        刻意**不**把 `渠道|链路` 的键漏给调用方：`snapshot()["channels"][plat]`
        的形状是界面与既有门禁的读法，多一层键就是一次静默破坏。
        """
        if not rows:
            return None
        dom = max(rows, key=lambda r: (r["remain_s"], r["strikes"]))
        out = dict(dom)
        out["state"] = ("cooldown" if any(r["state"] == "cooldown"
                                          for r in rows) else "ok")
        out["remain_s"] = max(r["remain_s"] for r in rows)
        out["strikes"] = max(r["strikes"] for r in rows)
        out["needs_login"] = any(r["needs_login"] for r in rows)
        out["needs_warmup"] = any(r["needs_warmup"] for r in rows)
        out["ok_streak"] = min(r["ok_streak"] for r in rows)
        return out

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        grouped = {}
        with self._lock:
            for p in PLATFORMS:
                grouped.setdefault(p, [])
            for key, st in self._st.items():
                grouped.setdefault(_book_base(key), []).append(
                    self._row(st, now))
        out = {}
        for p, rows in grouped.items():
            out[p] = self._merge(rows) or self._row({}, now)
        return out


class TokenBucket:
    """请求预算：最小间隔 + 每分钟上限，按 `(渠道[, 链路])` 记账。

    `wait_hint` 只算不睡。分钟窗口是滑动的（deque），因为站点的限流
    窗口几乎都不是整分钟对齐的，固定窗口会放过 2 倍突发。

    记账键（r1063 T7）：不带 `path` 时键就是渠道（**与旧行为一致**，
    `main.py` 的渠道级调用一行都不用改）；带 `path` 时是 `渠道|链路`，
    于是「PC 刚发过」不会让同渠道的 H5 跟着白等。`snapshot()` 仍按渠道
    聚合输出（见 `_book_base`）。
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

    def wait_hint(self, plat, now=None, *, path="", min_gap_s=None,
                  per_minute=None):
        """还要等几秒才轮得到这条链路。

        `min_gap_s` / `per_minute` 给定时**按这两个数算**（缺省=用本桶的
        全局值）：链路级覆盖要从这里进来，否则 `tongcheng/intl/PC：{rate_
        per_minute.value: 3}` 这种覆盖配了也不生效。
        """
        now = time.time() if now is None else now
        key = _book_key(plat, path)
        gap = (self.min_gap_s if min_gap_s is None
               else max(0.0, float(min_gap_s)))
        pm = (self.per_minute if per_minute is None
              else max(0, int(per_minute)))
        with self._lock:
            wait = 0.0
            last = self._last.get(key)
            if gap > 0 and last is not None:
                wait = max(wait, last + gap - now)
            if pm > 0:
                dq = self._win.get(key) or deque()
                while dq and now - dq[0] >= 60:
                    dq.popleft()
                if len(dq) >= pm:
                    wait = max(wait, dq[0] + 60 - now)
            return max(0.0, round(wait, 1))

    def record(self, plat, now=None, *, path="", channel=True):
        """记一次真实外发。带链路时**渠道桶与链路桶各记一次**。

        为什么渠道桶也记（复核 2026-11-06 Important 2）：`per_minute` 是
        **渠道上限**。只记链路桶的话，T8/T9 改成一链路一次闸门之后，
        「10 次/分钟」会变成「PC 10 + H5 10 + API 10 = 30 次/分钟」，
        站点看到的正是最坏的那一面。渠道桶兜住总量，链路桶只在用户显式
        给该链路配了更紧的值时才进一步收紧。

        `channel=False`（r1063 T8）时**只写 `plat|链路` 桶**：渠道桶已由
        `main.py` 为每条查询记过一次，采集器的链路闸门再记一次就是重复
        计数（见 `_bucket_keys`）。
        """
        now = time.time() if now is None else now
        keys = _bucket_keys(plat, path, channel=channel)
        with self._lock:
            for key in keys:
                self._last[key] = now
                dq = self._win.setdefault(key, deque())
                dq.append(now)
                while dq and now - dq[0] >= 60:
                    dq.popleft()

    def snapshot(self, now=None):
        """按**渠道**聚合的快照：`渠道|链路` 的键在输出前合回渠道。

        兼容性是硬要求（T7）：`snapshot()[plat]["last_ago_s"/"per_min_used"]`
        的形状一字不改。

        **不许重复计数**：`record(path=…)` 会同时记渠道桶与链路桶，所以
        `per_min_used` 取渠道桶自己的次数（它本来就是全渠道总量），只有该
        渠道没有渠道桶键（例如只有链路级记录）时才把各链路加起来。
        `last_ago_s` 取全渠道最近一次。
        """
        now = time.time() if now is None else now
        with self._lock:
            last_at = {}
            used = {}
            plat_used = {}
            for key in set(list(self._last) + list(self._win)):
                base = _book_base(key)
                t = self._last.get(key)
                if t is not None and (base not in last_at or t > last_at[base]):
                    last_at[base] = t
                n = sum(1 for x in (self._win.get(key) or ()) if now - x < 60)
                used[base] = used.get(base, 0) + n
                if str(key) == base:
                    plat_used[base] = n
            out = {}
            for p in list(PLATFORMS) + [b for b in used if b not in PLATFORMS]:
                t = last_at.get(p)
                out[p] = {
                    "last_ago_s": (max(0, int(round(now - t)))
                                   if t is not None else -1),
                    "per_min_used": int(plat_used.get(p, used.get(p, 0))),
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
           quiet=None, enabled=None):
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
        # r1804：App 渠道的会话在 App 里，浏览器窗口登不进去——别给错动作。
        if str(plat or "").startswith("app_"):
            _nm = _APP_CN.get(plat, "该 App")
            return {"state": "login", "action": "relogin",
                    "severity": "act",
                    "hint": ("登录态失效：在手机上打开「%s」用手机号登录一次"
                             "（验证码需你本人填，程序代不了）；登录后下一轮"
                             "自动带上会话" % _nm),
                    "eta_s": 0}
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
    # r1624：先问「这渠道在不在采集清单里」。不在清单里时，没有样本是
    # **正常**的（它根本没被调度），不能写「采集没在跑，去查进程」——
    # 用户会照着一句错话去排查一个不存在的故障（去哪儿实测）。
    if enabled is not None and str(plat) not in set(enabled):
        _last0 = str(node.get("last_seen_at") or node.get("last_at")
                     or node.get("last_ok_at") or "")
        return {"state": "disabled", "action": "config",
                "severity": "ok",
                "hint": "该渠道不在你的采集清单里——在「配置 · 平台」勾选后下一轮才会采%s"
                        % (("（最后一条 %s）" % _last0[5:16])
                           if _last0 else ""),
                "eta_s": 0}
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
            # r1844：**刚出过数就别催重登**。`login_since_ok` 是按路径计的，
            # 而 `app-login` 这条路径天生不会记 ok（它就是登录墙探针），它的
            # 连击数永远清不零、还会被域级聚合加总——于是用户刚登录、刚出数，
            # 界面还在催「去手机上登录一次」。本域最近一小时内出过数 = 会话是通的。
            # 用**域级**节点的 last_ok_at：命中的这条往往是 `app-login`
            # （登录墙探针），它自己永远没有 ok。
            _last_ok = str(((_sv or {}).get("last_ok_at")
                            or (_v or {}).get("last_ok_at") or ""))
            _last_login = str(((_sv or {}).get("last_login_at")
                               or (_v or {}).get("last_login_at") or ""))
            # r1851：**上次成功之后有没有再撞墙**——与时间无关，比
            # 「60 分钟内出过数」靠谱（轮询间隔就有 25–37 分钟，超过一小时
            # 没轮到它很常见，会把好会话判死）。字串比较对
            # "YYYY-mm-dd HH:MM:SS" 成立。
            _ok_recent = bool(_last_ok) and (
                not _last_login or _last_login <= _last_ok)
            if _ln_run >= 8 and _okish * 5 <= _n and not _ok_recent:
                _dom = "国内" if _sk == "dom" else "国际"
                # scope/path 回传给界面选登录端：飞猪 PC 与 H5 是两套
                # cookie，「国际 H5 被拦」必须去登 H5；只按厂商开窗
                # （verify）打开的是 PC 窗，登完 H5 依然进不去。
                # r1806：App 渠道给「去手机上登录」，浏览器渠道给「去登录」。
                _is_app = str(plat or "").startswith("app_")
                _act_txt = (
                    ("在手机上打开「%s」用手机号登录一次"
                     "（验证码需你本人填，程序代不了）")
                    % _APP_CN.get(plat, "该 App")) if _is_app else "点「去登录」重存该渠道会话"
                return {"state": "login", "action": "relogin",
                        "severity": "act", "scope": _sk, "path": _name,
                        "hint": "%s %s 近 24h 被登录墙拦 %d/%d 次、仅 %d 次"
                                "出数——根因是会话失效，限流与换路都无效；%s"
                                % (_dom, _shown, _login_n, _n, _okish,
                                   _act_txt),
                        "eta_s": 0}
            # 登录拦截占多数、但这条路其他航线仍在正常出数 → 会话是好的，
            # 是航线级拦截。不要提重登（无效），如实说明并给可行动作。
            if _ln_run >= 8:
                _dom = "国内" if _sk == "dom" else "国际"
                # r1848：这句在说"其他航线"，就必须用**域级**出数——
                # 本路径（app-login 探针）的出数天生是 0，会说出
                # 「其他航线仍在出数（0 次）」这种自相矛盾的话。
                _scope_okish = (int((_sv or {}).get("ok") or 0)
                                + int((_sv or {}).get("calendar")
                                      or (_sv or {}).get("calendar_ok")
                                      or 0))
                return {"state": "path_degraded", "action": "probe",
                        "severity": "wait",
                        "hint": "%s %s 有 %d/%d 次被登录墙拦，但同一会话"
                                "其他通路仍在出数（%d 次）——会话是好的，"
                                "属航线级拦截；先点「自检」核实，别急着重登"
                                % (_dom, _shown, _login_n, _n,
                                   _scope_okish),
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
        # r1744：**空转比失败更贵**。尝试很多、一次都没出数时，「观察一轮」
        # 等于让它继续白烧（App 单次 100–200 秒）。这时给「先停手排查」。
        _qatt = int(q_attempts or 0)   # 与上面同一口径（查询口径）
        _qok = int(q_ok or 0)
        if _qatt >= 20 and _qok == 0:
            return {"state": "degraded", "action": "halt",
                    "severity": "act",
                    "hint": "近 24h %d 次尝试 0 出数——空转比失败更贵，"
                            "建议先「停手」排查（点本行「停手」）" % _qatt,
                    "eta_s": 0}
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
        # 原始配置留一份：`self.cfg` 是 parse_pacing 之后的**节流参数**，
        # 开关类的原始键（path_auto_retire 等）不在里面（r1063 T206 实测）。
        self._raw_cfg = dict(cfg) if isinstance(cfg, dict) else {}
        self.cfg = parse_pacing(cfg or {})
        self._breaker = ChannelBreaker(
            self.cfg["breaker_base_s"], self.cfg["breaker_cap_s"],
            self.cfg["breaker_enabled"], self.cfg["login_cooldown_s"],
            self.cfg["challenge_cooldown_s"])
        self._bucket = TokenBucket(self.cfg["min_gap_s"],
                                   self.cfg["per_minute"])
        self._last = {}
        # 每个 (渠道, 航线, 日期) 最近一次**尝试**时间（不管成没成）。
        # 与 `_last`（最近一次**成功**取价）分开：cadence 要按尝试算，
        # 否则"从未成功"的渠道永远没有基线、每轮都被跑（见 plan_query）。
        self._tries = {}
        # 每渠道连续失败次数（成功即清零）。用来把 cadence 升级：
        # 连续失败越多，越不该按正常节奏去戳它。
        self._fail_streak = {}
        self._health_all = {}
        # r1063 T206：自动退役的"下次复检时间"（key = health scope key）
        self._auto_retire_next = {}
        # 兼容视图（见 `_health` property）：老代码只读，不写。
        # 人工停手读点（r1063 T18）：由调用方注入，未注入即「没有停手」。
        self._halt_reader = None
        # 换跑道（r1063 T23）成效计数：预置次数 / 实际换道次数 / 换道回采条数。
        # 放在 pacing 里是为了**一份状态**（面板、健康卡、接口都读 snapshot）。
        self._failover = {"preloads": 0, "switches": 0, "rows": 0,
                          "last": "", "reasons": {}}
        # 耗时构成（r1063 T27）：墙钟 / 有效工作 / 任务数 / 节流跳过数。
        # 每渠道「在等」累计（r1063 T30）：闸门 + 渠道内部限速/退避。
        self._chan_wait = {}
        # 会话重建次数（r1063 T48）：健康行要能说「这家已重建 N 次」，
        # 否则用户不知道系统有没有动过档案。
        self._chan_resets = {}
        # 会话重建的判据链（r1063 T49）：连续被拦次数/类型/上次时刻/今日次数。
        # 界面要能回答「凭什么判它该重建」，而不是只显示一个次数。
        self._sr_view = {}
        self._timing = {"n": 0, "wall": 0.0, "work": 0.0,
                        "tasks": 0, "paced": 0, "timed_out": 0,
                        "gate": 0.0}
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
            new["breaker_enabled"], new["login_cooldown_s"],
            new["challenge_cooldown_s"])
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
    def allow(self, plat, now=None, *, path="", dim=""):
        """`dim`（r1063 fix-wave 2）只递给开关求值：`breaker_switch.enabled`
        在 `渠道/维度` 层写的 `false` 要让这条决策看到，否则维度级覆盖只是
        界面文案。记账键不受影响（仍是 `渠道` / `渠道|链路`）。"""
        return self._breaker.allow(plat, now, path=path, dim=dim)

    def trip(self, plat, kind, now=None, retry_after=0, note="", *, path="",
             dim=""):
        return self._breaker.trip(plat, kind, now, retry_after, note,
                                  path=path, dim=dim)

    def reset(self, plat, *, path=""):
        # 一旦成功就清零连续失败：立刻回到正常节奏
        with self._lock:
            self._fail_streak[str(plat)] = 0
        self._breaker.reset(plat, path=path)

    def note_ok(self, plat, need=2, *, path="", dim=""):
        """`dim` 只为签名同族一致（`allow`/`trip`/`observe` 都吃它）：成功
        复位既不读开关、也不按维度建账，传进来不改变行为（见
        `ChannelBreaker.note_ok`）。"""
        return self._breaker.note_ok(plat, need, path=path)

    def note_warmup_ok(self, plat, *, path=""):
        self._breaker.note_warmup_ok(plat, path=path)

    def warmup_on(self, plat, dim="", path=""):
        """「首页预热」这条策略对该作用域生效与否（`warmup.enabled`）。

        读点在**调用那一刻**过参数层，`self.cfg["warmup_enabled"]`（由
        `parse_pacing` 从 `crawler.warmup.enabled` 归一出来的全局层旧值）只在
        没人配过这个键时兜底。为什么必须是方法而不是让调用方读 `pac.cfg`：
        `pac.cfg` 是 `refresh()` 那一刻的快照，而渠道级覆盖、以及"`main.py`
        的 rt["pacing"] 与采集器私有实例"这两份实例，只有现读参数层才一致
        （复核 2026-11-06 第 1 条）。

        `dim`/`path` 是作用域（r1063 fix-wave 2 起由调用点真递）：`渠道/维度`
        与 `渠道/维度/链路` 层写的 `warmup.enabled: false` 只有给了它们才查
        得到——「这条路不预热」是维度/链路级可调的正当需求。
        """
        return switch_on("warmup.enabled", plat=plat, dim=dim, path=path,
                         fallback=self.cfg.get("warmup_enabled", True))

    def health_penalty_on(self, plat, dim="", path=""):
        """「成功率保护」这条策略对该作用域生效与否（`health_penalty.enabled`）。

        **作用域只到渠道级（波次六对账后的实话）**：本方法的唯一消费者是
        `set_health(plat, rate, attempts)`，而 `set_health` 拿到的是
        `main.py` 从 `storage.path_stats(24)` 取来的**渠道级聚合**
        （一个渠道一个 `rate`/`attempts`，账本里本来就没有按维度分开的
        成功率）。所以 `dim`/`path` 留在签名里只为与 `warmup_on` 同族、
        将来真按维度算健康度时才用得上，今天**递进来也不会改变判定**。
        契约 `core/strategy_contract.py` 的 `health_penalty.scope` 因此只写
        `global/channel`，`effect` 也明说「只在渠道级生效」——声明不许比
        代码宽，否则用户在维度层配了 `false`、界面显示「已停用」、降频照旧，
        正是本项目列为头号缺陷的那一类。
        """
        return switch_on("health_penalty.enabled", plat=plat, dim=dim,
                         path=path,
                         fallback=self.cfg.get("health_penalty_enabled", True))

    # ---------- 5 区：令牌桶 ----------
    def wait_hint(self, plat, now=None, *, path=""):
        return self._bucket.wait_hint(plat, now, path=path)

    def record(self, plat, now=None, *, path="", channel=True):
        self._bucket.record(plat, now, path=path, channel=channel)

    # ---------- 6 区：链路闸门（r1063 T7） ----------
    def _param(self, pid, plat, dim, path):
        """按 `渠道/维度/链路` 求一个策略参数；没有值就用**策略声明**的默认值。

        默认值不在这里重抄一份数字：`sp.PARAMS[pid].default` 是契约里那一份，
        闸门只消费它。抄第二份的后果是契约改了默认值、门却还按旧数字跑
        （复核 2026-11-06）。

        热链路（r1063 T14 已接线）：`main.py` 在启动路径与 `reload_config()`
        两处都调 `strategy_params.set_config(cfg)`，所以 `resolve()` 读到的是
        用户此刻的配置——global/channel/dimension/path 各层当场接管，闸门不必
        重建（本实例的 `self.cfg` 只在 `refresh()` 时重读，那是节流动件那一层，
        与策略参数是两回事）。门禁 `tests/test_r1063_hot_reload.py` 钉这条：
        同一个 `Pacing` 对象，改配置后 `gate_path()` 立刻按新速率判。

        目录里查不到该 pid（例如策略被撤掉）时返回 `None`，由调用方兜底：
        闸门是采集的必经路径，不能因为参数目录的变化就抛异常停采。
        """
        pid = str(pid)
        decl = sp.PARAMS.get(pid)
        if decl is None:
            return None
        try:
            got = sp.resolve(pid, plat=str(plat or ""),
                             dim=str(dim or ""), path=str(path or ""))
        except KeyError:
            return decl.default
        if got.source == "default":
            return decl.default
        return got.value

    @staticmethod
    def _scope_key(plat, dim, path):
        """给人看的作用域串（`tongcheng/intl/PC`；缺段不拼空斜杠）。"""
        return "/".join([x for x in (str(plat or ""), str(dim or ""),
                                     str(path or "")) if x])

    def _path_enabled(self, plat, dim, path):
        """这条链路是否被策略停用（`path_fallback.enabled`，缺省启用）。

        `None`（YAML 里写了 `enabled:` 却没有值）按「没配」处理 → 启用：
        一个空值把整条链路静默关掉，是这类缺陷里最难查的一种。

        读不懂的值（`"flase"` 这种拼错的）**fail-open 但留痕**：一条根本
        启用不了的通路，如果连一行日志都没有，用户会以为自己配好了。
        """
        got = self._param("path_fallback.enabled", plat, dim, path)
        if got is None:
            return True
        if isinstance(got, bool):
            return got
        if isinstance(got, (int, float)):
            return bool(got)
        text = str(got).strip().lower()
        if not text:                      # 写了键却没写值：等于没配
            return True
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
        _warn_once(got, "crawler.path_fallback.enabled 的值 %r 读不懂"
                        "（%s）：已按启用处理，要停用请写 false"
                        % (got, self._scope_key(plat, dim, path)))
        return True

    def _rate_limits(self, plat, dim, path):
        """该链路生效的 (min_gap_s, per_minute)——两层各算一次。

        返回 `(渠道层, 链路层)`：渠道层按**渠道/全局**口径（`dim`/`path` 不参与
        求值，渠道桶是全渠道共享的一份总预算），链路层按 `渠道/维度/链路` 全口径
        求值（于是 `渠道/维度/链路` 的覆盖只收紧这一条路）。

        **开关按本次作用域求值**（r1063 fix-wave 2）：`rate_min_gap.enabled` /
        `rate_per_minute.enabled` 在 `渠道/维度[/链路]` 层写 `false` 时，这一次
        判定里的两腿都不设限——「这条路放开限速」正是路径级覆盖的意义。
        影响面被 `gate_path()` 的调用粒度天然框住：换个作用域再问一次，开关
        重新按那个作用域求值（它不写任何状态，也不改 `self.cfg`）。

        参数目录里查不到时退回本实例 cfg（`parse_pacing` 的结果），不抛异常。
        """
        def _gap(v):
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                return float(self.cfg["min_gap_s"] or 0)

        def _pm(v):
            try:
                return max(0, int(v))
            except (TypeError, ValueError):
                return int(self.cfg["per_minute"] or 0)

        # 两条限速策略各自可关（r1063 T12c）：关掉 = 这一维不设限，**另一维照旧**
        # （最小间隔与每分钟上限是两个旋钮，关一个不该把另一个一起废掉）。
        _gap_on = switch_on("rate_min_gap.enabled", plat=plat, dim=dim,
                            path=path)
        _pm_on = switch_on("rate_per_minute.enabled", plat=plat, dim=dim,
                           path=path)
        gap_c = _gap(self._param("rate_min_gap.value", plat, "", "")) if _gap_on else 0.0
        pm_c = _pm(self._param("rate_per_minute.value", plat, "", "")) if _pm_on else 0
        gap_p = _gap(self._param("rate_min_gap.value", plat, dim, path)) if _gap_on else 0.0
        pm_p = _pm(self._param("rate_per_minute.value", plat, dim, path)) if _pm_on else 0
        return (gap_c, pm_c), (gap_p, pm_p)

    def gate_path(self, plat, dim="", path=""):
        """**用某条链路之前**问一次：能不能用、要等多久、为什么。

        返回 `(allow, wait_s, why)`：

        * `allow=False` —— `why` 说清原因。调用方**只跳过这一条链路**，
          不要 `return` 整个查询，也不要把它记成 `failed`：记 `paced`
          （一条被策略停用的链路若记成失败，会把整家渠道的熔断拉开，
          那正是「停一条路 = 停一家渠道」的连坐）。
        * `wait_s > 0` —— 令牌桶还要等多久。**睡眠由调用方在锁外做**，
          本模块不在锁内睡（铁律 1）。

        三个判据依次是「策略停用 → 熔断 → 限速」：
          1. `path_fallback.enabled`：按 `渠道/维度/链路` 覆盖求值，被点名
             停用的那条直接拒绝，同渠道其它链路**不受影响**；
          2. 熔断：渠道级冷却对该渠道所有链路生效，`渠道|链路` 级冷却只停
             那一条（复合键存在的理由）。**开关本身按本次作用域求值**
             （r1063 fix-wave 2）：`breaker_switch.enabled=false` 写在
             `渠道/维度` 层时，这个维度的链路一律放行，同渠道别的维度照旧；
          3. 限速：`rate_min_gap` / `rate_per_minute` 同样按 `渠道/维度/链路`
             覆盖求值（含它们的 `enabled` 开关，见 `_rate_limits`），**渠道桶
             与链路桶各算一次、取较大者**——`per_minute` 是渠道上限，只按
             链路桶算会把它放大成「每条链路 N 次」。
        """
        plat = str(plat or "")
        dim = str(dim or "")
        path = str(path or "")
        scope = self._scope_key(plat, dim, path)
        # 0. **人工停手**（r1063 T18）：人按下的停手优先于一切自动策略。
        #    按「链路 → 维度 → 渠道」找：链路级停手只停这一条路，同维度
        #    其它通路照常（「可精准控制」在干预面上的落点）。
        #    读点由调用方注入（`set_halt_reader`），本模块不 import 持久化层。
        _hk, _hr = self._halt_of(plat, dim, path)
        if _hk:
            try:
                _until = float(_hr.get("until") or 0)
            except (TypeError, ValueError):
                _until = 0.0
            _left = max(0, int(_until - time.time()))
            _when = time.strftime("%m-%d %H:%M", time.localtime(_until))
            return False, 0.0, (
                "%s：人工停手至 %s（%s，剩 %d 分钟）——只停这一条，"
                "同渠道其它链路照常"
                % (PATH_HALTED, _when, _hk, (_left + 59) // 60))
        if not self._path_enabled(plat, dim, path):
            return False, 0.0, (
                "%s：path_fallback.enabled=false（%s）——只停这一条链路，"
                "同渠道其它链路照常" % (PATH_DISABLED, scope))
        # 自动退役（r1063 T206）：死链路别再白花一次完整抓取。
        _ar = self._auto_retire_why(plat, dim, path)
        if _ar:
            return False, 0.0, _ar
        ok, remain = self.allow(plat, path=path, dim=dim)
        if not ok:
            return False, float(remain), (
                "链路冷却中：%s 还要 %d 秒（熔断按 渠道|链路 记账，"
                "到点自动恢复，不建议手动解除）" % (scope, remain))
        (gap_c, pm_c), (gap_p, pm_p) = self._rate_limits(plat, dim, path)
        # 成功率保护按作用域缩放**链路**限速（r1063 T16）：
        # 该链路自己成功率差 → 只有它自己的最小间隔按倍数拉长；同维度其它
        # 链路（例如 PC 与 H5/API）不受影响。这就是「通路也算独立维度」在
        # 限速侧的落点——不缩放渠道桶，否则一条烂路会把整家拖慢。
        _pen = self._health_penalty(plat, dim, path)
        _pen_note = ""
        if path and _pen > 1.0:
            gap_p = (gap_p or gap_c) * _pen
            _pen_note = "，成功率保护 ×%.1f" % _pen
        wait_c = self._bucket.wait_hint(plat, min_gap_s=gap_c, per_minute=pm_c)
        wait_p = 0.0
        if path:
            wait_p = self._bucket.wait_hint(plat, path=path, min_gap_s=gap_p,
                                            per_minute=pm_p)
        wait = max(wait_c, wait_p)
        why = ""
        if wait > 0:
            why = ("链路限速：%s 还要等 %.1fs（渠道最小间隔 %.1fs%s）"
                   % (scope, wait, gap_c,
                      ("，每分钟上限 %d 次" % pm_c) if pm_c else "")
                   + _pen_note)
        return True, float(wait), why

    # ---------- 3 区：分层 TTL ----------
    #
    # 成功率保护的作用域是**三级**（r1063 T16）：
    #   链路 `(plat, dim, path)` > 维度 `(plat, dim, "")` > 渠道 `(plat, "", "")`
    # 账本里每一级都有真实样本（`path_stats` 的 `paths` / `dims` / 渠道节点），
    # 所以「H5/API 烂、PC 好」可以只压 H5/API，而不是整家一起慢下来。
    @property
    def _health(self):
        """渠道级健康读数的**兼容视图**（老形状 `{plat: {...}}`）。

        内部只有 `self._health_all` 一份状态（无包袱重构）；这里给既有门禁
        与旧读点留一个只读投影，别再往它写。"""
        with self._lock:
            return {k[0]: dict(v) for k, v in self._health_all.items()
                    if k[1] == "" and k[2] == ""}

    def _health_scope_key(self, plat, dim="", path=""):
        return (str(plat), str(dim or ""), str(path or ""))

    def note_chan_wait(self, plat, sec) -> None:
        """记某渠道「在等」的秒数（r1063 T30）：闸门睡眠 + 渠道内部限速。

        它和抓取耗时分开：面板要能回答「这家慢是在等我方限速，还是真的在抓」。
        """
        try:
            v = float(sec or 0)
        except (TypeError, ValueError):
            return
        if v <= 0:
            return
        with self._lock:
            k = str(plat or "")
            self._chan_wait[k] = round(
                float(self._chan_wait.get(k) or 0) + v, 1)

    def note_reset(self, plat, n: int = 1) -> None:
        """记一次「会话重建」（r1063 T47/T48）：界面据此显示「已重建 N 次」。"""
        try:
            add = max(1, int(n or 1))
        except (TypeError, ValueError):
            add = 1
        with self._lock:
            k = str(plat or "")
            self._chan_resets[k] = int(self._chan_resets.get(k) or 0) + add

    def _failover_view(self, channels) -> dict:
        """换道成效 + **每家渠道的判据输入**（r1063 T50）。

        只有成效（预置/换道/回采）回答不了用户的问题：**为什么这次没换？**
        预算还剩几次、冷却还要多久、上次换到哪、成没成——这些是决策真正的输入，
        由 `core.failover.state()` 从**同一个账本**读出（读数与决策同源）。
        """
        out = self.failover_stats()
        # 账本/判据的根目录：生产默认 `user_data`；`TM_USER_DATA_DIR` 只作
        # **测试注入**（端到端用例必须能把它指到临时目录，否则会读到真实账本，
        # 更糟的是会动真实档案——真实发生过一次）。
        import os as _os
        _ud = _os.environ.get("TM_USER_DATA_DIR") or "user_data"
        try:
            from core import failover as _fo
            keys = [k for k in (channels or {}) if not str(k).startswith("app_")]
            out["plats"] = _fo.states(keys, None, user_data_dir=_ud)
        except Exception:
            out["plats"] = {}
        # 7 天成效（r1063 T51）：进程内计数重启归零，历史账本才不会归零——
        # 用户据此判断"这条自动策略对我到底有没有用"。
        try:
            from core import strategy_ledger as _led
            out["history"] = _led.summary(days=7, root=_ud)
        except Exception:
            out["history"] = {}
        return out

    def note_sr_state(self, plat, **kw) -> None:
        """记会话重建的**判据输入**（只保留会变的那几项，缺省项保留旧值）。

        键：`fails` 连续被拦次数 · `kind` 被拦类型 · `last_ts` 上次重建时刻 ·
        `day` 今日次数 · `why` 上一轮给出的判断理由（人话）。
        """
        k = str(plat or "")
        with self._lock:
            cur = dict((self._sr_view or {}).get(k) or {})
            for key in ("fails", "kind", "last_ts", "day", "why"):
                if key in kw:
                    cur[key] = kw[key]
            self._sr_view[k] = cur

    def reset_count(self, plat) -> int:
        with self._lock:
            return int((self._chan_resets or {}).get(str(plat or "")) or 0)

    def note_query_timing(self, *, wall=0.0, work=0.0, tasks=0, paced=0,
                          timed_out=0, gate=0.0):
        """记一条查询的**耗时构成**（r1063 T27）：墙钟 / 有效工作 / 空等。

        为什么要这三个数：一轮慢，可能是"活多"（有效工作占比高），也可能是
        "在等"（栅栏模型下最慢的那家决定整条查询时长）。两者的解法完全不同——
        前者要提并发或砍请求，后者要打破栅栏（跨查询流水线）。
        没有这两个数就优化，只能靠猜。
        """
        try:
            w = float(wall or 0)
            k = float(work or 0)
        except (TypeError, ValueError):
            return
        if w < 0 or k < 0:
            return
        with self._lock:
            t = self._timing
            t["n"] = int(t.get("n") or 0) + 1
            t["wall"] = round(float(t.get("wall") or 0) + w, 1)
            t["work"] = round(float(t.get("work") or 0) + k, 1)
            t["tasks"] = int(t.get("tasks") or 0) + int(tasks or 0)
            t["paced"] = int(t.get("paced") or 0) + int(paced or 0)
            # 超时次数（r1063 T28）：栅栏超时是**纯浪费**的墙钟，必须单列——
            # 它和"节流跳过"不同，后者是我方主动不发，前者是在白等。
            t["timed_out"] = int(t.get("timed_out") or 0) + int(timed_out or 0)
            # 限速等待（r1063 T29）：有效工作里**有多少是在等我方的令牌桶**。
            # 这个数和"抓取耗时"必须分开——前者是风控代价，后者才是可优化项。
            t["gate"] = round(float(t.get("gate") or 0) + float(gate or 0), 1)

    def timing_stats(self) -> dict:
        """本轮耗时构成 + 派生占比（空等 = 1 - 工作/墙钟）。"""
        with self._lock:
            t = dict(self._timing)
        w = float(t.get("wall") or 0)
        k = float(t.get("work") or 0)
        t["idle_ratio"] = (round(max(0.0, 1.0 - (k / w)), 3) if w > 0 else None)
        g = float(t.get("gate") or 0)
        t["gate_ratio"] = (round(min(1.0, g / k), 3) if k > 0 else None)
        t["fetch"] = round(max(0.0, k - g), 1)
        return t

    def note_failover(self, *, preload=0, switched=0, rows=0, note="",
                      reason=""):
        """记一次换跑道（r1063 T23）：预置几家、真换了几次、回采到几条。

        `rows` 是关键读数——换道如果一直回采 0 条，说明这条 App 通路也一起
        被拦了，界面上要能看出来（否则用户以为"换道在生效"）。
        """
        with self._lock:
            f = self._failover
            f["preloads"] = int(f.get("preloads") or 0) + int(preload or 0)
            f["switches"] = int(f.get("switches") or 0) + int(switched or 0)
            f["rows"] = int(f.get("rows") or 0) + int(rows or 0)
            if note:
                f["last"] = str(note)[:120]
            # 归因（r1063 T33）：换道为什么没回采到数。四种原因处理方式不同，
            # 混成一句"回采 0 条"等于没信息。
            if reason:
                rs = f.setdefault("reasons", {})
                rs[str(reason)] = int(rs.get(str(reason)) or 0) + 1

    def failover_stats(self) -> dict:
        with self._lock:
            out = dict(self._failover)
            out["reasons"] = dict(out.get("reasons") or {})
            return out

    def set_halt_reader(self, fn):
        """注入「人工停手表读点」（r1063 T18）。

        签名 `fn(plat, dim, path) -> (key, {"until","note"})`，没命中返回
        `("", {})`。**由调用方注入**而不是在 pacing 里 import `core.policy`：
        这个模块要能脱离磁盘单测（现有门禁全是不碰 user_data 的纯内存用例）。
        """
        self._halt_reader = fn

    def _halt_of(self, plat, dim="", path=""):
        """查询当前作用域是否被人工停手（链路 → 维度 → 渠道）。"""
        fn = getattr(self, "_halt_reader", None)
        if not fn:
            return "", {}
        try:
            key, rec = fn(str(plat or ""), str(dim or ""), str(path or ""))
        except Exception:
            return "", {}          # 读停手表失败 ≠ 停手：宁可继续跑并留日志
        if not key:
            return "", {}
        try:
            if float((rec or {}).get("until") or 0) <= time.time():
                return "", {}      # 已到点：视同没有停手
        except (TypeError, ValueError):
            return "", {}
        return str(key), dict(rec or {})

    AUTO_RETIRE_S = 24 * 3600

    def _health_for_path(self, plat, dim="", path=""):
        """按（渠道, 链路）取健康记录——**不依赖维度命名**。

        实测分歧：健康账按 `dim_of_path(path)` 写（如 `detail`），
        爬虫问闸门按业务维度写（如 `domestic`），精确键必然对不上，
        于是"自动退役"永远读不到记录、一条都不退役。
        聚合口径：同 (渠道, 链路) 下取**样本最多**的那条（成功率取最低），
        宁可保守判"该停"，也不要因为命名漂移而永不生效。
        """
        exact = self._health_all.get(self._health_scope_key(plat, dim, path))
        if isinstance(exact, dict) and int(exact.get("attempts") or 0) > 0:
            return exact
        best = {}
        try:
            for k, v in list(self._health_all.items()):
                if not isinstance(v, dict) or len(k) != 3:
                    continue
                if k[0] != plat or k[2] != path:
                    continue
                if int(v.get("attempts") or 0) > int(best.get("attempts") or 0):
                    best = v
        except Exception:
            return exact or {}
        return best or (exact or {})

    def _auto_retire_enabled(self) -> bool:
        """自动退役开关（默认开）。原始配置优先，也接受 `crawler.` 前缀。"""
        raw = getattr(self, "_raw_cfg", {}) or {}
        for src in (raw, (raw.get("crawler") if isinstance(raw, dict) else None)):
            if isinstance(src, dict) and "path_auto_retire" in src:
                return bool(src.get("path_auto_retire"))
        return True

    def _auto_retire_why(self, plat, dim="", path=""):
        """这条链路是否该被**自动退役**（返回原因串；空串=不退役）。

        判据（全部满足才停）：
          1. 开关 `crawler.path_auto_retire`（默认 True，可整机关掉）；
          2. 窗口内样本 >= 10 且成功率 == 0（样本少不下结论）；
          3. 最后原因命中**能力边界**词（不查/不支持/停服…）——
             被风控拦出来的 0% 不在此列（那归熔断/换道处理）；
          4. 距上次放行已过 24 小时（到期自动探一次，仍 0% 再停 24h）。
        """
        try:
            if not self._auto_retire_enabled():
                return ""
            key = self._health_scope_key(plat, dim, path)
            rec = self._health_for_path(plat, dim, path)
            n = int(rec.get("attempts") or 0)
            rate = float(rec.get("rate") or 0.0)
            if n < 10 or rate > 0.0:
                return ""
            why = str(rec.get("why") or rec.get("last_why") or "")
            try:
                from core.advise import _is_boundary
                if not _is_boundary(why):
                    return ""
            except Exception:
                return ""
            now = float(self._clock() if callable(getattr(self, "_clock", None))
                        else time.time())
            # 「是否设过」必须看 key 在不在：用 `x or 0` 会把 0.0（=已到期）
            # 当成"没设过"，于是到期又被停 24h——可自愈变成永久拉黑。
            if key not in self._auto_retire_next:
                self._auto_retire_next[key] = now + self.AUTO_RETIRE_S
                return ("自动退役：%s 近窗口 %d 次全部 0 成功，原因是能力边界"
                        "（%s）——先停 24h，到期自动复检一次"
                        % (path or plat, n, why[:40]))
            nxt = float(self._auto_retire_next.get(key) or 0)
            if now < nxt:
                left_h = int((nxt - now) / 3600) + 1
                return ("自动退役中：%s 次全 0（%s），约 %d 小时后复检"
                        % (n, why[:24], left_h))
            # 到期：放行一次做复检，并预约下一次
            self._auto_retire_next[key] = now + self.AUTO_RETIRE_S
            return ""
        except Exception:
            return ""

    def set_health(self, plat, rate, attempts, dim="", path="", why=""):
        """按近 24h 成功率自动加罚（成功率保护，不是熔断）。

        熔断只管"对方明确拒绝"；持续解析失败/空结果不会触发它，却同样
        烧请求。这里按账本自动拉长该作用域的 TTL：0.4 以下 ×3、0.7 以下
        ×1.5，样本 <5 次不判（避免首轮波动就误降频）。

        `dim` / `path` 非空即写到该级；渠道级（都为 ""）是维度和链路的
        回落口径，也是今天行为的逐位延续。
        """
        try:
            r = float(rate or 0)
            n = int(attempts or 0)
        except (TypeError, ValueError):
            return
        key = self._health_scope_key(plat, dim, path)
        # 用户关掉「成功率保护」时：仍然记账（界面要显示 rate/attempts），
        # 但不产生任何降频。宁可多打几次，也不接受自动拉长 TTL。
        # 读点在**决策那一刻**过参数层（`health_penalty.enabled`，可到链路级）。
        _pen_on = self.health_penalty_on(plat, dim=key[1], path=key[2])
        if not _pen_on:
            with self._lock:
                self._health_all[key] = {"rate": round(r, 3), "attempts": n,
                                     "penalty": 1.0, "disabled": True,
                                         "why": str(why or "")[:120]}
            return
        # 五个阈值按作用域求值（r1063 T62）：渠道/维度/链路可以各自定
        # "多低算差、罚几倍、多少样本才判"——以前只读全局，界面上的格子是装饰。
        _pl, _dm, _pt = key
        _need = int(self._scoped("health_penalty.min_samples", _pl, _dm, _pt,
                                 self.cfg.get("health_min_samples", 5)))
        if n < _need:
            penalty = 1.0
        elif r >= float(self._scoped("health_penalty.ok_ratio", _pl, _dm, _pt,
                                     self.cfg.get("health_ok_ratio", 0.7))):
            penalty = 1.0
        elif r >= float(self._scoped("health_penalty.slow_ratio", _pl, _dm, _pt,
                                     self.cfg.get("health_slow_ratio", 0.4))):
            penalty = float(self._scoped("health_penalty.slow_factor",
                                         _pl, _dm, _pt,
                                         self.cfg.get("health_slow_factor", 1.5)))
        else:
            penalty = float(self._scoped("health_penalty.slowest_factor",
                                         _pl, _dm, _pt,
                                         self.cfg.get("health_slowest_factor",
                                                      3.0)))
        with self._lock:
            self._health_all[key] = {"rate": round(r, 3), "attempts": n,
                                     "penalty": penalty,
                                     "why": str(why or "")[:120]}

    def _health_at(self, key, need):
        """某作用域的记录，样本够才算数（内联用，调用方已持锁）。"""
        rec = self._health_all.get(key) or {}
        if rec and int(rec.get("attempts") or 0) >= need:
            return float(rec.get("penalty") or 1.0)
        return None

    def _scoped(self, pid, plat, dim, path, fallback):
        """按作用域取参数（r1063 T57）：**参数层有意见才采用**，否则用全局值。

        为什么需要它：TTL / 邻近窗口这些参数声明了 channel/dimension/path
        作用域，但消费方原先读的是 `parse_pacing` 解析出的**全局标量**——界面
        上按渠道改 TTL 完全无效（实测 `resolve(...)` 给 5、`cfg` 仍是 15）。

        与 `crawlers/slider.py::_pval` 同一条优先级：参数层是**默认来源**，
        不是永远优先——没配过时必须让既有全局值继续说算。
        """
        try:
            from core import strategy_params as _sp
            got = _sp.resolve(str(pid), plat=str(plat or ""),
                              dim=str(dim or ""), path=str(path or ""))
            if str(getattr(got, "source", "default")) != "default":
                return got.value
        except Exception:
            pass
        return fallback

    def _health_penalty(self, plat, dim="", path=""):
        """取该作用域的成功率保护倍数（r1063 T16）。

        顺序：链路（**该链路自己样本够**）→ 维度 → 渠道 → 1.0。
        为什么不「有就给」：一个作用域只有 2 条样本时按它降频，等于让噪声
        决定速度；逐级回落是有意的保守。"""
        plat = str(plat)
        dim = str(dim or "")
        path = str(path or "")
        need = int(self._scoped("health_penalty.min_samples", plat, dim, path,
                                self.cfg.get("health_min_samples", 5)))
        with self._lock:
            for key in ((plat, dim, path), (plat, dim, ""), (plat, "", "")):
                if key[1:] == ("", "") and (dim or path):
                    continue            # 别把渠道级算两遍
                got = self._health_at(key, need)
                if got is not None:
                    return got
            got = self._health_at((plat, "", ""), need)
        return got if got is not None else 1.0

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

    def plan_query(self, plat, key, threshold=0, days_ahead=None, dim="",
                   path=""):
        """返回 (tier, 原因)。tier ∈ fast/slow/skip。

        `days_ahead` 是出发日距今天数：临期行程价格变化快，给一个更短的
        TTL；远期只做低频基线。它只缩短 TTL，不会让本该跳过的查询变快。

        r1063 T15/T16：`dim`/`path` 非空时按**该链路 → 该维度 → 渠道**的
        成功率保护倍数拉长 TTL（每级样本不足自动回落，见 `_health_penalty`）。
        """
        now = self._clock()
        with self._lock:
            last = self._last.get((str(plat),) + tuple(key))
            # 按作用域求值（r1063 T57）：渠道/维度/链路的覆盖真的生效；
            # 没配过时回落到 parse_pacing 解析出的全局值（行为不变）。
            near_ratio = float(self._scoped("near_window.ratio", plat, dim,
                                            path, self.cfg["near_ratio"]))
            fast_ttl = int(self._scoped("ttl_tier.fast", plat, dim, path,
                                        self.cfg["fast_ttl_min"]))
            slow_ttl = int(self._scoped("ttl_tier.slow", plat, dim, path,
                                        self.cfg["slow_ttl_min"]))
        # 惩罚值单独取（`_health_penalty` 自己加锁，别在持锁时再进）
        pen = self._health_penalty(plat, dim, path)
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
            # 邻近比价窗口策略关掉 = **不做临期加密/远期翻倍**（TTL 只按
            # `ttl_tier` 的两档与健康惩罚走）。
            if switch_on("near_window.enabled", plat=plat):
                _nd = int(self._scoped("near_window.days", plat, dim,
                                       path,
                                       self.cfg.get("near_days") or 3))
                if _d <= _nd:
                    fast_ttl = max(5, int(round(fast_ttl / 2.0)))
                elif _d >= 30:
                    slow_ttl = min(1440, int(round(slow_ttl * 2.0)))
        # **cadence 按「尝试」算，且在「无基线」判定之前**（2026-11-06 修）。
        # 原顺序是 `if not last: return "fast"` → cadence 永远走不到，
        # 于是从未出过数的渠道每轮都被跑（qunar 实测一天 52 次、0 成功）。
        _k = (str(plat),) + tuple(key)
        try_ts = self._tries.get(_k)
        # 渠道节奏策略关掉 = **不做这家的最小间隔拦截**（0 在本文件的语义就是
        # 「跟随全局 TTL」，所以关掉只是让本家不再被 cadence 单独压住）。
        floor = (int((self.cfg.get("cadence") or {}).get(str(plat), 0) or 0)
                 if switch_on("cadence.enabled", plat=plat) else 0)
        # **连续失败升级**：基础 cadence ×（1/2/4），总上限 720 分钟。
        # 让"一直失败的渠道"自己慢慢退到每天探两次，而不是靠人调配置。
        if floor:
            with self._lock:
                _streak = int(self._fail_streak.get(str(plat), 0) or 0)
            _mult = 1 if _streak < 3 else (2 if _streak < 6 else 4)
            floor = min(720, floor * _mult)
        if floor:
            _refs = [t for t in ((last[0] if last else None), try_ts)
                     if t is not None]
            if _refs:
                _age = max(0.0, (now - max(_refs)) / 60.0)
                if _age < floor:
                    return "skip", "渠道节奏 %.0f/%d 分钟" % (_age, floor)
        if not last:
            return "fast", "无历史基线"
        ts, price = last
        age = max(0.0, (now - ts) / 60.0)
        th = float(threshold or 0)
        near = True
        if th > 0 and price > 0:
            near = abs(price - th) / th <= near_ratio
        # 分层 TTL 策略关掉 = **不分层**：不再区分「快档/慢档」，统一按快档 TTL
        # 判定（TTL 内跳过、过点就采）。关的只是那层"冷门航线可以放两小时"，
        # 不是把 TTL 整个去掉——去掉就等于每轮全量重抓，那是另一件事。
        if not switch_on("ttl_tier.enabled", plat=plat):
            if age < fast_ttl:
                return "skip", "单档 TTL 内（%.0f/%.0f 分钟）" % (age, fast_ttl)
            return "fast", "单档 TTL 已过，%.0f 分钟未采" % age
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

    def note_try(self, plat, key, now=None):
        """记录一次"真的发了请求"（不论成败）。供 cadence 按尝试时间拦截。"""
        now = self._clock() if now is None else now
        try:
            k = (str(plat),) + tuple(key)
        except TypeError:
            return
        with self._lock:
            self._tries[k] = float(now)
            # 只保留最近的一批，避免长跑内存无界增长
            if len(self._tries) > 4096:
                for _k in list(self._tries)[:1024]:
                    self._tries.pop(_k, None)

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

    def observe(self, plat, statuses, note="", retry_after=0, *, path="",
                dim=""):
        """一次采集落地后调用：真拒绝→熔断；拿到数据→复位。

        `retry_after` 来自响应头（秒）。有它就以它为准，没有才用自算阶梯。
        返回 (kind, cooldown_s)；kind 空串表示"不算拒绝"。

        `path`（r1063 fix-wave 1）：**这次证据来自哪条链路**（能确定时由
        调用方给）。给了就按 `渠道|链路` 记账，于是「PC 这条路被风控」不会
        把同渠道的 H5 一起停掉（`gate_path` 的熔断腿本来就会查这一层）；
        空串=渠道级结论（证据跨多条链路 / 调用方不知道）。关键字专用：
        `note` 与 `path` 都是字符串，位置调用会把「PC」绑成 note。

        `dim`（r1063 fix-wave 2）：这次证据属于哪个**维度**。它只参与下面
        两条开关的求值（`breaker_switch.enabled` / `warmup.enabled`），不改
        记账键：熔断键仍是 `渠道` / `渠道|链路`。少了它，策略里写
        `飞猪/intl: breaker_switch.enabled: false` 就只有界面文案生效、
        熔断照旧——与「配了不生效」同一类缺陷。

        熔断开关关闭时（r625）：分类照做（`cause` 仍记在通道状态里供界面
        显示「这次是被什么拦的」），但**不返回 kind**——调用方拿 kind 当
        「已熔断」的信号（写 auto_trip 台账、打「命中…熔断 Ns」、自动弹窗）。
        原实现在此只让 trip() 返回 0，kind 照旧返回，于是关掉开关后界面仍
        宣称「已熔断」、账本仍写一条自动干预 —— 开关看起来生效了，实际没有。
        开关本身**每次判定现读参数层**（`breaker_switch.enabled`，可到渠道/
        维度/链路级），`self.cfg["breaker_enabled"]` 只在没人配过时兜底。
        """
        kind = classify_failure(statuses, note)
        if not kind:
            if any(str(s) == "ok" or str(s) == "calendar"
                   for s in (statuses or [])):
                self.reset(plat, path=path)
            return "", 0
        # 连续失败计数（cadence 升级用）：hard/ip/captcha/login 都算失败，
        # 唯独 soft（会话没养熟）不算——那是我们自己的功课没做好。
        if kind != "soft":
            with self._lock:
                self._fail_streak[str(plat)] = int(
                    self._fail_streak.get(str(plat), 0)) + 1
        # 留证（2026-11-04）：把"是哪一条证据判的"记下来。原来只打「命中captcha」，
        # 而日志里智行 22 次 captcha 大多是"设置航线失败"被归错——没有证据串
        # 就查不动根因。这条只写内存/快照，不改任何冷却决策。
        with self._lock:
            self._last_evidence = getattr(self, "_last_evidence", {})
            self._last_evidence[str(plat)] = {
                "kind": kind,
                "evidence": classify_evidence(statuses, note),
                "statuses": [str(s or "") for s in (statuses or [])][:6],
                "note": str(note or "")[:160],
                "path": str(path or ""),
                "dim": str(dim or ""),
            }
        if not switch_on("breaker_switch.enabled", plat=plat, dim=dim,
                         path=path, fallback=self.cfg["breaker_enabled"]) \
                and kind not in ("soft", "login"):
            # 未熔断，但把归因留在 Pacing 上（可见性不因开关而消失）：
            # 面板仍能说「这次是被验证码拦的」，只是不再宣称已熔断。
            with self._lock:
                self._cause[str(plat)] = kind
            return "", 0
        if kind == "soft" and not self.warmup_on(plat, dim, path=path):
            # 预热开关关闭（r626）：不置 needs_warmup。那个标志只有
            # note_warmup_ok()（预热成功）才会清，而预热被关掉就永远不执行
            # ——标记会**永久挂着**；等用户哪天重开预热，一个几小时前的软拒
            # 会立刻触发一次"强制预热"。事实照旧留痕（reason / _cause），
            # 面板仍能说「这轮是软拒」，只是不再要求一个被关掉的动作。
            # 不调 trip()：它的 soft 分支会置 needs_warmup，而预热被关掉
            # 之后没有任何代码会清它。这里只留归因。
            self._breaker.mark_cause(str(plat), "soft", path=path)
            with self._lock:
                self._cause[str(plat)] = "soft"
            return "soft", 0
        # 软拒不清 needs_warmup：预热成功（拿到风控 cookie）后由
        # note_warmup_ok() 清；否则下一轮继续先预热。
        cd = self.trip(plat, kind, retry_after=retry_after, note=note,
                       path=path, dim=dim)
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
            health = {k[0]: dict(v) for k, v in self._health_all.items()
                      if k[1] == "" and k[2] == ""}
            health_dims, health_paths = {}, {}
            for (p, d, pth), v in self._health_all.items():
                if pth:
                    health_paths.setdefault(p, {})["%s/%s" % (d, pth)] = dict(v)
                elif d:
                    health_dims.setdefault(p, {})[d] = dict(v)
            cause = dict(self._cause)
        # 熔断关闭时的归因（r625）：未熔断不等于没被拦。把它挂到通道上，
        # 界面才能说「这轮被验证码拦了，熔断已关」而不是一片正常。
        for p, k in cause.items():
            if p in channels and not channels[p].get("reason"):
                channels[p]["blocked_but_open"] = k
        for p, wsec in (self._chan_wait or {}).items():
            if p in channels and wsec:
                channels[p]["waited_s"] = wsec
        for p, nres in (getattr(self, "_chan_resets", None) or {}).items():
            if p in channels and nres:
                channels[p]["resets"] = int(nres)
        for p, sv in (getattr(self, "_sr_view", None) or {}).items():
            if p in channels and sv:
                channels[p]["sr"] = dict(sv)
        for p, b in self._bucket.snapshot(now).items():
            if p in channels:
                channels[p]["bucket"] = b
        for p, h in health.items():
            if p in channels:
                channels[p]["health"] = h
        # 维度级成功率保护读数（r1063 T15）：界面据此说清「是哪个维度被降频」，
        # 而不是只看到一个渠道级倍数。没有维度样本的渠道不出现这个键。
        for p, hd in health_dims.items():
            if p in channels and hd:
                channels[p]["health_dims"] = hd
        # 链路级成功率保护读数（r1063 T16）：键 `"维度/通路"`，例如
        # `"detail/H5/API"`。策略面板据此逐链路显示「这一条被压到几倍」。
        for p, hp in health_paths.items():
            if p in channels and hp:
                channels[p]["health_paths"] = hp
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
            # 换跑道成效（r1063 T23）：预置次数 / 换道次数 / 回采条数。
            # 面板与健康卡据此说「换道这轮救回了几条」，而不是只有一句"已启用"。
            "failover": self._failover_view(channels),
            # 耗时构成（r1063 T27）：墙钟 / 有效工作 / 空等占比。
            # 提速先看这个：空等高 = 在等最慢的那家（栅栏），工作高 = 活真的多。
            "timing": self.timing_stats(),
            # 能力降级账本（r1063 T60）：fail-soft 的地方要留下可查的证据。
            # 「能力悄悄关掉」≠「一切正常」——上轮的定位失效就藏在这里。
            "degraded": _degraded_snapshot(),
        }
