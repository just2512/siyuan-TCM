# 人工核验操作规范

本指南定义 `catalog/generated/` 中人工核验队列的填写规则。机器生成的标签和候选项只用于导航，不构成书目事实或医学结论。

## 0. 书目元数据字段盘点

文件：`catalog/generated/metadata_inventory.csv`

- 该表统计原始 .sy 的 `Properties` 中各个非空字段出现于多少篇文档。
- 只输出字段名和覆盖篇数，不输出作者、出版社、日期等字段的具体值，避免将未经核验的元数据扩散到汇总表。
- 该表用于判断资料库实际包含哪些可供核验的字段；字段存在不代表字段值真实、完整或已与底本核对。
- 未出现在清单中的字段，表示当前扫描样本中没有检测到非空值，不代表思源格式或本地原始资料绝对不存在该字段。

## 1. 通用原则

- 每条人工结论必须有可复核证据：原始 .sy 内容、书籍版权页/目录页、可靠版本信息或可定位的原始出处。
- 不得仅凭笔记本名称、讲者姓名、文件夹层级、关键词或文件名推断作者、原书、版本、出版社或校勘状态。
- 未找到证据时保留 `UNVERIFIED`，不要为了填满字段而猜测。
- 修改标题或主题时保留原值与理由，必要时在 `review_notes` 写出证据位置。
- 本核验只处理资料组织、书目来源和文本版本，不评价医案、方药或治疗主张是否有效。

## 2. 标题核验

文件：`title_review_candidates.csv`、`document_review.csv`

`title_source` 的含义：
- `PROPERTY`：读取到思源 `Properties.title`，不等于标题已核实。
- `BODY_FIRST_LINE`：使用正文首行作为导航回退标题。
- `FILENAME`：正文没有可用文本时使用文件名。
- `RAW_FILENAME`：JSON 解析失败时使用文件名。

建议人工状态：
- `CONFIRMED`：与原始资料标题一致。
- `RENAME_REQUIRED`：确认当前标题是占位名、目录名或错误标题，并已记录建议名称。
- `UNRESOLVED`：现有证据不足。

正文首行回退、文件名回退和通用目录标签必须人工检查；不能直接当作正式书名或篇名。

标题候选的 reason 进一步区分：
- `NUMBER_ONLY_BODY_FALLBACK`：正文首行只有编号或编号标点，例如“1、”，不能作为有效标题。
- `BODY_SENTENCE_USED_AS_TITLE`：正文首行包含明显句末/分句标点，或长度超过 60 个字符，疑似把正文句子当成标题。
- `FALLBACK_TITLE_SOURCE`：其他非 Properties 标题回退，仍需查看原始笔记。
- `POSSIBLE_SECTION_OR_PLACEHOLDER_TITLE`：Properties 标题可能是目录标签或占位名。

这些规则只增加人工复核提示，不自动改写标题；最终以原始笔记结构和上下文为准。

## 3. 主题核验

文件：`topic_review.csv`

- `catalog_topics` 是完整正文初筛生成的现有主题标签。
- `catalog_matched_terms` 是生成正式主题标签时，在标题和完整正文中命中的关键词证据；它用于追溯机器标签的触发依据，不代表语义审核。

- `title_matched_terms` 是标题中的命中词。
- `body_excerpt_matched_terms` 仅覆盖前 2,000 字正文检索片段。
- `catalog_matched_terms` 覆盖完整正文，`body_excerpt_matched_terms` 仍只覆盖前 2,000 字；两者用途不同。
- `excerpt_topics` 是上述有限证据片段所命中的主题；它与完整正文主题标签不一致时，不代表程序错误，需回到原始 .sy 检查。

建议人工状态：
- `CONFIRMED`：现有主题适合检索导航。
- `REMOVE_TOPIC`：移除明确不相关的主题，并说明原因。
- `ADD_TOPIC`：补充明确遗漏的主题，并记录原文依据。
- `SPLIT_REQUIRED`：一篇笔记实际包含多个可独立检索主题，建议拆分或建立子主题索引。
- `UNRESOLVED`：上下文不足。

## 4. 来源、版本与校勘

文件：`document_review.csv`

