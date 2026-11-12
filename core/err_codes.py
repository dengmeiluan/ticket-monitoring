# -*- coding: utf-8 -*-
"""错误码 → 人话 → 三个动作（r1178）。

为什么要这个模块
----------------
用户看到的是 `请点击重试(error:x2VW8)`、`50003`、`710114/needLogin`、`HTTP 202`
这种字符串，页面上一句解释都没有——他没法判断"再点一次"有用没用、该换通路
还是该停手。仓库里其实**每个码都已经有人处理过**（各自写在 crawler / pacing /
verdict 文档里），只是没汇成一张表给界面用。

本模块只做"翻译 + 给出下一步"，**不新增任何判定逻辑**：
每个条目的 `doc` 字段必须指向真实出处，`kind` 必须落在下面 5 类里，
判定口径与 `core/pacing.py::_HARD_BLOCK_MARKS` 保持一致（硬风控 ≠ 解个码就过）。

约定
----
* `explain(x)` 从任意错误串里认码（`error:x2VW8` / `50003` / `710114`…），
  认不出就返回 `{"code": None, "kind": "unknown", ...}`——**不许编**。
* 每条必须有 3 个动作（不多不少）：页面按"下一步做什么"排序，不是给你堆解释。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

#: 只允许这 5 类（与 pacing 的硬风控/登录墙/挑战分层对齐）
KINDS = ("hard_block", "login_wall", "challenge", "retired", "transient")

KIND_CN = {
    "hard_block": "硬风控（重试会加重风险）",
    "login_wall": "登录墙（要人去登）",
    "challenge": "人机验证（简单可试，强人机停手）",
    "retired": "渠道停服（别再打）",
    "transient": "临时故障（可重试）",
}

#: 码 → 条目。`doc` 必须是仓库里真实存在的出处，改代码时顺手改这里。
ERR_CODES: Dict[str, dict] = {
    "50003": {
        "kind": "hard_block",
        "cn": "携程：环境存在风险",
        "why": ("携程对「账号 × 设备类别」做画像。两台不同模拟器、不同指纹、"
                "同一 IP 实测都是 50003——换身份 ≠ 换设备类别，所以换皮不解决。"),
        "acts": ["改走浏览器通路（PC / H5）",
                 "停该渠道并进入冷却，别再按小时重试",
                 "核对设备指纹自洽性（机型/ABI/GPU 是否自相矛盾）"],
        "doc": "docs/APP_RISK_VERDICT.md",
    },
    "x2VW8": {
        "kind": "challenge",
        "cn": "飞猪：阿里 NC 滑块判机器",
        "why": ("App 内滑块用单段直线 `input swipe` 会被判定为机器，"
                "回报 error:x2VW8；要走变速轨迹（appvcode）才可能过。"),
        "acts": ["用变速轨迹重试一次（只一次）",
                 "切 H5 / PC 通路继续拿数",
                 "仍不过就停手，等冷却后再人工拖一次"],
        "doc": "crawlers/app_base.py",
    },
    "710114": {
        "kind": "login_wall",
        "cn": "途牛：国内 listFlight 登录墙",
        "why": ("国内接口返回 710114/needLogin，说明该端会话不认；"
                "国际通道是独立判定，不受这个标记影响。"),
        "acts": ["先登录途牛对应端（PC / H5 各自一格）",
                 "国际航线可照常跑，不必等同一条通路",
                 "登录后点该槽位「立即核验」拿真实结论"],
        "doc": "crawlers/tuniu.py",
    },
    "22032": {
        "kind": "login_wall",
        "cn": "去哪儿：匿名态（userBaseInfo 未登录）",
        "why": ("userBaseInfo 在匿名态返回 ret=False / errcode=22032，登录态是 200。"
                "这是登录态探测，不是故障。"),
        "acts": ["网页端已停服，不要再登网页",
                 "要数据请走 App 通路（app_qunar）",
                 "不要反复探测——探测本身也是风控负担"],
        "doc": "crawlers/qunar.py",
    },
    "202": {
        "kind": "transient",
        "cn": "途牛 H5：HTTP 202 空壳",
        "why": "会话/边缘节点没给业务响应（202 无内容），不是价格为空。",
        "acts": ["原通路重试一次",
                 "改走 H5/API 通路",
                 "持续出现就按登录墙核验一次"],
        "doc": "core/channel_matrix.py",
    },
    "安全容器": {
        "kind": "hard_block",
        "cn": "阿里：安全容器白屏",
        "why": ("App 被切到 ContainerActivity 白屏——这是硬风控处置，"
                "不是页面改版，重试无用。"),
        "acts": ["停手，等冷却窗口",
                 "改走浏览器通路",
                 "记录证据后交给人工判断是否换设备"],
        "doc": "core/pacing.py",
    },
    "实名核验": {
        "kind": "hard_block",
        "cn": "账号被要求实名核验",
        "why": "服务端对账号的限制，只能本人处理；自动重试会加重风险分。",
        "acts": ["停该渠道采集",
                 "由账号本人完成核验",
                 "期间改走其它渠道取同一航线"],
        "doc": "core/pacing.py",
    },
}

#: 认码用的模式（顺序有意义：先长后短，避免 202 命中 22032）
_PATTERNS = (
    ("x2VW8", re.compile(r"x2VW8", re.I)),
    ("710114", re.compile(r"\b710114\b")),
    ("22032", re.compile(r"\b22032\b")),
    ("50003", re.compile(r"\b50003\b")),
    ("安全容器", re.compile(r"安全容器|ContainerActivity", re.I)),
    ("实名核验", re.compile(r"实名核验")),
    ("202", re.compile(r"\bHTTP\s*202\b|\b202\b")),
)


def explain(text: str) -> dict:
    """从任意错误串里认出码，返回统一结构；认不出就如实说 unknown。"""
    raw = str(text or "")
    for code, pat in _PATTERNS:
        if not pat.search(raw):
            continue
        item = ERR_CODES[code]
        return {"code": code, "kind": item["kind"], "kind_cn": KIND_CN[item["kind"]],
                "cn": item["cn"], "why": item["why"],
                "acts": list(item["acts"]), "doc": item["doc"],
                "matched": raw[:120]}
    return {"code": None, "kind": "unknown", "kind_cn": "未收录的错误码",
            "cn": "这个错误码还没有人翻译过",
            "why": ("先按下方三个动作做：不要连点、不要换身份重试；"
                    "把原始错误串连同时间贴进 issue，我们再补表。"),
            "acts": ["保持现场（别清缓存、别重登）",
                     "复制完整错误串与时间到 issue",
                     "换一条通路先拿到数据"],
            "doc": "", "matched": raw[:120]}


def table() -> List[dict]:
    """给界面用的整表（按 kind 分组用）。"""
    out = []
    for code, it in ERR_CODES.items():
        out.append({"code": code, "kind": it["kind"], "kind_cn": KIND_CN[it["kind"]],
                    "cn": it["cn"], "why": it["why"], "acts": list(it["acts"]),
                    "doc": it["doc"]})
    return out


def _self_check() -> Optional[str]:
    """开发自检：条目完整性（供测试和工作台调用）。"""
    for code, it in ERR_CODES.items():
        if it["kind"] not in KINDS:
            return "码 %s 的 kind 不在允许集合内：%s" % (code, it["kind"])
        if len(it["acts"]) != 3:
            return "码 %s 的动作必须是 3 条，实际 %d" % (code, len(it["acts"]))
        for f in ("cn", "why", "doc"):
            if not str(it.get(f) or "").strip():
                return "码 %s 缺字段 %s" % (code, f)
    return None
