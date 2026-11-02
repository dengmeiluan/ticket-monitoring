# -*- coding: utf-8 -*-
"""r900 门禁：低价机票（low_fare）的两张表必须是同一个答案。

实测缺陷（2026-10-31）：同一件事在两处各写一份、结论相反——
- `CHANNEL_DIMENSIONS[p]["low_fare"]`（渠道能力矩阵）
- `SPECIAL_CAPABILITY[p]["sources"]`（特价雷达的真实发现源）

当时：携程/同程/途牛在矩阵里是 `""`（未验证），但雷达里
`_ctrip_deals` / `_tongcheng_deals` / `_tuniu_deals` 都是真能出数的源；
去哪儿矩阵写 `y`，雷达却写 `sources: []`（"lowFlight 缓采"）。
用户看到的"哪家支持低价机票"取决于翻到哪一页，属可区分性缺陷。

判据（两表互为镜像）：
- 雷达登记了发现源 ⇔ 矩阵必须是 `y`；
- 雷达没有源 ⇔ 矩阵必须是 `""`（未接入，如实留空，不许写 y）。
特例：智行 App 的「特价」页形态不同（按目的地、非按日期），
雷达如实登记为空源，矩阵也必须是 `""`。

负控：把矩阵任一家的 low_fare 改回 `""`（而雷达有源）→ 红。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channels import CHANNEL_DIMENSIONS  # noqa: E402
from core.specials import SPECIAL_CAPABILITY  # noqa: E402


def test_low_fare_matrix_matches_radar_sources():
    bad = []
    for plat, row in CHANNEL_DIMENSIONS.items():
        caps = SPECIAL_CAPABILITY.get(plat) or {}
        has_src = bool(caps.get("sources"))
        declared = (row or {}).get("low_fare", "")
        if has_src and declared != "y":
            bad.append((plat, "雷达有源但矩阵=%r" % declared))
        if (not has_src) and declared == "y":
            bad.append((plat, "雷达无源但矩阵=y（谎称可用）"))
    assert not bad, (
        "低价机票在两处给出相反答案（矩阵 vs 特价雷达发现源）：%s" % bad)


def test_every_radar_source_owner_is_a_registered_channel():
    """雷达登记的源所属渠道，必须都在能力矩阵里（否则界面上无落点）。"""
    unknown = sorted(set(SPECIAL_CAPABILITY) - set(CHANNEL_DIMENSIONS))
    assert not unknown, "特价雷达登记了矩阵里不存在的渠道：%s" % unknown


def test_no_channel_silently_claims_low_fare_without_evidence():
    """没源的渠道必须写明原因，不能只留一个空数组。"""
    for plat, caps in SPECIAL_CAPABILITY.items():
        if caps.get("sources"):
            continue
        assert (caps.get("note") or "").strip(), (
            "%s 没有低价源，但 note 为空——用户看不出「为什么没有」" % plat)
