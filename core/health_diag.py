# -*- coding: utf-8 -*-
"""Evidence-first channel diagnosis.

The UI must not turn an absent round or an unclassified failure into a green
"normal" card. Inputs are the parsed last round, login state and a local
cookie-state hint; no network calls and no synthetic log lines live here.
"""
# 渠道集合与中文名统一来自 core/channels.py（单一事实源）：
# 曾在此另写一份，新增渠道时漏改就会出现「能采但界面露裸 id」。
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_CN as CN  # noqa: E402

PLATFORMS = BROWSER_CHANNELS

_IP = ("179991", "风控", "限流", "403", "429", "ip封", "IP封")
_CAPTCHA = ("验证码", "滑块", "人机", "challenge", "captcha")
_LOGIN = ("未登录硬拒", "请登录", "需登录", "登录失效", "会话失效",
          "login_required")
_EMPTY = ("没有查询到符合条件的航班", "未查询到", "无航班", "no flight")
_TIMEOUT = ("超时", "timeout")
# **本机环境故障**（不是渠道的问题）：代理挂了、DNS 不通、浏览器进程被关。
# 真账本实证（2026-11-01，fliggy H5）：note 写着
# `Page.goto: net::ERR_PROXY_CONNECTION_FAILED`，健康卡却归成「抓取失败
# （原因待核对）」并建议「打开原站核实 IP/风控/登录」——把**我们自己的
# 代理故障**指成渠道风控，用户会去换网络/重登，问题却在本机。
# 关键词只收网络栈层面的错误，避免吞掉真正的限流/风控措辞。
_ENV_FAULTS = ("err_proxy_connection_failed", "err_tunnel_connection_failed",
               "err_name_not_resolved", "err_internet_disconnected",
               "err_connection_refused", "err_connection_reset",
               "targetclosederror", "browser has been closed",
               "executable doesn't exist")


def _card(plat, kind, label, action, rp, note="", evidence=""):
    rp = rp or {}
    return {
        "plat": plat, "name": CN.get(plat, plat), "kind": kind,
        "label": label, "action": action,
        "s": rp.get("s") or "", "ok": int(rp.get("ok") or 0),
        "tot": int(rp.get("tot") or 0),
        "detail": int(rp.get("detail") or 0),
        "cal": int(rp.get("cal") or 0),
        "login": "", "cookie": "",
        "evidence": str(evidence or note or rp.get("note") or "")[:160],
    }


def _challenge_evidence(ch):
    """账本拦截的可核对证据：时刻 · 入口 · 原文。"""
    ch = ch or {}
    return " · ".join(x for x in (str(ch.get("at") or ""),
                                  str(ch.get("path") or ""),
                                  str(ch.get("note") or "")) if x)[:160]


def classify_round(plats, login=None, cookie=None,
                   all_plats=PLATFORMS):
    login = login or {}
    cookie = cookie or {}
    cards = []
    for p in all_plats:
        rp = (plats or {}).get(p)
        lg = login.get(p) or {}
        lg_status = str(lg.get("status") or
                        ("login_required" if lg.get("needs_login") else ""))
        ck = str(cookie.get(p) or "")
        # 账本里的滑块拦截（`fetch_paths`）与「本轮日志」是两份事实：
        # 同一轮另一张成功时整轮是 ok，卡若只看日志就写「最近一轮正常」，
        # 而搜索路径实际被滑块挡着（现场 2026-11-01 22:21 途牛 PC）。
        _ch = lg.get("challenge") or {}
        _ch_cap = _ch if str(_ch.get("kind") or "") == "captcha" else {}
        # 登录态失效**优先于**「本轮未扫描」：快照已失效时，等下一轮也没用，
        # 卡片必须直接指向重登（现场：重启后本轮不含 App，卡显示「未扫描」，
        # 而账本早已是 login）。
        _expired = bool(lg.get("needs_login") or lg_status == "login_required")
        _act = ("去「渠道登录」内嵌画面重新登录"
                if p in APP_CHANNELS else "重新登录并保存会话")
        if not rp:
            if _ch_cap:
                c = _card(p, "captcha", "需要人工验证",
                          "打开渠道可见窗口完成验证", rp,
                          evidence=_challenge_evidence(_ch_cap))
            elif _expired:
                c = _card(p, "login", "登录态失效", _act, rp)
            elif ck == "expired":
                c = _card(p, "cookie_expired", "Cookie 已过期",
                          "重新登录并保存会话", rp)
            else:
                c = _card(p, "unscanned", "本轮未扫描",
                          "等待下一轮或手动扫描", rp)
        else:
            s = str(rp.get("s") or "")
            note = str(rp.get("note") or "")
            low = note.lower()
            c = None
            if s == "maint":
                c = _card(p, "maintenance", "渠道维护", "等待渠道恢复", rp)
            elif any(k.lower() in low for k in _IP):
                c = _card(p, "ip", "IP/频率风控",
                          "停止重试，等待冷却或更换出口网络", rp)
            elif _ch_cap:
                # 本轮日志可能是 ok（另一张成功），账本才是被拦的那条路径。
                c = _card(p, "captcha", "需要人工验证",
                          "打开渠道可见窗口完成验证", rp,
                          evidence=_challenge_evidence(_ch_cap))
            elif any(k.lower() in low for k in _CAPTCHA):
                c = _card(p, "captcha", "需要人工验证",
                          "打开渠道可见窗口完成验证", rp)
            elif "渠道软拒" in note:
                c = _card(p, "empty", "渠道软拒/已退避",
                          "下轮自动重试；不要据此换日期或重登", rp,
                          evidence=note)
            elif (s == "empty"
                  or any(k.lower() in low for k in _EMPTY)):
                c = _card(p, "empty", "无符合条件的航班",
                          "换日期/航线再试；不要据此重登", rp)
            elif _expired or any(k in note for k in _LOGIN):
                c = _card(p, "login", "登录态失效", _act, rp)
            elif any(k in low for k in _ENV_FAULTS):
                c = _card(p, "env", "本机网络/代理故障",
                          "检查代理与网络后重试；这不是该渠道的问题", rp)
            elif (any(k.lower() in low for k in _TIMEOUT)
                  or s == "timeout"):
                c = _card(p, "timeout", "上游超时",
                          "稍后重试；查看该轮日志确认耗时", rp)
            elif s == "part":
                c = _card(p, "partial", "部分成功",
                          "查看失败日期/渠道；不要重登整渠道", rp)
            elif ck == "expired":
                c = _card(p, "cookie_expired", "Cookie 已过期",
                          "重新登录并保存会话", rp)
            elif s == "ok" and int(rp.get("detail") or 0) > 0:
                c = _card(p, "ok", "最近一轮正常", "无需操作", rp)
            elif s == "ok" and int(rp.get("cal") or 0) > 0:
                c = _card(p, "calendar_only", "仅日历价",
                          "需真实明细请发起探针", rp)
            elif s == "ok":
                c = _card(p, "ok", "最近一轮正常", "无需操作", rp)
            else:
                c = _card(p, "unknown", "抓取失败（原因待核对）",
                          "打开原站核实 IP/风控/登录；查看该轮日志", rp)
        c["login"] = lg_status or ("saved" if lg.get("saved") else "")
        c["cookie"] = ck
        cards.append(c)
    return cards
