# -*- coding: utf-8 -*-
"""Evidence-first channel diagnosis.

The UI must not turn an absent round or an unclassified failure into a green
"normal" card. Inputs are the parsed last round, login state and a local
cookie-state hint; no network calls and no synthetic log lines live here.
"""
PLATFORMS = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")
CN = {"ctrip": "携程", "qunar": "去哪儿", "fliggy": "飞猪",
      "tongcheng": "同程", "tuniu": "途牛"}

_IP = ("179991", "风控", "限流", "403", "429", "ip封", "IP封")
_CAPTCHA = ("验证码", "滑块", "人机", "challenge", "captcha")
_LOGIN = ("未登录硬拒", "请登录", "需登录", "登录失效", "会话失效",
          "login_required")
_EMPTY = ("没有查询到符合条件的航班", "未查询到", "无航班", "no flight")
_TIMEOUT = ("超时", "timeout")


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
        if not rp:
            if ck == "expired":
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
            elif any(k.lower() in low for k in _CAPTCHA):
                c = _card(p, "captcha", "需要人工验证",
                          "打开渠道可见窗口完成验证", rp)
            elif (s == "empty"
                  or any(k.lower() in low for k in _EMPTY)):
                c = _card(p, "empty", "无符合条件的航班",
                          "换日期/航线再试；不要据此重登", rp)
            elif (lg.get("needs_login") or lg_status == "login_required"
                  or any(k in note for k in _LOGIN)):
                c = _card(p, "login", "登录态失效",
                          "重新登录并保存会话", rp)
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
