# -*- coding: utf-8 -*-
"""Pure specials-radar alert decisions.

No I/O: callers load the previous low / armed state and persist the result.
Only same-basis prices are compared; a channel or basis switch resets rather
than fabricating a drop.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RadarAlertCfg:
    enabled: bool = True
    drop_min: float = 50.0
    threshold: float = 0.0
    cooldown_h: float = 12.0
    rearm_ratio: float = 1.05


@dataclass(frozen=True)
class AlertDecision:
    action: str
    price: float
    prev_low: float | None = None
    kind: str = ""
    armed: int = 1


def _cooldown_ok(last_alert_at, now, hours):
    if not last_alert_at:
        return True
    try:
        last = datetime.fromisoformat(str(last_alert_at))
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= float(hours) * 3600


def evaluate(prev_low, prev_basis, price, basis, armed, last_alert_at,
             now, cfg):
    """Return the alert decision for one date.

    seed: first observation, no push.
    basis_reset: same date observed under a different price basis.
    threshold: crossed configured threshold while armed.
    new_low: dropped at least drop_min after cooldown.
    rearm: price recovered above threshold*rearm_ratio.
    none: no alert (including a drop smaller than drop_min or in cooldown).
    """
    if not cfg.enabled:
        return AlertDecision("none", price, prev_low, armed=armed)
    if prev_low is None:
        return AlertDecision("seed", price, None, armed=1)
    if str(prev_basis or "") != str(basis or ""):
        return AlertDecision("basis_reset", price, prev_low, armed=1)

    if cfg.threshold > 0 and int(armed) and price <= cfg.threshold:
        return AlertDecision("threshold", price, prev_low, "threshold", 0)

    if price >= prev_low:
        rearm = (cfg.threshold > 0 and not int(armed)
                 and price >= cfg.threshold * cfg.rearm_ratio)
        return AlertDecision("rearm" if rearm else "none", price, prev_low,
                             armed=1 if rearm else armed)

    if (prev_low - price >= cfg.drop_min
            and _cooldown_ok(last_alert_at, now, cfg.cooldown_h)):
        return AlertDecision("new_low", price, prev_low, "new_low", armed)
    return AlertDecision("none", price, prev_low, armed=armed)
