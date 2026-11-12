# -*- coding: utf-8 -*-
"""r1063 T58：身份族三个参数**按渠道**求值（UA / 移动 UA / TLS 指纹）。

缺口：`crawlers/base.py::_ua()` 与各渠道的 `tls_impersonate` 只读 `self.config`
（该渠道 `crawler:` 段解析出来的**全局值**）——界面上给某家单独换 UA / 换 TLS
指纹，一律不生效。

修法：模块级 `crawlers.base.scoped_id(pid, plat, fallback)`，优先级与
`slider._pval`、`Pacing._scoped` 一致：**参数层有意见才采用**，否则用配置值。
"""
import io
import logging
import os

import pytest

from core import strategy_params as sp
from crawlers.base import BaseCrawler, DESKTOP_UA, MOBILE_UA, scoped_id

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


class _Probe(BaseCrawler):
    # 用**真实**渠道名：覆盖键的渠道段要过 core/channels.py 的校验
    name = "fliggy"

    def fetch(self, *a, **kw):          # pragma: no cover - 只为了实例化
        return []


def _mk(mobile=False, cfg=None):
    c = _Probe(dict(cfg or {}), logging.getLogger("t58"))
    c.use_mobile = mobile
    return c


def test_ua_follows_the_channel_override():
    sp.set_config({"crawler": {"user_agent": "GLOBAL-UA",
                               "strategy_overrides": {
                                   "fliggy": {
                                       "identity_headers.ua": "PROBE-UA"}}}})
    c = _mk()
    assert c._ua().startswith("PROBE-UA"), c._ua()


def test_other_channels_keep_the_global_ua():
    sp.set_config({"crawler": {"user_agent": "GLOBAL-UA",
                               "strategy_overrides": {
                                   "fliggy": {
                                       "identity_headers.ua": "PROBE-UA"}}}})
    other = _mk()
    other.name = "another_plat"
    assert other._ua().startswith("GLOBAL-UA"), other._ua()


def test_mobile_ua_is_scoped_too():
    sp.set_config({"crawler": {
        "mobile_user_agent": "",
        "strategy_overrides": {
            "fliggy": {"identity_headers.mobile_ua": "MOBILE-X"}}}})
    assert _mk(mobile=True)._ua().startswith("MOBILE-X")


def test_no_override_keeps_previous_behaviour():
    """没配过覆盖时行为**不变**（默认 UA 常量仍然说了算）。"""
    sp.set_config({})
    assert _mk()._ua() == DESKTOP_UA or _mk()._ua().startswith(
        DESKTOP_UA.split(" Chrome/")[0])
    assert _mk(mobile=True)._ua().startswith(
        MOBILE_UA.split(" Chrome/")[0])


def test_tls_impersonate_is_scoped():
    sp.set_config({"crawler": {
        "tls_impersonate": "chrome",
        "strategy_overrides": {"fliggy": {
            "identity_headers.tls": "safari"}}}})
    assert scoped_id("identity_headers.tls", "fliggy", "chrome") == "safari"
    assert scoped_id("identity_headers.tls", "ctrip", "chrome") == "chrome"


def test_scoped_id_never_raises():
    assert scoped_id("不存在.pid", "fliggy", "x") == "x"


def test_all_tls_read_points_go_through_scoped_id():
    """门禁：三个渠道的 `tls_impersonate` 读点必须包在 `scoped_id(...)` 里。"""
    bad = []
    for name in ("fliggy.py", "qunar.py", "tuniu.py"):
        src = io.open(os.path.join(ROOT, "crawlers", name),
                      encoding="utf-8").read()
        for i, line in enumerate(src.splitlines()):
            if "tls_impersonate" not in line:
                continue
            win = "\n".join(src.splitlines()[max(0, i - 3):i + 1])
            if "scoped_id(" not in win:
                bad.append("%s:%d %s" % (name, i + 1, line.strip()[:70]))
    assert not bad, "还有裸读的 tls_impersonate：\n" + "\n".join(bad)


def test_ua_read_point_goes_through_scoped_id():
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    assert 'scoped_id("identity_headers.mobile_ua"' in src
    assert 'scoped_id("identity_headers.ua"' in src
