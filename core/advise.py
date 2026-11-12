"""自动诊断：`python -m core.advise`（r1063 T163）

objective 原话有"**一切可建议 / 一切可意图理解**"。现在尺子很多
（`channel_matrix` / `--trend` / `--dates` / `--login` / `--slider` +
降级项 + 配置开关），但要人自己拼。这个模块把**已有事实**合成一份
"现在最该做什么"，每条都带命令和依据，不产生任何新采集。

设计原则：
* **只读**：不改配置、不发请求、不点按钮；
* **排序有依据**：先"能马上换来数据"的（登录/清墙），再"省钱"的（熔断/停服），
  最后"观察"的（口径/趋势）；
* **不装懂**：拿不到实例、没数据时直接说"看不到"，不猜。
"""
from __future__ import annotations

import json
import urllib.request

DEFAULT_PORTS = (8765, 8000, 5000)


def _get(base: str, path: str, timeout: float = 20.0) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def collect(port: int = 0) -> dict:
    """抓一次现场：pacing + 登录槽位（拿不到就如实空）。"""
    ports = [port] if port else list(DEFAULT_PORTS)
    err = ""
    for p in ports:
        base = "http://127.0.0.1:%d" % p
        try:
            pacing = _get(base, "/api/pacing")
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:40])
            continue
        slots = {}
        try:
            slots = (_get(base, "/api/login-state") or {}).get("slots") or {}
        except Exception:
            slots = {}
        return {"ok": True, "port": p, "pacing": pacing, "slots": slots}
    return {"ok": False, "why": "连不上实例：" + err}


def _need_login(slots: dict) -> list:
    out = []
    for key, v in (slots or {}).items():
        if isinstance(v, dict) and v.get("needs_login"):
            out.append({"slot": key,
                        "surface": str(v.get("surface_label") or ""),
                        "url": str(v.get("login_url") or "")})
    return sorted(out, key=lambda x: x["slot"])


#: 这些措辞说明是**能力边界/设计取舍**，不是"被拦"，不该进建议清单。
BOUNDARY_HINTS = ("不查", "不回填", "超出 App 视野", "停服", "不支持",
                  "视野", "不供")


def _is_boundary(text: str) -> bool:
    t = str(text or "")
    return any(k in t for k in BOUNDARY_HINTS)


def is_retired(plat: str) -> bool:
    """该渠道是否**永久停服已退役**（唯一口径：`core.setup_check._is_retired`）。

    这类渠道的"0 成功率"是**设计结果**，不该出现在"今天该做什么"里
    （否则用户会去清墙/换 IP，全是白费）。
    """
    # 网页版去哪儿 PC/H5 已永久停服（2026-10/11）：这是产品事实，
    # 不能依赖某台机器 user_data 里的运行期记忆；CI/新装环境也必须认。
    if str(plat or "").strip() == "qunar":
        return True
    try:
        from core import setup_check as _sc
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        return bool(_sc._is_retired(root, plat))
    except Exception:
        return False


def _why_text(v) -> str:
    """渠道/通路的原因字段可能是字符串，也可能是 `{state,hint,...}` 字典。

    字典直接摊在界面上会变成 `{'state': 'login', ...}` 这种噪声——取 `hint`
    （人话）优先，其次 `state`。
    """
    if isinstance(v, dict):
        for k in ("hint", "detail", "state"):
            if v.get(k):
                return str(v[k])
        return ""
    return str(v or "")


def _blocked_channels(pacing: dict) -> list:
    """被拦/需登录/超时的渠道（按降级项 + 渠道 advice）。"""
    out = []
    for plat, ch in sorted((pacing.get("channels") or {}).items()):
        if not isinstance(ch, dict):
            continue
        if ch.get("needs_login"):
            out.append({"plat": plat, "why": "需登录",
                        "advice": _why_text(ch.get("advice"))[:70]})
            continue
        for path, pv in (ch.get("paths") or {}).items():
            if not isinstance(pv, dict):
                continue
            rate = pv.get("rate")
            try:
                rate_f = float(rate) if rate is not None else None
            except (TypeError, ValueError):
                rate_f = None
            why = _why_text(pv.get("why"))
            n = int(pv.get("attempts") or 0)
            if rate_f is None or rate_f > 0.0:
                continue
            if n < 3:                    # 样本太少，别当结论
                continue
            if _is_boundary(why):        # 能力边界 ≠ 被拦
                continue
            if is_retired(plat):         # 已永久停服/退役 → 不是"今天被拦"
                continue
            out.append({"plat": plat, "why": "通路 0 成功率（%s）" % path,
                        "advice": why[:70]})
            break
    return out


