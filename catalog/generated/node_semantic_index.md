# SiYuan 节点语义索引

- 扫描文档：2667
- JSON 解析失败：0
- 节点记录：727584
- 可检索内容块：236987
- 可追溯关系边：10502
- 节点类型：27
- 有直接文本载荷的节点：334657
- 已定义字段语义映射：22
- 未映射字符串字段：0

## 节点类型分布

- NodeAudio: 1
- NodeBackslash: 254
- NodeBackslashContent: 226
- NodeBang: 10101
- NodeBr: 9788
- NodeCloseBracket: 10101
- NodeCloseParen: 10101
- NodeDocument: 2667
- NodeHTMLBlock: 1
- NodeHeading: 11861
- NodeImage: 10101
- NodeKramdownSpanIAL: 47795
- NodeLinkDest: 10101
- NodeLinkText: 10101
- NodeList: 268
- NodeListItem: 776
- NodeOpenBracket: 10101
- NodeOpenParen: 10101
- NodeParagraph: 224107
- NodeTable: 506
- NodeTableCell: 5474
- NodeTableHead: 506
- NodeTableRow: 5248
- NodeText: 249962
- NodeTextMark: 76142
- NodeThematicBreak: 11179
- NodeVideo: 15

## 关系类型分布

- BLOCK_REFERENCE: 72
- HYPERLINK: 313
- LINK_DESTINATION: 10101
- MEDIA_REFERENCE: 16

## 关系解析状态

- ASSET_REFERENCE: 10100
- EXTERNAL_URL: 243
- REFERENCE_RECORDED_NOT_FILE_VERIFIED: 16
- RESOLVED_IN_CORPUS: 72
- URI_OR_LOCAL_TARGET: 71

## 生成文件

- node_semantic_index.csv.gz：gzip 压缩的逐节点语义索引；解压后为 UTF-8 CSV，保留块 ID、父节点、树位置、文本及非正文资源字段。
- content_block_index.csv.gz：gzip 压缩的段落/标题/表格单元格/列表项/HTML 块全文索引，附带当前标题路径和标题块 ID，可直接用于检索和定位。
- node_relationship_index.csv.gz：gzip 压缩的块引用、超链接、附件目标和媒体引用关系边。
- document_semantic_summary.csv：逐文档节点覆盖、文本载荷、表格/列表/HTML/媒体节点和可检索内容块统计。
- node_field_mapping.csv：已知节点字段到语义角色的映射及是否进入正文索引。
- unmapped_node_fields.csv：尚未映射的字符串字段，供继续扩展解析器。

## 解析边界

- 原始 .sy 文件只读；所有索引记录包含原文件 SHA-256、相对路径和块定位。
- HTML 同时保留原始值和剥离标签后的可见文字；媒体地址、附件目标、图片布局不混入正文。
- 表格、列表和标题保留节点层级及父子关系；容器聚合文本只作导航，不能替代单元格/列表项节点记录。
- 未映射字段不会自动拼入正文，避免把样式、资源路径或内部元数据污染为可检索文本。
