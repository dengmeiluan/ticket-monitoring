# -*- coding: utf-8 -*-
"""r627：全局参数页的控件事件必须真的能被浏览器解析出来。

缺陷形态（真实踩过，实机普查 45 个控件里 5 个中招）：
`glcell` 把事件表达式直接拼进 `onchange="..."`，其中 text 型控件的表达式
自带 `""`（`(this.value||"")`）。HTML 属性用双引号包裹，浏览器在第一个
内嵌 `"` 处把属性截断：

    onchange="GLB.scan_quiet_start=(this.value||"     ← el.onchange === null
               "").trim()"                          ← 被当成两个野属性

结果：输入框能打字、能失焦，值却从未写进 GLB，保存后仍是原值，页面
不报错——「配了不生效」，比压根没有控件更难归因。

判据不是「源码里有没有 "" 」，而是**按 HTML 解析规则还原后能不能拿回
原表达式**。第三条测试用老写法做负控，证明这条判据真能抓到该缺陷。
"""
import io
import os
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


class _Attrs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = {}

    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def _parsed_onchange(expr, escape):
    """按浏览器规则解析 `onchange="<expr>"`，返回属性实际读到的值。"""
    if escape:
        expr = (expr.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;")
                .replace("'", "&#39;"))
    p = _Attrs()
    p.feed('<input onchange="%s">' % expr)
    return p.attrs.get("onchange")


# 正是那 5 个出问题的表达式形态
_REAL_WORLD = [
    'GLB.scan_quiet_start=(this.value||"").trim()',
    'GLB.warmup_platforms=(this.value||"").trim()',
    'GLB.android=Object.assign({},GLB.android||{},{install_dir:(this.value||"").trim()})',
    'GLB.android=Object.assign({},GLB.android||{},{provider:(this.value||"mumu").trim()})',
]


def test_escaping_restores_the_exact_expression():
    """esc() 之后，属性解析能完整还原本来的表达式。"""
    for expr in _REAL_WORLD:
        assert _parsed_onchange(expr, escape=True) == expr, \
            "转义后属性仍被截断：" + expr


def test_unescaped_expression_really_breaks():
    """负控：不转义时确实拿不回原表达式（证明上一条不是空转）。"""
    broken = [e for e in _REAL_WORLD
              if _parsed_onchange(e, escape=False) != e]
    assert broken, "判据失效：不转义也没被截断，说明这条门禁测不到目标缺陷"


def test_glcell_escapes_both_bindings():
    w = _w()
    i = w.index("const glcell=")
    seg = w[i:i + 2000]
    assert "onchange=\"'+esc(onch)+'\"" in seg, \
        "glcell 的 onchange 未转义：含 \"\" 的表达式会被截断成半截 JS"
    assert "onchange=\"'+onch+'\"" not in seg, \
        "glcell 仍在直接拼接 onch"
    assert "' onchange=\"'+esc(onch)+'\">'" in seg, \
        "输入框的 onchange 未转义"
