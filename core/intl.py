# -*- coding: utf-8 -*-
"""国际航班 scope 单源（r325）：自动判定 + 国际城市字典 + 时区表。

设计契约 docs/INTL_DESIGN.md §1.1/§1.2：
- scope 全自动判定，零配置——可判定的事不做配置；
- MAINLAND_CODES = core.citydata.CITY 值域剔除「中国」前缀条目
  （香港/澳门/台北等港澳门票在 OTA 语境走国际票体系，字典自带的
  前缀标记直接复用），再并 MAINLAND_AIRPORTS_EXTRA 机场级补充
  （城市字典是城市码口径，PEK/PKX 等机场码不在其中，缺了会把
  大陆机场误判国际）；
- 时区表存 IANA 名：偏移由 zoneinfo 按采集时刻实时算（DST 正确，
  静态数字表在欧美夏令时错 1 小时），爬虫解析时落数进元素
  tz_dep/tz_arr；未知码不落时区键 → flightnorm 国际档信渠道时长。
运行时零外部服务依赖（zoneinfo 是 stdlib；tzdata 纯 python 包已随
APScheduler 链在装，requirements 显式化）。
"""
import datetime as _dt

from core.citydata import CITY

# 「中国」前缀条目 = 港澳台（中国香港/中国澳门/中国台北/中国高雄…），
# OTA 语境票务走国际体系——从大陆码集合剔除
_MAINLAND = {code for name, code in CITY.items()
             if not str(name).startswith("中国")}

# 大陆机场三字码补充（城市字典是城市码口径；PEK/PVX 这类机场码不在
# CITY 值域，缺补会把大陆机场误判国际）。只收确定性高的大陆机场码；
# 漏收的真代价=该机场航线被分流国际端点，宁全勿缺
_MAINLAND_AIRPORTS_EXTRA = {
    # 华北东北
    "PEK", "PKX", "BJS", "TSN", "SJW", "TYN", "HET", "DLC", "SHE",
    "HRB", "CGQ", "YNT", "WEH",
    # 华东
    "SHA", "PVG", "HGH", "NKG", "WUX", "NGB", "WNZ", "HYN", "NTG",
    "LYG", "FOC", "XMN", "JJN", "TAO", "JNG",
    # 中南华南
    "CAN", "SZX", "CSX", "WUH", "KHN", "ZZV", "CGO", "SYX", "HAK",
    "NNG", "KWL", "MXZ", "ZUH",
    # 西南西北
    "CTU", "TFU", "CKG", "KMG", "GUI", "LZO", "XIY", "LHW", "URC",
    "KRL", "KHG", "AKU", "YIN", "HMI", "XNN", "INC",
}

# 大陆码全集（scope 判定唯一事实源）：城市字典 + 手工机场补充 +
# 官方字典机场全集（R33 自我进化：携程 17909 SearchBoxRecommend
# airportlst 并集 271 机场码官方口径——构建期生成本体
# core/ctrip_dict_gen.py，更新走 scripts/build_ctrip_dict.py）
from core.ctrip_dict_gen import (OFFICIAL_AIRPORT_CITY,  # noqa: E402
                                 OFFICIAL_INTL_NAME,
                                 OFFICIAL_MAINLAND_AIRPORTS as
                                 _OFFICIAL_MAINLAND_AIRPORTS)
MAINLAND_CODES = (frozenset(_MAINLAND)
                  | frozenset(_MAINLAND_AIRPORTS_EXTRA)
                  | _OFFICIAL_MAINLAND_AIRPORTS)

