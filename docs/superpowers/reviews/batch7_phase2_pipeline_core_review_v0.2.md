# Batch 7 Phase 2 Pipeline Core Review v0.2

**评审日期**: 2026-05-19  
**评审对象**: 当前 `main` 工作区未提交 Phase 2 candidate patch，以及用户补充的 `data_manifest.json` 上传语义  
**继承自**: `batch7_phase2_pipeline_core_review_v0.1.md`  
**角色定位**: reviewer only，不继续扩展实现

---

## 一、结论更新

**状态建议**: `DONE_WITH_CONCERNS`  
**新增 scope 判断**: `data_manifest.json` 不应升级为系统内部核心 Dataset 模型  
**是否推翻现有上传方式**: 否  
**是否建议当前 Phase 2 立刻做完整 dataset 支持**: 否，优先级下调，后置

用户补充后，v0.1 里对 manifest 的判断需要修正：

- 原 Phase 2 计划里的 `ManifestSource(entries[])` 是一种低层文件清单 manifest。
- 用户描述的 `data_manifest.json` 是另一种东西：它是用户上传前整理数据时提供的**组织说明**。
- 它不必成为系统内部核心模型，也不必现在引入完整 `Dataset` 概念。
- Phase 2 当前目标仍然应该是 pipeline core：source abstraction → job scheduler → parse/storage state → ingest report。

因此，本轮最稳的产品边界是：

```text
文件 / 文件夹 / zip                 仍是 Phase 2 主上传方式
文件清单 manifest                   可保留为内部/低层 source 能力，但不要占产品叙事中心
data_manifest.json                  作为后续 curated upload 的可选解析输入
Dataset 系统类型                    延后，不进入当前 Phase 2 core
annotation                          现在只作为关联引用和 tag，不解析语义
```

这不是 scope expansion，而是 scope correction：避免把一个“用户提供的组织说明 JSON”误建模成系统内部长期核心对象。

---

## 二、对 `data_manifest.json` 的正确定位

用户给出的例子：

```json
{
  "data": "/path/to/data",
  "annotation": [
    { "path": "/path/to/label1/", "task_type": "segmentation" },
    { "path": "/path/to/label2/", "task_type": "localization" },
    { "path": "/path/to/label3/", "task_type": "detection" }
  ]
}
```

应理解为：

```text
用户上传前已经整理好的目录结构说明
        │
        ▼
系统读取 JSON，发现：
  - data payload 在哪里
  - annotation payload 在哪里
  - annotation 带有什么 task_type tag
        │
        ▼
系统内部只沉淀：
  - data item
  - annotation reference
  - data item 与 annotation reference 的关系
  - task_type 作为普通 tag/metadata
```

不要在这个阶段引入：

- Dataset lifecycle
- Dataset versioning
- Dataset builder
- Annotation parser
- segmentation/localization/detection 语义校验
- 标注格式兼容矩阵
- UI / API / OHIF workflow

这些都是后续产品层能力，不属于当前 Phase 2 pipeline core。

---

## 三、当前 candidate patch 的 manifest 问题

### P0-scope-correction: `ManifestSource(entries[])` 命名容易误导

**位置**:

- `backend/src/dicom_ingestion/sources/manifest.py`
- `backend/src/dicom_ingestion/sources/__init__.py`
- `backend/tests/sources/test_ingest_sources.py`
- `docs/specs/dicom_ingestion_batch7_batch8_spec.md` 7D

当前实现中的 `ManifestSource(entries[])` 本质是：

```text
给我一组显式文件路径，我逐个验证并枚举
```

这可以存在，但它不是用户刚才描述的 `data_manifest.json`。

如果继续叫 `ManifestSource`，后续实现者很容易误会：

```text
manifest = 用户 curated dataset manifest
```

然后把 annotation、dataset、task_type 都塞进 Phase 2 core，导致 scope 变大。

**建议修正**

把当前低层 manifest 改名或降级描述：

```text
FileListSource
FileListManifestSource
ExplicitFileSource
```

文档里明确：

```text
This is an internal/low-level explicit file list source. It is not the user-facing curated data_manifest.json contract.
```

**验收标准**

- 代码和文档不再把 `ManifestSource(entries[])` 表述为产品级 manifest。
- `data_manifest.json` 被列为后续 optional curated upload adapter，不进入当前 Phase 2 core acceptance gate。
- Phase 2 focused tests 不要求完整 dataset/annotation lifecycle。

---

## 四、如果现在要留一个最小 hook，应该怎么留

可以留，但要非常克制。建议只留“关联事实”的入口，不建 Dataset。

### 最小内部形状

