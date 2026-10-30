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
# 中文名官方口径——补齐手工精选未收录的目的地【富国岛/清州/第比利
# 斯/马德里…】，面板「国际」完整度对齐渠道权威）。缺者补入不覆盖：
# 精选段是场级全名（东京成田/曼谷素万那普双场城市族），官方城市级
# 短名兜底会把它盖回歧义名（裸 update 曾实锤，钉运行时真值守卫）
INTL_CITY_NAME.update(
    {k: v for k, v in OFFICIAL_INTL_NAME.items() if k not in INTL_CITY_NAME})

# 去哪儿国际目的地并集（R35 三源汇集：缺者补入，官方/精选已收录的不
# 覆盖；时区随 QUNAR_INTL_TZ 增补进 INTL_TZ）
from core.qunar_dict_gen import QUNAR_INTL_NAME as _QUNAR_INTL_NAME
from core.qunar_dict_gen import QUNAR_INTL_TZ as _QUNAR_INTL_TZ
INTL_CITY_NAME.update(
    {k: v for k, v in _QUNAR_INTL_NAME.items() if k not in INTL_CITY_NAME})
INTL_TZ.update(_QUNAR_INTL_TZ)

# 携程城市面板第四源（R55：用户面板五洲榜单逐字转录 149 城，我方缺
# 39 城补齐——名称=渠道显示形，码=标准 IATA，时区 IANA 全部 ZoneInfo
# 实例化验证；缺者补入不覆盖，精选段场级全名律同）。中拿两城官方
# 字典在场（ALA/TAS tz=5 实证），余 37 城以面板名+标准码收录
INTL_CITY_NAME.update({
    "ALA": "阿拉木图", "TAS": "塔什干", "VVO": "海参崴",
    "TOS": "特罗姆瑟", "KEF": "雷克雅未克", "BEG": "贝尔格莱德",
    "GUM": "关岛", "SAN": "圣迭戈", "CUN": "坎昆",
    "GRU": "圣保罗", "GIG": "里约热内卢", "SCL": "圣地亚哥",
    "LIM": "利马",
    "HRG": "赫尔格达", "SSH": "沙姆沙伊赫", "ASW": "阿斯旺",
    "RAK": "马拉喀什", "JRO": "乞力马扎罗", "ZNZ": "桑给巴尔",
    "CKY": "科纳克里", "TNR": "塔那那利佛", "KGL": "基加利",
    "EBB": "恩德培", "SEZ": "马埃岛", "DKR": "达喀尔",
    "PSR": "普罗瑟恩", "HTI": "哈密尔顿岛", "LST": "朗塞斯顿",
    "AYQ": "艾尔斯岩", "CHC": "基督城", "ZQN": "皇后镇",
    "HLZ": "汉密尔顿", "SUV": "苏瓦", "PPT": "帕皮提",
    "ROR": "科罗尔", "POM": "莫尔兹比港", "VLI": "维拉港",
    "RAR": "拉罗汤加", "HIR": "霍尼亚拉", "APW": "阿皮亚",
})
INTL_TZ.update({
    "ALA": "Asia/Almaty", "TAS": "Asia/Tashkent",
    "VVO": "Asia/Vladivostok",
    "TOS": "Europe/Oslo", "KEF": "Atlantic/Reykjavik",
    "BEG": "Europe/Belgrade",
    "GUM": "Pacific/Guam",
    "SAN": "America/Los_Angeles", "CUN": "America/Cancun",
    "GRU": "America/Sao_Paulo", "GIG": "America/Sao_Paulo",
    "SCL": "America/Santiago", "LIM": "America/Lima",
    "HRG": "Africa/Cairo", "SSH": "Africa/Cairo",
    "ASW": "Africa/Cairo", "RAK": "Africa/Casablanca",
    "JRO": "Africa/Dar_es_Salaam", "ZNZ": "Africa/Dar_es_Salaam",
    "CKY": "Africa/Conakry", "TNR": "Indian/Antananarivo",
    "KGL": "Africa/Kigali", "EBB": "Africa/Kampala",
    "SEZ": "Indian/Mahe", "DKR": "Africa/Dakar",
    "PSR": "Australia/Brisbane", "HTI": "Australia/Brisbane",
    "LST": "Australia/Hobart", "AYQ": "Australia/Darwin",
    "CHC": "Pacific/Auckland", "ZQN": "Pacific/Auckland",
    "HLZ": "Pacific/Auckland", "SUV": "Pacific/Fiji",
    "PPT": "Pacific/Tahiti", "ROR": "Pacific/Palau",
    "POM": "Pacific/Port_Moresby", "VLI": "Pacific/Efate",
    "RAR": "Pacific/Rarotonga", "HIR": "Pacific/Guadalcanal",
    "APW": "Pacific/Apia",
})

