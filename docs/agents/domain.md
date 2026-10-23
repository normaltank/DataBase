# Domain Docs

本项目采用 **single-context（单上下文）**，沿用根目录 GLOSSARY.md。重要取舍的 ADR 在确有需要时存入 docs/adr/，不为 setup 先造决策记录或重复术语表。

## 读取与维护

- 运行领域梳理、讨论术语或解释业务关系前，读 [GLOSSARY.md](../../GLOSSARY.md)。涉及产品行为时，按 [AGENTS.md](../../AGENTS.md) 读取 PRODUCT.md 和当前任务的规格。
- 涉及既有重要取舍时，读取 docs/adr/ 中与任务有关的记录；目录或文件尚不存在时直接继续。
- Issue 标题、规格、测试和讨论使用术语表中的业务词义；遇到真实歧义交由 domain-modeling 或 grill-with-docs 澄清，决定后更新唯一维护处。
- 值得长期保留的重要取舍才写 ADR，并记录理由和影响；日常实施记录仍放在原有施工及验收文档中。
- 新建议与已有产品规则、规格或 ADR 不一致时，明确指出差异与影响，依照 AGENTS.md 处理，不以新配置覆盖业务共识。

当前不建立 GLOSSARY-MAP.md，也不拆分多个领域上下文。将来只有出现实际独立的业务边界与多包结构，再重新评估。
