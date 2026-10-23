# Issue tracker: GitHub

任务入口为 [normaltank/DataBase Issues](https://github.com/normaltank/DataBase/issues)，仓库标识为 `normaltank/DataBase`。本配置于 2026-10-23 经用户确认采用 GitHub Issues。

## 文档与任务的分工

- PRODUCT.md 定义产品规则，GLOSSARY.md 维护业务词义，已确认的实现规格沿用 docs/specs/。Issue 记录可执行任务、范围、验收条件、依赖及相关规格链接。
- 发布规格或拆分任务时，先核查现有文档与 Issue；复用已有条目，保留必要的自包含施工说明，避免另建相互冲突的权威版本。业务决定按 AGENTS.md 同步到对应文档。
- 技能要求“发布到任务跟踪器”时，在本仓库创建或更新 Issue；要求“获取任务”时，读取 Issue 正文、标签、评论、依赖及其引用的规格。
- Issue 是否可执行与本轮派工范围分别判断，继续遵循 AGENTS.md 的指挥与用户澄清约定。

## 操作方式

优先使用当前会话提供的 GitHub 工具；缺少对应能力时使用已认证的 GitHub REST API，或在已安装、已认证时使用 `gh`。安装了 Git 不代表已经安装 GitHub CLI。

- 创建：先搜索相同任务，再提交标题、正文和已配置标签；保存返回的编号与链接。
- 读取：读取正文、状态、标签和评论。列表有分页时继续读取，直到覆盖本次任务所需范围。
- 修改、评论和关闭：先读当前内容，保留已有讨论；完成后写明交付及验证依据。
- 标签：按 triage-labels.md 添加或移除对应标签，不覆盖无关标签。
- 使用 `gh` 时显式指定 `--repo normaltank/DataBase`。多行正文先写文件，再用 `--body-file`，避免命令转义改变正文。

## 父子任务与依赖

使用 GitHub 原生子任务和阻塞关系；操作所需的数字数据库 ID 与界面上的 #编号分别理解。仅在当前工具或仓库不支持原生关系时，改用父任务正文的清单与子任务顶部的 `Part of #编号`、`Blocked by: #编号`，并保持两边一致。

只有阻塞项已经解决、范围与验收条件明确且符合当前派工的任务，才进入施工。wayfinder 的地图和子任务也使用这套关系；相关专用标签在实际运行该技能时再按需创建。

## Pull requests as a triage surface

**PRs as a request surface: no.**

## 公开内容边界

本仓库及 Issues 为公开。发布代码、产品文档、脱敏复现步骤和验收摘要；内部研究材料、真实账号凭据、数据库及附件保留在本地。已有本地计划和验收记录继续作为历史，不在 setup 阶段批量转成 Issues。
