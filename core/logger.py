"""日志配置"""
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(log_path: str, name: str = "ticket-monitor") -> logging.Logger:
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    logger = logging.getLogger(name)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    # apscheduler 警告接入同一文件（r326 挂死案：max_instances=1 触发层
    # 静默跳轮走专用 logger，未接入文件=排程层零痕迹纯静默）
    ap = logging.getLogger("apscheduler")
    if not ap.handlers:
        ap.setLevel(logging.WARNING)
        ap.addHandler(fh)
        ap.propagate = False
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger
