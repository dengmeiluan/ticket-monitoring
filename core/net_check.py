"""出口 IP 定性（r1063 T94）：换 IP 之前先确认"当前 IP 是不是问题"。

解封阶梯里"换出口 IP"是一档，但盲目换 IP 成本不低（代理/拨号/换线），
而阿里系与携程都按 **IP 段**聚类：机房 IP（阿里云/AWS 等）比家宽更容易被判风险。
所以先测一次，能测出结论就别乱动。

实测（2026-11-08，本机）::

    出口 IP : 58.246.127.206
    位置    : China Shanghai Shanghai
    运营商  : CNC Group CHINA169 Shanghai Province Network
    AS      : AS17621 China Unicom Shanghai network
    代理标记: False | 数据中心标记: False
    → 住宅/普通线路，IP 不是主要风险点

接口：`probe()` 返回 dict（永不抛）；`python -m core.net_check` 打印人读结论。
"""
from __future__ import annotations

import json

_TIMEOUT = 12.0
_URLS = (
    "http://ip-api.com/json/?fields=status,country,regionName,city,isp,org,"
    "as,mobile,proxy,hosting,query",
    "https://ipinfo.io/json",
)


def probe(timeout: float = _TIMEOUT) -> dict:
    """探测出口 IP 与风险标记。失败返回 {}（不抛）。"""
    try:
        import httpx
    except Exception:
        return {}
    out = {}
    for url in _URLS:
        try:
            r = httpx.get(url, timeout=timeout)
            if r.status_code != 200:
                continue
            d = r.json() or {}
        except Exception:
            continue
        if "query" in d:                       # ip-api 形态
            out = {"ip": d.get("query"), "country": d.get("country"),
                   "region": d.get("regionName"), "city": d.get("city"),
                   "isp": d.get("isp"), "as": d.get("as"),
                   "mobile": d.get("mobile"), "proxy": d.get("proxy"),
                   "hosting": d.get("hosting"), "source": "ip-api"}
        elif "ip" in d:                        # ipinfo 形态
            out = {"ip": d.get("ip"), "city": d.get("city"),
                   "org": d.get("org"), "country": d.get("country"),
                   "proxy": None, "hosting": None, "mobile": None,
                   "source": "ipinfo"}
        if out:
            break
    if not out:
        return {}
    out["verdict"], out["advice"] = verdict(out)
    return out


def verdict(info: dict) -> tuple:
    """(verdict, advice)：机读结论 + 一句人话建议。"""
    if not info:
        return ("unknown", "测不出出口 IP（网络可能不通）——别急着换 IP")
    if info.get("proxy") or info.get("hosting"):
        return ("datacenter",
                "该 IP 被标注为机房/代理：阿里系与携程会更严，值得换家宽 IP")
    if info.get("mobile"):
        return ("mobile", "蜂窝网络 IP：一般比机房宽松，通常不用换")
    return ("residential", "住宅/普通线路（未被标注机房或代理）—— IP 不是主要风险点")


def _main(argv=None):                          # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    info = probe()
    if "--json" in argv:
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0 if info else 1
    if not info:
        print("测不出出口 IP（网络不通或被墙）")
        return 1
    print("出口 IP :", info.get("ip"))
    print("位置    : %s %s %s" % (info.get("country"), info.get("region"),
                                  info.get("city")))
    print("运营商  :", info.get("isp") or info.get("org"))
    print("AS      :", info.get("as") or "-")
    print("代理标记:", info.get("proxy"), "| 数据中心:", info.get("hosting"),
          "| 蜂窝:", info.get("mobile"))
    print("判定    :", info["verdict"], "→", info["advice"])
    return 0


if __name__ == "__main__":                     # pragma: no cover
    raise SystemExit(_main())
