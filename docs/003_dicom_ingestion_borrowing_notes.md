# DICOM Ingestion 模块借鉴笔记

## 文件识别与扫描

### 借鉴自 Dicoogle

**源码证据**：`IndexerInterface.handles(URI)` 的文档明确承认，单靠 URI / 扩展名并不可靠，若不能确定应允许进入 indexer，再由读取异常兜底。

**转化到我们的设计**：

```text
快速过滤层：文件名 / magic bytes / 大小 / zip entry
最终判定层：header parser + 必要 tag 校验
```

**我们要拿走的东西**：识别分层。不要把 `.dcm` 扩展名当真理。

---

## Header-only 解析

### 借鉴自 XNAT

**源码证据**：`DicomUtils.getMaxStopTagInputHandler()` 明确把“读到 PixelData 之前”定义为最大有用范围；`read()` 在缺少 `SOPClassUID` 时直接报错。

**转化到我们的设计**：

- ingestion 默认 `header_only=true`；
- DICOM 识别不能只靠后缀，至少校验 `SOPClassUID` / 基本结构；
- 需要支持“按 stop tag 读取”的 parser API。

**我们要拿走的东西**：性能默认值要体现在接口里，不靠调用方自觉。

---

## Index task

### 借鉴自 Dicoogle

**源码证据**：`IndexerInterface.index(...)` 返回异步 `Task<Report>`；批量 `unindex` 支持失败聚合和进度回调；`Task` 自带 uid、名称、完成 hook。

**转化到我们的设计**：

- `IngestionJob` 与 `IndexJob` 可以分层；
- 每个 job 需要 uid、状态、report、failed items；
- 支持按 Study / Series / Instance 触发重建索引；
- “失败了多少个”要成为结构化结果，不是日志里的自然语言。

**我们要拿走的东西**：任务是领域对象，不是线程池里的匿名 lambda。

---

## Private tag

### 借鉴自 dcm4che

**源码证据**：`dcm4che-dict-priv` 通过 `PrivateElementDictionary` 与 `META-INF/services/...ElementDictionary` 按 private creator 注册大量私有字典。

**转化到我们的设计**：

```text
raw tag retention
        ↓
vendor dictionary / creator-aware interpretation
        ↓
platform field mapping
```

**我们要拿走的东西**：private tag 不是一个“额外字段表”，而是一套分层解释体系。

---

## Workflow

### 借鉴自 Kaapana

**源码证据**：`dag_collect_metadata.py` 把 `GetInput → DcmAnonymizer → Dcm2Json → ConcatJson → Minio → Cleaner` 显式建成 DAG，并设置 retry / concurrency / max_active_runs；`advanced_collect_metadata` 又把 SEG 分支拆出来后再 merge。

**转化到我们的设计**：

- ingestion pipeline 应显式 stage 化；
- 原始影像、派生对象、质控对象允许分支处理；
- 清理 temp storage 应是正式 stage，不是“最后顺手删一下”；
- stage 级别需要 retry、timeout、metrics。

**我们要拿走的东西**：复杂影像处理天然是 workflow，不是 controller 里的长函数。

---

## 下游引用关系

### 借鉴自 OHIF

**源码证据**：`defaultRouteInit.ts` 通过 `series.metadata()` 拉取 series metadata；`SegmentationService.createSegmentationForSEGDisplaySet()` 依赖 `referencedDisplaySetInstanceUID`，找不到 referenced display set 或 referenced instances 会直接抛错。

**转化到我们的设计**：

- ingestion 必须保存原始 series / instance metadata；
- SEG / RTSTRUCT / SR 必须保存可解析的引用关系；
- derived asset 不能只存“这是一个 SEG”，还要能反查原始影像对象。

**我们要拿走的东西**：viewer 不是后话，它会倒逼 ingestion schema。

---

## 质量治理

### 借鉴自 Posda

**源码证据**：仓库中存在 `DuplicateSopResolution.pm`、重复 SOP 查询、重复 pixel digest 查询、import event 查询等一整套后导入治理能力。

**转化到我们的设计**：

- `imported` 不等于 `accepted`；
- 需要单独的 duplicate / QC / curation 维度；
- v1 不一定全做，但 schema 不应堵死未来。

**我们要拿走的东西**：生产系统里，导入之后真正麻烦的事才开始。

---

## 目前最值得直接影响我们设计的 6 个结论

1. `header-only parse` 必须是 parser 的一等能力，而不是调用方约定。
2. file identification 要分“快速过滤”和“最终判定”两层。
3. indexing 需要独立 job/report 模型，支持批量和重建。
4. private tag 需要三层结构：原始保留、厂商解释、平台映射。
5. 原始影像与派生对象应允许走分支 workflow，再统一汇总。
6. ingestion schema 必须从第一天保留 SEG / RTSTRUCT / SR 引用关系。
