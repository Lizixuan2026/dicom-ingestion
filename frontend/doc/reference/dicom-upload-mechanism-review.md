# DICOM 数据接入上传机制 Review

> 基于 `some_platform-upload-mechanisms.md` 的上传机制梳理，以及本项目现有后端 ingestion 设计约束整理。
>
> 结论日期：2026-05-20
> 分支：`prototype_design`

---

## 1. 结论

DICOM / 医学数据接入不应该照搬参考平台的某一套上传接口，也不应该只在 ZIP、多文件、文件夹、路径之间做单选。

推荐方案是：

```text
普通用户默认入口：上传文件夹
普通用户备选入口：上传 ZIP
轻量入口：选择多个文件
高级入口：Manifest 导入
管理员/本地部署入口：服务器路径 / 对象存储路径导入
```

其中，最值得参考的是参考平台的 **方式三：模型注册 - 分片上传（大文件/文件夹）**。

原因：它同时满足医学数据接入最重要的三件事：

1. 支持文件夹选择；
2. 通过 `webkitRelativePath` 保留目录结构；
3. 支持大文件/大量文件场景下的分片上传、并发控制和重试。

但我们不能完全照搬它。参考平台偏向“文件存储服务优先”，而本项目需要“ingestion pipeline 优先”。上传完成不是终点，上传完成后必须进入扫描、解析、校验、报告、Dataset/Data Version/Manifest 生成流程。

---

## 2. 为什么推荐参考方式三

参考方式三的关键能力：

```text
用户选择文件夹
  ↓
浏览器展开为 File[]
  ↓
每个 File 携带 webkitRelativePath
  ↓
前端按文件切片上传
  ↓
后端合并分片
  ↓
业务层记录 file_path / storage_key
```

这套机制适合 DICOM 接入的部分是：

- DICOM 数据经常以文件夹/树结构存在；
- 目录结构本身可能包含 patient、study、series、annotation、mask 等线索；
- 医学影像数据可能包含大量小文件，也可能包含较大文件；
- 上传过程需要进度、取消、失败重试；
- 后端需要知道每个文件的原始相对路径，不能只看到扁平文件名。

因此，前端应借鉴：

- `webkitdirectory` / 文件夹拖拽；
- `webkitRelativePath` 路径保留；
- 分片上传；
- 并发控制；
- 上传进度；
- 取消与重试。

---

## 3. 不能照搬的地方

参考平台的方式三最终更像是：

```text
上传文件 -> 得到 storage_key -> 关联模型注册
```

本项目不能停在这个层次。

本项目上传后应进入：

```text
UploadPackage / IngestSource
  ↓
InputTree / IngestSourceItem
  ↓
scanner
  ↓
parser
  ↓
validation report
  ↓
Dataset / Data Version / Manifest
```

也就是说，前端上传方式只是 transport，后端 ingestion source 才是业务入口。

后端不要因为前端入口不同而分裂成多套业务逻辑。ZIP、文件夹、多文件、路径、manifest 都应该统一收敛到同一个输入抽象。

---

## 4. 推荐后端抽象

建议所有上传/导入入口最终统一为：

```text
FolderUploadSource
ZipArchiveSource
MultiFileUploadSource
ServerPathSource
ManifestSource
        ↓
InputTree
        ↓
IngestSourceItem[]
```

每个 `IngestSourceItem` 至少包含：

```python
@dataclass
class IngestSourceItem:
    source_kind: Literal[
        "folder_upload",
        "zip",
        "multi_file",
        "server_path",
        "manifest",
    ]
    original_relative_path: str
    size_bytes: int
    content_type_guess: str | None
    open_bytes: Callable[[], bytes]
```

关键约束：

- scanner 只消费 `IngestSourceItem`，不直接关心来源是 ZIP 还是文件夹；
- 必须保留 `original_relative_path`；
- 不可读文件、非 DICOM 文件、坏文件应进入报告，而不是让整个任务静默失败；
- ZIP、路径、manifest 都必须有安全边界；
- 用户重新上传是新的 ingest job，不应被误当成 retry。

---

## 5. ZIP 上传 vs 多文件上传

ZIP 和多文件上传都应该支持，但产品定位不同。

| 对比项 | ZIP 上传 | 多文件上传 |
|---|---|---|
| 用户操作 | 先压缩，再上传 | 直接选择多个文件 |
| 目录结构 | ZIP 内路径可完整保留 | 普通多文件选择通常会丢目录结构 |
| 后端处理 | 需要解压和 ZIP 安全扫描 | 直接逐文件进入 source item |
| 原始证据包 | 容易保存一个完整原始包 | 需要记录每个文件的上传来源 |
| 大批量稳定性 | 较好 | 大量小文件会增加请求/浏览器管理复杂度 |
| 小批量体验 | 稍重 | 更轻 |
| 同名文件风险 | 低，只要保留 ZIP 内路径 | 高，如果只有 `file.name` |
| 推荐定位 | 正式批量导入 / 已打包数据 | 快速测试 / 少量文件导入 |

