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

队列基线：634 个唯一引用、742 条原始引用记录、836 条候选路径；309 个单候选、235 个多候选、90 个无候选。当前 544 条此前仅凭文件名/路径候选匹配而被标记为确认的记录，已统一退回 `NEEDS_INSPECTION`；90 条无候选保留 `UNRESOLVED`。这些路径线索不代表内容已核验。

先检查 `catalog/local-review/asset-evidence-2026-11-05/asset_evidence_manifest.md` 和 CSV：

- `PRESENT`：文件存在并有 SHA-256；只证明字节级身份。
- `MISSING`：该候选路径在本次指定目录下不存在；不能直接判定附件丢失。
- `UNSAFE_PATH`：工具拒绝读取的路径，需检查候选路径来源。
- `NO_CANDIDATE`：需要根据原始文档上下文在本地 assets 中查找。

然后按 `catalog/generated/asset_review_queue.csv` 的 26 个批次逐条处理：

1. 打开引用对应的原始 `.sy`，定位附件引用及前后文字。
2. 打开所有候选文件；多候选必须逐一比对，不能默认取第一项。
3. 核对实际内容、文件类型、清晰度/完整性，以及它是否确实对应该条引用。
4. 建立本地内容核验记录（建议文件：`catalog/local-review/asset-content-review-2026-11-05.csv`），至少记录 `reference`、实际检查的候选路径、内容描述、文件类型、清晰度/完整性、对应原始 `.sy` 的上下文定位和核验人/日期。
5. 只有内容和引用关系均核实后，才把本地候选清单的 `manual_status` 改为 `CONFIRMED_MATCH`；明确不匹配用 `NOT_MATCH`；两种结论都必须在 `content_evidence_reference` 填写指向上述记录的引用（例如该 CSV 中对应的 reference 键）。无法判断保留 `NEEDS_INSPECTION` 或 `UNRESOLVED`，并写明原因。
6. 无候选时可在本地 assets 按文件名、文件 ID、原始文档上下文搜索。搜索不到只记录本次搜索范围和结果，不推断原附件已永久丢失。

**禁止：** 仅凭文件名、扩展名、候选数量、`.sy` 路径命中或 SHA-256 将附件标记为匹配；`CONFIRMED_MATCH` / `NOT_MATCH` 必须有 `content_evidence_reference`；禁止将本地绝对路径或附件文件提交到仓库。

## 3. 来源与版本核验：231 条候选

当前 231 条来源候选均为 `UNVERIFIED`。此前 187 条 `PARTIAL` 只有文件名、文档标题或关键词线索，没有定位到原始来源证据，已全部退回 `UNVERIFIED`。按 `catalog/generated/source_review_queue.csv` 的批次处理。

逐条打开原始文件或可靠书目资料，填写 `catalog/source-review-candidates.csv`：

- `verification_status` 使用 `UNVERIFIED`、`PARTIAL`、`VERIFIED`、`CONFLICT`、`UNRESOLVED`。
- `PARTIAL` 只有在直接检查过原始来源材料、能提供具体页码/段落/期次/时间戳定位时才允许使用；文件名、文档标题、关键词命中或自动提取首页文字不能单独支撑 `PARTIAL`。
- 非 `UNVERIFIED` 必须填写 `evidence_reference`，指向仓库内可审阅的证据记录或明确页码/段落/期次/时间戳定位；不能填写本机绝对路径。
- 书籍：记录书名页、版权页、作者/编者、出版社、出版年、版次/印次、ISBN（若有）、目录及对应正文页码。
- 《黄帝内经》篇章候选：先确认所据版本，再记录卷/篇/章、目录位置和正文页码；不同版本篇名或编次冲突要保留冲突，不强行统一。
- 课程/讲座：记录原始课程载体、讲者身份依据、日期/期次、原文定位；整理稿、转录稿不能自动视为讲者原始讲稿。
- 来源身份、版本身份、文本校勘是不同结论。来源 VERIFIED 不代表版本和校勘也 VERIFIED。

证据记录应保存在 `catalog/local-review/` 下，采用稳定文件名和可定位页码/截图编号；如证据含版权材料，只记录必要的书目信息和定位，不复制整本受版权保护内容。

## 4. 主题规则复核：4,783 条文档-主题记录

查看 `catalog/generated/topic_rule_audit.csv`。本次静态审计有 4,783 条记录，全部初始为 `NOT_REVIEWED`。

人工决策约束：每条结论必须填写 `reviewer` 和 `evidence_reference`；`topic_review_status` 一旦不是 `NOT_REVIEWED`，必须填写规范主题枚举中的 `human_approved_topics`（分号分隔、不得重复）；`RENAME_REQUIRED` 必须填写 `human_corrected_title`，且修正标题只能与该状态同时使用。

