# -*- coding: utf-8 -*-
"""webui 图床引导回归（源码级钉死）：推送图床卡/引导链接/setIh
切换显隐/smms 保存校验/整用户回传落盘链/alerter upload_chart 消费端。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1559_webui_imghost.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _webui_src():
    import webui as _w
    return _read(_w.__file__)


class TestWebuiImghostPins:
    """webui.py 源码级钉死：引导链路错一处即失败（同 模式）。"""

    def test_guide_links_present(self):
        src = _webui_src()
        # 引导动线：注册页 + API Token 直达页，两链缺一不可
        assert 'href="https://sm.ms/home/apitoken"' in src
        assert 'href="https://sm.ms"' in src
        assert 'target="_blank"' in src

    def test_imghost_card_and_toggle(self):
        src = _webui_src()
        assert 'data-ch="imghost"' in src          # 图床卡（chcard 第五张）
        assert "function setIh(" in src            # 原位切换（不整卡重建）
        assert "ih-token" in src                   # Token 行显隐锚点
        assert "ihchip" in src                     # provider chips

    def test_save_validation_smms_token(self):
        src = _webui_src()
        # smms 无 token 会静默降级 pixhost（钉钉拉不到）——保存时拦下
        assert "图床选了 sm.ms 但 Token 为空" in src

    def test_users_wholesale_roundtrip(self):
        src = _webui_src()
        # image_host 随「整 users 回传」落盘——此行被改即断链
        assert 'cfg["users"] = body.get("users") or []' in src

    def test_alerter_consumes_upload_chart(self):
        import core.alerter as _a
        src = _read(_a.__file__)
        assert "upload_chart(" in src
        assert "ih=self.image_host" in src
