# -*- coding: utf-8 -*-
"""r521：只在 config.yaml 里能改的参数，网页上必须看得见。

审计方法：把 `config.example.yaml` 的键与 `/api/config` 回读键做集合差，
再逐一确认「是否真被采集端消费」。结论：

  · 保存端**先读回整份 cfg 再改**（`safe_load` → `safe_dump`），
    所以未回读的键**不会被网页保存覆盖**——这条不是数据丢失缺陷；
  · 但 `session_max_days`（会话到期强制续期）、`max_concurrency`（并发上限）、
    `tls_impersonate`（浏览器指纹）、`login_desktop`（登录窗是否可见）
    在采集端真实生效，配置页却**一个控件都没有、值也不显示**。
    用户在网页上既不知道它们存在，改过也无从对照——「可观察/可配置」缺口。

做法：后端把这四个键回读；配置页加一块**只读**说明（键路径 + 当前值 + 作用），
不提供编辑控件（这些键改完需要采集端重载，网页热改会给人「已生效」的错觉）。
"""
import io
import re
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_backend_reads_the_file_only_keys_back():
    w = _w()
    i = w.index('elif self.path == "/api/config":')
    seg = w[i:i + 11000]
    # 精确键名：`"session_max_days_X"` 这种改名必须被抓到，
    # 子串匹配 `'"session_max_days"' in seg` 挡不住（负控实测全绿）。
    keys = set(re.findall(r'"([a-z_]+)":', seg))
    for k in ("session_max_days", "max_concurrency", "tls_impersonate",
              "login_desktop"):
        assert k in keys, \
            "/api/config 没有回读 %s（网页上无法显示它的当前值）" % k


def test_config_page_renders_editable_controls_instead_of_a_readonly_note():
    """r523 起这些键必须**可编辑**：只读说明块已按要求撤除。

    历史：r521 曾用 `glnote()` 只读列出它们（当时判断「改完要重载」），
    但用户明确要求「配置页不允许存在无法配置的项」，于是改成控件。
    这条契约随之反转——**不变量变成了「不许再退回只读」**。
    """
    w = _w()
    assert "glnote('仅可在 config.yaml 中修改" not in w,         "又退回了「只能改文件」的只读说明"
    for pk in ("glbSessMax", "glbMaxConc", "glbMua", "glbTls",
               "glbDbgDir", "glbLcd", "glbNearD", "glbLgd"):
        assert pk in w, "缺少控件 %s" % pk


def test_cadence_controls_exist_for_all_five_channels():
    w = _w()
    for p in ("qunar", "fliggy", "ctrip", "tongcheng", "tuniu"):
        assert "glbCad_'+p" in w or ("glbCad_" in w and p in w),             "缺少 %s 的节奏控件" % p
    assert "GLB.cadence=Object.assign" in w, "cadence 控件写不回 GLB"


def test_saving_web_config_does_not_drop_unlisted_keys():
    """前提核实：保存端先把磁盘 cfg 读回来再改，所以未回读的键不会丢。

    这条钉住「不要把上面的处理误当成数据丢失缺陷」——若哪天保存方式改成
    「用前端提交的整份结构覆盖」，未回读的键就会在用户保存时被静默抹掉。
    """
    w = _w()
    i = w.index('with open(st.config_path, encoding="utf-8") as _yf:')
    assert "safe_load" in w[i:i + 200], "没有解析磁盘配置"
    j = w.index('with open(st.config_path, "w", encoding="utf-8") as f:')
    assert "safe_dump(cfg, f" in w[j:j + 300], "没有把整份 cfg 写回"
    assert i < j, "先写后读——未回读的键会被抹掉"
