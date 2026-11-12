# -*- coding: utf-8 -*-
"""策略建议器：把「数字」翻成「下一步动作」+ 一句中文短句（≤40 字）。

为什么单独一个模块
------------------
`core/pacing.py::advise()` 是**节奏域**的老建议器（看账本、算成功率、拼
`action/severity/hint`），它只懂节奏那几件事。策略控制面要的是**逐条策略**
的建议：这条策略现在是什么状态、下一步该点哪个按钮。把两件事塞进一个函数，
结果是「每条策略都说同一句『建议观察』」——那正是「只出数字不出动作」的另一种
写法（Spec §4 的 `advisable` 轴要的就是动作码）。

所以本模块只管三件事，且**一一对应真实入口**：

1. `ACTIONS`：允许的动作码（词表写死在这里，别在界面里另拼字符串）；
2. `advise(sid, ctx)`：`{action, text}`，`action ∈ ACTIONS`、`text` 是 ≤40 字的
   中文短句。按**策略**分化，不按「族」糊成一句（同族两条策略的下一步常常
   完全不同：`rate_min_gap` 该「解除冷却」，`rate_per_minute` 该「调上限」）；
3. `route_of(action)`：动作码 → **真实路由**（`webui.py` 里 `self.path == "…"`
   那一批）。建议说「点立即扫」就必须真能点到 `/api/run`，否则建议是空气
   （Spec §4 的 `intervenable` 轴逐条核对路由字面量）。

三条边界（写在这里，免得后面有人「顺手补全」）
---------------------------------------------
* **不执行、不写配置**：建议只是建议。停手/恢复/解除走运行期干预路由，参数
  改动一律回 `POST /api/config`（Spec §6(c)：写路径只有一个）。
* **只建议类策略不编动作**：`rotate_advice` 的动作是 `rotate`——它没有执行
  入口（换身份要人决定，Q6 裁决），所以 `route_of("rotate")` 返回空串，界面
  据此只显示文案、不出按钮。
* **文案不抄目录**：`label`/`intent`/`effect` 已在 `core/strategy_contract.py`
  里、由 `/api/strategy` 直出；本模块说的是**此刻该做什么**，与那三句
  「它是什么/防什么/改了会怎样」不重叠（重复一份就会两处互相打脸）。

冒烟：`python -c "from core.strategy_advice import advise; print(advise('budget'))"`
"""
from __future__ import annotations

from typing import Dict, Tuple

# 动作码词表。加一个动作就必须同时给 `ROUTES` 里一条**真实存在**的路由
# （`rotate` 例外：它只有建议、没有执行入口，见模块文档第三条边界）。
ACTIONS: Tuple[str, ...] = (
    "none",       # 现在无需动作
    "config",     # 回配置页改参数（唯一写路径 POST /api/config）
    "run",        # 立刻跑一轮（穿透 TTL / 节奏 / 静默窗）
    "probe",      # 单次探针（探一条通路/一条航线）
    "cancel",     # 取消在跑的探针（省预算）
    "warmup",     # 先预热首页再采
    "selfcheck",  # 身份/出口自检
    "challenge",  # 打开挑战窗口人工过验证
    "login",      # 重登入口
    "halt",       # 人工停手（按渠道，N 分钟）
    "resume",     # 恢复：解除停手 / 解除自动冷却
    "rotate",     # 换身份（只建议，无执行入口）
)

# 动作码 → 真实路由（`webui.py` 的 `self.path == "…"` 里逐条核过）。
ROUTES: Dict[str, str] = {
    "run": "/api/run",
    "probe": "/api/channel/probe",
    "cancel": "/api/probe/cancel",
    "warmup": "/api/channel/warmup",
    "selfcheck": "/api/channel/selfcheck",
    "challenge": "/api/challenge/open",
    "login": "/api/login",
    "halt": "/api/strategy/halt",
    "resume": "/api/strategy/resume",
    "config": "/api/config",
    # `rotate` / `none` 没有执行入口：前者是人的决定（Q6 裁决），后者是
    # 「现在什么都不用做」。空串＝界面不出按钮，只显示文案。
    "rotate": "",
    "none": "",
}

