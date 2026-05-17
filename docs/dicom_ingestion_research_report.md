# DICOM Ingestion Module 源码调研报告

## 1. 结论先行

这次研究的目标不是“从几个开源项目里选一个来用”，而是：

> 阅读真实源码，提炼可复用的 ingestion 实现机制，再设计我们自己的 DICOM 数据类型接入模块。

经过源码级阅读后，最重要的结论不是“某个项目最好”，而是下面 8 条：

1. **Header-only parse 必须是一等能力。** XNAT 的 `DicomUtils` 已经把“读到 PixelData 之前停止”做成正式 API，这说明生产系统不会默认把整份 DICOM 都读完。
2. **文件识别要分层。** Dicoogle 的 `IndexerInterface.handles(URI)` 明确承认，单靠路径和扩展名不可靠，最终仍要让 parser 判定。
3. **Indexing 必须有独立任务模型。** Dicoogle 的 `Task<Report>`、批量 `index/unindex`、失败聚合和进度回调，说明索引不是导入函数里的一个 side effect。
4. **Private tag 不是一张配置表能讲清的事。** dcm4che 把 private dictionary 做成按 creator 可扩展注册的体系，这要求我们至少区分 raw retention、vendor dictionary、platform mapping 三层。
5. **影像 ingestion 天生适合 workflow，而不是同步脚本。** Kaapana 的 metadata DAG 把 anonymize、dcm2json、concat、upload、cleanup 拆成显式 stage，并支持并发与重试。
6. **下游 viewer 需求会反向决定 ingestion schema。** OHIF 的 SEG 加载流程要求 referenced display set 和 referenced instances 都存在，这说明 SEG / RTSTRUCT / SR 的引用关系必须在 ingestion 阶段就保存。
7. **接收、落盘、索引、查询投影应该分层。** Dicoogle 的 C-STORE → storage plugin → priority queue → index task → DIM read model，和 Orthanc 的 full instance / MainDicomTags 双层存储，都说明生产系统不会把这些职责揉成一个同步函数。
8. **duplicate 不是单一布尔值。** Posda 同时区分 same-SOP duplicate 与 same-pixel-digest duplicate，并把保留哪一份做成显式 curation flow。

所以，真正的推荐不是“部署 PACS”，也不是“先直接设计”。

真正的推荐是：

> **基于源码证据，构建一个非 PACS 的、任务化的 DICOM ingestion module。**

---

## 2. 研究边界

### 2.1 我们不是在做 PACS

我们要做的是平台内的 DICOM 数据接入模块：

```text
上传文件 / 文件夹 / ZIP
        ↓
临时持久化
        ↓
扫描 / 解压 / 识别 DICOM
        ↓
header-only 解析
        ↓
metadata 标准化
        ↓
Study / Series / Instance 构建
        ↓
原始文件存储 + metadata 入库 + search index
        ↓
映射到 Asset / Dataset Sample / Annotation
```

### 2.2 我们研究开源项目时真正看的东西

| 项目 | 真正研究对象 |
| --- | --- |
| Dicoogle | scanner、indexer、task、storage/index 分离 |
| XNAT | header-only parse、对象识别、业务映射策略 |
| dcm4che | parser、tag model、private dictionary |
| Kaapana | workflow、metadata extraction、分支处理 |
| Posda | duplicate / QC / import governance |
| OHIF | viewer 侧 metadata 消费与引用关系 |
| Orthanc | fast index projection、main tag persistence、rebuild |

---

## 3. 源码级发现

## 3.1 Dicoogle

### 已确认的源码事实

- `dicoogle/src/main/java/pt/ua/dicoogle/server/DicomStorage.java`
  - C-STORE 收到对象后，先委托 storage plugin 落盘，再把返回的 URI 放入索引队列；
- `dicoogle/src/main/java/pt/ua/dicoogle/server/IndexQueueWorker.java`
  - 专门的 worker 从优先级队列取出 URI，再异步 dispatch index；
- `dicoogle/src/main/java/pt/ua/dicoogle/plugins/PluginController.java`
  - `index(URI)` 先按 URI scheme 解析 storage，再把 `StorageInputStream` 交给 indexer；
- `sdk/src/main/java/pt/ua/dicoogle/sdk/datastructs/dim/DIMGeneric.java`
  - DIM 层级模型是在查询结果之后由 `SearchResult.extraData` 聚合出来，不参与原始导入；
