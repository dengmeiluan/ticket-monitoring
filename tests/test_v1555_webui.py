# -*- coding: utf-8 -*-
"""webui 回归（源码级钉死）：buildForm 钉钉渠道卡补闭合（div 栈
平衡）、kpi.clk 焦点环、Esc 关 toast、1920 宽屏断点联动、渠道字段七批
消费端（out 白名单/明细次行/CSV 四列）、demo 合成新字段、600s 轮聚类
注释如实化、内嵌 JS 语法 node --check 与 CSS 花括号平衡。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1555_webui.py -q
"""
import os
import re
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1555Pins:
    """webui.py 源码级钉死：改结构/词面/字段错一处即失败，源码钉模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _page():
        import webui as _w
        return _w.PAGE

    # ---- A div 平衡（buildForm 钉钉卡补闭合） ----------

    def test_page_div_balance(self):
        """PAGE 内 <div/</div 栈计数恒相等。2664 三元双分支各写一份开标签
        属假差异（运行时单份）；真实缺闭合的场景：ntfy/aliyun/serverchan
        三卡嵌进钉钉卡内部，foldCh 按 parentElement.dataset.ch 取键致折
        一连藏三。对账基线随结构演进维护：推送图床卡 +11 对、header 右区
        单行化 -2 对、版本失配刷新横幅 +1 对、邮件通道卡 +31 对；断服
        错误态帮手（_markStale 概览骨架落点）+1 对 = 319/319。"""
        page = self._page()
        o = len(re.findall(r"<div\b", page))
        c = len(re.findall(r"</div\b", page))
        assert (o, c, o - c) == (319, 319, 0)

    def test_dingtalk_card_closed_before_ntfy(self):
        """钉钉卡闭合补钉字面在位，且位于 ntfy 卡开标签之前（顺序钉死）。"""
        src = self._src()
        anchor = "</div><!-- 此闭合标签必须保留"
        assert anchor in src
        assert src.index(anchor) < src.index('data-ch="ntfy"')

    def test_body_open_div_single_ternary(self):
        """用户卡体开标签单标签三元：源码不再双计开标签（未来自动平衡
        扫描免误报）。"""
        src = self._src()
        assert '''+'<div style="'+(open?'padding:4px 16px 14px':'display:none')+'">';''' in src
        assert """+'<div style="padding:4px 16px 14px">':'<div style="display:none">';"""not in src

    # ---- B1 Esc 关 toast ----------

    def test_esc_closes_latest_toast(self):
        src = self._src()
        branch = ("const ts=document.querySelectorAll('#toasts .toast');"
                  "if(ts.length){ts[ts.length-1].remove();return;}")
        assert branch in src
        # 顺序：抽屉分支之后、比价/改期行分支之前（关最新一条先于收行）
        assert src.index(".fbar.open") < src.index(branch) < src.index("if(EXP){EXP=null;_hideXrows();}")

    # ---- B2 kpi.clk 焦点环 ----------

    def test_kpi_clk_focus_ring(self):
        """clk 整卡可点带 tabindex/role=link，收编全站 2px 蓝环组。"""
        src = self._src()
        assert "#chart:focus-visible,.kpi.clk:focus-visible{" in src
        assert ".kpi.clk:focus-visible{outline" not in src   # 未另立孤环，与全站同款

    # ---- B3 1920 宽屏断点 ----------

    def test_widescreen_breakpoint_1920(self):
        """≥1920 全站统一 1680 内容宽（wrap 1716）：任何视图/标签切换零
        位移。 骨架收口——旧「宽窄组+负 margin 突破+applyWide 总
        闸」机制（/55/56/57/59 五轮演进）在用户实拍三连图里暴露
        为每次切标签整页横移 198px、标题头右缘跳 180px=「页面抖动」实感
        （组内对齐 ≠ 跨组不跳），整体退役。"""
        src = self._src()
        assert src.count("min-width:1920px") == 2
        assert "min-width:1800px" not in src
        assert "@media(min-width:1920px){\n  canvas{height:clamp(280px,42vh,460px)}}" in src
        assert ".wrap{max-width:1716px}" in src
        assert "header{margin-left:0;margin-right:0}}" in src  # ≥1920 停出血
        assert "margin-left:-198px" not in src      # 负 margin 突破绝迹
        assert "applyWide" not in src               # 总闸退役
        assert ".wide{" not in src and ".wide," not in src
        assert '<header id="hdcard">' in src
        assert '<div class="ucard" id="opscard">' in src
        assert '<nav id="mainnav">' in src

    # ---- B4 role="link" 注释如实化 ----------

    def test_kpi_clk_comment_matches_role_link(self):
        src = self._src()
        assert 'role="link" 已删' not in src
        assert 'role="link"+tabindex="0"+Enter 键开' in src
        # 渲染处现实未变：role=link + tabindex + Enter 键开仍在
        assert 'tabindex="0" role="link"' in src

    # ---- C1 out 白名单七批键 ----------

    def test_out_whitelist_batch7_keys(self):
        src = self._src()
        for lit in (
            # 后走 _int_or_none 转写（空串/脏值→None 前端不占位）
            '"bridgeRate": _int_or_none(f.get("bridgeRate"))',
            '"cancelRate": _int_or_none(f.get("cancelRate"))',
            '"bizPrice": _int_or_none(f.get("bizPrice"))',
            '"planeAge": f.get("planeAge") or None',
            '"lcc": bool(f.get("lcc"))',
        ):
            assert lit in src, lit

    # ---- C2 明细次行段内扩展（不新增段） ----------

    @staticmethod
    def _subrow_segments(page):
        """取明细航班格次行段数组，括号/字符串感知计顶层段数。"""
        # audit：段间分隔 ' · '→' ｜ '（与段内 '·' 拉开两级），
        # 锚点随分隔符同步更新；容量红线语义不变。
        m = re.search(r"\$\{\[(.*?)\]\.filter\(Boolean\)\.join\(' ｜ '\)\}", page, re.S)
        assert m, "次行段数组锚点丢失"
        body = m.group(1)
        depth = 0
        instr = None
        n = 1
        for ch in body:
            if instr:
                if ch == instr:
                    instr = None
                continue
            if ch in ("'", '"', "`"):
                instr = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                n += 1
        return n

    def test_subrow_segment_capacity_14(self):
        """段数组容量 ≤14（曾段数超 UI 容量截断——回归红线）。
        七批字段只做段内扩展；八批 +1 段（transferTax 机建燃油，仍远
        低于容量红线）。"""
        assert self._subrow_segments(self._page()) == 14

    def test_subrow_segment_extensions(self):
        page = self._page()
        # 准点段：cancelRate 用 != null 判定（0% 是真值，勿用 truthy）
        assert "f.prate?'准点'+he(String(f.prate))+'%'+(f.cancelRate!=null?'·取消'+he(String(f.cancelRate))+'%':''):'" in page
        # 机型段：planeSize + 廊桥率 + 机龄（title 防跨渠道口径误读）
        assert ('f.planeSize?\'<span title="数据源：渠道连廊率/机龄">\'+he(f.planeSize)'
                '+\'·廊桥\'' in page) or ("f.planeSize?'<span title=\"数据源：渠道连廊率/机龄\">'+he(f.planeSize)" in page)
        assert "'·机龄'+he(String(f.planeAge))+'年'" in page
        # 主行 tag 槽：lcc 廉航徽标（与经停/直挂同位，空值不占位）
        assert '<span class="stoptag" title="廉价航空：中转常需重新值机、行李托运受限">廉航</span>' in page
        # bizPrice 不进次行：拼 labels title 尾（裸价形态兜底；
        # 词面随 bizCabin 源，存量行回退「公务」）
        assert "he(f.bizCabin||'公务')+'￥'+he(String(f.bizPrice))" in page

    # ---- C3 CSV 四列 ----------

    def test_csv_header_32_columns(self):
        page = self._page()
        m = re.search(r"const head=\[(.*?)\];", page, re.S)
        assert m, "CSV 列头锚点丢失"
        head = m.group(1)
        # +机建燃油（fliggy 中转行裸价补税，续
        # 五批「新字段进 CSV」惯例）；：+标签说明（qunar PC
        # labelNote 随 labels 配对，32 列）；+退改（qunar
        # returnFee/changeFee 双键，33 列）；+座椅倾斜（ctrip
        # seattilt 舱位物理参数，34 列，贴舱位码）；+儿童/婴儿（tuniu
        # childPrice/infantPrice 消费端补齐，35 列，表尾追加）
        assert head.count(",") + 1 == 35
        for col in ("'取消率'", "'廊桥率'", "'机建燃油'", "'高档舱'", "'廉航'"):
            assert col in head, col
        assert "'退改'" in head
        # 就近插位：取消率贴均延、廊桥贴机型体量、机建燃油贴廊桥率、
        # 标签说明贴权益标签（worker 渲染门同窗插位）；
        # 高档舱（bizPrice 语义=公务/头等最低参考价，词面随 bizCabin 源）
        assert head.index("'均延'") < head.index("'取消率'") < head.index("'中转'")
        assert (head.index("'机型体量'") < head.index("'廊桥率'")
                < head.index("'机建燃油'") < head.index("'高档舱'")
                < head.index("'廉航'") < head.index("'权益标签'")
                < head.index("'标签说明'") < head.index("'中转服务'"))

    def test_csv_row_values_aligned(self):
        page = self._page()
        # 取消率/廊桥率：!= null 才出 N%；公务舱：升舱差主口径（        # M 防呆：biz>行价才出 +￥，否则裸价），行价缺失裸价
        assert "(f.cancelRate!=null?f.cancelRate+'%':'')" in page
        assert "(f.bridgeRate!=null?f.bridgeRate+'%':'')" in page
        assert "(f.transferTax!=null?f.transferTax:'')" in page
        assert ("(f.bizPrice!=null?((f.price!=null&&f.bizPrice>f.price)"
                "?'+￥'+(f.bizPrice-f.price):(f.bizCabin||'公务')+'￥'+f.bizPrice):'')") in page
        assert "(f.lcc?'是':'')" in page

    # ---- C4 demo 合成 ----------

    def test_demo_batch7_fields_functional(self):
        from core.demo import _mk_detail
        fs = _mk_detail(random.Random(1), "ctrip", "2026-10-06", 1820)
        f0 = fs[0]
        assert f0["bridgeRate"] == 92
        assert f0["cancelRate"] == 3
        assert f0["bizPrice"] == 1820 + 840          # base+840，呈升舱差
        assert f0["cabinCode"] == "Y"
        assert f0["labels"] == "机上Wi-Fi"
        tuniu = _mk_detail(random.Random(2), "tuniu", "2026-10-06", 1940)
        assert tuniu[0]["cabinCode"] == "D"
        qunar = _mk_detail(random.Random(3), "qunar", "2026-10-06", 1820)
        assert not any("bizPrice" in f for f in qunar)  # 防演示有真机无

    def test_demo_batch7_fields_source_pins(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "core", "demo.py"), encoding="utf-8") as f:
            src = f.read()
        assert 'fs[0]["bridgeRate"] = 92' in src
        assert 'fs[0]["cancelRate"] = 3' in src
        assert 'fs[0]["bizPrice"] = base + 840' in src
        assert 'fs[0]["cabinCode"] = "Y"' in src
        assert 'fs[0]["cabinCode"] = "D"' in src

    # ---- C5 600s 轮聚类注释如实化 ----------

    def test_cluster_round_comment_honest(self):
        src = self._src()
        assert "无此形态，发生时回此注释" not in src      # 旧假设已被实测推翻
        assert "503s" in src
        assert "语义刻意保持" in src   # 420s 收口后挂账解除，两消费端语义差异注释仍在
        assert "曲线合并桶取窗口内最低价、列表 dedupe 只留最新行" in src

    # ---- D7 内嵌 JS 语法与 CSS 平衡 ----------

    def test_embedded_js_syntax_node_check(self):
        """抽出 PAGE 各 <script> 块跑 node --check（只解析不执行）——
        本批 A2 三元合并曾引入多余右括号被此检查捕获。"""
        if shutil.which("node") is None:
            sys.exit("node 不在 PATH：无法完成内嵌 JS 语法自验")
        blocks = [b for b in re.findall(r"<script>(.*?)</script>", self._page(), re.S)
                  if b.strip()]
        assert blocks, "PAGE 内未找到 <script> 块"
        for i, b in enumerate(blocks):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as f:
                f.write(b)
                path = f.name
            try:
                r = subprocess.run(["node", "--check", path],
                                   capture_output=True, text=True, timeout=60)
                assert r.returncode == 0, f"script 块 {i} 语法错误：{r.stderr[:400]}"
            finally:
                os.unlink(path)

    def test_embedded_css_brace_balance(self):
        styles = re.findall(r"<style>(.*?)</style>", self._page(), re.S)
        assert styles, "PAGE 内未找到 <style> 块"
        for i, css in enumerate(styles):
            assert css.count("{") == css.count("}"), f"style 块 {i} 花括号失衡"