# 逐条策略的默认建议：(动作码, 中文短句 ≤40 字)。
# 写的时候守两条：① 只说「下一步点哪里」，不复述 `intent`；② 同族不同句
# （`slider_attempt` 与 `slider_guard` 一个是「别硬刚」、一个是「已拉黑」）。
ADVICE: Dict[str, Tuple[str, str]] = {
    "ttl_tier": ("run", "慢档里的航线不会马上重抓：要现在看就点立即扫"),
    "near_window": ("config", "远端日期几乎不抓：把邻近比例与天数调大"),
    "cadence": ("run", "这家被渠道节奏压着：要立刻看就点立即扫，或调小该家"),
    "schedule_clock": ("config", "整点齐发太像机器：把扰动与错峰调大一点"),
    "quiet_window": ("run", "静默窗内整轮跳过：现在要采就点立即扫（穿透）"),
    "rate_min_gap": ("resume", "间隔把请求卡住了：点解除冷却，或调小最小间隔"),
    "rate_per_minute": ("config", "分钟上限用完了就排队：把上限调大再跑"),
    "concurrency": ("cancel", "并发压着不开新浏览器：卡住就点中断本轮"),
    "budget": ("cancel", "本轮预算花完会收工：还剩活就点取消探针，下一轮再来"),
    "breaker_switch": ("resume", "熔断开着会自己冷却：修配置时先关总开关"),
    "breaker_ladder": ("resume", "冷却会翻倍到封顶：卡太久点解除，别关熔断"),
    "login_cooldown": ("login", "撞登录墙后要歇一阵：确认账号能过验证再点重登"),
    "challenge_cooldown": ("challenge", "硬风控要停很久：点开挑战窗口人工过一次"),
    "health_penalty": ("selfcheck", "成功率掉下去会自动降频：先修预热再点自检"),
    "policy_gate": ("halt", "总闸门关着一条都不采：点停手/恢复放行一轮"),
    "pace_factor": ("resume", "风险档把间隔放到最慢：确认过验证后点恢复"),
    "block_window": ("resume", "停手窗口内不发请求：到期自恢复，或点恢复"),
    "risk_bands": ("login", "风险分居高要停手：人工过验证后重登，再点解除"),
    "warmup": ("warmup", "没预热就打深链最容易被拒：先点预热再采"),
    "stealth_humanize": ("selfcheck", "指纹与动作不一致更可疑：点身份自检看差在哪"),
    "identity_headers": ("selfcheck", "身份三件套对不上会进名单：点出口自检核对"),
    "proxy_route": ("selfcheck", "这家被限流会牵连全站：给它单配出口再自检"),
    "rotate_advice": ("rotate", "身份用久了风险累积：建议换一次，换前先过验证"),
    "slider_attempt": ("challenge", "滑块能过就过，卡住别硬刚：点开挑战窗口"),
    "slider_guard": ("challenge", "滑块连败已拉黑：人工过验证，明天再试"),
    "captcha_solve": ("challenge", "验证码没认过去：放大倍数调高，或人工开窗"),
    "path_fallback": ("probe", "某条通路被挡时换路：探一次确认剩下那条还通"),
    "retired_path": ("probe", "退役通路不再拖低成功率：疑错杀就探那条路"),
}

# 兜底：目录里没有这条策略时的建议（不抛异常——建议器炸了不该让整行消失）。
_UNKNOWN = ("config", "目录里没有这条策略：先核对参数目录再动手")


def route_of(action: str) -> str:
    """动作码 → 真实路由（空串＝只建议、无执行入口）。未知动作一律空串。"""
    return ROUTES.get(str(action or ""), "")


def advise(sid: str, ctx: dict = None) -> dict:
    """给一条策略「下一步做什么」：`{"action": <ACTIONS 之一>, "text": ≤40 字}`。

    `ctx` 是可选的**当下证据**（`enabled` / `wait_s` / `halt` / `quiet` /
    `level`）。有证据时按证据改口，没证据时给这条策略的默认动作——两条路都
    只返回一句人话，绝不自作主张执行任何东西：

    * `enabled is False` → 先说「已关」，动作给 `resume`（恢复开关才是下一步，
      继续按原策略建议等于假装它还开着；观测与留证照旧，见 Spec §2 推论）；
    * `halt`（人工停手生效中）→ 动作 `resume`，别再说「去停手」；
    * `wait_s > 0`（冷却中）→ 动作 `resume`，文案说清还要等多久；
    * `level` 到 `human`/`rotate` → 动作 `challenge`（人工过验证）优先于原动作；
    * `quiet`（静默窗内）→ 动作 `run`：手动立即扫是唯一能穿透的入口。

    其余情况原样返回默认：**不同策略不同句**，不许 28 条同一句（`advisable`
    轴要的是「有信息量的动作」）。
    """
    c = ctx if isinstance(ctx, dict) else {}
    base = ADVICE.get(str(sid or ""))
    if base is None:
        return {"action": _UNKNOWN[0], "text": _UNKNOWN[1]}
    action, text = base
    if c.get("enabled") is False:
        return {"action": "resume",
                "text": "这条策略已关：要恢复请点恢复（观测与留证照旧）"}
    if c.get("halt"):
        return {"action": "resume",
                "text": "人工停手生效中：确认过验证后点恢复立刻回到正常节奏"}
    try:
        wait = int(c.get("wait_s") or 0)
    except (TypeError, ValueError):
        wait = 0
    if wait > 0:
        return {"action": "resume",
                "text": "还在冷却，剩 %d 分钟：到期自动恢复，别手动硬顶" % wait}
    if str(c.get("level") or "") in ("human", "rotate"):
        return {"action": "challenge",
                "text": "风险已到人档：点开挑战窗口人工过一次，别让程序继续试"}
    if c.get("quiet"):
        return {"action": "run",
                "text": "现在是静默窗：要立刻采就点立即扫（手动穿透静默）"}
    return {"action": action, "text": text}


__all__ = ["ACTIONS", "ROUTES", "ADVICE", "advise", "route_of"]
