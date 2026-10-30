# -*- coding: utf-8 -*-
"""App 页面拦路物（广告 / 验证码 / 登录墙）的识别与分级。

**为什么单独成模块**：App 采集里最常见的失败不是"没数据"，
而是"页面被别的东西挡着"。若把它笼统记成 empty，就等于把"看不清"说成
"没票"——项目里最忌的账本说谎。

三类拦路物，处置完全不同：
  * **广告弹窗**：只是遮挡，关掉即可继续 → 可自动关（点击关闭类控件），
    关不掉就记 `ad` 并提示人工。
  * **验证码**：风控已经触发，**不做任何自动破解**（docs/CAPTCHA_SOLUTION.md
    的边界），记 `captcha`，开干预窗口让用户自己点。
  * **登录墙**：记 `login`，走登录流程（内嵌画面）。

识别只用文案锚点，不用坐标——同一条规则要能跨版本、跨分辨率生效。
"""
from __future__ import annotations

import re

# 调用方写账本时用的状态（与 AppCrawler.PATH_STATUS 对齐）
BLOCK_AD = "ad"
BLOCK_CAPTCHA = "captcha"
BLOCK_LOGIN = "login"
BLOCK_FACE = "face"
# App 自身卡死弹的系统「没有响应」对话框（ANR）。它不是数据状态、也不是
# 风控，而是可以**自愈**的临时故障：点「等待」让系统继续等它恢复。
# 实证根因：主线程 Blocked 在 Runtime.load0，等 DynamicSoManager 下载 so
# （BnFaceSoManager）时持有的锁——与我们的点击无关，撞上就会卡 25s 以上。
BLOCK_ANR = "anr"
BLOCK_NONE = ""

# ANR 对话框文案（点「等待」而不是「关闭应用」——后者会真的杀掉 App）
_ANR_MARKS = ("没有响应", "无响应", "isn't responding", "is not responding")
_ANR_WAIT = ("等待", "Wait", "稍候")

# 人脸/活体核验：生物特征，自动化既无法也不应伪造 → 只能本人操作。
# 这类门槛与验证码不同：验证码理论上人也能过且常是一次性的，
# 人脸往往绑定实名，属于"这条渠道在当前账号下不可自动化"。
_FACE_MARKS = (
    "人脸识别", "人脸验证", "人脸核验", "刷脸", "活体检测",
    "请正对屏幕", "请眨眼", "请张嘴", "请转头", "人脸认证",
)

# 验证码：不同厂商文案差别大，用"互斥度高"的词组合，避免误伤正文。
# **不收裸「验证码」**：登录表单上就有「获取验证码」「语音验证码」，
# 收进来会把登录墙误判成风控（去哪儿实测：登录页整页只有手机号输入框，
# 却被判 captcha → 走人工接管而不是让用户登录，处置完全错）。
_CAPTCHA_MARKS = (
    "请点击绿色数字", "请点击蓝色数字", "请点击红色数字",
    "请依次点击", "请按顺序点选", "向右滑动填充拼图", "拖动滑块",
    "滑块验证", "安全验证", "身份核实", "人机验证", "完成验证",
    "请旋转", "请选择所有", "图形验证码", "短信验证码已发送",
)
# 登录墙
_LOGIN_MARKS = (
    "登录后", "请先登录", "立即登录", "去登录", "登录解锁",
    "手机号登录", "验证码登录", "账号登录", "登录查看",
)
# 手机号登录表单的**结构性**标记（去哪儿实测）：整页只有输入框 + 获取验证码，
# 却同时挂着「¥35 机票券」这类营销数字——`has_payload` 会把它们当成
# 「已有日历价」，登录墙因此漏判、采集器白跑一轮还记成 empty。
# 这几个词只出现在登录表单上，不进正文，命中即判定为登录页。
_LOGIN_FORM_MARKS = ("请输入手机号", "获取验证码")
# 广告弹窗（可关闭的营销层）
_AD_CLOSE_MARKS = ("关闭", "跳过", "跳过广告", "我知道了", "以后再说",
                   "暂不开启", "残忍拒绝", "取消")
_AD_MARKS = ("新人专享", "限时", "活动", "领券", "红包", "专享",
             "大放价", "特惠", "立减")
# 真弹层的文案节点极少；功能页（机票首页/列表页）动辄几十上百。
# 阈值取 12：实测弹层 4–6 行，最简功能页也有 20+。
_AD_MAX_TEXTS = 12

