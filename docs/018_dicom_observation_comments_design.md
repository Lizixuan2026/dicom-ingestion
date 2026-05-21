# DICOM Observation Comments 设计说明

> 目的：补充 observation/canonical 模型中的用户解释层。解决“同一个 DICOM 身份下存在多个 observation，用户如何区分不同版本、说明来源和决策原因”的产品与后端设计问题。
>
> 日期：2026-05-21  
> 分支：`main`  
> 关联文档：`docs/011_dicom_ingestion_schema_and_contracts.md`、`docs/017_dicom_upload_parse_edge_case_coverage.md`

---

## 1. 背景

当前 ingestion 设计里，DICOM logical identity 和物理上传事实是分开的：

```text
dicom_instances
  = 逻辑身份，由 SOPInstanceUID 唯一确定

 dicom_instance_observations
  = 每一次实际上传/观察到的物理文件
  = 记录 raw bytes、tag、hash、pixel_digest、来源 job、是否 canonical
```

当用户上传的 Series 或 SOP 与平台已有数据使用相同 DICOM ID，但 tag 或 pixel data 不同时，系统不会直接覆盖已有数据，也不会直接拒绝新数据。

正确处理是：

```text
同一个 logical instance 下挂多个 observation
当前官方版本由 current_canonical_observation_id 指向
新 observation 默认不替换旧 canonical
用户或治理策略显式决定是否 promote
```

但这带来一个用户侧问题：

> 用户需要知道这些 observation 分别是什么版本、为什么存在、为什么某个版本被选为官方版本。

如果没有 comment/说明层，用户只能看到 hash、时间、job、tag diff，很难建立业务理解。

---

## 2. 设计结论

应支持 **observation-level comments**，并且要把它和 **conflict resolution reason** 区分开。

推荐模型：

```text
Observation comment
  = 给某一次 observation 的用户说明
  = 用来区分版本、来源、处理状态、备注

Resolution reason
  = 对 canonical 切换或保留决策的不可变原因
  = 属于治理/audit 事件

System diff summary
  = 系统自动生成的差异摘要
  = 帮助用户理解 tag/pixel/hash 变化
```

一句话：

> comment 帮用户理解每个版本；resolution reason 记录为什么选某个版本做官方版本；system diff summary 自动解释版本差异。

---

## 3. 为什么 comment 应挂在 observation 上

不要把这个字段只放在 `dicom_instances` 上。

原因：

```text
dicom_instances
  = 一个逻辑身份
  = 只代表“这个 SOPInstanceUID”

observations
  = 多个实际版本/上传事实
  = 用户真正需要区分的是这些版本
```

示例：

```text
Instance: SOPInstanceUID = 1.2.3.4

obs_100
  current canonical
  comment: 原始院内导出版本

obs_200
  non-canonical
  comment: 脱敏后版本，PatientName/PatientID 已清理

obs_300
  non-canonical 或 promoted later
  comment: 质控后重新导出的修正版，PixelData 有变化
```

如果只有 `dicom_instances.comment`，这些说明会混在一起，无法对应具体版本。

---

## 4. 不要混淆 comment 与 audit reason

### 4.1 Observation comment

用于说明一个 observation 本身。

特点：

- 面向用户阅读；
- 可以多人补充；
- 可以编辑或软删除；
- 属于协作说明；
- 不应作为不可变审计事实。

示例：

```text
这是脱敏后的版本。
这是从外院系统重新导出的版本。
该版本 pixel data 有变化，暂不采用。
该版本为算法后处理生成，仅用于对比。
```

### 4.2 Resolution reason

用于说明一次治理决策。

特点：

- 属于 audit；
- 不应随意编辑；
- 与 `keep_existing` / `promote_uploaded` 动作绑定；
- 记录 actor、action、reason、timestamp；
- 用于事后追责和复盘。

示例：

```text
经人工确认，新上传版本来自质控修正后导出，提升为官方版本。
保留已有版本，因为新上传文件缺少完整脱敏证明。
```

因此，不能只用一个通用 `comment` 字段同时承担这两个责任。

---

## 5. 推荐数据模型

### 5.1 推荐方案：独立 observation comments 表

```sql
CREATE TABLE dicom_observation_comments (
  id                  bigserial PRIMARY KEY,
  observation_id       bigint NOT NULL REFERENCES dicom_instance_observations(id) ON DELETE RESTRICT,
  actor_id             text NOT NULL,
  comment_type         text NOT NULL DEFAULT 'user_note',
  body                 text NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  deleted_at           timestamptz NULL
);

CREATE INDEX idx_dicom_observation_comments_observation
  ON dicom_observation_comments(observation_id)
  WHERE deleted_at IS NULL;
```

推荐 `comment_type` 初始枚举：

