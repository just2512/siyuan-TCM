# 真实笔记内容异常初筛

- 扫描文档：2667
- JSON 解析失败：0
- 提取文本总字符数：23059032
- 有异常信号的文档：308
- 段落级候选：726

## 信号分布

- CONTROL_CHARACTER_IN_TEXT: 4
- EXACT_DUPLICATE_PARAGRAPH: 198
- UNICODE_REPLACEMENT_CHARACTER: 11
- VERY_LONG_EXTRACTED_TEXT: 74
- VERY_LONG_PARAGRAPH: 5
- VERY_SHORT_EXTRACTED_TEXT: 71

## 输出

- content_anomaly_audit.csv：逐篇文本长度、段落数和异常信号。
- paragraph_anomaly_audit.csv：重复段落和超长段落，保留原笔记路径及段落序号。

## 判读边界

- 很短/很长文本不自动等于内容缺失或异常；容器文档、图片笔记、长篇讲义都可能合理。
- 完全重复段落可能来自原文引用、重复章节或导出结构，必须回到原始笔记核实。
- 本工具不做语义相似度判断、不改写笔记，也不将候选标记为错误。
