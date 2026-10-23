# 拉脱维亚试点资料只读核查

核查日期：2026-10-21。用户指定目录 D:\Agent Workspace\ThinkTank。此次只读检查现有文件，未执行其中程序，未修改资料，未联网重验来源链接。未找到适用的 AGENTS.md。

## 初始导入候选
主资料库：D:\Agent Workspace\ThinkTank\PaperDatabase\LatviaResearchDatabase。

- 02_Source_Registry\sources.csv：64 条不同来源编号，混有智库、大学、下属单位、期刊、发现门户、历史机构及境外合作方，不能直接称为64家拉脱维亚智库。
- 02_Source_Registry\serials.csv：79 条不同连续出版物编号，包括期刊、年鉴、工作论文系列、会议论文集及待核候选，不能直接称为79种本地期刊。
- 02_Source_Registry\publication_channels.csv：54 个发布栏目。
- 03_Bibliography\records.csv：496 条不同资料编号，包括论文、报告、章节、会议摘要、书籍容器和范围外保留记录，不能直接称为496篇可入库论文。
- 03_Bibliography\attachments.csv：290 条不同附件登记，登记路径对应文件实际存在。附件内容质量和传播权限此次未重验。

## 可沿用的基础
来源已有原名、英文名、中文工作译名、类别、所在地、官网、出版目录、范围关系和核验状态；连续出版物有主办方、出版方、合作平台、刊号及目录。另有机构关系、文献关系及作者所属机构表。

01_Plan_and_Schema\source_adjudication.md 已区分本地机构成果与本地期刊，可供后续判断来源关系时参考，不将其中每项既有规则自动视为本项目已批准设计。

## 待整理事项
- sources 的“来源”不是纯粹机构集合，应先识别对象类型，再映射到新方案。
- serials 的连续出版物不全是期刊；需区分期刊、年鉴和报告系列。
- 研究覆盖范围、单篇资料研究对象国尚未见清晰独立字段，部分内容在说明文字中。
- 来源目录、中文工作译名、译题、摘要等存在空值，不承诺初始资料全部有完整中文内容。
- 尚未见能直接满足中心分级权限和传播授权的完整字段。
- README 中部分统计已经过时，数量以现行主表为准。

## 可选真实样本
均见 03_Bibliography\records.csv，此次仅核查本地数据，不等于重新验证外部网页。

1. LV-PROVIDUS-2026-PARTIJU-SKIROTAVA：PROVIDUS 政党与选民分析，有原文链接和本地结果报告附件，可演示智库—资料—附件。
2. LV-LEGACY-2CC3B1FC9DB89D1B：SOCRATES 期刊中的 Fundamental rights under geopolitical pressure…，有期刊、机构、日期、作者及本地 PDF，可演示机构—期刊—论文。
3. LV-FOCSU-2026-1751387：Baltic Studies Centre 相关研究发表于 Frontiers in Ocean Sustainability，标记为境外发表成果，可验证本地作者机构不等于本地期刊。

## 材料使用边界
ThinkTank 内还有 Compile 编译稿及专题报告文件，尚未确认哪些成果应纳入中心共享范围。MyPaper 包含个人研究材料，未阅读内容。初始导入应从主资料库选定条目及附件开始，不将整个目录直接导入共享系统。
