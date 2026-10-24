# -*- coding: utf-8 -*-
"""r319 采集代理接线钉：crawler.proxy 配置 → 浏览器/httpx 出口。

- BaseCrawler 读 proxy、browser() 传 Playwright proxy 参数（源码钉：
  启动参数真面无法无头单测，钉字面+属性读数）
- crawlers/special 双源 fetcher 接受 proxy 形参（签名字面）
- main specials 编排把 crawler.proxy 传给发现层（源码钉）
- webui 全局面板字段与 POST 落键（源码钉+config round-trip 由既有
  saveCfg verbatim 通路覆盖）
- config.example.yaml 带注释样例（入手简单）
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestProxyPlumbing(unittest.TestCase):
    def test_base_crawler_reads_proxy(self):
        import logging
        from crawlers.base import BaseCrawler
        c = BaseCrawler({"proxy": " http://127.0.0.1:7897 "},
                        logging.getLogger("t"))
        self.assertEqual(c.proxy, "http://127.0.0.1:7897")   # strip
        c2 = BaseCrawler({}, logging.getLogger("t"))
        self.assertEqual(c2.proxy, "")

    def test_browser_launch_passes_proxy(self):
        src = _src("crawlers/base.py")
        self.assertIn('proxy=({"server": self.proxy} if self.proxy else None)',
                      src)

    def test_special_fetchers_accept_proxy(self):
        import inspect
        from crawlers import special as sp
        for fn in (sp.fetch_tuniu_board, sp.fetch_ctrip_calendar,
                   sp.fetch_ctrip_board, sp.fetch_fliggy_board):
            self.assertIn("proxy", inspect.signature(fn).parameters, fn)

    def test_main_wires_proxy_into_discovery(self):
        src = _src("main.py")
        self.assertIn('fetch_tuniu_board(logger, proxy=_proxy)', src)
        self.assertIn('proxy=_proxy)', src)   # ctrip 日历正反向两处
        # 热重载：代理变更清爬虫实例缓存
        self.assertIn("采集代理已切换", src)

    def test_webui_globals_proxy_field(self):
        src = _src("webui.py")
        self.assertIn("glbProxy", src)                       # 面板字段
        self.assertIn('_crw["proxy"] = _px', src)            # POST 落键
        self.assertIn('"proxy": str((cfg.get("crawler") or {}).get(',
                      src)                                   # GET 组装
        # 形态校验（Soldier P2#4）：漏 scheme 的手滑输入回直连——
        # httpx 对无 scheme 代理抛 InvalidURL 会让发现层全哑
        self.assertIn('not re.match(r"^https?://[^\\s/]+:\\d+$", _px)',
                      src)
        self.assertIn("采集代理须为 http://主机:端口 形态", src)
        # 发现层 trust_env 恒 False（Soldier P2#3）：系统代理环境变量
        # 一律不吃，出口只由显式 proxy 形参控制
        sp = _src("crawlers/special.py")
        self.assertNotIn("trust_env=not proxy", sp)
        self.assertEqual(sp.count("trust_env=False"), 7)   # 五源 fetcher（新增飞猪/同程/途牛日历）   # 四源 fetcher

    def test_example_config_documents_proxy(self):
        src = _src("config.example.yaml")
        self.assertIn("proxy: http://127.0.0.1:7897", src)
        self.assertIn("国内直落", src)


if __name__ == "__main__":
    unittest.main()
