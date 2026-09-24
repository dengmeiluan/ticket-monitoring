# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v172_webui.py 模式；行为断言在
docs/uitest.py 补钉）。

（WebUI 交互完整性第五轮+布局美感第五轮；P0=0，P1=0，P2×3 全采纳，
五轮审计首次 P1 归零）：
 预览空数据错误文案指向不存在的按钮：「▶ 立即抓取」是产品改名前的
    旧词面（实际按钮 L1102「🔄 立即扫描一轮」，全页无「抓取」字样按钮）
    ——全新安装/库空时点「👁 预览推送」，空态教导指向不存在物=承诺失效。
    修法：L4425 err 文案与模块 docstring（L6，同根因）一并改「立即扫描一轮」。
 推送预览弹层三入口共用静态 aria-label「钉钉推送预览」：showLog/pushLog
    复用同一 #pvMask 只改 #pvTitle 可见标题，role=dialog 的读屏名与可见
    标题失配（实测 title=「📄 携程｜…轮日志」而 ariaLabel=「钉钉推送预览」）。
    修法：showLog/pushLog 各补 1 行 setAttribute（previewPush 保持现值）。
 明细行 📈（.tj）键位分裂：内联 onkeydown 只拦 Enter，Space 冒泡到
    数据行 tr 的 Enter||Space 处理器误开同班比价面板（真实按键实测
    EXP:true/xrowOpened:true，一键两义；role=button 的 Space 通道承诺
    未兑现）。修法：补 `||event.key===' '`（与 .hc/.pbar/#pvClose/明细行
    tr 的 Enter||Space 内联同式，Space=Enter 同义跳走势）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v173_webui.py -q
"""


class TestWebuiV173Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_p1_empty_payload_err_names_real_button(self):
        """：预览空数据教导指向真实按钮词面，旧词面全文件清零。"""
        src = self._src()
        assert 'err": "暂无本轮数据，先「立即扫描一轮」跑一轮"' in src, \
            "空态教导未指向「立即扫描一轮」（指向不存在按钮=教导失效）"
        assert "立即抓取" not in src, \
            "「立即抓取」旧词面残留（docstring/文案未跟产品改名）"

    def test_p2_dialog_aria_label_follows_entry(self):
        """：三入口开弹层时各自显式回设 aria-label（读屏名与可见
        标题一致；previewPush 不回设会被同会话先开的 showLog/pushLog
        留下上一入口的值——uitest 流程 showLog 先于预览实测抓回）。"""
        src = self._src()
        assert ("setAttribute('aria-label','渠道轮日志')" in src
                and "setAttribute('aria-label','推送记录')" in src
                and "setAttribute('aria-label','钉钉推送预览')" in src), \
            "弹层 aria-label 未随入口切换（读屏名与可见标题失配回潮）"
        assert 'aria-label="钉钉推送预览"' in src, \
            "previewPush 静态 aria-label 初始值丢失"

    def test_p3_tj_space_same_as_enter(self):
        """：.tj 内联键位 Enter||Space 同义（Space 冒泡误开比价回潮）。"""
        src = self._src()
        assert "onkeydown=\"if(event.key==='Enter'||event.key===' '){event" \
               ".preventDefault();event.stopPropagation();jumpRowTrend(" in src, \
            "📈 键位缺 Space 通道（冒泡到行级误开同班比价+role=button " \
            "Space 语义未兑现）"
