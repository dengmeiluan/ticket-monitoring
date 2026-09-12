# -*- coding: utf-8 -*-
"""扫描脉冲记录器：每轮每渠道 成败/行数/耗时 的进程内环形缓冲。

主页 01 PULSE 概览条与 04 HEALTH 脉冲柱的数据源（/api/pulse 直接吐视图）。
不落盘——轮次数据是短期可观察性，重启清零即可。"""
import threading
import time
from datetime import datetime


class Pulse:
    def __init__(self, maxlen: int = 48):
        self._max = maxlen
        self._lock = threading.Lock()
        self._rounds = []          # 已完成轮次（旧→新）
        self._cur = None           # 进行中的一轮
        self._since = datetime.now()

    def begin(self):
        with self._lock:
            self._cur = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "_t0": time.time(), "chans": {}}

    def channel(self, name: str, rows: int, lat: float):
        with self._lock:
            if self._cur is not None:
                self._cur["chans"][name] = {
                    "ok": int(rows) > 0, "rows": int(rows),
                    "lat": round(float(lat), 1)}

    def end(self):
        with self._lock:
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

    def view(self) -> dict:
        with self._lock:
            rounds = list(self._rounds)
        return {"ok": True, "rounds": rounds,
                "since": self._since.strftime("%Y-%m-%d %H:%M")}


PULSE = Pulse()
