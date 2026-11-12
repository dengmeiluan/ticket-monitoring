"""通路换道（`app_fallback`）：一条通路被**行为型强风控**拦住时，改走同一家的 App 通路。

为什么这是"提高爬取率"而不是"硬解验证码"
------------------------------------------------
行为型挑战（极验 v4 / 天御 / reCAPTCHA / 人脸）判的是**行为分布与环境指纹**，
通用开源方案拿不到稳定通过；硬解失败还会把这家渠道的风控分推得更高。
但同一时刻，同一家渠道的 **App 通路**（官方 App + 真机/模拟器指纹）往往还没被拦
——两条通路的会话、指纹、入口完全不同。所以这里的动作是**换跑道**，
不是绕过风控：一条路被拦，不代表这家渠道断了。

一条硬规则
----------
换道必须**有边界**：每日次数上限 + 冷却，禁止来回横跳（PC 被拦 → App 被拦 →
PC 再试），那样只会把两条路的分数一起打低。边界记账在 `Pacing` 的账本之外单独
一份（`app_fallback_ledger.json`），因为它记的是"换道决策"，不是采集结果。

统一抽象
--------
`app_counterpart()` 是"谁有 App 孪生"的**唯一映射**（从 `core.channels` 派生，
不写死数量）；`plan_switch()` 是唯一的决策入口，读参数层开关、预算与冷却，
返回 `(目标渠道, 原因)`——没有目标就返回 `("", 原因)`，调用方据此只记日志。
"""
from __future__ import annotations

import json
import logging
import os
import time

_LOG = logging.getLogger(__name__)

LEDGER = "app_fallback_ledger.json"

# 会触发「换跑道」的挑战类型：**行为型**才算。
# `face`/`click`/`slider` 不在此列——图像型题目由 `crawlers.captcha` 自己解，
# 解不动再谈换道；而行为型没有通用解法，换道是唯一有意义的动作。
BEHAVIOR_KINDS = ("captcha", "ip", "strong", "behavior")

# 判定"这条通路是被行为型拦的"用的状态词（证据来自 `_fail_evidence`）
BLOCK_STATUS = ("blocked", "login")


def app_counterpart(plat: str) -> str:
    """某浏览器渠道的 App 孪生渠道 id；没有就返回空串。

    映射从 `core.channels` 的注册表**派生**：凡是 App 渠道的 `name` 形如
    `app_<x>` 且 `<x>` 是已知浏览器渠道，就认为它们是同一家的两条通路。
    这样新增渠道不需要改这里（写死 5 家会在第 11 家时变成假红）。
    """
    plat = str(plat or "").strip()
    if not plat or plat.startswith("app_"):
        return ""
    try:
        from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    except Exception:
        return ""
    if plat not in tuple(BROWSER_CHANNELS):
        return ""
    for a in tuple(APP_CHANNELS):
        tail = str(a)[4:] if str(a).startswith("app_") else ""
        if tail == plat and a in tuple(APP_CHANNELS):
            return str(a)
    return ""


def is_behavior_block(kind: str) -> bool:
    """这类挑战值不值得换道（行为型才换；图像型先自己解）。"""
    return str(kind or "").strip().lower() in BEHAVIOR_KINDS


def _sec(cfg: dict = None) -> dict:
    """`crawler.app_fallback` 段（缺省空字典）。"""
    crw = ((cfg or {}).get("crawler") or {}) if isinstance(cfg, dict) else {}
    sec = crw.get("app_fallback")
    return sec if isinstance(sec, dict) else {}


def _enabled(plat: str, cfg: dict = None) -> bool:
    """开关：参数层优先（可到渠道/维度），缺省 True。

    默认开：换道本身不增加对同一入口的请求量（它把请求挪到**另一条**通路上），
    且带每日上限与冷却；关掉它等于让"一条路被拦"升级成"这家断了"。
    """
    try:
        from core.strategy_params import switch_on
        return bool(switch_on("app_fallback.enabled", plat=str(plat or ""),
                              fallback=True))
    except Exception:
        return True


def ledger_path(user_data_dir: str = "user_data") -> str:
    return os.path.join(str(user_data_dir or "user_data"), LEDGER)


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except Exception as e:                      # 记账失败不影响采集本身
        _LOG.warning("换道账本写不进去：%s（%s）", path, e)


