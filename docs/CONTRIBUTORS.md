# 贡献者

这个项目接受外部贡献，并且**把每个人的名字记下来**。本文件是唯一名单：
`tools/sync_contributors.py` 会从 PR 列表**去重**生成下面的表格，防止漏人。

## 署名怎么落地（为什么要这么绕）

初版约束要求公开发布历史是**单一 root commit**（仓库首页只显示一笔、文件列表不夹杂
他人的过程提交）。而 GitHub 的 Insights → Contributors 榜单**只统计 commit 的 `author`**
——一笔提交只能有一个作者。两者无法同时满足，所以我们的做法是：

| 手段 | 谁看得到 | 何时更新 |
|---|---|---|
| 提交正文 `Co-authored-by:`（每条贡献者一条） | 打开该提交的人、`git log` | 随提交 |
| 本文件表格（PR 列表去重生成） | 仓库内可见、可 diff | 每次发版/提交前跑工具 |
| `README` 的「贡献者」一段 | 仓库首页 | 同上 |
| GitHub Contributors 榜单 | 侧栏 | **GitHub 自己的缓存节奏**，不由我们控制 |

关于最后一条的实测：`Flobby949`、`1Wizzy` 的提交早已不在 `main` 里（历史收敛掉了），
但侧栏仍然显示他们；`Shengcun-Scanner` 在我们把提交作者改成带账号 ID 的 noreply 后出现；
`ismoss` 已在 `GET /repos/…/contributors` 里（`ismoss 1`），但侧栏还没刷新。
结论：那份榜单是**缓存 + 历史统计**，不能作为"是否认账"的判据——本文件才是。

## 怎么加新的人

```bash
python tools/sync_contributors.py            # 对账：PR 作者是否都登记了
python tools/sync_contributors.py --write    # 按 PR 列表重写下面的表格（去重）
python tools/sync_contributors.py --strict   # 漏人就非零退出（guard/CI 用）
```

贡献者本人的改动入库时，请保留其作者身份（`git am` / `git cherry-pick` 或 GitHub 的
Rebase/Squash merge 都会保留），并在提交正文里写 `Co-authored-by:`；随后跑一次 `--write`。

## 名单（自动生成，勿手改）

<!-- CONTRIBUTORS:TABLE:BEGIN -->
| 贡献者 | 署名方式 | PR |
|---|---|---|
| [@1Wizzy](https://github.com/1Wizzy) | 历史贡献（已随 PR 合入，作者提交在早期历史中） | #13 |
| [@Flobby949](https://github.com/Flobby949) | 历史贡献（已随 PR 合入，作者提交在早期历史中） | #5、#6、#7 |
| [@Shengcun-Scanner](https://github.com/Shengcun-Scanner) | 作者提交（`git log --author=Shengcun-Scanner`） | #17 |
| [@ismoss](https://github.com/ismoss) | 作者提交（`git log --author=ismoss`） | #20 |
<!-- CONTRIBUTORS:TABLE:END -->
