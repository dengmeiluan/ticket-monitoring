# -*- coding: utf-8 -*-
"""STEALTH_JS 的补齐层：把「一眼是自动化」之外的高熵特征也抹平。

为什么不直接改 ``crawlers/base.py::STEALTH_JS``
-----------------------------------------------
``tests/test_qunar_honesty.py`` 把「stealth 开 → 恰好 1 个 init script」钉成
了契约（可关、可审计）。往 ``_browser_context`` 里再加一次
``add_init_script`` 会直接破约。所以这里提供**纯函数**，由 base.py 把返回的
片段**拼进同一个脚本**：契约不变（仍然 1 个脚本），覆盖面变大。

为什么这些点值得补（按被风控利用的频率排）
------------------------------------------
1. **WebRTC 内网 IP 泄漏**（最高优先级）：Chromium 的 ICE 候选里带本机
   ``192.168.x.x`` / ``10.x``。你挂着代理让出口 IP 在另一个省，页面却发
   现内网网段与 ``rtc.local.ip``——这是「代理/多账号」最硬的一条证据。
   国内票务风控（同程/去哪儿用过类似判定）会直接降档。
2. **AudioContext 指纹**：headless 的 ``OfflineAudioContext`` 输出与真机
   存在稳定差异，且**跨 session 完全一致**，是绝佳的追踪锚点。给一个由
   profile seed 派生的固定微扰，等于把「机器指纹」变成「这台假设备」。
3. **enumerateDevices 数量**：headless 常返回 0 个设备，真机至少有一套
   扬声器/麦克风。
4. **chrome.* 子对象**：真实 Chrome 有 ``chrome.app/csi/loadTimes``；
   只塞 ``{runtime:{}}`` 的假对象在 ``Object.keys`` 下就露了。
5. **screen.orientation / outerWidth**：headless 的 ``outerWidth`` 等于
   ``innerWidth``（没有浏览器边框），真机差 70–90px。
6. **native toString**：被 JS 改写的 getter 直接 ``toString()`` 会打印出
   源码；补一层 ``[native code]`` 伪装。

失败一律吞掉：任何一段抛异常都不能让整页脚本不执行（后面的段仍然有效）。
"""


