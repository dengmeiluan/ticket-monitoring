# -*- coding: utf-8 -*-
"""构建期工具：携程官方城市字典（17909 SearchBoxRecommend）→ 生成
core/ctrip_dict_gen.py（运行时零外部依赖，r320 官方字典构建期拉取同律）。

用法：python scripts/build_ctrip_dict.py [官方响应JSON路径]
缺省读 _scratch/intl/official_dict_sample.json（2026-10-17 用户实测
样本，357 城含 50 国际城市）。重新拉取：按 docs/INTL_CALIBRATION.md
R7 复火轮的 SearchBoxRecommend curl 执行后重跑本脚本。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "_scratch", "intl",
                       "official_dict_sample.json")


def _walk_cities(obj, out):
    if isinstance(obj, dict):
        if "code" in obj and "name" in obj and "airportlst" in obj \
                and ("international" in obj or "timeZone" in obj):
            out[obj["code"]] = obj
        for v in obj.values():
            _walk_cities(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_cities(v, out)


def main(path):
    data = json.load(open(path, encoding="utf-8"))
    cities = {}
    _walk_cities(data, cities)
    # 去重（同一城市可能出现在 hot/indexed 多组）
    intl = {c: o for c, o in cities.items() if o.get("international")}
    dom = {c: o for c, o in cities.items()
           if not o.get("international") and o.get("type") == 1}
    # 机场归属官方推导：国际城市 airportlst → 机场码归其城市
    apt2city = {}
    for code, o in intl.items():
        for a in (o.get("airportlst") or []):
            apt2city[a["code"]] = code
    # 大陆城市机场全集（international=false 且 type=1）
    dom_apts = {a["code"] for o in dom.values()
                for a in (o.get("airportlst") or [])}

    lines = [
        "# -*- coding: utf-8 -*-",
        '"""携程官方城市字典生成件（构建期拉取 → 运行时零依赖）。',
        "",
        "来源：m.ctrip.com/restapi/soa2/17909/SearchBoxRecommend"
        "（2026-10-17 实测样本 _scratch/intl/official_dict_sample.json，",
        "357 城/50 国际城市/机场归属官方 airportlst 推导）。",
        "重生成：python scripts/build_ctrip_dict.py [样本路径]。",
        "勿手改本文件——更新走构建脚本（r320 官方字典同律）。",
        '"""',
        "",
        "# 官方 international=true 城市码全集（50 城，OTA 国际票体系",
        "# 的渠道权威口径）",
        "OFFICIAL_INTL_CODES = frozenset(" + json.dumps(
            sorted(intl), ensure_ascii=False) + ")",
        "",
        "# 官方国际城市 → 中文名（面板/显示名源）",
        "OFFICIAL_INTL_NAME = " + json.dumps(
            {c: intl[c]["name"] for c in sorted(intl)},
            ensure_ascii=False, indent=4),
        "",
        "# 官方国际城市 → 标准时偏移分钟（tzi.guv，东正西负；DST 由",
        "# core.intl 的 IANA 表运行时修正，此处为交叉校验基准）",
        "OFFICIAL_INTL_TZ = " + json.dumps(
            {c: int((intl[c].get("tzi") or {}).get("guv", "+0000")
                    [:3]) * 60
             + (int((intl[c].get("tzi") or {}).get("guv", "+0000")
                 [4:6]) * (1 if (intl[c].get("tzi") or {}).get(
                     "guv", "+0000")[0] != "-" else -1))
             for c in sorted(intl)},
            indent=4),
        "",
        "# 机场码 → 国际城市码（官方 airportlst 归属推导：NRT/HND→TYO、",
        "# LHR/LGW→LON、JFK/EWR→NYC…全量官方，替代手工映射）",
        "OFFICIAL_AIRPORT_CITY = " + json.dumps(
            dict(sorted(apt2city.items())), indent=4),
        "",
        "# 大陆城市机场码全集（international=false&type=1 城市",
        "# airportlst 并集，官方口径）——scope 判定的机场级兜底",
        "OFFICIAL_MAINLAND_AIRPORTS = frozenset(" + json.dumps(
            sorted(dom_apts)) + ")",
        "",
        "# 大陆城市码全集（type=1）",
        "OFFICIAL_MAINLAND_CITIES = frozenset(" + json.dumps(
            sorted(dom)) + ")",
        "",
    ]
    out = os.path.join(HERE, "..", "core", "ctrip_dict_gen.py")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    print(f"生成 core/ctrip_dict_gen.py：intl={len(intl)} dom={len(dom)} "
          f"机场归属={len(apt2city)} 大陆机场={len(dom_apts)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
