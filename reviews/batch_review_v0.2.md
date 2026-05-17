看过了。**比上一版进步很大，但 Batch 1 还没有完全 green。**

上次我提的 6 个点里，现在已经真正关掉了 3 个半：

| 上次问题 | 当前状态 |
| --- | --- |
| duplicate finding 缺 CHECK | **已修** |
| PG15+ 前提未写明 | **已修**，`backend/README.md` 已写 |
| observability vocabulary 缺关键字段 | **已修**，补了 `item_id` / `series_ingestion_attempt_id` / `stage` |
| invariant suite 太空 | **明显改善，但还没完整** |
| fixture corpus 是假数据 | **明显改善，但还不达标** |
| raw storage contract 太薄 | **明显改善，但还留着安全洞** |

## 当前结论

**还不建议放行 Batch 2。**  
但和上一版不一样，这次已经不是“方向不对”，而是**还剩几处具体缺口要补完**。

---

# 主要 findings

## 1. [P1] `RawObjectStore` 仍然可以越界访问 / 删除 base_dir 外文件

文件：`backend/src/dicom_ingestion/services/storage/raw_object_store.py`

你现在给 `get()` 加了边界检查，这是进步。  
但实现还是有两个问题：

### a) `startswith()` 不是安全的路径边界判断

```python
if not os.path.normpath(uri).startswith(os.path.normpath(self.base_dir)):
```

如果：

```text
base_dir = /tmp/base
uri      = /tmp/base_evil/file
```

`startswith()` 仍然返回真。

### b) `exists()` 和 `delete()` 完全没有边界检查

```python
def exists(self, uri): return os.path.exists(uri)
def delete(self, uri): os.remove(uri)
```

所以即便 `get()` 防住了，调用方仍然可以：

- 探测任意文件是否存在
- 删除 base_dir 外的文件

### 影响

A3 的目标是“raw object store 是可信边界”。  
现在它还不是。

### 建议

抽一个统一的 `_resolve_safe_path()`，让 `get / exists / delete` 都走同一套检查。  
用 `os.path.commonpath()` 或 `Path.resolve().is_relative_to()` 这一类真正的路径边界判断。别手写半套。半套安全措施通常比没有更危险，因为它让人放松警惕。

---

## 2. [P1] fixture corpus 仍然没有满足计划里的 A2 要求

文件：

- `generate_fixtures.py`
- `backend/tests/fixtures/dicom/README.md`

你已经从纯 mock bytes 升级到了 `pydicom` 生成，这一步是对的。  
但它还没有覆盖我们前面锁定的 fixture contract。

### 现在仍缺的东西

#### a) 没有明确的 duplicate pair

计划要求：

- identity duplicate pair
- content duplicate pair

当前所有有效 DICOM 都写死了同一个：

```python
SOPInstanceUID = "1.2.3.4.5.6.7"
```

这会制造一堆**偶然重复**，但不是两个可命名、可预期、可单独测试的 fixture pair。  
测试语料需要故意，不要碰巧。

#### b) 没有 private-tag fixture

计划要求：

- 至少两个 private creator
- 相同 numeric private tag 在不同 creator 下仍可区分

当前 generator 没有写任何 private tag。

#### c) SEG / SR 没有 reference edges

计划要求：

- SEG 或 SR fixture 能产生 expected reference edges

当前 `valid_seg.dcm` 和 `valid_sr.dcm` 只是换了 `SOPClassUID`，没有真实 referenced sequence。  
后面 `C3` 会没法靠这批 fixture 验证引用保留。

#### d) `missing_required_tag.dcm` 跟计划不一致

`generate_fixtures.py:34` 现在缺的是 `PatientID`。  
但 `012` 明确写的是：

```text
missing_required_tag.dcm -- no SOPInstanceUID
```

而我们更早的设计讨论里，真正重要的 unusable-DICOM case 是缺 `SOPClassUID` / `SOPInstanceUID` 这类 ingest 必需 tag，不是病人号。

#### e) 没有 mixed ZIP fixture

计划里需要 mixed ZIP 去证明：

- valid
- malformed
- non-DICOM
- sibling survival

当前只有 `valid_zip_42_files.zip`，而且里面只是 42 个带 `DICM` magic 的 stub，不是 mixed payload。

### 影响

`B3 / B5 / C1 / C2 / C3` 都会被这批 fixture 拖累。  
不是不能写测试，是测试会开始围着“现有 fixture 能表达什么”打转，而不是围着产品真相打转。

---

## 3. [P1] `generate_fixtures.py` 依赖了 `pydicom`，但 `backend/requirements.txt` 没有它