# 国际目的地字典：IATA 码 → 展示名（城市+场名；城市级别名给 TYO/SEL/
# OSA 三码）。精选热门目的地，未收录码原样显示三字码（宁缺勿错，
# 同 flightnorm.AIRPORT_NAME_CN 先例）。热榜另见 INTL_CITY_HOT
INTL_CITY_NAME = {
    # 港澳台（OTA 国际票体系）
    "HKG": "香港", "MFM": "澳门", "TPE": "台北桃园", "KHH": "高雄",
    "RMQ": "台中",
    # 日本
    "NRT": "东京成田", "HND": "东京羽田", "TYO": "东京",
    "KIX": "大阪关西", "OSA": "大阪", "CTS": "札幌新千岁",
    "OKA": "冲绳那霸", "FUK": "福冈", "NGO": "名古屋中部",
    # 韩国
    "ICN": "首尔仁川", "GMP": "首尔金浦", "SEL": "首尔",
    "PUS": "釜山", "CJU": "济州",
    # 东南亚
    "SIN": "新加坡", "BKK": "曼谷素万那普", "DMK": "曼谷廊曼",
    "HKT": "普吉", "CNX": "清迈", "USM": "苏梅岛", "KBV": "甲米",
    "KUL": "吉隆坡", "PEN": "槟城", "LGK": "兰卡威",
    "CGK": "雅加达", "DPS": "巴厘岛", "MNL": "马尼拉", "CEB": "宿务",
    "SGN": "胡志明市", "HAN": "河内", "DAD": "岘港", "CXR": "芽庄",
    "PNH": "金边", "REP": "暹粒", "VTE": "万象", "RGN": "仰光",
    # 南亚
    "DEL": "德里", "BOM": "孟买", "BLR": "班加罗尔", "MAA": "金奈",
    "CMB": "科伦坡", "MLE": "马累", "KTM": "加德满都", "DAC": "达卡",
    # 中东
    "DXB": "迪拜", "AUH": "阿布扎比", "DOH": "多哈",
    "IST": "伊斯坦布尔", "RUH": "利雅得", "JED": "吉达",
    "TLV": "特拉维夫",
    # 欧洲
    "LHR": "伦敦希思罗", "LGW": "伦敦盖特威克", "MAN": "曼彻斯特",
    "CDG": "巴黎戴高乐", "NCE": "尼斯", "FRA": "法兰克福",
    "MUC": "慕尼黑", "BER": "柏林", "AMS": "阿姆斯特丹",
    "BRU": "布鲁塞尔", "ZRH": "苏黎世", "GVA": "日内瓦",
    "VIE": "维也纳", "PRG": "布拉格", "WAW": "华沙", "BUD": "布达佩斯",
    "FCO": "罗马", "MXP": "米兰", "MAD": "马德里", "BCN": "巴塞罗那",
    "LIS": "里斯本", "ATH": "雅典", "CPH": "哥本哈根",
    "ARN": "斯德哥尔摩", "OSL": "奥斯陆", "HEL": "赫尔辛基",
    "DUB": "都柏林", "EDI": "爱丁堡", "SVO": "莫斯科",
    "LED": "圣彼得堡",
    # 北美
    "JFK": "纽约肯尼迪", "EWR": "纽约纽瓦克", "LAX": "洛杉矶",
    "SFO": "旧金山", "ORD": "芝加哥", "DFW": "达拉斯",
    "IAH": "休斯敦", "MIA": "迈阿密", "SEA": "西雅图", "BOS": "波士顿",
    "IAD": "华盛顿杜勒斯", "HNL": "檀香山", "YVR": "温哥华",
    "YYZ": "多伦多",
    # 大洋洲
    "SYD": "悉尼", "MEL": "墨尔本", "BNE": "布里斯班", "PER": "珀斯",
    "CNS": "凯恩斯", "AKL": "奥克兰",
    # 非洲
    "JNB": "约翰内斯堡", "CPT": "开普敦", "CAI": "开罗",
    "ADD": "亚的斯亚贝巴", "NBO": "内罗毕",
}

