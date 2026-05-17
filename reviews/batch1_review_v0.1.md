## Review 结论

**Batch 1 目前不建议放行到 Batch 2。**

### Scope Check: REQUIREMENTS MISSING

**Intent:** 完成 Batch 1 foundation，包含 schema、invariant suite、fixture corpus、raw storage contract、observability vocabulary。  
**Delivered:** 12 个 migration、一个 local `RawObjectStore`、部分 schema tests、fixture 文件、vocabulary draft。  
**Missing / partial:** invariant suite 不完整、fixtures 基本是 mock 占位、raw storage contract 还不够安全、部分 schema 约束未落地。

---

# Findings

## 1. [P1] `backend/tests/db/test_dicom_schema_invariants.py` 不是 Batch 1 要求的 invariant suite

文件自己已经承认了：

```python
# NOTE: A comprehensive suite would include tests for:
# - A1-c ...
# - A1-e ...
# - A1-h ...
# - A1-i ...
# - A1-j ...
```

现在只有：

- `study_instance_uid` unique
- `series -> study` FK restrict
- canonical upper bound

但 Batch 1 要求的是至少覆盖：

- FK restrict 全套
- canonical FK deferral
- ingestion jobs partial unique
- private tags cascade
- duplicate finding idempotency
- reference edge idempotency
- series attempt uniqueness
- accepted item assertion

这不是小漏项。  
**A1-z 是 Batch 1 的验收门，不是 nice-to-have。**

### 影响

如果现在进入 Batch 2，你是在“相信 schema 正确”，不是“证明 schema 正确”。后面 parser / retry / duplicate 开始依赖它时，返工会更贵。

---

## 2. [P1] fixture corpus 现在基本是假的，不能支撑后续 parser / scanner 测试

`generate_fixtures.py` 里：

```python
for f in dcm_files:
    out.write(b"DICOM_MOCK_DATA")
```

这意味着：

- `valid_ct_single.dcm`
- `valid_seg.dcm`
- `missing_required_tag.dcm`
- `truncated.dcm`

现在本质上是同一种 dummy bytes。

同时 `backend/tests/fixtures/dicom/README.md` 只解释了 3 个文件，离计划要求的 fixture manifest 差很远。

### 影响

后续 `B3/B5/C2/C3` 看起来能开工，实际上没有可靠测试输入。  
最危险的是 `missing_required_tag.dcm` 和 `truncated.dcm` 这种名字会制造假信心，名字说它坏，内容并没有真的坏。软件最会骗人的是测试夹具。

---

## 3. [P1] `dicom_duplicate_findings` 允许无意义坏数据落库

`backend/alembic/versions/234a9c2da0f4_create_dicom_duplicate_findings.py:22-44`

你已经做了 `NULLS NOT DISTINCT` unique index，这部分是对的。  
但缺少计划里要求的约束：

> `matched_instance_id` 和 `matched_observation_id` 不能同时为 NULL

现在可以插入一条：

```text
duplicate finding
  matched_instance_id = NULL
  matched_observation_id = NULL
```

这在业务上没有任何意义，但 DB 会接受。

### 影响

后续 duplicate classifier 会面对“系统声称有 duplicate，但没有任何匹配对象”的垃圾事实。  
这个应该在数据库层封死。

---

## 4. [P1] `RawObjectStore` 还不是可交付的 storage contract

`backend/src/dicom_ingestion/services/storage/raw_object_store.py:13-23`

当前逻辑：

```python
uri = os.path.join(self.base_dir, content_hash)
if not os.path.exists(uri):
    write(data)
```

问题有两个：

1. **不验证 `content_hash` 是否真的是 `data` 的 hash**
   - 调用方传同一个 hash、不同 bytes，第二次会静默复用旧文件
   - 这会把“幂等”变成“悄悄吞错”

2. **直接把调用方传入值拼路径**
   - 如果未来不是严格内部输入，`../` 一类路径会逃出 `base_dir`

当前测试也只测了 happy path：

- put idempotent
- get
- exists
- delete

没有测：

- hash mismatch
- same hash + different bytes
- unsafe hash / path escape
- atomic write / partial write

### 影响