```text
user_note
quality_note
deidentification_note
correction_note
system_note
```

含义：

| type | 用途 |
|---|---|
| `user_note` | 普通用户备注 |
| `quality_note` | 质控说明 |
| `deidentification_note` | 脱敏/去标识说明 |
| `correction_note` | 修正版本说明 |
| `system_note` | 系统生成但可展示的说明 |

### 5.2 Resolution event 表

canonical 决策不要写进 observation comments，而应作为 conflict resolution event：

```sql
CREATE TABLE dicom_series_conflict_resolution_events (
  id                  bigserial PRIMARY KEY,
  summary_id           bigint NOT NULL REFERENCES dicom_series_conflict_summaries(id) ON DELETE RESTRICT,
  action              text NOT NULL,
  actor_id             text NOT NULL,
  reason              text NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now()
);
```

`action` 只允许：

```text
keep_existing
promote_uploaded
```

v1 不支持 `merge`。

### 5.3 可选字段：display label

可以在 observation 上加一个轻量展示名：

```sql
ALTER TABLE dicom_instance_observations
  ADD COLUMN display_label text NULL;
```

用途：

```text
原始版本
脱敏版本
质控修正版
外部导入版本
```

`display_label` 适合列表展示；comments 适合详细说明。

---

## 6. 最小可行版本

如果要先做最小实现，可以拆成两步。

### Phase 1：轻量版本

在 `dicom_instance_observations` 上增加：

```sql
display_label text null,
user_comment text null
```

优点：实现快。

缺点：

- 不支持多条评论；
- 不支持多人协作历史；
- 编辑会覆盖历史；
- comment 类型弱；
- 后续很可能迁移到独立表。

### Phase 2：正式版本

引入：

```text
dicom_observation_comments
dicom_series_conflict_resolution_events
system diff summary projection
```

推荐直接做 Phase 2。因为这个功能天然带有治理和协作属性，过早做成单字段会很快不够用。

---

## 7. 系统自动 diff summary

用户 comment 很重要，但不应该让用户自己猜“两个版本到底哪里不同”。

系统应在 observation 对比时提供自动摘要：

```json
{
  "base_observation_id": 100,
  "compare_observation_id": 200,
  "same_sop_instance_uid": true,
  "whole_file_sha256_changed": true,
  "pixel_digest_changed": true,
  "changed_tags": [
    "PatientName",
    "PatientID",
    "SeriesDescription",
    "ManufacturerModelName"
  ]
}
```

UI 可展示为：

```text
该版本与当前官方版本使用相同 SOPInstanceUID，但文件内容不同。
PixelData 不同，说明影像像素发生变化。
DICOM tag 有 4 处差异，其中包含 PatientName、PatientID。
```

建议 diff summary 不直接写入 comments 表。它可以是：

- 查询时动态计算；或
- 写入独立 projection/cache；或
- 写入 conflict summary 的 metadata。

不要把系统 diff 和用户 comment 混在一个字段里。

---

## 8. 前端交互建议

### 8.1 Observation 列表

在同一个 SOP 或 Series conflict 页面展示：

```text
当前官方版本
- observation: obs_100
- 上传时间: 2026-05-18
- 来源 job: ingest_001
- whole_file_sha256: aaa...
- pixel_digest: ppp...
- comment: 原始院内导出版本

新上传版本
- observation: obs_200
- 上传时间: 2026-05-21
- 来源 job: ingest_032
- whole_file_sha256: bbb...
- pixel_digest: qqq...
- 系统差异: PixelData 不同，SeriesDescription 不同
- comment: 质控后重新导出的版本
```

### 8.2 用户操作

每个 observation 可支持：

```text
添加备注
编辑自己的备注
查看备注历史
设置 display label
```

对于 conflict summary 可支持：

```text
保留已有版本
提升本次上传为官方版本
```

执行 resolution 时，必须填写 reason：

```text
为什么保留已有版本？
为什么提升本次上传为官方版本？
```

这条 reason 写入 resolution event，不写入普通 observation comment。

---

## 9. API 草案

### 9.1 获取 observation comments

```http
GET /api/dicom/observations/{observation_id}/comments
```

返回：

```json
{
  "observation_id": 200,
  "comments": [
    {
      "id": 1,
      "comment_type": "correction_note",
      "body": "质控后重新导出的修正版。",
      "actor_id": "uid_100001",
      "created_at": "2026-05-21T09:00:00Z",
      "updated_at": "2026-05-21T09:00:00Z"
    }
  ]
}
```

### 9.2 新增 comment

```http
POST /api/dicom/observations/{observation_id}/comments
Content-Type: application/json

{
  "comment_type": "correction_note",
  "body": "质控后重新导出的修正版。"
}
```

