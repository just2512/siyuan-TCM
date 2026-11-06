# 自动生成与本地生成说明

## GitHub Actions

仓库已加入工作流：.github/workflows/build-catalog.yml。

- master 分支上的 .sy 文件、索引脚本或工作流文件发生变更时，工作流会生成 catalog/generated/ 下的索引，并尝试提交回 master。
- 也可以在 GitHub 仓库的 Actions 页面选择 Build and commit TCM catalogue，再点击 Run workflow 手动执行。
- 工作流需要仓库允许 Actions 使用 GITHUB_TOKEN 写入 contents；如果 master 分支保护规则禁止机器人写入，自动回写会失败。

## 本地执行

要求 Python 3.10 或更新版本。在仓库根目录执行：

```bash
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/build_siyuan_catalog.py
python tools/build_node_semantic_index.py --output catalog/generated
python tools/build_section_index.py --output catalog/generated
python tools/build_knowledge_units.py --output catalog/generated
python tools/build_knowledge_units.py --validate --output catalog/generated
```

扫描另一个思源数据目录：

```bash
python tools/build_siyuan_catalog.py --root /path/to/siyuan/data
```

映射仓库外的附件目录：

```bash
python tools/build_siyuan_catalog.py --root /path/to/siyuan/data --assets-dir /path/to/assets
```

默认结果写入 catalog/generated/，并自动读取仓库的 catalog/notebook-map.json。工具不会上传或复制 assets。

## CI 生成与验收

每次 master 上的源码、词典或工作流更新，Actions 会重新生成逐篇索引。以 [Build and commit TCM catalogue](../.github/workflows/build-catalog.yml) 的最新运行结果为准；只有全部构建、来源校验、SQLite 构建、语义图校验和产物上传步骤成功，才视为该版本索引完成。

生成结果包括知识单元、实体提及候选、词面级实体注册表、方剂—药物关系候选、SQLite 检索库和 JSONL.GZ 语义图。原始笔记保持只读，程序输出不覆盖笔记内容。

机器可读知识单元的数据契约见 [KNOWLEDGE_UNIT_SCHEMA.md](KNOWLEDGE_UNIT_SCHEMA.md)。该步骤只标准化结构与来源定位，不自动解释或改写医学内容。

## 可查询 SQLite 索引

全量生成后，可在本地执行：

```bash
python tools/build_entity_registry.py
python tools/build_entity_registry.py --validate
python tools/build_formula_herb_relation_candidates.py
python tools/build_formula_herb_relation_candidates.py --validate
python tools/build_siyuan_search_db.py --build --entity-mentions catalog/generated/entity_mention_candidates.csv.gz --relation-candidates catalog/generated/formula_herb_relation_candidates.csv --entity-registry catalog/generated/entity_registry.csv
python tools/build_siyuan_search_db.py --context-query SYMPTOM --db catalog/generated/siyuan_search.sqlite3
python tools/build_siyuan_search_db.py --query "桂枝汤" --limit 20
python tools/build_siyuan_search_db.py --entity-query "桂枝汤" --limit 20
python tools/build_siyuan_search_db.py --entity-id "lex_..." --limit 100
python tools/build_siyuan_search_db.py --relation-query "桂枝汤" --limit 20
python tools/export_semantic_graph.py
python tools/export_semantic_graph.py --validate
```

数据库包含：
- `content_blocks`：带原文、章节、块定位的全文检索数据。
- `node_relationships`：笔记内部引用、链接及附件关系。
- `entity_catalog`：由词典词面生成的稳定实体标识；当前仅保证“类型+词面”唯一，不做同义词归并。\n- `entity_mentions`：词典匹配实体提及、精确字符区间、稳定实体 ID 和来源定位。
- `semantic_relation_candidates`：从明确的“方剂由药物组成”等句式中提取的关系候选，保留完整证据句和字符范围；仍标记为候选，不作为医学事实。
- `semantic_graph.jsonl.gz`：将实体词面节点与关系候选边导出为 JSONL，边保留原文、文件哈希、块位置和字符跨度；可供其他程序直接消费。
- `index_metadata`：索引记录数和实际检索后端。

