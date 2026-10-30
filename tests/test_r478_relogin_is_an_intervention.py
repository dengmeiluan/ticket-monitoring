# -*- coding: utf-8 -*-
"""r478：网页重登必须入干预账，且能成为「干预成效」的分界。

缺口实测：`interventions` 只有 warmup/verify/probe/reset/auto_trip 五种
action，网页重登（点「弹窗登录」→「我已登录完成」）一条都不写。而重登
恰恰是对成功率影响最大的干预：去哪儿国际 H5 被登录墙拦 13/17 次、0 出数，
重登后恢复出数——这么一次关键操作，事后在溯源里查不到，节流面板的
「上次干预 44%→100%」也永远不会以重登为分界。

两条契约：
  1) 登录会话保存成功时写 action='relogin'，槽位进 scope（PC/H5 可分）；
  2) 该记录不被 `substr(action,1,5) <> 'auto_'` 误排除，能当分界；
  3) 前端动作名能显示成「重登」，不落成英文 action。
"""
import io
import os
import re
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_saved_login_writes_relogin_intervention():
    w = _w()
    i = w.index("_State.logger.info(\"[登录] %s 会话已保存（网页登录）\", key)")
    # 用下一个分支边界作终止符：固定字符窗口会被后续新增逻辑挤出
    # （r496 加了 30 秒去重后，1600 字符装不下 save_intervention）
    j = w.index('if key == "fliggy_h5":', i)
    seg = w[i:j]
    assert '"relogin"' in seg, "会话保存后未写重登干预账"
    assert "save_intervention(" in seg, "未调用入账接口"
    assert "scope=str(key)" in seg, "槽位未入 scope（PC/H5 无法区分）"
    # 必须真的走 PriceStorage（不是打印日志了事）
    assert "PriceStorage(_anchored(" in seg


def test_relogin_counts_as_manual_boundary_and_maps_to_chinese():
    """重登不属 auto_*，必须能当成效分界；两处溯源都要显示「重登」。"""
    st = io.open(os.path.join(ROOT, "core", "storage.py"),
                 encoding="utf-8", newline="").read()
    assert "substr(action,1,5) <> 'auto_'" in st
    assert not re.search(r"action\s*<>\s*'auto'", st)
    w = _w()
    assert "relogin:'重登'" in w, "干预成效未把 relogin 映射成中文动作名"
    # 两处干预记录渲染（展开溯源 + 行内溯源）都必须走中文映射，
    # 否则读者看到「relogin」对不上面板上的「上次重登」。
    assert w.count("relogin:'重登'") >= 2, "有一处溯源仍直出英文动作名"
    i = w.index("const _acn=({probe:'自检'")
    assert "esc(act)}}" not in w[i:i + 400].replace("title=\"'+esc(act)+'\"", ""), \
        "动作名仍在可见文本里直出英文"


def test_relogin_effect_flows_through_storage():
    """行为级：relogin 落库后，intervention_effect 以它为分界并给出前后对比。"""
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))
    with ps._conn() as c:
        for i in range(4):
            c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status) "
                "VALUES ('2026-10-29 06:0%d:00','fliggy','BKK','CAN',"
                "'2026-11-05','H5','login')" % i)
        for i in range(4):
            c.execute(
                "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
                "to_city,depart_date,entry_path,path_status) "
                "VALUES ('2026-10-29 07:0%d:00','fliggy','BKK','CAN',"
                "'2026-11-05','H5','ok')" % i)
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy_h5",
                         before="login_wall", note="网页登录保存会话",
                         at="2026-10-29 06:30:00")
    e = ps.intervention_effect("fliggy", 24)
    assert e.get("has") is True
    assert e.get("action") == "relogin", e
    assert e.get("before") == 0.0, e
    assert e.get("after") == 1.0, e
    from core.pacing import effect_verdict
    state, hint, sev = effect_verdict(e)
    assert state in ("improved", "recovered"), (state, hint)
    assert "100%" in hint, hint