# ---------------------------------------------------------------------------
# JS 片段
#
# 占位符刻意用 __EXT_*__ 前缀，与 base.STEALTH_JS 的 __X__ 区分，
# 便于测试独立核对「有没有残留未替换」。
# ---------------------------------------------------------------------------
EXTRA_JS = r"""
/* ===== tm stealth ext: web / audio / devices / chrome / screen ===== */
(() => {
  const SEED = __EXT_SEED__;
  const W = __EXT_SW__, H = __EXT_SH__;
  const MOBILE = __EXT_MOBILE__;
  const patched = [];
  const markNative = (fn, name) => {
    try {
      Object.defineProperty(fn, '__tmNative', {value: 1, enumerable: false});
      if (name) { Object.defineProperty(fn, 'name', {value: name}); }
      patched.push(fn);
    } catch (e) {}
    return fn;
  };

  /* ---- 1. WebRTC：过滤带内网地址的 ICE 候选（代理场景最关键的一条） ---- */
  try {
    const RTC = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    const PRIVATE = /(^|[\s:])(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/;
    const isLeaky = (cand) => {
      if (!cand) return false;
      const s = String(cand);
      if (!/typ (host|srflx|relay)/i.test(s)) return false;
      return PRIVATE.test(s);
    };
    if (RTC) {
      const OrigRTC = RTC;
      const Wrapped = function (cfg, ...rest) {
        const c = Object.assign({}, cfg || {});
        if ('iceCandidatePoolSize' in c) { c.iceCandidatePoolSize = 0; }
        return new OrigRTC(c, ...rest);
      };
      markNative(Wrapped, 'RTCPeerConnection');
      Wrapped.prototype = OrigRTC.prototype;
      for (const k of ['generateCertificate', 'toString']) {
        try { Wrapped[k] = OrigRTC[k]; } catch (e) {}
      }
      try {
        const proto = OrigRTC.prototype;
        const origAdd = proto.addEventListener;
        proto.addEventListener = markNative(function (type, fn, ...r) {
          if (type === 'icecandidate' && typeof fn === 'function') {
            const wrapped = function (ev) {
              try {
                if (ev && ev.candidate && isLeaky(ev.candidate.candidate)) return;
              } catch (e) {}
              return fn.apply(this, arguments);
            };
            return origAdd.call(this, type, wrapped, ...r);
          }
          return origAdd.call(this, type, fn, ...r);
        }, 'addEventListener');
      } catch (e) {}
      try {
        Object.defineProperty(window, 'RTCPeerConnection',
          {value: Wrapped, configurable: true, writable: true});
        if (window.webkitRTCPeerConnection) {
          Object.defineProperty(window, 'webkitRTCPeerConnection',
            {value: Wrapped, configurable: true, writable: true});
        }
      } catch (e) {}
    }
  } catch (e) {}

  /* ---- 2. AudioContext：seed 固定的微扰（跨 session 稳定 ≠ 空白） ---- */
  try {
    const bias = ((SEED % 11) - 5) * 1e-7;
    const AB = window.AudioBuffer && AudioBuffer.prototype;
    if (AB && AB.getChannelData) {
      const orig = AB.getChannelData;
      AB.getChannelData = markNative(function (ch) {
        const arr = orig.call(this, ch);
        try {
          for (let i = 0; i < arr.length; i += 1997) {
            arr[i] = arr[i] + bias;
          }
        } catch (e) {}
        return arr;
      }, 'getChannelData');
    }
    const AN = window.AnalyserNode && AnalyserNode.prototype;
    if (AN && AN.getFloatFrequencyData) {
      const orig = AN.getFloatFrequencyData;
      AN.getFloatFrequencyData = markNative(function (arr) {
        orig.call(this, arr);
        try {
          for (let i = 0; i < arr.length; i += 1013) {
            arr[i] = arr[i] + bias * 1000;
          }
        } catch (e) {}
        return arr;
      }, 'getFloatFrequencyData');
    }
  } catch (e) {}

  /* ---- 3. enumerateDevices：headless 常为 0，补一套「普通办公机」 ---- */
  try {
    const md = navigator.mediaDevices;
    if (md && md.enumerateDevices) {
      const orig = md.enumerateDevices.bind(md);
      md.enumerateDevices = markNative(function () {
        return orig().then((list) => {
          if (list && list.length) return list;
          const mk = (kind, label, id) => ({
            kind, label, deviceId: id, groupId: 'tm-g-' + id,
            toJSON() { return this; }
          });
          return MOBILE ? [
            mk('audioinput', 'Built-in Microphone', 'tm-a-in'),
            mk('audiooutput', 'Built-in Speaker', 'tm-a-out'),
            mk('videoinput', 'Back Camera', 'tm-v-back')
          ] : [
            mk('audioinput', 'Microphone (Realtek(R) Audio)', 'tm-a-in'),
            mk('audiooutput', 'Speakers (Realtek(R) Audio)', 'tm-a-out')
          ];
        });
      }, 'enumerateDevices');
    }
  } catch (e) {}

  /* ---- 4. chrome.* 子对象：真 Chrome 有，只有 runtime 就露 ---- */
  try {
    if (!MOBILE) {
      const c = window.chrome || (window.chrome = {});
      if (!c.runtime) { c.runtime = {}; }
      if (!c.app) {
        c.app = {
          isInstalled: false,
          InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'},
          RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'},
          getDetails: function () { return null; },
          getIsInstalled: function () { return false; },
          runningState: function () { return 'cannot_run'; }
        };
      }
      if (!c.csi) {
        c.csi = function () {
          return {onloadT: Date.now(), startE: Date.now(), pageT: 1000, tran: 15};
        };
      }
      if (!c.loadTimes) {
        c.loadTimes = function () {
          const t = Date.now() / 1000;
          return {
            requestTime: t - 0.4, startLoadTime: t - 0.35,
            commitLoadTime: t - 0.2, finishDocumentLoadTime: t - 0.1,
            finishLoadTime: t - 0.05, firstPaintTime: t - 0.15,
            firstPaintAfterLoadTime: 0, navigationType: 'Other',
            wasFetchedViaSpdy: true, wasNpnNegotiated: true,
            npnNegotiatedProtocol: 'h2', wasAlternateProtocolAvailable: false,
            connectionInfo: 'h2'
          };
        };
      }
    }
  } catch (e) {}

  /* ---- 5. screen.orientation / outerWidth / hasFocus ---- */
  try {
    if (screen.orientation) {
      const o = screen.orientation;
      Object.defineProperty(o, 'type', {get: () => MOBILE ? 'portrait-primary' : 'landscape-primary', configurable: true});
      Object.defineProperty(o, 'angle', {get: () => 0, configurable: true});
    }
    Object.defineProperty(window, 'outerWidth', {get: () => W, configurable: true});
    Object.defineProperty(window, 'outerHeight',
      {get: () => H + (MOBILE ? 0 : 87), configurable: true});
    Object.defineProperty(window, 'screenX', {get: () => 0, configurable: true});
    Object.defineProperty(window, 'screenY', {get: () => 0, configurable: true});
    document.hasFocus = markNative(function () { return true; }, 'hasFocus');
  } catch (e) {}

  /* ---- 6. Notification 默认权限（headless 可能是 denied） ---- */
  try {
    if (window.Notification) {
      Object.defineProperty(Notification, 'permission',
        {get: () => 'default', configurable: true});
    }
  } catch (e) {}

  /* ---- 7. 被改写函数的 toString 伪装成 [native code] ---- */
  try {
    const origToString = Function.prototype.toString;
    const fake = function toString() {
      try {
        if (this && this.__tmNative) {
          const name = this.name || 'anonymous';
          return 'function ' + name + '() { [native code] }';
        }
      } catch (e) {}
      return origToString.call(this);
    };
    Object.defineProperty(Function.prototype, 'toString',
      {value: markNative(fake, 'toString'), configurable: true, writable: true});
  } catch (e) {}
})();
"""


