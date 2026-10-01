"""数据模型"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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


# 价格带单源：取数链五处（爬虫接受带/曲线 _rounds/日报池/
# 各渠道最低/查现价选台）曾三套并存（100–50000 / 300–50000 / 0<p≤50000
# 无下界），「图上的最低」可系统性高于「列表的最低」——统一对齐爬虫端
# 100–50000（<100 的真实国内航价几乎不存在，且生产行本就先过爬虫带）。
# 勿单侧改值：跨端同带是「曲线与列表含义一致」的底线约束
PRICE_MIN = 100
PRICE_MAX = 50000
