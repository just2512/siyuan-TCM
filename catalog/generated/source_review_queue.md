# 来源资料候选核验队列

- 候选总数：231
- 每批：20 条；批次数：12

## source_identity_status

- CONFLICT: 0
- PARTIAL: 0
- UNRESOLVED: 0
- UNVERIFIED: 231
- VERIFIED: 0

## source_version_status

- CONFLICT: 0
- PARTIAL: 0
- UNRESOLVED: 0
- UNVERIFIED: 231
- VERIFIED: 0

## collation_status

- CONFLICT: 0
- PARTIAL: 0
- UNRESOLVED: 0
- UNVERIFIED: 231
- VERIFIED: 0

## 核验边界

- 来源身份、版本身份、文本校勘是三个独立结论，必须分别填写状态和证据引用。
- 来源身份 VERIFIED 不代表版本 VERIFIED；版本 VERIFIED 不代表校勘完成。
- PARTIAL 仅用于已直接检查原始材料且有页码/段落/期次/时间戳定位的部分核验。
- 文件名、标题、关键词和自动提取片段不能支撑任何 VERIFIED 结论。
- 只有 HUMAN_DIRECT 类型证据可以通过人工结论交叉校验。
- 冲突和未解决状态必须保留，不得为了清零而强行统一。

详细项目见 `source_review_queue.csv`。
