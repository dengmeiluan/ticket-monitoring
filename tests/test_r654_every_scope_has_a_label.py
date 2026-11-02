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
    # 与 App 渠道 id（r813d 起 App 登录按渠道记 scope，不再合并成 app）
    from core.channels import APP_CHANNELS
    from core.login_slots import LOGIN_SLOTS
    scopes |= set(LOGIN_SLOTS.keys()) | set(APP_CHANNELS)
    # 动作级（空 scope）不计
    scopes.discard("")

    missing = sorted(s for s in scopes
                     if s != "<dynamic>" and s not in labels)
    assert not missing, (
        "这些 scope 值没有中文标签，面板会直接打出原始 id：%s（已有：%s）"
        % (missing, sorted(labels)))


def test_app_scope_reads_as_the_channel_name_not_raw_id():
    """两个 App 的干预 scope 必须各显示各的名字。

    r813d 前 App 登录统一写 scope="app"，面板把合并后的成功率标成
    「智行 App」——去哪儿 App 的重登统计被算在智行名下，既错又不可区分。
    现在写入按渠道 id；历史 scope=app 保留中性标签「旧记录」。
    """
    w = _w()
    i = w.index("const _ivScope={")
    seg = w[i:w.index("};", i)]
    assert "app_zhixing:'智行 App'" in seg, seg
    assert "app_qunar:'去哪儿 App'" in seg, seg
    assert "app:'App 登录（旧记录）'" in seg, seg
    assert "app:'智行 App'" not in seg, "合并的 app scope 不能再冒充智行"
    # 写入侧：登录成功后按渠道记 scope，而不是共享的 "app"
    assert "scope=_plata" in w
    assert 'save_intervention(\n                                _plata, "relogin", ok=True, scope="app"' not in w