# 国际城市全拼（r326：面板「国际」页签拼音搜索路——README 三路搜索
# 承诺面，拼音路曾在 177 城缺席 "dongjing" 无匹配）。键=城市名（与
# core.citydata.CITY_NPY 同 convention，重名城市共条）；初字母表
# INTL_CITY_PY 由全拼派生（CITY_PY 首字母同律），消费端 webui 配置
# 载荷两表合并下发
INTL_CITY_NPY = {
    "中国香港": "zhongguoxianggang", "中国澳门": "zhongguoaomen",
    "中国台北": "zhongguotaibei", "香港": "xianggang", "澳门": "aomen",
    "台北桃园": "taibeitaoyuan", "高雄": "gaoxiong", "台中": "taizhong",
    "东京成田": "dongjingchengtian", "东京羽田": "dongjingyutian",
    "东京": "dongjing", "大阪关西": "dabanguanxi", "大阪": "daban",
    "札幌新千岁": "zhahuangxinqiansui", "札幌": "zhahuang",
    "冲绳": "chongsheng", "冲绳那霸": "chongshengnaba",
    "福冈": "fugang", "名古屋": "mingguwu", "名古屋中部": "mingguwuzhongbu",
    "茨城": "chicheng", "清州": "qingzhou",
    "首尔仁川": "shouerrenchuan", "首尔金浦": "shouerjinpu",
    "首尔": "shouer", "釜山": "pushan", "济州岛": "jizhoudao",
    "济州": "jizhou",
    "亚庇": "yabi", "新加坡": "xinjiapo", "曼谷": "manggu",
    "曼谷廊曼": "mangulangman", "曼谷素万那普": "mangusuwannapu",
    "普吉岛": "pujidao", "普吉": "puji", "清迈": "qingmai",
    "苏梅岛": "sumeidao", "甲米": "jiami", "吉隆坡": "jilongpo",
    "槟城": "bincheng", "兰卡威": "langkawei", "雅加达": "yajiada",
    "巴厘岛": "balidao", "马尼拉": "manila", "宿务": "suwu",
    "胡志明市": "huzhiminshi", "河内": "henei", "岘港": "xiangang",
    "芽庄": "yazhuang", "富国岛": "fuguodao", "金边": "jinbian",
    "暹粒": "xianli", "万象": "wanxiang", "仰光": "yangguang",
    "德里": "deli", "孟买": "mengmai", "班加罗尔": "banjialuoer",
    "金奈": "jinnai", "科伦坡": "kelunpo", "马累": "malei",
    "加德满都": "jiademandu", "达卡": "daka", "迪拜": "dubai",
    "阿布扎比": "abuzhabi", "多哈": "duoha", "伊斯坦布尔": "yisitanbuer",
    "利雅得": "liyade", "吉达": "jida", "特拉维夫": "telaweifu",
    "第比利斯": "dibilisi", "伦敦希思罗": "lundunxisiluo",
    "伦敦盖特威克": "lundungaiteweike", "伦敦": "lundun",
    "曼彻斯特": "manchesite", "爱丁堡": "aidinbao", "都柏林": "dubolin",
    "格拉斯哥": "gelasige", "巴黎戴高乐": "balidaigale", "巴黎": "bali",
    "尼斯": "nisi", "法兰克福": "flankefu", "慕尼黑": "munihei",
    "柏林": "bolin", "汉堡": "hanbao", "杜塞尔多夫": "dusaierduofu",
    "阿姆斯特丹": "amusitedan", "布鲁塞尔": "bulusaier",
    "苏黎世": "sulishi", "日内瓦": "rineiwa", "维也纳": "weiyena",
    "布拉格": "bulage", "华沙": "huasha", "布达佩斯": "budapeisi",
    "罗马": "luoma", "米兰": "mila", "马德里": "madeli",
    "巴塞罗那": "basailuona", "里斯本": "lisiben", "雅典": "yadian",
    "哥本哈根": "gebenhagen", "斯德哥尔摩": "sidegeermo",
    "奥斯陆": "aosilu", "赫尔辛基": "heerxinji", "莫斯科": "mosike",
    "圣彼得堡": "shengbidebao", "基辅": "jifu",
    "纽约肯尼迪": "niuyuekendini", "纽约纽瓦克": "niuyueniuwake",
    "纽约": "niuyue", "洛杉矶": "luoshanji", "旧金山": "jiujinshan",
    "芝加哥": "zhijiage", "达拉斯": "dalasi", "休斯敦": "xiusidun",
    "迈阿密": "maiami", "西雅图": "xiyatu", "波士顿": "bosidun",
    "华盛顿杜勒斯": "huashengdundulesi", "华盛顿": "huashengdun",
    "檀香山": "tanxiangshan", "温哥华": "wengehua",
    "多伦多": "duolunduo", "蒙特利尔": "mengtelier",
    "渥太华": "wotaihua", "卡尔加里": "kaerjiali",
    "埃德蒙顿": "aidemengdun", "悉尼": "xini", "墨尔本": "moerben",
    "布里斯班": "bulisiban", "珀斯": "posi", "凯恩斯": "kaiensi",
    "黄金海岸": "huangjinhaian", "阿德莱德": "adeleide",
    "堪培拉": "kanpeila", "霍巴特": "huobate", "达尔文": "daerwen",
    "达尼丁": "daniding",
    "奥克兰": "aokelan", "惠灵顿": "huilingdun", "楠迪": "nandi",
    "帕皮堤": "papidi", "塞班": "saiban", "约翰内斯堡": "yuehanneisibao",
    "开普敦": "kaipudun", "开罗": "kailuo", "卢克索": "lukesuo",
    "亚的斯亚贝巴": "yadisiyabeiba", "内罗毕": "neiluobi",
    "达累斯萨拉姆": "daleisisalamu", "哈拉雷": "halalei",
    "卢萨卡": "lusaka", "喀土穆": "katumu", "罗安达": "luoanda",
    "阿比让": "abirang", "阿克拉": "akela", "拉各斯": "lagesi",
    "杜阿拉": "duala", "雅温得": "yawende", "金沙萨": "jinshasa",
    "卡萨布兰卡": "kasabulanka", "阿尔及尔": "aerjier",
    "突尼斯": "tunisi", "马普托": "maputuo", "毛里求斯": "maoliqiusi",
    "费里敦": "feilidun", "哈博罗内": "haboluonei", "德班": "deban",
    "布宜诺斯艾利斯": "buyinuosailisi", "墨西哥城": "moxigecheng",
    "亚特兰大": "yatelanda", "奥兰多": "aolando", "费城": "feicheng",
    "明尼阿波利斯": "mingniabolisi", "底特律": "ditelv",
    "丹佛": "danfo", "拉斯维加斯": "lasiweijiasi",
    "乌兰巴托": "wulanbato",
    # R55 携程面板第四源 39 城拼音（三路搜索路）
    "阿拉木图": "alamuotu", "塔什干": "tashigan", "海参崴": "haishenwai",
    "特罗姆瑟": "teluomuse", "雷克雅未克": "leikeiyawieke",
    "贝尔格莱德": "beiergelaide", "关岛": "guandao",
    "圣迭戈": "shengdiege", "坎昆": "kankun",
    "圣保罗": "shengbaoluo", "里约热内卢": "liyaoreneilu",
    "圣地亚哥": "shengdiyage", "利马": "lima",
    "赫尔格达": "heergeda", "沙姆沙伊赫": "shamushayihe",
    "阿斯旺": "asiwang", "马拉喀什": "malakashi",
    "乞力马扎罗": "qilimazhaluo", "桑给巴尔": "sanggeibaer",
    "科纳克里": "kenakeli", "塔那那利佛": "tananalifo",
    "基加利": "jijiali", "恩德培": "endepei", "马埃岛": "maaidao",
    "达喀尔": "dakaer", "普罗瑟恩": "puluosaien",
    "哈密尔顿岛": "hamierdundao", "朗塞斯顿": "langsaidun",
    "艾尔斯岩": "aiersiyan", "基督城": "jiducheng",
    "皇后镇": "huanghouzhen", "汉密尔顿": "hanmierden",
    "苏瓦": "suwa", "帕皮提": "papiti", "科罗尔": "keluoer",
    "莫尔兹比港": "moerzibigang", "维拉港": "weilagang",
    "拉罗汤加": "lalotangjia", "霍尼亚拉": "huoniyala",
    "阿皮亚": "apiya",
}
INTL_CITY_PY = {k: v[0].upper() for k, v in INTL_CITY_NPY.items()}
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
             "BHX", "NCL", "IEV", "TOS", "KEF", "BEG"}),
    ("美洲", {"JFK", "EWR", "LAX", "SFO", "ORD", "DFW", "IAH", "MIA",
             "SEA", "BOS", "IAD", "HNL", "YVR", "YYZ", "YTO", "YMQ",
             "YOW", "YYC", "YEA", "CHI", "HOU", "MSP", "PHL", "LAS",
             "DEN", "WAS", "ATL", "ORL", "DTT", "MEX", "SAO",
             "NYC", "BUE", "SAN", "CUN", "GRU", "GIG", "SCL",
             "LIM"}),
    ("大洋洲", {"SYD", "MEL", "BNE", "PER", "CNS", "AKL", "OOL",
               "CBR", "ADL", "WLG", "NAN", "PPT", "DRW", "HBA",
               "DUD", "SPN", "GUM", "HTI", "LST", "AYQ", "ZQN",
               "HLZ", "SUV", "ROR", "POM", "VLI", "RAR", "HIR",
               "APW", "CHC", "PSR"}),
    ("非洲", {"JNB", "CPT", "CAI", "ADD", "NBO", "DAR", "TUN", "LOS",
             "MRU", "ABJ", "ACC", "KRT", "LAD", "FIH", "CAS", "ALG",
             "HRE", "YAO", "DLA", "LUN", "FNA", "GBE", "LXR",
             "DUR", "MPM", "HRG", "SSH", "ASW", "RAK", "JRO",
             "ZNZ", "CKY", "TNR", "KGL", "EBB", "SEZ", "DKR"}),
]
INTL_REGION = {}
INTL_REGIONS = []
for _rl, _rc in _INTL_REGION_SETS:
    INTL_REGIONS.append(_rl)
    for _c in _rc:
        INTL_REGION[_c] = _rl
