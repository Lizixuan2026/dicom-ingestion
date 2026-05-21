# Series 级版本化设计（简化 Canonical 到 Series）

> 目的：在不按 SOP/Observation 逐条做 canonical 的前提下，提供一套可落地的 Series 级版本化存储与治理方案。  
> 日期：2026-05-21  
> 关联文档：`docs/018_dicom_observation_comments_design.md`、`docs/011_dicom_ingestion_schema_and_contracts.md`

---

## 1. 背景与目标

当前模型以 `dicom_instances`（SOP 逻辑身份）+ `dicom_instance_observations`（物理上传事实）为中心，并在 SOP 级维护 canonical 指针。该方案粒度细、审计强，但实现和产品交互复杂度较高。  
当业务优先级是“先快速稳定上线版本管理”时，可以将 canonical 粒度上提到 Series 级：

- 同一个 `SeriesInstanceUID` 每次上传形成一个新版本；
- 同一 Series 下 SOP 重复时，不直接覆盖旧数据，而是写入新 `series_version`；
- 平台只暴露“当前 active 的 series_version”作为官方版本。

一句话：**用 `series_version` 管“整包版本”，而非用 observation 管“单 SOP 版本”。**

---

## 2. 术语定义

- **Series Logical Identity**：`dicom_series` 中的逻辑实体（由 `SeriesInstanceUID` 标识）。
- **Series Version**：某次上传下，该 Series 全量 `.dcm` 的快照。
- **Active Version**：当前对外生效的版本（每个 series 同时仅一个）。
- **Version File Entry**：某个 series_version 内的一条 SOP 文件记录。

---

## 3. 数据模型（核心新增）

## 3.1 `dicom_series_versions`

用途：记录 Series 的版本头信息与“当前版本”状态。

建议字段：

- `id bigserial primary key`
- `series_id bigint not null references dicom_series(id)`
- `version_no int not null`（同 series 内递增）
- `status text not null`（`candidate | active | archived`）
- `source_ingestion_job_id bigint null`
- `created_by text not null`
- `created_at timestamptz not null default now()`
- `activated_at timestamptz null`
- `activation_reason text null`

建议约束与索引：

- `unique(series_id, version_no)`
- 部分唯一索引：`unique(series_id) where status='active'`
- 索引：`(series_id, created_at desc)`

## 3.2 `dicom_series_version_files`

用途：记录每个版本包含的 SOP 文件清单与对象存储定位。

建议字段：

- `id bigserial primary key`
- `series_version_id bigint not null references dicom_series_versions(id)`
- `sop_instance_uid text not null`
- `raw_object_uri text not null`
- `whole_file_sha256 text not null`
- `pixel_digest text null`
- `tag_digest text null`
- `file_size_bytes bigint null`
- `metadata_json jsonb null`
- `created_at timestamptz not null default now()`

建议约束与索引：

- `unique(series_version_id, sop_instance_uid)`
- 索引：`(series_version_id)`
- 索引：`(sop_instance_uid)`（便于跨版本追踪）
- 索引：`(whole_file_sha256)`（便于内容去重分析）

## 3.3 `dicom_series_version_events`（审计事件）

用途：记录“为什么切换版本”的不可变治理审计。

建议字段：

- `id bigserial primary key`
- `series_id bigint not null references dicom_series(id)`
- `from_version_id bigint null references dicom_series_versions(id)`
- `to_version_id bigint not null references dicom_series_versions(id)`
- `action text not null`（`activate_version | keep_current_version | rollback_version`）
- `actor_id text not null`
- `reason text not null`
- `created_at timestamptz not null default now()`

---

## 4. 与现有表关系调整

## 4.1 保留但弱化 SOP canonical 机制

- `dicom_instances.current_canonical_observation_id` 可保留用于兼容历史逻辑；
- 新业务主流程改为以 `dicom_series_versions.status='active'` 作为“官方版本”来源；
- 对外 API 优先返回 active series version 的文件集。

