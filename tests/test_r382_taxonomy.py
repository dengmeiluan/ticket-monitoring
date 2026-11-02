# -*- coding: utf-8 -*-
"""r382: 异常分类正确性（taxonomy）。

真实 24h 数据暴露两处归因错误，都会让"会话没养熟"被当成"请重登"：
  - 同程 49 次 HTTP 444 / code=444 被记 login 并置 login_suspect；
  - 去哪儿"原站明确无符合条件航班"被粘滞 login_suspect 覆盖成 login。
后果是 15 分钟登录冷却 + 误导用户重登，而真正该做的是下一轮预热。

判定口径：
  login_required  → 站点明确要求登录（710114/needLogin/登录页）
  soft_reject     → 会话/边缘层门拒（444/202 空体），预热可解
  empty           → 站点明确"无符合条件的航班"（真无票）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import Pacing, classify_failure, advise  # noqa: E402


def test_444_is_soft_not_login():
    """444 不得再归为"需登录"，也不得冷却渠道。"""
    assert classify_failure(["soft_reject"], "国际日历 HTTP 444") == "soft"
    p = Pacing({})
    kind, cd = p.observe("tongcheng", ["soft_reject"],
                         "国际日历会话门拒 code=444")
    assert kind == "soft" and cd == 0
    ch = p.snapshot()["channels"]["tongcheng"]
    assert ch["state"] == "ok" and ch["strikes"] == 0
    assert ch["needs_warmup"] is True
    assert ch["needs_login"] is False
    a = advise("tongcheng", ch, {})
    assert a["state"] == "soft_reject"
    assert a["action"] == "probe"        # 让用户自检/预热，而不是重登


def test_real_login_still_login():
    """真登录墙（710114/needLogin）必须仍然是 login。"""
    assert classify_failure(["login"], "登录号（710114/needLogin）") == "login"
    p = Pacing({})
    kind, cd = p.observe("tuniu", ["login"], "710114")
    assert kind == "login" and cd > 0
    ch = p.snapshot()["channels"]["tuniu"]
    assert ch["needs_login"] is True
    assert advise("tuniu", ch, {})["action"] == "relogin"


def test_soft_precedes_ip_when_note_has_444():
    """软拒常带 444 字样，不能被 IP 规则先吃掉（否则整家冷却）。"""
    assert classify_failure([], "HTTP 444 关连接") == "soft"
    p = Pacing({})
    kind, cd = p.observe("tongcheng", [], "HTTP 444 关连接")
    assert kind == "soft" and cd == 0
    assert p.snapshot()["channels"]["tongcheng"]["strikes"] == 0


def test_true_empty_is_not_login():
    assert classify_failure(["empty"], "原站明确返回无符合条件的航班") == ""


def test_qunar_no_result_does_not_inherit_login_suspect():
    """源码契约：no_result 必须先于 login_suspect 判定。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", "qunar.py"),
              encoding="utf-8") as f:
        src = f.read()
    i = src.find('_h5_status = ("ok" if got else')
    assert i > 0
    block = src[i:i + 420]
    assert '"empty" if _nores' in block, block
    j = src.find('_api_status = ("ok" if got else')
    assert j > 0
    assert '"empty" if _nores' in src[j:j + 420]


def test_tongcheng_444_does_not_set_login_suspect():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", "tongcheng.py"),
              encoding="utf-8") as f:
        src = f.read()
    # 找到 code=444 分支，确认不再 login_suspect / 不再写 login
    i = src.find('if _code == "444" or "非法链接"')
    assert i > 0
    block = src[i:i + 700]
    # 只断言"没有赋值/置位"，注释里出现该词是允许的
    assert "login_suspect = True" not in block, block
    assert "type(self).login_suspect" not in block, block
    assert '"soft_reject"' in block, block
    # HTTP 444 两处也必须是 soft_reject
    assert src.count('"soft_reject" if _hs == 444') == 1
    assert src.count('"soft_reject" if ar.status == 444') == 1