INTL_REGIONS.append("其他国际")
INTL_REGION["ULN"] = "其他国际"   # 乌兰巴托：蒙古语义不入日韩，显式兜底
for _c in ("ALA", "TAS", "VVO"):   # R55 中亚+俄远东：显式兜底（不入日韩/中东语义域）
    INTL_REGION[_c] = "其他国际"


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
    when 收 datetime 或 'YYYY-MM-DD' 航班日串（锚定正午 UTC——date-only
    按 UTC 午夜解析会让东八早段把「当日」读成未来，正午锚距 DST 切换
    边界最远）；缺省回退抓取时刻。
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
        if isinstance(when, str) and when.strip():
            when = _dt.datetime.fromisoformat(
                when.strip()[:10]).replace(hour=12, tzinfo=_dt.timezone.utc)
        when = when or _dt.datetime.now(_dt.timezone.utc)
        off = ZoneInfo(zone).utcoffset(when)
        return int(off.total_seconds() // 60) if off is not None else None
    except Exception:
        return None


# ===== R55b 官方 17909 全量对齐（一切以携程的为准）=====
# 官方 intl=true 224 城全量对表：60 缺补入 + 14 名称形官方改写 +
# 我方误码置换（GRU/GIG/KEF/PSR 机场级码→SAO/RIO/REK/PPP 携程
# 城市级码）。名称/拼音一律官方 namePy 口径。
INTL_CITY_NAME.update({
    "TNN": "中国台南",
    "HUN": "中国花莲",
    "NQZ": "阿斯塔纳",
    "FRU": "比什凯克",
    "BAK": "巴库",
    "DYU": "杜尚别",
    "MSQ": "明斯克",
    "SCO": "阿克套",
    "EVN": "埃里温",
    "CIT": "奇穆肯特",
    "ISB": "伊斯兰堡",
    "OSS": "奥什",
    "ASB": "阿什哈巴德",
    "KBL": "喀布尔",
    "TWU": "斗湖",
    "JHB": "新山",
    "NHA": "芽庄",
    "SUB": "泗水",
    "LBJ": "拉布安",
    "MPH": "卡提克兰",
    "KTI": "金边",
    "SAI": "暹粒",
    "HKD": "函馆",
    "AKJ": "旭川",
    "AOJ": "青森市",
    "SDJ": "仙台",
    "MMY": "宫古岛",
    "HIJ": "广岛市",
    "TAK": "高松",
    "KMQ": "小松",
    "KOJ": "鹿儿岛",
    "KMJ": "熊本市",
    "FSZ": "静冈",
    "TOY": "富山市",
    "MMB": "女满别",
    "KUH": "钏路市",
    "TAE": "大邱",
    "KWJ": "光州",
    "YNY": "襄阳",
    "RSU": "丽水",
    "USN": "蔚山",
    "HIN": "晋州",
    "REK": "雷克雅未克",
    "SAO": "圣保罗",
    "RIO": "里约热内卢",
    "AYT": "安塔利亚",
    "NAV": "内夫谢希尔",
    "ASR": "开塞利",
    "ANK": "安卡拉",
    "IZM": "伊兹密尔",
    "DLM": "达拉曼",
    "SHJ": "沙迦",
    "SKD": "撒马尔罕",
    "DMM": "达曼",
    "CCU": "加尔各答",
    "LHE": "拉合尔",
    "KHI": "卡拉奇",
    "CMN": "卡萨布兰卡",
    "PPP": "普罗瑟派恩",
    "BOB": "博拉博拉"
})
for _c in ("GRU", "GIG", "KEF", "PSR",):
    INTL_CITY_NAME.pop(_c, None)
    INTL_TZ.pop(_c, None)
    INTL_REGION.pop(_c, None)
    INTL_CITY_NPY.pop(_c, None)
INTL_CITY_NAME.update({
    "BKK": "曼谷",
    "CJU": "济州岛",
    "HKG": "中国香港",
    "HKT": "普吉岛",
    "KBV": "甲米镇",
    "KHH": "中国高雄",
    "MFM": "中国澳门",
    "NGO": "名古屋",
    "OKA": "冲绳",
    "PPT": "帕皮堤",
    "RMQ": "中国台中",
    "SSH": "沙姆沙伊赫湾",
    "TPE": "中国台北",
    "TUN": "突尼斯市"
})
INTL_TZ.update({
    "TNN": "Asia/Taipei",
    "HUN": "Asia/Taipei",
    "NQZ": "Asia/Almaty",
    "FRU": "Asia/Bishkek",
    "BAK": "Asia/Baku",
    "DYU": "Asia/Dushanbe",
    "MSQ": "Europe/Minsk",
    "SCO": "Asia/Aqtau",
    "EVN": "Asia/Yerevan",
    "CIT": "Asia/Almaty",
    "ISB": "Asia/Karachi",
    "OSS": "Asia/Bishkek",
    "ASB": "Asia/Ashgabat",
    "KBL": "Asia/Kabul",
    "TWU": "Asia/Kuching",
    "JHB": "Asia/Kuala_Lumpur",
    "NHA": "Asia/Ho_Chi_Minh",
    "SUB": "Asia/Jakarta",
    "LBJ": "Asia/Kuala_Lumpur",
    "MPH": "Asia/Manila",
    "KTI": "Asia/Phnom_Penh",
    "SAI": "Asia/Phnom_Penh",
    "HKD": "Asia/Tokyo",
    "AKJ": "Asia/Tokyo",
    "AOJ": "Asia/Tokyo",
    "SDJ": "Asia/Tokyo",
    "MMY": "Asia/Tokyo",
    "HIJ": "Asia/Tokyo",
    "TAK": "Asia/Tokyo",
    "KMQ": "Asia/Tokyo",
    "KOJ": "Asia/Tokyo",
    "KMJ": "Asia/Tokyo",
    "FSZ": "Asia/Tokyo",
    "TOY": "Asia/Tokyo",
    "MMB": "Asia/Tokyo",
    "KUH": "Asia/Tokyo",
    "TAE": "Asia/Seoul",
    "KWJ": "Asia/Seoul",
    "YNY": "Asia/Seoul",
    "RSU": "Asia/Seoul",
    "USN": "Asia/Seoul",
    "HIN": "Asia/Seoul",
    "REK": "Atlantic/Reykjavik",
    "SAO": "America/Sao_Paulo",
    "RIO": "America/Sao_Paulo",
    "AYT": "Europe/Istanbul",
    "NAV": "Europe/Istanbul",
    "ASR": "Europe/Istanbul",
    "ANK": "Europe/Istanbul",
    "IZM": "Europe/Istanbul",
    "DLM": "Europe/Istanbul",
    "SHJ": "Asia/Dubai",
    "SKD": "Asia/Samarkand",
    "DMM": "Asia/Riyadh",
    "CCU": "Asia/Kolkata",
    "LHE": "Asia/Karachi",
    "KHI": "Asia/Karachi",
    "CMN": "Africa/Casablanca",
    "PPP": "Australia/Brisbane",
    "BOB": "Pacific/Tahiti"
})
INTL_CITY_NPY.update({
    "中国台南": "tainan",
    "中国花莲": "hualian",
    "阿斯塔纳": "asitanan",
    "比什凯克": "bishikeke",
    "巴库": "baku",
    "杜尚别": "dushangbie",
    "明斯克": "mingseke",
    "阿克套": "aketao",
    "埃里温": "ailiwen",
    "奇穆肯特": "qimukente",
    "伊斯兰堡": "yisilanbao",
    "奥什": "aoshi",
    "阿什哈巴德": "ashahabade",
    "喀布尔": "kabuer",
    "斗湖": "douhu",
    "新山": "xinshan",
    "芽庄": "yazhuang",
    "泗水": "sishui",
    "拉布安": "labuan",
    "卡提克兰": "katikelan",
    "金边": "jinbian",
    "暹粒": "xianli",
    "函馆": "hanguan",
    "旭川": "xuchuan",
    "青森市": "qingsenshi",
    "仙台": "xiantai",
    "宫古岛": "gonggudao",
    "广岛市": "guangdaoshi",
    "高松": "gaosong",
    "小松": "xiaosong",
    "鹿儿岛": "luerdao",
    "熊本市": "xiongbenshi",
    "静冈": "jinggang",
    "富山市": "fushanshi",
    "女满别": "nvmanbie",
    "钏路市": "chuanlushi",
    "大邱": "daqiu",
    "光州": "guangzhou",
    "襄阳": "xiangyang",
    "丽水": "lishui",
    "蔚山": "weishan",
    "晋州": "jinzhou",
    "雷克雅未克": "leikeiyawieke",
    "圣保罗": "shengbaoluo",
    "里约热内卢": "liyaoreneilu",
    "安塔利亚": "antaliya",
    "内夫谢希尔": "neifuxiexier",
    "开塞利": "kaisaili",
    "安卡拉": "ankala",
    "伊兹密尔": "yizimier",
    "达拉曼": "dalaman",
    "沙迦": "shajia",
    "撒马尔罕": "samaerhan",
    "达曼": "daman",
    "加尔各答": "jiaergeda",
    "拉合尔": "laheer",
    "卡拉奇": "kalaqi",
    "卡萨布兰卡": "kasabulanka",
    "普罗瑟派恩": "puluosipaien",
    "博拉博拉": "bolabola",
})
INTL_REGION.update({
    "TNN": "港澳台",
    "HUN": "港澳台",
    "ISB": "南亚",
    "DMM": "中东",
    "NQZ": "其他国际",
    "FRU": "其他国际",
    "BAK": "其他国际",
    "DYU": "其他国际",
    "SCO": "其他国际",
    "EVN": "其他国际",
    "CIT": "其他国际",
    "OSS": "其他国际",
    "ASB": "其他国际",
    "KBL": "其他国际",
    "SKD": "其他国际",
    "MSQ": "欧洲",
    "REK": "欧洲",
    "TWU": "东南亚",
    "JHB": "东南亚",
    "NHA": "东南亚",
    "SUB": "东南亚",
    "LBJ": "东南亚",
    "MPH": "东南亚",
    "KTI": "东南亚",
    "SAI": "东南亚",
    "HKD": "日韩",
    "AKJ": "日韩",
    "AOJ": "日韩",
    "SDJ": "日韩",
    "MMY": "日韩",
    "HIJ": "日韩",
    "TAK": "日韩",
    "KMQ": "日韩",
    "KOJ": "日韩",
    "KMJ": "日韩",
    "FSZ": "日韩",
    "TOY": "日韩",
    "MMB": "日韩",
    "KUH": "日韩",
    "TAE": "日韩",
    "KWJ": "日韩",
    "YNY": "日韩",
    "RSU": "日韩",
    "USN": "日韩",
    "HIN": "日韩",
    "SAO": "美洲",
    "RIO": "美洲",
    "AYT": "中东",
    "NAV": "中东",
    "ASR": "中东",
    "ANK": "中东",
    "IZM": "中东",
    "DLM": "中东",
    "SHJ": "中东",
    "CCU": "南亚",
    "LHE": "南亚",
    "KHI": "南亚",
    "CMN": "非洲",
    "PPP": "大洋洲",
    "BOB": "大洋洲"
})
INTL_CITY_PY.update({k: v[0].upper() for k, v in
                      {"TNN": "zhongguotainan", "HUN": "zhongguohualian",
                        "NQZ": "asitanan", "FRU": "bishikeke",
                        "BAK": "baku", "DYU": "dushangbie",
                        "MSQ": "mingseke", "SCO": "aketao",
                        "EVN": "ailiwen", "CIT": "qimukente",
                        "ISB": "yisilanbao", "OSS": "aoshi",
                        "ASB": "ashahabade", "KBL": "kabuer",
                        "TWU": "douhu", "JHB": "xinshan",
                        "NHA": "yazhuang", "SUB": "sishui",
                        "LBJ": "labuan", "MPH": "katikelan",
                        "KTI": "jinbian", "SAI": "xianli",
                        "HKD": "hanguan", "AKJ": "xuchuan",
                        "AOJ": "qingsenshi", "SDJ": "xiantai",
                        "MMY": "gonggudao", "HIJ": "guangdaoshi",
                        "TAK": "gaosong", "KMQ": "xiaosong",
                        "KOJ": "luerdao", "KMJ": "xiongbenshi",
                        "FSZ": "jinggang", "TOY": "fushanshi",
                        "MMB": "nvmanbie", "KUH": "chuanlushi",
                        "TAE": "daqiu", "KWJ": "guangzhou",
                        "YNY": "xiangyang", "RSU": "lishui",
                        "USN": "weishan", "HIN": "jinzhou",
                        "REK": "leikeiyawieke", "SAO": "shengbaoluo",
                        "RIO": "liyaoreneilu", "AYT": "antaliya",
                        "NAV": "neifuxiexier", "ASR": "kaisaili",
                        "ANK": "ankala", "IZM": "yizimier",
                        "DLM": "dalaman", "SHJ": "shajia",
                        "SKD": "samaerhan", "DMM": "daman",
                        "CCU": "jiaergeda", "LHE": "laheer",
                        "KHI": "kalaqi", "CMN": "kasabulanka",
                        "PPP": "puluosipaien", "BOB": "bolabola",
                        "SSH": "shamushaihewan", "CJU": "jizhoudao",
                        "HKT": "pujidao", "TUN": "tunissishi",
                        "PPT": "papidi", "BKK": "mangu",
                        "HKG": "zhongguoxianggang", "KHH": "zhongguogaoxiong",
                        "MFM": "zhongguoaomen", "RMQ": "zhongguotaizhong",
                        "TPE": "zhongguotaibei", "NGO": "mingguwu",
                        "OKA": "chongsheng", "KBV": "jiamizhen"
                      }.items()})


# R55c NPY 键名修正+全量补齐（r55b 块 NPY 键曾误用码；键=携程官方名）
INTL_CITY_NPY.update({
    "中国台中": "taizhong",
    "中国台北": "taibei",
    "伊斯兰堡": "yisilanbao", "达曼": "daman",
    "中国台南": "tainan",
    "中国澳门": "aomen",
    "中国花莲": "hualian",
    "中国香港": "xianggang",
    "中国高雄": "gaoxiong",
    "丽水": "lishui",
    "仙台": "xiantai",
    "伊兹密尔": "yizimier",
    "伊斯兰堡": "yisilanbao",
    "光州": "guangzhou",
    "内夫谢希尔": "neifuxiexier",
    "函馆": "hanguan",
    "加尔各答": "jiaergeda",
    "博拉博拉": "bolabola",
    "卡拉奇": "kalaqi",
    "卡提克兰": "katikelan",
    "卡萨布兰卡": "kasabulanka",
    "喀布尔": "kabuer",
    "圣保罗": "shengbaoluo",
    "埃里温": "ailiwen",
    "大邱": "daqiu",
    "奇穆肯特": "qimukente",
    "奥什": "aoshi",
    "女满别": "nvmanbie",
    "安卡拉": "ankala",
    "安塔利亚": "antaliya",
    "宫古岛": "gonggudao",
    "富山市": "fushanshi",
    "小松": "xiaosong",
    "巴库": "baku",
    "广岛市": "guangdaoshi",
    "开塞利": "kaisaili",
    "拉合尔": "laheer",
    "拉布安": "labuan",
    "撒马尔罕": "samaerhan",
    "斗湖": "douhu",
    "新山": "xinshan",
    "旭川": "xuchuan",
    "明斯克": "mingseke",
    "晋州": "jinzhou",
    "普罗瑟派恩": "puluosipaien",
    "暹粒": "xianli",
    "杜尚别": "dushangbie",
    "比什凯克": "bishikeke",
    "沙迦": "shajia",
    "泗水": "sishui",
    "熊本市": "xiongbenshi",
    "芽庄": "yazhuang",
    "蔚山": "weishan",
    "襄阳": "xiangyang",
    "达拉曼": "dalaman",
    "达曼": "daman",
    "里约热内卢": "liyaoreneilu",
    "金边": "jinbian",
    "钏路市": "chuanlushi",
    "阿什哈巴德": "ashahabade",
    "阿克套": "aketao",
    "阿斯塔纳": "asitanan",
    "雷克雅未克": "leikeiyawieke",
    "青森市": "qingsenshi",
    "静冈": "jinggang",
    "高松": "gaosong",
    "鹿儿岛": "luerdao"
})
INTL_CITY_PY.update({
    "中国台中": "T",
    "中国台北": "T",
    "中国台南": "T",
    "中国澳门": "A",
    "中国花莲": "H",
    "中国香港": "X",
    "中国高雄": "G",
    "丽水": "L",
    "仙台": "X",
    "伊兹密尔": "Y",
    "伊斯兰堡": "Y",
    "光州": "G",
    "内夫谢希尔": "N",
    "函馆": "H",
    "加尔各答": "J",
    "博拉博拉": "B",
    "卡拉奇": "K",
    "卡提克兰": "K",
    "卡萨布兰卡": "K",
    "喀布尔": "K",
    "圣保罗": "S",
    "埃里温": "A",
    "大邱": "D",
    "奇穆肯特": "Q",
    "奥什": "A",
    "女满别": "N",
    "安卡拉": "A",
    "安塔利亚": "A",
    "宫古岛": "G",
    "富山市": "F",
    "小松": "X",
    "巴库": "B",
    "广岛市": "G",
    "开塞利": "K",
    "拉合尔": "L",
    "拉布安": "L",
    "撒马尔罕": "S",
    "斗湖": "D",
    "新山": "X",
    "旭川": "X",
    "明斯克": "M",
    "晋州": "J",
    "普罗瑟派恩": "P",
    "暹粒": "X",
    "杜尚别": "D",
    "比什凯克": "B",
    "沙迦": "S",
    "泗水": "S",
    "熊本市": "X",
    "芽庄": "Y",
    "蔚山": "W",
    "襄阳": "X",
    "达拉曼": "D",
    "达曼": "D",
    "里约热内卢": "L",
    "金边": "J",
    "钏路市": "C",
    "阿什哈巴德": "A",
    "阿克套": "A",
    "阿斯塔纳": "A",
    "雷克雅未克": "L",
    "青森市": "Q",
    "静冈": "J",
    "高松": "G",
    "鹿儿岛": "L"
})

# R55c 补：官方 namePy 空缺三城手填（携程官方未下发拼音）
INTL_CITY_NPY.update({"沙姆沙伊赫湾": "shamushaihewan", "甲米镇": "jiamizhen",
                      "突尼斯市": "tunissishi"})
INTL_CITY_PY.update({"沙": "S", "甲": "J", "突": "T"})

# R55c 全量 PY 重建（不变式 PY[n]==NPY[n][0].upper() 由构造保证——
# 散点 update 曾留 TNN:Z 陈值，invariant 钉实锤）
INTL_CITY_PY.update({k: v[0].upper() for k, v in INTL_CITY_NPY.items()})
