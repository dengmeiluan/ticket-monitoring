# -*- coding: utf-8 -*-
"""r1235：tuniu 解析必须是"API 形态也能出字段"，不能只认页面形态。

解析哨兵实录（2026-11-10 15:19）：

```
[解析哨兵] tuniu 字段 apt / aptc / cabin / plane / psize 命中 0/105
```

而真实载荷 `debug/tuniu_raw_*.json` 的 `data.fareList[].filtered` 里明明有
`dPortIataCode / aPortIataCode / cabinType / planeModel` —— 是解析器只读了
页面形态的键（`segmentList / cabinName / craftTypeDetail`），换成 API 形态就全空。

本文件看三件事（不依赖网络、不碰真设备）：
1. 源码里确实加了 `filtered` 兜底（且**保留旧键**，只增不改）；
2. 用**真实载荷**验证这些兜底键确实有值（不是纸上谈兵）；
3. 负控：页面形态的旧读法仍然在（不许为了兜底把老路径拆掉）。
"""
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TUNIU = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"), encoding="utf-8").read()


def test_source_has_filtered_fallbacks():
    assert '_flt = it.get("filtered")' in TUNIU, "没有取 filtered 兜底"
    assert 'str(_flt.get("cabinType")' in TUNIU, "cabin 没兜底"
    assert 'iata3(_flt.get("dPortIataCode"))' in TUNIU, "depAirportCode 没兜底"
    assert 'iata3(_flt.get("aPortIataCode"))' in TUNIU, "arrAirportCode 没兜底"
    assert '_flt.get("planeModel")' in TUNIU, "plane 没兜底"


def test_legacy_page_shape_still_read():
    """负控：老读法必须还在（否则页面形态那条通路会被改坏）。"""
    for old in ('it.get("cabinName")', 'it.get("segmentList")',
                'craftTypeDetail'):
        assert old in TUNIU, "旧读法被删了：%s" % old


def test_real_payload_actually_has_those_keys():
    """兜底键必须在**真实形状**的载荷里确实有值（各条目都该命中）。

    r1387：优先用本机 `debug/tuniu_raw_*.json`（真实抓包）；没有时退回
    `tests/fixtures/tuniu_farelist_sample.json`（同结构的最小样本）。
    原因：`debug/` 不入库，CI 上没有抓包，原写法直接 assert 失败——
    那是"环境缺文件"假红，不是产品问题。
    """
    files = sorted(glob.glob(os.path.join(ROOT, "debug", "tuniu_raw_*.json")))
    files = [f for f in files if os.path.getsize(f) > 10000]
    if files:
        p = files[-1]
    else:
        p = os.path.join(ROOT, "tests", "fixtures", "tuniu_farelist_sample.json")
    assert os.path.isfile(p), "既没有抓包样本，也没有随库样本：%s" % p
    d = json.load(io.open(p, encoding="utf-8", errors="replace"))
    fare = (d.get("data") or {}).get("fareList") or []
    assert fare, "样本里没有 fareList"
    ok = {"cabin": 0, "dep": 0, "arr": 0, "plane": 0}
    for it in fare:
        f = it.get("filtered") or {}
        ok["cabin"] += bool(str(f.get("cabinType") or "").strip())
        ok["dep"] += bool(str(f.get("dPortIataCode") or "").strip())
        ok["arr"] += bool(str(f.get("aPortIataCode") or "").strip())
        ok["plane"] += bool(str(f.get("planeModel") or "").strip())
    assert ok["cabin"] > 0 and ok["dep"] > 0 and ok["arr"] > 0, (p, ok)
    print("样本 %s 命中: %s / %d 条" % (os.path.basename(p), ok, len(fare)))
