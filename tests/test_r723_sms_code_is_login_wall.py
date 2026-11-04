# -*- coding: utf-8 -*-
"""r723 验证码页也是登录墙。

真机实测（2026-10-31 19:17，去哪儿 App）：输入手机号收到短信后，页面变成

    请输入验证码
    验证码已发送到 +86 199****8573
    46秒后重发

而 `LOGIN_FORM_MARKS` 只有「请输入手机号 / 获取验证码」——两条都不匹配，
登录墙被当成普通页继续找城市位，账本最后记成「选日期失败」/「设到达城市
失败」。用户按提示去查选择器，实际只要重登一次。

本门禁同时守「各 App 渠道别各写一份判据」：子类一旦覆盖 `_is_login_page`，
必须复用基类 `is_login_wall`，否则新增一种登录页形态时又只改一处。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from crawlers import APP_CHANNELS  # noqa: E402
from crawlers.app_base import AppCrawler  # noqa: E402

SMS_CODE_PAGE = """<hierarchy>
<node index="0" text="请输入验证码" resource-id="" class="android.widget.TextView"
      bounds="[40,600][400,650]" clickable="false" />
<node index="1" text="验证码已发送到 +86 199****8573" resource-id=""
      class="android.widget.TextView" bounds="[40,700][600,740]" clickable="false" />
<node index="2" text="46秒后重发" resource-id=""
      class="android.widget.TextView" bounds="[40,780][300,820]" clickable="false" />
</hierarchy>"""

PHONE_PAGE = """<hierarchy>
<node index="0" text="请输入手机号" resource-id="" class="android.widget.EditText"
      bounds="[40,600][600,660]" clickable="true" />
<node index="1" text="获取验证码" resource-id=""
      class="android.widget.TextView" bounds="[600,700][860,760]" clickable="true" />
</hierarchy>"""

FLIGHT_LIST = """<hierarchy>
<node index="0" text="上海" resource-id="" class="android.widget.TextView"
      bounds="[40,200][200,260]" clickable="false" />
<node index="1" text="¥1360" resource-id="" class="android.widget.TextView"
      bounds="[600,400][860,460]" clickable="false" />
<node index="2" text="01.27" resource-id="" class="android.widget.TextView"
      bounds="[40,300][200,340]" clickable="false" />
</hierarchy>"""


def _base():
    import logging
    return AppCrawler({"user_data_dir": "_scratch/r723_data"},
                      logging.getLogger("r723"))


def test_sms_code_page_counts_as_login_wall():
    """输入验证码的页面必须判成登录墙（否则会被当成普通页继续操作）。"""
    assert _base().is_login_wall(SMS_CODE_PAGE) is True


def test_phone_entry_page_still_counts():
    assert _base().is_login_wall(PHONE_PAGE) is True


def test_normal_page_is_not_login_wall():
    """负控：普通列表页不能判成登录墙，否则每轮都被当成掉登录。"""
    assert _base().is_login_wall(FLIGHT_LIST) is False
    assert _base().is_login_wall("") is False


@pytest.mark.parametrize("plat", list(APP_CHANNELS))
def test_each_app_channel_uses_same_login_judgement(plat):
    """各 App 渠道的 `_is_login_page` 必须与基类同源。

    子类各写一份判据，就会出现「基类加了验证码页、子类没跟」的漂移——
    r723 的缺陷正是这样产生的。
    """
    from crawlers import REGISTRY
    cls = REGISTRY.get(plat)
    assert cls is not None, "渠道 %s 未注册" % plat
    inst = cls({"user_data_dir": "_scratch/r723_data"},
               __import__("logging").getLogger("r723"))
    if type(inst).__dict__.get("_is_login_page") is None:
        # 子类没有私有判据：直接走基类 is_login_wall，这本身即同源。
        # 仍要证明「验证码页是登录墙、普通列表不是」在它身上成立。
        assert inst.is_login_wall(SMS_CODE_PAGE) is True
        assert inst.is_login_wall(FLIGHT_LIST) is False
        return
    # 验证码页：两份判据必须给同一个答案
    assert inst._is_login_page(SMS_CODE_PAGE) == inst.is_login_wall(SMS_CODE_PAGE), (
        "%s 的 _is_login_page 与基类登录墙判据不一致（验证码页）" % plat)
    assert inst._is_login_page(PHONE_PAGE) == inst.is_login_wall(PHONE_PAGE), (
        "%s 的 _is_login_page 与基类登录墙判据不一致（手机号页）" % plat)