- `sdk/src/main/java/pt/ua/dicoogle/sdk/IndexerInterface.java`
  - `index(StorageInputStream file, ...)` 与 `index(Iterable<StorageInputStream> files, ...)` 都返回异步 `Task<Report>`；
  - `unindex(Collection<URI> uris, ...)` 支持批量、进度回调、失败收集；
  - `handles(URI)` 文档明确指出路径 / URI 规则并不总可靠，有疑问时应继续尝试读取，由 indexer 捕获异常。
- `sdk/src/main/java/pt/ua/dicoogle/sdk/task/Task.java`
  - task 有 `uid`、名称、完成回调、创建时间。

### 对我们的直接启发

- `IndexJob` 应该是领域对象，而不是导入里的一个同步步骤；
- `Receive / Store / Index / QueryProjection` 应该拆成不同阶段；
- 我们需要结构化 `report` 和 `failed_items`；
- “扫描过滤”和“最终 DICOM 判定”必须拆开；
- 后续应该支持按 Study / Series / Instance 重建索引。

### 不该照搬

- 不照搬其 PACS 形态；
- 不把 metadata index 直接等同于我们的平台对象模型。

---

## 3.2 XNAT

### 已确认的源码事实

- `libs/dicomtools/src/main/java/org/nrg/dicomtools/utilities/DicomUtils.java`
  - `getMaxStopTagInputHandler()` 被定义为“处理到 PixelData 之前的最大有用范围”；
  - `read(...)` 读取后若没有 `SOPClassUID` 会抛出错误；
  - `read(file, handler)` 支持通过 handler 控制读取范围。
- `web/src/main/java/org/nrg/dcm/id/*`
  - 存在一套可配置、且可按 receiver 变化的 `DicomObjectIdentifier` / routing extractor 体系；
- `web/src/main/java/org/nrg/xapi/rest/dicom/ArchiveProcessorInstanceApi.java`
  - 存在可配置的 processor 实例管理。

### 对我们的直接启发

- parser 层必须原生支持 `header-only` 模式；
- DICOM 识别至少要检查关键 tag，不可只靠文件名；
- metadata 解析和“这份 DICOM 归到哪个平台对象”要解耦；
- 业务映射规则应该可配置，而不是写死在 parser 里。

### 当前源码边界

- XNAT checkout 中能直接确认的是 **identity / routing layer**；
- 真正把 DICOM 转成 Session / Scan 的 builder 实现，至少部分位于外部 `SessionBuilders` 依赖中，而不在当前仓库树内；
- 所以我们可以据此支持“解析层与业务映射层解耦”，但不能把当前仓库单独当作完整的 Session/Scan builder 证据。

### 不该照搬

- 不照搬 XNAT 的 Project / Subject / Session / Scan 业务模型；
- 不沿用其较旧的 dcm4che2 风格 API。

---

## 3.3 dcm4che

### 已确认的源码事实

- `dcm4che-dict-priv/src/main/xsl/PrivateElementDictionary.java.xsl`
  - private dictionary 以 `PrivateElementDictionary` 形式生成；
- `dcm4che-dict-priv/src/main/resources/META-INF/services/org.dcm4che3.data.ElementDictionary`
  - 通过服务发现注册大量厂商私有字典，如 Philips、Siemens、Agfa 等。

### 对我们的直接启发

- private tag 不能只做成“原始 JSON 留存”；
- 应拆成三层：

```text
raw tag retention
        ↓
vendor-aware interpretation
        ↓
platform field mapping
```

- 这样后续新增厂商规则时，不会污染平台核心模型。

### 不该照搬

- 不需要一开始就复刻 dcm4che 的全部私有字典体系；
- 但架构边界应该先设计对。

---

## 3.4 Kaapana

### 已确认的源码事实

- `data-processing/kaapana-plugin/extension/docker/files/dags/dag_collect_metadata.py`
  - 明确的 DAG：`GetInput → LocalDcmAnonymizerOperator(single_slice=True) → LocalDcm2JsonOperator → LocalConcatJsonOperator → MinioOperator → LocalWorkflowCleanerOperator`；
  - DAG 显式设置 `retries=1`、`concurrency=50`、`max_active_runs=50`。