def advise(rep: dict) -> dict:
    """把现场事实翻成"带命令的建议"，按优先级排序。"""
    if not rep.get("ok"):
        return {"ok": False, "why": rep.get("why"), "items": []}
    pacing = rep.get("pacing") or {}
    slots = rep.get("slots") or {}
    degraded = pacing.get("degraded") or {}
    items = []

    need = _need_login(slots)
    if need:
        items.append({
            "rank": 1, "kind": "login",
            "title": "有 %d 个槽位需要登录（这是唯一能立刻换来数据的动作）"
                     % len(need),
            "detail": "、".join(x["slot"] for x in need),
            "cmd": "面板「渠道健康 → 渠道登录」点对应槽位；"
                   "或用 `python -m core.channel_matrix --login` 看入口",
        })

    if degraded.get("app_risk_blocked"):
        items.append({
            "rank": 2, "kind": "app_risk",
            "title": "App 侧被风控/需登录（%s 次）"
                     % (degraded["app_risk_blocked"].get("n")),
            "detail": str(degraded["app_risk_blocked"].get("last") or "")[:80],
            "cmd": "先登录——**App 的登录要在搜索弹出的页面完成**"
                   "（首页显示会员/积分≠搜索可用：携程/飞猪一进搜索就要求"
                   "手机验证码登录）；登录后仍拦就用同名浏览器通路"
                   "（App 通道要彻底通只有真机，见 docs/APP_RISK_VERDICT.md）",
        })

    blocked = _blocked_channels(pacing)
    if blocked:
        names = "、".join(sorted({b["plat"] for b in blocked})[:6])
        items.append({
            "rank": 3, "kind": "blocked",
            "title": "这些渠道有通路 0 成功率：%s" % names,
            "detail": "；".join("%s：%s" % (b["plat"], b["advice"]) for b in blocked[:3]),
            "cmd": "`python -m core.channel_matrix` 看每条通路原因；"
                   "试 `POST /api/channel/clear-wall` 立刻重试；"
                   "App 渠道先跑 `python -m core.app_check` 用设备实况对账"
                   "（首页已登录但搜索仍要登录是常态）",
        })

    if degraded.get("device_env"):
        items.append({
            "rank": 4, "kind": "device_env",
            "title": "设备环境有矛盾（会持续拉低风控分）",
            "detail": str(degraded["device_env"].get("last") or "")[:80],
            "cmd": "`python -m core.android.consistency` 看明细；"
                   "改完身份要 `python scripts/identity_boot_module.py` 再重启实例",
        })

    if degraded.get("app_layout"):
        items.append({
            "rank": 5, "kind": "app_layout",
            "title": "App 认屏失败累计 %s 次（可能是改版）"
                     % (degraded["app_layout"].get("n")),
            "detail": str(degraded["app_layout"].get("last") or "")[:80],
            "cmd": "`POST /api/channel/probe {\"platform\":\"app_xxx\"}` 取真实页面证据",
        })

    items.append({
        "rank": 9, "kind": "observe",
        "title": "日常观察三件套",
        "detail": "矩阵看现状 / 趋势看有没有变好 / 日期看缺口与口径",
        "cmd": "`python -m core.channel_matrix`、`--trend --hours 6`、`--dates`",
    })
    return {"ok": True, "port": rep.get("port"), "items": items}


def _text(rep: dict) -> str:
    if not rep.get("ok"):
        return "✗ 看不到实例现场：%s" % rep.get("why")
    items = rep["items"]
    if not items:
        return "（没有需要处理的项）"
    out = ["现在最该做的（按收益排序，实例 127.0.0.1:%s）" % rep.get("port"), ""]
    for it in items:
        out.append("%d. %s" % (it["rank"], it["title"]))
        if it.get("detail"):
            out.append("   依据：%s" % it["detail"])
        out.append("   怎么做：%s" % it["cmd"])
        out.append("")
    out.append("说明：只读诊断，不改配置、不发请求。")
    return "\n".join(out)


