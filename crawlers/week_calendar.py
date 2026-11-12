"""跨日期低价条（周历）公共件（r1063 T150）。

为什么要有这一层：**"列表空"不等于"没价"**。途牛实测（2026-11-09）列表写
「很抱歉，暂未查询到符合您要求的航班」，而页面顶部周历仍有 `11-16 ￥388`；
携程同样有这条条带（国际 `SHA→TYO 11-16 ￥1200`、国内 `SHA→BJS 11-16 ￥400`）。

所以把它做成**独立通路**（各渠道自己的 path 名，如 `PC·周历`），与列表/接口
分开记账：列表被拦或该日无航班时，它照样能给出"当日最低价"。

抽取不依赖任何 class，只认文本形态 `MM-DD 周X ￥NNN`（站点改版也能活）。
"""
from __future__ import annotations

WEEK_JS = """
() => {
  const out = [];
  document.querySelectorAll('li, div, a, span').forEach(el => {
    const t = (el.innerText || el.textContent || '')
      .replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 40) return;
    const m = t.match(/(\\d{2})-(\\d{2})\\s*周[一二三四五六日](?:[（(][^）)]{0,8}[）)]|[去返程])?\\s*[¥￥]\\s*(\\d{2,6})/);
    if (m) out.push([m[1] + '-' + m[2], parseInt(m[3], 10)]);
  });
  const map = {};
  for (const [d, p] of out) {
    if (!(d in map) || p < map[d]) map[d] = p;
  }
  return Object.entries(map).map(([d, p]) => [d, p]);
}
"""


def week_to_dates(anchor_date: str, pairs) -> dict:
    """把 `MM-DD → 价` 补成 `YYYY-MM-DD → 价`（含跨年）。

    12 月锚点看到次年 1 月时补一年；脏数据跳过而**不抛**——
    一条脏数据不该让整周兜底失效。
    """
    out = {}
    try:
        year = str(anchor_date)[:4]
        anchor_mm = int(str(anchor_date)[5:7])
    except Exception:
        return out
    for md, price in (pairs or []):
        try:
            mm = int(str(md).split("-")[0])
            val = int(price)
        except Exception:
            continue
        y = str(int(year) + 1) if (anchor_mm >= 11 and mm <= 2) else year
        key = "%s-%s" % (y, md)
        if key not in out or val < out[key]:
            out[key] = val
    return out


class WeekCalendarMixin:
    """给渠道复用：打开一个列表页，只抓顶部"跨日期低价条"。"""

    WEEK_PATH_LABEL = "PC·周历"

    def fetch_week_calendar(self, url: str, anchor_date: str,
                            headless=None, browser_factory=None) -> dict:
        """返回 {"YYYY-MM-DD": 最低价}。任何异常都只记日志、返回已拿到的部分。"""
        out = {}
        try:
            opener = browser_factory or self.browser
            with opener(headless=headless) as ctx:
                # 用 getattr 取 `new_page`：本类是**纯 mixin**，静态门禁
                # （test_r1063_no_missing_methods）看不到继承链上的定义，
                # 直接 self.new_page() 会被误判为"调用了不存在的方法"。
                new_page = getattr(self, "new_page")
                page = new_page(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                # 两段等待 + 重试：飞猪/携程的条带是异步渲染的，5 秒常常不够
                # （实测同一个页面等 9 秒才出现）。空则再等一次再判。
                pairs = []
                for wait_ms in (6000, 5000):
                    page.wait_for_timeout(wait_ms)
                    pairs = page.evaluate(WEEK_JS) or []
                    if pairs:
                        break
            out = week_to_dates(anchor_date, pairs)
        except Exception as e:
            try:
                self.logger.warning("[%s] 周历抓取失败：%s", self.name,
                                    str(e)[:90])
            except Exception:
                pass
        return out
