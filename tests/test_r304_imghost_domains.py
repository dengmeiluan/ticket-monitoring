# -*- coding: utf-8 -*-
"""图床 provider 三方枚举一致性钉 + chhead 双 auto 边距禁复活钉。

判例（配置面扫盲盲区）：upload_chart 消费域三床（ghimg=GitHub 图库
主通路/freeimage/smms），配置页图床卡曾只有 freeimage/sm.ms 两 chip，
ghimg 被标签三元式错标成「freeimage」、repo/token 零 UI 面、通路验证
端点报「未知图床服务」——生产在用通路在配置页隐身且被冒名。本钉锁：
选项域（webui chips）==消费域（report.upload_chart）==验证域
（/api/test-imghost 白名单），任何一方单独扩床当日即红。

chhead 双 auto：`.chhead .muted{margin-left:auto}` 与 chev 的内联
margin-left:auto 平分自由空间——状态词面被顶到卡片/面板中央（展开态
面板 1180px 时 muted 距右缘 549px 实锤），右聚拢设计意图被内联样式
击穿。禁复活 + 右聚拢实效双段断言（行为级在 uitest R4）。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8").read()


PROVIDERS = ("ghimg", "freeimage", "smms")


def test_webui_chips_cover_all_providers():
    s = _src("webui.py")
    for p in PROVIDERS:
        assert 'data-p="%s"' % p in s, \
            "webui 图床 chip 缺 %s（选项域 < 消费域=配置盲区回归）" % p


def test_report_consumes_all_providers():
    s = _src("report.py")
    for p in PROVIDERS:
        assert 'provider == "%s"' % p in s, \
            "report.upload_chart 消费分支缺 %s（消费域漂移）" % p


def test_testimghost_whitelist_covers_all_providers():
    s = _src("webui.py")
    m = re.search(r'provider not in \(([^)]*)\)', s)
    assert m, "/api/test-imghost provider 白名单缺席"
    for p in PROVIDERS:
        assert '"%s"' % p in m.group(1), \
            "通路验证白名单缺 %s（验证域 < 消费域=测试按钮对主通路报「未知图床服务」）" % p


def test_ghimg_label_and_fields_present():
    s = _src("webui.py")
    assert "GitHub 图库" in s, "ghimg 词面（GitHub 图库）缺席"
    assert "ih-repo" in s, "ghimg repo 行缺席"
    assert "ih-proxy" in s, "ghimg 代理行缺席（直连失败重试代理无 UI 面）"


def test_chhead_chev_no_inline_auto_margin():
    s = _src("webui.py")
    n = s.count('<span class="chev open" style="margin-left:auto">')
    assert n == 0, \
        "chhead chev 内联 margin-left:auto 复活 %d 处（与 .muted 的 auto " \
        "平分自由空间，状态词面被顶到卡/面板中央）" % n


def test_chgrid_action_button_last():
    """通道网格语义序钉：全部配置卡一组，动作按钮（添加邮箱通道）收尾。

    动作按钮曾被图床卡隔在中间（邮件卡→添加按钮→图床卡），配置组里
    插动作件=顺序语义破相（用户立案）。"""
    s = _src("webui.py")
    i_card = s.find('data-ch="imghost"')
    i_btn = s.find('onclick="addEm(${i})"')
    assert i_card >= 0 and i_btn >= 0, "图床卡/添加邮箱通道模板缺席"
    assert i_card < i_btn, \
        "图床配置卡在动作按钮之后——chgrid 配置组未收拢、动作按钮未收尾"
