# 2026-11-07 检索/健康重排：被替代门禁归档清单

本文件记录 r1130 全站重排中被**新契约门禁替代**而移出 `tests/` 的旧测试。
归档目录：`_scratch/archived_tests_2026-11-07/`（仍保留源码，便于追溯，不参与 pytest）。

替代关系：

| 归档测试 | 旧契约 | 新门禁 |
| --- | --- | --- |
| `test_r812_fold_no_resident_between.py` | 旧检索折叠 DOM（`srxProbeTool`/`srxOvHero`/`fltBtn`）与夹层判据 | `test_r1130_wave1_search_contract.py`（组合/筛选触发器两态 ≤1px、面板仅出现在正下方）+ `test_r1130_filter_continuity.py` |
| `test_r869_more_conditions_trigger_stays.py` | 已删除的「展开更多条件」二级入口 | 筛选条件全部进浮层：`test_r1130_wave1` + `test_r1130_filter_continuity` |
| `test_r978_edge_occlusion_geometry.py` | 旧检索工具行/筛选面板几何 | `test_r1130_wave1`（6 档零溢出、浮层贴合）+ `test_r1130_wave3_pages_contract` |
| `test_r990_filter_compact.py` | 旧内联筛选白墙 | `test_r1130_wave1`（筛选浮层 720–880px、航司搜索独占一行零相交） |
| `test_r996_search_ctrl_tier.py` | 旧 `#srxQ` 控件档位 | `test_r1130_wave3`（6 档零裁切/零重叠） |
| `test_r1014_search_row_columns.py` | 旧结果行四列网格 | `test_r1130_wave3`（全站 6 档布局普查） |
| `test_r1020_gallery_channel_rail.py` | 校准册旧横滚几何 | `test_r1130_wave3` |
| `test_r1040_narrow_text_fit.py` | 旧 320 检索文字裁切清单 | `test_r1130_wave3` |
| `test_r989_probe_flat_toolbar.py` | 旧探针工具行 | `test_r1130_wave1`（表单常驻、组合独立行、10 渠道 rail） |
| `test_r1103_probe_tools_compact.py` | 旧探针工具浮层挂载点 | `test_r1130_wave1` |
| `test_r806_filter_panel_alignment.py` | 旧筛选内衬/网格 | `test_r1130_wave1`（浮层头/命中/清除/关闭 + 航司搜索） |
| `test_r845_health_cards_fill_rows.py` | 旧 5 张诊断卡等高 | `test_r1130_wave2_health_contract.py`（10 行健康矩阵 + 诊断浮层） |
| `test_r999_combo_empty_state.py` | 旧组合空态入口文案 | `test_r1130_combo_states.py`（＋当前条件/已加入/已满 4 条） |
| `test_r1031_overview_ops_row.py` | 概览操作卡旧行式 | `test_r1130_wave3` |
| `test_r1033_cfg_approw.py` | App 渠道行旧两端对齐 | `test_r1130_wave4_channel_surfaces.py`（10 渠道全表面） |
| `test_r999_pace_facts_grid.py` | 节流面板旧 facts 网格 | `test_r1130_wave2`（节流 10 行/溯源 10 入口） |
| `test_r361_alignment.py` | 旧「探针会话」内联样式字面量 | `test_r1130_wave1`（控件几何真渲染） |
| `test_r294_webui.py` | 旧 `.dx` 日期片热区 | `test_r1130_wave3` |
| `test_r367_action_alignment.py` | 旧 `#healthcard .hrow` 四列字面量 | `test_r1130_wave2`（10 行 + 自检动作） |
| `test_r640_pacing_row_fits.py` | 旧节流行宽档 | `test_r1130_wave2` |
| `test_r808_header_selector_scope.py` | 旧裸 `header` 选择器锚点 | `test_r1130_wave3` |
| `test_r806_surfaced_cards_only.py` | 旧诊断卡底色判据 | `test_r1130_wave2`（诊断体默认折叠、展开为浮层） |
| `test_r880_named_toggles.py` | 旧探针默认关闭状态 | `test_r1130_wave1` + `test_r1130_filter_continuity`（默认 0 浮层） |

