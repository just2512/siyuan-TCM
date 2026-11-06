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