# IANA 时区（按码）：偏移经 zoneinfo 实时算，DST 半年差由真历法兜住。
# 不变量：INTL_CITY_NAME 的每个键必须在本表有区（tests 钉）
INTL_TZ = {
    # 港澳台
    "HKG": "Asia/Hong_Kong", "MFM": "Asia/Macau",
    "TPE": "Asia/Taipei", "KHH": "Asia/Taipei", "RMQ": "Asia/Taipei",
    # 日本
    "NRT": "Asia/Tokyo", "HND": "Asia/Tokyo", "TYO": "Asia/Tokyo",
    "KIX": "Asia/Tokyo", "OSA": "Asia/Tokyo", "CTS": "Asia/Tokyo",
    "OKA": "Asia/Tokyo", "FUK": "Asia/Tokyo", "NGO": "Asia/Tokyo",
    # 韩国
    "ICN": "Asia/Seoul", "GMP": "Asia/Seoul", "SEL": "Asia/Seoul",
    "PUS": "Asia/Seoul", "CJU": "Asia/Seoul",
    # 东南亚
    "SIN": "Asia/Singapore", "BKK": "Asia/Bangkok",
    "DMK": "Asia/Bangkok", "HKT": "Asia/Bangkok",
    "CNX": "Asia/Bangkok", "USM": "Asia/Bangkok",
    "KBV": "Asia/Bangkok", "KUL": "Asia/Kuala_Lumpur",
    "PEN": "Asia/Kuala_Lumpur", "LGK": "Asia/Kuala_Lumpur",
    "CGK": "Asia/Jakarta", "DPS": "Asia/Makassar",
    "MNL": "Asia/Manila", "CEB": "Asia/Manila",
    "SGN": "Asia/Ho_Chi_Minh", "HAN": "Asia/Ho_Chi_Minh",
    "DAD": "Asia/Ho_Chi_Minh", "CXR": "Asia/Ho_Chi_Minh",
    "PNH": "Asia/Bangkok", "REP": "Asia/Bangkok",
    "VTE": "Asia/Bangkok", "RGN": "Asia/Yangon",
    # 南亚
    "DEL": "Asia/Kolkata", "BOM": "Asia/Kolkata",
    "BLR": "Asia/Kolkata", "MAA": "Asia/Kolkata",
    "CMB": "Asia/Colombo", "MLE": "Indian/Maldives",
    "KTM": "Asia/Kathmandu", "DAC": "Asia/Dhaka",
    # 中东
    "DXB": "Asia/Dubai", "AUH": "Asia/Dubai", "DOH": "Asia/Qatar",
    "IST": "Europe/Istanbul", "RUH": "Asia/Riyadh",
    "JED": "Asia/Riyadh", "TLV": "Asia/Jerusalem",
    # 欧洲
    "LHR": "Europe/London", "LGW": "Europe/London",
    "MAN": "Europe/London", "EDI": "Europe/London",
    "CDG": "Europe/Paris", "NCE": "Europe/Paris",
    "FRA": "Europe/Berlin", "MUC": "Europe/Berlin",
    "BER": "Europe/Berlin", "AMS": "Europe/Amsterdam",
    "BRU": "Europe/Brussels", "ZRH": "Europe/Zurich",
    "GVA": "Europe/Zurich", "VIE": "Europe/Vienna",
    "PRG": "Europe/Prague", "WAW": "Europe/Warsaw",
    "BUD": "Europe/Budapest", "FCO": "Europe/Rome",
    "MXP": "Europe/Rome", "MAD": "Europe/Madrid",
    "BCN": "Europe/Madrid", "LIS": "Europe/Lisbon",
    "ATH": "Europe/Athens", "CPH": "Europe/Copenhagen",
    "ARN": "Europe/Stockholm", "OSL": "Europe/Oslo",
    "HEL": "Europe/Helsinki", "DUB": "Europe/Dublin",
    "SVO": "Europe/Moscow", "LED": "Europe/Moscow",
    # 北美
    "JFK": "America/New_York", "EWR": "America/New_York",
    "BOS": "America/New_York", "IAD": "America/New_York",
    "MIA": "America/New_York", "LAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles", "SEA": "America/Los_Angeles",
    "ORD": "America/Chicago", "DFW": "America/Chicago",
    "IAH": "America/Chicago", "HNL": "Pacific/Honolulu",
    "YVR": "America/Vancouver", "YYZ": "America/Toronto",
    # 大洋洲
    "SYD": "Australia/Sydney", "MEL": "Australia/Sydney",
    "BNE": "Australia/Brisbane", "CNS": "Australia/Brisbane",
    "PER": "Australia/Perth", "AKL": "Pacific/Auckland",
    # 非洲
    "JNB": "Africa/Johannesburg", "CPT": "Africa/Johannesburg",
    "CAI": "Africa/Cairo", "ADD": "Africa/Addis_Ababa",
    "NBO": "Africa/Nairobi",
}