- `source_status`：只有找到可定位的原始出处或书目记录后才能标为 `VERIFIED`。
- `source_version_status`：需要确认具体版本、出版信息或底本；只知道讲者/课程名称不够。
- `collation_status`：只有完成与明确底本的逐段/逐页比对后才可标为已校勘。未比对时保留 `NOT_REVIEWED`。
- `review_notes` 应写清书名、作者/编者、出版社或版本、出版年份、卷册/页码，以及证据位置；缺项时明确标注未知。

## 5. 空正文检查

文件：`empty_body_review.csv`

- `structure_status=PARAGRAPH_NODES_WITHOUT_EXTRACTED_TEXT` 表示仓库中的 .sy JSON 可解析，子节点是空段落结构，提取器没有找到可见文本字段。
- 这不证明原始本地资料为空或损坏。必须对照用户本地思源库、原始导出或备份。
- 建议人工状态：`SOURCE_EMPTY_CONFIRMED`、`LOCAL_SOURCE_HAS_CONTENT`、`RESTORE_REQUIRED`、`UNRESOLVED`。
- 不要从 0 条附件引用推断原始文档没有图片或其他外部资源。

## 6. 附件映射

附件目录不纳入 Git。用户在本地运行：

```bash
python tools/build_siyuan_catalog.py --notebook-map catalog/notebook-map.json --assets-dir "本地assets目录"
```

`asset_references.csv` 中：
- `FOUND`：按 assets 根目录下的相对路径精确找到附件。
- `FOUND_BY_UNIQUE_BASENAME`：相对路径未命中，但整个 assets 目录中只有一个同名文件；这是回退匹配，建议人工确认。
- `AMBIGUOUS`：存在多个同名候选，脚本拒绝任意挑选，必须人工核对引用路径。
- `MISSING`：精确路径和唯一文件名回退均未找到。
- `INVALID_REFERENCE`：引用路径为空或包含不安全的路径穿越片段。
- `NOT_CHECKED`：没有提供 `--assets-dir`，不是缺失结论。
- `asset_references.csv` 的 `match_method` 记录命中方式；不得把文件名回退当成精确路径命中。

- `asset_prefix_candidates.csv`：在提供 `--assets-dir` 时，对全部本地附件文件名做候选搜索；仅输出文件名线索，不检查图像内容、不自动匹配。
- `asset_audit.md` 同时报告候选扫描状态。`NOT_RUN` 表示没有提供本地附件目录，不能将候选数 0 理解为未匹配附件为 0；只有 `COMPLETED` 才能读取候选统计。


不要将 assets 复制或上传到仓库。对 `MISSING` 项应先核对思源导出目录结构和相对路径，再判断是否真正缺失。


## 7. 人工结论持久化（重要）

人工核验结论统一填写在仓库中的 `catalog/review-decisions.csv`，不要直接编辑 `catalog/generated/*.csv`。生成文件每次都会重建，手工修改生成文件会丢失。

每条记录以 `document` 的仓库相对 .sy 路径作为稳定键；同一文档只允许一行。可只填写已经核实的字段，其余留空。可用字段：

- `reviewer`：核验人。
- `title_review_status`：`CONFIRMED`、`RENAME_REQUIRED`、`UNRESOLVED`。
- `human_corrected_title`：人工确认后的标题建议，不覆盖机器原始标题。
- `source_status` / `source_version_status`：`VERIFIED`、`CONFLICT`、`UNRESOLVED`。
- `collation_status`：`COLLATION_CONFIRMED`、`CORRECTION_REQUIRED`、`UNRESOLVED`。
- `topic_review_status`：`CONFIRMED`、`REMOVE_TOPIC`、`ADD_TOPIC`、`SPLIT_REQUIRED`、`UNRESOLVED`。
- `human_approved_topics`：人工确认的主题标签，以分号分隔；不会覆盖自动生成的 `topics`。
- `empty_body_status`：`SOURCE_EMPTY_CONFIRMED`、`LOCAL_SOURCE_HAS_CONTENT`、`RESTORE_REQUIRED`、`UNRESOLVED`。
- `review_notes`：核验说明。
- `evidence_reference`：必须可定位到原始资料、书目、版本或校勘底本。填写任何非默认人工结论时必填。

生成器会检查重复文档键、仓库中不存在的路径、非法状态和缺少证据引用；发现问题即失败，不会静默忽略。人工结论输出到生成核验表的对应字段，机器原始标签仍保留，避免把人工判断与算法结果混为一谈。


## 8. 多主题核验分批工作包

文件：`catalog/generated/topic_review_batches.csv`

