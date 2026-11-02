# -*- coding: utf-8 -*-
"""渲染 PNG 落盘重定向（TM_RENDER_DIR）：图表渲染写点原本硬编码
`data/` 相对路径——pytest/uitest 触达渲染链路时把测试图表落进生产
data/（实录：租户段 t 的 flights_table_*.png 多轮残留）。与
PUSH_HISTORY_FILE（r234）、哨兵状态（r235）同律的根治层：显式环境
变量重定向永远放行，默认路径行为不变。

钉面三层：
1. helper 默认值/环境覆盖行为；
2. 四个渲染写点全部消费 helper（源码钉：裸 `data/` 字面零残留）；
3. conftest autouse 注入在位（会话级重定向，防下一颗漏网）。"""
import os


class TestRenderDirHelper:
    def test_default_is_data(self, monkeypatch):
        from core.models import render_dir
        monkeypatch.delenv("TM_RENDER_DIR", raising=False)
        assert render_dir() == "data"

    def test_env_override(self, monkeypatch, tmp_path):
        from core.models import render_dir
        monkeypatch.setenv("TM_RENDER_DIR", str(tmp_path / "rend"))
        assert render_dir() == str(tmp_path / "rend")

    def test_empty_env_falls_back(self, monkeypatch):
        from core.models import render_dir
        monkeypatch.setenv("TM_RENDER_DIR", "")
        assert render_dir() == "data"


class TestRenderSitesConsumeHelper:
    """源码钉：四个渲染写点（alerter×2 + report×2）一律经 render_dir()
    构路径；裸 `data/` 图表字面零残留（notify 目录等非图表写点不在面）。"""

    @staticmethod
    def _src(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_alerter_no_bare_table_literal(self):
        import core.alerter as _a
        src = self._src(_a.__file__)
        assert "data/flights_table_" not in src
        assert src.count("render_dir()") >= 2

    def test_report_no_bare_table_or_trend_literal(self):
        import report as _r
        src = self._src(_r.__file__)
        assert "data/flights_table_" not in src
        # os.path.join("data", f"trend_ 形态的裸目录零残留
        assert '"data", f"trend_' not in src
        assert src.count("render_dir()") >= 2

    def test_models_exports_render_dir(self):
        import core.models as _m
        assert callable(_m.render_dir)


class TestConftestAutouseInjection:
    def test_autouse_fixture_redirects_render_dir(self):
        """autouse 夹具在场：本测试未显式 setenv，靠夹具注入后
        TM_RENDER_DIR 应已指向 tmp_path 且不在仓库内。"""
        cpath = os.path.join(os.path.dirname(__file__), "conftest.py")
        val = os.environ.get("TM_RENDER_DIR")
        assert val, "TM_RENDER_DIR 未被 autouse 夹具注入"
        # 源码钉：夹具对 TM_RENDER_DIR 的 setenv 在位
        with open(cpath, encoding="utf-8") as f:
            csrc = f.read()
        assert "TM_RENDER_DIR" in csrc

    def test_uitest_spawns_demo_with_redirect(self):
        """uitest 自包含脚本拉起的 demo 服务同样注入重定向
        （子进程经 env 继承，服务端渲染不落仓库 data/）。"""
        upath = os.path.join(os.path.dirname(__file__), os.pardir,
                             "docs", "uitest.py")
        with open(upath, encoding="utf-8") as f:
            usrc = f.read()
        assert "TM_RENDER_DIR" in usrc
