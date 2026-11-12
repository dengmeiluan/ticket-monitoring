# -*- coding: utf-8 -*-
"""r253 数据层两案（渠道调研报告 r253_recon_*.md 真候选收编）：

D-1【ctrip】经济舱公布运价 stdFare——pid zstd 载荷 items.L_Y_Price
（值形态「4350.0,产品后缀」取价格段），tprice=L_Y_Price×drate/10 在
43/43 行成立（26 行精确 1.0）=折扣锚定全价（报销/里程累积口径）。
tuniu stdFare（bcTaxExclusiveFare）同键同语义已接线（webui 白名单
「公布运价」CSV 列现成），ctrip 补齐后跨渠道对等。产品后缀词语义
未证不采（只取逗号前价格段）；镜像键 listFinalShowPrice 不另落；
仅直飞行落（中转组合行的「公布运价」语义未证，宁缺勿错同 baggage
「仅直飞」先例）；解码失败/依赖缺失/值域外静默。
【r254 撤采定谳】上段「跨渠道对等」承诺被观测双源 raw 对照推翻：
L_Y_Price 实为卖价镜像（172/172 行与 price 恒等）——撤采，见
TestCtripStdFare 类注释；webui 白名单/CSV 列保留（tuniu 源在用）。

D-2【qunar】中转各段承运航司中文名——H5 binfo.carrierSimpleName
（「南航|东航」，中转行 100% 在场），非共享中转行的二段承运方此前
读者不可见（shareCarrier 只在 codeShare 行、shareAirline PC-only
出勤 4%）。落 shareAirline 既有键（webui 白名单现成）+ 渲染门新增
非共享行独立「承运·」档（原门只拼 shareCarrier 行=孤儿键防线）。
H5 兜底路径专属源：PC 主路径无此键，复活期归零属断供非回归。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r253_fields.py -q
"""
import base64
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zstandard  # noqa: E402

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("t253")
_CT = CtripCrawler({}, _LOG)


def _mk_pid_payload(payload):
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    return "__Zstd__|" + base64.b64encode(blob).decode("ascii")


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _ctrip_item(pid, policies, transfer=False):
    segs = ([_ctrip_seg("2026-10-08 16:40:00", "2026-10-08 21:30:00")]
            if not transfer else
            [_ctrip_seg("2026-10-08 16:40:00", "2026-10-08 19:10:00",
                        "GS7529"),
             _ctrip_seg("2026-10-08 20:30:00", "2026-10-08 23:30:00",
                        "MU5700")])
    return {"pid": pid, "mutilstn": segs, "policyinfo": policies}


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows, "样本应产出至少一行"
    return rows[0]


_CI_Y = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}


def _pid_with_std(std="4350.0,BusinessPriority", **items_extra):
    payload = {"trlinfos": [
        {"policies": {"price": 2457, "grade": "Y",
                      "tag": ["freeLuggageAmount_20"]}}],
        "items": dict({"L_Y_Price": std}, **items_extra)}
    return _mk_pid_payload(payload)


class TestCtripStdFare:
    """r254 撤采定谳（观测双源 raw 对照）：L_Y_Price 实为卖价镜像
    （近 48h 172/172 行 stdFare==price 恒等，1.6 折深折行也不含全价），
    与 tuniu bcTaxExclusiveFare（税前公布价）跨渠道不对等——「公布运价
    列跨渠道对等」承诺失真，恒等镜像零信息增量撤采（词面配对判据），
    CSV「公布运价」列回归 tuniu 纯口径；存量行随 40 分钟滚动窗自然
    老化出列（extra 内 stdFare 在窗内仍显示，消费端空值不占位）。
    _pid_free_kgs 行李额同门消费不受牵连（回归钉保留）。"""

    def test_direct_row_no_stdfare(self):
        """直飞行撤采：L_Y_Price 卖价镜像不再落 stdFare。"""
        r = _ctrip_one(_ctrip_item(_pid_with_std(),
                                   [_ctrip_policy(ci=_CI_Y)]))
        assert "stdFare" not in r

    def test_transfer_row_not_landed(self):
        """中转组合行不落（维持原判）。"""
        r = _ctrip_one(_ctrip_item(_pid_with_std(),
                                   [_ctrip_policy(ci=_CI_Y)],
                                   transfer=True))
        assert "stdFare" not in r

    def test_free_kgs_regressor(self):
        """pid 解码单源重构不回归：行李额同门照常（_pid_free_kgs
        既有行为，trlinfos 与 items 双消费并存）。"""
        r = _ctrip_one(_ctrip_item(_pid_with_std(),
                                   [_ctrip_policy(ci=_CI_Y)]))
        assert r.get("baggage") == "免费托运20KG"


def _h5_trans(**top):
    """H5 中转行最小形态（r244 样板同构）。"""
    f = {
        "minPrice": 1200, "code": "3U1599/MU2161",
        "transTime": "25h40m",
        "binfo1": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05",
                   "carrierSimpleName": "南航｜东航"},
        "binfo2": {"arrTime": "18:20", "arrDate": "2026-10-05"},
        "extparams": "{}",
    }
    f.update(top)
    return f


def _h5_direct(**top):
    """H5 直飞行最小形态：单段 code、无 binfo2。"""
    f = {
        "minPrice": 900, "code": "CZ6981",
        "transTime": "4h30m",
        "binfo": {"depTime": "08:00", "arrTime": "12:30",
                  "depDate": "2026-10-05", "arrDate": "2026-10-05",
                  "carrierSimpleName": "南航"},
        "extparams": "{}",
    }
    f.update(top)
    return f


def _h5_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows, "样本应产出至少一行"
    return rows[0]


class TestQunarShareAirline:
    def test_trans_row_lands_normalized(self):
        """中转行落 shareAirline，全角分隔符归一半角。"""
        r = _h5_one(_h5_trans())
        assert r.get("shareAirline") == "南航|东航"

    def test_direct_row_not_landed(self):
        """直飞行不落（单段无「各段承运」语义；PC 出口同键=
        共享行专属，直飞非共享两侧皆无源）。"""
        r = _h5_one(_h5_direct())
        assert "shareAirline" not in r

    def test_null_garbage_not_landed(self):
        """「null」垃圾串不落（H5 mainCarrier 家族曾现字符串 null）。"""
        f = _h5_trans()
        f["binfo1"]["carrierSimpleName"] = "null"
        assert "shareAirline" not in _h5_one(f)

    def test_shared_row_not_landed(self):
        """共享行（codeShare 主源在场）不落——承运信息由 shareCarrier
        词面承载，防两键同屏语义混淆。"""
        f = _h5_trans(binfo1={"depTime": "08:00", "arrTime": "11:30",
                              "depDate": "2026-10-05",
                              "arrDate": "2026-10-05",
                              "carrierSimpleName": "南航｜东航",
                              "codeShare": True,
                              "mainCarrierSimpleNameAndNo": "川航3U1599"})
        r = _h5_one(f)
        assert r.get("shareCarrier") == "川航3U1599"
        assert "shareAirline" not in r