### 9.3 更新 comment

```http
PATCH /api/dicom/observations/{observation_id}/comments/{comment_id}
Content-Type: application/json

{
  "body": "质控后重新导出的修正版，PixelData 已确认。"
}
```

### 9.4 删除 comment

```http
DELETE /api/dicom/observations/{observation_id}/comments/{comment_id}
```

建议使用 soft delete，保留审计能力。

### 9.5 conflict resolution 必填 reason

```http
POST /api/dicom/series-conflicts/{summary_id}/resolve
Content-Type: application/json

{
  "action": "promote_uploaded",
  "reason": "经人工确认，新上传版本为质控修正后版本，提升为官方版本。"
}
```

---

## 10. 权限与审计

### 10.1 Comment 权限

建议第一版规则：

- job owner 可以新增 comment；
- 有 dataset 管理权限的人可以新增 comment；
- 用户只能编辑/删除自己的 comment；
- 管理员可以软删除违规 comment；
- system_note 只能由系统写入。

### 10.2 Resolution 权限

`keep_existing` / `promote_uploaded` 是治理动作，权限应高于普通 comment。

建议：

- job owner 可以 resolve 自己上传产生的 conflict；
- dataset owner / curator / admin 可以 resolve；
- promote_uploaded 必须填写 reason；
- resolution event 不允许编辑，只能追加新的补充 audit event。

---

## 11. Report 中如何呈现

Batch/terminal report 可以加入轻量 observation note summary，不要塞完整评论流。

示例：

```json
{
  "item_id": 42,
  "observation_id": 200,
  "terminal_outcome": "accepted",
  "dicom_identity": {
    "study_uid": "...",
    "series_uid": "...",
    "sop_instance_uid": "..."
  },
  "observation_note_summary": {
    "display_label": "质控修正版",
    "comment_count": 2,
    "latest_comment_preview": "质控后重新导出的修正版..."
  }
}
```

完整 comment 应通过 observation comments API 查询，避免 report 变得过重。

---

## 12. 不推荐的方案

### 12.1 只在 `dicom_instances` 上放 comment

问题：多个 observation 的说明会混在一个逻辑身份上，无法区分版本。

### 12.2 只在 `series_conflict_summary` 上放 comment

问题：conflict summary 是一次冲突事件，observation 是长期存在的版本事实。冲突解决后，用户仍然需要理解每个 observation。

### 12.3 把 resolution reason 当普通 comment

问题：治理决策原因需要不可变审计。普通 comment 可以编辑，不适合承担 audit 责任。

### 12.4 只靠系统 diff，不允许用户 comment

问题：系统能说明“哪里不同”，但不能说明“为什么不同”。例如“脱敏版本”“质控修正版”“外部导入版本”都需要人类语境。

---

## 13. 验收场景

建议用以下场景验收：

1. 同 SOP UID 首次上传，创建 observation，可添加 comment。
2. 同 SOP UID 再次上传，tag 不同，生成新 observation，可分别添加 comment。
3. 同 SOP UID 再次上传，pixel data 不同，Series conflict 为 `content_conflict`，新 observation 可添加 comment。
4. 用户选择 `keep_existing`，必须填写 reason，canonical 不变。
5. 用户选择 `promote_uploaded`，必须填写 reason，canonical 指针切换。
6. resolution reason 进入 audit event，不出现在普通 comment 列表里。
7. report 只显示 comment summary，不加载完整评论历史。
8. 普通用户不能编辑他人 comment。
9. system_note 不能由普通用户创建。
10. 删除 comment 为 soft delete，历史可审计。

---

## 14. 推荐实施顺序

```text
Phase A
- 建 dicom_observation_comments
- observation comments API
- 前端 observation 详情显示 comments

Phase B
- conflict resolution API 增加 required reason
- 建 resolution event/audit
- conflict 页面展示 observation comments + diff summary

Phase C
- 自动生成 observation diff summary
- report 加 observation_note_summary
- 权限细化、软删除审计、系统 note
```

如果要压缩范围，Phase A + resolution reason 必填应优先做。

---

## 15. 最终建议

这个能力应该进入 DICOM ingestion 的治理设计，不应被当成普通备注小功能。

原因很简单：observation/canonical 模型解决了工程上的版本并存问题，但用户还需要理解：

```text
这个版本是什么？
为什么它和当前官方版本不同？
为什么最后选择了这个版本？
谁做了这个判断？
```

推荐最终模型：

```text
每个 observation 有自己的 comments
每次 canonical 决策有不可变 resolution reason
系统自动提供 diff summary
report 只带 comment summary
完整评论通过 observation API 查询
```

这样既保留数据治理审计，也给用户足够上下文去区分“原始版本、脱敏版本、修正版、冲突版本”。