_NODE_RE = re.compile(
    r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


class Block:
    """一次识别结果。"""

    __slots__ = ("kind", "detail", "close_xy")

    def __init__(self, kind: str, detail: str = "", close_xy=None):
        self.kind = kind          # ad / captcha / login / ""
        self.detail = detail
        self.close_xy = close_xy  # 广告弹窗的关闭按钮坐标（若有）

    @property
    def blocking(self) -> bool:
        return bool(self.kind)

    def __repr__(self):
        return f"Block({self.kind!r}, {self.detail!r})"


def _texts(xml: str):
    return [(m.group(1).strip(),
             (int(m.group(2)) + int(m.group(4))) // 2,
             (int(m.group(3)) + int(m.group(5))) // 2)
            for m in _NODE_RE.finditer(xml or "")
            if m.group(1).strip()]


def _close_button(texts):
    """在文案里找"关闭/跳过"类按钮，返回坐标。"""
    for want in ("跳过广告", "跳过", "关闭", "我知道了", "以后再说",
                 "暂不开启", "残忍拒绝"):
        for t, x, y in texts:
            if t == want:
                return (x, y)
    return None


def detect_block(xml: str) -> Block:
    """识别当前页面的拦路物。

    优先级：验证码 > 登录 > 广告。
    验证码放最前——验证码页上常同时挂着"登录"字样，先判登录会把
    "风控触发"误记成"该登录"，去重登也不能解决验证码。

    **登录只在"页面没有可采数据"时才算拦路**：真实航班页顶部本来就有
    「登录解锁更低价」横幅，但日历价照样能拿。若只看文案就把整页判成
    登录墙，会把"能采"误记成"要登录"——这是把好数据丢掉。
    判据因此是结构性的：有航班号/日历价 = 数据在，登录横幅只是提示。
    """
    if not xml or "<hierarchy" not in xml:
        return Block("", "no-ui")

    texts = _texts(xml)
    joined = " ".join(t for t, _, _ in texts)

    # ANR 最先判：整页只有系统弹窗（没有 App 内容），且它是**可自愈**的；
    # 判成别的会让人去做无意义的重登/关广告。处置=点「等待」。
    if any(m in joined for m in _ANR_MARKS):
        wait_xy = None
        for t, x, y in texts:
            if t in _ANR_WAIT:
                wait_xy = (x, y)
                break
        return Block(BLOCK_ANR, "系统无响应对话框", wait_xy)

    # 人脸最先判：它比验证码更"硬"——验证码人还能过，人脸必须本人，
    # 且一旦出现就说明该账号在此渠道已被要求实名活体，重试无意义。
    for mark in _FACE_MARKS:
        if mark in joined:
            return Block(BLOCK_FACE, mark, None)

    for mark in _CAPTCHA_MARKS:
        if mark in joined:
            return Block(BLOCK_CAPTCHA, mark, None)

    # 手机号登录表单：结构性命中，不看有没有"数字"——去哪儿登录页同时
    # 展示 ¥35/¥60 的机票券，按 has_payload 判会把登录墙当数据页。
    for mark in _LOGIN_FORM_MARKS:
        if mark in joined:
            return Block(BLOCK_LOGIN, "手机号登录表单：" + mark, None)

    # 先确认"有没有数据"，再决定登录横幅算不算拦路
    if not has_payload(xml):
        for mark in _LOGIN_MARKS:
            if mark in joined:
                return Block(BLOCK_LOGIN, mark, None)

    # 广告：营销词 + **页面不像正常功能页**才算拦路物。
    # 只看营销词会把机票首页判成广告（首页自带「返里程」「领券」入口，
    # 去哪儿实测整轮作废）；只看有没有关闭按钮则会把「关不掉的弹层」
    # 漏成无拦路（既有契约要求如实上报）。区分用页面规模：
    # 真弹层只有寥寥几行文案，功能页有几十个控件。
    has_ad_word = any(w in joined for w in _AD_MARKS)
    if has_ad_word and not has_payload(xml) and len(texts) <= _AD_MAX_TEXTS:
        close_xy = _close_button(texts)
        if close_xy:
            return Block(BLOCK_AD, "可关闭的营销弹层", close_xy)
        return Block(BLOCK_AD, "营销弹层（未找到关闭按钮）", None)

    return Block("")


def has_payload(xml: str) -> bool:
    """页面是否已经含有可采数据：航班号，或日历条上的真实价格。"""
    if not xml:
        return False
    if re.search(r"\b[A-Z]{2}\d{3,4}\b", xml):
        return True
    # 日历价：¥450 / ￥450（遮罩价 4?? 不算）
    return bool(re.search(r"[\u00a5\uffe5]\s*\d{2,5}", xml))


def is_page_blank(xml: str, min_nodes: int = 6) -> bool:
    """页面是否"空壳"——风控页失败后会退化成几乎无内容的页面。

    这不是 empty（没票），而是"页面没加载出来/被清空"，要单独表达。
    """
    if not xml or "<hierarchy" not in xml:
        return True
    return len(_texts(xml)) < min_nodes
