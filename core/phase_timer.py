"""分段计时（r1063 T77）：把"一次采集慢在哪一步"变成可读数字。

为什么需要：App 渠道单次查询实测 57–100 秒，而日志里明明能看出大头在
**导航**（切国内档 ~30s、打开长窗口日历 ~20s）。可现有账本只有查询级的
三个数（墙钟/有效工作/空等），它回答"这一轮多久"，回答不了"慢在哪一步"。
没有分段数就优化，只能靠猜。

用法::

    with self.timed("导航"):
        ...
    self.timed_mark("日历")          # 无 with 语法时手动打点
    self.phases.summary()            # [{"name": "导航", "s": 31.2}, ...]

约定：**只做观测，不做控制**。计时器永不抛异常、永不影响主流程——
计时把采集搞挂，比没有计时更糟。
"""
from __future__ import annotations

import time


class PhaseTimer:
    """一次采集内的分段计时器（同名的段会累加）。"""

    def __init__(self):
        self._rows = []          # [(name, seconds)]，保持先后顺序
        self._open = []          # [(name, t0)]
        self._t0 = time.time()

    # ---- 打点 ----
    def __call__(self, name: str):
        """`with timer("导航"): ...`"""
        timer = self

        class _Ctx:
            def __enter__(self):
                timer.start(name)
                return timer

            def __exit__(self, *exc):
                timer.stop(name)
                return False

        return _Ctx()

    def start(self, name: str) -> None:
        self._open.append((str(name or "?"), time.time()))

    def stop(self, name: str) -> float:
        name = str(name or "?")
        # 从最近打开的**同名**段开始关（允许嵌套同名）
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == name:
                _, t0 = self._open.pop(i)
                dt = max(0.0, time.time() - t0)
                self._rows.append((name, dt))
                return dt
        return 0.0

    def mark(self, name: str, seconds: float) -> None:
        """直接记一段已知耗时（例如外部已经量好的）。"""
        try:
            dt = float(seconds or 0)
        except (TypeError, ValueError):
            return
        if dt > 0:
            self._rows.append((str(name or "?"), dt))

    # ---- 读数 ----
    def total(self) -> float:
        return round(time.time() - self._t0, 1)

    def summary(self, top: int = 0) -> list:
        """[{name, s, n}]：同名累加，按耗时降序；`top` 只取前 N。"""
        agg = {}
        for name, dt in self._rows:
            cur = agg.setdefault(name, [0.0, 0])
            cur[0] += dt
            cur[1] += 1
        out = [{"name": k, "s": round(v[0], 1), "n": v[1]}
               for k, v in agg.items()]
        out.sort(key=lambda x: -x["s"])
        return out[:int(top)] if top else out

    def text(self, top: int = 3) -> str:
        """一句话读数：`导航 31s · 日历 20s · 明细 6s（共 60s）`。"""
        rows = self.summary(top)
        if not rows:
            return ""
        body = " · ".join("%s %ss" % (r["name"], int(r["s"])) for r in rows)
        return "%s（共 %ss）" % (body, int(self.total()))
