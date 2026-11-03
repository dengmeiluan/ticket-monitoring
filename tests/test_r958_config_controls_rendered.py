# -*- coding: utf-8 -*-
"""r958：stealth/identity 9 个配置控件真渲染。

r601 只查源码落点；这里从真实入口进全局参数面板，断言控件可见、标签在、
面板真实展开；页面 console/pageerror 由 harness 在 teardown 统一兜底。
"""
from entry_mon_harness import page, srv, _goto  # noqa: F401


IDS = {
    "glbHum": "拟人化动作",
    "glbHumR": "拟人化轮数",
    "glbBch": "浏览器内核",
    "glbAndIdEn": "设备身份指纹",
    "glbAndRoot": "use_root",
    "glbAndReboot": "重启方式",
    "glbAndForce": "非模拟器也强制",
    "glbAndHideDev": "隐藏开发者选项",
    "glbAndKeep": "复用前台 App",
    "glbVendorApply": "应用 MuMu 官方设置",
    "glbCapArithmetic": "算数验证码",
    "glbCapText": "文字验证码",
    "glbCapOcrScale": "OCR 放大倍数",
}


def test_stealth_identity_controls_are_rendered(page):
    _goto(page)
    page.evaluate("switchView('cfg');showCfgPanel('globals')")
    page.wait_for_timeout(600)
    assert page.evaluate(
        "()=>{const p=document.getElementById('panel-globals');"
        "return !!p && p.offsetParent!==null;}"), "全局参数面板未展开"
    for cid, label in IDS.items():
        st = page.evaluate("""(id)=>{
          const e=document.getElementById(id);
          if(!e)return null;
          const c=e.closest('.glcell');
          const l=c?c.querySelector('.glab'):null;
          return {visible:e.offsetParent!==null,
                  label:l?l.textContent.trim():''};
        }""", cid)
        assert st and st["visible"], "%s 不可见：%r" % (cid, st)
        assert label in st["label"], "%s 标签缺失：%r" % (cid, st)
    # 数字控件必须挂范围校验（r606 的通用门禁也覆盖；这里钉住新增项）
    assert page.evaluate("()=>!!glbRangeOf('glbHumR')")
    # 可见还要真的写回：点击后 GLB.android.vendor.apply 必须翻转
    before = page.evaluate(
        "()=>!!(((GLB.android||{}).vendor||{}).apply)")
    page.click("#glbVendorApply")
    after = page.evaluate(
        "()=>!!(((GLB.android||{}).vendor||{}).apply)")
    assert after is (not before), "vendor.apply 勾选没有写回 GLB（%r→%r）" % (
        before, after)
    page.click("#glbVendorApply")