def test_failure_kind_vocabulary_is_stable():
    from core.pacing import failure_kind
    assert failure_kind("soft")[0] == "会话层软拒"
    assert failure_kind("soft")[2] is True          # 自动自愈
    assert failure_kind("login")[0] == "登录态失效"
    assert failure_kind("login")[2] is False        # 需人工
    assert failure_kind("ip")[2] is False
    unknown = failure_kind("something_new")
    assert unknown[0] == "未分类"


def test_recurrence_flags_soft_as_autoheal(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(4):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2027-06-01",
                           "日历", "soft_reject", attempt_id="a%d" % i)
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01",
                           "H5", "login", attempt_id="b%d" % i)
    rows = {r["platform"]: r for r in st.failure_recurrence(24, 3)}
    assert rows["tongcheng"]["kind"] == "soft"
    assert rows["qunar"]["kind"] == "login"


def test_panel_shows_recurrence_with_action_flag():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "反复出现" in src
    assert "autoHeal" in src and "需人工" in src and "自动" in src
    assert "failure_kind" in src


def test_legacy_444_login_rows_are_relabelled_as_soft(tmp_path):
    """历史行曾把 444 记成 login；复发账必须按证据改判，避免自相矛盾。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2027-06-01",
                           "日历", "login", note="会话门拒 code=444",
                           attempt_id="old%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "soft_reject"
    assert row["kind"] == "soft"
    # 证据原样保留，便于核对
    assert "444" in (row["evidence"] or {}).get("note", "")


def test_legacy_real_login_is_not_relabelled(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("tuniu", "SHA", "BKK", "2027-06-01",
                           "H5/API", "login", note="登录号（710114/needLogin）",
                           attempt_id="t%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "login" and row["kind"] == "login"


def test_legacy_no_result_login_rows_are_relabelled_as_empty(tmp_path):
    """去哪儿"原站无符合条件的航班"曾被记 login（1999 双向重载）。

    真实 48h 账本里这类历史行 44 条；不按证据改判，复发面板会把
    真无票说成"登录态失效（需人工）"，把用户推去做无用重登。
    """
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path(
            "qunar", "SHA", "HKG", "2026-11-10", "API", "login",
            note="原站返回无符合条件的航班（可能受指纹 SDK/风控环境影响）",
            attempt_id="q%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "empty"
    assert row["kind"] == "empty"
    assert "无符合条件的航班" in (row["evidence"] or {}).get("note", "")


def test_legacy_1999_login_rows_are_relabelled_soft(tmp_path):
    """r385 受控 A/B 推翻了 r382 的假设：1999 不是登录墙。

    同 profile、零介入、6 轮 × SHA→LHR：首轮 1999 后连续 5 轮出数，
    未重登即自愈。故历史 login 行（证据写 1999）展示时按 soft 归类，
    不再催用户重登。改名保留用例位（原 test_legacy_1999_login_wall_
    stays_login 的结论已被实测推翻）。
    """
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "HKG", "2026-11-10", "H5",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="k%d" % i)
    row = st.failure_recurrence(24, 3)[0]
    assert row["status"] == "soft_reject" and row["kind"] == "soft"


def test_recurrence_marks_recovered_after_later_success(tmp_path):
    """失败后又成功 = 已恢复：复发账不再继续喊「需人工」。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-01", "H5",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="b%d" % i)
    st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-02", "H5", "ok",
                       rows=30, attempt_id="ok")
    row = next(r for r in st.failure_recurrence(24, 3)
               if r["path"] == "H5")
    assert row["recovered"] is True, "之后已出数，不能还标需人工"
    assert row["last_ok_at"]


def test_recurrence_not_recovered_without_later_success(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2027-06-01", "日历",
                           "soft_reject", note="国际日历请求形态门拒 code=444",
                           attempt_id="s%d" % i)
    row = next(r for r in st.failure_recurrence(24, 3)
               if r["path"] == "日历")
    assert row["recovered"] is False


def test_recurrence_recovered_only_for_same_path(tmp_path):
    """别的路径成功不能顶替：H5 好了不代表 API 也好了。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(3):
        st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-01", "API",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="a%d" % i)
    st.save_fetch_path("qunar", "SHA", "BKK", "2027-06-02", "H5", "ok",
                       rows=20, attempt_id="ok2")
    row = next(r for r in st.failure_recurrence(24, 3)
               if r["path"] == "API")
    assert row["recovered"] is False
