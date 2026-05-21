# DICOM Observation / Canonical / Comment 表使用说明

> 目的：用一个真实上传冲突场景说明 `dicom_instances`、`dicom_instance_observations`、comments、duplicate findings、Series conflict 和 resolution event 这些表如何协同工作。
>
> 日期：2026-05-21  
> 分支：`main`  
> 关联文档：`docs/011_dicom_ingestion_schema_and_contracts.md`、`docs/018_dicom_observation_comments_design.md`

---

## 1. 先记住三层

DICOM ingestion 里最容易混淆的是“DICOM 身份”和“上传文件版本”。这两件事必须分开。

```text
dicom_instances
= 这个 DICOM 实例是谁
= logical identity

 dicom_instance_observations
= 我们实际见过/上传过哪些版本
= physical uploaded occurrence / observed version

 dicom_observation_comments
= 用户怎么解释这些版本
= human explanation attached to one observation
```

然后还有 conflict 决策层：

```text
dicom_series_conflict_summaries
= 这次上传的 Series 和已有 Series 有什么关系/冲突

 dicom_series_conflict_resolution_events
= 用户最后为什么这么处理
```

最核心的一句话：

> `dicom_instances` 代表官方身份；`dicom_instance_observations` 代表每次实际上传的版本；当前平台采用哪一版由 canonical 指针控制。

---

## 2. `dicom_instances`：官方身份

这张表代表一个逻辑 DICOM 实例。

核心字段：

```text
id
sop_instance_uid
current_canonical_observation_id
```

例如平台第一次看到一个 DICOM：

```text
SOPInstanceUID = 1.2.3.4
```

就创建：

```text
dicom_instances
------------------------------------------------
id      sop_instance_uid      current_canonical_observation_id
inst_1  1.2.3.4               obs_100
```

含义：

> 这个 SOP 的官方当前版本是 `obs_100`。

注意：`dicom_instances` 不代表某个具体文件。它代表“这个 DICOM 身份”。具体文件版本在 observation 表里。

---

## 3. `dicom_instance_observations`：每次实际上传

每次用户上传一个解析成功的 DICOM 文件，系统都会创建一条 observation。

第一次上传：

```text
dicom_instance_observations
--------------------------------------------------------------------------------
id       instance_id  raw_object_uri       whole_file_sha256  pixel_digest  is_canonical
obs_100  inst_1       local-nas://.../a    aaa                ppp           true
```

后来用户又上传一个同 SOP UID 的文件，但内容不同：

```text
SOPInstanceUID = 1.2.3.4
whole_file_sha256 = bbb
pixel_digest = qqq
```

系统不会覆盖 `obs_100`，而是新增：

```text
dicom_instance_observations
--------------------------------------------------------------------------------
id       instance_id  raw_object_uri       whole_file_sha256  pixel_digest  is_canonical
obs_100  inst_1       local-nas://.../a    aaa                ppp           true
obs_200  inst_1       local-nas://.../b    bbb                qqq           false
```

含义：

> `obs_200` 是同一个 DICOM 身份下的另一个实际版本，但当前官方版本仍然是 `obs_100`。

这就是 observation/canonical 模型的关键：

```text
同 ID 的新文件不会自动覆盖旧官方版本。
它会作为新 observation 被保存下来。
是否成为官方版本，需要显式决策。
```

---

## 4. `dicom_observation_comments`：给每个版本加说明

用户真正关心的是：这些版本分别是什么，为什么存在。

所以 comment 应该挂在 observation 上，而不是 instance 上。

示例：

```text
dicom_observation_comments
--------------------------------------------------------------------------------
id  observation_id  actor_id    comment_type           body
1   obs_100         uid_001     user_note              原始院内导出版本
2   obs_200         uid_002     deidentification_note  脱敏后重新导出的版本
3   obs_200         uid_003     quality_note           PixelData 与原版本不同，待质控确认
```

用户看到的是：

```text
obs_100：原始院内导出版本
obs_200：脱敏后重新导出的版本，PixelData 有变化，待质控确认
```

这张表回答的问题是：

```text
这个版本是什么？
为什么它存在？
用户怎么解释它？
```

它不是官方决策记录。官方决策原因应该进 resolution event。

---

## 5. `dicom_duplicate_findings`：系统发现了什么事实

当 `obs_200` 进来时，系统可能发现：

```text
obs_200 和 obs_100 使用同一个 SOPInstanceUID
```

于是记录：

```text
dicom_duplicate_findings
--------------------------------------------------------------------------------
id  observation_id  duplicate_type  basis             matched_instance_id  matched_observation_id
10  obs_200         identity        sop_instance_uid  inst_1               null
```

如果系统还发现两个 observation 的像素或文件内容一样，可能记录：

```text
id  observation_id  duplicate_type  basis              matched_observation_id
11  obs_200         content         pixel_digest       obs_100
```

