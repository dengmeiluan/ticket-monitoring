# -*- coding: utf-8 -*-
"""r1063 T316：提交完整性守卫——今晚每处修复的关键标记必须在树里。

由来：我用"按 hunk 分批暂存"避开并行会话的未提交改动，但 hunk 会被拆开，
**丢掉其中几行不会报错**。T250 的后半段（PC 槽位把 `"detail"/"verified_at"/"page_ok"`
改成读 `_pv`）就是这么丢的：本地被并行改动掩盖，CI 才红。

本用例直接读仓库文件（CI 里就是提交内容），逐条对账"该在的东西在不在"。
如果哪天重命名/重构，改这里的标记即可——它守的是"别静默丢改动"。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHECKS = [
    # —— 登录 / 核验（issue #15） ——
    ("webui.py", '_pv = dict(_SLOT_VERIFY.get(key)', "PC 槽位读核验结果"),
    ("webui.py", '"verified_at": _pv.get("at", "")', "PC 槽位暴露核验时间"),
    ("webui.py", '"detail": _pv.get("detail", "")', "PC 槽位暴露核验说明"),
    ("webui.py", '"page_ok": _st == "page_ok"', "PC 槽位 page_ok 标志"),
    ("webui.py", "classify_text(body, page_url, ignore_url=True)",
     "核验忽略 URL 启发式（否则永远判需登录）"),
    ("webui.py", "_surface_detail_ok", "端面明细可用判定"),
    ("webui.py", "detail_ok 抬成 available", "detail_ok 抬成 available"),
    ("webui.py", "_State.cfg = _live_cfg", "面板保存后同步配置快照"),
    # —— 升级 / 观测 / 建议 ——
    ("webui.py", "/api/update/check", "检查更新接口"),
    ("webui.py", "/api/update/apply", "一键升级接口"),
    ("webui.py", "/api/insight", "诊断视图接口"),
    ("webui.py", 'data["distance_advice"]', "距离建议进载荷"),
    ("webui.py", "advice_distance_min_n", "建议阈值可配"),
    ("webui.py", "srxDistJump", "建议可跳转"),
    ("webui.py", "PATH_HINT", "通路口径提示"),
    ("webui.py", "_updateLine", "更新提示行"),
    ("webui.py", "insightBox", "诊断视图容器"),
    # —— 采集侧 ——
    ("crawlers/challenge.py", "ignore_url", "classify_text 支持 ignore_url"),
    ("crawlers/app_zhixing.py", "dialog_open", "日历限频后明细自开弹层"),
    ("crawlers/app_zhixing.py", "_dump_detail_fail", "明细失败取证"),
    ("crawlers/app_zhixing.py", "_route_intl", "国际标记（不计连败）"),
    ("crawlers/app_zhixing_nav.py", "_reopened", "找不到格则重开弹层"),
    ("crawlers/app_zhixing_nav.py", "1300, 450, 500",
     "日历滚动方向（上划看更早）"),
    ("crawlers/tongcheng.py", "_today_override", "窗历今天接缝"),
    # —— 工具 / 核心 ——
    ("core/update.py", 'while rel.startswith("./")', "_skip 归一化不用 lstrip"),
    ("tools/verify_release_assets.py", 'while low.startswith("./")',
     "发布包禁止项归一化"),
    ("core/advise.py", "def distance_advice", "距离建议实现"),
]


def test_all_tonight_fixes_are_present():
    missing = []
    for path, mark, desc in CHECKS:
        p = os.path.join(ROOT, path)
        try:
            src = io.open(p, encoding="utf-8").read()
        except OSError:
            missing.append("%s 不存在" % path)
            continue
        if mark not in src:
            missing.append("%s 缺 %r（%s）" % (path, mark, desc))
    assert not missing, "提交里缺了今晚的修复片段（分批暂存丢过）：\n  " + \
        "\n  ".join(missing)