def main(argv=None):                                     # pragma: no cover
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    port = 0
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    rep = advise(collect(port))
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep.get("ok") else 1
    print(_text(rep))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())

def top_from_pacing(pacing: dict) -> list:
    """从**已有的 pacing 载荷**算出"最该做的两条"（不发起任何请求）。

    与 `advise()` 同源判据（能力边界不算被拦、已退役不算今天被拦），
    只是输入换成现成载荷，供面板在同一屏里显示。
    """
    out = []
    if not isinstance(pacing, dict):
        return out
    degraded = pacing.get("degraded") or {}
    try:
        blocked = _blocked_channels(pacing)
    except Exception:
        blocked = []
    if blocked:
        names = "、".join(sorted({b["plat"] for b in blocked})[:3])
        out.append({"kind": "blocked",
                    "text": "被拦/0 成功率：%s（点该家「自检」看真实原因）" % names})
    if degraded.get("app_risk_blocked"):
        out.append({"kind": "app_risk",
                    "text": "App 被风控/需登录：登录要在**搜索弹出的页面**完成"
                            "（首页会员态不算）"})
    if degraded.get("device_env"):
        out.append({"kind": "device_env",
                    "text": "设备脸有矛盾：python -m core.android.consistency 看明细"})
    # 面板是纯文本：Markdown 的星号会原样露出来（实测「登录要在**搜索弹出」）。
    for _it in out:
        _it["text"] = str(_it.get("text") or "").replace("**", "")
    return out[:2]

def weak_paths(pacing: dict, limit: int = 3, min_n: int = 5,
               ceiling: float = 0.9) -> list:
    """从 pacing 载荷挑"最该修的通路"（按损失量 = (1-成功率)×次数）。

    与 `advise()` **同一套判据**（这是关键）：
    * 能力边界（unsupported / 停服 / 不支持…）**不算弱环**——那是"本来就做不到"，
      让用户去修不存在的东西只会浪费时间。现场反例：`tuniu·PC 0%/45` 全是
      `unsupported`，一度被前端当成弱环显示；
    * 已退役渠道不算；
    * 样本 < `min_n` 不下结论；
    * 成功率 >= `ceiling` 的通路不算弱环（别刷存在感）。
    """
    out = []
    for plat, ch in (pacing.get("channels") or {}).items():
        if not isinstance(ch, dict):
            continue
        try:
            if is_retired(plat):
                continue
        except Exception:
            pass
        for path, pv in (ch.get("paths") or {}).items():
            if not isinstance(pv, dict):
                continue
            n = int(pv.get("attempts") or 0)
            if n < min_n:
                continue
            try:
                rate = float(pv.get("rate"))
            except (TypeError, ValueError):
                continue
            if rate >= ceiling:
                continue
            why = _why_text(pv.get("why"))
            st = str(pv.get("status") or "")
            # r1063 T197b：边界判定必须以**成功率为 0**为前提。
            # 反例（真机）：tuniu H5/API 73%/62 次，而 why 里带的是渠道级提示
            # 「>30 天的 PC 不查」，被 _is_boundary 命中 → 面板一条弱环都不显示。
            # 道理很直白：有产出的通路不可能是"能力边界"。
            if rate <= 0.0 and (st in ("unsupported", "retired")
                                or _is_boundary(why)):
                continue
            out.append({"plat": plat, "path": str(path), "rate": rate,
                        "attempts": n, "why": why[:60],
                        "loss": (1.0 - rate) * n})
    out.sort(key=lambda x: -x["loss"])
    # r1063 T201：**按渠道去重**再取前 N。
    # 真机反例：app_fliggy/app_ctrip 的几条通路把 3 个名额占满，
    # `tuniu·H5/API 74%/66` 完全看不见——同渠道多条不该垄断名额。
    seen, uniq = set(), []
    for it in out:
        if it["plat"] in seen:
            continue
        seen.add(it["plat"])
        uniq.append(it)
    return uniq[:limit]

