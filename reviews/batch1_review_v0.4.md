STATUS: DONE_WITH_CONCERNS

Batch 1 进步很大。上次几个 blocker 基本都收掉了，但我发现一个新的 P1，建议修完再放行 Batch 2。

Scope Check: CLEAN  
Intent: Batch 1 schema、fixtures、raw storage、observability、invariant tests  
Delivered: 已补 fixture 可再生性、content duplicate 语义、accepted item repository assertion、RawObjectStore 回归测试、review docs

验证过：
- `backend/tests/services/storage/test_raw_object_store.py`：10 passed
- DB/repository tests：13 passed, 需要本机 PostgreSQL 访问权限
- fixture 语义抽查通过：identity dup、pixel dup、SEG reference、private creators、zip bomb/path traversal/mixed zip 都符合预期

## Blocker

`[P1] (confidence: 9/10) backend/src/dicom_ingestion/repositories/item_repository.py:37`  
`mark_as_accepted()` 只检查 `attempt_id is not None`，但没有保证这个 `series_ingestion_attempt_id` 属于同一个 `ingestion_job_id`。

证据很直接：

- `backend/tests/repositories/test_item_repository_invariants.py:32-43` 创建 item 时新建了一个 ingestion job
- `backend/tests/repositories/test_item_repository_invariants.py:47-59` 创建 attempt 时又新建了另一个 ingestion job
- `test_mark_as_accepted_sets_terminal_outcome` 仍然通过，说明当前实现允许跨 job 绑定

这会污染后续 Series conflict summary。用户上传 Job A 的 item，可以被绑定到 Job B 的 series attempt。后面按 `series_ingestion_attempt_id` 聚合时，结果会把两个上传会话混在一起。医学数据入口最怕这种账本串线。不是崩，是悄悄错。更糟。

建议修法：

1. DB 层加组合约束，防止任何写路径绕过 repository：
   - `dicom_series_ingestion_attempts` 增加 `UNIQUE(id, ingestion_job_id)`
   - `dicom_ingestion_items(series_ingestion_attempt_id, ingestion_job_id)` 组合 FK 到 attempts 的 `(id, ingestion_job_id)`

2. Repository 层也收紧：
   - `UPDATE ... FROM dicom_series_ingestion_attempts`
   - 条件包括 `items.ingestion_job_id = attempts.ingestion_job_id`
   - 检查 `rowcount == 1`，否则 raise

3. 加测试：
   - same-job attempt 可以 accepted
   - cross-job attempt 必须失败
   - nonexistent item 不应 silent no-op

## 已经 green 的部分

- RawObjectStore：现在路径边界用 `commonpath()`，`get/exists/delete` 都覆盖了 sibling-prefix bypass。
- fixtures：generator 已恢复完整 golden set，`missing_required_tag.dcm` 回到缺 `SOPInstanceUID`，content duplicate 改成 `pixel_digest` 语义。
- pydicom：已 pin `pydicom==2.4.4`。
- accepted item 非空 assertion：有 repository guard 和测试，只是还缺 same-job guard。
- review docs：已提交到 `reviews/`，`.gitignore` 也解除屏蔽。

## Workflow concern

`/review` 要求的 `.agents/skills/gstack/review/checklist.md` 不存在，所以我按等价 review 维度完成了实质审查，但不是完整 gstack checklist run。

## Verdict

**Batch 1 还差一个 P1，不建议放行 Batch 2。**

好消息是这个不是架构推翻，是一个很明确的账本完整性约束。修完这个，我会倾向于给 Batch 1 green。