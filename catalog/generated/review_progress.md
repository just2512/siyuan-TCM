# 人工核验进度报告

> 本报告只汇总持久化表格中的状态，不读取原始 .sy 或附件内容，不判定内容真实性。CI 通过不代表人工核验完成。

## 人工决策表

| 核验域 | 记录数 | 状态分布 |
|---|---:|---|
| title_review_status | 33 | NOT_REVIEWED: 33 |
| source_status | 33 | NOT_REVIEWED: 33 |
| source_version_status | 33 | NOT_REVIEWED: 33 |
| collation_status | 33 | NOT_REVIEWED: 33 |
| topic_review_status | 33 | NOT_REVIEWED: 33 |
| empty_body_status | 33 | NEEDS_SOURCE_INSPECTION: 33 |

## 原始人工复核队列

- 逐文档—主题审计：4782 条；NOT_REVIEWED: 4782
- 标题风险审计：22 条；NOT_REVIEWED: 22
- 空正文候选：33 条；NEEDS_SOURCE_INSPECTION: 33

## 真实笔记内容审计

- 内容异常扫描文档：2667；有静态信号：308
- 段落级异常候选：726
- 剂量样式表达候选：60540（全部初始 NOT_REVIEWED）
- 章节级索引记录：13871
- 块类型覆盖记录：27

## 来源候选

- 候选记录：231
- source_identity_status: UNVERIFIED: 231
- source_version_status: UNVERIFIED: 231
- collation_status: UNVERIFIED: 231

## 附件引用

- 唯一引用记录：634
- NEEDS_INSPECTION: 544
- UNRESOLVED: 90

## 证据台账

- 证据记录：33
- 证据类型 original_sy: 33
- 检查方式 PROGRAMMATIC_STRUCTURE: 33

## 状态解释

- 空白状态按 NOT_REVIEWED 统计；不得把空白当作通过。
- UNVERIFIED / NOT_REVIEWED / NEEDS_INSPECTION / NEEDS_SOURCE_INSPECTION / PENDING 均属于未完成。
- UNRESOLVED 和 CONFLICT 单独保留，不并入已核验。
- 本报告不把 PARTIAL 等同 VERIFIED，也不将机器扫描状态转换为人工结论。
- 每个有效人工结论仍须通过证据台账结构校验和跨表引用校验，并由复核者确认原始材料确已检查。
