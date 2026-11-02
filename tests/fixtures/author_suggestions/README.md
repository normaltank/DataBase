# 作者建议的固定公开材料

本目录冻结2026-10-27的一份Crossref响应及四份ORCID公开响应；URL、取得时间、HTTP状态、大小和SHA-256见[清单](manifest.json)。原件只复制响应正文，传输头、Cookie、账号和凭据不在本夹具。2026-11-02复算五份原字节hash，与原采样清单相符；本轮没有重新请求原站或调用真实AI。

`06-crossref-online.raw`来自Crossref的BJE期刊作品接口。`crossref-doi-derived.json`仅将原响应`message.items[0]`放入单篇接口的`message`包装，供程序精确DOI接缝回放；它是有明确转换的衍生输入，不冒充另一次实际HTTP响应。两位作者顺序、Unicode姓名、各自ORCID、`authenticated-orcid=false`及各自文章单位保留原值。原响应文章级publisher不是作者任职证据。

HTTP回放预期分别为Alena Jechová／0009-0000-8922-637X与Martina Mysíková／0000-0002-6340-4753，对应两份person响应的given/family一致。采用前人物数与正式署名不变，人工采用后才建立关系。Alena的works原件`group=[]`不否定文章上的明确标识。Martina目标DOI位于`group[4].work-summary[0]`，source-name为Crossref；其中source-client-id是同步客户端，不能当作者ORCID，self不是本人认证，也不是第二独立出版来源。程序当前取person作为可选核对材料，不据公开works计数推断身份或影响力。

软件负例由这些材料或完全合成页面人为构造，明确标作派生控制，不声称原站出现相同错误。个人主页正例及任职直接句式仅经合成的“文章明确链接＋取得主页”成对页面验证；本轮没有真实成对主页原件，不证明原站覆盖、现实身份认证、自然语言全部语义、研究结论或真人跨人接续。