这张表回答的是：

```text
系统检测到了什么事实？
是同 SOPInstanceUID？
是同文件 hash？
是同 pixel digest？
```

它不是用户评论，也不是最终治理决策。

---

## 6. Series 层：把很多 SOP 的细节归纳给用户看

单个 SOP 太细。真实用户通常上传的是一个 Series。

所以系统需要把 SOP 级别的 observation / duplicate finding 汇总到 Series 级别。

### 6.1 `dicom_series_ingestion_attempts`

这张表表示：

> 这次上传中，有一个 Series 尝试进入平台。

示例：

```text
dicom_series_ingestion_attempts
--------------------------------------------------------------------------------
id          ingestion_job_id  series_instance_uid  uploaded_sop_count
attempt_1   job_32            SERIES_1             120
```

### 6.2 `dicom_series_conflict_summaries`

如果平台已有 `SERIES_1`，系统生成冲突摘要：

```text
dicom_series_conflict_summaries
--------------------------------------------------------------------------------
id          attempt_id  classification      status  existing_sop_count  uploaded_sop_count  conflicting_sop_count
summary_1   attempt_1   content_conflict    open    120                 120                 3
```

这张表回答的是：

```text
这次上传的整个 Series 和平台已有 Series 是什么关系？
```

典型分类：

| classification | 含义 |
|---|---|
| `exact_duplicate` | SOP 集合完全一样，内容也一样 |
| `partial_overlap` | 部分 SOP 重叠，部分不同 |
| `content_conflict` | 同一个 SOPInstanceUID 下出现不同内容 |
| `uid_conflict` | SOP 集合几乎不重叠，怀疑 UID 复用 |

---

## 7. `dicom_series_conflict_resolution_events`：用户为什么这样决定

用户看到 conflict 后，会做一个治理决策：

```text
keep_existing
```

或者：

```text
promote_uploaded
```

这个决策必须留下 reason，写入 resolution event。

### 7.1 保留已有版本

```text
dicom_series_conflict_resolution_events
--------------------------------------------------------------------------------
id  summary_id  action         actor_id  reason
1   summary_1   keep_existing  uid_001   新上传版本缺少质控确认，暂保留平台已有版本
```

然后 summary 状态变成：

```text
dicom_series_conflict_summaries
--------------------------------------------------------------------------------
id          classification      status
summary_1   content_conflict    kept_existing
```

canonical 不变：

```text
obs_100.is_canonical = true
obs_200.is_canonical = false
dicom_instances.current_canonical_observation_id = obs_100
```

### 7.2 提升新上传版本为官方版本

```text
dicom_series_conflict_resolution_events
--------------------------------------------------------------------------------
id  summary_id  action             actor_id  reason
2   summary_1   promote_uploaded   uid_001   新版本为质控修正版，经确认应作为官方版本
```

然后系统切换 canonical：

```text
obs_100.is_canonical = false
obs_200.is_canonical = true
dicom_instances.current_canonical_observation_id = obs_200
```

这张表回答的是：

```text
谁在什么时候，因为何种原因，把官方版本保留或切换了？
```

它是审计记录，不是普通评论。

---

## 8. 完整流程示例

假设平台已有：

```text
inst_1
  SOPInstanceUID = 1.2.3.4
  canonical = obs_100
```

用户上传新文件：

```text
SOPInstanceUID = 1.2.3.4
whole_file_sha256 = bbb
pixel_digest = qqq
```

### Step 1：找到已有 logical instance

系统用 SOPInstanceUID 查到：

```text
dicom_instances.id = inst_1
```

### Step 2：新增 observation

```text
dicom_instance_observations
obs_200
  instance_id = inst_1
  raw_object_uri = local-nas://.../b
  whole_file_sha256 = bbb
  pixel_digest = qqq
  is_canonical = false
```

### Step 3：记录 duplicate / conflict fact

```text
dicom_duplicate_findings
obs_200
  duplicate_type = identity
  basis = sop_instance_uid
  matched_instance_id = inst_1
```

如果 pixel 不同，则 Series 级冲突可能是：

```text
dicom_series_conflict_summaries
summary_1
  classification = content_conflict
  status = open
```

### Step 4：用户给新 observation 加说明

```text
dicom_observation_comments
obs_200
  comment_type = correction_note
  body = 质控后重新导出的修正版，PixelData 有变化
```

### Step 5：用户决定官方版本

如果保留旧版本：

```text
resolution event:
  action = keep_existing
  reason = 新版本暂未质控确认

canonical:
  obs_100 继续 canonical
  obs_200 保留但非 canonical
```

如果提升新版本：

```text
resolution event:
  action = promote_uploaded
  reason = 新版本已通过质控，应作为官方版本

canonical:
  obs_100.is_canonical = false
  obs_200.is_canonical = true
  dicom_instances.current_canonical_observation_id = obs_200
```

