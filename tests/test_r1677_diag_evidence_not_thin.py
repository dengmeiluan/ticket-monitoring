# -*- coding: utf-8 -*-
"""r1677：诊断卡的「证据」行不能是空的，也不能是「抓取失败」四个字。

现场（改前）：

```
ctrip      evidence=抓取失败     ← 等于没说
app_qunar  evidence=（空）       ← 账本明明写着「该日被要求登录 · 页面: 登录」
app_fliggy evidence=（空）
app_ctrip  evidence=（空）
app_zhixing evidence=（空）      ← 账本：App 自行退出后熔断中（还剩 115 分钟）
```

「证据」是这张卡唯一的可核对物。缺了就只剩猜。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_backend_fills_evidence_from_ledger():
    s = _w()
    assert "r1677" in s, "没有证据补全逻辑"
    i = s.index("r1677")
    seg = s[i:i + 900]
    assert 'recent_paths(_pp, 1)' in seg, "没有从账本取最近一条"
    assert '"抓取失败"' in seg, "没有把通用的「抓取失败」也当成缺证据"


def test_live_diag_has_real_evidence():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/health",
                               timeout=25).read())
    except Exception:
        return
    diag = d.get("diag") or []
    if not diag:
        return
    thin = [c.get("plat") for c in diag
            if str(c.get("evidence") or "").strip() in ("", "抓取失败")]
    assert not thin, "这些渠道的诊断卡没有可核对证据：%s" % thin
