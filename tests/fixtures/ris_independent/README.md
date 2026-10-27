# #36 独立 RIS 合成验证包

本文件下文保留 2026-10-27 实现前独立制样时的说明快照；“未改仓库”“待 #52”描述制样时状态。现已随 #52 保存安全合成输入、固定期望和 reader 脚本，未包含 `_vendor` 或数据库。当前复跑从仓库根目录执行 `python -m pip install -r requirements-test.txt`、`python -m unittest tests.test_ris_export -v`；浏览器实际下载验证见根 README。`expected.json` 保持制样时 SHA-256 `6849e5ad000d32eef2846d2b8ba071ac5040f260d6bde0247035dd4c10da7e7e`，不按实现输出改写。TT 与 N1 的当前输出契约及额外断言见根 README、`tests/test_ris_export.py`。下文的临时路径仅原制样环境可查。

路径：C:\Users\27451\AppData\Local\Temp\database-ris-independent-fixtures

规格 1.0，提交 d9129c294f428c61227dcb62c9a0f2389d4653eb。2026-10-27。
Agent-authored fixed synthetic literals, independently prepared before application implementation review.
这些固定样本由 Agent 编写，不是真人样本或真人复核。未读取真实库或研究材料，所有题名、姓名、单位和路径为合成；example.invalid 不应访问。

## 样本与期望

- 01_core_utf8_lf.ris：5 条 JOUR/RPRT/WEB/ELEC/GEN，多语题名、两名含逗号与变音符的姓名、机构单条署名、年/年月/完整日期、页段/文章号、多 SN。
- 02_core_bom_crlf.ris：01 的 BOM+CRLF 变体，语义相同而字节、文件摘要不同。
- 03_alias_conflicts_unknown.ris：题名/刊名/日期/摘要别名冲突，AU/A1 交错及重复姓名，重复 SN/KW、未知 X1、PB/AD/L1。固定原始保留与警告义务，不猜 #51 未在规格中写明的别名赢家。
- 04_unsupported_book_and_valid.ris：BOOK 未支持，后续完整 JOUR 单独可处理。
- 05_invalid_date_and_missing_title.ris：非法日期和缺题名，不得补造。
- 06_unterminated_structure.ris：完整前缀及缺 ER 后缀，不得静默丢损坏部分。
- 07_nested_ty_structure.ris：嵌套 TY，结构不能可靠分段，要求明确拒绝。
- 08_reference_standard_export.ris：Agent 固定规范参考输出，仅供验证工具自检，不是应用输出或验收。
- 09_translated_title_reader_probe.ris：独立读取 TI/TT 的技术探针，不扩展冻结导入契约。
- 10_negative_changed_title_export.ris：故意改错题名的负对照，完整校验必须失败。
- expected.json：独立固定语义、原始/警告义务、core 与 resolved_conflict 导出期望、题名技术建议和未知项。未调用生产 parser/writer 生成期望。
- verify_independent.py：只用隔离 rispy==0.10.0 的 reader，读取明确指定的合成导出文件；不导入应用模块、不读SQLite。
- rispy-observations.json：实际 reader 和工具自检结果。
- manifest.json：SHA-256，检查文件一致性，不能证明研究材料真实。

## #52 使用入口

自检：

    python C:\Users\27451\AppData\Local\Temp\database-ris-independent-fixtures\verify_independent.py --self-check

按 expected.json/core 的 setup 将 01 或 02 导入临时应用库，保持题录不变，按原队列顺序选中五条并下载实际 RIS，再运行：

    python C:\Users\27451\AppData\Local\Temp\database-ris-independent-fixtures\verify_independent.py C:\explicit-synthetic-export.ris --case core

人工修订优先于原始依据：导入 03，按 expected.json/export_cases/resolved_conflict 明确修改并清空其他字段，保存、选择该条、下载，然后用同一入口加 --case resolved_conflict。

脚本不查找库或自动发现文件。明确传入的路径必须是合成测试输出。当前 PASS 只验证样本与工具自身，不能记作 #52 已完成；仍需 HTTP 权限、重复、历史/完整恢复和实际浏览器验收。

校验器要求规范 UTF-8 无 BOM、CRLF 含末行换行、平衡 TY/ER 和标准输出标签。字段由独立 rispy 读取，小结构守卫只作补充，不替代应用 parser。TI/T1 等别名只作一致性归一化，冲突会失败。
N1 已放入标准允许集合，避免未来用于明确原题名时产生白名单伪失败；N1 文本的实际契约及逐值断言待 #52 冻结。不能把允许 N1 等同已验证其语义。核心样本无 AU/A1 交错顺序歧义。若 #52 选用另一种合法输出表达，应先说明契约差异，不可按实际输出倒写固定期望。

## 已实测的 rispy 0.10.0 局限

- 默认重复 SN 保留第一个值，不是最后值；SN 不在默认列表标签内。公开 list_tags 加 SN 后保留全部值和重复项。
- AU/A1、TI/T1、JF/JO/T2、PY/Y1/DA、AB/N2 分别映射不同键；默认返回不等于平台映射。
- 默认可读 BOOK，不执行平台类型、身份、日期、题名或权限规则。
- 截断样本06默认仅返回完整首条，嵌套TY样本07默认吞成一条，均不足以通过平台结构验收。
- 默认 UR 用分号分割；本工具显式关闭 delimiter 映射，保全合法 URL 分号。
- BOM 由工具 UTF-8-sig 解码明确移除，不声称 reader 默认处理所有编码。
- TI 与 TT 已实测分别读入 title 与 translated_title，不代表所有消费者保留 TT，也不代表导入 TT 自动成为已采用中文。

## 题名技术建议

rispy 官方固定配置：
https://github.com/MrTango/rispy/blob/b7aae3b2069ced3fb75287711300f2edf0bcac21/rispy/config.py

TT 对应 translated_title；TI/T1 不能冒作不同语言标题。EndNote 官方 Generic 字段包括 Translated Title：
https://docs.endnote.com/docs/endnote/2025/v1/windows/en/content/17reftypes/the_generic_type.htm

建议 TI 输出当前 title，若 #52 明确支持 TT 则输出当前人工已采用 chinese_title；original_title 与 title 不同可用明确 N1 文本保留，并由内容包完整保全。机器未采用译文不输出，禁止回读旧 raw 补当前空字段。此为技术建议，具体三字段契约仍由 #52 审阅确定。
Clarivate 当前每类型RIS标签附件未取得，本轮不宣称原厂已确认所有类型TT映射。RIS不承担全部内部语言版本、采用责任和历史。

## 隔离依赖

实际仅在本目录安装：

    python -m pip install --target C:\Users\27451\AppData\Local\Temp\database-ris-independent-fixtures\_vendor --no-deps --disable-pip-version-check rispy==0.10.0

官方来源：https://pypi.org/project/rispy/0.10.0/
官方 wheel SHA-256：acc8b941ab5e7b65b5365e468af2e00f0cb031a9e5c5a6b06538d856151e61be
官方发布提交：b7aae3b2069ced3fb75287711300f2edf0bcac21

未改仓库依赖、应用代码或生产解析器，未跑应用测试，未启动导出施工。