**当前持久化状态核对：** `catalog/review-decisions.csv` 当前 33 行记录的 `topic_review_status` 全部为空，尚无主题人工结论被正式应用。提交说明中提到的 `BODY_CONFIRMED`、`BROAD_TERM_REVIEW` 等分类没有映射进当前人工决策字段，不能据此宣称主题复核已完成。请将逐条结论映射为 `CONFIRMED`、`REMOVE_TOPIC`、`ADD_TOPIC`、`SPLIT_REQUIRED` 或 `UNRESOLVED`，填写 `human_approved_topics`、理由和证据定位；否则保持 `NOT_REVIEWED`。

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

## 5. 标题核验：22 条静态风险信号（本次重算）

查看 `catalog/generated/title_extraction_audit.csv`，逐条打开原始 `.sy`。

**当前持久化状态核对：** 此前 11 条 `CONFIRMED` 和 1 条 `UNRESOLVED` 均来自 `local-programmatic-v2` 程序化结构扫描，并非原始 `.sy` 人工复核；现已全部退回 `NOT_REVIEWED`。重新生成后，19 条标题候选均应保持待人工复核，另有 22 条静态审计信号仍为 `NOT_REVIEWED`。此前提交说明中提到的 2 条 `RENAME_REQUIRED` 未进入正式决策表，不能计入已落地结论。

- `TITLE_IS_FALLBACK`：当前标题不是 Properties.title，核对是否只是正文首行/文件名回退。
- `GENERIC_OR_PLACEHOLDER_TITLE`：检查是否为目录标题、占位标题或有效的章节标题。
- `TITLE_RESEMBLES_BODY_SENTENCE`：检查是否误把正文句子当标题；HTML 转义字符、目录命名风格可能造成静态误报。

将结论写入 `catalog/review-decisions.csv`：
- 确认原始标题：`title_review_status=CONFIRMED`。
- 确认需要改名：`title_review_status=RENAME_REQUIRED`，填写 `human_corrected_title` 并在备注中说明证据。
- 证据不足：`title_review_status=UNRESOLVED`。

不要直接修改自动生成的 `documents.csv` 或审计 CSV；人工决定只写入人工决策表，再由生成流程应用。

## 6. 空正文与父子文档检查

查看 `catalog/generated/empty_body_review.csv`。此前 33 条 `SOURCE_EMPTY_CONFIRMED` 同样来自程序化结构扫描，没有逐篇检查原始 `.sy`；现已全部退回 `NEEDS_SOURCE_INSPECTION`。逐条在思源中打开：

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
- 来源：当前 231 条均为 UNVERIFIED；只有直接检查原始来源材料并留下可定位证据后才能转为 PARTIAL / VERIFIED / CONFLICT / UNRESOLVED。PARTIAL 不得计入 VERIFIED。
- 主题：对审计记录作出人工结论，保留原始命中词和上下文证据。
- 标题：对本次重算后的 22 条风险信号逐条确认、改名或标记未解决。
- 空正文：逐条检查原始思源内容和父子关系。
- 所有未完成项保留未核验状态，不为追求清零而猜测。


## 跨表证据引用校验（新增）

在人工决策表、来源候选表或附件队列中写入人工结论后，必须执行证据 ID 跨表校验：

```bash
python tools/validate_review_evidence.py --ledger catalog/review-evidence.csv
python tools/validate_review_evidence_references.py --ledger catalog/review-evidence.csv --decisions catalog/review-decisions.csv --sources catalog/source-review-candidates.csv --assets catalog/generated/asset_review_queue.csv
```

约束：
- 人工决策字段进入有效结论状态后，`evidence_reference` 必须是台账中存在的 evidence_id；多个 ID 使用英文分号分隔。
- 决策证据必须属于同一文档键，且证据类型必须与结论域兼容。
- 来源状态不再是 `UNVERIFIED` 时，证据必须属于相同候选 path 的 `source_candidate`。
- 附件状态为 `CONFIRMED_MATCH` 或 `NOT_MATCH` 时，证据必须属于相同 reference 的 `asset_reference`。
- 未核验记录可以保留历史线索文字，但不把它当成有效证据 ID，也不因此要求创建证据行。
- 本校验只证明引用存在、对象键一致、证据域兼容；不证明原始材料真实，也不证明观察内容正确。

在本地完整原始资料不可提交的情况下，台账的 `source_reference` 可指向脱敏的本地证据索引条目，但该索引必须能由人工复核者在本地找到对应材料。


## 8. 人工核验进度报告

每次本地更新人工决策表、来源候选表或附件队列后，重新生成汇总：

```bash
python tools/build_review_progress_report.py --decisions catalog/review-decisions.csv --sources catalog/source-review-candidates.csv --assets catalog/generated/asset_review_queue.csv --evidence catalog/review-evidence.csv --output catalog/generated/review_progress.md
```

报告按标题、来源身份、来源版本、文本校勘、主题、空正文、附件和证据类型分别统计状态。空白按 NOT_REVIEWED 统计；UNRESOLVED、CONFLICT、PARTIAL 和未开始状态不会被合并成已完成。报告是持久化状态的计数，不是对原始材料的自动验真。
