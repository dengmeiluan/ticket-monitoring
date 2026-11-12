# -*- coding: utf-8 -*-
"""r936：认不出页面时不落现场 —— 于是同一个失败连查几轮还在猜。

2026-11-04 账本（`fetch_paths`）实证：

    app_qunar    航班明细  timeout  | 未取到可用结果：no-list-page
    app_zhixing  app-list  timeout  | 无法识别的页面状态（可能是 App 改版）

两条断言都**等于没说**：列表页为什么没出现？页面到底长什么样？
而且两次 `no-list-page` 各花了 **154s / 170s** 设备时间，查不出原因只能再来一轮。

对比：`no-priced-rows` 分支**有**落现场（`nopriced-<date>`），所以那个问题
几轮就查清了（`¥` 前缀那次的现场就是从这儿来的）。

结论：**"认不出/没出现"这类失败最需要现场，却偏偏没落盘。**

修法（统一抽象）：

1. `app_base.save_scene()` —— 通用落盘，任何 App 渠道都能用；
   只留前 150 条带文案/id/desc 的节点（真机 dump 常 200KB，不宜整份存）；
   `TICKET_SCENE_DIR` 作为测试隔离锚（避免合成现场混进生产目录）。
2. `app_qunar` 的 `no-list-page` 分支落 `nolist-<date>`，并**一行说清**
   命中了哪些已知标记（首页/城市页/列表页/登录），不用打开文件就知道停在哪。
3. `app_zhixing` 的「无法识别的页面状态」落 `unknown-page`，同样打标记命中。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r936_scene_on_unknown.py -q
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_base import save_scene  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 通用落盘
# ---------------------------------------------------------------------------
def test_save_scene_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    xml = ('<node text="机票查询" resource-id="com.suan:id/a" '
           'bounds="[10,20][300,80]" />')
    p = save_scene("unknown-page", xml, prefix="zhixing_app")
    assert p and os.path.isfile(p)
    body = io.open(p, encoding="utf-8").read()
    assert "机票查询" in body
    assert "10,20,300,80" in body


def test_save_scene_caps_rows(tmp_path, monkeypatch):
    """真机 dump 常 200KB：必须截断，不能整份存。"""
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    nodes = "".join('<node text="t%d" bounds="[0,%d][10,%d]" />'
                    % (i, i, i + 5) for i in range(500))
    p = save_scene("big", nodes, prefix="x", limit=20)
    lines = io.open(p, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 20, len(lines)


def test_save_scene_keeps_desc_only_nodes(tmp_path, monkeypatch):
    """中转航班号这类节点只有 content-desc、没有 text，也要留住。"""
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    xml = ('<node text="" content-desc="flight_search_rn|Qunar|ItemPrice" '
           'bounds="[655,784][723,817]" />')
    p = save_scene("desc", xml, prefix="x")
    body = io.open(p, encoding="utf-8").read()
    assert "ItemPrice" in body


def test_save_scene_is_fail_soft(monkeypatch, tmp_path):
    """写不进去不能抛（采集优先）。

    用「普通文件当目录」制造不可写：不依赖权限（root/runner 差异），
    也不往环境变量塞 NUL（Linux 的 os.environ 会先抛 ValueError，
    测试还没进 save_scene 就红了——2026-11-04 CI test(2) 实测）。
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("TICKET_SCENE_DIR", str(blocker / "sub"))
    assert save_scene("x", "<node text='a' bounds='[0,0][1,1]' />") == ""


def test_save_scene_empty_xml(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    p = save_scene("empty", "", prefix="x")
    # 仍写一个空文件（至少说明"这一帧是空的"）
    assert p and os.path.isfile(p)


# ---------------------------------------------------------------------------
# 2. 两处调用点都在，且带了标记提示（源码钉）
# ---------------------------------------------------------------------------
def test_qunar_saves_scene_when_list_page_missing():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find('return [], ("empty" if saw_list_page else "no-list-page")')
    assert i > 0
    seg = src[max(0, i - 1800):i]
    assert "nolist-" in seg, "no-list-page 仍不落现场"
    assert "列表页未出现" in seg, "没有一行说清停在哪一页"


def test_zhixing_saves_scene_on_unknown_state():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    i = src.find("无法识别的页面状态")
    assert i > 0
    seg = src[max(0, i - 1600):i]
    assert "save_scene" in seg, "认不出页面时不落现场"
    assert "unknown-page" in seg


def test_no_bare_private_save_scene_left_in_zhixing():
    """不许再引用不存在的 `_save_scene`（那是 qunar 的私有函数）。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert "_save_scene(" not in src