文件：

- `generate_fixtures.py:3`
- `backend/requirements.txt`

现在 generator 直接：

```python
import pydicom
```

但 requirements 里只有：

```text
alembic
SQLAlchemy
pytest
psycopg2-binary
```

我本地直接验了一下，当前环境里也确实没有 `pydicom`。

### 影响

fixture corpus 现在变成了“仓库里有一批生成后的文件，但别人不能按仓库说明重建它”。  
这会让 fixture 演化变成手工活。测试语料一旦不能稳定重建，几周后就没人敢动。

### 建议

把 `pydicom` 加进 dev/test 依赖，或者明确单列一个 fixture-generation dependency group。  
不要让唯一能重建 fixtures 的脚本第一行就 ImportError。

---

## 4. [P1] `A1-z` 已经不是空壳了，但仍没达到 Batch 1 gate

文件：`backend/tests/db/test_dicom_schema_invariants.py`

这版比上一版强很多，已经补了：

- ingestion jobs partial unique
- duplicate finding bad shape + idempotency
- reference edge idempotency
- series attempt uniqueness
- private tags cascade

这很好。

但还缺两类关键验证。

### a) canonical deferral 只测了“坏引用延迟到检查时失败”

当前测试：

```python
INSERT current_canonical_observation_id = 99999
SET CONSTRAINTS ALL IMMEDIATE
```

这证明了“constraint 是 deferred 的”。  
但计划真正要求的是：

> 有效 circular insert 能成功提交，且 observation 确实属于这个 instance

也就是至少还要测：

- instance -> observation 合法闭环能 commit
- composite FK 能拒绝“引用另一个 instance 的 observation”

现在还没覆盖。

### b) 没有覆盖 accepted item 必须有 `series_ingestion_attempt_id`

`660d6ad...create_dicom_series_ingestion_attempts.py` 里只是加了 nullable FK。  
计划里明确要求：

- non-DICOM 可以 NULL
- accepted DICOM 不能 NULL

当前没有 DB CHECK，也没有 application assertion test。  
如果你打算把这条放到 B6 repository 层，那可以，但需要在 Batch 1 review 里明确它是**有意延后**，而不是默认已经完成。

### 影响

`A1-z` 现在已经从 3/10 变成大概 7/10。  
但还没到“下游可以完全信它”的程度。

---

# 已经修好的地方

这轮也有不少是真修了，不只是补文档。

## 已确认改善

- `dicom_duplicate_findings` 已补 `CheckConstraint`
- `backend/README.md` 已写明 PostgreSQL 15+
- observability vocabulary 已补核心键
- fixtures 已从纯 mock 升级为实际 DICOM-like 文件
- invariant suite 已经有实质内容，不再是占位注释
- raw storage 已补：
  - hash mismatch check
  - put path traversal check
  - atomic temp write
  - get path traversal test

这说明你不是在原地打磨。是在往可放行状态收敛。

---

# 当前 Batch 1 状态

我会这样评：

```text
Schema migrations:               8.5/10
Invariant suite:                 7/10
Fixture corpus:                  5/10
Raw storage contract:            6.5/10
Observability vocabulary draft:  8/10
---------------------------------------
Batch 1 readiness:               NOT YET GREEN
```

## 剩下最该做的 4 件事

按优先级：

1. **修 `RawObjectStore` 的路径边界**
   - `get / exists / delete` 共用安全 resolver

2. **把 fixture corpus 补成真的 golden set**
   - explicit identity pair
   - explicit content pair
   - private tags with two creators
   - SEG/SR references
   - mixed ZIP
   - 把 `missing_required_tag` 改成真正 ingest 必需 tag 缺失
   - README 记录 expected result，不只写一句说明

3. **补 `pydicom` 依赖**
   - 让 fixtures 可重建

4. **把 `A1-z` 最后两块补齐**
   - valid canonical circular FK path
   - cross-instance canonical rejection
   - 明确 accepted-item assertion 是现在做还是 B6 做

---

# 放行判断

**现在还差一点。**  
不是大返工，像是把最后几颗地脚螺栓拧紧。

如果你问我“离 Batch 2 还有多远”，我的判断是：

- 人类团队：半天到一天
- 你现在这种 AI 协作速度：一轮就能补完

## 我会怎么做

我会直接继续修，而不是再开一轮纯 review：

- 先修 raw store
- 再重做 fixture generator
- 补 requirements
- 最后补齐 A1-z

这四个补完，我大概率会把 Batch 1 判成 **green**。

**状态：DONE_WITH_CONCERNS**  
如果你要，我下一步可以直接接手把这 4 处补完。