# 城市面板国际页签热榜（展示序=近邻圈优先：日韩东南亚 → 中东 →
# 欧美澳），面板页签按此序渲染
INTL_CITY_HOT = [
    "HKG", "MFM", "TPE", "NRT", "HND", "KIX", "ICN", "SEL", "BKK",
    "DMK", "HKT", "SIN", "KUL", "CGK", "DPS", "MNL", "SGN", "HAN",
    "DXB", "DOH", "LHR", "CDG", "FRA", "FCO", "MAD", "AMS", "SVO",
    "JFK", "LAX", "SFO", "SYD", "MEL", "AKL",
]

# 官方国际城市名并集（R33 自我进化：ctrip 官方 international=true 50 城
# 中文名官方口径优先——覆盖手工精选未收录的目的地【富国岛/清州/第比利
# 斯/马德里…】，面板「国际」完整度对齐渠道权威）
INTL_CITY_NAME.update(OFFICIAL_INTL_NAME)

# 去哪儿国际目的地并集（R35 三源汇集：缺者补入，官方/精选已收录的不
# 覆盖；时区随 QUNAR_INTL_TZ 增补进 INTL_TZ）
from core.qunar_dict_gen import QUNAR_INTL_NAME as _QUNAR_INTL_NAME
from core.qunar_dict_gen import QUNAR_INTL_TZ as _QUNAR_INTL_TZ
INTL_CITY_NAME.update(
    {k: v for k, v in _QUNAR_INTL_NAME.items() if k not in INTL_CITY_NAME})
INTL_TZ.update(_QUNAR_INTL_TZ)
# 三源汇集城市的 IANA 补全（R35：城市级码 LON/PAR/NYC/MOW/MIL/ROM/
# SPK 等官方城市码 + qunar 新目的地——全部 ZoneInfo 实例化验证过）
INTL_TZ.update({
    "BKI": "Asia/Kota_Kinabalu", "CJJ": "Asia/Seoul",
    "JKT": "Asia/Jakarta", "LON": "Europe/London",
    "MIL": "Europe/Rome", "MOW": "Europe/Moscow",
    "NYC": "America/New_York", "PAR": "Europe/Paris",
    "PQC": "Asia/Ho_Chi_Minh", "ROM": "Europe/Rome",
    "SPK": "Asia/Tokyo", "TBS": "Asia/Tbilisi",
    "ATL": "America/New_York", "DRW": "Australia/Darwin",
    "DTT": "America/Detroit", "DUD": "Pacific/Auckland",
    "DUR": "Africa/Johannesburg", "FNA": "Africa/Freetown",
    "GBE": "Africa/Gaborone", "HBA": "Australia/Hobart",
    "IEV": "Europe/Kiev", "LXR": "Africa/Cairo",
    "MPM": "Africa/Maputo", "ORL": "America/New_York",
})


