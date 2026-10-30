# -*- coding: utf-8 -*-
"""r280 同程准点率恒档占位守卫（立案 R280-1）。

渠道侧退化实录：首见 2026-10-10 15:43，近 24h 1,422/1,422 元素恒
prate="50"（真源对照：10-07 报文同字段多值 {100×94, 97×56, 90×1}
→ 渠道上游退化为恒档默认词面透传）。原样入库经告警链同指纹决策
字段补全扩散到其他渠道行，渲染面全量「准点50%」假数据。

tuniu 恒 20 占位读层守卫同律（宁缺勿错）：恒 "50" 置空；渠道值域
恢复多值即撤守卫（观察哨在案：每轮全量键 diff 复验本守卫依据）。

fixture 按 debug/tongcheng_xhr_2027-02-14.txt 生产自然轮实证形态
构造（fl[].lps[].atp+brs 有票位、sts[].tt int/td 词面）。
"""
import json

from crawlers.tongcheng import TongchengCrawler


def _mk_xhr(prate_td: str) -> str:
    data = {"ec": 0, "d": "HAK", "a": "SHA", "dd": "2027-02-14",
            "fl": [{"fn": "SC2168", "asn": "SC",
                    "dt": "2027-02-14 19:05", "at": "2027-02-14 22:45",
                    "lps": [{"atp": 1750, "brs": [{"al": -1}]}],
                    "sts": [{"tt": 1, "td": prate_td},
                            {"tt": 4, "td": "无餐食"}]}]}
    # 响应包装层与生产同形（解析器取 obj["data"]，缺包装=恒零行）
    return json.dumps({"success": True, "data": data},
                      ensure_ascii=False)


def test_placeholder_50_never_lands():
    """恒档「到达准点率50%」不得落库（tuniu 恒 20 同律）。"""
    rows = TongchengCrawler._extract_flights(_mk_xhr("到达准点率50%"))
    assert rows, "回放零行=样本形态错位"
    assert all(r.get("prate") != "50" for r in rows), \
        f"恒档占位 50 落库: {set(r.get('prate') for r in rows)}"


def test_real_value_kept():
    """真实值域（多值时代的 97）照常入库——守卫不误杀真值。"""
    rows = TongchengCrawler._extract_flights(_mk_xhr("到达准点率97%"))
    assert rows and any(r.get("prate") == "97" for r in rows)


def test_placeholder_isolation_from_meal():
    """同 sts 内其余字段（tt=4 餐食）不受守卫牵连。"""
    rows = TongchengCrawler._extract_flights(_mk_xhr("到达准点率50%"))
    assert rows and all(r.get("meal") == "无餐食" for r in rows)