```python
@dataclass
class AnnotationRef:
    source_relative_path: str
    task_type: str | None
    label_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class IngestSourceItem:
    source_kind: str
    original_relative_path: str
    size_bytes: int
    open_bytes: Callable[[], bytes]
    annotations: list[AnnotationRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

这里的重点是：

- annotation 是 ref，不是 parsed annotation object。
- `task_type` 是 tag，不是行为分发器。
- `annotations` 可以为空，不影响普通文件/文件夹/zip ingest。
- 不要求当前 storage pipeline 存 annotation 文件内容，除非已有 storage policy 明确支持。

### 最小 report 输出

如果 Phase 2 想提前兼容这个方向，report 里只输出 coverage，不输出 annotation 内容：

```json
{
  "source_summary": {
    "source_kind": "local_folder",
    "curated_manifest_present": true
  },
  "items": [
    {
      "source_relative_path": "data/sample_001/IM0001.dcm",
      "terminal_outcome": "accepted",
      "annotation_refs": [
        {
          "source_relative_path": "label1/sample_001/",
          "task_type": "segmentation",
          "status": "referenced"
        }
      ]
    }
  ],
  "annotation_summary": {
    "referenced_count": 1,
    "missing_count": 0,
    "task_type_counts": {
      "segmentation": 1
    }
  }
}
```

但这仍然可以后置。当前 Phase 2 不需要为了这个 report shape 改大 pipeline。

---

## 五、推荐的阶段切分

### Phase 2 core 继续保持

继续做：

- local folder source
- zip adapter
- file list / explicit file source
- DICOM parse/storage pipeline
- job/item state
- safe ingest report

不做：

- dataset 概念
- annotation 内容解析
- task_type 行为语义
- curated dataset lifecycle

### Phase 2.5 或后续新增：Curated Upload Adapter

后续单独做一个轻量 adapter：

```text
CuratedUploadManifestAdapter
  reads data_manifest.json
  validates data path and annotation paths under allowed roots
  enumerates data files/folders as source items
  attaches annotation refs by relative sample id
  emits annotation coverage in report
```

它应该是 adapter，不是 core domain model。

### Batch 8+ 再考虑 Dataset

当产品真的需要这些能力时，再引入系统内 Dataset：

- dataset object
- dataset sample
- annotation object
- annotation version
- dataset import job
- dataset validation/report UI

这时 `data_manifest.json` 可以成为 dataset import 的一种输入格式，但不是现在。

---

## 六、更新后的 NOT in scope

当前 Phase 2 仍然不包含：

- REST API / FastAPI / HTTP endpoint
- UI / conflict UI
- Redis/RMQ/Celery
- PACS compatibility
- hospital system integration
- generic DICOMweb
-完整 Dataset 系统类型
- Dataset versioning / builder / lifecycle
- Annotation 内容解析
- segmentation / detection / localization 语义实现
- OHIF viewer/annotation workflow，除非未来有具体最小桥接需求

---

## 七、对另一个 AI 的执行建议

如果另一个 AI 正在基于 v0.1 修 Phase 2，建议它这样改：

1. 先修 v0.1 的三个 P1：
   - report-safe projection，不能暴露完整 `parsed_tags` / PHI。
   - rejected item 不保留误导性的 pending axes。
   - bytes-only source materialization 必须清理 temp files。

2. 同时做一个小 scope correction：
   - 把当前 `ManifestSource(entries[])` 改名为 `FileListManifestSource` 或 `ExplicitFileSource`。
   - 文档中说明它不是用户 curated `data_manifest.json`。
   - 不实现完整 `data_manifest.json`。

3. 如果一定要预留 annotation：
   - 只预留 `AnnotationRef` / metadata hook。
   - 不解析 annotation 内容。
   - `task_type` 只当 tag。
   - 不引入 Dataset model。

4. 测试上只需新增：
   - file-list manifest 命名/行为测试继续通过。
   - report 不包含 PHI。
   - 当前 pipeline 不会把 annotation 文件当 DICOM parse。
   - 如果未实现 curated manifest，明确没有相关 acceptance gate。

---

## 八、最终建议

当前最好的路线不是“扩充 Phase 2 支持 dataset manifest”，而是：

```text
Phase 2: 把 DICOM ingest pipeline core 做稳
Phase 2.5: 增加 curated upload manifest adapter，把 data 和 annotation refs 关联起来
Batch 8+: 当产品需要 dataset 工作流时，再引入 Dataset 作为系统类型
```

这样保留了用户上传前整理数据的路径，又不会让 Phase 2 pipeline core 被 dataset/annotation 产品语义拖大。

**状态建议仍为**: `DONE_WITH_CONCERNS`  
**新增阻塞项**: 当前 `ManifestSource` 命名/文档需要校正，避免误导实现方向  
**修正后目标状态**: `READY_FOR_PHASE2_CORE_PR`
