# -*- coding: utf-8 -*-
"""r312 落地钉：B1 fliggy 回放载体（_debug_snapshot extra_text 落 .txt）
+ P1-1 失败态 pill 词面分路 + P3-1 header 出血相抵律（源码钉，
几何/行为钉在 docs/uitest.py 尾段）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.base import BaseCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
import webui  # noqa: E402


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _mk_crawler(tmp_path):
    c = BaseCrawler.__new__(BaseCrawler)
    c.debug = True
    c.debug_dir = str(tmp_path)
    c.name = "testplat"
    c.logger = _FakeLogger()

    class _Page:
        def screenshot(self, *a, **k):
            raise RuntimeError("no shot in test")

        def content(self):
            return "<html></html>"
    return c, _Page()


def test_debug_snapshot_extra_text_writes_txt(tmp_path):
    """extra_text 在场 → {base}.txt 落盘且内容逐字节一致（回放载体）。"""
    c, page = _mk_crawler(tmp_path)
    c._debug_snapshot(page, "pc_ABCD_2026-10-15",
                      extra_text="航班A\n@@@\n航班B")
    txt = Path(tmp_path) / "testplat_pc_ABCD_2026-10-15.txt"
    assert txt.exists(), "extra_text 未落 .txt"
    assert txt.read_text(encoding="utf-8") == "航班A\n@@@\n航班B"


def test_debug_snapshot_without_extra_text_no_txt(tmp_path):
    """缺省不落 .txt（既有调用方零变化）。"""
    c, page = _mk_crawler(tmp_path)
    c._debug_snapshot(page, "pc_X")
    assert not (Path(tmp_path) / "testplat_pc_X.txt").exists()


def test_fliggy_fetch_wires_full_stream():
    """fliggy 抓取尾段把解析输入 full（innerText 流）传给快照
    （回放载体的接线点：存的是解析器实际吃的东西，不是 DOM 壳）。"""
    import crawlers.fliggy as _fm
    # 接线断言走源码级（模块定位随包安装位置走，非仓库根 CWD 亦可跑）；
    # 行为级全链需真浏览器，uitest 面；此处锁接线形态防回归
    body = Path(_fm.__file__).read_text(encoding="utf-8")
    call = [ln for ln in body.splitlines()
            if "self._debug_snapshot(page, f\"pc_{fc}{tc}_{date}\"" in ln]
    assert len(call) == 1, "pc_ 快照调用形态漂移"
    idx = body.splitlines().index(call[0])
    nxt = body.splitlines()[idx + 1]
    assert "extra_text=full" in nxt, "pc_ 快照未传解析输入流"


def test_pillstate_failure_forms_carry_bad_flag():
    """失败形态 pillState **全部**带 bad 旗标（计数断言锁全量——存在性
    断言对「其中一处回退」失明）：服务异常 ×3、服务未启动 ×2；
    中性态（已全停用/未配置/达标态）不带。"""
    src = Path(webui.__file__).read_text(encoding="utf-8")
    assert src.count("pillState('服务异常','pill bad',") == 3, \
        "服务异常失败形态应恰 3 处带 bad 旗标"
    assert src.count("pillState('服务未启动','pill bad',") == 2, \
        "服务未启动失败形态应恰 2 处带 bad 旗标"
    assert "pillState('已全停用','pill'," in src, "中性态被误标 bad"
    assert "pillState('未配置','pill'," in src, "中性态被误标 bad"


def test_jumpqual_branches_on_bad_flag():
    """jumpQual 首分支按 bad 旗标分路（行为钉在 uitest 尾段）。"""
    src = Path(webui.__file__).read_text(encoding="utf-8")
    assert "classList.contains('bad')" in src
    assert "恢复后自动刷新" in src


def test_header_bleed_matches_wrap_padding_clamp():
    """header 出血与 .wrap padding 同函数（相抵律）：-clamp(12px,3vw,18px)。
    几何行为钉（三带巡检）在 docs/uitest.py。"""
    src = Path(webui.__file__).read_text(encoding="utf-8")
    assert "margin:0 calc(-1*clamp(12px,3vw,18px)) 4px" in src