def _num(pid: str, plat: str, cfg: dict, key: str, default):
    """读一个数值参数：**参数层优先**（可到渠道/维度覆盖），否则 cfg，再否则默认。

    为什么必须过参数层而不是只读 cfg：面板里改的数若只在 cfg 里，热改就看不到
    效果；`strategy_params.resolve` 是全局唯一的求值入口（r1063 的铁律）。
    """
    try:
        from core import strategy_params as sp
        got = sp.resolve(pid, plat=str(plat or ""))
        return int(float(got.value))
    except Exception:
        pass
    sec = _sec(cfg)
    try:
        return int(float(sec.get(key, default)))
    except (TypeError, ValueError):
        return int(default)


def is_service_closed(kind: str) -> bool:
    """这条通路的服务是不是**已经下线**（r1063 T67）。

    与"被拦"完全不同：被拦是对方不让你进，停服是**门没有了**。
    前者等一会儿可能好，后者只能换通路。
    """
    k = str(kind or "").strip().lower()
    return k in ("service_closed", "closed", "offline")


def is_switch_worthy(kind: str) -> bool:
    """值不值得换道（r1063 T67）：行为型被拦 + **服务下线** 都算。

    行为型：同一份指纹继续用只会越用越黑 → 换 App 通路；
    服务下线：浏览器通路彻底没有 → App 是唯一通路，更该换。
    """
    return bool(is_behavior_block(kind) or is_service_closed(kind))


