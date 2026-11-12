# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r316_sentinel_window.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import main as _m

from types import SimpleNamespace as _NS


# ---- merged from tests/test_r316_sentinel_window.py ----

def _iso(monkeypatch, tmp_path):
    # r320 写入面生产资格门同轮双锚：helper 读 SENTINEL_STATE_FILE
    # 环境变量优先，仅 patch 模块属性会被绕过（读写劈叉）
    monkeypatch.setenv("SENTINEL_STATE_FILE",
                       str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, *a, **k):
        self.seen.append(("W", a))

    def info(self, *a, **k):
        self.seen.append(("I", a))


def _rows_win(n, **kw):
    """单窗直飞行群夹具：n 行、全直飞（无 transCity）；kw 覆盖字段。"""
    row = {"price": 1000, "cabin": "", "meal": "", "prate": "",
           "plane": "", "psize": "", "discount": "4.5折",
           "shareCarrier": "MU1234", "arrTerminal": "T2",
           "depAirport": "虹桥", "depAirportCode": "SHA",
           "arrAirportCode": "HAK"}
    row.update(kw)
    return [{"price": 1000, **row} for _ in range(n)]


def _rec(rows, fc="SHA", tc="HAK", dd="2027-01-29"):
    return [_NS(platform="tongcheng", from_city=fc, to_city=tc,
                depart_date=dd, extra=json.dumps(rows))]


def test_never_supplied_window_silent(monkeypatch, tmp_path):
    """窗口诞生起恒零=never-supplied 特征：分子恒 0 的窗不告警
    （不 WARNING 不 INFO 不计连败），观测面交给 conn 壳哨与 dump 调研。"""
    _iso(monkeypatch, tmp_path)
    lg = _L()
    rows = _rows_win(20)   # meal/prate/cabin/plane/psize 全空、直飞 20 行
    _m._field_sentinel(_rec(rows), lg)
    assert lg.seen == [], lg.seen
    assert ("tongcheng", "prate") not in _m._SENT_LAST
    assert ("tongcheng", "prate") not in _m._SENT_CNT


def test_supplied_then_broken_warns(monkeypatch, tmp_path):
    """曾供给后归零=断链真警：第一轮字段在场（写供给基线），
    第二轮同窗归零 → WARNING 照发（tx→td 事故模式防线不弱化）。"""
    _iso(monkeypatch, tmp_path)
    lg = _L()
    ok = _rows_win(20, meal="有餐食", prate="97", cabin="经济舱")
    _m._field_sentinel(_rec(ok), lg)
    assert lg.seen == [], lg.seen          # 供给轮健康不警
    assert _m._SENT_SUPPLIED[("tongcheng", "meal", "SHA", "HAK",
                              "2027-01-29")]
    bad = _rows_win(20)
    lg2 = _L()
    _m._field_sentinel(_rec(bad), lg2)
    kinds = {k for k, _ in lg2.seen}
    assert "W" in kinds, lg2.seen          # 断链真警
    texts = " ".join(str(a) for _, a in lg2.seen)
    assert "prate" in texts and "meal" in texts


def test_supplied_persisted_across_restart(monkeypatch, tmp_path):
    """供给基线持久化：sentinel_state.json 落 `supplied|` 族，
    进程重启（load 回读）后判定不丢——断链照警、never 窗照静默。"""
    _iso(monkeypatch, tmp_path)
    lg = _L()
    ok = _rows_win(20, meal="有餐食")
    _m._field_sentinel(_rec(ok), lg)
    disk = json.load(open(tmp_path / "sent.json", encoding="utf-8"))
    assert any(k.startswith("supplied|") for k in disk), disk.keys()
    # 模拟重启：内存态清空重载
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    _m._sent_load()
    lg2 = _L()
    _m._field_sentinel(_rec(_rows_win(20)), lg2)
    texts = " ".join(str(a) for _, a in lg2.seen)
    assert "meal" in texts, lg2.seen       # 重启后断链仍真警


def test_never_supplied_window_with_stale_flat_marks(monkeypatch, tmp_path):
    """never-supplied 窗静默且不产新窗键留痕；旧平键时代的存量留痕
    惰性滞留（窗键下告警状态按窗键判定，平键残留零消费点，摘除机械
    随共享键退役——静默不因残留平键翻转发）。"""
    _iso(monkeypatch, tmp_path)
    _m._SENT_LAST[("tongcheng", "prate")] = "2026-10-01"
    _m._SENT_CNT[("tongcheng", "prate")] = 7
    lg = _L()
    _m._field_sentinel(_rec(_rows_win(20)), lg)
    assert lg.seen == []
    assert ("tongcheng", "prate", "SHA", "HAK", "2027-01-29") \
        not in _m._SENT_LAST
    assert ("tongcheng", "prate") in _m._SENT_LAST


def test_never_supplied_silent_even_if_flat_mark_is_today(
        monkeypatch, tmp_path):
    """平键残留恰为「今日已报」形态（生产实况：连续在燃哨的日期恒
    今天）同样惰性：静默判定走窗键供给门（前置），平键残留既不触发
    告警也不得借道复活。"""
    _iso(monkeypatch, tmp_path)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    _m._SENT_LAST[("tongcheng", "prate")] = today
    _m._SENT_CNT[("tongcheng", "prate")] = 7
    lg = _L()
    _m._field_sentinel(_rec(_rows_win(20)), lg)
    assert lg.seen == []
    assert ("tongcheng", "prate", "SHA", "HAK", "2027-01-29") \
        not in _m._SENT_LAST


def test_window_isolation(monkeypatch, tmp_path):
    """窗隔离：同 (渠道×字段)，A 窗 never-supplied 静默、B 窗
    曾供给后断链真警——供给基线按窗维度记录，互不稀释。"""
    _iso(monkeypatch, tmp_path)
    lg = _L()
    ok_b = _rows_win(20, meal="有餐食")
    _m._field_sentinel(_rec(ok_b, fc="HAK", tc="SHA", dd="2027-02-13"), lg)
    assert lg.seen == []
    # A 窗（never）静默
    _m._field_sentinel(_rec(_rows_win(20), fc="SHA", tc="HAK",
                            dd="2027-01-29"), lg)
    texts_a = " ".join(str(a) for _, a in lg.seen)
    assert "meal" not in texts_a, lg.seen
    # B 窗断链真警
    _m._field_sentinel(_rec(_rows_win(20), fc="HAK", tc="SHA",
                            dd="2027-02-13"), lg)
    texts_b = " ".join(str(a) for _, a in lg.seen)
    assert "meal" in texts_b, lg.seen
