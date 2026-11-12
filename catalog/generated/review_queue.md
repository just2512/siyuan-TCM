# 逐篇人工核验队列

- 文档记录：2667
- 正文抽取为空：33
- 多主题关键词命中、待人工复核：1425
- 多主题复核分组：5_PLUS_TOPICS=153；3_TO_4_TOPICS=650；2_TOPICS=622；0_TO_1_TOPICS=0
- 标题来源分布：BODY_FIRST_LINE=5；PROPERTY=2662
- catalog_matched_terms 保留标题和完整正文的机器命中词；人工复核的 excerpt 证据仍只覆盖标题和前 2000 字正文片段，两者可能不完全一致。
- 所有来源、版本及校勘状态均初始化为 UNVERIFIED / NOT_REVIEWED；未从文件名或关键词推断出处。

## 文件

- 人工核验状态、证据要求和附件本地检查方法见 catalog/REVIEW_GUIDE.md。
- 人工结论从 catalog/review-decisions.csv 读取；该文件与自动生成产物分离，重建索引不会覆盖人工结论。
- 已应用人工核验覆盖记录：33 篇；无覆盖记录时保持 NOT_REVIEWED / UNVERIFIED。
- document_review.csv：逐篇标题、正文、来源、版本、校勘人工核验状态及父子文档上下文。
- topic_review.csv：完整多主题复核清单。
- topic_review_batches.csv：按文档仓库相对路径排序后每批 50 篇的人工工作包索引，共 29 批；批次只用于组织工作，不保存人工结论。
- empty_body_review.csv：单独列出正文抽取为空的文档，等待回看原始 .sy。
- title_review_candidates.csv：标题来源回退或命中少量通用目录标签的候选项，共 19 篇；均未自动判错。

## 边界

- 主题命中只是字符串包含关系，不是语义分类；多主题记录只是复核队列，不自动判为错误。
- title_source 区分 Properties 字段、正文首行回退、文件名回退及原始文本回退；回退标题不得当作已核验书名或篇名。
- title_matched_terms 与 body_excerpt_matched_terms 分开记录标题命中和前 2000 字正文片段命中；二者都只是字符串证据。
- review_bucket 仅按当前主题标签数量分组，方便分批检查，不代表错误程度或医学风险。
- topic_review_batches.csv 每次按 document 路径字典序重新分批；新增/删除文档可能改变后续批次边界。人工结论仍只写入 catalog/review-decisions.csv。
- 空正文可能来自空白文档、非文本内容或提取器尚未覆盖的节点类型，必须回看原始 .sy。
- 本清单不构成医学内容真实性、出处或临床有效性的证明。
