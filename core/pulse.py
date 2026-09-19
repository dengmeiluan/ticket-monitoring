# -*- coding: utf-8 -*-
"""扫描脉冲记录器：每轮每渠道 成败/行数/耗时 的环形缓冲（落盘持久化）。

主页 01 PULSE 概览条与 04 HEALTH 脉冲柱的数据源（/api/pulse 直接吐视图）。
轮次历史落盘 data/pulse.json，重启自动恢复——脉冲柱跨重启连续可读
（2026-09-13 用户反馈：纯内存缓冲重启清零，柱数与服务在线时长对不上）。
since 仍为本进程启动时刻，「服务在线」语义不变。"""
import json
import os
import threading
import time
from datetime import datetime

# 锚定仓库 data 目录（v1.5.49，与 main._SENT_PATH 同族收口）：曾用
# CWD 相对路径——进程 CWD 漂移（计划任务/手动启动差异）=脉冲历史清零/
# 异处落盘；import 时即实例化，错一次就是整个运行期
STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "pulse.json")


class Pulse:
    def __init__(self, maxlen: int = 48, store: str = None):
        self._max = maxlen
        self._store = store or STORE   # 可注入：单测用 tmp_path 隔离
        self._lock = threading.Lock()
        self._rounds = []          # 已完成轮次（旧→新）
        self._cur = None           # 进行中的一轮
        self._since = datetime.now()
        self._load()

    def _load(self):
        """启动恢复：只载入**本进程**写入的轮次（缺失/损坏静默从零开始）。
        按属主 pid 过滤是硬要求：两个监控实例并存时共用 pulse.json 会互相
        污染（实测同屏「成功率 88%」与渠道健康「100%×5」自相矛盾——
        僵尸实例的旧签名轮次混入当前进程历史）。"""
        try:
            with open(self._store, "r", encoding="utf-8") as f:
                rounds = json.load(f)
            if isinstance(rounds, list):
                clean = [r for r in rounds
                         if isinstance(r, dict) and "ts" in r
                         and isinstance(r.get("chans"), dict)
                         and r.get("pid") == os.getpid()]
                with self._lock:
                    self._rounds = clean[-self._max:]
        except Exception:
            pass

    def _save(self):
        """轮次落盘（持锁调用）：tmp+replace 原子写；失败只丢持久化不丢内存。"""
        try:
            os.makedirs(os.path.dirname(self._store) or ".", exist_ok=True)
            tmp = self._store + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._rounds, f, ensure_ascii=False)
            os.replace(tmp, self._store)
        except Exception:
            pass

    def begin(self):
        with self._lock:
            self._cur = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "_t0": time.time(), "chans": {}}

    def channel(self, name: str, rows: int, lat: float):
        with self._lock:
            if self._cur is not None:
                prev = self._cur["chans"].get(name)
                if prev:
                    # 多查询轮（航线×日期×渠道各一次）：累加而非覆盖——
                    # 曾把 5 渠道×2 日期=10 行少报成 5
                    prev["rows"] += int(rows)
                    prev["lat"] = round((prev["lat"] + float(lat)) / 2, 1)
                    prev["ok"] = prev["ok"] or int(rows) > 0
                else:
                    self._cur["chans"][name] = {
                        "ok": int(rows) > 0, "rows": int(rows),
                        "lat": round(float(lat), 1)}

    def end(self):
        with self._lock:
            if self._cur is not None:
                self._cur["pid"] = os.getpid()
            if self._cur is None:
                return
            r = self._cur
            r["dur"] = round(time.time() - r.pop("_t0"), 1)
            r["rows"] = sum(c["rows"] for c in r["chans"].values())
            r["fails"] = sum(1 for c in r["chans"].values() if not c["ok"])
            self._cur = None
            self._rounds.append(r)
            if len(self._rounds) > self._max:
                self._rounds = self._rounds[-self._max:]
            self._save()

    def view(self) -> dict:
        with self._lock:
            rounds = list(self._rounds)
        return {"ok": True, "rounds": rounds,
                "since": self._since.strftime("%Y-%m-%d %H:%M")}


PULSE = Pulse()
