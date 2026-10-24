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
        错误态帮手（_markStale 概览骨架落点）+1 对、明细行 mmeta
        预置容器 +1 对、配置即时校验 verr 行内提示位 +1 对、推送通道
        健康区（pushhl 容器 + renderPushChannels 渲染模板）+4 对 = 325/325；r244 opscard .opsbtns 包裹层 +1 对 = 326/326；r248 单日期过期停采 dlab 徽标容器 +1 对 = 327/327；停用态空态卡（ucard hero + hicon）+2 对 = 329/329；明细档位图例补位行（.flgrow 行容器，自按钮行 span 提位独立成行）+1 对 = 330/330；r291 cfg 搜索零命中空态引导行（cfgEmpty 预置行）+1 对 = 331/331；图床卡三床化（GitHub 图库 repo/ghtoken/proxy 三行，旧图床服务行改版）+12 对 = 343/343；r319 特价监控卡（用户卡 D 区 5 个 srow 行 ×4 对）+20 对 = 363/363（同轮 glbProxy 为 glcell 调用非字面 div，计数零增）；r320 明细行属性筛选两行组 +2 对 = 365/365 + 概览特价雷达卡（ucard/uhead/spbody）+3 对、雷达 JS 渲染模板（容器+行）+2 对 = 370/370；r320 城市选择面板（citypanel/cp-search/cpbody 三静态容器 + JS 渲染模板 cp-sec/lhead/grid/cpNone 等）+10 对 = 380/380。"""
        page = self._page()
        o = len(re.findall(r"<div\b", page))
        c = len(re.findall(r"</div\b", page))
        # r325：城市面板「🌐 国际目的地」页签（cp-sec/lhead/grid 三容器）
        # +3 对；R34：scope 分 Tab 行（cfgScopeBar 容器）+1 对；
        # r366 探针查询行/渠道行/KPI 次级行 +1 对 = 993/993；
        # 后续并行 r326 对账至 391/391（含 cptabs 等后续增量）；
        # r339 双特性对账至 426/426（Bark 通道卡 chcard+4 srow、
        # 往返返程日期 chips 行 srow、渠道徽标 glab 增量）；
        # 日期行两段式（.dwrap/.dline）对账至 430/430；
        # r339g 启动级重启横幅（restartHint 预置位）+1 对 = 431/431；
        # r341 到达窗快捷挡行/glAbs 绝对路径行等 +15 对 = 446/446；
        # r339j 最长飞行时长行（srow+slab+sctl）+4 对 = 450/450；
        # r342 配置工作台：概览容器 + 配置 chrome + 重启中心五件 +
        # 日期双通道工具卡/航司选择/路径卡渲染模板 + 明细筛选摘要与
        # 预设行 + 范围/状态零命中空态行 = 508/508；r343 统一确认层
        # 五件 + 明细属性筛选 5 个 agrp = 518/518；r344 日期编排合并
        # 共享快捷行（每行 -1 对，去/返程两行） = 516/516；r345 双卡
        # 编辑器收为单编辑器模式条（每行再 -6 对，去/返程两行）= 504/504；
        # r346 移动端筛选结果 CTA +1 对 = 505/505；
        # r340 生产检索页静态骨架 + JS 渲染模板 +78 对 = 583/583；
        # r340b 原页镜像 + 三重对齐抽屉 + 校准册 +69 对 = 652/652；
        # r340c 主动探针表单 +8 对 = 660/660；r348 证据工作台/探针城市联想 +91 对 = 751/751；
        # v286 探针链路账本（路径行容器 + 渲染模板）+2 对 = 992/992；
        # r351 配置中心独立航班监控（路由/筛选/表单/列表/走势模板）+74 对 = 825/825；
        # r352 关注航班台/名册/轨迹/K线/试看/独立编排 +116 对 = 941/941；
        # r353 品牌层：总览关注卡代码行 monwatch-code +1 对、详情来源承运航司行 +1 对 = 943/943；
        # 总览关注卡容器（card/uhead/routes/list/empty）+5 对 = 948/948；
        # r354 价带 PEND 骨架 +1 静态 div = 949/949
        # r355 国际能力条（srx-capbar 容器）+1、配置航线城市联想双浮层
        # （rtFromDrop/rtToDrop）+2、健康/搜索语义容器 +2 = 954/954；
        # r357 矩阵完整分组提示（srx-cmpnote）+1 = 955/955
        # r357 关注数据预热的 cfgwatch-skel 骨架 +1 开/闭
        # r358 来源接入卡（srccap/uhead/scpath/3 scnode/scfoot）+7 对、
        # 登录卡停服说明 lgnote +1 对 = 964/964
        # r358b 检索矩阵窄屏卡片（srx-mxcards/srx-mxcard ×5 格）+7 对 = 971/971
        # r364 镜像截断提示 +1、r365 语义容器 +1 = 973/973
        # v284 组合探针静态骨架（#srxBatchWrap/.srx-batchbar/#srxBatchList）
        # +3 对、矩阵身份格 fname/fsub +1 对 = 977/977；v285 任务面板
        # （panel/sum/body/legs/evbar/events）+6 对、恢复条 +1 对 = 984/984
        # （运行期任务行/事件模板另计，不在 PAGE 字面）
        # goal 关注航线卡 4 对 + 共享曲线容器 + 整合树探针标记 = 1003/1003
        # P1 挑战票据卡（容器 + 卡头/元信息/动作模板）+7 对 = 1023/1023
        # 渠道页面矩阵（配置区/探针入口/渲染模板）+9 对 = 1032/1032
        # 特价矩阵 + 特价雷达独立页签/卡片 + 每条特价直达 +11 对 = 1043/1043
        # 检索台特价雷达面板/能力矩阵 +8 对 = 1051/1051
        # 渠道台重构（渠道带/链接芯片替代平铺矩阵）-3 对 = 1048/1048
        # 飞猪 PC/H5 双域登录说明条 +1 对 = 1049/1049
        # 渠道登录/渠道入口分区（新增 sec-chlinks 卡壳）+1 对 = 1050/1050
        # 六槽位登录卡（Fliggy 双泳道/槽位壳）+5 对 = 1055/1055
        # 飞猪双端登录弹层（遮罩/弹层/双泳道模板）+13 对 = 1068/1068
        # 用户内关注航班 + 特价雷达查询卡（表单/状态/结果容器）+34 对 = 1102/1102
        # r368 用户卡 D/E：关注内联宿主 + 雷达城市/预览/官方入口容器
        # 关注面板寄存容器不增对；v294 雷达监控日历/趋势/低价航班卡 +14 对、
        # 渠道健康诊断卡 +15 对、检索大块折叠（details 包裹不改 div 字面）、
        # 探针入口徽标 +1 对 = 1148/1148
        # v295 诊断卡动作行 +1 对 = 1149/1149；详情来源卡「采集入口」
        # 行 +1 对 = 1150/1150；雷达图表隐藏数据表包裹层 +1 对 = 1151/1151
        assert (o, c, o - c) == (1151, 1151, 0)

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
                  "if(ts.length){ts[ts.length-1].remove();}")
        assert branch in src
        # 顺序：抽屉分支之后、比价/改期行分支之后（toast 只读即点即关，
        # 驻留期不得挡内容态回收——序在展开行前曾 return 早退，展开行
        # 要等 toast 自然消散才能收）；展开清行串随持久化收口带 saveUI
        # （r220 affordance 轮起同路补 _ariaOff() 态回写，落盘语义不变）
        assert src.index(".fbar.open") < src.index(
            "if(EXP){EXP=null;_hideXrows();_ariaOff();saveUI();}") < src.index(branch)

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
        # r301 F-1 后仅 header 停出血档仍锚 1920（canvas 高度档改
        # 随 wrap 封顶同拍 1866 坡带）
        assert src.count("min-width:1920px") == 1
        assert "min-width:1800px" not in src
        # r301 F-1 双段：42vh 专带禁复活（1920 整点跳变源）+ 实效档
        # 在场（1866 起坡连续函数，封顶语义不变）
        assert "clamp(280px,42vh,460px)" not in src
        assert ("@media(min-width:1866px){\n  canvas{height:min(460px,"
                "calc(360px + (100vw - 1866px)*0.6))}}") in src
        # 硬顶退役改双段：禁复活（硬顶形态=+30% 宽度跳变源）+实效档
        # 在场（渐进上限 min(1716px,max(1180px,92vw)) 于 1280 渐进带
        # 统一承载，≥1920 封顶语义不变）
        assert ".wrap{max-width:1716px}" not in src
        assert ".wrap{max-width:min(1716px,max(1180px,92vw))}" in src
        assert "header{margin-left:0;margin-right:0}}" in src  # ≥1920 停出血
        # r280 P3-1 定谳备案：停出血后 h1（卡内文字轴）与 nav（盒轴线）
        # 差 18px 属「盒内呼吸 vs 盒轴通线」的结构差，非齐线破口——
        # nav 必须留在盒轴（下方 all-of-1920 钉组锁通线），禁加缩进
        assert "#mainnav{margin-left:18px}" not in src
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
        """段数组容量红线（曾段数超 UI 容量截断——回归红线）。
        七批字段只做段内扩展；八批 +1 段（transferTax 机建燃油）；
        r325 +1 段（intl 含税词，条件段——国内行 join 滤空不占位，
        容量口径按源码段位计）；R45 +1 段（codeShare 共享航班，
        条件段）= 16；r339j +1 段（托运 kg 命中片，bagkg 门开着才
        渲染的条件段）= 17。"""
        assert self._subrow_segments(self._page()) == 17

    def test_subrow_segment_extensions(self):
        page = self._page()
        # 准点段：cancelRate 用 != null 判定（0% 是真值，勿用 truthy）
        assert "f.prate?'准点'+he(String(f.prate))+'%'+(f.cancelRate!=null?'·取消'+he(String(f.cancelRate))+'%':''):'" in page
        # 机型段：planeSize + 廊桥率 + 机龄（title 防跨渠道口径误读）；
        # r313 R2-1 起 span 挂 .nw（CJK 词组断词孤字根治，与同容器
        # 机场段同律——.nw 全局工具类声明生效，td .stl.nw 是压制豁免
        # 档；uitest r313 stl orphan 行为钉锁三窄带实效）；
        # r329 起 title 前缀机型细名（plane 三端收口：条件前缀，
        # 无机型行 title 原样）；r339 起二段机型/体量同段并入
        # （title 二段注记 + 词面「·二段X」并列，中转行全程机型判断）
        assert ("(f.plane||f.planeSize)?'<span class=\"nw nw-keep\"" in page
                or "f.planeSize?'<span class=\"nw nw-keep\"" in page)
        assert ("srxPlaneIcon(f.plane||f.planeSize)+he(f.plane||f.planeSize)" in page
                or "srxPlaneIcon(f.plane||f.planeSize)+he(f.planeSize)" in page)
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
        # childPrice/infantPrice 消费端补齐，35 列，表尾追加）；
        # +准点率（ctrip prate 决策字段，36 列，贴取消率）；
        # +托运额（ctrip pid 数字托运额与 qunar/tongcheng baggage
        # 同键，37 列，贴直挂）；+手提额（ctrip pid 孪生家族，38 列，
        # 贴托运额）；批内四键表尾追加：航程/航司码/公布运价/实际承运
        # （42 列）；r254 +改期公务（tongcheng trendBiz 高档舱改期日历
        # 价，贴改期最低，43 列）；r268 +周边特价（fliggy J_Nearby
        # 周边城市特价，_nb_txt 词面单源，表尾追加，44 列）；r269
        # +往返推荐（fliggy J_RoundRecommend，_rt_txt 词面单源，
        # 表尾追加，45 列）；r51 +税费（国际行 tax 税费构成，
        # 贴价格——「含税￥N」口径的构成列，46 列）；v295 +采集入口/
        # 证据级别（路径级溯源，贴渠道，48 列）
        assert head.count(",") + 1 == 48
        assert "'税费'" in head
        for col in ("'取消率'", "'廊桥率'", "'机建燃油'", "'高档舱'", "'廉航'",
                    "'准点率'", "'托运额'"):
            assert col in head, col
        assert "'退改'" in head
        # 就近插位：准点率贴取消率、取消率贴均延、廊桥贴机型体量、
        # 机建燃油贴廊桥率、标签说明贴权益标签（worker 渲染门同窗插位）；
        # 高档舱（bizPrice 语义=公务/头等最低参考价，词面随 bizCabin 源）
        assert (head.index("'均延'") < head.index("'准点率'")
                < head.index("'取消率'") < head.index("'中转'"))
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
