"""数据模型"""
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def render_dir() -> str:
    """图表渲染 PNG 的落盘目录。测试/自检经 TM_RENDER_DIR 重定向出
    仓库（与 PUSH_HISTORY_FILE 同律：显式重定向永远放行，默认行为
    不变）——渲染写点硬编码相对路径曾把测试图表落进生产 data/。"""
    return os.environ.get("TM_RENDER_DIR") or "data"


# 「只出价、不证明细」的日历族通路名。同程国际 r384 由「日历」换成
# 「窗历」——同一条业务通路的新入口名。任何按入口名做账的地方（路径
# 统计的族抑制、复发账的恢复判定）都必须按族看，否则换名当刻旧账就
# 永远配不上新成功。判据是通路语义（有无航班号/时刻），不是渠道。
CAL_PATH_FAMILY = ("日历", "窗历")


@dataclass
class FlightPrice:
    platform: str           # ctrip / fliggy / tongcheng / qunar
    from_city: str          # 出发地（三字码）
    to_city: str            # 目的地（三字码）
    depart_date: str        # YYYY-MM-DD
    price: float            # 最低价（含税或裸价，视平台展示）
    airline: str = ""       # 航司
    flight_no: str = ""     # 航班号
    depart_time: str = ""   # HH:MM
    arrive_time: str = ""   # HH:MM
    fetched_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    extra: str = ""         # 备用字段（JSON 字符串等）
    prov: str = ""          # 入口/路径级证据 JSON；空=未记录


@dataclass
class Route:
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    dates: list
    alert_threshold: float = 0
    alert_direct: float = 0        # 直飞阈值（0 不启用）
    alert_transfer: float = 0      # 中转阈值（0 不启用，须满足到达时间约束）
    transfer_arrival_max: str = "02:00"  # 中转最晚到达（次日该时刻前）
    transfer_layover_min: int = 0  # 中转最短衔接分钟（0=不限；需托运建议 ≥90）
    transfer_baggage: str = ""     # "direct"=仅认渠道标明行李直挂的班次（""=不限）
    dep_time_min: str = ""         # 出发时段下限 HH:MM（空=不限）
    dep_time_max: str = ""         # 出发时段上限 HH:MM（空=不限）
    ret_date: str = ""             # 往返回程日期（INTL_DESIGN §2.6；空=单程；legacy 单值键，读取兼容）
    ret_dates: list = field(default_factory=list)  # 往返多返程日（AiLao 提案：可配多个不同返程日；空=单程；build_routes 从 ret_dates/ret_date 归一）
    airlines: str = ""             # 航司白名单（逗号分隔 IATA 码或名称片段；空=不限）；`!` 前缀=排除项（如 `!9C,!春秋` 命中即剔，与白名单独立判定：先排除后白名单）
    no_lcc: bool = False           # 排除廉航（True=标注廉航的班次不参达标/明细）
    min_baggage: int = 0           # 免费托运下限 kg（0=不限；未标注 kg 的行按不满足）
    widebody_only: bool = False    # 仅大型机（未标注机型的行不剔除，防渠道覆盖差整渠道误杀）
    price_max: float = 0           # 价格上限 ¥（0=不限；只盯 ≤ 此价的班次；票价不可解析的行保留——票价是行主体，缺席剔除会整渠道误杀）
    no_cross: bool = False         # 排除跨天（crossDayN>0 的班次不参达标/明细，红眼嫌弃用）
    arr_time_min: str = ""         # 到达时段下限 HH:MM（空=不限；与出发窗同构，红眼落地嫌弃用）
    arr_time_max: str = ""         # 到达时段上限 HH:MM（空=不限）
    max_duration_h: float = 0      # 最长飞行总时长小时（0=不限；含中转全程；超限班次不参达标/明细；渠道未标注时长的行按不满足）
    transfer_layover_max: int = 0  # 中转最长衔接分钟（0=不限；已知衔接超限即剔，未知放行）
    exclude_stop: bool = False     # 排除经停（f["stop"] 明确标注经停的班次不参达标/明细）
    exclude_share: bool = False    # 排除共享航班（渠道标注共享承运的班次不参达标/明细）


# 价格带单源：取数链五处（爬虫接受带/曲线 _rounds/日报池/
# 各渠道最低/查现价选台）曾三套并存（100–50000 / 300–50000 / 0<p≤50000
# 无下界），「图上的最低」可系统性高于「列表的最低」——统一对齐爬虫端
# 100–50000（<100 的真实国内航价几乎不存在，且生产行本就先过爬虫带）。
# 勿单侧改值：跨端同带是「曲线与列表含义一致」的底线约束。
# 国际档（r325，INTL_DESIGN §1.3）：长途经济舱全档+高档舱低价窗越
# 国内带上界，国际航线（任一端国际，core.intl 自动判定）上界放宽到
# 200000——带过滤只挡垃圾价不挡真实国际票价；共享消费端（report/
# webui/alerter/main 的带过滤）一律走 price_band_ok 单源，勿再裸写
# PRICE_MIN–PRICE_MAX（国际行会被窄带静默丢行）。
PRICE_MIN = 100
PRICE_MAX = 50000
PRICE_INTL_MAX = 200000


def price_max_for(from_code: str = "", to_code: str = "",
                  el: dict = None) -> int:
    """航线上界单源：国际航线 200000，国内 50000。
    元素旗标优先（明细 dict 自带 intl 键即国际行——共享消费端手上
    只有元素没有路由上下文时也能判对），路由码兜底。"""
    if (el and el.get("intl")) or _intl_route(from_code, to_code):
        return PRICE_INTL_MAX
    return PRICE_MAX


def price_band_ok(v, from_code: str = "", to_code: str = "",
                  el: dict = None) -> bool:
    """价格带判定单源（scope-aware）：非法值 False，其余按航线档。"""
    try:
        p = float(v)
    except (TypeError, ValueError):
        return False
    return PRICE_MIN <= p <= price_max_for(from_code, to_code, el)


def _intl_route(from_code: str, to_code: str) -> bool:
    # 延迟导入：intl 依赖 citydata 大字典，models 是最底层模块，
    # 保持无重依赖链（intl 不反依赖 models）
    from .intl import is_intl_route
    return is_intl_route(from_code, to_code)
