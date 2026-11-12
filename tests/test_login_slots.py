# -*- coding: utf-8 -*-
"""Six login slots: five channels, with Fliggy PC and Taobao H5 split."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_six_slots_include_fliggy_pc_and_taobao_h5():
    """槽位表：**双端固定登录**（r1063 T82 统一设计）。

    用户要求："途牛和同程的弹窗登录现在默认全部到 H5 页面了，原来不是 PC 吗，
    要不然就跟飞猪一样，做双端固定登录，携程也是，统一设计算了"。
    于是每家浏览器渠道都有 PC/H5 两格（profile 也按端分开：域不同、cookie 不共享），
    去哪儿网页版正式停服，保留一格只做说明。
    """
    from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER
    assert LOGIN_SLOT_ORDER == (
        "ctrip", "ctrip_h5", "fliggy", "fliggy_h5", "tongcheng",
        "tongcheng_h5", "tuniu", "tuniu_h5", "qunar", "qunar_h5")
    assert set(LOGIN_SLOTS) == set(LOGIN_SLOT_ORDER)
    pc = LOGIN_SLOTS["fliggy"]
    h5 = LOGIN_SLOTS["fliggy_h5"]
    assert pc["profile"] == "fliggy"
    assert h5["profile"] == "fliggy_h5"
    assert pc["surface"] == "pc" and h5["surface"] == "h5"
    assert "fliggy.com" in pc["login_url"]
    assert "market.m.taobao.com" in h5["login_url"]
    assert h5["mobile"] is True and h5["login_mobile"] is True
    assert "淘宝" in h5["account"]
    assert "飞猪" in pc["account"]
    for key in ("ctrip", "qunar", "tongcheng", "tuniu"):
        assert LOGIN_SLOTS[key]["profile"] == key
        assert LOGIN_SLOTS[key]["login_url"].startswith("https://")


def test_fliggy_h5_login_uses_its_own_profile_and_mobile_window(tmp_path):
    from crawlers.fliggy import FliggyH5Login
    c = FliggyH5Login({"user_data_dir": str(tmp_path)},
                      logging.getLogger("slot-test"))
    assert c.name == "fliggy_h5"
    assert c.use_mobile is True
    assert c.login_mobile is True
    assert "market.m.taobao.com" in c.login_url()
    assert os.path.basename(c.user_data_dir) == "fliggy_h5"


def test_slot_crawler_resolves_fliggy_h5_separately(tmp_path):
    from core.login_slots import slot_crawler
    from crawlers.fliggy import FliggyH5Login
    cfg = {"user_data_dir": str(tmp_path)}
    log = logging.getLogger("slot-test")
    h5 = slot_crawler("fliggy_h5", cfg, log)
    pc = slot_crawler("fliggy", cfg, log)
    assert isinstance(h5, FliggyH5Login)
    assert pc.__class__.__name__ == "FliggyCrawler"
    assert os.path.basename(h5.user_data_dir) == "fliggy_h5"
    assert os.path.basename(pc.user_data_dir) == "fliggy"


def test_login_api_and_ui_are_slot_aware():
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    for needle in ("fliggy_h5", "data-slot", "淘宝登录", "slot_crawler"):
        assert needle in src, needle
    assert "body.get(\"slot\"" in src or "body.get('slot'" in src
    assert "loginStart('${p}',this)" not in src
