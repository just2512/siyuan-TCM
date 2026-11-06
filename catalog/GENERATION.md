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

## 当前执行状态

索引生成工具和工作流配置已经提交。当前尚未取得成功的 GitHub Actions 运行记录，因此 catalog/generated/ 中的全量逐篇索引仍待实际执行后验收；不要将仓库盘点基线误认为逐篇索引已完成。

机器可读知识单元的数据契约见 [KNOWLEDGE_UNIT_SCHEMA.md](KNOWLEDGE_UNIT_SCHEMA.md)。该步骤只标准化结构与来源定位，不自动解释或改写医学内容。

## 可查询 SQLite 索引

全量生成后，可在本地执行：

```bash
python tools/build_siyuan_search_db.py --build --entity-mentions catalog/generated/entity_mention_candidates.csv.gz
python tools/build_siyuan_search_db.py --query "桂枝汤" --limit 20
```

数据库包含：
- `content_blocks`：带原文、章节、块定位的全文检索数据。
- `node_relationships`：笔记内部引用、链接及附件关系。
- `entity_mentions`：词典匹配实体提及、精确字符区间和来源定位。
- `index_metadata`：索引记录数和实际检索后端。

GitHub Actions 会将 SQLite 数据库作为 `siyuan-tcm-search-index` 工作流产物发布，保留 30 天；数据库本身不提交进 Git，以免把可重建的大型二进制文件放入版本历史。实体提及表中的记录仍然只是词典候选，不是已确认的医学关系。
