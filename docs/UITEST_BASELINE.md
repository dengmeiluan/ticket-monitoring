# UI 自检基线

> 这份文件是**入库的、小而稳的**信号：UI 自检（`python docs/uitest.py`）当前有多少条断言、
> 最近一次全绿是哪一天/哪棵源码树。
>
> 运行产物 `docs/uitest_result.txt` **不入库**（每次运行都变，见
> `docs/GENERATED_ARTIFACTS.md`）；`docs/release_align_check.py` 读的是本文件。
> 发版前请把下面两行更新为本次结果。

- 断言数：690
- 最近一次全绿：690/690（2026-11-12，发版提交见 Release 页的 `v1.0`）
1.0\）

## 怎么更新

```bash
python docs/uitest.py                      # 必须 690/690、JS 错误 0
# 然后改上面两行：断言数 = 通过数；日期 = 今天；SHA = git rev-parse --short HEAD
```
