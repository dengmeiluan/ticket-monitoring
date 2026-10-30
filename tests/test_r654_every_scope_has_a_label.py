# -*- coding: utf-8 -*-
r"""r654：干预成功率里出现的每个 scope，面板都要有中文标签。

r646 让 App 登录成功后写 `scope="app"` 的干预账；而前端
`_ivScope` 映射表里只有 dom/intl/pc/h5/fliggy_h5 —— 于是节流面板的
「干预成功率」分域里会把原始 id 直接打出来：「app 100%」。
读者不知道这是哪一家（渠道名表里没有 `app` 这个词）。

这类缺陷只在**真的有 App 干预样本**时才显形，正常数据下看不出来。

判据：把源码里所有会被写入 interventions.scope 的取值收集起来，
逐个要求 `_ivScope` 有对应中文；空格值除外（动作级统计，不分域）。
负控：删掉 `app:'智行 App'` → 本测试红。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_every_scope_written_to_the_ledger_has_a_chinese_label():
    w = _w()
    i = w.index("const _ivScope={")
    seg = w[i:w.index("};", i)]
    # 先按逗号切项再取键名：直接 findall 时 `fliggy:` 会先吃掉
    # `fliggy_h5:` 的前缀（非重叠匹配），带下划线的 key 永远读不到。
    labels = set()
    for item in seg.split(","):
        # 贪婪取到冒号前为止：`fliggy_h5:` 必须整体作为一个 key，
        # 而 [a-z_]+ 会先试着只吃 fliggy、发现后面不是冒号就整项放弃。
        m = re.match(r"\s*([a-z0-9_]+)\s*:", item)
        if m:
            labels.add(m.group(1))

    # 所有 save_intervention(..., scope=<literal>) 的落库取值
    scopes = set()
    for m in re.finditer(r'save_intervention\((?:[^()]|\([^()]*\))*?\)', w):
        call = m.group(0)
        for sm in re.finditer(r'scope\s*=\s*"([a-z_]+)"', call):
            scopes.add(sm.group(1))
        for sm in re.finditer(r'scope\s*=\s*str\(([^)]*)\)', call):
            # scope=str(key) / scope=str(scene.get("kind") or "")
            scopes.add("<dynamic>")
    # 动态 scope 的实际取值来自登录槽位 key（ctrip/qunar/fliggy/fliggy_h5/...）
    from core.login_slots import LOGIN_SLOTS
    scopes |= set(LOGIN_SLOTS.keys())
    # 动作级（空 scope）不计
    scopes.discard("")

    missing = sorted(s for s in scopes
                     if s != "<dynamic>" and s not in labels)
    assert not missing, (
        "这些 scope 值没有中文标签，面板会直接打出原始 id：%s（已有：%s）"
        % (missing, sorted(labels)))


def test_app_scope_reads_as_the_channel_name_not_raw_id():
    w = _w()
    i = w.index("const _ivScope={")
    seg = w[i:w.index("};", i)]
    assert "app:" in seg and "智行 App" in seg, (
        "App 干预的 scope 没配中文名：%r" % seg)
