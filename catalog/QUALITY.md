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


## 空正文结构与标题候选复核（2026-11-04 后续验收）

最新生成提交：`7913b2107121e09fbbd99d62eb9def47e8cff045`；对应工作流：<https://github.com/just2512/siyuan-TCM/actions/runs/41820373093>，结果为 success。

- 新增 `node_types` 与 `child_node_count`，保留每篇文档的子节点类型结构；`empty_body_review.csv` 进一步列出结构判定。
- 33 篇空正文文档全部是 JSON 可解析文档，且当前记录的子节点均为 `NodeParagraph`，没有抽取到可见文本；其状态为 `PARAGRAPH_NODES_WITHOUT_EXTRACTED_TEXT`。这说明仓库文件里保存的是空段落节点结构，不等同于证明原始资料损坏；仍需与用户本地思源库核对。
- 新增 `title_review_candidates.csv`，当前 19 篇候选：包括正文首行回退标题和“其他/方剂/药势/总义/穴/法门/收纳/未命名/待收录”等可能是目录标签或占位名称的标题。它们全部是待核验候选，不自动判错。
- 当前标题来源统计仍为 PROPERTY 2,662 篇、BODY_FIRST_LINE 5 篇；但 PROPERTY 只说明读取到 Properties.title，不代表标题语义准确或书目身份已核实。


## 人工核验结论持久化（2026-11-04）

新增 `catalog/review-decisions.csv` 作为人工核验覆盖层，避免自动重建索引覆盖人工结论。工作流现已把该文件作为输入，再生成 `catalog/generated/*.csv`。

- 人工结论以 .sy 仓库相对路径作为键；重复键、未知文档路径、非法状态值、缺少证据引用均使生成步骤失败，不静默丢弃。
- 自动标签 `topics` 保留不变；人工确认结果写入独立的 `human_approved_topics`，保留机器结果与人工判断的来源区别。
- 标题人工修订写入 `human_corrected_title`，不覆盖机器提取的 `title`。
- 核验结论必须填写 `evidence_reference`，以便回溯书目、原文页码或底本。
- 初始模板只有表头，当前已应用人工核验记录为 0；这表示机制已建立，不表示任何书目、主题或校勘事项已人工验收。

最新持久化覆盖层版本的 CI：<https://github.com/just2512/siyuan-TCM/actions/runs/41822653752>，8 项单元测试、索引生成、核验队列生成和生成提交均成功。生成结果显示 2,667 篇文档、33 篇空正文、1,425 篇多主题候选、19 篇标题候选，人工覆盖记录 0 篇。

人工填写规则见 `catalog/REVIEW_GUIDE.md`。不要直接编辑 `catalog/generated/` 下的 CSV；请编辑 `catalog/review-decisions.csv` 并提交到 master，随后由 CI 自动应用。


### 覆盖层校验补充（2026-11-04）

随后补充重复键和非法状态的拒绝测试。最新 CI：<https://github.com/just2512/siyuan-TCM/actions/runs/41822816916>，9 项单元测试全部通过，生成索引和人工核验队列步骤均通过。由于生成内容未变化，工作流无需产生新的生成提交；人工覆盖表仍为空表，未产生虚构的人工结论。


## 附件路径映射安全性修正（2026-11-04）

附件映射由简单的 basename 首个命中改为确定性匹配：

- 优先按 assets 根目录下的相对路径精确匹配。
- 仅当整个 assets 目录中同名文件唯一时，才允许 basename 回退，状态单独标记为 `FOUND_BY_UNIQUE_BASENAME`。
- 多个同名候选标记为 `AMBIGUOUS`，不再随意选取第一个文件。
- 拒绝空路径和路径穿越引用，Windows 反斜杠也先统一规范化。
- `asset_references.csv` 增加 `match_method`，审计报告区分精确命中、唯一文件名回退、歧义、缺失、非法路径和未检查。

最新验证：<https://github.com/just2512/siyuan-TCM/actions/runs/41823203985>，10 项单元测试通过；索引生成、核验队列生成、生成提交步骤均成功。测试覆盖精确相对路径、唯一文件名、重复文件名歧义及 Windows/Unix 路径穿越拒绝。尚未对用户本地 assets 做实际映射，因为本地目录未提供。


## 用户本地核验结果与持久化（2026-11-04）

用户完成本地附件目录映射和 33 篇空正文文档检查后，结果已从易被 CI 重建覆盖的 `catalog/generated/` 移入持久化输入位置：

- `catalog/local-review/empty-body-review-2026-11-04.csv`：33 篇均由用户标记为 `CONFIRMED_EMPTY`。其中 26 篇是容器/父级文档，直接正文为空但内容位于子文档；7 篇是无子文档、无附件引用的空白占位笔记。这里的“空”仅指当前文档没有直接正文，不表示其子树为空或原始资料损坏。
- `catalog/local-review/asset-audit-2026-11-04.md`：5,309 条引用中，4,567 条精确匹配、742 条未匹配；无唯一 basename 回退、同名冲突或非法路径。742 条中用户初步归类为 722 条无扩展名中文引用和 20 条图片引用。未匹配不等于已证实附件丢失，必须逐项检查路径与扩展名。
- `catalog/source-review-candidates.csv`：保留 231 条来源核验候选（57 个本地附件、160 条《黄帝内经》分篇候选、14 条倪海厦讲稿候选）。所有条目均为 `UNVERIFIED`；分类依据是用户的本地候选整理，不等于出版信息、作者归属或原始底本已核实。

这些人工记录不再放在 `catalog/generated/`，CI 不应重建或覆盖。新一轮核验使用新的日期文件，保留历史记录。

## 本机路径隐私修正（2026-11-04）

本地运行时生成的 `catalog.md` 和 `asset_references.csv` 不应把用户绝对路径提交到仓库。生成器现改为：

- 报告只说明是否提供本地目录，不写入扫描根目录或 assets 绝对路径；
- `asset_references.csv` 的 `local_path` 使用相对于 assets 根目录的 `assets/...` 路径；
- 增加回归测试，检查生成报告和附件映射结果不包含临时本机绝对路径。

历史提交中曾出现的绝对路径文本不会因当前文件修正而从 Git 历史自动消失；本次没有重写远端历史。

