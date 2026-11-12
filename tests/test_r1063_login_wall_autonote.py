# -*- coding: utf-8 -*-
"""r1063 T85：把"要登录"识别准，并让登录墙记忆自动生效（不再每轮白跑）。

真机链条（携程 App，2026-11-08）：
* 设备脸修好（T84）之后，**匿名可以进机票搜索页**（首页正常、能填上海→北京、
  能选日期、能看到「查询」按钮）；
* 但一点「查询」就回「手机验证码登录」——**查询必须登录**，这是站点策略；
* 我们却把这一步记成 `timeout/列表已打开但无可解析航班`：
  登录页晚一帧才盖上来，轮询已经在列表壳上判了 `is_list_page()` 并跳出。

两处修正：
1. `path_note(..., "login")` → **自动**置 `login_suspect` + 落登录墙记忆（全渠道，`app_base`）；
2. `_collect_rows` 为空时**再查一次登录墙**（携程这类竞态的直接补丁）。

真机效果：
```
login_suspect = True
登录墙记忆: 路径账记 login：该日被要求登录
窗口内再跑：0 条，耗时 0.00s（应≈0）
```
即：健康页会显示「需登录 + 去登录」，且**不再每轮白跑 20 秒**。
"""
import io
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_ctrip import AppCtripCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _crawler(tmp=None):
    return AppCtripCrawler({"user_data_dir": tmp or tempfile.mkdtemp(),
                            "android": {}}, logging.getLogger("t85"))


def test_login_note_marks_wall_automatically():
    """记一条 login 账，就该等于"这家要登录"——置状态 + 落记忆。"""
    c = _crawler()
    assert c.login_suspect is False
    assert c.login_wall_until() == 0.0
    c.path_note("航班明细", "login", detail="该日被要求登录")
    assert c.login_suspect is True
    assert c.login_wall_until() > 0, "登录墙记忆必须落盘"


def test_non_login_status_does_not_mark():
    c = _crawler()
    c.path_note("航班明细", "timeout", detail="没打开")
    assert c.login_suspect is False
    assert c.login_wall_until() == 0.0


def test_login_memo_makes_fetch_free():
    c = _crawler()
    c.path_note("航班明细", "login", detail="窗内测")
    import time
    t0 = time.time()
    rows = c.fetch("SHA", "PEK", ["2026-11-16"])
    assert rows == []
    assert time.time() - t0 < 3, "登录墙窗口内不该再跑（真机实测 20 秒）"


def test_ctrip_rechecks_login_wall_when_rows_empty():
    """竞态补丁：空结果前必须再查一次登录墙，别把"要登录"记成"无航班"。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_ctrip.py"),
                  encoding="utf-8").read()
    i = src.index("_collect_rows(dev, page)")
    seg = src[i:i + 900]
    assert "再查一次登录墙" in seg
    assert 'note_date(date, [], "login"' in seg
    # 二次检查必须发生在记 timeout 之前
    assert seg.index('"login"') < seg.index("列表已打开但无可解析航班")