def extra_js(fp: dict) -> str:
    """返回已替换占位符的扩展脚本；任何异常返回空串（不能拖垮主脚本）。

    ``fp`` 用 ``BaseCrawler.fingerprint()`` 的既有字段（ua/viewport/seed/
    is_mobile），**不新增键**——``test_r394`` 钉死了那个字段集。
    """
    try:
        fp = fp or {}
        vp = fp.get("viewport") or {}
        mobile = bool(fp.get("is_mobile"))
        width = int(vp.get("width") or (390 if mobile else 1366))
        height = int(vp.get("height") or (844 if mobile else 900))
        seed = int(fp.get("seed") or 0)
        js = EXTRA_JS
        for k, v in (
                ("__EXT_SEED__", str(seed)),
                ("__EXT_SW__", str(width)),
                ("__EXT_SH__", str(height)),
                ("__EXT_MOBILE__", "true" if mobile else "false")):
            js = js.replace(k, v)
        return js
    except Exception:
        return ""


def launch_args(fp: dict) -> list:
    """启动参数：只补充「不改行为、只关旁路」的几项。

    ``--force-webrtc-ip-handling-policy=disable_non_proxied_udp``：让 WebRTC
    只走代理 UDP（没有代理时不产生候选），从源头掐掉内网 IP 泄漏。这是
    Chrome 官方支持的策略开关，不影响页面功能（票务站不用 WebRTC）。
    """
    if not (fp or {}).get("stealth"):
        return []
    return [
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--enforce-webrtc-ip-permission-check",
        "--disable-features=WebRtcAllowInputVolumeAdjustment",
    ]


def channel(config: dict) -> str:
    """可选：用系统真 Chrome 而不是 Playwright 自带的 Chromium。

    默认空（保持现状，不改变任何既有行为）。为什么值得开：自带 Chromium
    与真 Chrome 在字体、编解码、GPU 白名单、``sec-ch-ua`` 全版本串上仍有
    差异，风控侧拿「Chromium 特征 + Chrome UA」就能配成一条矛盾。
    配置：``crawler.browser_channel: chrome``。
    """
    if not isinstance(config, dict):
        return ""
    return str(config.get("browser_channel") or "").strip()