- 该文件将多主题候选按 .sy 仓库相对路径字典序排列，每批 50 篇，包含批次编号、批内序号、主题标签及机器命中词，便于分段处理。
- 批次是工作组织方式，不代表风险、错误程度或优先级；批次边界随新增/删除文档可能变化。
- 不要在该生成文件中填写结论。所有人工结论仍写入 `catalog/review-decisions.csv`，以 document 路径为唯一键。
- `topic_review.csv` 保留完整复核清单；`topic_review_batches.csv` 是便于筛选和分批的工作视图。

## 9. 本地核验记录与 CI 边界

用户本地核验结果保存在 `catalog/local-review/`，不要写入 `catalog/generated/`：

- `empty-body-review-YYYY-MM-DD.csv`：本地逐篇核验空正文的结果。
- `asset-audit-YYYY-MM-DD.md`：本地 assets 映射的汇总结果。
- 新一轮核验应新增日期文件，不覆盖旧记录。

本地核验结果和机器生成队列不是同一数据源。CI 会重新生成 `catalog/generated/empty_body_review.csv`、`asset_references.csv` 等文件，因此不要把人工结果只写在这些生成文件中。

### 来源候选清单

文件：`catalog/source-review-candidates.csv`

- 该表是本地整理出的来源核验候选，不是已验证书目。
- `candidate_category` 仅表示候选分组；`verification_status` 当前统一为 `UNVERIFIED`。
- `asset_file` 只表示附件候选，不证明它是原始底本、正式出版物或讲稿。
- `huangdi_neijing_chapter` 和 `nihongxia_lecture` 是按笔记标题/目录整理的候选归类，不能据此确认作者、讲者、出处或版本。
- 找到版权页、扉页、目录页或明确的原始来源后，才填写 `evidence_reference` 并更新正式人工核验记录。
- 不要将本地附件上传到 GitHub；只提交必要的相对路径、人工核验说明和可定位证据。

### 文件名候选分析（仅用于缩小人工搜索范围）

使用本地 `--assets-dir` 运行最新的 `tools/build_siyuan_catalog.py` 后，会额外生成 `asset_prefix_candidates.csv`：

- 该表扫描本地 assets 目录中的文件名，为未匹配引用列出无扩展名前缀候选或扩展名变体候选。
- `ONE_CANDIDATE` 仍不是 `FOUND`；只代表当前目录中有一个文件名候选，必须打开文件确认内容。
- `MULTIPLE_CANDIDATES` 必须人工辨认，不能按排序或首个候选自动选择。
- `NO_CANDIDATE` 只表示当前候选规则未找到文件名线索，不证明附件不存在。
- 该 CSV 属于本地审计输出。若要长期保存，请复制到 `catalog/local-review/asset-prefix-candidates-YYYY-MM-DD.csv`，不要只保留在 `catalog/generated/`。



## 10. 生成结果跨文件一致性门禁

CI 在所有索引和人工核验工作队列生成后，运行 `tools/validate_siyuan_catalog.py`。它会检查文档键、附件引用计数、逐篇核验记录、空正文集合、主题复核队列、附件候选队列和来源候选队列之间的一致性。

若新增或调整生成字段，应同步更新校验器及其测试。门禁通过只表示表间结构和状态关系一致，不代表人工内容审核完成。


## 11. 思源文档父子层级

文件：`catalog/generated/document_hierarchy.csv`

- 思源导出采用嵌套目录：子文档通常位于以父文档 ID 命名的目录中，父文档本身是该目录的同级 `.sy` 文件。
- 目录索引仅在该父级 `.sy` 文件确实存在于当前扫描集合时建立父子关系；缺少对应文件时保留空父级，不根据笔记本目录名或标题猜测。
- `document_depth` 从当前仓库可识别的顶层文档记为 0；`child_document_count` 只统计直接子文档；`structure_role` 的 CONTAINER/LEAF 仅表示是否有直接子文档。
- `document_review.csv` 与 `empty_body_review.csv` 同时展示父文档、层级深度和直接子文档数，便于区分“容器文档自身无正文”与“无子文档的空白笔记”。
- 该结构是基于导出路径的导航关系，不代表思源内部所有引用、块级嵌入或语义从属关系；也不证明父文档内容完整。
- CI 会校验层级索引与 documents.csv 的文档集合、父级存在性、深度、直接子文档数及结构角色一致。



## 12. 主题规则与标题抽取静态审计