保留原则：所有**渠道宇宙、接口字段、导出、登录槽位、真实数据来源**门禁保持不动；仅归档「旧 DOM 选择器/旧像素字面量」类布局门禁。

后续补充归档（同一轮 r1130 全站重排）：

| 归档测试 | 旧契约 | 新门禁 |
| --- | --- | --- |
| `test_r1072_cfg_section_actions.py` | 配置分区「收起/展开」旧列宽字面量 | `docs/uitest.py` 配置分区开合 + `test_r1130_wave3_pages_contract.py` |
| `test_r1064_cfg_channel_entry_compact.py` | 配置渠道入口旧两份卡尺寸 | `test_r1130_wave4_channel_surfaces.py`（10 渠道全表面） |
| `test_r1070_cfg_pacing_fold.py` | 配置节流旧手风琴结构 | `docs/uitest.py` + `test_r1130_wave2_health_contract.py` |
| `test_r1059_cfg_pacing_desc_clamp.py` | 配置节流说明旧 `-webkit-line-clamp` | `test_r1130_wave3`（窄档零裁切） |
| `test_r1074_pace_flat_grid.py` | 节流 facts 旧白卡网格 | `test_r1130_wave2` + `test_r993_pace_tools_flat.py` |
| `test_r1027_pace_status_fit.py` | 节流状态行旧 grid-template-areas | `test_r1130_wave2` |
| `test_r998_trace_drawer.py` | 溯源旧 `.pace-detail` 限高 | `test_r1130_wave2`（溯源默认折叠、展开透明块） |
| `test_r1034_trace_btn_width.py` | 溯源旧按钮定宽 | `test_r1130_wave2` |
| `test_r1066_watch_chart_header.py` | 关注走势旧两行头 | `test_r1130_wave3`（6 档零重叠） |
| `test_r1067_radar_controls_row.py` | 雷达旧控件单行高 | `test_r1130_wave3` |
| `test_r1081_morefilters_select_row.py` | 旧筛选 3 列「更多条件」 | `test_r1130_wave1` + `test_r1130_filter_continuity` |
| `test_r999_cfg_field_30.py` | 配置字段旧 30/36 字面量 | `docs/uitest.py` coarse 36 地板 + `test_r1130_wave3` |
| `test_r999_cfg_login_dedup.py` | 登录卡旧重复要求文案 | `docs/uitest.py` 登录卡对齐/等宽 |
| `test_r873_scnote_inside_source_card.py` | 要求来源接入条**不渲染**（与新功能相反） | `docs/uitest.py`「来源接入板可见/三节点/路径词面」 |
| `test_r1012_more_pop_and_link_titles.py` | 旧「更多工具」DOM 字符串 | `test_r1130_wave1` + `test_r1130_filter_continuity` |
| `test_r300_webui.py` | 配置页旧 `.dchip .dx` 日期片热区采样（新结构无该节点） | `docs/uitest.py` 日期模式 + `test_r1130_wave3` |
| `test_r700_triggers_same_position.py` | 旧遍历所有 `aria-expanded`（含条件隐藏触发器，测试顺序污染） | `test_r1130_wave1`（组合/筛选两态同坐标）+ `test_r874`（镜像折叠钮） |
| `test_r1088_mirror_fold_icons.py` | 镜像折叠旧像素级契约（桌面 absolute/窄档 static），与 r874 触发钮同坐标冲突 | `test_r874_filter_edges_and_mirror_void.py`（折叠钮同坐标）+ `test_r941_app_chip_quality.py`（图标） |
| `test_r1044_search_swap.py`（渲染段） | 旧 320 三列网格像素排版；静态契约保留 | `test_r1130_wave1`（表单 6 档零溢出）+ 保留的静态 swap 用例 |