def plan_switch(plat: str, kind: str, cfg: dict = None, *,
                user_data_dir: str = "user_data", now: float = None,
                running=(), ready=None) -> tuple:
    """要不要把 `plat` 的这次查询改走它的 App 通路。

    返回 `(app_plat, 原因)`；不该换道时 `app_plat` 为空串，原因给人看。

    判据顺序（任一不满足即不换）：
      1. 挑战类型是行为型（`is_behavior_block`）；
      2. 这家有 App 孪生，且它**不在**本轮已在跑的渠道里（否则重复采）；
      3. 参数层开关开着（`app_fallback.enabled`，可到渠道/维度）；
      4. 今日换道次数 < `daily_switches`（默认 6/渠道/天）；
      5. 不在这家的换道冷却里（默认 20 分钟，防来回横跳）。
    """
    now = float(now if now is not None else time.time())
    plat = str(plat or "").strip()
    if not is_behavior_block(kind):
        return "", "不是行为型挑战（%s）：先由验证码模块自己解" % (kind or "未知")
    app = app_counterpart(plat)
    if not app:
        return "", "这家没有 App 通路"
    if app in tuple(str(x) for x in (running or ())):
        return "", "App 通路本轮已在跑（不重复采）"
    if not _enabled(plat, cfg):
        return "", "换道开关已关（app_fallback.enabled=false）"
    # 就绪度（r1063 T34）：App 通路没启用/没注册时换过去必然 0 条，
    # 还白占一次每日额度——**先挡住**。`ready` 由调用方注入（pacing/failover
    # 都不该知道 android 配置长什么样）；没注入就跳过这项检查（fail-open）。
    if ready is not None:
        try:
            _ok, _why = ready(app)
        except Exception:
            _ok, _why = True, ""
        if not _ok:
            return "", "App 通路未就绪：%s" % (_why or "未知原因")
    sec = _sec(cfg)
    cap = _num("app_fallback.daily_switches", plat, cfg, "daily_switches", 6)
    cool = _num("app_fallback.cooldown_s", plat, cfg, "cooldown_s", 1200)
    path = ledger_path(user_data_dir)
    data = _load(path)
    rec = data.get(plat) if isinstance(data.get(plat), dict) else {}
    day = time.strftime("%Y%m%d", time.localtime(now))
    used = int(rec.get("day_used") or 0) if rec.get("day") == day else 0
    if cap > 0 and used >= cap:
        return "", "今日换道已达上限（%d/%d）" % (used, cap)
    last = float(rec.get("last_at") or 0)
    if cool > 0 and last and (now - last) < cool:
        return "", "换道冷却中（还剩 %d 分钟）" % int((cool - (now - last)) // 60 + 1)
    return app, "行为型挑战 %s → 改走 %s（第 %d/%d 次）" % (kind, app, used + 1, cap)


def state(plat: str, cfg: dict = None, *, user_data_dir: str = "user_data",
          now: float = None) -> dict:
    """换道的判据输入（r1063 T50）：**界面据此解释"凭什么换 / 为什么不换"**。

    与 `plan_switch` 用同一个账本、同一组参数——读数与决策同源，才不会出现
    "界面说还能换、实际不换"这种最难查的不一致。
    """
    now = float(now if now is not None else time.time())
    plat = str(plat or "").strip()
    app = app_counterpart(plat)
    try:
        cap = int(_num("app_fallback.daily_switches", plat, cfg,
                       "daily_switches", 6))
    except (TypeError, ValueError):
        cap = 6
    try:
        cool = int(_num("app_fallback.cooldown_s", plat, cfg, "cooldown_s",
                        1200))
    except (TypeError, ValueError):
        cool = 1200
    rec = {}
    try:
        data = _load(ledger_path(user_data_dir))
        rec = data.get(plat) if isinstance(data.get(plat), dict) else {}
    except Exception:
        rec = {}
    day = time.strftime("%Y%m%d", time.localtime(now))
    used = int(rec.get("day_used") or 0) if rec.get("day") == day else 0
    last = float(rec.get("last_at") or 0)
    left_s = max(0, int(cool - (now - last))) if (cool > 0 and last) else 0
    return {
        "plat": plat,
        "app": app,
        "enabled": bool(_enabled(plat, cfg)),
        "cap": cap,
        "used": used,
        "left": max(0, cap - used) if cap > 0 else -1,
        "cooldown_s": cool,
        "cooldown_left_s": left_s,
        "last_at": last,
        "last_app": str(rec.get("last_app") or ""),
        "last_ok": bool(rec.get("last_ok")),
    }


def states(plats, cfg: dict = None, *, user_data_dir: str = "user_data",
           now: float = None) -> dict:
    """批量版 `state()`：`{渠道: 判据输入}`，只给**有 App 孪生**的渠道。"""
    out = {}
    for p in sorted(set(str(x) for x in (plats or ()))):
        if not app_counterpart(p):
            continue
        try:
            out[p] = state(p, cfg, user_data_dir=user_data_dir, now=now)
        except Exception:
            continue
    return out


def preload_targets(scenes: dict, plats, cfg: dict = None, *,
                    user_data_dir: str = "user_data", now: float = None,
                    logger=None) -> dict:
    """本轮要**预置**的 App 孪生：`{源渠道: App渠道}`。

    为什么要预置：不预置的话，换道只能在"整波跑完 → 发现被拦 → 再补采"发生，
    等于白等一个完整往返；预置把它变成"两条通路从第一秒就并行"。

    每轮只决策一次（并 `note_switch` 记一次）：按查询数记账会把每日上限瞬间
    用光，那样上限就从"防横跳"退化成"第一查询就用完"。
    """
    plats = set(str(x) for x in (plats or ()))
    out = {}
    scenes = scenes if isinstance(scenes, dict) else {}
    for src in sorted(plats):
        kind = str((scenes.get(src) or {}).get("kind") or "")
        if not is_behavior_block(kind):
            continue
        app, why = plan_switch(src, kind, cfg, user_data_dir=user_data_dir,
                               now=now, running=plats)
        if not app:
            continue
        out[src] = app
        note_switch(src, app, ok=True, user_data_dir=user_data_dir, now=now)
        if logger is not None:
            try:
                logger.info("[换道] 本轮预置 %s → %s：%s", src, app, why)
            except Exception:
                pass
    # 成效入账（r1063 T51）：跨进程账本记一天预置了几家。
    if out:
        try:
            from core import strategy_ledger as _led
            _led.record_failover(preloads=len(out), root=user_data_dir)
        except Exception:
            pass
    return out


def note_switch(plat: str, app: str = "", *, ok: bool = True,
                user_data_dir: str = "user_data", now: float = None) -> None:
    """记一次换道决策（成功或失败都记：失败也要占预算，否则会无限重试）。"""
    plat = str(plat or "").strip()
    if not plat:
        return
    now = float(now if now is not None else time.time())
    path = ledger_path(user_data_dir)
    data = _load(path)
    rec = data.get(plat) if isinstance(data.get(plat), dict) else {}
    day = time.strftime("%Y%m%d", time.localtime(now))
    if rec.get("day") != day:
        rec["day"], rec["day_used"] = day, 0
    rec["day_used"] = int(rec.get("day_used") or 0) + 1
    rec["last_at"] = now
    rec["last_app"] = str(app or "")
    rec["last_ok"] = bool(ok)
    data[plat] = rec
    _save(path, data)

def browser_counterpart(app: str) -> str:
    """某 App 渠道对应的**浏览器**渠道 id（反补用）；没有就返回空串。

    与 `app_counterpart()` 互为反函数，同样从注册表派生，不写死映射表。
    """
    p = str(app or "").strip()
    if not p.startswith("app_"):
        return ""
    want = p[len("app_"):]
    try:
        from crawlers import REGISTRY
        if want in REGISTRY and not str(want).startswith("app_"):
            return want
    except Exception:
        pass
    return ""


def _app_blocked(app: str, user_data_dir: str = "user_data") -> tuple:
    """该 App 渠道现在是不是"根本跑不动"（登录墙 / 设备掉了 / 崩溃）。

    返回 `(blocked, 原因)`。读的是采集侧同一份状态（`login_wall` 服务状态 +
    `app_gone` 熔断），不另建口径——否则"面板说能跑、兜底说不跑"。
    """
    import os as _os
    root = str(user_data_dir or "user_data")
    try:
        from core import service_state as _ss
        if _ss.until(root, app, "login_wall") > 0:
            return True, "登录墙未解"
        if _ss.until(root, app, "app_gone") > 0:
            return True, "App 不在前台/崩溃"
    except Exception:
        pass
    try:
        p = _os.path.join(root, app, "login_wall.json")
        if _os.path.isfile(p):
            return True, "登录墙未解"
    except Exception:
        pass
    return False, ""


def plan_backstop(app: str, cfg: dict = None, *, user_data_dir: str = "user_data",
                  now: float = None, running=(), blocked=None) -> tuple:
    """要不要让 `app` 这一轮由**同名浏览器渠道**反补。返回 `(browser, 原因)`。

    判据（任一不满足就不补）：
      1. 它有浏览器孪生，且孪生**不在**本轮已在跑的渠道里；
      2. 它现在确实跑不动（登录墙 / app_gone）；
      3. 开关开着（`app_fallback.enabled`，可按渠道覆盖）；
      4. 今日反补次数 < `daily_switches`（沿用同一预算，防把浏览器路打爆）；
      5. 不在冷却里（防来回横跳）。
    """
    now = float(now if now is not None else time.time())
    app = str(app or "").strip()
    if not app.startswith("app_"):
        return "", "不是 App 渠道"
    browser = browser_counterpart(app)
    if not browser:
        return "", "这家没有浏览器通路"
    # r1063 T203：**目标必须还活着**。真机第一炮反补到了 qunar（永久停服），
    # 请求进黑洞还要占额度。
    try:
        from core.advise import is_retired as _ret
        if _ret(browser):
            return "", "目标渠道已停服（%s），不反补" % browser
    except Exception:
        pass
    if browser in tuple(str(x) for x in (running or ())):
        return "", "浏览器通路本轮已在跑（不重复采）"
    # blocked 优先用调用方注入的事实（来自 pacing 快照的"0 成功率且样本够"），
    # 因为它比读文件更接近真相：携程 App 是"首页有会员、**搜索时**弹手机
    # 验证码登录"，文件里根本没有墙。
    if blocked is None:
        blocked, why = _app_blocked(app, user_data_dir)
    else:
        blocked, why = True, "通路 0 成功率（调用方注入）"
    if not blocked:
        return "", "App 通路尚可用（不需要反补）"
    if not _enabled(app, cfg):
        return "", "换道开关已关（app_fallback.enabled=false）"
    path = ledger_path(user_data_dir)
    data = _load(path)
    rec = data.get("backstop:" + app)
    rec = rec if isinstance(rec, dict) else {}
    day = time.strftime("%Y%m%d", time.localtime(now))
    used = int(rec.get("day_used") or 0) if rec.get("day") == day else 0
    cap = 6
    try:
        from core.strategy_params import resolve as _r
        cap = int(_r("app_fallback.daily_switches", plat=app).value or 6)
    except Exception:
        pass
    if used >= max(1, cap):
        return "", "今日反补次数已用完（%d/%d）" % (used, cap)
    last = float(rec.get("last_at") or 0)
    if last and now - last < 20 * 60:
        return "", "反补冷却中（%d 分钟）" % int((20 * 60 - (now - last)) / 60)
    return browser, "%s → %s（%s）" % (app, browser, why)
