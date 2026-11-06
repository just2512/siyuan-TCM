# 机器可读知识单元契约

当前版本：`1.0.0`

## 目标

将思源导出的 `.sy` 节点索引转换为稳定、可供后续程序消费的知识单元。该格式负责结构标准化和来源定位，不负责医学解释。

## 记录格式

输出：`catalog/generated/knowledge_units.jsonl.gz`，每行一个 JSON 对象。

| 字段 | 含义 |
|---|---|
| schema_version | 数据契约版本 |
| unit_id | 来源文档哈希、树位置和块 ID 生成的稳定标识 |
| unit_type | 结构角色：章节标题、正文段落、表格单元格、列表项、HTML 可见文本 |
| semantic_status | 当前固定为 `UNCLASSIFIED` |
| assertion_status | 当前固定为 `NOT_INTERPRETED` |
| source | 文档相对路径、SHA-256、块 ID、树位置、父节点 |
| context | 章节路径、标题块 ID、标题层级 |
| content.source_text | 原始可见文本，不做改写 |
| content.normalized_text | 仅折叠空白的检索文本 |
| content.characters | 来源记录的字符数 |

## 结构示例

```json
{
  "schema_version": "1.0.0",
  "unit_id": "<sha256>",
  "unit_type": "SOURCE_PARAGRAPH",
  "semantic_status": "UNCLASSIFIED",
  "assertion_status": "NOT_INTERPRETED",
  "source": {
    "document": "notebook/document.sy",
    "sha256": "<source-sha256>",
    "block_id": "<block-id>",
    "tree_position": "0.1.2",
    "parent_block_id": "<parent-id>",
    "parent_node_type": "NodeDocument"
  },
  "context": {
    "section_path": "经方 / 桂枝汤",
    "section_heading_block_ids": ["<heading-id>"],
    "heading_level": ""
  },
  "content": {
    "source_text": "原始笔记正文",
    "normalized_text": "原始笔记正文",
    "characters": 6
  }
}
```

## 强制约束

1. 原始笔记只读；不得把机器生成的摘要或推断写回原笔记。
2. 每条记录必须可以通过文档路径、源文件 SHA-256、块 ID 和树位置回到原文。
3. 相同源版本和位置生成相同 `unit_id`；源文件变化后 ID 随版本变化。
4. 正文原文与检索规范文本分开保存，禁止用规范文本覆盖原文。
5. 未完成语义解析前，不得把文本标记为事实、证候、治法、方剂功效或医学结论。
6. 空正文、未知节点类型、非法来源路径和重复 ID 必须显式失败或留在上游异常报告，不得静默丢弃。

## 本阶段边界

本契约完成的是“机器可定位、可传输、可检索”的中间表示。下一阶段再基于独立的术语词表和可追溯规则，生成实体候选与关系候选；每个候选都必须携带原文跨度和来源定位。候选不是医学结论，也不能覆盖原文。


## 实体提及候选（扩展阶段）

词典文件：`catalog/entity-lexicon.csv`，当前词典版本为 `1.0.0`。

生成文件：`catalog/generated/entity_mention_candidates.csv.gz`。

每条候选记录包含：
- `mention_id`：由知识单元、实体类型、字符区间和词条生成的稳定 ID。
- `unit_id`：对应知识单元 ID。
- `entity_type`：当前词典定义的类型（药物、方剂、脏腑、证候、穴位）。
- `matched_text`、`character_start`、`character_end`：原文精确命中及字符区间。
- 来源文档、源哈希、树位置、块 ID、章节路径。
- `lexicon_version`、`extraction_method`、`resolution_status`。

当前提取方法为精确词典匹配。允许嵌套和重叠提及，例如方剂名与方剂名中包含的药名同时保留。候选统一标记为 `UNRESOLVED_CANDIDATE`；不执行同义词扩展、否定识别、实体消歧或关系推断。词典是第一版启动词表，不代表全量覆盖。
