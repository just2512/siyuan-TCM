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

## 3. 主题核验

文件：`topic_review.csv`

- `catalog_topics` 是完整正文初筛生成的现有主题标签。\n- `catalog_matched_terms` 是生成正式主题标签时，在标题和完整正文中命中的关键词证据；它用于追溯机器标签的触发依据，不代表语义审核。\n
- `title_matched_terms` 是标题中的命中词。
- `body_excerpt_matched_terms` 仅覆盖前 2,000 字正文检索片段。\n- `catalog_matched_terms` 覆盖完整正文，`body_excerpt_matched_terms` 仍只覆盖前 2,000 字；两者用途不同。
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
