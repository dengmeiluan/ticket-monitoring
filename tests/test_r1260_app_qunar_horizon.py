# -*- coding: utf-8 -*-
"""r1260：app_qunar 缺"日期视野守卫"——远期日期把它整条渠道拖进熔断。

现场（2026-11-10 16:4x–16:5x）：

```
[app_qunar] 开始抓取 SHA->LHR 日期=['2026-11-16']     ← 远期
[app_qunar] 抓取完成，得到 0 条记录
[app_qunar] 连续未取到结果，熔断 30 分钟：连续 9 次超时
[路径影子] app_qunar/dom 偏好 航班明细 82%, app-login 0%
```

四个兄弟渠道（ctrip / fliggy / tongcheng / zhixing）的 `fetch()` 里都有
`reject_far_dates(dates)`，**只有 app_qunar 没有**。于是远期日期照跑 → 超时 →
渠道级熔断 → 连它本来 82–90% 的「航班明细」通路一起停。

契约：
1. `app_qunar.fetch()` 必须调用 `reject_far_dates`（能力边界记 `unsupported`，不是失败）；
2. 早退顺序：`early_skip`（停服/需登录）→ `reject_far_dates`（视野）→ 再碰设备；
3. 兄弟渠道的那一处不许被删（防止将来有人"顺手统一"时漏掉）。
"""
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APPS = ["app_ctrip.py", "app_fliggy.py", "app_tongcheng.py",
        "app_zhixing.py", "app_qunar.py"]


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_every_app_crawler_guards_far_dates():
    """五个 App 渠道都要有视野守卫（今天只有 qunar 缺）。"""
    missing = [n for n in APPS if "reject_far_dates(" not in _src(n)]
    assert not missing, "这些 App 渠道没有日期视野守卫：%s" % missing


def test_qunar_orders_guards_before_touching_device():
    s = _src("app_qunar.py")
    i_fetch = s.find("def fetch(self, from_city")
    assert i_fetch > 0
    seg = s[i_fetch:i_fetch + 1200]
    i_early = seg.find("self.early_skip(dates)")
    i_far = seg.find("self.reject_far_dates(dates)")
    i_rt = seg.find("self.runtime()")
    assert i_early > 0 and i_far > i_early, (i_early, i_far)
    assert i_rt > i_far, "视野守卫必须在碰设备之前（否则照样耗设备时间）"


def test_siblings_still_have_it():
    """负控：不许为了"统一"把兄弟渠道那一处删掉。"""
    for n in APPS[:-1]:
        assert "reject_far_dates(" in _src(n), n