- `data-processing/processing-pipelines/advanced-collect-metadata/.../dag_advanced_collect_metadata.py`
  - 把 CT/MR 与 SEG 走成不同分支，最后再 merge。

### 对我们的直接启发

- ingestion pipeline 应该显式 stage 化；
- cleanup 是正式阶段，不是 finally 里顺手删目录；
- 原始影像与派生对象允许分支处理；
- concurrency / retry 必须是系统配置的一部分，而不是临时 patch。

### 不该照搬

- 不把 Airflow / Kubernetes 的整套复杂度原样搬进 v1；
- 我们借的是 workflow 思想，不是平台体积。

---

## 3.5 OHIF

### 已确认的源码事实

- `platform/app/src/routes/Mode/defaultRouteInit.ts`
  - viewer 会通过 `series.metadata()` 拉取 series 级 metadata；
- `extensions/cornerstone/src/services/ViewportService/CornerstoneViewportService.ts`
  - overlay display set（如 SEG、RTSTRUCT）会通过 `referencedDisplaySetInstanceUID` 找到底图 display set；
- `extensions/cornerstone-dicom-sr/src/utils/hydrateStructuredReport.ts`
  - SR hydration 依赖 `ReferencedSOPInstanceUID + frameNumber` 做引用映射，并据此反推出相关 series / study。

### 对我们的直接启发

- ingestion 阶段就必须保存完整的 series / instance metadata；
- SEG / RTSTRUCT / SR 必须保留可解析引用关系；
- derived asset 不能只保存“我是一份 SEG”，还要知道“我指向谁”。

### 不该照搬

- 不把 viewer 的显示模型直接当平台存储模型；
- 但 viewer 的消费需求必须反向约束 schema。

---

## 3.6 Posda

### 已确认的源码事实

- `queries/sql/DuplicateSopsInSeries.sql`
  - 将“同一 `sop_instance_uid`、不同 `file_id`”定义为 actual duplicate SOP；
- `queries/sql/Checking Duplicate Pixel Data By Series.sql`
  - 通过 `pixel_data_digest` 单独检查像素级重复；
- `PosdaCuration/include/PosdaCuration/DuplicateSopResolution.pm`
  - 把 duplicate 的比较与保留哪份文件做成明确的 curation 流程；
- 另有大量 `import_event` 查询与导入脚本，说明“文件已导入”只是治理流程的一部分。

### 对我们的直接启发

- `imported` 与 `accepted` 不是同一个状态；
- duplicate 至少要区分 identity duplicate 与 content duplicate；
- 生产系统要预留 duplicate、QC、curation 维度；
- 导入后的治理问题需要被建模，而不是被埋进人工脚本。

### 不该照搬

- 不把 Posda 的脚本化 curation 工具链作为 ingestion 主架构；
- 它更适合作为导入后治理参考。

---

## 3.7 Orthanc

### 已确认的源码事实

- `OrthancServer/Sources/Database/MainDicomTagsRegistry.cpp`
  - `MainDicomTags` 是正式的 fast projection，不是临时缓存；
- `OrthancServer/Sources/ServerIndex.cpp`
  - index 层围绕这些主标签做独立持久化与查询；
- `OrthancServer/UnitTestsSources/ServerIndexTests.cpp`
  - 存在 `DicomUntilPixelData` 测试；
- `NEWS`
  - 多个版本都提到 `ExtraMainDicomTags`、`ReconstructMainDicomTags`、`LimitMainDicomTagsReconstructLevel` 等机制。

### 对我们的直接启发

- full DICOM payload 与 fast query projection 应该分层；
- query projection 需要可演进、可重建；
- 这能避免把全部解析结果一次性塞进一个巨大而僵化的 ingestion 表。

### 不该照搬

- 不把 Orthanc 的 PACS 资源树直接当成我们的平台数据模型；
- 借的是“canonical source + fast projection”这个结构，而不是它的整套产品边界。

---

## 3.8 dcm4che 进一步深挖

### 已确认的源码事实

- `dcm4che-core/src/main/java/org/dcm4che3/io/DicomInputStream.java`
  - 显式提供 `readDatasetUntilPixelData()`；
  - 其底层通过 `Predicate<DicomInputStream>` 在 `readAttributes(...)` 中中止解析；
- `dcm4che-core/src/main/java/org/dcm4che3/data/ElementDictionary.java`
  - private dictionary 以 `privateCreator` 为键，通过 `ServiceLoader` 解析；
