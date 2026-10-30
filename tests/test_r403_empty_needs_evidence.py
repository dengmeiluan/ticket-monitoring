# -*- coding: utf-8 -*-
"""r403：跨渠道守卫——`empty` 只能由"明确无票"支撑。

r398b / r400 / r401 / r402 是同一个病的四次发作：**用"没证据"去支撑一个
肯定性结论**。`empty` 一旦记错，用户看到的是"今天确实没航班"并停止关注，
比记成 error 危害更大（error 至少会让人去看现场）。

本守卫把判据固定在源码层面：

1. 任何渠道代码里出现 `path_status='empty'` / `"empty"` 的写入，所在函数
   或邻近上下文必须能指出"明确无票"的依据（文案匹配 / 显式常量），
   不能是 `else:` 兜底；
2. 已知的四类"伪 empty"文案不得再被写成 empty：
   「请求无响应」「未解析到」「没拿到」「无证据」；
3. 正常渠道里，`empty` 之外还要有 `error` 这个出口（不能只剩二选一）。

这是**防止回潮的护栏**，不替代各渠道自己的行为测试。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")

# 这些措辞描述的是"我们没拿到/没解析出"，不是"站点说没票"
PSEUDO_EMPTY_MARKERS = ("请求无响应", "未解析到", "没拿到", "无证据")
# 正则版：允许短语中间夹词（"H5 无 listingsearch 响应" 曾漏网，r405）
PSEUDO_EMPTY_PATTERNS = (
    re.compile(r"无.{0,24}响应"),
    re.compile(r"未(解析|拿到|获取)"),
    re.compile(r"没有(拿到|收到|获取)"),
)


def _sources():
    for fn in sorted(os.listdir(CRAWLERS)):
        if fn.endswith(".py"):
            path = os.path.join(CRAWLERS, fn)
            yield fn, open(path, encoding="utf-8").read()


def test_no_pseudo_empty_wording():
    """不得把"没拿到/没解析出"的文案写成 empty 状态。

    只看**代码行**（去掉注释），否则解释这条规则本身的注释会被误报。
    同时用**正则**匹配短语中间夹词的形态——「H5 无 listingsearch 响应」
    曾因字面标记只覆盖「请求无响应」而漏网（r405）。
    """
    bad = []
    for fn, src in _sources():
        lines = src.splitlines()
        for line_no, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if not re.search(r'["\']empty["\']', code):
                continue
            ctx = "\n".join(
                ln.split("#", 1)[0] for ln in lines[max(0, line_no - 3):line_no + 2])
            for mk in PSEUDO_EMPTY_MARKERS:
                if mk in ctx:
                    bad.append((fn, line_no, mk, code.strip()[:60]))
            for pat in PSEUDO_EMPTY_PATTERNS:
                m = pat.search(ctx)
                if m:
                    bad.append((fn, line_no, m.group(0), code.strip()[:60]))
    assert not bad, bad


def test_every_crawler_has_error_escape():
    """每个采集渠道都必须能记 error——否则失败时只能二选一（login/empty）。

    判据要看**能力**，不是「该文件里出现字面量」：继承 `AppBaseCrawler`
    的渠道（app_zhixing 等）统一走 `safe_fetch()`，异常在那里就被记成
    `app-error`，子类自己不必再写一遍。曾经只查文件字面量，于是
    `app_zhixing.py` 被判缺牌——而它其实有（r609 实测）。
    """
    try:
        with open(os.path.join(CRAWLERS, "app_base.py"),
                  encoding="utf-8", errors="replace") as f:
            base = f.read()
    except OSError:
        base = ""
    # 判据必须落在 `safe_fetch` 的**函数体**里：整个文件查关键字会假绿——
    # `PATH_STATUS` 元组、`path_note` 的默认兜底都含 "error"，
    # 实测删掉 safe_fetch 里那两行之后断言照样通过。
    base_escapes = False
    _i = base.find("def safe_fetch(")
    if _i >= 0:
        _j = base.find("\n    def ", _i + 10)
        _body = base[_i:_j if _j > 0 else _i + 1200]
        base_escapes = ('"error"' in _body and "path_note(" in _body
                        and "except Exception" in _body)
    missing = []
    for fn, src in _sources():
        if fn in ("__init__.py", "challenge.py"):
            continue
        if "path_note(" not in src:
            continue
        own = ('"error"' in src or "'error'" in src)
        # 基类在 `crawlers/app_base.py` 里叫 `AppCrawler`（早前注释里写的是
        # `AppBaseCrawler`，那个名字类上并不存在）。只认旧名会把继承这条
        # 逃逸能力的渠道（app_qunar 等）判成缺牌——它们 `safe_fetch()` 里
        # 的 error 分支是真生效的（r666 实况）。
        inherits_app = (("AppCrawler" in src or "AppBaseCrawler" in src)
                        and base_escapes)
        if not (own or inherits_app):
            missing.append(fn)
    assert not missing, missing


def test_empty_writes_are_not_bare_else():
    """`empty` 不得出现在"其他全失败"的裸 else 上。

    允许形态：`("empty" if <明确条件> else ...)` 或显式
    `path_note(..., "empty", ...)` 且上下文有 no-result 依据。
    """
    bad = []
    for fn, src in _sources():
        for line_no, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if not re.match(r'^else\s*["\']empty["\']', s):
                continue
            bad.append((fn, line_no, s))
    assert not bad, bad


def test_pacing_classifies_all_six_buckets():
    """path_stats 的六个桶必须都存在（r397 的登录/错误分离不能回退）。"""
    from core.storage import PriceStorage
    import tempfile
    st = PriceStorage(os.path.join(tempfile.mkdtemp(prefix="r403_"), "p.db"))
    st.save_fetch_path("x", "SHA", "BKK", "2026-11-16", "H5", "login")
    n = st.path_stats(hours=24)["x"]
    for k in ("ok", "empty", "login", "blocked", "soft", "unsupported",
              "error"):
        assert k in n, (k, sorted(n))
