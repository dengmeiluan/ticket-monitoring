# -*- coding: utf-8 -*-
"""r1063 T82：MuMu 底层设备身份——看得到、换得掉（且换得像真的）。

用户问「是否可能是 mumu 底层 id 已经被封禁，还有什么手段可以进行解封」。

取证结论（T81）：**不是整机被封**（同一台机的智行/去哪儿 19 秒正常出数），
是**分渠道**的风控状态（飞猪=阿里 NC 滑块、携程=强制登录）。
但"换一张设备脸"仍是解封阶梯里的一档，所以把它做成工具：

    python -m core.android.identity show        # 当前 imei/品牌/机型/认证码
    python -m core.android.identity rotate      # 演练：只说会换成什么
    python -m core.android.identity rotate --apply   # 真写（需重启实例）

纪律：
* 默认只演练；
* **必须先关机再改**（运行中改会让 App 看到半新半旧，比不换更可疑）；
* 换的机型取自真实机型清单——编造型号本身就是异常信号；
* IMEI 带 **Luhn 校验位**，校验位错的 IMEI 一眼假。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import identity  # noqa: E402


def test_imei_is_valid_luhn():
    import random

    for seed in range(20):
        imei = identity._rand_imei(random.Random(seed))
        assert len(imei) == 15

        def luhn_ok(s):
            total = 0
            for i, ch in enumerate(reversed(s)):
                d = int(ch)
                if i % 2 == 1:
                    d *= 2
                    if d > 9:
                        d -= 9
                total += d
            return total % 10 == 0

        assert luhn_ok(imei), imei


def test_models_are_real_shapes():
    """机型清单必须是"品牌 + 型号 + 认证码"三件套，且不像编的。"""
    for brand, model, miit in identity.DEVICE_MODELS:
        assert brand and model and miit
        assert len(model) >= 4 and len(miit) >= 4
        assert brand.lower() != "unknown"


def test_rotate_dry_run_never_writes():
    rep = identity.rotate_id({}, 0, apply=False)
    assert rep["ok"] is True and rep["applied"] is False
    assert rep["want"]["phone_imei"]
    assert "演练" in rep["why"]
    assert rep["need_restart"] is True


def test_show_is_honest_when_manager_missing():
    rep = identity.show({"android": {"install_dir": "\\不存在的路径"}}, 0)
    assert isinstance(rep, dict) and "id" in rep
    if not rep["ok"]:
        assert rep["why"], "读不到时必须说明原因，不能静默返回空"


def test_unwrap_handles_json_text():
    assert identity._unwrap(
        "phone_imei", '{\n  "phone_imei": "865247046277134"\n}\n'
    ) == "865247046277134"
    assert identity._unwrap("phone_brand", "vivo") == "vivo"


def test_rotate_requires_restart_hint():
    """换完必须重启实例才生效——这条要写在返回里，别让人以为即时生效。"""
    rep = identity.rotate_id({}, 0, apply=False)
    assert rep["need_restart"] is True