A3 的目标是“raw bytes 是 canonical truth”。  
现在这层还没到能承这个责任的程度。

---

## 5. [P2] observability vocabulary draft 有，但和既定契约还没对齐

`backend/docs/observability/001_vocabulary_draft.md`

优点是：它确实存在了，这比“C7 以后再想”强很多。

但当前缺少计划里后续必需的结构化键：

- `item_id`
- `series_ingestion_attempt_id`
- `stage`

反而列了：

- `study_instance_uid`
- `series_instance_uid`
- `sop_instance_uid`

这些不是一定不能打，但它和我们之前锁定的 `C7` 目标还没有完全对上。

### 影响

不至于卡死 Batch 1，但如果现在不收口，后面每条 lane 还是可能各自发明事件字段。  
vocabulary draft 的价值就在于早点统一，不是早点写一份未来再改的大纲。

---

## 6. [P2] PostgreSQL 15+ 前提用了，但没真正写进项目约束

这两个 migration 都依赖：

```sql
NULLS NOT DISTINCT
```

- `234a9c2...duplicate_findings.py`
- `6c6ab93...reference_edges.py`

这要求 PostgreSQL 15+。  
migration 注释里写了，但仓库级别没有我能看到的 backend README / environment contract 去锁这个前提。

### 影响

如果 deployment 环境不是 PG15+，第一次跑 migration 就会炸。  
这不是设计错，是约束还没写完整。

---

# 什么是已经做对的

这部分也要说清楚，避免误伤。

## 已经合理的部分

- 12 张表的拆分方向是对的
- Alembic 链路顺序基本可读
- `observations` 和 `instances` 分离是对的
- deferred canonical FK 设计落下来了
- reference edge / duplicate finding 都考虑了 `NULLS NOT DISTINCT`
- `dicom_series_ingestion_attempts` 已经提前进入 schema，这能避免后面 Series review 层返工

这些不是小事。  
说明 schema 主线没跑偏。

---

# Batch 1 完成度判断

我会这样打：

```text
Schema skeleton:                 8/10
Invariant proof:                 3/10
Fixture corpus:                  2/10
Raw storage contract:            4/10
Observability vocabulary draft:  6/10
-------------------------------------
Batch 1 readiness:               NOT READY
```

## 为什么不是 ready

因为 Batch 1 的目标不是“先把 migration 文件写出来”。  
目标是让 Batch 2 不需要替 Batch 1 猜东西。

现在 Batch 2 仍然会被迫猜：

- fixtures 到底代表什么
- storage hash 语义到底是什么
- duplicate finding 是否允许坏 shape
- schema 是否真的守住了计划中的不变量

这就说明 Batch 1 还没真正完成。

---

# 我建议的修复顺序

按收益排序：

1. **先补 `A1-z`**
   - 这是总闸门
   - 没有它，别的都只是“看起来差不多”

2. **重做 fixture corpus**
   - 真实、区分明确、README 完整
   - 否则后面 parser / scanner / security tests 都在沙地上盖楼

3. **补 duplicate finding CHECK**
   - 小修复，收益高

4. **把 `RawObjectStore` 收成真正 contract**
   - 验 hash
   - 防 path escape
   - 测 same hash / different bytes
   - 明确 local adapter vs production adapter

5. **补齐 observability vocabulary draft**
   - 加 `item_id`
   - 加 `series_ingestion_attempt_id`
   - 加 `stage`
   - 对齐后续 `C7`

6. **写明 PG15+ 要求**
   - backend README 或 deploy notes

---

# 我对“能不能继续”的判断

**可以继续修 Batch 1。**  
**不建议开始 Batch 2。**

这不是在吹毛求疵。  
你前面花这么多力气把 execution plan 做对，就是为了在这个时刻敢说：**foundation 还没 green，先别往上盖。**

如果你要，我下一步可以直接帮你做两种事之一：

### A. 只出正式 review 文档
落成 `docs/dicom_ingestion_execution/006_batch_1_review.md`

### B. 直接修
我按上面的 6 个点把 Batch 1 补到可以放行。

我建议 **B**。这几个都属于“lake”，不是“ocean”。现在补最便宜。