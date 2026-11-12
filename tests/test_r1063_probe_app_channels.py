# -*- coding: utf-8 -*-
"""r1063 T103：`/api/channel/probe` 对 App 渠道必须能跑（不许 AttributeError）。

真机现场（2026-11-08 16:05）：
```
app_fliggy {"ok": false, "err": "'AppFliggyCrawler' object has no attribute 'last_block_url'"}
app_ctrip  {"ok": false, "err": "'AppCtripCrawler' object has no attribute 'last_block_url'"}
```
`last_block_url` 是**浏览器爬虫专属**字段，App 爬虫没有。用户在 App 渠道点
「自检 / 核验」永远得到失败——读作"登录无效"，而真实原因可能是"日期超视野"
或"访问被拒绝"。

修好后同样的探针给出的都是**具体原因**：
```
app_fliggy  blocked 「飞猪返回『访问被拒绝』安全页；需人工打开 App 处理后再采集」
app_ctrip   login   「该日被要求登录」
app_qunar   login   「需登录（83 分钟内不再重试）」
app_zhixing ok      1 条真实航班/时刻/价格
```
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_last_block_url_use_is_guarded():
    """`last_block_url` 是浏览器专属字段，出现处必须 getattr 保护。"""
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    for m in re.finditer(r"[^\n]*\.last_block_url[^\n]*", src):
        line = m.group(0)
        if line.strip().startswith("#"):
            continue
        assert 'getattr(c, "last_block_url"' in line or \
            "getattr(" in line, "未保护的 last_block_url：%s" % line.strip()


def test_probe_result_includes_blocked_url_safely():
    """探针结果里仍要有 blocked_url（浏览器渠道用得到），但缺字段不能炸。"""
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert '"blocked_url": (getattr(c, "last_block_url", "") or "")[:120]' \
        in src


def test_app_crawlers_lack_browser_only_fields():
    """确认前提：App 爬虫确实没有 last_block_url（这正是当初崩的原因）。"""
    from crawlers.app_ctrip import AppCtripCrawler
    from crawlers.app_fliggy import AppFliggyCrawler
    for cls in (AppCtripCrawler, AppFliggyCrawler):
        assert not hasattr(cls, "last_block_url"), cls
