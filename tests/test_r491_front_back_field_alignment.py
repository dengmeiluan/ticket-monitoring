# -*- coding: utf-8 -*-
"""r491：把「前端读的字段，后端真的会产出」变成可执行断言。

背景：这类 bug 已经出现过两次——
  - r490 `/api/health` 的 scopes 只发 `{rate,attempts}`，前端读 `query_*`，
    「分域」这一维在生产上从未渲染；
  - 更早的分域口径错配（尝试级 vs 查询级）读出来对不上。
它们的共同点：**前端按字段名读，后端按另一套字段名发**，而没有一处测试
把两侧放在一起对。字符串守卫（`scoped('dom','国内')` 在场）对此完全无效。

这条契约不注入载荷，直接调真实的 `/api/paths` 构造器，拿真实产出与
前端读取的字段集比对。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 前端在这些对象上读 node.* / v.* 字段；只统计「节流行读取 PTH 节点」那一段
FRONT_SCOPE_ANCHOR = "const node=PTH[k]||{},pw=node.paths||{}"


def _front_fields():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index(FRONT_SCOPE_ANCHOR)
    # 节流行拼装整段（到下一个渠道 map 结束前）
    seg = w[i:i + 7000]
    return set(re.findall(r"\bnode\.([a-z_]+)", seg)), w


def _backend_node_keys(tmp_path):
    """真实 /api/paths 产出里，平台节点上实际存在的键。

    用临时账本固定「近 24h 有 pc/h5 两条 ok」的形态，不依赖本机生产库
    当前是否在跑；干净克隆也走同一条聚合实现。
    """
    import sqlite3
    import time

    import webui
    db = str(tmp_path / "paths.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY, platform TEXT,"
            " entry_path TEXT, path_status TEXT, from_city TEXT, to_city TEXT,"
            " depart_date TEXT, attempt_id TEXT, fetched_at TEXT)")
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        conn.executemany(
            "INSERT INTO fetch_paths (platform, entry_path, path_status,"
            " from_city, to_city, depart_date, attempt_id, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-10", "a1", now),
             ("ctrip", "H5", "ok", "SHA", "BJS", "2026-11-10", "a1", now),
             ("qunar", "H5", "blocked", "SHA", "BJS", "2026-11-10", "a2",
              now)])
        conn.commit()
    finally:
        conn.close()
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": db}}
    try:
        p = webui._paths_payload(24)
    finally:
        webui._State.cfg = old
    plats = (p or {}).get("platforms") or {}
    keys = set()
    for node in plats.values():
        keys |= set((node or {}).keys())
        for sc in ((node or {}).get("scopes") or {}).values():
            keys |= set((sc or {}).keys())
    return keys, len(plats)


def test_frontend_node_fields_all_exist_in_real_payload(tmp_path):
    front, w = _front_fields()
    # scroll/get/class 之类不是数据字段，排除
    front = {f for f in front if f not in ("scroll", "get", "class",
                                           "scrollLeft", "scrollWidth")}
    assert front, "未能解析节流行的 node.* 读取"
    back, n = _backend_node_keys(tmp_path)
    assert back, "聚合产出为空，判据失去锚点"
    missing = sorted(front - back)
    assert not missing, (
        "前端读取但后端不产出的字段（该维度会永远空白）：%s\n"
        "前端读取集合：%s" % (missing, sorted(front)))
