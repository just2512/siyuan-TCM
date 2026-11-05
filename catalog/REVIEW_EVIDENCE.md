# 人工核验证据台账规范

本台账用于把人工结论关联到可复查的原始材料定位。它是审计索引，不是自动真实性认证。程序通过只说明字段结构合格，不说明来源内容真实。

## 文件与校验

- 台账：`catalog/review-evidence.csv`。
- 校验：`python tools/validate_review_evidence.py --ledger catalog/review-evidence.csv`。
- 当前模板只有表头；空台账可通过校验。人工完成后逐条增加记录。
- 完整字段和允许值由 `tools/validate_review_evidence.py` 定义。

## 字段填写

| 字段 | 含义 | 要求 |
|---|---|---|
| evidence_id | 稳定证据编号 | 唯一，建议 EV-0001 |
| subject_type | 被核验对象类型 | document / source_candidate / asset_reference / topic_decision / title_decision / empty_body_decision |
| subject_key | 对象键 | 文档相对路径、来源候选 path、附件 reference |
| evidence_kind | 证据类型 | original_sy / asset_content / title_page / copyright_page / table_of_contents / body_page / lecture_record / audio_timestamp / catalogue_record / other_primary_source |
| inspection_method | 检查方式 | HUMAN_DIRECT / PROGRAMMATIC_STRUCTURE / AUTOMATED_EXTRACTION / SECONDARY_REFERENCE；只有 HUMAN_DIRECT 可支撑人工结论。程序结构读取可以作为技术观察记录，但不能标记人工核验完成。 |
| source_reference | 材料引用 | 仓库内脱敏相对路径或可复核书目信息；不得写机器绝对路径 |
| locator | 精确位置 | 页码、段落、块 ID、期次、时间戳或附件引用上下文 |
| observation | 实际观察 | 只写检查到的事实，区分原文与推断 |
| reviewer | 核验人 | 可追溯的人工身份标识 |
| reviewed_at | 核验日期 | YYYY-MM-DD |

## 结论门槛

- `UNVERIFIED` / `NOT_REVIEWED`：尚未直接检查原始材料；不得创建虚假的人工证据行。
- `PARTIAL`：至少有一处原始材料被直接检查，并有具体定位；必须明确未核验的部分。
- `VERIFIED`：该字段所声明的核验范围全部有直接材料支撑。来源身份、版本身份、文本校勘是三个不同范围，不得相互代替。
- `CONFLICT`：存在可定位且相互矛盾的材料；分别记录双方证据，不擅自消解。
- `UNRESOLVED`：已执行明确检查但仍无法判断；记录检查范围、缺失信息和未解决原因。

## 禁止事项

1. 文件名、标题、关键词、搜索命中、自动提取片段不能单独成为原始来源证据。
2. SHA-256、文件存在性、扩展名和路径匹配只说明文件属性，不说明内容与引用相符。
3. 不得把自动化脚本、AI 输出或提交者身份写成实际人工核验人。
4. 不上传本地 assets、整本书扫描件、版权讲义、私人信息或机器绝对路径。
5. 不因字段齐全或 CI 通过就把人工内容核验标记为完成。

## 示例（虚构格式示例，不是本仓库已核验结论）

```csv
EV-0001,document,folder/note.sy,original_sy,catalog/local-review/evidence-index.md,原始 .sy：标题属性与正文第 3 段,已直接检查标题属性及指定段落；此处仅示范记录格式,reviewer-1,2026-11-05
```

人工决策表当前的 `evidence_reference`、来源候选表的 `evidence_reference`、附件队列的 `content_evidence_reference` 仍由各自流程消费。本台账目前先建立统一记录格式和结构校验；在跨表 ID 引用校验接入之前，不要把普通文字引用误认为已经通过台账交叉验证。


## 跨表引用校验

使用 `tools/validate_review_evidence_references.py` 检查人工决策、来源候选和附件队列中的证据 ID 是否存在、对象键是否一致、证据类型是否属于相应结论域。多个 evidence ID 使用英文分号分隔。该工具不校验原始材料真实性或人工观察正确性；未核验状态保留的旧文本线索不视为证据 ID。


## 证据类型与结论域的强制对应

| 人工结论域 | 允许的证据类型 |
|---|---|
| 标题核验 | original_sy |
| 主题核验 | original_sy |
| 空正文/父子结构核验 | original_sy |
| 来源身份 | title_page、copyright_page、catalogue_record、lecture_record、audio_timestamp、other_primary_source |
| 来源版本 | title_page、copyright_page、table_of_contents、catalogue_record、lecture_record、audio_timestamp、other_primary_source |
| 文本校勘 | original_sy、table_of_contents、body_page、lecture_record、audio_timestamp、other_primary_source |
| 附件内容匹配/不匹配 | asset_content |

来源候选表目前使用一个 evidence_reference 字段承载来源身份、版本和校勘证据，因此可引用多条不同 evidence_kind 的证据；每条引用都必须属于同一 source_candidate/path。只完成其中一类核验，不得据此推导其他结论已经完成。证据不足时保持未核验或未解决状态。

此映射只验证证据分类，不认证内容真实性。不得为了通过校验而更改 evidence_kind。


## 检查方式与人工结论的边界（强制）

证据台账新增 `inspection_method`：

- `HUMAN_DIRECT`：核验者直接打开原始材料，检查与结论相关的内容并记录可复查定位。
- `PROGRAMMATIC_STRUCTURE`：程序读取原始文件结构、节点类型、属性或子节点关系。
- `AUTOMATED_EXTRACTION`：解析器、脚本或模型自动提取的文本/字段。
- `SECONDARY_REFERENCE`：目录、二手书目或其他间接材料。

只有 `HUMAN_DIRECT` 可以支撑人工决策表中的有效结论、来源状态和附件内容匹配结论。其他方式的证据可以保留，用于说明自动化观察到的事实，但不得用于人工结论交叉校验。

2026-11-05 提交的 33 条记录属于 `PROGRAMMATIC_STRUCTURE`：它们记录原始 .sy 的 JSON 节点结构、标题属性和子文档数量。这些是可复核的结构事实，但不能单独证明内容完整性、标题语义正确性或人工已经检查。因此标题状态保持 `NOT_REVIEWED`，空正文状态保持 `NEEDS_SOURCE_INSPECTION`，直到完成直接人工检查。


## 来源候选表的独立状态字段

`catalog/source-review-candidates.csv` 不再使用一个聚合 `verification_status` 表示三个不同问题。每条候选分别维护：

- `source_identity_status` / `source_identity_evidence_reference`
- `source_version_status` / `source_version_evidence_reference`
- `collation_status` / `collation_evidence_reference`

每个状态均使用 UNVERIFIED / PARTIAL / VERIFIED / CONFLICT / UNRESOLVED。每个非 UNVERIFIED 状态必须引用其自身的证据 ID；不能用来源身份的证据替代版本或校勘证据。证据类型和检查方式仍由跨表校验执行。
