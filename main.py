# -*- coding: utf-8 -*-
"""机票价格监控 主入口（多租户版）

用法:
    python main.py                # 按 config.yaml 启动定时监控
    python main.py --once         # 每条航线只跑一次后退出
    python main.py -c other.yaml  # 指定配置文件

多租户模型：采集与告警正交——
  采集层按 (航线, 日期) 去重共享（多人盯同航线只采一份），
  告警层按用户分发（各自的阈值 / 钉钉群 / @手机号）。
  去哪儿接口有 ~5 分钟全局限流（与航线无关），查询间错峰。
"""
import argparse

__version__ = "1.5.50"
import os
import subprocess
import sys
import time
import concurrent.futures
from pathlib import Path

import yaml

from core.logger import setup_logger
from core.models import Route
from core.storage import PriceStorage
from core.alerter import Alerter
from core.scheduler import run_scheduler
from core.notifier import build_notifier
from crawlers import REGISTRY


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_routes(routes_cfg: list) -> list:
    routes = []
    for r in routes_cfg or []:
        if r.get("enabled") is False:
            # 停用航线：配置保留在 config.yaml（心理线/日期不丢），
            # 不入运行时模型——调度、状态、明细、日历全链路自动豁免
            continue
        routes.append(Route(
            from_code=r["from"],
            from_name=r.get("from_name", r["from"]),
            to_code=r["to"],
            to_name=r.get("to_name", r["to"]),
            dates=list(r.get("dates", [])),
            alert_threshold=float(r.get("alert_threshold", 0) or 0),
            alert_direct=float(r.get("alert_direct", 0) or 0),
            alert_transfer=float(r.get("alert_transfer", 0) or 0),
            transfer_arrival_max=str(r.get("transfer_arrival_max", "02:00")),
            # 中转衔接下限与行李直挂必须传入 Route——漏传曾使主链路
            # （达标推送/总表/概览）的这两项配置整体失效（默认 0/""），
            # 而日报 dict 路径却生效，同一配置两条口径「时好时坏」
            transfer_layover_min=int(r.get("transfer_layover_min", 0) or 0),
            transfer_baggage=str(r.get("transfer_baggage", "") or ""),
            dep_time_min=str(r.get("dep_time_min", "") or ""),
            dep_time_max=str(r.get("dep_time_max", "") or ""),
        ))
    return routes


def build_users(cfg: dict) -> list:
    """归一化用户列表；兼容旧单用户格式（无 users 键则整体作为一个用户）。"""
    if "users" in cfg:
        raw_users = cfg["users"] or []
    else:
        raw_users = [{"name": "default", **{
            k: cfg[k] for k in ("routes", "platforms", "schedule", "notifier")
            if k in cfg}}]
    users = []
    for i, u in enumerate(raw_users):
        if not u.get("routes"):
            continue
        users.append({
            "name": str(u.get("name") or f"user{i+1}"),
            "routes": build_routes(u["routes"]),
            "platforms": u.get("platforms") or cfg.get(
                "platforms", ["qunar", "fliggy", "tongcheng", "tuniu"]),
            "notifier": u.get("notifier") or {},
            "schedule": u.get("schedule") or cfg.get("schedule") or {},
        })
    return users


def ensure_chromium(platforms, logger=None):
    """playwright 系平台启用时确保 chromium 内核就绪（幂等；缺失自动下载）。"""
    if not ({"qunar", "ctrip", "tongcheng"} & set(platforms or [])):
        return
    try:
        import playwright
    except ImportError:
        return
    if getattr(sys, "frozen", False):
        # 冻结态 playwright 默认找驱动目录下 .local-browsers；
        # 显式指向全局注册表，使安装与启动同轨
        os.environ.setdefault(
            "PLAYWRIGHT_BROWSERS_PATH",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"))
    os.environ.setdefault(
        "PLAYWRIGHT_DOWNLOAD_HOST",
        "https://cdn.npmmirror.com/binaries/playwright")
    pkg = os.path.dirname(playwright.__file__)
    node = os.path.join(pkg, "driver", "node.exe")
    cli_js = os.path.join(pkg, "driver", "package", "cli.js")
    if os.path.exists(node) and os.path.exists(cli_js):
        # 驱动自带 node，直调 cli.js（源码/打包态通用）
        cmd = [node, cli_js, "install", "chromium"]
    elif not getattr(sys, "frozen", False):
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    else:
        warn = "未找到 playwright 驱动，无法自动安装 chromium"
        (logger.warning if logger else print)(warn)
        return
    msg = "检查/安装 chromium 内核（首次约 120MB，已安装则秒过）……"
    (logger.info if logger else print)(msg)
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        warn = f"chromium 安装命令执行失败: {e}；浏览器采集可能不可用"
        (logger.warning if logger else print)(warn)


# 解析哨兵报警状态：(platform, field) → 上次报警日期（每渠道×字段每天至多一条）
_SENT_LAST = {}
# 连续命中天数（v1.5.47）：结构性无源字段连续第 3 天起降为 INFO——
# 如实催修但不再淹没真告警；断档（跳过一天）自动归零，恢复即重新
# 从 WARNING 起报
_SENT_CNT = {}
# 行数塌方检测：platform → 当天近 8 轮明细行数（进程内存；重启后重新
# 累计基线可接受——塌方是持续性现象，重启丢一轮基线不漏报持续故障）
_ROW_HIST = {}
# 锚定仓库 data 目录（v1.5.48）：曾用相对路径——部分轮次进程 CWD
# 不同（计划任务/手动启动差异）时状态加载失效=当日重复告警 ×4、
# 连续天数计数恒 0（「连续 3 天降 INFO」从未触发）
_SENT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "sentinel_state.json")
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _anchored(p, default):
    """CWD 漂移免疫（v1.5.49，与 _SENT_PATH 同族收口）：config 相对路径
    锚定仓库根——计划任务/手动启动 CWD 不同曾另起新库新日志，
    _first_run 的 300s 节流查到空库必不跳过（首轮重推）。"""
    p = (str(p) if p else "").strip() or default
    return p if os.path.isabs(p) else os.path.join(_REPO_ROOT, p)


