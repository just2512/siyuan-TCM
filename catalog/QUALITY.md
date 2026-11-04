# 索引质量检查记录

## 已完成的全量索引复建

2026-11-04，GitHub Actions 生成提交 `98d4f250b3836e5476b6a9a84be98f8d6ded2ac3` 已回写 `master`。提交差异包含标题回退修正和笔记本 ID 到可读名称的映射结果，说明修正后的提取器已参与全量生成。

该次生成的 `catalog/generated/catalog.md` 明确记录：

- .sy 文档：2,667 篇；
- JSON 解析：2,667 篇 PARSED，未出现 RAW_FALLBACK；
- 附件引用：5,309 条；
- 完全相同文件内容组：0；
- 7 个笔记本目录均显示为可读名称；
- 未提供本地 assets，因此 5,309 条附件引用均为 NOT_CHECKED，不代表缺失。

生成提交由 `github-actions[bot]` 创建。工作流定义为先执行 `python -m unittest discover -s tools -p 'test_*.py' -v`，再生成索引，最后提交结果；因此该次任务至少已越过测试步骤并完成生成、回写。当前连接器没有提供该次 Actions 的逐步骤日志，故不把它描述为已取得独立日志级测试报告。

## 已修正的提取问题

抽查真实 .sy 文件后确认，思源正文包含 `TextMarkTextContent` 等块节点字段。工具已调整：

- 正文抽取读取 `TextMarkTextContent` 和文本节点 `Data`；
- 不递归 Properties 元数据；
- 排除 IAL 样式元数据；
- 通用标题“笔记/无标题”等使用首条可见正文作为导航标题回退；
- 使用 notebook-map.json 显示笔记本名称；
- 收窄部分过宽的方剂关键词。

## 当前已知质量风险

1. **标题尚未逐篇人工核验。** 通用标题回退到正文首行只是导航标题，不等于正式标题。
2. **主题标签仍是字符串包含式关键词初筛。** 一篇长篇课程笔记可能命中多个主题；多主题不自动等于错误，但必须复核命中词和上下文。
3. **空正文不能直接判定为坏文档。** 可能是空白文档、图像/附件型文档，也可能是提取器尚未覆盖的节点结构。
4. **来源、版本、校勘状态尚无可信结构化证据。** 不从文件名、讲者名或关键词自动推断出处及版本。
5. **assets 未检查。** 需要用户本地 assets 目录才能做引用映射；仓库不会复制或上传附件。

## 新增人工核验队列

新增 `tools/build_siyuan_review_queue.py` 和对应单元测试。工作流现计划在生成 documents.csv 后继续生成：

- `document_review.csv`：逐篇标题、正文、来源、版本、校勘状态；
- `topic_review.csv`：多主题命中的关键词证据和正文片段；
- `review_queue.md`：核验队列概况与边界。

所有来源/版本字段初始化为 UNVERIFIED，标题与校勘状态初始化为 NOT_REVIEWED。该队列用于安排人工复核，不会伪造医学出处或校勘结论。

## 验收边界

- 文件结构索引与医学内容真实性、出处校勘是两项独立工作。
- 自动主题标签仅用于检索导航，不可作为辨证、处方或临床决策规则。
- SHA-256 只能识别文件字节完全一致，不能识别改写、节选或语义重复。
- 索引生成不改变原始资料的版权、授权及使用限制。


## 标题来源与主题证据边界（2026-11-04 后续修订）

- documents.csv 新增 title_source：PROPERTY 表示读取到思源 Properties.title；BODY_FIRST_LINE 表示通用标题回退到正文首行；FILENAME 表示正文为空时回退文件名；RAW_FILENAME 表示 JSON 无法解析时使用文件名。
- 正文首行和文件名回退仅供导航，不应作为已核验书名、篇名或原始标题。
- topic_review.csv 新增 catalog_topics 与 evidence_scope。分类标签由完整正文计算，但复核队列只能使用 documents.csv 保存的前 2000 字检索片段展示关键词证据；未在片段中出现的词不代表分类器没有命中。
- 逐篇来源、版本及校勘仍为 UNVERIFIED / NOT_REVIEWED；标题来源可追溯不等于标题内容已人工核验。


## 逐篇核验队列实测结果（2026-11-04）

最近一次全量生成提交：`6062d33972b03f6328343bf465df13d110978523`。对应工作流：<https://github.com/just2512/siyuan-TCM/actions/runs/41819737909>，测试、索引生成、核验队列生成和提交均完成。

- 2,667 篇文档；33 篇正文抽取为空；5,309 条附件引用仍为 NOT_CHECKED。
- 标题来源：PROPERTY 2,662 篇；BODY_FIRST_LINE 5 篇。未出现 FILENAME 或 RAW_FILENAME 回退。
- 多主题复核队列 1,425 篇：5_PLUS_TOPICS 153 篇；3_TO_4_TOPICS 650 篇；2_TOPICS 622 篇。这些是按主题标签数量分组，不代表错误程度。
- `topic_review.csv` 将标题命中词与前 2,000 字正文片段命中词分开记录。完整正文分类与有限片段证据范围不同，不能将片段中未显示某个词解释为分类器未命中。
- 新增 `empty_body_review.csv`，单独列出 33 篇空正文文档，含原始路径、标题来源、解析状态、文件字节数和附件引用数，状态为 NEEDS_SOURCE_INSPECTION。

抽查空正文文件时，多个样本均为 JSON 可解析的 NodeDocument，Children 中只有带 Properties 的 NodeParagraph 节点，没有可见文本字段；这支持“空段落/占位节点”的解释，但抽查不等于逐篇确认，33 篇仍保持 NEEDS_SOURCE_INSPECTION。不得将其直接判为资料损坏。

## 自动提交可靠性

工作流的生成提交步骤增加了有限次数的 fetch/rebase/push 重试，不使用 force-push。此前出现过 GitHub push 拒绝及一次内部服务器错误；在修正工作流并重试后，最新工作流完成成功。若后续仍遇到持续性 GitHub 服务错误，应保留失败状态和日志，不覆盖远端历史。
