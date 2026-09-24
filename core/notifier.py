"""消息推送：钉钉群机器人（加签） / Server酱（sct.ftqq.com）/ SMTP 邮件
（163/QQ 免费邮箱授权码）/ Windows 系统弹窗"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re as _re
import smtplib
import time
import urllib.parse
import urllib.request
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Optional

import httpx

from .alerter import TIER_EMOJI, TIER_FULL, TIER_TRANSCRIBE

# 强提醒通道 emoji 档位点转词表：ntfy/aliyun(_alert_body) 与
# WinToast(_plain) 共用此单源，勿再手抄；词面与 core.alerter.gap_txt
# 同律（🎯=真达标）——转写词与建议行在同条消息并存，两词面曾打架。
# 双轨备案（推送审校 P1-3）：达标标题/正文头用「达标/已达标」
# （口径词=alert_threshold 命中），四档档位词「真达标」（档位词）——
# 语义不同轴有意并存，改档位词勿动标题口径词，反之亦然。
# 改挂 alerter._TIER_TABLE 投影（词面单源收编，别名保留同名
# 防 test_v1553_regress 断言破裂）：三档键序显式防 over/fall 空串
# 混入转写表；🔥=命中非价格档（语义不同轴）留字面
_EMOJI_TIER_WORDS = (tuple((TIER_EMOJI[k], TIER_TRANSCRIBE[k])
                           for k in ("qual", "mkt", "near"))
                     + (("🔥", "命中 "),))

# 行情注剥除词表单源（推送审校 P2-1）：KPI 行1 尾注「（行情价）
# /*行情」、行3 兜底注「行情价」、恰达线「行情破线」（收口
# 词面）与 🟩 转写词「行情价 」同句两名——ntfy/短信(_alert_body) 与
# WinToast(_plain) 转写前共用此表勿再手抄（模块头「改词必漏」同病）。
# 尾两位改挂投影（=TIER_TRANSCRIBE["mkt"].strip()/
# TIER_FULL["mkt"]），前两位标点变体留本地
_MKT_NOTE_DUPS = ("（行情价）", "*行情",
                  TIER_TRANSCRIBE["mkt"].strip(), TIER_FULL["mkt"])


class _HeartbeatBackoff:
    """未达标心跳退避：钉钉 -1「系统繁忙」
    占 push_history 失败大头（实测 90%），每 15 分钟重推同语义心跳自身
    就是限流放大器。连败 ≥HB_BACKOFF_AFTER 轮后心跳跳过、每
    HB_PROBE_EVERY 轮放行一次探测（≈ 每小时 1 探）。

    跳过轮必须计入连败：否则退避期不再调 send、streak 冻在阈值，
    连败弹窗（≥8 每 8 轮升级）永远到不了——「故障必须被看见」断档。

    入闸范围由调用方（alerter._heartbeat_gate）结构性保证：达标轮与
    回落出线轮不入闸（必达不可吞）；状态存进程内存不持久化——重启后
    首轮心跳本身就是合法探测，陈旧退避态反而会吞掉已自愈通道的心跳。
    """

    HB_BACKOFF_AFTER = 6   # 连败 6 轮（15min/轮 ≈ 1.5h）起退避
    HB_PROBE_EVERY = 4     # 退避中每 4 个心跳轮放行 1 次探测

    def heartbeat_allow(self) -> bool:
        streak = getattr(self, "_fail_streak", 0)
        if streak < self.HB_BACKOFF_AFTER:
            self._hb_skip = 0
            return True
        self._hb_skip = getattr(self, "_hb_skip", 0) + 1
        if self._hb_skip % self.HB_PROBE_EVERY == 0:
            return True
        self._fail_streak = streak + 1
        return False


def _append_push_history(title: str, desp: str, ok: bool,
                         ch: str = "serverchan") -> None:
    """推送历史存档（JSONL 追加，各通道同文件同格式）：ServerChan 曾
    成功/失败都不落盘，控制台「推送记录」对本通道失明（补齐）；
     邮件通道原样破例再犯（P1-3），参数化 ch 收口。"""
    try:
        os.makedirs("logs", exist_ok=True)
        with open("logs/push_history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "ok": ok, "ch": ch, "title": title, "desp": desp},
                ensure_ascii=False) + "\n")
    except Exception:
        pass


class ServerChanNotifier(_HeartbeatBackoff):
    """Server 酱·Turbo 版：https://sct.ftqq.com/

    免费额度：每日 5 条；超出付费。
    """

    ENDPOINT_TPL = "https://sctapi.ftqq.com/{key}.send"

    def __init__(self, send_key: str, logger: logging.Logger,
                 channel: Optional[str] = None):
        self.send_key = send_key.strip()
        self.logger = logger
        self.channel = channel  # 可指定推送通道，不填默认
        self._fail_streak = 0   # 连败自监控（与钉钉通道同权）

    def send(self, title: str, desp: str = "", at_mobiles=None,
             is_at_all: bool = False, launch: str = "") -> bool:
        # at_mobiles/is_at_all/launch 收下即忽略：与钉钉/ntfy 通道签名
        # 对齐（alerter 统一按 send(title, desp, at_mobiles=…) 调用），
        # Server 酱无 @/@all 能力——签名缺形参会让选中本通道即整轮
        # TypeError 断推
        if not self.send_key:
            self.logger.debug("Server酱 SendKey 未配置，跳过推送")
            return False
        url = self.ENDPOINT_TPL.format(key=self.send_key)
        # desp 按 utf-8 字节截断（上限按字符切曾让中文长文超服务端
        # 字节限被整体拒绝）。截断留痕与切点避让对齐钉钉同款（发送端
        # 留痕家族律）：预算=上限-尾注（地板档总额预留制，尾注恒
        # 落位）、切点避让图链起点与段落边界（横切 URL 产出语法完整
        # 却指向不存在资源的死链，比坏 markdown 更隐蔽）、尾注点明
        # 丢失面（尾部恒是明细总表段/对账段/无链提示）
        text = desp or ""
        if len(text.encode("utf-8")) > 31800:
            raw_b = len(text.encode("utf-8"))
            note = ("\n\n⚠️ 内容超长已截断"
                    "（尾部明细总表/对账段未收入，完整明细见控制台）")
            budget = 31800 - len((note + "，本条已无跳转链接")
                                 .encode("utf-8"))
            cut_b = text.encode("utf-8")[:budget]
            img = cut_b.rfind(b"![")
            edge = cut_b.rfind(b"\n\n")
            if img > 6000:
                cut_b = cut_b[:img]
            elif edge > 12000:
                cut_b = cut_b[:edge]
            # 终验：切点后仍超预算时按预算重切，复用同款切点搜索防
            # 横切在位链接成死链（与钉钉同款）。当前参数下 cut_b 首切
            # 即 ≤budget、本分支恒假；本终验是尾注未来缩水（budget>
            # 首切上限）时的预留防线，勿因「不可达」删除
            if len(cut_b) > budget:
                cut_b = cut_b[:budget]
                img = cut_b.rfind(b"![")
                edge = cut_b.rfind(b"\n\n")
                if img > 6000:
                    cut_b = cut_b[:img]
                elif edge > 12000:
                    cut_b = cut_b[:edge]
            if b"](http" not in cut_b:
                note += "，本条已无跳转链接"
            cut_b += note.encode("utf-8")
            self.logger.warning(
                "Server酱 desp 超上限截断 %d→%d 字节（尾段丢弃）",
                raw_b, len(cut_b))
            text = cut_b.decode("utf-8", "ignore")
        payload = {
            # 限60字符
            "title": title[:60],
            # 支持 markdown
            "desp": text,
        }
        if self.channel:
            payload["channel"] = self.channel

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "ignore")
                obj = json.loads(body)
                code = obj.get("code", -1)
                if code == 0:
                    if self._fail_streak:
                        self.logger.info(
                            "Server酱 推送恢复（此前连续失败 %d 轮）",
                            self._fail_streak)
                    self._fail_streak = 0
                    self.logger.info("Server酱 推送成功: %s", title)
                    _append_push_history(title, desp, True)
                    return True
                self.logger.warning("Server酱 推送失败 code=%s body=%s",
                                    code, body[:200])
                self._fail_streak += 1
                _append_push_history(title, desp, False)
                self._maybe_streak_toast(code)
                return False
        except Exception as e:
            self.logger.warning("Server酱 推送异常: %s", e)
            self._fail_streak += 1
            _append_push_history(title, desp, False)
            self._maybe_streak_toast("EXC")
            return False

    def _maybe_streak_toast(self, code) -> None:
        """连败达阈值经本机弹窗浮出（与钉钉同款）：build_notifier
        里 Server酱与钉钉二选一为主通道，钉钉有连败弹窗而本通道曾只有
        日志——key 失效/欠费真断推时「告警系统自身的故障」无人看见。"""
        if self._fail_streak >= 8 and self._fail_streak % 8 == 0:
            _channel_streak_toast(
                self.logger, "Server酱",
                f"Server酱文本推送已连续 {self._fail_streak} 轮失败"
                f"（code={code}）。若微信同样收不到，请检查 SendKey/"
                "付费额度/通道设置。")


class DingTalkNotifier(_HeartbeatBackoff):
    """钉钉群自定义机器人：Webhook + 加签（HMAC-SHA256）。

    文档：https://open.dingtalk.com/document/robots/custom-robot-access
    markdown 消息有 18000 字节限制。
    """

    def __init__(self, webhook: str, logger: logging.Logger,
                 secret: str = ""):
        self.webhook = webhook.strip()
        self.secret = (secret or "").strip()
        self.logger = logger
        # 最近一次响应的钉钉 errcode（-1=幽灵送达信号，上层防重发用；
        # 网络异常时置 None 防陈旧值误判）
        self.last_errcode = None
        # 连续失败轮数（连败自监控用，成功即清零）
        self._fail_streak = 0

    def _signed_url(self) -> str:
        url = self.webhook
        if self.secret:
            ts = str(round(time.time() * 1000))
            string_to_sign = f"{ts}\n{self.secret}"
            sign = urllib.parse.quote_plus(base64.b64encode(
                hmac.new(self.secret.encode("utf-8"),
                         string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()))
            url = f"{url}&timestamp={ts}&sign={sign}"
        return url

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False,
             launch: str = "") -> bool:
        # launch 收下即忽略（断推根治）：Composite 按成员统一
        # 签名透传 launch（邮件「打开控制台」按钮/ntfy click/WinToast
        # launch 属性），钉钉消息体内本就内嵌 base_url 文本链接，无需
        # 点击直达参数——漏参会让透传抛 TypeError，钉钉通道每轮静默
        # 炸（邮件成功吞掉聚合真值，用户侧只剩「钉钉怎么没了」）
        # 尾空段收口（推送审校 P2-3）：图片行后「\n\n」尾随
        # 空段全量存在（last_push.md 实证）——零信息损失仅末尾留白
        text = (desp or title or "").rstrip()
        # 钉钉 18000 上限按 UTF-8 字节计（中文 3 字节/字，按字符数判
        # 会漏判：近万字中文 desp 实际已近 3 万字节，原样发出被网关拒收）
        if len(text.encode("utf-8")) > 18000:
            # 截断回退：优先落在最后一个完整段落边界；若边界太靠前，
            # 再回退到最后一个图链起点之前——![走势](url) 是纯 ASCII，
            # 恰在 18000 处硬切会产出语法完整却指向不存在资源的死链
            # （比坏 markdown 更隐蔽）。截断必须留痕：丢的尾段可能含
            # 对账行/达标命中，静默丢失曾无从排查；起消息内
            # 也留痕（⚠️ 已截断尾注），且链接全被切掉时补控制台指引
            # ——用户侧「这期没链接」曾无从解释
            raw_b = len(text.encode("utf-8"))
            # 尾注语义补全（推送审校）：泛化「已截断」不说
            # 丢了什么——尾部恒是明细总表段（比价唯一载体）、对账段
            # 与 @提醒段（@高亮结构性垫底，被切即触达蒸发），逐项点明
            # 丢失面让读者知道去控制台看什么
            note = ("\n\n⚠️ 内容超长已截断"
                    "（尾部明细总表/@提醒/对账段未收入，完整明细见控制台）")
            # 切点预算=上限-尾注最大形态（地板档总额预留制：尾注
            # 恒落位，正文按剩余预算让位——17900 固定切+108B 尾注
            # 曾可达 18035B 超限，单发铁律下该轮必丢）
            budget = 18000 - len((note + "，本条已无跳转链接")
                                 .encode("utf-8"))
            cut_b = text.encode("utf-8")[:min(17900, budget)]
            img = cut_b.rfind(b"![")
            edge = cut_b.rfind(b"\n\n")
            if img > 6000:
                cut_b = cut_b[:img]
            elif edge > 12000:
                cut_b = cut_b[:edge]
            # 终验（推送审校）：切点后仍超预算时按预算重切，复用同款
            # 切点搜索防横切在位链接成死链。当前参数下的活跃修复是
            # 上行 min(17900, budget) 预算钳制（budget=17865<17900，
            # 本分支恒假）；本终验是尾注未来缩水到 <100B（budget>
            # 17900）时的预留防线，勿因「不可达」删除
            if len(cut_b) > budget:
                cut_b = cut_b[:budget]
                img = cut_b.rfind(b"![")
                edge = cut_b.rfind(b"\n\n")
                if img > 6000:
                    cut_b = cut_b[:img]
                elif edge > 12000:
                    cut_b = cut_b[:edge]
            if b"](http" not in cut_b:
                # 无链分支独立指引（词面与尾注本体「完整明细见控制台」
                # 去重——同义两现曾是病句）
                note += "，本条已无跳转链接"
            cut_b += note.encode("utf-8")
            self.logger.warning(
                "钉钉 desp 超上限截断 %d→%d 字节（尾段丢弃）",
                raw_b, len(cut_b))
            text = cut_b.decode("utf-8", "ignore")
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": (title or "机票监控")[:60],
                "text": text,
            },
        }
        at = {}
        if at_mobiles:
            at["atMobiles"] = [str(m).strip() for m in at_mobiles if str(m).strip()]
        if is_at_all:
            at["isAtAll"] = True
        if at:
            payload["at"] = at
        # 严格单发，永无重试（用户明确要求杜绝重发）：钉钉 -1 存在
        # 幽灵送达（报错但消息已入群），任何第二次发送都可能造成重复。
        # -1 即放弃本轮，15 分钟后下轮心跳自然补；达标场景电话/ntfy
        # 通道完全独立于钉钉，关键警报不依赖本通道。
        try:
            os.makedirs("debug", exist_ok=True)
            with open("debug/last_push.md", "w", encoding="utf-8") as f:
                f.write("<!-- title: %s -->\n<!-- saved: %s -->\n%s" % (
                    title, datetime.now().strftime("%H:%M:%S"), desp))
        except Exception:
            pass
        try:
            r = httpx.post(self._signed_url(), json=payload,
                           timeout=10, trust_env=False)
            body = r.text
            obj = r.json()
        except Exception as e:
            self.logger.warning("钉钉推送异常: %s", e)
            # 网络异常未收到 errcode，必须清掉上轮残留（如 -1）：日报落账
            # 据 last_errcode==-1 判「幽灵送达按已推」——本轮根本没发出去，
            # 残留 -1 会把当日日报静默吞掉且不再重试
            self.last_errcode = None
            # 网络异常同样计入连败：持续断网时只有本 WARNING 无弹窗，
            # 「故障必须被看见」在主通道上不留死角
            self._fail_streak += 1
            return False
        ok = obj.get("errcode") == 0
        # 留痕 errcode：钉钉 -1「系统繁忙」是幽灵送达（报错但消息已入群），
        # 上层（日报落账等）据此决定不重发——内容固定的消息重试=重复轰炸
        self.last_errcode = obj.get("errcode")
        # 推送历史存档：控制台"推送记录"随时回看群里收到过什么
        # （ch="dingtalk" 通道维度与 email/serverchan 对齐，单源收口）
        _append_push_history(title, desp, ok, ch="dingtalk")
        if ok:
            if self._fail_streak:
                self.logger.info("钉钉推送恢复（此前连续失败 %d 轮）",
                                 self._fail_streak)
            self._fail_streak = 0
            self.logger.info("钉钉推送成功: %s", title)
            return True
        self._fail_streak += 1
        self.logger.warning(
            "钉钉推送失败 code=%s（单发不重试，下轮自然补）: %s",
            obj.get("errcode"), body[:200])
        # 连败自监控：-1 历史多为幽灵送达，但若真断推，
        # 钉钉是唯一文本通道且服务端无法区分两种形态——连败达阈值经
        # 本机弹窗浮出（告警系统自身的故障必须被看见，原则
        # 补齐主通道缺口）。每 8 轮（15 分钟轮约 2 小时）提醒一次
        if self._fail_streak >= 8 and self._fail_streak % 8 == 0:
            self._streak_toast(self._fail_streak, obj.get("errcode"))
        return False

    def _streak_toast(self, streak: int, code) -> None:
        """连败本机弹窗（抽共用 _channel_streak_toast）：
        用户见弹窗即可对照群聊分辨「幽灵送达」与「真断推」。"""
        _channel_streak_toast(
            self.logger, "钉钉",
            f"钉钉文本推送已连续 {streak} 轮失败（code={code}）。"
            "若群里同样收不到消息，请检查机器人 webhook/加签/限流设置。")


def _channel_streak_toast(logger: logging.Logger, channel: str, body: str):
    """文本通道连败本机弹窗（单源，钉钉/Server酱共用）：WinToast
    同法零依赖。失败静默——告警系统自身不得再炸。"""
    try:
        import base64 as _b64
        import subprocess
        script = WindowsToastNotifier._script(f"{channel}推送通道异常", body, "")
        enc = _b64.b64encode(script.encode("utf-16-le")).decode()
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", enc],
            timeout=20, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False)
    except Exception as e:
        logger.warning("[连败自监控] 弹窗失败: %s", e)


def _is_legend_line(ln: str) -> bool:
    """图例行兜底识别（emoji 计数式）：剥引用块 `>` 后档位
    emoji（🎯🟩🟨）计数 ≥2 即判图例——正文任何行至多 1 个档位点
    （KPI 行点前置 1 个、hits 行用 🔥 不入计、建议行无点、仪表条行
    另有独立过滤）。旧双词识别（「破线+超线」「破线+达标」）锚死
    现役措辞，图例降级丢段/未来改词即静默漏进电话/弹窗。"""
    t = ln.lstrip("> ").strip()
    return sum(t.count(e) for e in "🎯🟩🟨") >= 2


def _alert_body(desp: str) -> str:
    """强提醒通道（弹窗/电话短信）的正文瘦身：弹窗一闪而过，
    主通道专用的「图例/时刻」说明行在弹窗里是噪音——现行聚合头行
    「> ⏱ 22:38 🎯真达标 🟩破线 🟨擦边 超线」（引用块行首是 `>`，
    startswith("⏱") 恒不中）与纯仪表条行「🟩🟩🟩🟩🟩」一律滤除，
    旧措辞（距达标/进度条 =/数据截至）兼容保留，首屏只留航线价格
    与操作建议。"""
    def _skip(ln: str) -> bool:
        # 结构化前缀判定先剥引用块 `>`（旧 lstrip 不剥 `>`，头行
        # 「> ⏱ …」恒漏网，靠措辞子串兜底——图例超宽降级丢词条
        # 时子串双词识别失效、图例直进电话/弹窗）；⏳ 空窗/⚠️ 运维
        # 对账行同属弹窗噪音（收口）
        t = ln.lstrip("> ").strip()
        if t.startswith(("⏱", "⏳", "⚠️", "⚠")):
            return True
        if ("距达标" in ln or "进度条 =" in ln or "数据截至" in ln):
            return True
        # 图例行兜底（emoji 计数式）：图例措辞再变/降级丢段
        # 均可识别（≥2 档位点=图例），不再耦合「破线+超线」字面
        if _is_legend_line(ln):
            return True
        # 纯仪表条行（只由五格方块/分隔符组成）：电话播报读不出颜色
        if any(c in t for c in "🟩🟨🟦⬜🟥") and not _re.sub(
                r"[🟩🟨🟦⬜🟥\s|]", "", t):
            return True
        return False

    lines = [ln for ln in (desp or "").splitlines() if not _skip(ln)]
    body = chr(10).join(lines)
    # 🟩 转写词「行情价 」与 KPI 行1 尾注「（行情价）/*行情」、行3
    # 兜底注「行情价」同条重复（调研② P2-7 挂起项收口）：转写前
    # 剥注——剥前不剥后，转写前缀此刻尚未拼入，零信息损失。
    # 「行情破线」同律（推送审校 P2）：恰达线（diff==0 非达标）
    # gap_txt 出「行情破线」、🟩 点转写「行情价 」——不剥则同句读出
    # 「行情价…行情破线」两名（notifier 模块头「两词面打架」事故类）
    for _dup in _MKT_NOTE_DUPS:
        body = body.replace(_dup, "")
    # 残留单档位点转词：图例/纯符号行已剥，KPI 行内的
    # 🎯🟩🟨 点进 900 字短信与 TTS 播报会读成「绿方块直飞…」——
    # 弹窗/电话一闪而过场景 emoji 无解码，按四档语义转可读词
    for _e, _w in _EMOJI_TIER_WORDS:
        body = body.replace(_e, _w)
    # 装饰符剥离（推送审校）：❌✈️📋📈📉🚨↩️📍🗓💡 等标题/
    # 结构装饰 emoji 对 TTS 是噪音（读「叉号/飞机/剪贴板」）而信息已由
    # 文字承载；↑/↓ 趋势箭头转「涨/跌」（TTS 读「上箭头」不可懂）。
    # 勿动已转写的 🎯🟩🟨🔥（档位语义，上方单源承担）。
    # （推送审校 P2-4）补缺口：🔔（持续达标头，达标主路径）/📲
    # （完整详情直达）/👉（单航线详情直达）/💰⚖️（图挂兜底）/⚠️
    # （比价离群头·行中形态——行首 ⚠️ 行已被 _skip 整行滤除，VS16
    # 剥除后裸 ⚠ 会漏进短信/TTS）——清单机制无自愈，新装饰 emoji
    # 入 desp 须记着在此补
    for _d in ("❌", "✈️", "✈", "📋", "📈", "📉", "🚨",
               "↩️", "↩", "📍", "🗓️", "🗓", "💡",
               "🔔", "📲", "👉", "💰", "⚖️", "⚠️", "⚠"):
        body = body.replace(_d, "")
    # pictograph 全量剥离自愈层（挂账③收口）：≥U+1F000 区段+
    # VS16 尾零维护覆盖新装饰 emoji（黑名单曾五轮追补，代码自认无自愈）；
    # BMP 区 pictograph（↩⚠⏱ 等）仍靠上方清单——档位/箭头已由上方
    # 转写承担，此处只清残留噪音，TTS/短信场景任何 emoji 均为噪音
    body = _re.sub("[\U0001F000-\U0001FFFF\uFE0F]", "", body)
    body = body.replace("↓", "跌").replace("↑", "涨")
    return body


# 邮件友好壳状态横幅（形态 v3）：title 首个档位 emoji →
# (横幅底色, 状态字色, 状态词)。配色=webui 设计令牌浅色谱（--okbg
# #e9f4ec/--ok-txt #0b6e39、琥珀 --warn-deep #6f5600、回落红）——
# 打开邮件 1 秒内以色识态，词面与 alerter 档位词同源不另造
_TIER_BANNER = (
    # 键序=匹配优先级（_banner_html 首中即断）。🚨/🔔=alerter 达标主路径
    # title 头（push_history 941 条实发词表：❌856/📈70/🔔9/🚨5，🎯🔥🟩🟨
    # 仅入 desp 恒不进 title—— P1-1 补齐，达标邮件不再落默认蓝）；
    # 档位词面挂 TIER_FULL 投影（P2-1 词面单源律，改词只动 _TIER_TABLE）
    ("🚨", ("#e9f4ec", "#0b6e39", TIER_FULL["qual"] + " · 可出手")),
    ("🔔", ("#e9f4ec", "#0b6e39", "持续达标")),
    ("🎯", ("#e9f4ec", "#0b6e39", TIER_FULL["qual"] + " · 可出手")),
    ("🔥", ("#e9f4ec", "#0b6e39", "命中达标线")),
    ("🟩", ("#e9f4ec", "#0b6e39", TIER_FULL["mkt"])),
    ("🟨", ("#fff8e1", "#6f5600", TIER_FULL["near"])),
    ("↩️", ("#fdecec", "#a12622", TIER_FULL["fall"])),
    ("❌", ("#f1f3f6", "#5a6472", "未达标")),
)
_TIER_BANNER_DEFAULT = ("#eef4fc", "#0b62d6", "机票监控推送")


def _banner_html(title: str) -> str:
    """状态横幅：底色按档位，主字=状态词，副行=title 剥「机票监控｜」
    前缀（Subject 已含品牌名，横幅不复读；剩余信息如航线/日期保留）。
    emoji 匹配前双端剥 VS16（\\ufe0f）——alerter 实发「↩️」与字面表中
    「↩️」变体选择符有无不一致时仍命中。"""
    t = title or ""
    t_norm = t.replace("\ufe0f", "")
    hit_emoji = ""
    for emoji, (bg, fg, word) in _TIER_BANNER:
        if emoji.replace("\ufe0f", "") in t_norm:
            hit_emoji = emoji.replace("\ufe0f", "")
            break
    else:
        bg, fg, word = _TIER_BANNER_DEFAULT
    sub = t.replace("机票监控｜", "").replace("机票监控", "").strip("｜ |")
    # 副行不复读主字：title 首段含命中 emoji 时先剥行首 emoji（
    # P2-5 统一形态——🚨/↩️ 支同样剥 emoji，整段原样带 emoji 与 ❌/🔔 剥后不一），
    # 主词命中再剥词面：❌ 首段纯档位复读（实发 91%）整段消失，🔔 支只
    # 剥词面保留航线价信息；主词不中（🚨 支「达标！」异形）保留余段，
    # 轻度可接受
    head, sep, rest = sub.partition("｜")
    w_main = word.split(" · ")[0].split(" ")[0] if word else ""
    if hit_emoji and hit_emoji in head.replace("\ufe0f", ""):
        head = head.replace("\ufe0f", "").replace(hit_emoji, "", 1).lstrip(" ")
        if w_main and w_main in head:
            pos = head.find(w_main)
            # 「·」入 strip 集：🔔「持续达标·上→乌」
            # 剥词后行首残留间隔号；无「｜」单段 title 同样剥离
            # （达标轮单航线单日期形态整段=档位复读）
            head = head[pos + len(w_main):].strip("！!｜| 　·")
        if sep:
            sub = (head + "｜" + rest) if head else rest
        else:
            sub = head
    else:
        # default 支（📈/📉 日报等无档位 emoji 的 title）副行同样剥
        # 行首装饰 emoji（P2-5 只覆盖命中支，
        # 日报重放实证「📈 09/21 日报…」带 emoji 直出）。VS16 先归一
        # （↩️/🗓️ 等变体选择符有无不一），长形态无需重复列出
        h = head.replace("\ufe0f", "")
        for _d in ("✈", "📋", "📈", "📉", "📍", "🗓", "💡",
                   "📲", "👉", "💰", "⚖", "⚠"):
            if h.startswith(_d):
                head = h[len(_d):].lstrip(" ")
                sub = ((head + "｜" + rest) if head else rest) if sep else head
                break
    sub_html = ("" if not sub else
                '<div style="font-size:13px;color:%s;margin-top:3px;'
                'opacity:.85">%s</div>' % (fg, _esc_md(sub)))
    return ('<div style="padding:14px 18px;background:%s;border-radius:'
            '10px;margin-bottom:14px"><span style="font-size:18px;'
            'font-weight:700;color:%s">%s</span>%s</div>'
            % (bg, fg, word, sub_html))


def _sec_label(txt: str) -> str:
    """小节标：13px 灰字+左侧品牌蓝短竖条（分区不喧宾）。"""
    return ('<div style="font-size:13px;color:#8a94a3;margin:16px 0 8px;'
            'font-weight:600"><span style="display:inline-block;width:3px;'
            'height:11px;background:#0b62d6;border-radius:2px;'
            'margin-right:7px"></span>%s</div>' % txt)


def _email_shell_html(title: str, desp: str, launch: str = "",
                      with_snapshot: bool = True) -> str:
    """邮件友好壳（形态 v3，全内联样式）：状态横幅（色识态）→ 控制台
    快照图（cid 引用；with_snapshot=False 时降级提示行）→ 推送详情
    （desp markdown 渲染）→ 控制台直达按钮（launch 有值才出，截图内
    链接不可点，文字区按钮是唯一跳转入口）→ 页脚。"""
    parts = [
        '<div style="max-width:700px;margin:0 auto;font-family:'
        "-apple-system,'Segoe UI','Microsoft YaHei','PingFang SC',"
        'sans-serif;background:#ffffff;color:#1c2733">',
        _banner_html(title),
    ]
    if with_snapshot:
        parts.append(_sec_label("🖥 控制台实时快照"))
        parts.append(
            '<img src="cid:console-shot" alt="机票监控控制台快照" '
            'style="width:100%;display:block;border:1px solid #e6ebf2;'
            'border-radius:8px">')
    else:
        # P1-2：降级提示一行（曾塞 _email_html 整壳——其内已含
        # 完整 desp+页脚，与下方「推送详情」重复渲染，状态头×2/页脚×2）
        parts.append('<div style="padding:10px 12px;background:#f1f3f6;'
                     'border-radius:8px;color:#5a6472;font-size:13px">'
                     '🖥 控制台快照生成失败，以下为文字详情</div>')
    parts.append(_sec_label("📨 推送详情"))
    parts.append(_md_to_html(desp or ""))
    if (launch or "").strip():
        parts.append(
            '<a href="%s" style="display:inline-block;margin:16px 0 4px;'
            'padding:10px 22px;background:#0b62d6;color:#ffffff;'
            'border-radius:8px;text-decoration:none;font-size:14px;'
            'font-weight:600">📲 打开控制台看完整详情</a>'
            % _esc_md(launch))
    parts.append(
        '<div style="margin-top:14px;padding-top:10px;border-top:1px '
        'solid #e6ebf2;color:#8a94a3;font-size:12px">ticket-monitoring '
        '自动推送%s%s</div></div>'
        # 页脚两态各自成立（/ ）：launch 空
        # 不出「请点上方按钮」（正文并无按钮）；降级轻壳不出「截图即
        # 控制台原貌」（与「快照生成失败」自相矛盾）
        % ((' · 截图即控制台原貌' if with_snapshot else ''),
           (' · 链接请点上方按钮' if (launch or "").strip() else '')))
    return "".join(parts)


def launch_is_public(base_url: str) -> bool:
    """base_url 是否公网可点（从 alerter._launch_public 收编
    单源）：127.0.0.1/localhost/::1 回环仅本机可点——钉钉 desp 链接/
    邮件「打开控制台」按钮/测试邮件 launch 统一以此过滤，异机死链
    防回潮。"""
    if not (base_url or "").strip():
        return False
    try:
        from urllib.parse import urlparse as _up
        h = (_up(base_url).hostname or "").lower()
        return bool(h) and h not in ("127.0.0.1", "localhost", "::1")
    except ValueError:
        return False


def _esc_md(s: str) -> str:
    """markdown 正文转 HTML 前的 &<> 转义（webui esc() 同律：先转义
    后注标签，正文里的 <script> 不可能直进邮件）；引号一并转义——
    输出会进 href="%s" 属性上下文（补 &quot;）"""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _md_inline_html(s: str) -> str:
    """行内级 markdown → HTML（输入须已 _esc_md 转义）：
    ![alt](url) / [t](u) / **粗体**——alerter desp 行内语法全集"""
    s = _re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        r'<img src="\2" alt="\1" style="max-width:100%;'
        r'border-radius:6px;margin:6px 0;display:block">', s)
    s = _re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        r'<a href="\2" style="color:#0b62d6">\1</a>', s)
    s = _re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return s


def _md_to_html(desp: str) -> str:
    """desp markdown 子集 → HTML 片段（alerter 全产出形态：#### 标题、
    > 引用、- 项、N. 项、独立图行、普通行）。样式全内联——QQ/163 网页
    版会剥 <style> 块，类选择器不可用。"""
    out, ul, ol, quote = [], False, False, []

    def _close_lists():
        nonlocal ul, ol
        if ul:
            out.append("</ul>")
            ul = False
        if ol:
            out.append("</ol>")
            ol = False

    def _flush_quote():
        nonlocal quote
        if quote:
            out.append(
                '<blockquote style="margin:8px 0;padding:6px 12px;'
                'border-left:3px solid #0b62d6;background:#f2f6fc;'
                'color:#3d4a5c;font-size:14px;line-height:1.7">'
                + "<br>".join(quote) + "</blockquote>")
            quote = []

    for raw in (desp or "").splitlines():
        ln = raw.rstrip()
        if not ln.strip():
            _close_lists()
            _flush_quote()
            continue
        m = _re.match(r"^#{1,6}\s+(.*)$", ln)
        if m:
            _close_lists()
            _flush_quote()
            out.append(
                '<h3 style="margin:16px 0 6px;font-size:15px;'
                'color:#0f1b2d;font-weight:700">'
                + _md_inline_html(_esc_md(m.group(1))) + "</h3>")
            continue
        if ln.startswith(">"):
            _close_lists()
            quote.append(_md_inline_html(_esc_md(ln.lstrip("> ").rstrip())))
            continue
        _flush_quote()
        m = _re.match(r"^-\s+(.*)$", ln)
        if m:
            if ol:
                out.append("</ol>")
                ol = False
            if not ul:
                out.append('<ul style="margin:6px 0;padding-left:20px;'
                           'font-size:14px;line-height:1.7">')
                ul = True
            out.append("<li>" + _md_inline_html(_esc_md(m.group(1)))
                       + "</li>")
            continue
        m = _re.match(r"^(\d+)[.、]\s+(?!\d)(.*)$", ln)
        if m:
            if ul:
                out.append("</ul>")
                ul = False
            if not ol:
                out.append('<ol style="margin:6px 0;padding-left:22px;'
                           'font-size:14px;line-height:1.7">')
                ol = True
            out.append("<li>" + _md_inline_html(_esc_md(m.group(2)))
                       + "</li>")
            continue
        out.append('<p style="margin:6px 0;font-size:14px;line-height:1.7">'
                   + _md_inline_html(_esc_md(ln.strip())) + "</p>")
    _close_lists()
    _flush_quote()
    return "".join(out)


def _email_html(desp: str) -> str:
    """邮件 HTML 壳：浅色底适配客户端多样预览环境，配色取 webui 设计
    令牌（品牌蓝 #0b62d6 / 墨蓝 #0f1b2d）。title 已是邮件 Subject，
    头部只留品牌条（desp 内自带 #### 状态头，不重复标题——UX 写作
    「不复读读者已能看到的信息」）"""
    return (
        '<div style="max-width:680px;margin:0 auto;'
        'font-family:-apple-system,\'Segoe UI\',\'Microsoft YaHei\','
        '\'PingFang SC\',sans-serif;background:#ffffff;color:#1c2733">'
        '<div style="padding:13px 20px;background:#0f1b2d;'
        'color:#e8eef7;font-weight:700;font-size:15px">✈️ 机票监控</div>'
        '<div style="padding:16px 20px">' + _md_to_html(desp or "")
        + '</div><div style="padding:10px 20px;border-top:1px solid #e6ebf2;'
        "color:#8a94a3;font-size:12px\">ticket-monitoring 自动推送"
        " · SMTP 授权码直发</div></div>")


# ---- 推送图 CID 内嵌（邮件通路专属） ----
# desp 里的图床外链图（![明细总表](https://sm.ms/..) 等，钉钉 markdown
# 只认公网 URL 才被迫走免费图床）原样进邮件会让 QQ/163 网页版默认折叠
# （要手点「显示图片」）+ 免费图床直链加载慢（用户 09-22 实报）。邮件
# 有附件通路，发送端把图下载后并进 console-shot 同一条 multipart/related，
# 收件端零外网请求；下载失败/非图片保留外链（客户端旧行为兜底），钉钉
# 等其他通道拿到的 desp 原文不动。
_PUSH_IMG_RE = _re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_PUSH_IMG_MAX = 6            # 单封最多内嵌张数（日报多航线可到 3-5 张）
_PUSH_IMG_BYTES = 10 * 1024 * 1024   # 单张体积上限（自身渲染图远小于此）
_PUSH_IMG_DEADLINE = 25.0    # 全部下载共享总时限（防图床悬挂拖住推送轮）


def _sniff_img_fmt(data: bytes) -> str:
    """图片格式嗅探（魔数）：只收 png/jpeg——渲染端只出 png，jpeg 兜底
    防图床转码；其余（webp/软拒 HTML 页）不内嵌。"""
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    return ""


def _fetch_push_image(url: str) -> bytes:
    """下载图床直链：trust_env=False 与上传端同律（系统代理曾随机掐
    图床 HTTPS）；follow_redirects 直链 302 跳 CDN。"""
    r = httpx.get(url, timeout=httpx.Timeout(10.0, connect=5.0),
                  trust_env=False, follow_redirects=True)
    if r.status_code != 200:
        raise ValueError("HTTP %s" % r.status_code)
    return r.content


def _inline_push_images(desp: str, logger) -> tuple:
    """desp 里的图床外链图 → 下载转 CID：返回 (HTML part 用的替换后
    desp, [(cid, data, fmt)])。仅替 markdown 图片形态（[文字](同链) 的
    纯链接不动）；多张共享总时限，单张失败即弃；去重按 URL（走势图
    同 URL 跨小节复用只下载一次）。"""
    urls, seen = [], set()
    for m in _PUSH_IMG_RE.finditer(desp or ""):
        u = m.group(2)
        if u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            urls.append(u)
    if not urls:
        return (desp or ""), []
    out = desp or ""
    parts = []
    t0 = time.time()
    for n, u in enumerate(urls[:_PUSH_IMG_MAX], 1):
        if time.time() - t0 > _PUSH_IMG_DEADLINE:
            logger.warning("[Email] 推送图下载超总时限，第 %d 张起保留外链",
                           n)
            break
        try:
            data = _fetch_push_image(u)
            fmt = (_sniff_img_fmt(data)
                   if 0 < len(data) <= _PUSH_IMG_BYTES else "")
        except Exception as e:
            data, fmt = b"", ""
            logger.warning("[Email] 推送图下载失败（保留外链）%s: %s",
                           u[:80], e)
        if not fmt:
            continue
        cid = "push-img-%d" % n
        parts.append((cid, data, fmt))
        out = _PUSH_IMG_RE.sub(
            lambda m, _u=u, _c=cid: ("![%s](cid:%s)" % (m.group(1), _c))
            if m.group(2) == _u else m.group(0), out)
    if parts and len(parts) < len(urls):
        logger.info("[Email] 推送图内嵌 %d/%d 张（其余保留外链）",
                    len(parts), len(urls))
    return out, parts


class EmailNotifier(_HeartbeatBackoff):
    """SMTP 邮件通道（163/QQ 等免费邮箱）：网页版设置开 SMTP 拿「授权码」
    （非登录密码）。multipart/alternative = 纯文本降级 part + HTML part，
    客户端不支持 HTML 时自动落纯文本。@手机号/at_mobiles 无对应能力，
    收下即忽略（同 ServerChan 先例）。 起 desp 里的图床外链图
    下载后 CID 内嵌（与控制台快照同一 related 通路，收件端零外网请求）。

    163/QQ 发件人策略：From 必须等于登录账号，否则服务端 554 拒信——
    sender_name 只作显示名。"""

    def __init__(self, host: str, port: int, user: str, password: str,
                 to: str, logger: logging.Logger,
                 sender_name: str = "机票监控",
                 snapshot_base: str = ""):
        self.host = (host or "").strip() or "smtp.163.com"
        self.port = int(port or 465)
        self.user = (user or "").strip()
        self.password = (password or "").strip()
        self.to = [t.strip() for t in
                   _re.split(r"[,;，；\s]+", (to or "")) if t.strip()]
        self.sender_name = sender_name
        self.snapshot_base = (snapshot_base or "").strip()
        self.logger = logger
        self._fail_streak = 0
        self.last_err = ""   # 最近一次失败原因（webui 通路验证回显）

    def _html_body(self, desp: str) -> str:
        """降级轻壳 HTML（快照不可用时）：颜色/排版取 webui 设计令牌。
        title 已是邮件 Subject，头部只留品牌条（desp 内自带 #### 状态头，
        不重复标题——不复读读者已能看到的信息）。"""
        return _email_html(desp)

    def _build_msg(self, title: str, desp: str,
                   launch: str = "") -> MIMEMultipart:
        """组装 MIME（图内嵌）：快照或推送图可用 → multipart/
        related（友好壳：状态横幅+截图+详情+直达按钮；alternative 纯文本
        兜底 + PNG CID 内嵌——控制台快照 + desp 图床图下载转内嵌）；全缺
        → 纯 alternative（友好壳无图模式）。纯文本 part 恒用 desp 原文
        （外链保持可点），cid 替换只进 HTML part。"""
        shot = None
        if self.snapshot_base:
            try:
                from .emailshot import render_console_png
                shot = render_console_png(self.snapshot_base, self.logger)
            except Exception as e:
                self.logger.warning("[Email] 快照渲染异常（降级轻壳）: %s",
                                    e)
        try:
            html_desp, inline = _inline_push_images(desp, self.logger)
        except Exception as e:
            html_desp, inline = (desp or ""), []
            self.logger.warning("[Email] 推送图内嵌异常（保留外链）: %s", e)
        if shot or inline:
            from email.mime.image import MIMEImage
            msg = MIMEMultipart("related")
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(desp or title or "", "plain", "utf-8"))
            alt.attach(MIMEText(
                _email_shell_html(title, html_desp, launch,
                                  with_snapshot=bool(shot)),
                "html", "utf-8"))
            msg.attach(alt)
            if shot:
                img = MIMEImage(shot, "png", name="console-shot.png")
                img.add_header("Content-ID", "<console-shot>")
                img.add_header("Content-Disposition", "inline",
                               filename="console-shot.png")
                msg.attach(img)
            for cid, data, fmt in inline:
                img = MIMEImage(
                    data, fmt, name="%s.%s" % (cid, "png" if fmt == "png"
                                               else "jpg"))
                img.add_header("Content-ID", "<%s>" % cid)
                img.add_header("Content-Disposition", "inline",
                               filename="%s.%s" % (cid, "png" if fmt == "png"
                                                   else "jpg"))
                msg.attach(img)
            self._msg_headers(msg)
            return msg
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(desp or title or "", "plain", "utf-8"))
        msg.attach(MIMEText(
            _email_shell_html(title, desp, launch, with_snapshot=False),
            "html", "utf-8"))
        self._msg_headers(msg)
        return msg

    def _msg_headers(self, msg: MIMEMultipart) -> None:
        """Date/Message-ID（P2-2）：smtplib 不自动补 Date，缺两头
        部分客户端排序错乱+反垃圾减分；domain 取发件账号 @ 后缀。"""
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(
            domain=(self.user.rsplit("@", 1)[-1]
                    if "@" in self.user else self.host))

    def send(self, title: str, desp: str = "", at_mobiles: list = None,
             is_at_all: bool = False, launch: str = "") -> bool:
        if not (self.user and self.password and self.to):
            self.logger.warning(
                "[Email] 配置不全（账号/授权码/收件人），跳过发送")
            return False
        msg = self._build_msg(title, desp, launch=launch)
        msg["Subject"] = Header(title or "机票监控", "utf-8")
        msg["From"] = formataddr((str(Header(self.sender_name, "utf-8")),
                                  self.user))
        msg["To"] = ", ".join(self.to)
        try:
            # 每次新建连接：推送低频（15min 级），池化复杂度不值
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as s:
                s.login(self.user, self.password)
                s.sendmail(self.user, self.to, msg.as_string())
            self._fail_streak = 0
            self.last_err = ""
            _append_push_history(title, desp, True, ch="email")
            self.logger.info("[Email] 邮件已发至 %s: %s",
                             ", ".join(self.to), (title or "")[:50])
            return True
        except Exception as e:
            self._fail_streak += 1
            self.last_err = str(e)
            _append_push_history(title, desp, False, ch="email")
            self.logger.warning("[Email] 发送失败(第%d次): %s",
                                self._fail_streak, e)
            return False


class CompositeNotifier(_HeartbeatBackoff):
    """多通道并联（邮件与主通道并联）：逐个 send、任一成功即
    True。心跳退避看聚合结果——主通道挂了但邮件通，心跳继续走通的
    通道；全军覆没才计连败。单通道失败日志已在各通道 send 内留痕。"""

    def __init__(self, members: list, logger: logging.Logger):
        self.members = members
        self.logger = logger
        self._fail_streak = 0

    def send(self, title: str, desp: str = "", at_mobiles: list = None,
             is_at_all: bool = False, launch: str = "") -> bool:
        ok_any = False
        for m in self.members:
            try:
                ok = bool(m.send(title, desp, at_mobiles=at_mobiles,
                                 is_at_all=is_at_all, launch=launch))
            except Exception as e:
                # 通道实现不应抛（各 send 内部已兜），抛了也不能殃及
                # 后续通道（一个通道 TypeError 整轮推送全丢的旧案）
                self.logger.warning("[Composite] 通道 %s 异常: %s",
                                    type(m).__name__, e)
                ok = False
                # 异常路径计入该通道连败（P2-4）：P0-1 事故中
                # 钉钉 TypeError 发生在其内部计数之前，_fail_streak 冻结，
                # 「连败弹窗」自监控被整轮绕过——坏死通道可无限期静默
                if getattr(m, "_fail_streak", None) is not None:
                    m._fail_streak += 1
            ok_any = ok_any or ok
        self._fail_streak = 0 if ok_any else self._fail_streak + 1
        return ok_any


class NtfyNotifier:
    """ntfy.sh 强提醒通道（达标专用）：手机装 ntfy App 订阅同名 topic，
    即可获得系统级弹窗 + 铃声 + 免打扰穿透（priority=max）——
    自定义钉钉机器人无法打电话/发 DING，这是 webhook 体系内最接近的强提醒。"""

    def __init__(self, topic: str, logger: logging.Logger,
                 server: str = "https://ntfy.sh", priority: int = 5):
        self.topic = (topic or "").strip()
        self.server = (server or "https://ntfy.sh").rstrip("/")
        self.priority = max(1, min(5, int(priority or 5)))
        self.logger = logger

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False,
             launch: str = "") -> bool:
        if not self.topic:
            return False
        # 命中条数取转写前原文（🔥 入 _EMOJI_TIER_WORDS 转写
        # 表后，转写后文本已无 🔥——截断留痕「共N条命中」须在转写前
        # 计数，否则静默消失）
        _nfire = (desp or "").count("🔥")
        body = _alert_body(desp or title)
        body = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图]", body)
        # markdown 链接还原「文字: url」：ntfy 自动链接化裸 URL，剥壳后
        # 手机通知栏不再残留 [文字](url) 原始记号
        body = _re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1: \2", body)
        body = _re.sub(r"[#>*`]", "", body).strip()
        # 截断避让 URL：600 字符硬截曾落在 URL 中段——通知栏
        # 链接可点但必死的半截链。在完整文本上判定截点是否落入 URL 内，
        # 是则回退到链接前
        _full = body
        _cut = body[:600]
        for _m in _re.finditer(r"https?://\S+", body):
            if _m.start() >= len(_cut):
                break
            if len(_cut) < _m.end():
                _cut = body[:_m.start()].rstrip()
                break
        body = _cut or title
        # 截断留痕（与钉钉「⚠️ 已截断」纪律对齐）：回退后其后
        # 整段（含后续命中行的渠道链接）曾静默丢弃，读者以为只有这些
        if len(body) < len(_full):
            # 无 … 尾注（P2-2）：ntfy 是 TTS 绑定通道，U+2026
            # 播报成「。。。」（钉钉同律）
            _tail = "（已截断"
            _n = _nfire
            if _n:
                _tail += f"，共{_n}条命中"
            body += _tail + "，完整内容见钉钉/详情页）"
        try:
            # JSON body 模式：标题含中文/emoji（HTTP header 仅 latin-1 会炸）
            # click：通知级点击跳转（缺了手机点 ntfy 通知就无任何反应）
            r = httpx.post(
                self.server,
                json={
                    "topic": self.topic,
                    "title": (title or "机票监控")[:120],
                    "message": body,
                    "priority": self.priority,
                    "tags": ["rotating_light", "bell"],
                    **({"click": launch} if launch else {}),
                }, timeout=15, trust_env=False)
            ok = 200 <= r.status_code < 300
            if ok:
                self.logger.info("ntfy 强提醒已发送: %s", title)
            else:
                self.logger.warning("ntfy 发送失败 %s: %s",
                                    r.status_code, r.text[:120])
            return ok
        except Exception as e:
            self.logger.warning("ntfy 发送异常: %s", e)
            return False


class WindowsToastNotifier:
    """Windows 10+ 系统右下角 Toast 通知（零依赖：经系统自带 PowerShell 调 WinRT）。

    达标强提醒的本机触达通道：无需联网、无需任何账号，人在电脑前即见即点。
    脚本经 -EncodedCommand（UTF-16LE Base64）传输——中文零乱码、引号零转义风险。
    任何失败静默降级（记日志），绝不影响主推送链路。"""

    # PowerShell 的已注册 AUMID（自定义 AppId 在未注册系统上会抛异常）
    APPID = ("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
             "\\WindowsPowerShell\\v1.0\\powershell.exe")

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.available = (os.name == "nt")

    @staticmethod
    def _ps_str(s: str) -> str:
        """PS 单引号字面量：内部单引号翻倍转义。"""
        return "'" + str(s).replace("'", "''") + "'"

    @classmethod
    def _script(cls, title: str, body: str, launch: str = "") -> str:
        launch_attr = ""
        if launch:
            # 点击通知 → 浏览器打开单条详情页（protocol 激活）
            launch_attr = (f"$x.DocumentElement.SetAttribute('activationType',"
                           f"'protocol')\n"
                           f"$x.DocumentElement.SetAttribute('launch',"
                           f"{cls._ps_str(launch)})\n")
        return (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
            "$x=[Windows.UI.Notifications.ToastNotificationManager]"
            "::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText04)\n"
            f"{launch_attr}"
            "$x.GetElementsByTagName('text').Item(0).AppendChild("
            f"$x.CreateTextNode({cls._ps_str(title)})) > $null\n"
            "$x.GetElementsByTagName('text').Item(1).AppendChild("
            f"$x.CreateTextNode({cls._ps_str(body)})) > $null\n"
            f"$app={cls._ps_str(cls.APPID)}\n"
            "$t=[Windows.UI.Notifications.ToastNotification]::new($x)\n"
            "[Windows.UI.Notifications.ToastNotificationManager]"
            "::CreateToastNotifier($app).Show($t)\n")

    @staticmethod
    def _plain(text: str, limit: int) -> str:
        """去 markdown 取纯文本：链接留文字（钉钉 KPI 行是 [**直飞 ￥x**](url)，
        原样进弹窗会带一长串 URL）、加粗/图片/仪表条/图例行剔除，
        行间以「；」相连。弹窗第二行可见高度有限，信息密度优先。"""
        import re as _re
        t = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text or "")
        t = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
        lines = []
        for ln in t.splitlines():
            ln = _re.sub(r"^[#>\-*\s]+", "", ln).strip().replace("**", "")
            if not ln:
                continue
            if _re.fullmatch(r"[🟦⬜🟩🟥🟨\s|]+", ln):
                continue                       # 仪表条/纯符号行（🟨 曾漏剥直进弹窗）
            if ln.startswith(("⏱", "⏳", "⚠")):
                continue                       # 时间戳/空窗/运维对账行（弹窗噪音）
            if ("进度条 =" in ln or "去哪儿查看" in ln
                    or "查看详情" in ln or "完整详情" in ln
                    or "查现价" in ln or "查价" in ln):
                continue                       # 图例/跳转行（弹窗本身就是提醒）
            # 四档图例行（🎯真达标 🟩破线 🟨擦边 超线）：emoji 计数
            # 式识别（≥2 档位点=图例）——曾按「破线+达标」双词
            # 同现，耦合措辞长度的教训（超宽降级丢段即整行漏进弹窗）
            if _is_legend_line(ln):
                continue
            lines.append(ln)
        body = "；".join(lines)
        # 🟩 转写词与 KPI/行3 行情注重复：同 _alert_body 转写前剥注
        # （P2-7 收口；加「行情破线」恰达线双词面同律）。
        # 有意差异备案（审校）：WinToast 是视觉弹窗通道，装饰
        # emoji（✈️📋 等）可显示有版式价值、不镜像 _alert_body 的装饰符
        # 剥离与 ↑↓ 转词——纯文本通道（ntfy/短信/TTS）才需要
        for _dup in _MKT_NOTE_DUPS:
            body = body.replace(_dup, "")
        # 残留单档位点转词（与 _alert_body 同律）：弹窗一闪
        # 而过 emoji 无解码，词面走 _EMOJI_TIER_WORDS 单源
        for _e, _w in _EMOJI_TIER_WORDS:
            body = body.replace(_e, _w)
        # 截断留痕（推送审校 P2-6）：钉钉/ntfy/短信均有截断
        # 纪律，弹窗通道独缺——第二行高度有限系 documented 设计，截尾
        # 至少留「已截断」词，防长 digest 静默丢尾被当全文（尾注无
        # U+2026：TTS 与 _plain 共用，… 播报「。。」定律同族）
        if len(body) > limit:
            body = body[:limit - 5] + "（已截断）"
        return body

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False,
             launch: str = "") -> bool:
        """launch 非空时：点击通知经浏览器打开该链接（如单条达标详情页）。"""
        if not self.available:
            return False
        try:
            import subprocess
            body = self._plain(desp, 180) or self._plain(title, 120)
            script = self._script(title[:120], body, launch)
            enc = base64.b64encode(
                script.encode("utf-16-le")).decode()
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-EncodedCommand", enc],
                timeout=20, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False)
            # 退出码非 0 = PS 脚本失败（AUMID 未注册等）：如实报 False——
            # 禁无条件 return True 把哑弹报成功，失败通道必须能浮出水面
            if proc.returncode != 0:
                self.logger.warning("[WinToast] 弹窗脚本退出码 %s: %s",
                                    proc.returncode, title[:50])
                return False
            self.logger.info("[WinToast] 右下角通知已弹出: %s", title[:50])
            return True
        except Exception as e:
            self.logger.warning("[WinToast] 弹窗失败: %s", e)
            return False


def build_urgent_notifier(cfg: dict, logger: logging.Logger):
    """达标专用强提醒通道列表（与普通推送分开，心跳不会吵）：
    ntfy（系统级弹窗+铃声）与 aliyun（云监控事件→电话/短信）可并联。"""
    outs = []
    wt = (cfg or {}).get("win_toast", True)   # 缺省开启（Windows 本机弹窗）
    if isinstance(wt, dict):
        wt = wt.get("enabled", True)
    if wt and os.name == "nt":
        outs.append(WindowsToastNotifier(logger))
    nt = (cfg or {}).get("ntfy") or {}
    if nt.get("enabled") and (nt.get("topic") or "").strip():
        outs.append(NtfyNotifier(
            topic=nt["topic"], logger=logger,
            server=nt.get("server") or "https://ntfy.sh",
            priority=nt.get("priority", 5)))
    ay = (cfg or {}).get("aliyun") or {}
    if ay.get("enabled") and (ay.get("url") or "").strip() and ay.get("user"):
        outs.append(AliyunAlertNotifier(
            url=ay["url"], user=ay["user"], password=ay.get("password", ""),
            logger=logger, rule_name=ay.get("rule_name") or "机票监控"))
    return outs or None


class AliyunAlertNotifier:
    """阿里云云监控事件通知通道（达标专用）：CRITICAL 级事件经联系人组
    触达电话/短信——电话 DING 的免费替代（同事提供的告警通道）。
    仅达标即时触发一次（风暴连推不重复拨打）。"""

    def __init__(self, url: str, user: str, password: str,
                 logger: logging.Logger, rule_name: str = "机票监控"):
        self.url = url.strip()
        self.user = (user or "").strip()
        self.password = (password or "").strip()
        self.rule_name = rule_name
        self.logger = logger

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False) -> bool:
        body_txt = _alert_body(desp or title)
        body_txt = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图]", body_txt)
        # 剥链接保文字（对齐 WinToast _plain 策略）：裸 URL 曾
        # 原文进短信——长 OTA 链接白占 900 字符额度且不可点
        body_txt = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body_txt)
        body_txt = _re.sub(r"https?://\S+", "", body_txt)
        body_txt = _re.sub(r"[#>*`\[\]]", "", body_txt).strip()
        if len(body_txt) > 900:
            # 截断留痕（钉钉/ntfy 同律）：短信触顶无痕迹会被当完整播报。
            # 纯文字尾注（推送审校）：emoji 在短信网关计费/显形
            # 不稳；无 …（P2-2）——TTS 播「。。。」定律同族
            body_txt = body_txt[:880] + "（已截断，完整内容见钉钉）"
        body_txt = body_txt or title
        try:
            # 中文全部 ASCII 转义传输（ensure_ascii），网关不可能解错编码；
            # JSON 解析后自动还原中文，短信不再乱码
            r = httpx.post(
                self.url,
                auth=(self.user, self.password),
                content=json.dumps(
                    {"ruleName": self.rule_name,
                     "title": (title or "机票监控达标")[:80],
                     "message": body_txt},
                    ensure_ascii=True).encode("ascii"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=15, trust_env=False)
            ok = r.status_code == 200
            if ok:
                self.logger.info("阿里云电话/短信告警已受理: %s", title[:50])
            else:
                self.logger.warning("阿里云告警失败 %s: %s",
                                    r.status_code, r.text[:120])
            return ok
        except Exception as e:
            self.logger.warning("阿里云告警异常: %s", e)
            return False


def build_notifier(cfg: dict, logger: logging.Logger,
                   base_url: str = ""):
    """根据 notifier 配置块构造推送器；未配置则返回 None。钉钉优先、
    Server酱为钉钉之外的备份（单选语义不变）；邮件与主通道并联
    （CompositeNotifier）——邮件无额度限制，可与钉钉同时启用。
    base_url：控制台地址，邮件 HTML part 整套快照的渲染源。"""
    if not cfg:
        return None
    primary = None
    dt = (cfg.get("dingtalk") or {})
    if dt.get("enabled") and dt.get("webhook"):
        primary = DingTalkNotifier(
            webhook=dt["webhook"],
            logger=logger,
            secret=dt.get("secret", ""),
        )
    if primary is None:
        sc = (cfg.get("serverchan") or {})
        if sc.get("enabled") and sc.get("send_key"):
            primary = ServerChanNotifier(
                send_key=sc["send_key"],
                channel=sc.get("channel"),
            )
    # 邮件渠道（多渠道）：emails 列表优先（每项=发件账号+
    # 收件人们，163/QQ 各配各的自发自收互不依赖），单对象 email 为
    # 兼容形态；两者同时在场以 emails 为准（防同账号双发）。
    # 形态防御：emails 非 list/项非 dict 一律忽略，
    # port 非数字回落 465，to 缺失同账号密码一并拦在装配门（免得
    # 每轮 send 空转 warning 却不落 push_history 不计连败）
    ems = cfg.get("emails")
    ems = [e for e in ems if isinstance(e, dict)] if isinstance(ems, list) else []
    if not ems and isinstance(cfg.get("email"), dict):
        ems = [cfg["email"]]
    email_ns = []
    for em in ems:
        try:
            port = int(em.get("port") or 465)
        except (TypeError, ValueError):
            port = 465
        # str() 兜底：手编 YAML 的 to 列表/纯数字
        # 授权码直取 .strip() 会 AttributeError，装配门自己不能成为
        # 启动崩点（旧代码 str() 传参不炸，门内同律）；to 数组 join
        # 成逗号串（str(list) 会带引号括号垃圾进收件人解析）
        to_v = em.get("to")
        to_s = (",".join(str(x) for x in to_v)
                if isinstance(to_v, list) else str(to_v or ""))
        if not (em.get("enabled") and str(em.get("user") or "").strip()
                and str(em.get("password") or "").strip()
                and to_s.strip()):
            continue
        email_ns.append(EmailNotifier(
            host=str(em.get("host") or ""),
            port=port,
            user=str(em.get("user") or ""),
            password=str(em.get("password") or ""),
            to=to_s,
            logger=logger,
            snapshot_base=(base_url or "").strip()))
    if primary and email_ns:
        return CompositeNotifier([primary] + email_ns, logger)
    if email_ns:
        return email_ns[0] if len(email_ns) == 1 else (
            CompositeNotifier(email_ns, logger))
    return primary
