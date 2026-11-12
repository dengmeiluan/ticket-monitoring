# -*- coding: utf-8 -*-
"""r607：飞猪 H5 兜底通路在账本里只能有一个名字。

`FliggyCrawler._h5_fallback()` 会临时构造一个 `FliggyH5Crawler` 去取数，
再把它的 `paths` 并进自己的。而 `FliggyH5Crawler` **自己**就把每条路径
记成 `H5`（它在 `fetch()` 里先 `path_reset()`，然后 `path_note("H5", …)`）。

原实现无脑拼前缀：

    self.paths.append(dict(rec, path="H5:" + str(rec.get("path") or "")))

于是同一条通路在账本里出现两个名字：`H5`（H5 采集器自己记的）与
`H5:H5`（兜底包装后记的）。后果都在用户可见面上：

  - 健康卡的分通路小标把同一条路显示成两行；
  - `core/storage._retired_paths()` 按**字面** entry_path 比对，`H5` 与
    `H5:H5` 互不认识，一条已退役的兜底仍会拖着「在用」口径；
  - 渠道健康的通路成功率被拆成两份样本，任一份都可能不足判定下限。

修法：路径名由 H5 采集器单源决定，兜底原样透传。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                   encoding="utf-8", newline="").read()


def test_fallback_does_not_prefix_paths():
    src = _src()
    i = src.index("def _h5_fallback")
    seg = src[i:i + 1400]
    assert 'path="H5:"' not in seg, (
        "兜底仍在给 H5 采集器的路径加前缀（会产生 H5:H5 双名）")
    assert "self.paths.extend(" in seg, "兜底没有原样透传路径"


def test_h5_crawler_owns_the_path_name():
    """名字必须来自 H5 采集器本身——它是这条通路的唯一记账方。"""
    h5 = io.open(os.path.join(ROOT, "crawlers", "fliggy_h5.py"),
                 encoding="utf-8", newline="").read()
    assert 'path_note("H5"' in h5, "H5 采集器没有用 H5 作为路径名"


def test_fallback_notes_use_the_same_constant():
    """兜底自己的两条记账（缺会话 / 异常）也要用同一个名字。"""
    src = _src()
    i = src.index("def _h5_fallback")
    seg = src[i:i + 1400]
    assert "_FLIGGY_H5_PATH" in seg, "兜底记账没有走统一常量"
    assert not re.search(r'path_note\("H5"', seg), (
        "还有写死的 \"H5\" 字面量（与常量并存迟早漂移）")


def test_no_doubled_name_reaches_the_ledger():
    """真跑一次包装逻辑：并进 PC 采集器的路径不能出现 H5:H5。"""
    import sys
    sys.path.insert(0, ROOT)
    from crawlers.fliggy import FliggyCrawler, _FLIGGY_H5_PATH

    class FakeH5:
        session_state_path = __file__      # 存在即可，走正常分支
        paths = [{"path": _FLIGGY_H5_PATH, "status": "ok", "rows": 2},
                 {"path": "listingsearch", "status": "ok", "rows": 1}]

        def fetch(self, *a, **k):
            return [{"price": 1}]

    c = object.__new__(FliggyCrawler)
    c.config = {}
    c.logger = __import__("logging").getLogger("t")
    c.paths = []
    # 只测包装段：替换掉真实 H5 类。`_h5_fallback` 现在从
    # `crawlers.fliggy_h5` 里 import（不是 `crawlers.fliggy` 的命名空间），
    # 打在旧位置等于没打补丁——假替身不生效，真 H5 找不到会话直接返回，
    # 账本为空，测试就以「H5 不在 names」假红。补丁必须打在 import 源上。
    import crawlers.fliggy_h5 as mod
    real = mod.FliggyH5Crawler
    mod.FliggyH5Crawler = lambda *a, **k: FakeH5()
    try:
        c._h5_fallback("SHA", "BJS", ["2026-11-01"])
    finally:
        mod.FliggyH5Crawler = real
    names = [p.get("path") for p in c.paths]
    assert "H5:H5" not in names, "账本里出现了双名前缀：%s" % names
    assert "H5:H5:listingsearch" not in names, names
    assert "H5" in names, names
