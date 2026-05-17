STATUS: DONE_WITH_CONCERNS

Batch 1 现在可以 green。  
上轮那个 P1 已经被正确关闭了。

Scope Check: CLEAN  
Intent: 修掉 cross-job attempt binding，并补 DB/repository 双层保护  
Delivered: 新 migration、repository guard、same-job/cross-job/nonexistent-item 测试、v0.4 review doc

## 关键复查结果

### P1 已修

`backend/src/dicom_ingestion/repositories/item_repository.py:34-51`

现在 `mark_as_accepted()` 用：

```sql
UPDATE ... FROM dicom_series_ingestion_attempts AS a
WHERE i.id = :item_id
  AND a.id = :attempt_id
  AND i.ingestion_job_id = a.ingestion_job_id
```

并且检查 `rowcount != 1` 就 raise。  
这封住了 application-layer 的跨 job 绑定。

DB 层也补了：

`backend/alembic/versions/b3954e035423_add_cross_job_attempt_guard.py:26-36`

- `udx_attempts_id_job`
- `fk_items_attempt_same_job`

我直接验证了绕过 repository 的 SQL update：

```text
constraints: [..., 'fk_items_attempt_same_job']
direct_cross_job_update: rejected
```

这才是正确的账本边界。用户上传 Job A 的文件，不可能被偷偷挂到 Job B 的 Series attempt 上。

## 测试结果

通过：

```bash
PYTHONPATH=backend/src backend/venv/bin/pytest -q \
  backend/tests/services/storage/test_raw_object_store.py \
  backend/tests/repositories/test_item_repository_invariants.py \
  backend/tests/db/test_dicom_schema_invariants.py
```

结果：

```text
25 passed in 0.28s
```

Alembic 状态也对：

```text
b3954e035423 (head)
```

## 非阻塞小建议

`mark_as_rejected()` 现在还是 silent no-op，如果 `item_id` 不存在不会报错。  
这不是 Batch 1 blocker，但后面 ingestion accounting 做完整后，建议也加 `rowcount` 检查，避免坏 item id 静默漏账。

## Workflow concern

`/review` 要求的 checklist 仍然不存在：

```text
.agents/skills/gstack/review/checklist.md
/Users/haohuayin/gstack/.agents/skills/gstack-review/checklist.md
```

所以这次是按等价 Batch 1 review 维度完成，不是完整 gstack checklist run。

## Verdict

**Batch 1 GREEN。可以进入 Batch 2。**

这版已经具备 Batch 1 该有的底座质量：schema 约束、raw storage 安全、fixture corpus、repository invariant、DB-level guard 都闭上了。
