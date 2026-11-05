# 本地人工核验工作包

本文件一次性列出需要在持有原始思源资料和本地 `assets/` 的电脑上完成的工作。GitHub Actions 只能验证程序和仓库内数据结构，无法访问本地附件，也不能替代逐篇阅读原始资料。

## 0. 准备环境

1. 在本地克隆或更新 `just2512/siyuan-TCM` 的 `master`。
2. 确认仓库目录内有 `tools/`、`catalog/` 和最新的 `catalog/generated/`。
3. 准备本地原始资料目录：思源工作空间/导出目录中的原始 `.sy` 文件，以及与其对应的 `assets/`。不要把 assets 上传到 GitHub。
4. Python 版本需支持项目现有脚本（Python 3.10+）。
5. 先运行测试：`python -m unittest discover -s tools -p "test_*.py" -v`。失败先修复，不开始批量人工核验。

## 1. 生成本地复核队列和附件指纹

在仓库根目录执行：

```bash
python tools/build_asset_review_queue.py --candidates catalog/local-review/asset-prefix-candidates-2026-11-05.csv --output catalog/generated --batch-size 25
python tools/build_asset_evidence_manifest.py --queue catalog/generated/asset_review_queue.csv --assets-dir "本地assets目录" --output catalog/local-review/asset-evidence-2026-11-05
python tools/build_source_review_queue.py --candidates catalog/source-review-candidates.csv --output catalog/generated --batch-size 20
python tools/build_rule_extraction_audit.py --documents catalog/generated/documents.csv --output catalog/generated
python tools/build_siyuan_review_queue.py --documents catalog/generated/documents.csv --output catalog/generated --decisions catalog/review-decisions.csv
```

将 `"本地assets目录"` 替换为实际 assets 目录路径。Windows 示例：`--assets-dir "D:\\SiYuan\\data\\assets"`。不要把该绝对路径写入仓库。

## 2. 附件核验：634 个引用

队列基线：634 个唯一引用、742 条原始引用记录、836 条候选路径；309 个单候选、235 个多候选、90 个无候选。

先检查 `catalog/local-review/asset-evidence-2026-11-05/asset_evidence_manifest.md` 和 CSV：

- `PRESENT`：文件存在并有 SHA-256；只证明字节级身份。
- `MISSING`：该候选路径在本次指定目录下不存在；不能直接判定附件丢失。
- `UNSAFE_PATH`：工具拒绝读取的路径，需检查候选路径来源。
- `NO_CANDIDATE`：需要根据原始文档上下文在本地 assets 中查找。

然后按 `catalog/generated/asset_review_queue.csv` 的 26 个批次逐条处理：

1. 打开引用对应的原始 `.sy`，定位附件引用及前后文字。
2. 打开所有候选文件；多候选必须逐一比对，不能默认取第一项。
3. 核对实际内容、文件类型、清晰度/完整性，以及它是否确实对应该条引用。
4. 只有内容和引用关系均核实后，才把本地候选清单的 `manual_status` 改为 `CONFIRMED_MATCH`；明确不匹配用 `NOT_MATCH`；无法判断保留 `NEEDS_INSPECTION` 或 `UNRESOLVED`，并写明原因。
5. 无候选时可在本地 assets 按文件名、文件 ID、原始文档上下文搜索。搜索不到只记录本次搜索范围和结果，不推断原附件已永久丢失。

**禁止：** 仅凭文件名、扩展名、候选数量或 SHA-256 将附件标记为匹配；禁止将本地绝对路径或附件文件提交到仓库。

## 3. 来源与版本核验：231 条候选

按 `catalog/generated/source_review_queue.csv` 的 12 个批次处理。当前 231 条均为 `UNVERIFIED`。

逐条打开原始文件或可靠书目资料，填写 `catalog/source-review-candidates.csv`：

- `verification_status` 只能使用 `UNVERIFIED`、`VERIFIED`、`CONFLICT`、`UNRESOLVED`。
- 非 `UNVERIFIED` 必须填写 `evidence_reference`，指向仓库内可审阅的证据记录或明确页码/期次定位；不能填写本机绝对路径。
- 书籍：记录书名页、版权页、作者/编者、出版社、出版年、版次/印次、ISBN（若有）、目录及对应正文页码。
- 《黄帝内经》篇章候选：先确认所据版本，再记录卷/篇/章、目录位置和正文页码；不同版本篇名或编次冲突要保留冲突，不强行统一。
- 课程/讲座：记录原始课程载体、讲者身份依据、日期/期次、原文定位；整理稿、转录稿不能自动视为讲者原始讲稿。
- 来源身份、版本身份、文本校勘是不同结论。来源 VERIFIED 不代表版本和校勘也 VERIFIED。