def _sent_load():
    """哨兵状态落盘回读：进程重启曾让当日已报警字段重复告警。
    v1.5.47 值改 [日期, 连续天数]；旧格式（纯日期串）兼容读入。"""
    import json as _json
    import os as _os
    try:
        with open(_SENT_PATH, encoding="utf-8") as f:
            for k, v in _json.load(f).items():
                plat, fld = k.split("|", 1)
                if isinstance(v, list):
                    _SENT_LAST[(plat, fld)] = v[0]
                    _SENT_CNT[(plat, fld)] = int(v[1] or 0)
                else:
                    _SENT_LAST[(plat, fld)] = v
    except Exception:
        pass


def _sent_save():
    import json as _json
    import os as _os
    try:
        _os.makedirs(_os.path.dirname(_SENT_PATH), exist_ok=True)
        with open(_SENT_PATH, "w", encoding="utf-8") as f:
            _json.dump({f"{k[0]}|{k[1]}": [v, _SENT_CNT.get(k, 0)]
                        for k, v in _SENT_LAST.items()},
                       f, ensure_ascii=False)
    except Exception:
        pass


def _xchan_ratios(xchan):
    """指纹组 → {platform: [组内最低/组中位比,…]}（渠道中位比观测的
    纯计算部分，便于单测）。组内 <3 渠道不产出。"""
    ratios = {}
    for _fp, byp in xchan.items():
        if len(byp) < 3:
            continue
        lows = {pl: min(vs) for pl, vs in byp.items()}
        med = sorted(lows.values())[len(lows) // 2]
        if med <= 0:
            continue
        for pl, v in lows.items():
            ratios.setdefault(pl, []).append(v / med)
    return ratios


def _field_sentinel(all_prices, logger):
    """解析层哨兵：按渠道统计决策字段命中率 + 中转衔接字段覆盖 + 行数
    塌方（v1.5.41 扩容——此前只盯 cabin/meal/prate 三字段）。

    站点改版（键名变更）过去只能靠人看 DB 才发现——同程 sts tx→td
    实锤：meal/prate 静默全空数日、8783 行无决策信息。行数 ≥20 且
    命中率 <10% 判定「疑似整字段失效」，WARNING 留痕（每渠道×字段
    每天至多一条防刷屏）。字段结构性无源的渠道（qunar PC 死后 cabin
    无来源）会每日一条，属如实告警、催修信号。

    扩容项（决策关键字段，P0 调研定论）：
    - plane 机型命中率（<10%）：qunar DOM 名行自源提取的存活观测；
    - transferBaggage=="direct" 命中率（<1% 且 ≥50 中转行）：五渠道仅
      qunar 偶发有源，「直挂筛选的中转达标告警实质近空」的 P0 缺口
      无观测不修——此哨兵即寻源进度的温度计（v1.5.44 分母改中转行，
      全行分母曾让直飞占比高的渠道近乎恒真）；
    - 中转行 layover 覆盖率（<10% 且 ≥20 中转行；v1.5.47 双键兼容——
      原只读 normalize 后的 layoverM，而爬虫原始 extra 写的键是
      layover，全库 0 命中=健康渠道 ctrip 天天被假告警、真断供反而
      与日常同面目）：中转停留单点依赖 ctrip _propagate_layover 补全，
      ctrip 解析坏→全链停留静默归零；
    - 行数塌方：本轮行数 < 近 8 轮中位数 30% 且连续 ≥2 轮——「有响应
      但明细骤减 90%」此前字段命中率与 pulse 双双不报（v1.5.44 分池
      键含航线+日期、记当条记录行数——单平台累计值混池曾让基线失真）。

    v1.5.47 扩容：
    - 渠道指纹中位比（同指纹 ≥3 渠道组内「本渠道最低/组中位」，样本
      ≥20 且 p50 偏离 ±10% 告警）：渠道口径系统性漂移（飞猪税前史实、
      qunar minPrice 重摇）的第二层观测——行级 0.5x 守卫之外此前
      无任何一条观测会响；
    - 经停城市覆盖（≥5 经停行且 <10%）：「经停」徽标无地点，「停哪」
      无从决策；
    - 行数绝对下限（同查询其他渠道中位 ≥30 而本渠道 <10 连续 2 轮）：
      塌方哨兵 base≥20 门槛下，小渠道长期低位成了自己的基线永不触发；
    - 连续命中 ≥3 天的哨兵降级 INFO（结构性无源字段每日一报曾淹没
      真告警），断档自动恢复 WARNING。

    刻意不观测：discount（fliggy 自然覆盖率仅 ~6%，<10% 阈值必误报）；
    stopFlight（qunar H5 经停布尔有标记但 stopsCitys 恒空——入城市覆盖
    分母=制造新的结构性永空假火，与 v1.5.49 死键表同理）。

    v1.5.49 扩容：
    - 结构性死键表（qunar|prate、qunar|plane、fliggy|meal）：观测键=
      渠道×字段，但现役路径无源的组合继续观测=健康渠道天天假告警，
      「疑似站点改版」归因错误（v1.5.49 审计键名三方对账定论）；
    - 新决策字段命中率（shareCarrier/fewTicket/depTerminal）：同班同
      物理属性跨渠道应有值，键名失效静默死亡正是 tx→td 事故模式；
    - 渠道明细全空观测：extra 空/解析败/无价行的记录此前对哨兵与
      脉冲双双隐身（有记录 0 行明细形态）。
    """
    import json as _json
    import datetime as _dt
    # 结构性死键（现役路径无源，告警=假火）：qunar 准点率 PC/H5 报文
    # 均无源；qunar 机型现役 H5 主路径 planeType 75/75 空（PC 有源，
    # PC 恢复主路径时从此表移除）；fliggy 餐食列表页 DOM 无源。
    # fliggy|cabin 刻意保留——条件源 0/34 是真信号疑改版待核
    _SENT_DEAD_KEYS = {("qunar", "prate"), ("qunar", "plane"),
                       ("fliggy", "meal")}
    # 新字段有源渠道白名单（v1.5.48/49 dump 冒烟实证命中率）：不在表内
    # 的渠道不告警（同死键表逻辑——无源渠道观测即假火）
    _SENT_FIELD_SOURCES = {
        ("qunar", "share"), ("ctrip", "share"), ("fliggy", "share"),
        ("tuniu", "share"),                                   # codeShare 24/46
        ("qunar", "few"),
        ("qunar", "term"), ("ctrip", "term"), ("tuniu", "term"),
        # 航站楼单侧命中（多航站楼侧近全量、单航站楼侧空串），dep/arr
        # 并集恒非 0——恒 0 才是键死
    }
    buckets = {}
    xchan = {}   # 指纹 → {platform: [价,…]}（渠道中位比观测）
    no_det = {}   # platform → 明细 0 行记录数（v1.5.49 渠道全空观测）
    for p in all_prices or []:
        if not getattr(p, "extra", ""):
            no_det[getattr(p, "platform", "?")] = \
                no_det.get(getattr(p, "platform", "?"), 0) + 1
            continue
        try:
            obj = _json.loads(p.extra)
        except Exception:
            no_det[getattr(p, "platform", "?")] = \
                no_det.get(getattr(p, "platform", "?"), 0) + 1
            continue
        if not isinstance(obj, list):
            no_det[getattr(p, "platform", "?")] = \
                no_det.get(getattr(p, "platform", "?"), 0) + 1
            continue
        b = buckets.setdefault(p.platform, {
            "n": 0, "cabin": 0, "meal": 0, "prate": 0, "plane": 0,
            "trans_n": 0, "layover": 0, "bag_direct": 0,
            "stop_n": 0, "stop_city": 0,
            "share": 0, "few": 0, "term": 0})
        n_rows = 0
        for f in obj:
            if not isinstance(f, dict) or "price" not in f:
                continue
            b["n"] += 1
            n_rows += 1
            for k in ("cabin", "meal", "prate", "plane"):
                if str(f.get(k) or "").strip():
                    b[k] += 1
            # 新决策字段命中率（v1.5.49）：物理属性跨渠道应有值，
            # 键名失效=静默死亡（tx→td 事故模式）
            if str(f.get("shareCarrier") or "").strip():
                b["share"] += 1
            if str(f.get("fewTicket") or "").strip():
                b["few"] += 1
            if (str(f.get("depTerminal") or "").strip()
                    or str(f.get("arrTerminal") or "").strip()):
                b["term"] += 1
            if str(f.get("transCity") or "").strip():
                b["trans_n"] += 1
                # 双键兼容（v1.5.47 根治假火）：layoverM 是 alerter 读取时
                # normalize 的产物，爬虫原始 extra 写的键是 layover——
                # 此前只读 layoverM，全库 0 命中，健康渠道天天被假告警、
                # 真断供反而与日常同面目不可分辨
                _lay = f.get("layoverM") or f.get("layover")
                if isinstance(_lay, int) and _lay > 0:
                    b["layover"] += 1
            if f.get("transferBaggage") == "direct":
                b["bag_direct"] += 1
            # 经停城市覆盖（v1.5.47 新观测）：「停」行只报经停不报地点，
            # 用户只见经停不知停哪——原始标记 stopCitys（qunar PC/ctrip/
            # tongcheng）或 _via=停（fliggy/qunar H5）
            _sc = str(f.get("stopCitys") or "").strip()
            if _sc or f.get("_via") == "停":
                b["stop_n"] += 1
                if _sc:
                    b["stop_city"] += 1
            # 渠道级系统性偏差观测（v1.5.47）：行级 0.5x 守卫之外的第二
            # 层——渠道口径整体漂移（飞猪税前史实、qunar minPrice 重摇）
            # 现有观测无一条会响。同指纹（航班号+起降时刻+中转+到达日）
            # 跨渠道组内「本渠道最低 / 组中位」，聚合 p50 判系统性偏离
            _code = str(f.get("code") or "").strip().upper()
            try:
                _pv = float(f["price"])
            except (TypeError, ValueError):
                _pv = 0.0
            if _code and 300 <= _pv <= 50000:
                _fp = (_code, str(f.get("depTime") or ""),
                       str(f.get("arrTime") or ""),
                       str(f.get("transCity") or ""),
                       str(f.get("arrDate") or ""))
                xchan.setdefault(_fp, {}).setdefault(
                    p.platform, []).append(_pv)
        # 分池键含航线+日期、记当条记录行数（v1.5.44）：单平台键曾把
        # 大/小航线交错混池抬基线；且同平台多条记录时 b["n"] 是累计值，
        # 逐条 append 曾让历史序列变成递增累加数列（中位数基线失真）。
        # getattr 防御：测试夹具用极简 SimpleNamespace 无航线属性
        _k = (p.platform, getattr(p, "from_city", ""),
              getattr(p, "to_city", ""), getattr(p, "depart_date", ""))
        _ROW_HIST.setdefault(_k, []).append(n_rows)
        del _ROW_HIST[_k][:-8]
        if n_rows == 0:
            # 解析成 list 但全部行无 price：与 extra 空/解析败同属
            # 「有记录 0 行明细」形态，一并计入全空观测
            no_det[p.platform] = no_det.get(p.platform, 0) + 1
    # 键随日期累积清理（v1.5.47）：分池键含日期，长跑月级缓慢泄漏——
    # 当前轮不扫的 (航线,日期) 键 sweep 掉（基线 4 轮即重建，代价可忽略）
    _live = {(getattr(p, "from_city", ""), getattr(p, "to_city", ""),
              getattr(p, "depart_date", "")) for p in all_prices or []}
    for _k in [k for k in _ROW_HIST if (k[1], k[2], k[3]) not in _live]:
        del _ROW_HIST[_k]
    _xchan_ratio_map = _xchan_ratios(xchan)
    today = _dt.date.today().isoformat()

    def _warn(key, msg, *args):
        if _SENT_LAST.get(key) == today:
            return
        # 连续命中计数（v1.5.47）：昨日也命中则 +1、断档归零——结构性
        # 无源字段连续第 3 天起降为 INFO（如实催修但不再淹没真告警），
        # 恢复后自动重置、重新从 WARNING 起报
        yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        cnt = _SENT_CNT.get(key, 0) + 1 if _SENT_LAST.get(key) == yest else 1
        _SENT_CNT[key] = cnt
        _SENT_LAST[key] = today
        _sent_save()
        if cnt >= 3:
            logger.info("[解析哨兵][连续%d日] " + msg, cnt, *args)
        else:
            logger.warning("[解析哨兵] " + msg, *args)

    for plat, b in buckets.items():
        # 门槛 50→20：tongcheng 48 行 / fliggy ~33 / tuniu ~26 量级的
        # 小渠道当轮曾全部逃逸哨兵（tuniu 舱位解析死透数日无报警实锤）；
        # 20 行下 2/20=10% 即不触发，小样本偶发波动不会误报。
        # v1.5.49 再收 20→10：tuniu 现役 ~12 行仍处 10-19 行死区
        # （三条门槛全不命中=观测失明）；10 行下 0/10=0% 才触发，
        # 零命中是强信号不致误报
        if b["n"] >= 10:
            for k in ("cabin", "meal", "prate", "plane"):
                if (plat, k) in _SENT_DEAD_KEYS:
                    continue   # 结构性无源（死键表）：观测即假火
                if b[k] / b["n"] < 0.10:
                    _warn((plat, k), "%s 字段 %s 命中 %d/%d（<10%%，疑似"
                           "站点改版键名失效，决策信息在静默丢失）",
                           plat, k, b[k], b["n"])
            for k in ("share", "few", "term"):
                if (plat, k) not in _SENT_FIELD_SOURCES:
                    continue   # 无源渠道不观测（同死键表逻辑）
                # 恒 0 才算死（v1.5.49）：共享/余票/航站楼覆盖率随航线
                # 波动（DB 实测 20-40%），比率阈值会误报——0 命中才是
                # 键名失效信号（tx→td 事故形态），样本 ≥20 防小样本
                if b[k] == 0 and b["n"] >= 20:
                    _warn((plat, k), "%s 决策字段 %s 命中 0/%d（键名失效/"
                           "渠道改版，或本航线天然无此属性——共享/航站楼"
                           "覆盖率随 OD 波动，连日恒 0 才需寻源）",
                           plat, {"share": "shareCarrier",
                                  "few": "fewTicket",
                                  "term": "depTerminal"}[k], b["n"])
            # 分母=中转行（v1.5.44）：transferBaggage 只挂中转行，全行
            # 分母曾让直飞占比高的渠道该指标数学上近乎恒真（温度计失真）
            if b["trans_n"] >= 50 and b["bag_direct"] / b["trans_n"] < 0.01:
                _warn((plat, "bag_direct"), "%s 行李直挂命中 %d/%d 中转行"
                       "（<1%%：直挂筛选的中转达标告警实质近空，寻源待修）",
                       plat, b["bag_direct"], b["trans_n"])
        if b["trans_n"] >= 20 and b["layover"] / b["trans_n"] < 0.10:
            _warn((plat, "layover"), "%s 中转停留覆盖 %d/%d（<10%%："
                   "衔接时长供给单点化，ctrip 补全链若断全链静默归零）",
                   plat, b["layover"], b["trans_n"])
        # 经停城市覆盖（v1.5.47）：≥5 经停行且城市覆盖 <10%——「经停」
        # 徽标无地点，「停哪/停多久」无从决策
        if b["stop_n"] >= 5 and b["stop_city"] / b["stop_n"] < 0.10:
            _warn((plat, "stopcity"), "%s 经停城市覆盖 %d/%d（<10%%：经停"
                   "徽标无地点，停哪无从决策）",
                   plat, b["stop_city"], b["stop_n"])
        # 行数塌方按 (平台,航线,日期) 分池判（v1.5.44）：基线取同池近轮
        # 中位数——单平台混池键曾让大/小航线交错抓取时基线失真
        for _hk, hist in _ROW_HIST.items():
            if _hk[0] != plat:
                continue
            if len(hist) >= 4:
                base = sorted(hist[:-2])[len(hist[:-2]) // 2]
                # base≥10（v1.5.49 收 20→10 关 10-19 行死区，同字段门槛）
                if base >= 10 and hist[-1] < base * 0.3 and hist[-2] < base * 0.3:
                    _warn((plat, "rowfall"), "%s 行数塌方 %d/%d（近轮中位数"
                           "的 <30%% 连续 2 轮：有响应但明细骤减）",
                           plat, hist[-1], base)
        # 渠道指纹中位比（v1.5.47）：本渠道样本 ≥20 才判，p50 <0.9 或
        # >1.1 即渠道报价口径系统性漂移（非单行毒价——那是 alerter
        # 0.5x 孤低价守卫的辖区）
        _plat_rs = _xchan_ratio_map.get(plat) or []
        if len(_plat_rs) >= 20:
            _rs_sorted = sorted(_plat_rs)
            _p50 = _rs_sorted[len(_rs_sorted) // 2]
            if _p50 < 0.9 or _p50 > 1.1:
                _warn((plat, "median"), "%s 同指纹组中位比 p50=%.2f（n=%d，"
                       "<0.9/>1.1：渠道报价口径系统性漂移，非单行毒价）",
                       plat, _p50, len(_plat_rs))

    # 渠道明细全空（v1.5.49）：≥2 条记录解析后 0 行——「有记录但 0 行
    # 明细」形态对字段/塌方/脉冲三面隐形（仅 qunar 有拒落价守卫）；1 条
    # 空记录是常态波动不入报。独立于 buckets 循环：extra 全空的渠道
    # 根本不会建桶，放进桶循环=对最该报的形态失明
    for plat, cnt in no_det.items():
        if cnt >= 2:
            _warn((plat, "noDet"), "%s 本轮 %d 条记录明细 0 行（extra 空/"
                   "解析败/无价行）", plat, cnt)

    # 行数绝对下限（v1.5.47）：塌方哨兵 base≥20 门槛下，小渠道长期低位
    # （tuniu 1-7 行实况）成了自己的基线永不触发——同查询其他渠道
    # 中位 ≥30 而本渠道 <10 连续 2 轮仍要响
    _low_cur = {}
    for (pk, fck, tck, dtk), hist in _ROW_HIST.items():
        if len(hist) >= 2:
            _low_cur.setdefault((fck, tck, dtk), {})[pk] = (hist[-1], hist[-2])
    for (fck, tck, dtk), per in _low_cur.items():
        for pk, (v1, v2) in per.items():
            if v1 >= 10 or v2 >= 10:
                continue
            oth = sorted(o1 for pk2, (o1, _o2) in per.items() if pk2 != pk)
            if oth and oth[len(oth) // 2] >= 30:
                _warn((pk, "rowlow"), "%s 行数 %d 连续低位（同查询其他渠道"
                       "中位 %d：渠道侧明细骤减或解析半瘫，基线低于塌方"
                       "门槛故单列观测）", pk, v1, oth[len(oth) // 2])


_sent_load()


def make_sweep_job(cfg, rt, logger, storage, charts_fn):
    """构造一轮全量扫描：航线去重 → 逐查询错峰采集 → 分发给订阅用户。

    rt 为运行时容器（dict）：users/alerters/cfg 均可被 web 配置热重载替换，
    每轮扫描开始时取最新值。cfg 形参只是热重载前的初始快照——扫描期一律读
    rt["cfg"]（reload_config 会同步更新），否则爬虫超时/错峰/日报时刻/图床
    等配置在首次热重载后仍沿用启动快照。去哪儿接口 ~5 分钟全局限流（与航线
    无关），每个 (航线, 日期) 查询之间错峰等待。"""
    import threading
    # 进程级互斥：启动首轮 / 定时调度 / 网页手动触发统一防并发
    # （曾因"启动即扫 + /api/run"双跑导致每渠道抓两次、每消息推两条）
    _sweep_lock = threading.Lock()

    # 平台实例：按「平台集合」缓存（去哪儿实例的 token/浏览器会话复用）
    crawler_cache = {}
    # 热改无头模式后清缓存，下轮按新配置重建浏览器实例
    rt["clear_crawlers"] = crawler_cache.clear

    def get_crawlers(platforms):
        key = tuple(sorted(set(platforms)))
        if key not in crawler_cache:
            crawler_cfg = (rt.get("cfg") or cfg).get("crawler", {})
            insts = []
            for name in key:
                cls = REGISTRY.get(name)
                if cls:
                    insts.append(cls(crawler_cfg, logger))
            crawler_cache[key] = insts
        return crawler_cache[key]

    def sweep():
        if not _sweep_lock.acquire(blocking=False):
            logger.warning("[扫描] 上一轮仍在进行，跳过本次触发")
            return
        try:
            _sweep_inner()
        finally:
            _sweep_lock.release()

    def _sweep_inner():
        from core.pulse import PULSE
        users, alerters = rt["users"], rt["alerters"]
        logger.info("===== 开始一轮扫描（%d 用户 / %d 航线） =====",
                    len(users),
                    len({(r.from_code, r.to_code) for u in users for r in u["routes"]}))
        # 航线×日期 去重注册表：{(from,to,date): [订阅该组合的用户索引]}
        registry = {}
        for ui, u in enumerate(users):
            for r in u["routes"]:
                for d in r.dates:
                    registry.setdefault((r.from_code, r.to_code, d), set()).add(ui)

        queries = sorted(registry)
        PULSE.begin()

        def _timed_fetch(c, fc_, tc_, d_):
            # 单渠道计时入脉冲（成败=是否有数据），控制台可观察性数据源
            t0 = time.time()
            prices = c.safe_fetch(fc_, tc_, [d_])
            try:
                PULSE.channel(c.name, len(prices), time.time() - t0)
            except Exception:
                pass
            return prices

        user_pairs = {}   # 按用户聚合 (route, prices)，轮末一次聚合推送
        chart_cache = {}
        for qi, (fc, tc, d) in enumerate(queries):
            # 平台集合 = 所有订阅用户平台配置的并集（一次采集服务所有人）
            plats = set()
            th_min = None  # 该查询的最低达标线（qunar 幻影价复核参考）
            for ui in registry[(fc, tc, d)]:
                plats |= set(users[ui]["platforms"])
                for r in users[ui]["routes"]:
                    if r.from_code == fc and r.to_code == tc and d in r.dates:
                        for v in (r.alert_direct, r.alert_transfer):
                            try:
                                v = float(v or 0)
                            except (TypeError, ValueError):
                                continue
                            if v > 0:
                                th_min = v if th_min is None else min(th_min, v)
            for c in get_crawlers(plats):
                try:
                    c.threshold_hints[(fc, tc, d)] = {"min": th_min}
                except AttributeError:
                    pass
            # 渠道并发（各平台相互独立：浏览器实例/会话目录均隔离）；
            # 去哪儿的全局限流错峰由 qunar 渠道自身控制（类级时间锁），
            # 不再让其余渠道陪等
            all_prices = []
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max(1, len(plats) or 1)) as ex:
                futs = {ex.submit(_timed_fetch, c, fc, tc, d): c.name
                        for c in get_crawlers(plats)}
                for fu in concurrent.futures.as_completed(futs):
                    try:
                        prices = fu.result()
                    except Exception as e:
                        logger.warning("[并发] %s 抓取异常: %s", futs[fu], e)
                        continue
                    all_prices.extend(prices)
            storage.save_many(all_prices)
            _field_sentinel(all_prices, logger)
            # 走势图按航线一次生成、所有用户复用
            # charts_fn 返回 {(from,to,date): url} 整表——此处须取本航线的
            # 单个 URL 存缓存，否则 alerter 拿到 dict 嵌进 markdown 变裂图
            chart = charts_fn(fc, tc, d) or {}
            chart_url = chart.get((fc, tc, d))
            if chart_url:
                chart_cache[(fc, tc, d)] = chart_url
            # 分发：按用户聚合本轮全部 (route, prices)，
            # 一轮一消息（每航线一个小节，明细合并一张总表）
            for ui in sorted(registry[(fc, tc, d)]):
                u = users[ui]
                for r in u["routes"]:
                    if r.from_code == fc and r.to_code == tc and d in r.dates:
                        sub = [p for p in all_prices
                               if p.from_city == fc and p.to_city == tc
                               and p.depart_date == d]
                        user_pairs.setdefault(ui, []).append((r, sub))
            logger.info("[扫描] %s→%s %s 完成（%d/%d）", fc, tc, d, qi + 1, len(queries))
        # 轮末统一分发（全部航线采集完成后聚合推送）
        for ui, pairs in user_pairs.items():
            try:
                alerters[ui].round_charts = chart_cache
                alerters[ui].check_multi(pairs)
            except Exception as e:
                logger.warning("[%s] 聚合推送异常: %s", users[ui]["name"], e)
        # 每用户日报（到点触发一次，防重发按用户隔离）
        for ui, u in enumerate(users):
            try:
                from report import maybe_daily_report
                maybe_daily_report(rt.get("cfg") or cfg, logger,
                                   alerters[ui].notifier, user=u["name"])
            except Exception as e:
                logger.warning("[%s] 每日走势报告异常: %s", u["name"], e)
        PULSE.end()
        logger.info("===== 本轮扫描结束 =====")
        # 数据窗口维护：删 14 天前明细（extra 大 JSON 是增长主体）
        try:
            n = storage.purge(days=14)
            if n:
                logger.info("[存储] 已清理 %d 条过期价格记录", n)
        except Exception as e:
            logger.warning("[存储] 过期清理失败: %s", e)
        # 控制台缓存预热：扫描写库使 /api/state 签名失效，后台先重建，
        # 用户打开控制台永远命中热缓存（首屏不等全量重算）
        try:
            import webui as _webui
            _webui.prewarm_state()
        except Exception:
            pass

    return sweep


def acquire_instance_lock() -> bool:
    """单实例互斥锁：多实例并发会抢采/互踩 DB/调度互相干扰（历史多轮
    事故）。锁文件 data/.instance.lock 被第二个实例加锁失败 → 立即
    退出；进程退出时 OS 自动释放（含崩溃）。"""
    try:
        import msvcrt
    except ImportError:
        # 非 Windows（msvcrt 为 Win 专属）：README 声明面向 Windows，
        # 曾在 Linux 上裸 ModuleNotFoundError 崩在第一行——给友好出口。
        # 无文件锁时退化为「不锁」，多实例风险由部署方自行保证。
        print("⚠ 非 Windows 平台：跳过单实例锁（采集浏览器依赖 Windows 环境）")
        return True
    lock_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", ".instance.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    global _LOCK_FP
    _LOCK_FP = open(lock_path, "a+b")
    try:
        msvcrt.locking(_LOCK_FP.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        try:
            _LOCK_FP.close()
        except Exception:
            pass
        return False


_LOCK_FP = None


def main():
    ap = argparse.ArgumentParser(description=f"机票监控 ticket-monitoring v{__version__}")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    ap.add_argument("--once", action="store_true", help="每条航线只运行一次后退出")
    ap.add_argument("--setup", action="store_true", help="重跑配置向导")
    ap.add_argument("--report", action="store_true",
                    help="立即生成价格走势图并推送钉钉（未配图床则只存本地）")
    ap.add_argument("--install-browser", action="store_true",
                    help="仅安装/更新 chromium 内核后退出")
    ap.add_argument("--setup-login", action="store_true",
                    help="顺序弹出浏览器引导登录所有已启用渠道（每家登录一次永久复用）")
    ap.add_argument("--login", metavar="PLATFORM",
                    help="登录指定平台(ctrip/fliggy/tongcheng)，弹出可见浏览器，登录完成后回车保存会话")
    args = ap.parse_args()

    # 锁在参数解析后（v1.5.44）：--version/--help 曾被单实例锁拦下，
    # 发版门禁「exe 实跑 --version」在监控运行时必假红
    if not acquire_instance_lock():
        print("⚠ 已有实例在运行（检测到实例锁），本次启动退出。"
              "控制台仍可用：浏览器打开 http://127.0.0.1:8765")
        sys.exit(1)

    cfg_path = Path(args.config)

    if args.setup:
        from wizard import run_wizard
        run_wizard(str(cfg_path))
        print("配置完成，重新运行程序即开始监控。")
        return

    if args.install_browser:
        ensure_chromium(["qunar"])
        return

    if not cfg_path.exists():
        # 无配置文件时给一个空骨架，直接进 web 页面配置（不再强制 CLI 向导）
        cfg = {"users": [], "schedule": {"interval_minutes": 30,
                                         "jitter_minutes": 5},
               "crawler": {"headless": True, "debug": True},
               "output": {"db_path": "data/prices.db",
                          "log_path": "logs/monitor.log"}}
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        except Exception:
            pass
        print("未找到配置——已生成空骨架，请在 http://127.0.0.1:8765 页面配置")
    else:
        cfg = load_config(str(cfg_path))

    out = cfg.get("output", {})
    logger = setup_logger(_anchored(out.get("log_path"), "logs/monitor.log"))
    ensure_chromium(cfg.get("platforms") or ["qunar"], logger)
    storage = PriceStorage(_anchored(out.get("db_path"), "data/prices.db"))

    # 运行时容器：web 配置热重载时替换 users/alerters/cfg，sweep 每轮取最新；
    # rt["cfg"] 是配置的单一事实源（reload_config 同步更新）
    rt = {}
    rt["cfg"] = cfg

    def build_runtime():
        users = build_users(cfg)
        alerters = []
        for u in users:
            ncfg = u["notifier"]
            notifier = build_notifier(ncfg, logger)
            if notifier:
                logger.info("[%s] 已启用推送: %s", u["name"], type(notifier).__name__)
            from core.notifier import build_urgent_notifier
            urgent = build_urgent_notifier(ncfg, logger)
            if urgent:
                logger.info("[%s] 已启用达标强提醒: %s",
                            u["name"], type(urgent).__name__)
            alerters.append(Alerter(
                logger, notifier=notifier, storage=storage,
                push_drop_min=float((ncfg or {}).get("push_drop_min", 30)),
                push_rise_min=float((ncfg or {}).get("push_rise_min", 50)),
                digest=bool((ncfg or {}).get("digest", False)),
                at_mobile=str(((ncfg or {}).get("dingtalk") or {}).get(
                    "at_mobile", "")),
                storm_repeat=int((ncfg or {}).get("storm_repeat", 3)),
                user=u["name"],
                platforms=u.get("platforms"),
                urgent_notifier=urgent,
                quiet_start=str((ncfg or {}).get("quiet_start", "") or ""),
                quiet_end=str((ncfg or {}).get("quiet_end", "") or ""),
                # base_url 可配置：钉钉「完整详情」链接的可达性取决于它——
                # 服务默认绑 127.0.0.1，手机端钉钉点开必死链；手机要看详情需
                # 配 web.base_url 为本机局域网地址（如 http://192.168.x.x:8765）
                base_url=str((cfg.get("web") or {}).get("base_url") or (
                    "http://127.0.0.1:%d" % int(
                        ((cfg.get("web") or {}).get("port", 8765)) or 8765))),
            ))
        rt["users"], rt["alerters"] = users, alerters
        return users

    build_runtime()
    if not rt["users"]:
        logger.warning("配置中没有任何用户/航线——可通过 http://127.0.0.1:8765 配置")

    # 走势图生成（按航线，一次上传多用户复用）
    def charts_fn(fc, tc, d):
        try:
            from report import prepare_round_charts
            return prepare_round_charts(cfg, logger, route_override=(fc, tc, d))
        except Exception as e:
            logger.warning("走势图准备失败: %s", e)
            return {}

    sched_ref = [None, int((cfg.get("schedule") or {}).get(
        "interval_minutes", 30) or 30)]  # [scheduler实例, 当前周期]
    # 调度参数可变引用：wrapped 每轮实时读取，热改周期/扰动即生效
    sched_state = {"interval_minutes": sched_ref[1],
                   "jitter_minutes": int((cfg.get("schedule") or {}).get(
                       "jitter_minutes", 0) or 0)}

    def reload_config():
        """web 配置保存后的热重载：重读 config.yaml 并重建用户/告警器。"""
        nonlocal cfg
        cfg = load_config(str(cfg_path))
        rt["cfg"] = cfg
        users = build_runtime()
        logger.info("[热重载] %d 用户已生效：%s", len(users),
                    "、".join(u["name"] for u in users))
        # 同步 webui 的内存引用（否则状态页仍用启动时的旧用户配置）
        try:
            from webui import _State
            _State.users, _State.cfg = rt["users"], cfg
        except Exception:
            pass
        # 调度周期热更新：interval 变化时重排调度器（无需重启）
        try:
            sc = (cfg.get("schedule") or {})
            new_iv = int(sc.get("interval_minutes", 30) or 30)
            new_jm = int(sc.get("jitter_minutes", 0) or 0)
            sched_state["interval_minutes"] = new_iv
            sched_state["jitter_minutes"] = new_jm
            from core.scheduler import SCHED
            if SCHED is not None and new_iv != sched_ref[1]:
                from apscheduler.triggers.interval import IntervalTrigger
                SCHED.reschedule_job(
                    "price_monitor",
                    trigger=IntervalTrigger(minutes=new_iv))
                sched_ref[1] = new_iv
                logger.info("[热重载] 调度周期已更新为 %d 分钟", new_iv)
        except Exception as e:
            logger.warning("[热重载] 调度周期更新失败: %s", e)
        # 无头模式变化 → 清爬虫实例缓存（下轮按新配置重建浏览器）
        try:
            new_hl = bool((cfg.get("crawler") or {}).get("headless", True))
            if new_hl != rt.get("headless", new_hl):
                rt["headless"] = new_hl
                if rt.get("clear_crawlers"):
                    rt["clear_crawlers"]()
                    logger.info("[热重载] 无头模式已切换为 %s，爬虫实例下轮重建",
                                new_hl)
        except Exception as e:
            logger.warning("[热重载] 爬虫缓存清理失败: %s", e)
        # 控制台端口变化 → 原地重绑（响应送回后异步切换）
        try:
            new_port = int((cfg.get("web") or {}).get("port", 8765) or 8765)
            if new_port != rt.get("web_port", new_port):
                rt["web_port"] = new_port
                from webui import rebind_web
                rebind_web(new_port)
                logger.info("[热重载] 控制台端口热切换至 %d", new_port)
        except Exception as e:
            logger.warning("[热重载] 控制台端口切换失败: %s", e)
        return len(users)

    sweep = make_sweep_job(cfg, rt, logger, storage, charts_fn)

    # ---------- 登录引导：--login 单家 / --setup-login 全部 ----------
    login_set = []
    if getattr(args, "setup_login", False):
        plat_all = set()
        for u in build_users(load_config(str(cfg_path))):
            plat_all |= set(u.get("platforms") or [])
        login_set = [p for p in ("qunar", "ctrip", "tongcheng", "tuniu", "fliggy")
                     if p in plat_all]
    elif getattr(args, "login", ""):
        login_set = [args.login]
    if login_set:
        import threading
        # 五窗齐弹：每家独立线程+浏览器（user_data 各自独立无冲突），
        # 阶梯排布窗口；用户自由登录，回一次车统一保存关闭
        done_evt = threading.Event()
        results = {}

        def _open_window(pname, idx):
            try:
                cls = REGISTRY.get(pname)
                crawler = cls(cfg.get("crawler", {}) or {}, logger)
                crawler._login_window(done_evt, idx)
                results[pname] = "ok"
            except Exception as e:
                results[pname] = f"fail: {e}"

        threads = []
        for i, pname in enumerate(login_set):
            t = threading.Thread(target=_open_window, args=(pname, i), daemon=True)
            t.start()
            threads.append(t)
            import time as _t
            _t.sleep(1.2)   # 错峰启动避免窗口抢焦点
        print()
        print("=" * 64)
        print("  已同时打开 %d 个浏览器窗口（每家一个，窗口阶梯排布）。" % len(login_set))
        print("  请逐个完成登录（点各站右上角登录）。")
        print("  全部完成后回到这里按一次 Enter，统一保存会话并关闭。")
        print("=" * 64)
        try:
            input(">>> 全部登录完成后按 Enter：")
        except EOFError:
            import time as _t
            _t.sleep(120)
        done_evt.set()
        for t in threads:
            t.join(timeout=20)
        print("\n".join(f"  {k}: {v}" for k, v in results.items()))
        print("会话已持久化（user_data/），监控将自动复用。")
        return

    if args.report:
        from report import build_and_push
        for u, a in zip(rt["users"], rt["alerters"]):
            build_and_push(cfg, logger, a.notifier, user=u["name"])
        return

    # 伴生本地控制台（127.0.0.1，随监控常驻；--once 不启动）
    if not args.once:
        try:
            from webui import start_web

            def _report_push():
                from report import build_and_push
                ok = True
                for u, a in zip(rt["users"], rt["alerters"]):
                    ok = build_and_push(cfg, logger, a.notifier, user=u["name"]) and ok
                return ok

            start_web(cfg, sweep, _report_push, logger, users=rt["users"],
                      reload_cb=reload_config, config_path=str(cfg_path),
                      version=__version__)
            rt["web_port"] = int((cfg.get("web") or {}).get("port", 8765))
            rt["headless"] = bool((cfg.get("crawler") or {}).get(
                "headless", True))
        except Exception as e:
            logger.warning("控制台启动异常: %s", e)

    sched_cfg = (rt["users"][0]["schedule"] if rt["users"]
                 else cfg.get("schedule") or {})
    interval = int(sched_cfg.get("interval_minutes", 30))
    jitter = int(sched_cfg.get("jitter_minutes", 0))
    run_on_start = bool(sched_cfg.get("run_on_start", True))
    if not rt["users"]:
        run_on_start = False  # 无用户时空转，等 web 配置热重载
        interval = max(interval, 5)
    sched_state["interval_minutes"] = interval
    sched_state["jitter_minutes"] = jitter
    logger.info("启动定时调度，每 %d 分钟一轮 (±%d 随机扰动)", interval, jitter)
    try:
        def _first_run():
            """启动首轮节流：上轮完成 <5 分钟则跳过（连环重启不轰炸推送）。"""
            try:
                import sqlite3 as _sq
                from datetime import datetime as _dt
                db = _anchored(
                    (cfg.get("output") or {}).get("db_path"),
                    "data/prices.db")
                row = _sq.connect(db).execute(
                    "SELECT MAX(fetched_at) FROM flight_prices").fetchone()
                if row and row[0]:
                    age = (_dt.now() - _dt.strptime(
                        row[0][:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
                    if age < 300:
                        logger.info("[启动] 上轮 %.0f 分钟前已完成，跳过首轮",
                                    age / 60)
                        return
            except Exception:
                pass
            sweep()

        run_scheduler(_first_run, sched_state,
                      run_on_start)  # BlockingScheduler，阻塞至此
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，停止监控")


if __name__ == "__main__":
    main()
