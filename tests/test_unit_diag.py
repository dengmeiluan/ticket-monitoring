# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1677_diag_evidence_not_thin.py
- tests/test_r1726_diag_card_kinds.py
- tests/test_r557_diag_button_baseline.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pathlib
import re
import urllib.request


# ---- merged from tests/test_r1677_diag_evidence_not_thin.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


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


# ---- merged from tests/test_r1726_diag_card_kinds.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kinds():
    hd = io.open(os.path.join(ROOT, "core", "health_diag.py"),
                 encoding="utf-8").read()
    return sorted(set(re.findall(r'_card\(\s*\w+\s*,\s*"([a-z_]+)"', hd)))


def _webui():
    return webui_full_src()


def test_every_kind_has_a_tone():
    w = _webui()
    missing = [k for k in _kinds() if (".hdiag-card.%s .hdiag-st" % k) not in w]
    assert not missing, "这些 kind 没有配色（会与「未知」同色）：%s" % missing


def test_cookie_expired_offers_login_button():
    w = _webui()
    # 按钮条件现在是多行形态：`const btn=(c.kind==='login'||c.kind==='captcha'
    #   ||c.kind==='cookie_expired')`，按 const btn= 定位再检查。
    i = w.index("const btn=")
    seg = w[i:i + 260]
    assert "cookie_expired" in seg, \
        "cookie 过期的卡没有「打开登录」按钮——文案让人重登，按钮却只有自检"
    assert "data-diaglogin" in w[i:i + 900], "登录按钮没有接到 srxGoLogin"


def test_known_kinds_all_styled():
    kinds = _kinds()
    assert "cookie_expired" in kinds and "maintenance" in kinds, kinds


# ---- merged from tests/test_r557_diag_button_baseline.py ----

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = webui_full_src()


def _rule(sel):
    """取**基础规则**的声明块。

    锚点必须带行首前缀：裸 `.hdiag-h{` 会先命中更靠前的窄卡覆盖规则
    `.hdiag[data-n="5"] .hdiag-h{flex-wrap:wrap…}`，拿它去比基础契约
    会造出假红（2026-10-31 实测：三条守卫同因失败，基础规则本身完好）。
    """
    i = TEXT.index("\n" + sel)
    j = TEXT.index("}", TEXT.index("{", i))
    return re.sub(r"/\*.*?\*/", "", TEXT[i:j + 1], flags=re.S)


def test_status_pill_can_shrink_inside_header():
    body = _rule(".hdiag-h>.hdiag-st{")
    flat = body.replace(" ", "")
    assert "min-width:0" in flat, body
    assert "overflow:hidden" in flat, body
    assert "text-overflow:ellipsis" in flat, body


def test_channel_name_never_shrinks():
    body = _rule(".hdiag-h>b{").replace(" ", "")
    assert "flex:0 0 auto".replace(" ", "") in body, body
    assert "white-space:nowrap".replace(" ", "") in body, body


def test_header_has_pinned_min_height():
    body = _rule(".hdiag-h{")
    assert "min-height:17px" in body.replace(" ", ""), body


def test_status_pill_keeps_family_padding():
    """胶囊 1px 6px 是同族契约（test_r374 也守着），改收缩不能顺手改内边距。"""
    body = _rule(".hdiag-st{")
    assert "padding:1px 6px" in body, body


def test_header_carries_full_text_in_title():
    # r1634/r1639 新增了 halt / retired 两个短标签分支，源码里排在主卡之前；
    # 本测试钉的是**主卡**的长状态标签（_surfTxt+c.label 可能被裁），
    # 锚点必须钉主卡模板本身，不能用首个 'class="hdiag-card '（会落到新分支）。
    i = TEXT.index('<div class="hdiag-card \'+he(c.kind)+\'"')
    seg = TEXT[i:i + 420]
    assert 'class="hdiag-st" title="' in seg, seg