文件：

- `catalog/generated/topic_rule_audit.csv`
- `catalog/generated/title_extraction_audit.csv`
- `catalog/generated/extraction_audit.md`

主题审计按“文档 × 主题”展开完整正文生成阶段记录的命中词，并提供以下提示：

- `BROAD_TERM_ONLY`：当前主题仅由规则中预先列出的宽泛词触发；回看命中词所在原文段落，判断是主题讨论、顺带提及、引用还是目录/索引。
- `TITLE_ONLY_MATCH`：主题词只出现在标题字段；检查标题是否准确表达正文主题。
- `BODY_ONLY_MATCH`：主题词只出现在完整正文；检查是否为正文主体内容，还是孤立提及。
- `MULTI_TOPIC_DOCUMENT`：文档机器标签命中多个主题；不表示误报，应检查各主题是否具有独立检索价值。
- `NO_STATIC_RISK_SIGNAL`：当前静态规则没有发现上述信号，不代表标签已人工确认。

标题审计会列出回退标题、通用/占位标题和疑似正文句子标题。它不自动改写标题；尤其 Properties 字段也可能是目录名、章节名或容器标签。

**复核规则：**

1. 先打开原始 .sy 文档，定位命中词的实际上下文；不要仅凭命中词列表判断。
2. 记录“保留/移除/补充/拆分/未解决”的人工结论及理由。
3. 每条实质结论必须通过 `catalog/review-decisions.csv` 提交，并填写可定位的 `evidence_reference`。
4. 不得把静态审计标记直接转换为误报或确认状态。

附件与来源证据仍遵循第 6 节和第 4 节：附件候选必须打开文件确认内容与引用关系；来源候选必须取得原始书目或讲稿证据。文件名、候选数量、关键词和 CI 通过均不能代替原始证据。


## 13. 本地附件候选文件指纹核验

工具：`tools/build_asset_evidence_manifest.py`

先在本地生成当前附件复核队列（若已有最新队列可跳过）：

```bash
python tools/build_asset_review_queue.py --candidates catalog/local-review/asset-prefix-candidates-2026-11-05.csv --output catalog/generated --batch-size 25
python tools/build_asset_evidence_manifest.py --queue catalog/generated/asset_review_queue.csv --assets-dir "本地assets目录" --output catalog/local-review/asset-evidence-2026-11-05
```

输出：
- `asset_evidence_manifest.csv`：逐引用、逐候选记录文件存在状态、字节数、SHA-256、扩展名和相对路径。
- `asset_evidence_manifest.md`：本次扫描汇总及证据边界。

状态解释：
- `PRESENT`：候选文件在指定 assets 根目录下存在，且已计算字节级指纹。
- `MISSING`：候选路径在本次指定目录下不存在；不等于附件已丢失。
- `UNSAFE_PATH`：路径不符合 `assets/` 相对路径约束或解析后越过根目录；文件未被读取。
- `NO_CANDIDATE`：候选清单没有文件路径，需回到原始引用和本地目录继续查找。

**重要：** SHA-256 只能证明字节级一致性，不能证明图片/文档内容与引用相符，也不能确认书名、版本、作者或医学出处。单候选、多候选和 PRESENT 均不能自动升级为 `CONFIRMED_MATCH`。必须人工打开文件核对内容和对应 .sy 上下文，再将结论及证据位置记录在本地审计记录中；若需要持久化书目结论，应按第 7 节提交带证据的人工核验记录。不要上传 assets 文件或提交本机绝对路径。


## 14. 本地完整核验工作包

本地人工任务的统一入口见 [LOCAL_REVIEW_RUNBOOK.md](LOCAL_REVIEW_RUNBOOK.md)。该文件一次性列出附件、来源/版本、主题规则、标题、空正文与父子文档的操作步骤、命令、人工状态字段和完成条件。

主题审计新增 `context_excerpt` / `context_state`：
- `FOUND_IN_SEARCH_WINDOW`：在有限检索窗口中找到正文命中词附近的短片段。
- `NOT_IN_SEARCH_WINDOW`：完整正文命中证据存在，但检索窗口未包含该词；必须打开原始 .sy 定位。
- `TITLE_ONLY`：仅标题命中，不提供正文上下文。
- `NO_CONTEXT`：没有可展示的上下文。

这些字段是定位辅助，不改变主题标签，也不构成语义审核结论。
