# -*- coding: utf-8 -*-
"""航班明细归一化：跨天(+N天)与时长以 日期/时刻 为唯一事实源重算，格式统一。

渠道给的 totalDuration/crossDayDesc 各家口径不一：携程中转只给首段时长、
同程跨天无脑 +1天、时长格式 时/小时/纯数字 混排、跨天标记漏标。
而列表接口普遍带 depDate/arrDate 全日期——跨天 N = arrDate-depDate 精确可得，
时长 = N*1440 + 到达时刻 - 起飞时刻。渠道时长与重算差 >15 分钟视为不可信，
以重算为准（±15 分钟内保留渠道值，仅统一格式）。
"""
import re
from datetime import date as _date

# 注意：此映射与 ctrip 爬虫内置的 {0:经济,1:公务,2:头等} 是两套口径
# （ctrip 的 cgrd 从 0 起算，dump 实证）——若「统一」到此处会让 ctrip
# 全部舱位错位一档，勿合并（09-18 审计留痕）
_CABIN_LV = {1: "经济舱", 2: "公务舱", 3: "头等舱"}


def _hhmm(t):
    m = re.match(r"^(\d{1,2}):(\d{2})", (t or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    # 渠道 JSON 时刻野值宁缺勿错（v1.5.37）：小时 0-23/分钟 0-59 之外返回
    # None——调用方（cross_days/normalize）对 None 均按「缺时刻」跳过重算，
    # 不会把 None 写进时刻字段
    return (h, mi) if h <= 23 and mi <= 59 else None



# 廉航二字码：其中转基本需重新值机托运——机场「代转运」服务标签
# 不能代表两段直挂（用户实锤：春秋大概率不直挂），保守按不满足
AIRLINE_LCC = {"9C", "KN", "AQ", "GX", "DZ", "EU", "8L", "PN", "QW",
               "G5", "BK", "KY"}


def _is_lcc(name: str) -> bool:
    # 兼容「春秋9C8945」「9C8945」两种形态（中文前缀可有可无）
    m = re.search(r"([A-Z0-9]{2})\d{3,4}", str(name or ""))
    return bool(m and m.group(1) in AIRLINE_LCC)


# 常见航司二字码 → 中文名（纯代码航班名兜底；未覆盖航司保持原样）
AIRLINE_CN = {
    "MU": "东航", "CZ": "南航", "CA": "国航", "HU": "海航", "ZH": "深航",
    "FM": "上航", "MF": "厦航", "HO": "吉祥", "9C": "春秋", "GS": "天津",
    "SC": "山东", "3U": "川航", "8L": "祥鹏", "TV": "西藏", "UQ": "乌鲁木齐航空",
    "G5": "华夏", "KN": "联航", "PN": "西部", "DZ": "东海", "EU": "成都",
    "QW": "青岛", "BK": "奥凯", "GX": "北部湾", "AQ": "北部湾", "CX": "国泰",
    "GJ": "长龙", "KY": "瑞丽", "CN": "大新华", "PNX": "西部",
    # 以下二字码按全库反查实证补全（v1.5）：ctrip 曾有 1088 行/24h 裸码
    "Y8": "金鹏航空", "JD": "首都航空", "9H": "长安航空",
    "NS": "河北航空", "RY": "江西航空",
}


def _dur_min(s):
    """'26时55分'/'5小时45分钟'/'3h5m'/'11时5分'/纯分钟数字 → 分钟。"""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    m = re.match(r"^(\d+)\s*(?:小时|时|h)\s*(\d{1,2})?\s*(?:分钟|分|m|$)", s)
    if m:
        try:
            return int(m.group(1)) * 60 + int(m.group(2) or 0)
        except ValueError:
            return None
    m = re.match(r"^(\d+)分$", s)
    return int(m.group(1)) if m else None


def fmt_dur(mins):
    """统一 'X时YY分'。"""
    if mins is None or mins < 0:
        return ""
    try:
        mins = int(mins)
    except (TypeError, ValueError):
        return ""
    return f"{mins // 60}时{mins % 60:02d}分"


def dur_min(s):
    """公开别名：时长文本 → 分钟数。"""
    return _dur_min(s)


def cross_days(f, depart_date=""):
    """跨天天数 N（0-3）：优先 arrDate-depDate，其次 crossDayDesc，
    最后用时长对表推导（dep+dur 与 arr+N*1440 差 ≤10 分钟的 N）。"""
    dd = (f.get("depDate") or depart_date or "")[:10]
    ad = (f.get("arrDate") or "")[:10]
    if dd and ad:
        try:
            n = (_date.fromisoformat(ad) - _date.fromisoformat(dd)).days
            if 0 <= n <= 3:
                return n
        except ValueError:
            pass
    desc = f.get("crossDayDesc") or ""
    m = re.search(r"\+?(\d+)天", desc)
    if m:
        return min(3, max(0, int(m.group(1))))
    if "次日" in desc:
        return 1
    dm = _dur_min(f.get("totalDuration"))
    dep, arr = _hhmm(f.get("depTime")), _hhmm(f.get("arrTime"))
    if dm and dep and arr:
        for cand in range(0, 4):
            if abs(dep[0] * 60 + dep[1] + dm
                   - (arr[0] * 60 + arr[1] + cand * 1440)) <= 10:
                return cand
    return 0


# 中转城市机场三字码 → 中文城市（渠道偶发吐机场码而非城市名，
# 实测 XFN=西安咸阳；未收录的原样保留——宁缺勿错）
AIRPORT_CN = {
    "XFN": "西安", "XIY": "西安", "CKG": "重庆", "KWL": "桂林",
    "KHN": "南昌", "WUH": "武汉", "CSX": "长沙", "HGH": "杭州",
    "NKG": "南京", "TNA": "济南", "TAO": "青岛", "TSN": "天津",
    "HET": "呼和浩特", "LHW": "兰州", "URC": "乌鲁木齐", "KRL": "库尔勒",
    "KHG": "喀什", "AKU": "阿克苏", "YIN": "伊宁", "HMI": "哈密",
}


def normalize(f, depart_date=""):
    """就地归一化一条航班明细 dict：crossDayN/crossDayDesc/totalDuration/durM。"""
    if not isinstance(f, dict):
        return f
    tc = str(f.get("transCity") or "")
    if tc in AIRPORT_CN:
        f["transCity"] = AIRPORT_CN[tc]
    # 经停城市（qunar PC stopCitys="西安"，分号分隔取首个）：经停徽标
    # 与比价行「经停西安」的数据源——此前只有「经停」二字无地点
    sc = str(f.get("stopCitys") or "").split(";")[0].strip()
    if sc:
        f["stopCity"] = sc
    # 经停停留时长（qunar PC stopTime="1小时5分"/"45分"）→ 时刻式
    # 「H:MM」，与 layoverT 同语言（「停1:05」根治「1时」误读 26 时）；
    # raw 44/47 为空——空值留空不作假
    st = str(f.get("stopTime") or "").strip()
    if st and not f.get("stopTimeT"):
        m = re.fullmatch(r"\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分)?\s*", st)
        if m and (m.group(1) or m.group(2)):
            f["stopTimeT"] = (f"{int(m.group(1) or 0)}:"
                              f"{int(m.group(2) or 0):02d}")
    # 航班名规范化（无前置依赖，缺起降时刻的行同样生效）：
    # 渠道常吐纯代码（"UQ2600"），补中文航司前缀——同航线命名口径统一
    name = str(f.get("name") or "")
    m = re.fullmatch(r"([A-Z0-9]{2})(\d{3,4})", name)
    if m and m.group(1) in AIRLINE_CN:
        f["name"] = AIRLINE_CN[m.group(1)] + name
    elif "/" in name:
        # 中转共享段斜杠双名（"MU5533/SC8711"）：两段各自补前缀
        parts = name.split("/")
        fixed = []
        for p in parts:
            pm = re.fullmatch(r"([A-Z0-9]{2})(\d{3,4})", p.strip())
            if pm and pm.group(1) in AIRLINE_CN and not pm.group(2).startswith("0"):
                fixed.append(AIRLINE_CN[pm.group(1)] + p.strip())
            else:
                fixed.append(p.strip())
        f["name"] = "/".join(fixed)
    # 时刻补零（无前置依赖）：渠道 6:30 → 06:30
    for _tk in ("depTime", "arrTime"):
        _m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(f.get(_tk) or ""))
        if _m:
            f[_tk] = f"{int(_m.group(1)):02d}:{_m.group(2)}"
    # 时长规范化（无前置依赖）："29h55m"/"7时" 等 → "X时YY分"
    _dur_raw = str(f.get("totalDuration") or "").strip()
    _dur_min_val = _dur_min(_dur_raw)
    if _dur_raw and _dur_min_val is not None:
        f["totalDuration"] = fmt_dur(_dur_min_val)
    # 经停信号（无前置依赖）：qunar DOM 的「停」= 同机号中途落地不换机——
    # 全程常比真直飞长 2h+（实测 CZ6976 7时 vs 直飞 4时50分），必须随行透传；
    # PC 接口 stopCitys 在场同为经停（stopCity 已取首城）；qunar H5 无
    # stopCitys 但 extparams.stopFlight=true 实测 6/6 全为经停行（交叉验证：
    # CZ6976/GS7588/9C8845 与 DOM「停」行一致）
    f["stopover"] = ((f.get("_via") == "停") or bool(sc)
                     or bool(f.get("stopFlight")))
    dep, arr = _hhmm(f.get("depTime")), _hhmm(f.get("arrTime"))
    if not (dep and arr):
        f.setdefault("crossDayN", 0)
        f.setdefault("layoverT", "")
        return f
    n = cross_days(f, depart_date)
    dur_ch = _dur_min(f.get("totalDuration"))
    computed = n * 1440 + arr[0] * 60 + arr[1] - (dep[0] * 60 + dep[1])
    if computed > 0 and (dur_ch is None or abs(dur_ch - computed) > 15):
        dur_ch = computed          # 渠道时长不可信（错值/缺值）→ 重算
    f["totalDuration"] = fmt_dur(dur_ch)
    f["durM"] = dur_ch
    f["crossDayN"] = n
    f["crossDayDesc"] = f"+{n}天" if n > 0 else ""
    lay = f.get("layover")
    # 不可能值守卫：衔接 ≥ 全程必为渠道分段计算错值（实测 qunar H5 的
    # %1440 回绕曾产「停15时20分 > 全程8时40分」）——作废归零。
    # 另一类擦边毒值：停留无限逼近全程（9C8846 全程7h55 停7:55，两段
    # 飞行剩 0 分钟）——国内中转两段合计飞行 < 60 分钟不存在，同作废
    if isinstance(lay, int) and lay > 0 and dur_ch and (
            lay >= dur_ch or dur_ch - lay < 60):
        lay = 0
    # 假衔接判伪守卫（qunar H5 实测 26/26 假行命中、0 例外）：binfo2
    # 缺独立时刻时 lay=(dep−arr)%1440 与全程时长完美反相关——lay+dur
    # 恰为 1440 整数倍（span=1→1440，span=2→2880），真实停留+全程落进
    # 1440 倍数 ±15 分钟的离散概率可忽略。全程 ≤12.5h 不判（守卫从宽，
    # 直飞短时长无此毒值形态），命中即回绕垃圾 → 弃值宁缺勿错。
    # 豁免：layoverSrc=transInfo 是渠道结构化真值（四段时刻+transTime），
    # 真值跨天长停留恰会落入击杀区（dump 实测 3/150 误杀）——启发式
    # 只服务猜衔接值，不判真值（物理守卫仍生效）
    if isinstance(lay, int) and lay > 0 and dur_ch and dur_ch > 720 \
            and f.get("layoverSrc") != "transInfo":
        rem = (lay + dur_ch) % 1440
        if rem <= 15 or rem >= 1425:
            lay = 0
    # 衔接用时刻式「H:MM」而非「H时MM分」：小字号灰字下「2时」曾被
    # 误读成「26时」（用户实锤「时好时坏」），与出发/到达列同语言后根治
    f["layoverT"] = (f"{lay // 60}:{lay % 60:02d}"
                     if isinstance(lay, int) and lay > 0 else "")
    f["layoverM"] = lay if isinstance(lay, int) and lay > 0 else 0
    f.setdefault("transferBaggage", "")  # 中转行李直挂信号（爬虫层解析，缺省未知）
    if not f["transferBaggage"]:
        sv = (f.get("transitServiceLabel") or "") + (f.get("transitServiceLabelName") or "")
        if ("行李免提" in sv or "免费托运" in sv) and not _is_lcc(f.get("name", "")):
            f["transferBaggage"] = "direct"   # 规范层兜底：demo/未接爬虫的渠道同样生效
    return f


def cabin_text(f):
    """舱位描述拼装：舱位名/舱位代码 · 折扣 · 机型 · 行李额（缺失项自动跳过）。"""
    parts = []
    if f.get("cabinName"):
        parts.append(str(f["cabinName"]))
    elif f.get("cabin"):
        c = str(f["cabin"]).strip()
        parts.append((c + "舱") if len(c) <= 2 else c)
    if f.get("discount"):
        parts.append(str(f["discount"]))
    if f.get("plane"):
        parts.append(str(f["plane"]))
    if f.get("baggage"):
        parts.append(str(f["baggage"]))
    return " · ".join(parts)
