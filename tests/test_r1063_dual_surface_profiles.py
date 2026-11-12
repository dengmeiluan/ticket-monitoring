# -*- coding: utf-8 -*-
"""r1063 T143/T144：所有渠道统一 PC + H5 双端登录，且**各端独立 profile**。

背景（用户要求）："统一设计跟飞猪一样，所有渠道登录要求 PC 和 H5 双端登录，
避免歧义"。

原来的歧义：`slot_crawler` 对 PC 与 H5 槽位返回同一个类、同一个 profile
（`profile_name or name`），于是 `user_data/tuniu` 一份 cookie 顶着两个标签，
登一边覆盖另一边。

现在：
1. 每个槽位一个 profile（`tuniu` / `tuniu_h5` …），`--login` 里多一列 `profile`；
2. 首次切换时把厂商 PC profile 的会话**继承**到 H5 profile（不丢已登录状态）；
3. 采集时 H5 通路用 `using_surface("h5")` 主动切到 H5 profile；
4. `web.login_split_profiles: false` 可退回旧的"一份 profile"行为。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.login_slots import LOGIN_SLOTS, slot_profile  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_vendor_has_pc_and_h5():
    vendors = {"ctrip", "fliggy", "tongcheng", "tuniu"}
    for v in vendors:
        assert v in LOGIN_SLOTS, "%s 缺 PC 槽位" % v
        assert "%s_h5" % v in LOGIN_SLOTS, "%s 缺 H5 槽位（双端登录）" % v


def test_slot_profiles_are_distinct():
    assert slot_profile("tuniu") == "tuniu"
    assert slot_profile("tuniu_h5") == "tuniu_h5"
    assert slot_profile("ctrip_h5") == "ctrip_h5"
    # 同一厂商两端必须不同 profile，否则又是"一份 cookie 两个标签"
    for v in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        assert slot_profile(v) != slot_profile("%s_h5" % v)


def test_slot_crawler_uses_h5_profile_and_optin_inherit(tmp_path, monkeypatch):
    """r1063 T178：**继承改成配置开关，默认关**。

    为什么关：继承来的只是 PC 域 cookie，H5 域并未登录，却让槽位显示
    「会话有效·明细可用」——假可用，且与"两端要分别登录"直接矛盾。
    """
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "tuniu"
    d.mkdir(parents=True, exist_ok=True)
    (d / "session-state.json").write_text(json.dumps({"cookies": []}),
                                         encoding="utf-8")

    from core.login_slots import slot_crawler
    import logging
    cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    c = slot_crawler("tuniu_h5", cfg, logging.getLogger("t"))
    assert os.path.basename(c.user_data_dir) == "tuniu_h5"
    # 默认**不继承**：H5 端要自己登，否则就是"假可用"
    assert not (tmp_path / "tuniu_h5" / "session-state.json").is_file()
    # 显式打开开关才继承（给"我就想复用 PC 会话"的人留口子）
    c2 = slot_crawler("tuniu_h5",
                      dict(cfg, web={"login_inherit_pc_session": True}),
                      logging.getLogger("t"))
    assert os.path.basename(c2.user_data_dir) == "tuniu_h5"
    assert (tmp_path / "tuniu_h5" / "session-state.json").is_file()


def test_split_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core.login_slots import slot_crawler
    import logging
    c = slot_crawler("tuniu_h5",
                     {"crawler": {"user_data_dir": str(tmp_path)},
                      "web": {"login_split_profiles": False}},
                     logging.getLogger("t"))
    assert (c.profile_name or "") in ("", "tuniu"), \
        "关闭开关后应退回共享 profile"


def test_using_surface_switches_and_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    (tmp_path / "tuniu_h5").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tuniu_h5" / "session-state.json").write_text("{}",
                                                             encoding="utf-8")
    from crawlers import REGISTRY
    import logging
    c = REGISTRY["tuniu"]({"crawler": {"user_data_dir": str(tmp_path)}},
                          logging.getLogger("t"))
    before = c.session_state_path
    with c.using_surface("h5"):
        inside = c.session_state_path
    after = c.session_state_path
    assert "tuniu_h5" in inside and "tuniu_h5" not in before
    assert after == before, "退出上下文必须恢复原 profile"


def test_using_surface_without_h5_session_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from crawlers import REGISTRY
    import logging
    c = REGISTRY["tuniu"]({"crawler": {"user_data_dir": str(tmp_path)}},
                          logging.getLogger("t"))
    before = c.session_state_path
    with c.using_surface("h5"):
        assert c.session_state_path == before


def test_tuniu_intl_uses_h5_surface():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("def _fetch_intl(")
    seg = src[i:i + 2500]
    assert 'using_surface("h5")' in seg, "途牛国际（H5 面）必须用 H5 槽位会话"