# 国际地区分组（R36 双 Tab：面板国际页签按地区分组，对齐 ctrip/
# 去哪儿「国内/国际」双 Tab 心智）。未命中码归「其他国际」
_INTL_REGION_SETS = [
    ("港澳台", {"HKG", "MFM", "TPE", "KHH", "RMQ"}),
    ("日韩", {"NRT", "HND", "TYO", "KIX", "OSA", "CTS", "OKA", "FUK",
             "NGO", "SPK", "ICN", "GMP", "SEL", "PUS", "CJU", "CJJ",
             "IBR"}),
    ("东南亚", {"SIN", "BKK", "DMK", "HKT", "CNX", "USM", "KBV", "KUL",
               "PEN", "LGK", "CGK", "DPS", "MNL", "CEB", "SGN", "HAN",
               "DAD", "CXR", "PNH", "REP", "VTE", "RGN", "PQC", "BKI",
               "JKT"}),
    ("南亚", {"DEL", "BOM", "BLR", "MAA", "CMB", "MLE", "KTM", "DAC"}),
    ("中东", {"DXB", "AUH", "DOH", "IST", "RUH", "JED", "TLV", "TBS"}),
    ("欧洲", {"LHR", "LGW", "LON", "MAN", "EDI", "CDG", "NCE", "PAR",
             "FRA", "MUC", "BER", "AMS", "BRU", "ZRH", "GVA", "VIE",
             "PRG", "WAW", "BUD", "FCO", "MXP", "ROM", "MIL", "MAD",
             "BCN", "LIS", "ATH", "CPH", "ARN", "STO", "OSL", "HEL",
             "DUB", "SVO", "LED", "MOW", "DUS", "GLA", "HAM",
             "BHX", "NCL", "IEV"}),
    ("美洲", {"JFK", "EWR", "LAX", "SFO", "ORD", "DFW", "IAH", "MIA",
             "SEA", "BOS", "IAD", "HNL", "YVR", "YYZ", "YTO", "YMQ",
             "YOW", "YYC", "YEA", "CHI", "HOU", "MSP", "PHL", "LAS",
             "DEN", "WAS", "ATL", "ORL", "DTT", "MEX", "SAO",
             "NYC", "BUE"}),
    ("大洋洲", {"SYD", "MEL", "BNE", "PER", "CNS", "AKL", "OOL",
               "CBR", "ADL", "WLG", "NAN", "PPT", "DRW", "HBA",
               "DUD", "SPN"}),
    ("非洲", {"JNB", "CPT", "CAI", "ADD", "NBO", "DAR", "TUN", "LOS",
             "MRU", "ABJ", "ACC", "KRT", "LAD", "FIH", "CAS", "ALG",
             "HRE", "YAO", "DLA", "LUN", "FNA", "GBE", "LXR",
             "DUR", "MPM"}),
]
INTL_REGION = {}
INTL_REGIONS = []
for _rl, _rc in _INTL_REGION_SETS:
    INTL_REGIONS.append(_rl)
    for _c in _rc:
        INTL_REGION[_c] = _rl
INTL_REGIONS.append("其他国际")
INTL_REGION["ULN"] = "其他国际"   # 乌兰巴托：蒙古语义不入日韩，显式兜底


def intl_region_of(code):
    """码 → 地区分组标签（面板国际页签分组用；未命中归其他国际）。"""
    return INTL_REGION.get(str(code or "").strip().upper(), "其他国际")


# 城市级短名（搜索参数用）：部分渠道国际搜索参数收中文城市名
# （qunar touchInterList depCity=上海 实证），机场全名形态（「东京成田」）
# 是否被搜索接受未验证——展示名（INTL_CITY_NAME）与搜索名分槽，
# 未收录的码回退展示名再回退裸码
INTL_CITY_SHORT = {
    "NRT": "东京", "HND": "东京", "KIX": "大阪", "CTS": "札幌",
    "OKA": "冲绳", "NGO": "名古屋", "ICN": "首尔", "GMP": "首尔",
    "BKK": "曼谷", "DMK": "曼谷", "LHR": "伦敦", "LGW": "伦敦",
    "CDG": "巴黎", "MXP": "米兰", "JFK": "纽约", "EWR": "纽约",
    "IAD": "华盛顿", "DPS": "巴厘岛", "FUK": "福冈",
}


def city_short_of(code) -> str:
    """码 → 城市级搜索短名（qunar 等中文城市名参数渠道用）：
    短名表 → 展示名 → 裸码三级回退。"""
    c = str(code or "").strip().upper()
    return INTL_CITY_SHORT.get(c) or INTL_CITY_NAME.get(c) or c