_COVER_CACHE = {"at": 0.0, "rows": []}


def date_cover(hours: int = 12, limit: int = 6, db: str = "") -> list:
    """近 N 小时各渠道覆盖的**出发日期数**（面板一行用，30 秒缓存）。

    与 `core.channel_matrix.date_coverage()` 同源（都读 `fetch_paths`），
    但只取 `count(distinct depart_date)` ——面板每 2 秒轮询，不能每次打整张网格。
    """
    import os as _os
    import sqlite3 as _sq
    import time as _t
    now = _t.time()
    if now - float(_COVER_CACHE.get("at") or 0) < 30:
        return list(_COVER_CACHE.get("rows") or [])
    db = db or _os.path.join("data", "prices.db")
    if not _os.path.isfile(db):
        return []
    hours = max(1, min(int(hours or 12), 168))
    try:
        conn = _sq.connect("file:%s?mode=ro" % db, uri=True)
    except Exception:
        return []
    try:
        # **必须查 flight_prices**：`fetch_paths` 只记"请求的那一天"，
        # 整窗收割出来的另外 60+ 天在价格表里（查错表会得出"每家都 4 天"的假象）。
        rows = list(conn.execute(
            "select platform, count(distinct depart_date) d, count(*) n "
            "from flight_prices where fetched_at >= datetime('now','localtime', "
            "'-%d hours') and depart_date != '' "
            "group by platform order by d desc limit %d" % (hours, int(limit))))
    except Exception:
        rows = []
    finally:
        conn.close()
    out = [{"plat": r[0], "days": int(r[1] or 0), "rows": int(r[2] or 0)}
           for r in rows]
    _COVER_CACHE["at"] = now
    _COVER_CACHE["rows"] = out
    return out

def distance_advice(hours: int = 24, min_n: int = 6, gap: float = 0.25,
                    limit: int = 2, db: str = "") -> list:
    """同一渠道"近端能成、远端明显不行"的结构性建议（r1063 T268）。

    返回 [{plat, near_pct, far_pct, far_n, loss, text}]，按损失降序。
    口径与面板 `--dist` 同源（都按距今天数分桶），避免两套数字打架。
    """
    import datetime as _dt
    import os as _os
    import sqlite3 as _sq

    db = db or _os.path.join("data", "prices.db")
    if not _os.path.isfile(db):
        return []
    hours = max(1, min(int(hours or 24), 336))
    try:
        conn = _sq.connect("file:%s?mode=ro" % db, uri=True)
    except Exception:
        return []
    try:
        rows = list(conn.execute(
            "select platform, depart_date, path_status, count(*) n "
            "from fetch_paths where fetched_at >= datetime("
            "'now','localtime','-%d hours') and depart_date != '' "
            "group by platform, depart_date, path_status" % hours))
    except Exception:
        return []
    finally:
        conn.close()

    today = _dt.date.today()
    acc = {}
    for plat, dd, st, n in rows:
        try:
            dist = (_dt.date.fromisoformat(str(dd)) - today).days
        except Exception:
            continue
        if dist <= 30:
            k = "near"
        elif dist >= 61:
            k = "far"
        else:
            continue
        a = acc.setdefault(plat, {"near": [0, 0], "far": [0, 0]})
        a[k][1] += n
        if st in ("ok", "calendar"):
            a[k][0] += n

    out = []
    for plat, a in acc.items():
        (nok, ntot), (fok, ftot) = a["near"], a["far"]
        if ntot < min_n or ftot < min_n:
            continue
        nr = nok / ntot
        fr = fok / ftot
        if nr < 0.6 or (nr - fr) < gap:
            continue
        out.append({
            "plat": plat,
            "near_pct": round(nr * 100), "far_pct": round(fr * 100),
            "far_n": ftot, "loss": round((nr - fr) * ftot, 1),
            "text": ("%s 远日期成功率 %d%%，近端 %d%%（%d 次样本）："
                     "建议把该家视野收窄、远端交浏览器"
                     % (plat, round(fr * 100), round(nr * 100), ftot)),
        })
    out.sort(key=lambda x: -x["loss"])
    return out[:max(0, int(limit))]
