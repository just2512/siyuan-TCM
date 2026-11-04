# 索引质量检查记录

## 首轮全量扫描结果

首轮自动生成的索引覆盖 2,667 篇 .sy 文档，全部通过 JSON 解析；共提取 5,309 条附件引用。按原始文件 SHA-256 比对，没有发现完全相同的文件组。SHA-256 检查不能识别改写、节选或语义重复。

## 首轮发现并已修正的提取问题

抽查真实 .sy 文件后确认，思源正文并不主要存放在通用的 text/content 字段，而是以块节点形式保存，例如 NodeTextMark.TextMarkTextContent。首版提取器把部分 Properties 标题（如“笔记”）当作文档标题，也把 NodeKramdownSpanIAL 中的样式属性混入正文检索片段。

已在索引工具中调整：

- 正文抽取读取 TextMarkTextContent 和文本节点 Data；
- 不递归 Properties 元数据；
- 排除名称包含 IAL 的节点，避免样式标记污染正文；
- 文档 Properties.title 为“笔记/无标题”等通用值时，以首条可见正文作为导航标题回退；该回退值不是经人工核验的正式标题；
- 移除过宽的“汤/散/丸”单字主题触发词，减少方剂标签泛化；
- 增加 notebook-map.json，把目录 ID 显示为笔记本名称。

## 验证状态

- 首轮 2,667 篇全量扫描：已执行。
- 提取器修正后的全量重新生成：待工作流执行后验收。
- 工具单元测试：已加入并接入 GitHub Actions；需以最新一次 Actions 运行结果为准。
- 本地 assets 文件存在性：未检查。当前附件清单只证明文档中存在 5,309 条引用。

## 重新生成

在 GitHub 仓库 Actions 页面运行 Build and commit TCM catalogue。工作流先执行 tools 下的单元测试，再重新扫描并将结果提交到 catalog/generated/。