产品提示建议：

```text
选择多个文件不会保留本地文件夹结构。
如需保留 patient/study/series 等目录结构，请上传文件夹或 ZIP。
```

---

## 6. 各入口的产品定位

### 6.1 上传文件夹：默认主入口

推荐作为 DICOM 接入默认入口。

适合：

- 本地已有 DICOM 文件夹；
- 需要保留目录结构；
- 大量文件；
- 用户希望直接拖拽整个数据目录。

前端要求：

- 支持点击选择文件夹；
- 支持拖拽文件夹；
- 保留 `webkitRelativePath`；
- 展示总文件数、总大小、上传进度；
- 支持取消和失败重试。

### 6.2 上传 ZIP：强支持备选入口

适合：

- 用户已经拿到压缩包；
- 数据需要跨机器传输；
- 希望保存一个完整原始上传包；
- 批量交付数据。

后端要求：

- raw ZIP 先持久化；
- 解压前做 ZIP 安全检查；
- 检查 zip bomb、path traversal、嵌套 zip、超大 entry、超大总解压体积；
- ZIP 内路径转成 `original_relative_path`。

### 6.3 多文件上传：轻量入口

适合：

- 少量 DICOM 文件；
- 临时测试；
- 用户不关心目录结构。

限制：

- 普通多文件选择通常不保留目录结构；
- 同名文件可能冲突；
- 不适合作为正式医学数据集导入的默认入口。

### 6.4 Manifest 导入：高级/curated 入口

适合：

- curated dataset；
- 明确 sample 结构；
- 多模态引用；
- annotation/mask/label 绑定；
- 可复现导入。

不建议作为普通用户第一入口。

### 6.5 服务器路径 / 对象存储路径导入：管理员入口

适合：

- 本地部署；
- NAS；
- 后端机器已经能访问数据目录；
- 云对象存储中已有数据。

必须限制：

- 普通浏览器用户不能上传任意本地路径；
- server-side path 必须经过 allowlist root 校验；
- 对象存储凭据不能随意明文长期保存；
- 导入报告中不要泄漏敏感绝对路径。

---

## 7. 推荐前端信息架构

建议把“接入方式”从平级 radio 改成普通入口 + 高级入口。

```text
数据源

推荐
[ 上传文件夹 ]
保留目录结构，适合 DICOM 数据集、patient/study/series 文件树。

[ 上传 ZIP ]
适合已有压缩包或批量交付数据。

[ 选择多个文件 ]
适合少量文件快速测试，不保留文件夹结构。

高级
[ Manifest 导入 ]
适合 curated dataset、多模态引用、annotation/mask/label 绑定。

[ 从服务器路径导入 ]
仅限管理员/本地部署/NAS/对象存储路径。
```

当前原型中类似：

```text
本地上传 DICOM 文件 / ZIP
文件夹上传
Manifest 导入
```

建议改为：

```text
上传文件夹（推荐）
上传 ZIP
选择多个文件
Manifest 导入（高级）
服务器路径导入（高级/管理员）
```

---

## 8. 推荐实现优先级

### Phase A：原型/交互先定清楚

- 默认展示“上传文件夹”；
- ZIP 和多文件作为同级备选；
- Manifest、服务器路径放高级区；
- 明确提示多文件上传不保留目录结构；
- 在摘要区展示预计文件数、总大小、目录层级是否保留。

### Phase B：前端上传 facade

建立统一 `UploadFacade`，业务层不直接依赖某一种上传实现。

```typescript
type UploadSourceKind =
  | 'folder'
  | 'zip'
  | 'multi_file'
  | 'manifest'
  | 'server_path';

interface UploadSourceDescriptor {
  kind: UploadSourceKind;
  files?: File[];
  relativePaths?: Record<string, string>;
  zipFile?: File;
  manifestFile?: File;
  serverPath?: string;
}
```

### Phase C：后端 ingestion source adapter

后端按来源生成统一 `IngestSourceItem[]`：

- folder upload → `FolderUploadSource`；
- ZIP → `ZipArchiveSource`；
- multi-file → `MultiFileUploadSource`；
- server path → `ServerPathSource`；
- manifest → `ManifestSource`。

### Phase D：大文件/大量文件增强

- 文件夹上传使用分片；
- 支持并发控制；
- 支持取消；
- 支持失败重试；
- 上传进度和后端解析进度分开展示。

---

## 9. 最终建议

采用参考平台方式三作为主要技术参考，但只借鉴其上传 transport 能力，不照搬其业务边界。

最终产品策略：

```text
默认：上传文件夹
强支持：上传 ZIP
轻量：选择多个文件
高级：Manifest 导入
管理员：服务器路径 / 对象存储路径导入
```

最终架构策略：

```text
不同上传方式
  ↓
统一 InputTree / IngestSourceItem
  ↓
统一 scanner / parser / validation / report
  ↓
Dataset / Data Version / Manifest
```

这能同时满足用户体验、医学数据目录结构保留、后端安全边界和后续 curated/multimodal 扩展。
