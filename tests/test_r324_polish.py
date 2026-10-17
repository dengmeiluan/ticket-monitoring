# -*- coding: utf-8 -*-
"""r324 落地批钉面。

- demo 半年走势日桶覆盖最旧历史日：明细行跨度 13d23h30m 触达 14 个
  自然日（今天往前 14 天），派生循环少刷最旧一日 → 长窗首桶比最老
  行晚一天（行在桶不在，「数据自 X 起」注与首桶同错）。
- 行内跳转链接 title 禁叠字：渠道名「去哪儿」与动词「去」相邻产出
  「去去哪儿查看该航线」——title 统一「在{渠道}查看该航线」。
  （源码钉：三处链接出口同改，出现「去${」+查看 组合即红。）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_polish.py -q
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_demo_daily_covers_oldest_history_day():
    from core.demo import build_demo_db, demo_routes
    from core.storage import PriceStorage
    path = os.path.join(tempfile.gettempdir(), "r324_demo_span_probe.db")
    try:
        build_demo_db(path)
        conn = sqlite3.connect(path)
        mn = conn.execute(
            "SELECT min(fetched_at) FROM flight_prices").fetchone()[0]
        conn.close()
        assert mn, "demo 库应有历史明细行"
        oldest_day = str(mn)[:10]                      # YYYY-MM-DD
        mmdd = oldest_day[5:]
        rt = demo_routes()[0]
        st = PriceStorage(path)
        rows = st.daily_series(rt["from"], rt["to"], rt["dates"][0],
                               days=30, th_d=0, kind="d")
        assert rows, "长窗应有日桶"
        assert rows[0]["day"] <= mmdd, (
            f"日桶首桶 {rows[0]['day']} 晚于最老明细日 {mmdd}——"
            "派生循环少刷最旧一日")
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_view_link_title_no_duplicated_qu():
    src = open(os.path.join(ROOT_DIR, "webui.py"),
               encoding="utf-8").read()
    assert src.count('title="在${') >= 3, "三处行内链接出口应统一「在{渠道}查看」"
    assert "去${platCn}查看" not in src, "numlink title 渠道名「去哪儿」与动词叠字"
    assert "去${he(x.plat" not in src and "去${he(f.plat" not in src, (
        "概览/明细行链接 title 同款叠字")
