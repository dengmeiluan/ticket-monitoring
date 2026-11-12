# -*- coding: utf-8 -*-
"""离线体检：把爬取率 / 登录退避 / 设备身份三本账读成一张表。

为什么单独做成脚本而不是塞进 webui：这三本账都是**只读落地文件**
（`user_data/<profile>/yield_stats.json`、`login_ledger.json`、
`device/device_identity.json`），做成一页 CLI 就没有任何接线风险，也不会
因为改 UI 把 852 个测试带崩。等数值稳定下来，再决定要不要上面板。

用法：
    python scripts/yield_report.py
    python scripts/yield_report.py --user-data user_data --profile 邓美鸾
    python scripts/yield_report.py --json          # 机读，便于接监控

输出三块：
    1) 爬取率：每渠道的成功率（Wilson 下界）、路径排名、死钟点、间隔建议
    2) 登录：连击数、下次可试时间、是否该换身份
    3) 设备：身份 ID / 机型 / 旋转次数（有身份文件才显示）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.yield_stats import YieldLedger, default_ledger  # noqa: E402
from core.riskscore import LoginLedger                 # noqa: E402
from core.riskscore import default_ledger as _login_ledger  # noqa: E402
from core.policy import PolicyEngine                  # noqa: E402


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _platform_dirs(user_data: str) -> list:
    """列出所有**确实有账本文件**的渠道目录。

    为什么必须有这个（2026-11-05 实测）：写侧按渠道分文件
    （`core.yield_stats.default_ledger(user_data, plat)` →
    `user_data/<plat>/yield_stats.json`，`login_ledger.json` 同理），
    而本脚本的 `collect()` 以前读的是 `user_data/yield_stats.json`
    —— **那个路径没有任何代码会写**。
    结果是"[爬取率] 还没有样本"，而同一时刻监控正在往每渠道文件里写数据。
    测量工具静默读到空、并且把空当成事实播报，比没有工具更坏：
    它会让人以为"没数据可看"而不是"我看错了地方"。

    所以这里以**文件是否存在**为准来发现渠道，不硬编码渠道清单
    （清单会漏新渠道，也会带着已删除的渠道不放）。
    """
    out = []
    try:
        for name in sorted(os.listdir(user_data)):
            d = os.path.join(user_data, name)
            if not os.path.isdir(d) or name in ("device", "snapshots"):
                continue
            if (os.path.isfile(os.path.join(d, "yield_stats.json"))
                    or os.path.isfile(os.path.join(d, "login_ledger.json"))
                    or os.path.isfile(os.path.join(d, "slider_ledger.json"))):
                out.append(name)
    except OSError:
        return []
    return out


def _fmt_wait(sec: int) -> str:
    sec = max(0, int(sec))
    if sec <= 0:
        return "可立即尝试"
    if sec < 60:
        return "%ds 后" % sec
    if sec < 3600:
        return "%dm 后" % (sec // 60)
    return "%.1fh 后" % (sec / 3600.0)


def _slider_ledger(base: str) -> dict:
    """读滑块预算/命中账本（``slider_ledger.json``）。

    这是判断「``slider.auto: simple`` 到底值不值得开」的唯一数据来源：
    ``tries``/``fails`` 是累计尝试与失败，``day_used`` 是当日用量。
    """
    # 同样按渠道分文件；以前只猜 base 和 base/probe 两个固定路径，
    # 于是真实的 `user_data/<plat>/slider_ledger.json` 一律读不到。
    cands = [os.path.join(base, "slider_ledger.json")]
    if os.path.isdir(base):
        try:
            for name in sorted(os.listdir(base)):
                cands.append(os.path.join(base, name, "slider_ledger.json"))
        except OSError:
            pass
    for cand in cands:
        d = _load(cand)
        if d:
            return d
    return {}


def _fmt_slider(rec: dict, now: float) -> str:
    """一行说清验证现状：总尝试/命中率 + **分类别** + 是否被拉黑。

    分项来自账本的 ``by_kind``（``slider``/``arithmetic``/``text``）。
    总账与拉黑仍按合计算（不同类别各记一套会让"失败 2 次拉黑"互相抵消），
    分项只用于"哪一类更容易过"——决定该关哪一类。
    """
    tries = int(rec.get("tries") or 0)
    fails = int(rec.get("fails") or 0)
    if not tries:
        return "未尝试"
    ok = max(0, tries - fails)
    rate = ok / float(tries)
    parts = []
    bk = rec.get("by_kind")
    if isinstance(bk, dict):
        for k in ("arithmetic", "text", "slider"):
            it = bk.get(k)
            if not isinstance(it, dict):
                continue
            t = int(it.get("tries") or 0)
            o = int(it.get("ok") or 0)
            if t:
                parts.append("%s %d/%d" % (k, o, t))
    tail = ""
    until = float(rec.get("blocked_until") or 0)
    if until > now:
        tail = "，拉黑剩余 %.0f 小时" % ((until - now) / 3600.0)
    detail = ("（%s）" % " · ".join(parts)) if parts else ""
    return ("试 %d / 过 %d（命中 %.0f%%）%s%s"
            % (tries, ok, rate * 100, detail, tail))


class _AggYield:
    """多份按渠道账本合成一个读视图（不改写、只聚合）。

    刻意做得薄：任何方法出错就回退到"这一份没有"，
    不能因为某个渠道的账本坏掉就让整张报表空白
    （以前正是"读错一个路径 → 全表空"这种脆弱）。
    """

    def __init__(self, by_plat: dict):
        self._by = dict(by_plat or {})

    def snapshot(self, exclude_infra: bool = False) -> dict:
        """合成各渠道视图。

        ``exclude_infra`` 透传给单渠道账本：顶行按**真实采集通路**算，
        不把 snap-restore/android-runtime 这类基础设施通路算进分母
        （它们永远 rows=0，实测会把 app_zhixing 从 0.99 拖到 0.60）。
        单份账本不支持该参数时退回旧调用，绝不因此让整张报表空白。
        """
        out = {}
        for pl, led in self._by.items():
            try:
                if exclude_infra:
                    try:
                        out.update(led.snapshot(exclude_infra=True) or {})
                        continue
                    except TypeError:
                        pass
                out.update(led.snapshot() or {})
            except Exception:
                continue
        return out

    def recommend_interval(self, plat: str, base_min: int) -> dict:
        led = self._by.get(plat)
        if led is None:
            return {"minutes": int(base_min), "factor": 1.0}
        try:
            return led.recommend_interval(plat, base_min) or {}
        except Exception:
            return {"minutes": int(base_min), "factor": 1.0}


class _AggLogin:
    """同上，登录账本的聚合读视图。"""

    def __init__(self, by_plat: dict):
        self._by = dict(by_plat or {})

    @property
    def data(self) -> dict:
        out = {}
        for pl, led in self._by.items():
            try:
                out.update(getattr(led, "data", {}) or {})
            except Exception:
                continue
        return out

    def rec(self, plat: str) -> dict:
        led = self._by.get(plat)
        try:
            return (led.rec(plat) if led else {}) or {}
        except Exception:
            return {}

    def wait_s(self, plat: str, now=None) -> int:
        led = self._by.get(plat)
        try:
            return int(led.wait_s(plat, now=now) if led else 0) or 0
        except Exception:
            return 0

    def should_rotate(self, plat: str) -> bool:
        led = self._by.get(plat)
        try:
            return bool(led.should_rotate(plat)) if led else False
        except Exception:
            return False


def collect(user_data: str, profile: str = "", base_interval: int = 30) -> dict:
    """读三本账，返回结构化结果（纯函数，便于测试与接监控）。"""
    base = os.path.join(user_data, profile) if profile else user_data
    # **按渠道各读各的文件**：给定了 profile 就只读那一个渠道，
    # 否则扫出所有有账本的渠道逐个读（约定与写侧同源：`default_ledger`）。
    plats_read = [profile] if profile else _platform_dirs(user_data)
    yls, lls = {}, {}
    for pl in plats_read:
        yls[pl] = default_ledger(user_data, pl)
        # 与写侧同一个工厂：路径约定只有一份，改约定时不会只改一边
        lls[pl] = _login_ledger(user_data, pl)
    # 兼容原接口：下面仍按"单个 yl/ll"来问数，只是这几个对象是聚合视图。
    yl = _AggYield(yls)
    ll = _AggLogin(lls)
    ident = _load(os.path.join(user_data, "device", "device_identity.json"))

    out = {"base": os.path.abspath(base), "yield": {}, "login": {},
           "device": {}, "policy": {}, "advice": []}
    # 顶行按真实采集通路算：剔除 snap-restore / android-runtime 这类
    # 基础设施通路（永远 rows=0，却会把成功率拖到 0.60）。这些通路
    # 仍在下面的"路径排序"里逐条列出，只是不再进分母。
    snap = yl.snapshot(exclude_infra=True)
    now = time.time()
    _ = plats_read          # 显式声明依赖顺序：发现渠道 → 再喂策略层
    # 统一策略：一次性看所有渠道的最终决定（停/降速/换身份），不改状态机
    try:
        # **与生产同构**：`crawlers.base` / `app_base` 都是
        # `default_engine(cfg, repo_root=..., profile=<渠道名>)`，
        # 所以 PolicyEngine 内部 `base_dir = user_data/<渠道>`，
        # 它读自己的 `yield_stats.json` / `login_ledger.json` 都对得上。
        # 报表以前建的是 profile=""（base_dir=扁平 user_data），
        # 那三个文件都在渠道目录下 ⇒ 策略段永远空 —— 同一个"读错路径"的病。
        pol = {}
        for pl in plats_read:
            eng = PolicyEngine({"user_data_dir": user_data}, profile=pl,
                               repo_root=".")
            try:
                pol.update(eng.snapshot(now=now) or {})
            except Exception:
                continue
        out["policy"] = pol
    except Exception:
        out["policy"] = {}
    plats = sorted(set(snap) | set(ll.data) | set(out["policy"]) |
                   set(_slider_ledger(base)))
    for plat in plats:
        rec = snap.get(plat) or {}
        led = ll.rec(plat)
        wait = ll.wait_s(plat, now=now)
        item = {
            "rate": rec.get("rate", 0.0),
            "lower": rec.get("lower", 0.0),
            "samples": rec.get("n", 0),
            "rows": rec.get("rows", 0),
            "paths": rec.get("paths", []),
            "dead_hours": rec.get("dead_hours", []),
            "streak": int(led.get("streak") or 0),
            "device_risk": int(led.get("device_risk") or 0),
            "wait_s": wait,
            "next_allowed": _fmt_wait(wait),
            "rotate": ll.should_rotate(plat),
            "interval": yl.recommend_interval(plat, base_interval),
            "slider": _fmt_slider(_slider_ledger(base).get(plat) or {}, now),
        }
        out["yield"][plat] = item
        pol = out["policy"].get(plat) or {}
        if pol:
            out["advice"].append(
                "%s：策略=%s 倍率 %.1f×%s%s"
                % (plat, pol.get("state"), float(pol.get("pace_factor") or 1),
                   "，停 %ds" % pol["wait_s"] if pol.get("wait_s") else "",
                   "，建议换身份" if pol.get("rotate") else ""))
        if item["rotate"]:
            out["advice"].append(
                "%s：设备侧已累计 %d 次风险且连击 %d —— 降速无效，考虑换身份"
                % (plat, item["device_risk"], item["streak"]))
        if item["interval"]["factor"] != 1.0:
            out["advice"].append(
                "%s：建议间隔 %d 分钟（%s）"
                % (plat, item["interval"]["minutes"], item["interval"]["why"]))
        if item["dead_hours"]:
            out["advice"].append(
                "%s：%s 点常年取不到数，可纳入 scan_quiet"
                % (plat, "/".join(str(h) for h in item["dead_hours"])))

    for vm, rec in (ident or {}).items():
        prof = rec.get("profile") or {}
        out["device"][vm] = {
            "ident_id": rec.get("ident_id", ""),
            "model": "%s %s" % (prof.get("brand", ""), prof.get("model", "")),
            "android_id": rec.get("android_id", ""),
            "serial": rec.get("serial", ""),
            "rotations": int(rec.get("rotations") or 0),
            "applied_boot": bool(rec.get("applied_boot")),
        }
    return out


def _print_human(data: dict, base_interval: int) -> None:
    print("=" * 78)
    print("账本目录：%s" % data["base"])
    print("=" * 78)

    if not data["yield"]:
        print("\n[爬取率] 还没有样本（跑完一轮采集后再看）")
    else:
        print("\n[爬取率] 只有 rows>0 才算成功；lower 是 Wilson 下界（保守值）")
        print("          分母只含「真的打了站点」的通路：snap-restore/android-runtime")
        print("          等基础设施、TRIP（往返不支持）、unknown（旧轮次无留痕）都不计入")
        print("  %-10s %6s %6s %6s %8s %8s  %-9s %s"
              % ("渠道", "样本", "成功", "下界", "间隔建议", "倍率", "状态", "滑块"))
        for plat, it in sorted(data["yield"].items()):
            n = it["samples"]
            ok = int(round(it["rate"] * n)) if n else 0
            pol = (data.get("policy") or {}).get(plat) or {}
            print("  %-10s %6d %6d %6.2f %8d %7.1fx  %-9s %s"
                  % (plat, n, ok, it["lower"], it["interval"]["minutes"],
                     float(pol.get("pace_factor") or 1.0),
                     pol.get("state") or "-", it.get("slider") or "-"))
        for plat, it in sorted(data["yield"].items()):
            if not it["paths"]:
                continue
            top = " ".join("%s:%.2f(%d)" % (p["path"], p["lower"], p["n"])
                           for p in it["paths"][:4])
            print("    %-10s 路径排序 %s" % (plat, top))
            # 状态分布：把"没取到数"拆成 empty/error/login 等。
            # 没有这一行，`16/40` 看不出是"真没票"还是"没抓到"。
            st_parts = []
            for p in it["paths"][:4]:
                st = p.get("st") or {}
                if st:
                    st_parts.append("%s[%s]" % (p["path"], "/".join(
                        "%s×%d" % (k, v) for k, v in
                        sorted(st.items(), key=lambda kv: -kv[1]))))
            if st_parts:
                print("    %-10s 状态分布 %s" % (plat, " ".join(st_parts)))

    if not data["device"]:
        print("\n[设备] 没有身份文件（android.identity 未启用或还没跑过）")
    else:
        print("\n[设备] 稳定身份（跨重启不变，换身份才会变）")
        for vm, d in data["device"].items():
            print("  vm%-3s %-26s %s  %s  rotations=%d"
                  % (vm, d["model"], d["ident_id"], d["android_id"],
                     d["rotations"]))

    print("\n[建议]")
    if data["advice"]:
        for a in data["advice"]:
            print("  - " + a)
    else:
        print("  - 无（各渠道都在正常区间）")
    print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="爬取率 / 登录 / 设备 体检")
    ap.add_argument("--user-data", default="user_data")
    ap.add_argument("--profile", default="",
                    help="user_data 下的子目录（阿凡达式的渠道 profile）；留空=根")
    ap.add_argument("--interval", type=int, default=30,
                    help="当前 schedule.interval_minutes，用于算建议")
    ap.add_argument("--json", action="store_true", help="输出机读 JSON")
    args = ap.parse_args(argv)

    data = collect(args.user_data, args.profile, args.interval)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(data, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