# 机场码 → 城市码（飞猪国际搜索按城市码收，机场码被拒「城市基础数据
# 缺失」实证——report_fliggy.md §3；只收 IATA 标准城市码确定性高的对，
# 机场码=城市码同串的（BKK/SIN/HKT…）不列，恒等映射零成本）
INTL_AIRPORT_CITY = {
    "NRT": "TYO", "HND": "TYO", "KIX": "OSA", "ITM": "OSA",
    "LHR": "LON", "LGW": "LON", "CDG": "PAR", "ORY": "PAR",
    "JFK": "NYC", "EWR": "NYC", "LGA": "NYC",
    "FCO": "ROM", "MXP": "MIL", "SVO": "MOW", "DME": "MOW",
    "ARN": "STO",
    # 大陆同城多场归并城市码（同程/飞猪国际面按城市码收：同程实证
    # PEK→BJS/PVG→SHA，report_tongcheng.md §7；PVG→SHA 飞猪同义
    # ——SHA 城市码覆盖虹桥/浦东，report_fliggy.md §3）
    "PEK": "BJS", "PKX": "BJS", "PVG": "SHA",
}

# 官方机场归属并集（R33 自我进化：ctrip airportlst 推导 92 对官方
# 口径——手工表为官方缺项兜底，官方键优先；大陆归并对（PEK→BJS）
# 已在上方手工表，官方 airportlst 只含国际城市不覆盖）
INTL_AIRPORT_CITY.update(
    {k: v for k, v in OFFICIAL_AIRPORT_CITY.items()
     if v in OFFICIAL_INTL_NAME})


def airport_city_code(code) -> str:
    """机场码 → 渠道城市码（飞猪族）：映射表 → 原码（恒等回退）。"""
    c = str(code or "").strip().upper()
    return INTL_AIRPORT_CITY.get(c, c)


def is_intl_city(code) -> bool:
    """三字码 → 是否国际城市/机场：合法 IATA3 且不在大陆码全集。
    非法码（空串/中文/数字）恒 False（宁缺勿错——判不了的不硬判）。"""
    c = str(code or "").strip().upper()
    return bool(_is_iata3(c)) and c not in MAINLAND_CODES


def _is_iata3(c: str) -> bool:
    return len(c) == 3 and c.isalpha() and c.isascii()


def is_intl_route(from_code, to_code) -> bool:
    """航线 scope：任一端国际即国际（自动判定，零配置）。"""
    return is_intl_city(from_code) or is_intl_city(to_code)


def city_name_of(code) -> str:
    """码 → 展示名：国际字典 → 国内 CODE_NAME 反查 → 原样码。"""
    c = str(code or "").strip().upper()
    if c in INTL_CITY_NAME:
        return INTL_CITY_NAME[c]
    try:
        from core.citydata import CODE_NAME
        if c in CODE_NAME:
            return CODE_NAME[c]
    except Exception:
        pass
    return c


def tz_offset_min(code, when=None):
    """机场码 → 当地对 UTC 偏移分钟（东正西负；DST 按查询时刻真历法）。
    大陆码恒 480（全国统一 UTC+8、无夏令时）——跨区判定需要两端偏移
    都已知（SHA→NRT 480/540 落时区键；SHA→HKG 480/480 同区不落）。
    未知码/无区返回 None——调用方不落 tz_dep/tz_arr 键，
    flightnorm 国际档对无时区行信渠道时长。"""
    c = str(code or "").strip().upper()
    if c in MAINLAND_CODES:
        return 480
    zone = INTL_TZ.get(c)
    if not zone:
        return None
    try:
        from zoneinfo import ZoneInfo
        when = when or _dt.datetime.now(_dt.timezone.utc)
        off = ZoneInfo(zone).utcoffset(when)
        return int(off.total_seconds() // 60) if off is not None else None
    except Exception:
        return None