- `dcm4che-core/src/main/java/org/dcm4che3/data/Attributes.java`
  - 读取 private value 的 API 持续把 `privateCreator` 与 numeric tag 一起传递。

### 对我们的直接启发

- `header_only` 应该是 ingestion contract 的显式模式，而不是内部小优化；
- private tag 的最小安全身份不是 `(group, element)`，而是 `(private_creator, tag)`；
- raw retention、creator-aware interpretation、platform mapping 三层边界现在有了更硬的源码支撑。

---

## 4. 经过源码修正后的推荐架构

```text
[Upload API]
     ↓
[Temporary Durable Storage]
     ↓
[IngestionJob]
     ↓
[Fast Filter / Scanner]
     ↓
[Header Parser: stop before PixelData]
     ↓
[Metadata Normalizer]
     ↓
[Study / Series / Instance Builder]
     ↓
[Asset Mapper]
     ↓
[Primary DB] + [Raw Tag Store] + [Search Index Job]
     ↓
[Object Storage]
     ↓
[QC / Derived Asset / Viewer Consumers]
```

### 这版架构和旧版最大的不同

| 旧版含糊表述 | 源码研究后的具体修正 |
| --- | --- |
| 支持 metadata 解析 | 默认 header-only，stop before PixelData |
| 支持 private tag | raw retention + vendor dictionary + platform mapping |
| 支持索引 | 独立 IndexJob + report + failed items + rebuild |
| 支持任务 | 显式 stage、retry、cleanup、branching |
| 支持 annotation / viewer | 保存 referenced object graph，不是后补 |
| 支持质控 | 区分 imported 与 accepted，预留 QC / duplicate 状态 |

---

## 5. 我们真正借鉴了什么

### 从 Dicoogle 借

- 异步 index task；
- 批量失败报告；
- 识别分层；
- storage 与 index 解耦。

### 从 XNAT 借

- header-only parse；
- 关键 tag 校验；
- 解析和业务归属分层。

### 从 dcm4che 借

- private tag 的 creator-aware 字典体系。

### 从 Kaapana 借

- workflow stage 化；
- 并发 / 重试配置化；
- 原始影像与派生对象分支处理。

### 从 OHIF 借

- ingestion schema 必须服务下游引用关系。

### 从 Posda 借

- duplicate / QC / curation 是独立问题，不是导入成功后的附属日志。

---

## 6. 现在还没有完全定死的 3 个问题

经过第二轮源码深挖后，主干方向已经足够稳定，可以进入架构设计；但下面 3 件事仍然是**产品 / 实现选择**，不是源码自动替我们决定的：

1. **是否在 v1 就物理持久化 `bytes-until-pixel-data` 这类派生对象。**
   - Orthanc 证明了它在成熟系统里有价值；
   - 但我们是否一开始就需要，取决于对象存储读放大、压缩策略和典型查询负载。
2. **private tag 的首批解释范围。**
   - 架构边界已清楚；
   - 但首批到底支持哪些厂商 creator，需要由目标数据集和客户场景决定。
3. **branching workflow 的第一版形态。**
   - Kaapana 证明“派生对象会让 DAG 分叉”；
   - 但我们第一版是上通用 workflow engine、typed dispatcher，还是 staged job runner，还需要结合平台现状取舍。

---

## 7. 下一步

下一阶段可以进入详细设计了，但设计时要把上面 3 个未决问题显式保留为 decision points，而不是假装源码已经替我们做完选择。

此时已经满足 3 个进入设计的门槛：

1. 每个关键模块都有至少一个源码级借鉴来源；
2. 每条主推荐都能回指到真实实现或明确的一阶推理；
3. 每个“我们不借什么”也都有具体理由，而不是偏好。

---

## 8. 研究落地

基于前述源码研究，已经形成可执行的模块架构文档：

- `docs/006_dicom_ingestion_architecture.md`

该文档将研究结论收敛为：

1. v1 必须实现的 ingestion spine；
2. 需要预留但暂不完整实现的 branch / curation / vendor interpretation 能力；
3. 明确不进入当前范围的 PACS 化、全量 viewer、全量 workflow engine 等工作。

这意味着研究阶段已经完成从“借鉴他人实现”到“形成自身系统设计”的转换。
