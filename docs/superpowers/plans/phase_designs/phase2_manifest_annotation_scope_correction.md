# Phase 2 Design Correction: Manifest 与 Annotation Scope

**日期**: 2026-05-19  
**适用阶段**: Phase 2 Ingestion Pipeline  
**修正对象**: `phase2_ingestion_pipeline_design.md` 中关于 `MANIFEST_FILE` / `ManifestSource` 的语义  
**状态**: Active design correction

---

## 1. 结论

Phase 2 继续以 **pipeline core** 为目标：

```text
source abstraction → job scheduler → parse/storage state → ingest report
```

本阶段不把 `data_manifest.json` 升级为系统内部核心模型，也不引入完整 Dataset 概念。

用户提供的 `data_manifest.json` 只是上传前的数据组织说明：系统可以读取它，用来发现 data 与 annotation 的对应关系，但内部当前只需要沉淀关联事实，不需要立刻建立 Dataset lifecycle。

---

## 2. 不变的上传方式

原有上传方式不被推翻：

```text
文件上传
文件夹上传
zip 上传
```

这些仍然是 Phase 2 的主路径。

manifest 是新增的可选输入方式，不是替代方式，也不是 Phase 2 的中心抽象。

---

## 3. 两种 manifest 必须区分

### 3.1 低层文件清单 manifest

这是工程侧 source abstraction 的一种形式：

```text
给系统一组明确文件路径，系统逐个验证、枚举、摄入
```

如果保留，建议命名为：

```text
FileListManifestSource
ExplicitFileSource
```

不要命名为裸 `ManifestSource`，避免和用户侧 `data_manifest.json` 混淆。

### 3.2 用户侧 curated `data_manifest.json`

用户侧 manifest 表达的是：

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

它的含义是：

```text
用户已经在上传前整理好了数据目录
系统根据 JSON 找到 data payload 与 annotation payload
系统建立 data item ↔ annotation reference 的关系
```

它不是当前阶段的系统内部 Dataset schema。

---

## 4. Annotation 当前只作为关联引用

Phase 2 如果接触 annotation，只做最小事实表达：

```text
data item
  └── annotation reference(s)
        ├── source_relative_path
        ├── task_type tag
        └── optional metadata
```

当前不做：

- annotation 文件内容解析
- segmentation / localization / detection 语义实现
- annotation 格式兼容矩阵
- annotation versioning
- dataset sample lifecycle
- viewer/OHIF annotation workflow

`task_type` 当前只作为 tag，不作为行为分发依据。

---

## 5. 推荐内部最小形状

如果实现者需要为后续 curated upload 预留 hook，建议只预留引用结构：

```python
@dataclass
class AnnotationRef:
    source_relative_path: str
    task_type: str | None
    label_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

并允许 source item 挂载 annotation refs：

```python
@dataclass
class IngestSourceItem:
    source_kind: str
    original_relative_path: str
    size_bytes: int
    open_bytes: Callable[[], bytes]
    annotations: list[AnnotationRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

这只是兼容未来，不要求当前 Phase 2 完成 curated manifest adapter。

---

## 6. 推荐阶段切分

### Phase 2: Pipeline Core

做：

- `LocalFolderSource`
- ZIP adapter，复用 existing scanner
- explicit file list source，如果需要
- DICOM parse/storage pipeline
- job/item state transitions
- report-safe ingest report

不做：

-完整 Dataset 系统类型
- curated dataset lifecycle
- annotation 内容解析
- task_type 语义行为

### Phase 2.5: Curated Upload Manifest Adapter

后续可以新增：

```text
CuratedUploadManifestAdapter
  reads data_manifest.json
  validates data and annotation paths under allowed roots
  enumerates data payloads
  attaches annotation refs
  emits annotation coverage in ingest report
```

注意：它是 adapter，不是 core domain model。

### Batch 8+ 或更后续: Dataset Product Surface

当产品真正需要 dataset workflow 时，再设计：

- Dataset
- DatasetSample
- AnnotationObject
- AnnotationVersion
- Dataset import job
- Dataset validation/report UI

---

## 7. 对 Phase 2 实现计划的具体修正

原设计中的：

```text
IngestSource
  - ZipArchiveSource
  - LocalFolderSource
  - ManifestSource(entries[])
```

建议改为：

```text
IngestSource
  - ZipArchiveSourceAdapter
  - LocalFolderSource
  - FileListManifestSource / ExplicitFileSource
```

并补充说明：

```text
Curated data_manifest.json is deferred to Phase 2.5 as an adapter that attaches annotation refs. It is not the Phase 2 core manifest source.
```

---

## 8. Acceptance Gate 修正

Phase 2 core acceptance 不要求：

- 完整解析 `data_manifest.json`
- 建立 Dataset 模型
- 存储 annotation 对象
- 解析 annotation 内容
- 根据 `task_type` 做业务行为

Phase 2 core 可以要求：

- 当前低层 file-list source 不被误命名为产品 manifest。
- report 不泄露内部绝对路径或 PHI。
- annotation 文件不会被误送入 DICOM parser。
- 如果预留 annotation refs，report 只输出引用与 coverage，不输出 annotation 内容。

---

## 9. NOT in scope

本修正明确以下内容不进入 Phase 2：

- REST API / FastAPI / HTTP endpoint
- UI / conflict UI
- Redis/RMQ/Celery
- PACS compatibility
- hospital system integration
- generic DICOMweb
- Dataset lifecycle
- Dataset versioning / builder
- Annotation parser
- segmentation / localization / detection 语义实现
- OHIF viewer/annotation workflow，除非未来有具体最小桥接需求

---

## 10. Review Trace

本设计修正来自：

- `docs/superpowers/reviews/batch7_phase2_pipeline_core_review_v0.2.md`

review 文件保留为审查记录；本文件作为 Phase 2 后续实现时更直接的设计约束。