## 4.2 `dicom_duplicate_findings` 的定位变化

在 Series 版本化方案中，`dicom_duplicate_findings` 可改为“检测证据层”：

- 记录新上传与 active version 比较时发现的 identity/content 重复事实；
- 不负责驱动最终版本切换；
- 用于解释冲突摘要与支持后续复盘。

## 4.3 `dicom_series_conflict_summaries` 继续保留

可继续作为前端冲突页主读表，新增版本字段以提升可解释性：

- `current_active_version_id`
- `candidate_version_id`
- `changed_sop_count`
- `unchanged_sop_count`

---

## 5. 上传处理时序（Series 粒度）

1. 解析上传包，识别 `study_uid/series_uid/sop_uid`。  
2. 定位或创建 `dicom_series`。  
3. 为本次上传创建 `dicom_series_versions` 新行（`status='candidate'`）。  
4. 将本批 `.dcm` 写入对象存储，并逐条写 `dicom_series_version_files`。  
5. 与当前 active version 做 diff，生成摘要（new/missing/changed/unchanged SOP 计数）。  
6. 产出 `dicom_series_conflict_summaries`（如适用）。  
7. 根据策略或人工决策：
   - `keep_current_version`：候选版本归档；
   - `activate_version`：将候选版本设为 active，并将旧 active 归档。  
8. 写 `dicom_series_version_events` 审计记录。

---

## 6. API 契约建议

## 6.1 查询当前版本

`GET /dicom/series/{seriesId}/active-version`

返回：

- `series_id`
- `active_version`（id/version_no/created_at/created_by）
- `files[]`（sop_instance_uid, raw_object_uri, digests）

## 6.2 列出版本历史

`GET /dicom/series/{seriesId}/versions`

返回：

- 每个版本的状态（active/archived/candidate）
- 关键计数（file_count, changed_sop_count）
- 最近一次治理事件摘要

## 6.3 激活候选版本

`POST /dicom/series/{seriesId}/versions/{versionId}/activate`

请求体：

- `reason`（必填）

行为：

- 事务内保证同 series 仅一个 active 版本；
- 记录 `dicom_series_version_events`。

---

## 7. 幂等、并发与事务边界

- **幂等键建议**：`(ingestion_job_id, series_id)` 防止重复创建 candidate version。
- **并发保护**：激活版本时对 `dicom_series_versions` 同 `series_id` 行加锁（`FOR UPDATE`）。
- **事务边界**：
  - 创建 candidate version + files 可在一个事务内；
  - 对象存储写入建议先完成，再提交 DB（或用 staged uri + finalize 流程）。
- **一致性约束**：任何时刻 `status='active'` 仅一条。

---

## 8. 方案利弊评估

## 优点

- 业务认知简单：同一 series 多次上传即多版本。
- 回滚操作直接：切换 active version 即可。
- 上线速度快：避免 observation 级 canonical 大量边界处理。

## 风险与代价

- 粒度下降：无法只替换某个 SOP 的 canonical。
- 存储冗余提升：同 SOP 在多版本重复引用。
- 精细审计能力弱于 observation 级治理。

---

## 9. 落地计划（建议）

### Phase A（1~2 个迭代）

- 新建 `dicom_series_versions`、`dicom_series_version_files`、`dicom_series_version_events`。
- 上传主路径切换到“先落 candidate version”。
- 增加激活版本接口（reason 必填）。

### Phase B（后续增强）

- 增加版本间自动 diff 详情（tag/pixel/hash 维度）。
- 与 `dicom_duplicate_findings` 打通证据链。
- 评估是否保留并回填 SOP/observation 细粒度索引层。

---

## 10. 决策建议

如果目标是“快速稳定支持同 series 重复上传且可回滚”，优先采用本方案。  
如果未来必须支持“同 series 内按单个 SOP 精细治理”，建议保留与 observation 模型的兼容索引，避免后续全量迁移成本。
