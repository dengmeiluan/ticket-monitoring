# -*- coding: utf-8 -*-
"""r261 WebUI 测试：MM-DD→MM/DD 词面单源收口（audit P3-1）+
监听地址 ♻ 启动级标注（audit P3-2）。"""
from webui import PAGE


def test_dslash_single_source():
    """日期短标词面单源：dSlash helper 在案，裸内联换装写法零残留
    （r260 词面统一案的内联存量收口——裸表达式残留是词面漂移温床）。"""
    assert 'function dSlash(' in PAGE
    # dSlash 定义内两处（YYYY-MM-DD 长形态 + 协议 MM-DD 短形态各一）
    assert PAGE.count("replace('-','/')") == 2, (
        "MM→斜杠换装必须收敛进 dSlash 单源（Date 解析的 replace(/-/g,'/')"
        " 不在此列）")


def test_dslash_consumed_at_audit_points():
    """审计 P3-1 三处残留消费点换装：改期微图柱 title、轴标、
    日历格悬停 tip（格面已换而悬停仍旧词面=同簇双格式）。"""
    assert 'he(dSlash(p[0]))' in PAGE, "改期柱 title 仍裸 MM-DD"
    assert 'he(dSlash(tg[0][0]))' in PAGE, "改期轴标首仍裸 MM-DD"
    assert 'he(dSlash(cur))' in PAGE, "改期轴标出发日仍裸 MM-DD"
    # 日历悬停 tip 的日期词面走 dSlash（tip 拼接基换装）
    assert 'const ds=dSlash(d)' in PAGE
    assert "ds+' 直飞最低" in PAGE


def test_host_hint_startup_badge():
    """审计 P3-2：「监听地址」重启生效项在 🔥 段头下须挂 ♻ 启动级
    视觉家族（与 ♻ 只读三件同族），段头「保存即热生效」不再与
    hint「重启生效」无标冲突。"""
    assert '· ♻ 重启生效' in PAGE
