# -*- coding: utf-8 -*-
"""webui 回归（源码级钉死）：审计 P1×2 + P2×8。

 用户卡「● 未保存」徽标显示复位值、 改期胶囊 .tg 触控热区；
 /api/state 304 路径 body/etag 同锁快照、 mkact 内联 onkeydown
不双绑、 挡位 chips 原位更新保焦点、 buildChips 空选不回填、
 卡头字段转义、 行指纹去引号、 CSS 死代码清退、 灰点
令牌化。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1558_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1558Pins:
    """webui.py 源码级钉死（同 test_v1553_webui.py 模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- 未保存徽标 ----------

    def test_udirty_badge_visible_when_dirty(self):
        """内联 display 空串回落样式表仍被 .udirty{display:none} 压死，
        复位值必须显式 inline-block（.uhead2 flex 内渲染无差）。"""
        src = self._src()
        assert ".udirty{display:none}" in src          # 默认隐藏保留
        assert "el.style.display=d?'inline-block':'none';" in src
        assert "el.style.display=d?'':'none'" not in src   # 旧撕裂复位值清零

    # ---- 改期胶囊触控热区 ----------

    def test_tg_touch_hotzone(self):
        """本体 ~19px 低于 36px 触控基准；::after 全宽生效（透明无视觉差），
        纵向 -9px 外扩、横向只 -4px 不吃同行链接/行点击。"""
        src = self._src()
        assert ".tg::after{content:'';position:absolute;inset:-9px -4px}" in src
        assert "transition:border-color .15s;position:relative}" in src  # 本体定位锚

    # ---- 304 路径 ETag 撕裂 ----------

    def test_state_snap_paired_read(self):
        """body/etag/gz 必须同锁成对读取：重建线程锁内 body→etag 两步
        落位，请求线程裸读两次可拿旧 body 配新 etag 下发 200，客户端
        按新 etag 落陈旧缓存后被 304 粘死。"""
        src = self._src()
        assert "_STATE_LOCK = threading.RLock()" in src    # 快照读取重入 _latest_state
        assert "def _latest_state_snap():" in src
        # 两段式：_latest_state 先无锁触发/等待重建（锁内等待与
        # 构建线程发布段互等死锁，CI uitest 实锤），三元组同锁读齐不变量保持
        assert (
            "_latest_state()\n    with _STATE_LOCK:\n"
            "        body = _STATE_CACHE[\"body\"]" in src
        )
        assert "body, etag, gz = _latest_state_snap()" in src
        assert "_latest_state_body" not in src             # 旧裸读入口清零

    # ---- mkact 双绑 ----------

    def test_mkact_skips_inline_onkeydown(self):
        """模板自带内联 onkeydown（.hc/.pbar/#pvClose）不再叠加监听——
        一次 Enter 曾连发两个相同 /api/logtail。"""
        assert "if(el.getAttribute('onkeydown'))return;" in self._src()

    # ---- 挡位 chips 焦点 ----------

    def test_buildwinsel_inplace_update(self):
        """WINS 恒定：子节点齐时原位翻 on 类，不重建节点——table 每拍
        整组 innerHTML 重建曾把刚点按/回车的 .schip 换掉焦点丢回 body。"""
        src = self._src()
        assert "want.some((w,i)=>have[i]!==w)" in src
        assert "c.classList.toggle('on',c.dataset.w===cw)" in src

    # ---- 渠道空选回填 ----------

    def test_platchips_empty_selection_stable(self):
        """空集=全部是用户显式选择（_platsInit），10s 轮询 buildChips
        不得回填全亮；重置/恢复路径语义不回退。"""
        src = self._src()
        assert "_platsInit:false" in src                                   # FLT 声明
        assert "if(keep.length||FLT._platsInit){FLT.plats=new Set(keep);FLT._platsInit=true;}" in src
        assert "FLT.plats=new Set();FLT._platsInit=false;" in src          # resetFlt 回全选语义
        assert "FLT.plats=new Set(j.plats);FLT._platsInit=true;" in src    # restoreUI 显式选择

    # ---- 卡头转义 ----------

    def test_ucard_head_escaped(self):
        """与同函数用户 pills 的 he 纪律对齐。"""
        src = self._src()
        assert "${he(x.name)}</span>" in src
        assert '<span class="uroutes">${he(x.routesTxt)}</span>' in src

    # ---- 行指纹注入面 ----------

    def test_row_fingerprint_sanitized(self):
        """k 含渠道自由文本（trans/cross），构造点去引号/尖括号；
        he 在单引号 JS 上下文会因实体解码还原引号反而无效。"""
        assert ".replace(/[\"'<>&]/g,'_')" in self._src()

    # ---- CSS 死代码 ----------

    def test_dead_css_removed(self):
        src = self._src()
        assert ".calcell.none" not in src      # renderCal 只产 calcell/best/link
        assert "btn2 ical" not in src          # 类无规则无消费

    # ---- 灰点令牌 ----------

    def test_pill_dot_tokenized(self):
        src = self._src()
        assert "93a3b4" not in src             # 亮暗同值硬编码清零（含注释）
        assert "border-radius:50%;background:var(--mut);flex:none}" in src