证据记录应保存在 `catalog/local-review/` 下，采用稳定文件名和可定位页码/截图编号；如证据含版权材料，只记录必要的书目信息和定位，不复制整本受版权保护内容。

## 4. 主题规则复核：4,783 条文档-主题记录

查看 `catalog/generated/topic_rule_audit.csv`。本次静态审计有 4,783 条记录，全部初始为 `NOT_REVIEWED`。

优先按 `audit_flags` 筛选：

- `BROAD_TERM_ONLY`：仅宽泛词触发，需要查看词语所在语境。
- `TITLE_ONLY_MATCH`：主题仅由标题命中，检查标题是否真的表达该主题。
- `BODY_ONLY_MATCH`：主题由正文触发，查看具体段落是否有实质相关内容。
- `MULTI_TOPIC_DOCUMENT`：同一文档命中多个主题，判断是否确实覆盖多个可检索主题。
- `NO_STATIC_RISK_SIGNAL`：没有上述静态风险标记，不等于已人工确认正确。

新增的 `context_excerpt` 只从 `search_text` 检索窗口截取短上下文；`context_state=NOT_IN_SEARCH_WINDOW` 表示完整正文命中证据存在，但当前检索窗口没有该词。必须打开原始 `.sy` 搜索命中词并查看前后段落，不能把窗口缺失当作误报。

将人工主题结论写入 `catalog/review-decisions.csv` 的对应文档行：
- `topic_review_status`：按 `catalog/REVIEW_GUIDE.md` 约定填写。
- `human_approved_topics`：填写人工确认的主题集合。
- `review_notes`：说明保留/删除/新增主题的理由。
- `evidence_reference`：指向原始 `.sy` 的相对路径、标题/段落定位或本地核验记录。

不能仅因宽泛关键词命中就删除主题；需要原文上下文支持。一个文档有多个主题也不自动代表误分类。

## 5. 标题核验：48 条静态风险信号

查看 `catalog/generated/title_extraction_audit.csv`，逐条打开原始 `.sy`：

- `TITLE_IS_FALLBACK`：当前标题不是 Properties.title，核对是否只是正文首行/文件名回退。
- `GENERIC_OR_PLACEHOLDER_TITLE`：检查是否为目录标题、占位标题或有效的章节标题。
- `TITLE_RESEMBLES_BODY_SENTENCE`：检查是否误把正文句子当标题；HTML 转义字符、目录命名风格可能造成静态误报。

将结论写入 `catalog/review-decisions.csv`：
- 确认原始标题：`title_review_status=CONFIRMED)。
- 确认需要改名：`title_review_status=RENAME_REQUIRED`，填写 `human_corrected_title` 并在备注中说明证据。
- 证据不足：`title_review_status=UNRESOLVED`。

不要直接修改自动生成的 `documents.csv` 或审计 CSV；人工决定只写入人工决策表，再由生成流程应用。

## 6. 空正文与父子文档检查

查看 `catalog/generated/empty_body_review.csv`。逐条在思源中打开：

1. 确认文档本身确实为空，还是图片/附件型内容。
2. 检查是否为父级目录容器，实际正文在子文档中。
3. 检查是否因不支持的块类型而未被提取。
4. 记录 `empty_body_status`、备注和可定位证据。只有确实为空且检查范围足够时才使用 `SOURCE_EMPTY_CONFIRMED`；其他情况保留未确定状态。

## 7. 回写、复跑和提交

1. 人工完成后，提交人工决策文件和不含原始附件/个人绝对路径的必要证据索引：`catalog/review-decisions.csv`、`catalog/source-review-candidates.csv`、必要的 `catalog/local-review/*.csv` / Markdown。
2. 不要提交 assets、整本书扫描件、受版权保护的讲义或未经脱敏的私人资料。
3. 执行 `python -m unittest discover -s tools -p "test_*.py" -v`。
4. 执行本文件第 1 节的队列生成命令，确认人工决策已被读取且未被覆盖。
5. 提交到 `master` 后监测 GitHub Actions；只有测试、生成、队列、校验和自动提交全部通过，才标记代码/数据结构验收 PASS。
6. 人工内容核验必须单独统计：已核验、冲突、未解决、未开始。不能用 CI PASS 替代人工核验完成。

## 完成条件

- 附件：每条引用都有人工结论或明确的未解决原因，且证据可追溯。
- 来源：每条来源候选有 VERIFIED / CONFLICT / UNRESOLVED / UNVERIFIED 状态；所有非 UNVERIFIED 结论都有证据定位。
- 主题：对审计记录作出人工结论，保留原始命中词和上下文证据。
- 标题：对 48 条风险信号逐条确认、改名或标记未解决。
- 空正文：逐条检查原始思源内容和父子关系。
- 所有未完成项保留未核验状态，不为追求清零而猜测。
