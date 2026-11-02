# 国家与地区名称词表

本目录随应用分发，运行时只读，不需要联网或额外 Python 依赖。`countries.py` 是查询身份与中文展示的唯一规则入口；词表不修改来源、资料、任职、历史或导出原字段，也不判定领土地位、作者国籍或现实身份。

主源为 Unicode CLDR JSON **48.0.0** 的 [英文名称](https://github.com/unicode-org/cldr-json/blob/48.0.0/cldr-json/cldr-localenames-full/main/en/territories.json)和[简体中文名称](https://github.com/unicode-org/cldr-json/blob/48.0.0/cldr-json/cldr-localenames-full/main/zh/territories.json)。采用 CLDR 稳定地域代码作为匹配键，收录双字母条目及其明确短名／变体，排除测试区域 XA、XB 和未知 ZZ。CLDR 同时含国家、属地和组织，代码不表示它们是同一种业务对象。Asia（142）、Arctic、Western Balkans 各自作为独立地区；EU、EZ 沿用各自代码。历史 Yugoslavia 和 Socialist Republic of Macedonia 使用独立历史键及明确中文译名，不并入任何现行国家。

上游下载原字节 SHA-256：英文 `158c1d575308f7e46912edbeda435c8fe2ef5dad280798231f3a432e406b1807`；中文 `18f1426f1e8981a671517a4857a8d4e56060909906c4cfd9b9a43a8a18b9ab6f`。本地派生版本写在 `territories.json`。上游授权为 [Unicode-3.0](LICENSE-UNICODE.txt)，完整许可随词表保存和分发。

等价比较仅去除首尾空白并忽略大小写，不做模糊匹配或 AI 猜测；未识别词保留原拼写用于展示，只对大小写等价匹配。新增别名须有确定依据，修改词表后运行国家 HTTP 回归及相关列表、导出、保存检索和批次恢复检查；旧冻结查找优先复用原条件的成员，不重算历史成员。
