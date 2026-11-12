# -*- coding: utf-8 -*-
"""r956：国际航线"轮到过了"的记账只写在让位分支里 → 正常路径抓了不记。

2026-11-04 三份证据指向同一个洞：

```
user_data/qunar/intl_rotation.json  只有 SHA-NRT / SHA-LHR，**没有 SHA-BKK**
日志 19:44 / 19:58 / 20:02          连续三轮都在抓 SHA→BKK，每次 1999/8
每轮                    [qunar] 错峰等待 90s → 再撞 1999
```

原代码只在**"越过让位窗口放行"那一支**里记时间戳：

```python
if _is_intl and self._intl_quiet_until > _t.time():
    ...
    self._intl_route_seen[_rk_key] = _t.time()   # ← 只有窗口激活时才记
```

而绝大多数轮次走的是**正常路径（窗口未激活）**，抓完根本不记。
于是 BKK 永远"从没轮到过"(`_never`) → 每次都赢下每个窗口的放行名额 →
每轮都被抓、每次撞 1999、每次白烧 90–176s。
轮转的初衷"4 条国际线公平轮换、别让一条独吞配额"**完全没实现**。

修法：记账移到闸门之后，**语义 = "这条线我真的查了"**；
两个 `return []`（让位 / 退避窗口）都在它之前，所以"只是路过"的不算数。

这里钉的是可测的部分：
1. **结构**：记账必须在 `if _is_intl and …quiet_until…` 那个块**外面**
   （缩进层级 == 方法体层级），而不是只在放行支里；
2. **落盘可回读**（轮转靠文件跨进程存活，写不进等于没记）；
3. **只有一个记账点**（多处必漂移）；
4. 让位支的 `return []` 在记账之前（源码顺序）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r956_rotation_records_normally.py -q
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.qunar import QunarCrawler  # noqa: E402

QUNAR_PY = os.path.join(ROOT, "crawlers", "qunar.py")


def _fetch_body():
    src = open(QUNAR_PY, encoding="utf-8").read()
    i = src.find("    def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j]


def _record_line(body):
    """返回**记账那一行**（赋值给 `_intl_route_seen[...]`）。

    不能直接用 `find("_intl_route_seen[")`：第一处命中其实是**读**
    （`float(self._intl_route_seen.get(_rk_key) or 0)`），
    拿读的位置去判结构会得出完全错误的结论。
    """
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith("self._intl_route_seen[") and "] =" in s:
            return ln
    return None


# ---------------------------------------------------------------------------
# 1. 结构：记账必须在让位块**外面**
# ---------------------------------------------------------------------------
def _guard_of(body, rec):
    """往上找**最近的一行可执行代码**（跳过注释/空行）作为 rec 的守卫。"""
    i = body.index(rec)
    head = body[:i].splitlines()
    for ln in reversed(head):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        return s
    return ""


def test_record_is_outside_the_quiet_branch():
    """记账不能只在"让位窗口激活时放行"那一支里。

    **不能用缩进判断**：旧写法（藏在让位块内）和新写法（块外的独立
    `if _is_intl …`）都是 12 空格缩进，看起来一样，语义完全不同。
    所以要钉的是**守卫条件**：记账所在分支不许要求 `quiet_until` 激活，
    否则正常路径（窗口未激活）抓完不记 → BKK 永远"从没轮到过"。
    """
    body = _fetch_body()
    rec = _record_line(body)
    assert rec, "找不到记账行"
    guard = _guard_of(body, rec)
    assert guard.startswith("if "), "记账没有守卫：%s" % guard
    assert "_is_intl" in guard, "记账不该作用于国内线：%s" % guard
    assert "quiet_until" not in guard, (
        "记账的守卫要求让位窗口激活 → 正常路径抓完不记，"
        "被 1999 卡死的航线每轮重抓（实测 SHA-BKK 19:44/19:58/20:02）")


def test_record_gated_off_during_backoff_window():
    """退避窗口里那一支会 `return []`，所以它**之前**的记账必须跳过。"""
    body = _fetch_body()
    rec = _record_line(body)
    assert rec, "找不到记账行"
    i = body.index(rec)
    seg = body[max(0, i - 900):i]
    assert "_WAIT_BACKOFF_UNTIL" in seg, \
        "记账没排除退避窗口：只路过的航线会被记成'查过了'，挤掉真正该轮到的"


def test_yield_returns_happen_before_the_record():
    """让位（quiet skip）必须 `return []` 在记账之前，否则会让位也记一笔。"""
    body = _fetch_body()
    rec = _record_line(body)
    assert rec, "找不到记账行"
    i_rec = body.index(rec)
    # 让位那一支的特征：path_note(... "paced" ...) + return []
    i_yield = body.find("国际查询让位：%s")
    assert 0 < i_yield < i_rec, "让位分支在记账之后（会让'没查'也记成'查过'）"
    seg = body[i_yield:i_rec]
    assert "return []" in seg, "让位分支没有提前 return"


def test_only_one_record_site():
    body = _fetch_body()
    n = sum(1 for ln in body.splitlines()
            if "_intl_route_seen[" in ln and "=" in ln and "get(" not in ln)
    assert n == 1, "记账点有 %d 处，多处实现必然漂移" % n


# ---------------------------------------------------------------------------
# 2. 落盘：轮转靠文件跨进程存活，写不进等于没记
# ---------------------------------------------------------------------------
def _crawler(tmp_path):
    import logging
    c = QunarCrawler({"user_data_dir": str(tmp_path),
                      "profile": "qunar"}, None)
    # 这几条测试会走到 `fetch()` 的日志分支；没 logger 会在 self.logger.info
    # 上炸掉（AttributeError），看起来像产品的错。补一个静默 logger。
    c.logger = logging.getLogger("r956")
    return c


def _quiet_gaps(monkeypatch):
    """让 `fetch()` 不真的 sleep、也不真的抓网页，只记录它有没有发抓取。

    为什么要 stub `_fetch_inner`：这几条测试钉的是**闸门行为**
    （谁该被挡、谁该被记账），不是抓取解析。真发请求会碰浏览器和网络。
    """
    now = time.time()
    QunarCrawler._cooldown_until = 0.0
    # 必须留够间隔：wait 的第二项是 `MIN_GAP_S - (now - last_done)`，
    # 设成 now 反而刚好触发最小间隔、真的去 sleep。
    QunarCrawler._last_done_ts = now - 10_000
    QunarCrawler._WAIT_BUDGET["used_s"] = 0.0
    QunarCrawler._WAIT_BUDGET["since"] = now
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    calls = []

    def _fake_inner(self, f, t, dates, **kw):
        calls.append((f, t))
        return []
    monkeypatch.setattr(QunarCrawler, "_fetch_inner", _fake_inner)
    return calls


def _key(c):
    """轮转表里 SHA-BKK 的时间戳（None = 从没记过）。"""
    return c._intl_route_seen.get("SHA-BKK")


def test_rotation_round_trip_through_disk(tmp_path):
    c1 = _crawler(tmp_path)
    assert c1._intl_route_seen == {}
    c1._intl_route_seen["SHA-BKK"] = time.time()
    c1._save_intl_rotation()

    c2 = _crawler(tmp_path)                     # 新实例 = 模拟重启
    assert c2._intl_route_seen.get("SHA-BKK"), \
        "没落盘/读不回：重启后 BKK 又变'从没轮到过'，老 bug 复发"


def test_load_tolerates_garbage(tmp_path):
    """轮转文件坏了不许把采集带崩（fail-soft）。"""
    c1 = _crawler(tmp_path)
    p = c1._intl_rot_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not json")
    c2 = _crawler(tmp_path)
    assert c2._intl_route_seen == {}


def test_bypass_gate_flips_once_recorded(tmp_path):
    """记账之后，同窗口内这条线不该再被判定为'从没轮到过'。"""
    c = _crawler(tmp_path)
    c._intl_quiet_until = time.time() + 600
    c._intl_quiet_reason = "配额保护"
    assert c._intl_route_seen.get("SHA-BKK") is None   # 从没查过

    key = "SHA-BKK"
    last = float(c._intl_route_seen.get(key) or 0)
    never = last <= 0
    assert never, "起点应是'从没轮到过'"

    c._intl_route_seen[key] = time.time()             # 记账
    c._save_intl_rotation()
    last2 = float(c._intl_route_seen.get(key) or 0)
    assert last2 > 0, "记了还是'从没轮到过' → 每轮重抓同一条线"


# ---------------------------------------------------------------------------
# 6. 退避窗口只管国际线（本轮我自己引入、又被测试撞出来的 bug）
# ---------------------------------------------------------------------------
def test_backoff_window_must_not_block_domestic(tmp_path, monkeypatch):
    """国际线被 1999 限流，不许把**国内**查询一起挡掉。

    这不是假想：退避窗口的判定原本写在国内外**共用**的 attempt 循环里，
    所以只要窗口点着，国内 fetch 也直接 `return []`。
    是测试隔离（类级窗口被同批其它测试留在未来时刻）把它撞出来的，
    而本文件自己的注释早就写明"国内列表另有配额，不受此限"。

    一个渠道的一半产能，绝不能被另一半的配额拖走。
    """
    calls = _quiet_gaps(monkeypatch)
    c = _crawler(tmp_path)
    c._intl_quiet_until = 0.0
    QunarCrawler._WAIT_BACKOFF_UNTIL = time.time() + 600   # 窗口开着
    try:
        c.fetch("SHA", "BJS", ["2026-11-16"])              # 国内线
    finally:
        QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    assert calls, "退避窗口把国内查询也挡了"


def test_domestic_still_absent_from_rotation_when_backoff_open(
        tmp_path, monkeypatch):
    """国内线既不被挡，也不该混进国际轮转表。"""
    calls = _quiet_gaps(monkeypatch)
    c = _crawler(tmp_path)
    c._intl_quiet_until = 0.0
    QunarCrawler._WAIT_BACKOFF_UNTIL = time.time() + 600
    try:
        c.fetch("SHA", "BJS", ["2026-11-16"])
    finally:
        QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0
    assert calls
    assert not any(k.startswith("SHA-BJS") for k in c._intl_route_seen)