---

## 9. 每张表一句话

| 表 | 一句话 |
|---|---|
| `dicom_instances` | 这个 DICOM 实例的官方身份 |
| `dicom_instance_observations` | 这个实例实际上传/出现过的每个版本 |
| `dicom_observation_comments` | 用户对某个版本的解释 |
| `dicom_duplicate_findings` | 系统检测到的重复/冲突事实 |
| `dicom_series_ingestion_attempts` | 一次上传里的 Series 尝试 |
| `dicom_series_conflict_summaries` | 这个 Series 和已有数据的冲突摘要 |
| `dicom_series_conflict_resolution_events` | 用户对冲突做出的正式决策原因 |

---

## 10. 关键边界

### 10.1 Comment 不等于 decision

```text
comment:
“这个版本像是脱敏版本”
```

这只是说明。

```text
resolution reason:
“经确认，该版本为官方脱敏修正版，提升为 canonical”
```

这才是治理决策。

两者必须分开。

### 10.2 Hash 不等于 identity

`whole_file_sha256` 和 `pixel_digest` 帮助系统判断内容是否相同，但它们不定义 DICOM logical identity。

DICOM logical identity 仍由：

```text
SOPInstanceUID
```

定义。

所以：

```text
same SOPInstanceUID + different hash
```

不是新 instance，而是同 instance 下的新 observation。

### 10.3 Storage 去重不等于业务去重

对象存储可以因为 hash 一样复用同一份 bytes。

但业务层仍应创建新的：

```text
ingestion_item
observation
```

因为用户确实又上传了一次。这是 provenance。

### 10.4 canonical 切换不删除旧版本

`promote_uploaded` 只是切换指针：

```text
current_canonical_observation_id
```

旧 observation 仍然保留。

这保证：

- 历史可追踪；
- 决策可回看；
- 数据治理可审计；
- 误操作可以通过新的显式决策恢复。

---

## 11. UI 应该怎么帮助用户理解

对于一个有多个 observation 的 SOP，前端不应只显示 ID/hash。

建议展示：

```text
当前官方版本
- observation id
- 上传时间
- 来源 job
- hash / pixel digest
- display label
- 最新 comment
- 是否 canonical

其他版本
- observation id
- 上传时间
- 来源 job
- 系统 diff summary
- comments
- 是否可 promote
```

对于 conflict summary 页面，建议展示：

```text
该 Series 已存在。
本次上传与已有 Series 发生 content_conflict。

已有版本：120 个 SOP
上传版本：120 个 SOP
内容冲突：3 个 SOP
完全重复：117 个 SOP

操作：
[保留已有版本] [提升本次上传为官方版本]

操作前必须填写 reason。
```

---

## 12. 查询示例

### 12.1 查询某个 instance 的所有 observation

```sql
SELECT
  o.id,
  o.raw_object_uri,
  o.whole_file_sha256,
  o.pixel_digest,
  o.is_canonical,
  o.observed_at
FROM dicom_instance_observations o
WHERE o.instance_id = :instance_id
ORDER BY o.observed_at DESC;
```

### 12.2 查询当前 canonical observation

```sql
SELECT o.*
FROM dicom_instances i
JOIN dicom_instance_observations o
  ON o.id = i.current_canonical_observation_id
WHERE i.id = :instance_id;
```

### 12.3 查询 observation comments

```sql
SELECT
  id,
  actor_id,
  comment_type,
  body,
  created_at,
  updated_at
FROM dicom_observation_comments
WHERE observation_id = :observation_id
  AND deleted_at IS NULL
ORDER BY created_at ASC;
```

### 12.4 查询 open Series conflicts

```sql
SELECT *
FROM dicom_series_conflict_summaries
WHERE status = 'open'
ORDER BY created_at DESC;
```

### 12.5 查询某个 conflict 的 resolution history

```sql
SELECT
  action,
  actor_id,
  reason,
  created_at
FROM dicom_series_conflict_resolution_events
WHERE summary_id = :summary_id
ORDER BY created_at ASC;
```

---

## 13. 小结

这些表一起解决的是一个数据治理问题：

```text
同一个 DICOM ID 下可能出现多个实际文件版本。
系统不能悄悄覆盖，也不能粗暴拒绝。
它应该保留每次观察事实，用 canonical 指针表达当前官方版本，
用 comments 让用户解释版本，用 resolution events 记录正式决策。
```

最终效果是：

```text
obs_100：原始版本，当前官方版本
obs_200：脱敏版本，未采用，用户说明了原因
obs_300：质控修正版，后来被 promote 为官方版本，并有审计 reason
```

这比单纯“重复文件检测”更适合医学数据管理平台，因为它同时保留了身份、版本、来源、解释和治理决策。
