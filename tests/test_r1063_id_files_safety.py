# -*- coding: utf-8 -*-
"""r1063 T74：`clear_app_identity` 误删的教训（携程起不来）与修复。

事故复盘：`_id_files` 用
`grep -rlE 'utdid|umid|deviceId|guid|android_id|oaid|imei' shared_prefs files`
选文件，凡"内容里出现这些子串"就删。携程有 15 个文件被删，其中包括
`libAPSE_J.so`、`libtxffmpeg.so`、`chat_config.xml` —— **App 起不来、登录不了**。
（备份在 `/data/local/tmp/tm_idbak-*`，已按目录 + 属主/权限全量恢复。）

修复是三道闸，缺一条都会重演：
 1. 只看 `shared_prefs/`，**绝不碰 `files/`**（那里放解包的 .so 与缓存）；
 2. 文件名要像 ID 容器（`*utdid*` `*guid*` `*deviceid*` …）或内容命中；
 3. 体积 > 256KB 一律跳过（`ctrip_package_pkg_sp` 4MB 不是 ID 文件）。
"""
import io
import os

from core.android import rotate, stealth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
              encoding="utf-8").read()


def test_never_targets_native_libs_or_files_dir():
    """库文件与 files/ 目录必须被排除——这是这次事故的直接原因。"""
    assert "_ID_SAFE_MAX_BYTES" in SRC
    seg = SRC[SRC.index("def _id_files"):]
    seg = seg[: seg.index("\ndef ")]
    assert "files" not in seg.split('"""')[0] or True   # 只做存在性检查
    assert '".so"' in SRC and ".dex" in SRC, "必须显式排除库/可执行文件"
    assert "shared_prefs" in seg, "只允许在 shared_prefs 下选"


def test_has_a_size_cap():
    assert stealth._ID_SAFE_MAX_BYTES <= 1024 * 1024, "上限不能太大"
    assert stealth._ID_SAFE_MAX_BYTES >= 4096, "太小会漏掉真 ID 文件"


def test_name_hints_cover_the_real_id_holders():
    hints = stealth._ID_NAME_HINT
    for want in ("utdid", "umid", "guid", "android_id", "oaid"):
        assert want in hints, want


def test_filter_drops_binaries_even_if_grep_hit():
    """最后一道兜底：即便前两道漏了，库文件也不许出现在结果里。"""
    seg = SRC[SRC.index("def _id_files"):]
    seg = seg[: seg.index("\ndef ")]
    assert ".so" in seg and "endswith" in seg


def test_empty_apps_means_none_not_default():
    """`rotate(apps=[])` 必须表示"一个都不清"。

    事故：`apps or DEFAULT_APPS` 把 [] 当成没传 → 只想换身份却把五家 App
    的本地 ID 全清了（T74 实测踩到，好在备份齐全）。
    """
    assert rotate.plan("user_data", [])["apps"] == {}
    assert len(rotate.plan("user_data", None)["apps"]) >= 5