GitHub Actions 会将 SQLite 数据库作为 `siyuan-tcm-search-index` 工作流产物发布，保留 30 天；数据库本身不提交进 Git，以免把可重建的大型二进制文件放入版本历史。实体提及表中的记录仍然只是词典候选，不是已确认的医学关系。


## 机器术语发现与查询

CI 会从知识单元原文中并行挖掘跨文档重复出现的中文连续词片段，生成
`catalog/generated/unclassified_term_candidates.csv.gz`。默认要求至少出现 3 次且覆盖 2 篇文档，
每条候选保留出现次数、知识单元数、文档数以及最多 5 条原文位置和字符跨度证据。

这一步不依赖逐篇人工审批，也不自动把词片段判定为中医实体。候选统一标记为
`UNCLASSIFIED_TERM_CANDIDATE`，供后续按症状、脉象、舌象、证候、治法、方剂、药物等类别
进行程序化归类。SQLite 同时保存这些候选，可用：

```bash
python tools/build_siyuan_search_db.py --term-query 太阳中风 --db catalog/generated/siyuan_search.sqlite3
```


## Candidate discovery and provenance boundaries

Corpus-driven term discovery excludes exact lexical forms already present in
`catalog/entity-lexicon.csv`. Its remaining output is a vocabulary-discovery
queue, not a medical ontology: each row remains
`UNCLASSIFIED_TERM_CANDIDATE`, and sample spans are checked against the
captured source snippet. This is a programmatic discovery and indexing stage;
it does not require the notebook author to re-approve the original note text.

Relation validation independently verifies both endpoint mentions against
their own source knowledge units, then verifies that the object mention belongs
to the evidence block and that the formula mention belongs to the same source
document and source revision. Invalid or cross-document endpoints are rejected
before SQLite and graph export.


## 上下文分类候选查询

语料术语候选经过原文局部上下文规则分类后，生成
`contextual_term_type_candidates.csv.gz`。每条记录保留词条、分类规则、原文文档、
SHA、块位置和字符跨度，状态为 `CONTEXT_RULE_CANDIDATE`。这是机器候选，不是人工审批状态或医学事实断言。

CI 将这些记录同步写入 SQLite 的 `contextual_term_type_candidates` 表。可按词语或类别查询：

```bash
python tools/build_siyuan_search_db.py --context-query 头痛 --db catalog/generated/siyuan_search.sqlite3
python tools/build_siyuan_search_db.py --context-query SYMPTOM --db catalog/generated/siyuan_search.sqlite3
```


## 显式症状—证候—治法—方剂关系候选

`build_contextual_relation_candidates.py` 从上下文分类候选与方剂实体提及中抽取三类有明确谓词的关系：
`SYMPTOM_TO_SYNDROME`、`SYNDROME_TO_TREATMENT` 和 `TREATMENT_TO_FORMULA`。
仅当主体、客体在同一知识单元、同一分句中，且支持关系的谓词位于两个原文跨度之间时才生成候选。
单纯共现不会生成关系。每条记录保留双方候选 ID、原文句子、谓词、文档 SHA、块定位和字符范围，
并保持 `UNRESOLVED_CANDIDATE` 状态。该文件随 CI artifact 发布，后续纳入统一关系查询表。


## 语义图中的上下文术语与显式关系

语义图除词典实体和方剂—药物关系外，还导出上下文分类术语候选
(`CONTEXTUAL_TERM_CANDIDATE`) 与显式症状—证候—治法—方剂关系
(`CONTEXTUAL_RELATION_CANDIDATE`)。图校验会逐条核对候选状态、文档 SHA、
块定位、原文证据跨度，以及关系主体、客体和谓词在源文本中的实际位置。
图边仍保持候选语义，不会将规则抽取结果升级为已确认医学事实。
