# some_platform 上传机制全梳理

> 本文档基于代码走读整理，汇总 some_platform 平台中各种数据上传的技术实现细节
> 
> 生成时间: 2026-05-20

---

## 1. 总体架构概览

some_platform 没有统一的「全站通用上传组件」，而是根据业务场景分成了多套上传方案。底层虽然有共享的文件服务能力（`/api/v1/files/*`），但各业务模块的前端接入方式不同。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         前端业务模块                                       │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────────────┤
│  知识库      │  数据集      │  模型注册    │  镜像构建    │   智能体导入     │
│  (KB)       │  (Data Hub)  │  (Model)    │  (Image)    │   (Agent)       │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴────────┬────────┘
       │             │             │             │               │
       ▼             ▼             ▼             ▼               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     前端服务层 (Service Layer)                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐  │
│  │ file-upload-svc  │  │ dataset-service  │  │ model-registry-svc     │  │
│  │   (通用批量)      │  │   (XHR直连)       │  │   (分片上传)            │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ /files/upload    │  │ /files/batch    │  │ /files/chunked/* │
│ (单文件)         │  │ -upload         │  │ (分片上传)       │
│                  │  │ (批量文件)       │  │                  │
└─────────────────┘  └─────────────────┘  └─────────────────┘
       │                       │                       │
       └───────────────────────┼───────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     后端 FastAPI 路由层                                    │
│                    routes/v1/file.py                                     │
└─────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     文件存储层                                           │
│        PostgreSQL (元数据) + 对象存储/本地 (文件本体)                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 七种上传方式详解

### 2.1 方式一：通用批量文件上传（最常用）

**典型场景**
- 知识库创建/编辑时的文件上传
- 训练数据、评估数据集上传
- 通用文件管理功能

**用户操作**
- 拖拽或点击选择**单个或多个文件**
- 通过 `accept` 属性限制文件类型（如 `.pdf`, `.txt`, `.json`）
- 通常限制：最多 10 个文件，每个 50MB 以内

**前端处理**

```typescript
// src/frontend/services/common/file-upload-service.ts
class FileUploadService extends BaseService {
  public async uploadFileBatch(
    files: Array<File | Blob>,
    platform?: string,
    format?: string
  ): Promise<IFileUploadResponse[]> {
    const formData = new FormData();
    files.forEach(file => {
      const filename = file instanceof File 
        ? file.name 
        : `upload_${Date.now()}_${Math.random().toString(36).substr(2, 9)}.bin`;
      formData.append('files', file, filename);  // ← 注意是 'files' 复数
    });
    if (platform) formData.append('platform', platform);
    if (format) formData.append('format', format);
    
    return apiService.upload<IFileUploadResponse[]>(this.serviceURL, formData);
  }
}

// 导出三个 service 实例
export const fileUploadService = new FileUploadService('files/upload');       // 单文件
export const fileUploadBatchService = new FileUploadService('files/batch-upload');  // 批量
export const fileDeleteService = new FileUploadService('files');              // 删除
```

**关键特征**
- **整文件上传**：不做分片，一次性通过 `multipart/form-data` 发送
- **Axios 封装**：通过 `apiService.upload()` 发送，最终会调用 Axios POST
- **自动鉴权**：请求拦截器会自动添加 `Authorization` 和 `WorkspaceID`
- **FormData 格式**：浏览器自动处理 `boundary`，不需要手动设置 `Content-Type`

**后端接收**

```python
# src/backend/src/routes/v1/file.py:314
@router.post(
    "/batch-upload",
    response_model=ResponseEnvelope[List[FileDetail]],
    status_code=status.HTTP_201_CREATED,
    summary="批量上传文件",
)
async def batch_upload_files(
    files: List[UploadFile] = File(...),  # FastAPI 自动解析多个文件
    scope: str = Form("workspace"),
    platform: str = Form("agent"),
    ...
) -> ResponseEnvelope[List[FileDetail]]:
```

**调用链路**

```
FileUpload 组件 / KnowledgeBaseCreateFlow
    ↓
uploadFileBatch(files, 'model', fintuneType)  // store 层
    ↓
fileUploadBatchService.uploadFileBatch()      // service 层
    ↓
apiService.upload('files/batch-upload', formData)  // api-service 层
    ↓
Axios POST http://.../api/v1/files/batch-upload
    ↓
后端 FastAPI batch_upload_files() 接收
```

---

### 2.2 方式二：数据集详情页上传（XHR 直连）

**典型场景**
- Data Hub → 数据集详情 → 上传文件到特定目录

**用户操作**
- 点击「上传」按钮，弹出文件选择器
- 可选择**多个文件**
- 可选择上传到哪个**虚拟目录前缀**（`prefix` 参数）

**前端处理**

```typescript
// src/frontend/stores/data/dataset-management-store.ts:261-294
uploadFile: async (
  datasetId: string | number,
  file: File,
  onProgress?: (progress: number) => void
) => {
  const formData = new FormData();
  formData.append('file', file);  // ← 注意是 'file' 单数

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    
    // 实时进度回调
    xhr.upload.onprogress = event => {
      if (event.lengthComputable && onProgress) {
        const progress = Math.round((event.loaded / event.total) * 100);
        onProgress(progress);
      }
    };
    
    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`Upload failed: ${xhr.statusText}`));
      }
    };
    
    // 直接构造完整 URL
    xhr.open('POST', `/api/v1/data-hub/raw-datasets/${datasetId}/files`);
    xhr.setRequestHeader('Authorization', `Bearer ${localStorage.getItem('access_token') || ''}`);
    xhr.send(formData);
  });
}
```

**关键特征**
- **原生 XHR**：不使用 Axios 封装，直接 `new XMLHttpRequest()`
- **进度可见**：通过 `xhr.upload.onprogress` 实现实时进度条
- **独立 API**：走 `data-hub/raw-datasets` 域专属接口，不是通用 `/files`
- **目录前缀**：通过 query 参数 `?prefix=/some/path` 指定上传到哪个目录

**后端接收**

```python
# src/backend/src/routes/v2/datasets.py (data-hub 相关路由)
# POST /api/v1/data-hub/raw-datasets/{dataset_id}/files
# 接收单个文件，可带 prefix 参数
```

**与方式一的区别**

| 特性 | 方式一 (通用批量) | 方式二 (数据集 XHR) |
|------|------------------|-------------------|
| 前端封装 | Axios (apiService) | 原生 XHR |
| 进度支持 | 无（或需额外配置） | 有 (onprogress) |
| API 路径 | `/files/batch-upload` | `/data-hub/raw-datasets/{id}/files` |
| 文件字段 | `files` 复数 | `file` 单数 |
| 目录前缀 | 不支持 | 支持 (query 参数) |

---

### 2.3 方式三：模型注册 - 分片上传（大文件/文件夹）

**典型场景**
- 模型注册页 → 上传整个模型文件夹（可能包含 GB 级大文件）
- 需要保留完整的目录结构

**用户操作**
- 选择**整个文件夹**（通过 `<input webkitdirectory directory>`）
- 或拖拽文件夹到上传区域
- 浏览器会把文件夹展开成多个带路径的 File 对象

**前端处理**

```typescript
// src/frontend/stores/model/model-registry-store.ts
const CHUNK_SIZE = 5 * 1024 * 1024;  // 5MB 一片
const GLOBAL_CHUNK_CONCURRENCY = 6;  // 最多6个分片并发

async preUploadFiles(files: File[], reset?: boolean) {
  const fileTasks = files.map(file => async () => {
    // 1. 计算分片数
    const totalParts = Math.ceil(file.size / CHUNK_SIZE);
    
    // 2. 保留相对路径（webkitRelativePath 包含完整目录结构）
    const relativePath = normalizeRelativePath(
      (file as any).webkitRelativePath, 
      file.name
    );
    
    // 3. 发起上传会话
    const initiateRes = await modelRegistryService.initiateChunkedUpload({
      filename: file.name,
      size: file.size,
      total_parts: totalParts,
      content_type: file.type || 'application/octet-stream',
    });
    const upload_id = (initiateRes as any)?.upload_id;
    
    // 4. 并行上传分片
    await uploadChunksParallel(
      upload_id, 
      file, 
      totalParts,
      new Set<number>(),  // 已上传的分片集合
      () => { /* 进度回调 */ },
      () => { /* 取消检查 */ }
    );
    
    // 5. 完成合并
    const completeRes = await modelRegistryService.completeChunkedUpload({
      upload_id,
      filename: file.name,
      size: file.size,
    });
    const storage_key = (completeRes as any)?.key;
    
    // 6. 保存结果供后续关联模型
    preUploadedFiles.push({
      file_name: file.name,
      file_path: relativePath,
      storage_key,
      ...
    });
  });
  
  // 多文件并行上传
  await Promise.all(fileTasks.map(task => task()));
}
```

**分片上传细节**

```typescript
// 单个分片上传
async function uploadChunk(upload_id: string, part_number: number, chunk: Blob) {
  const form = new FormData();
  form.append('upload_id', upload_id);
  form.append('part_number', String(part_number));
  form.append('file', chunk);  // 5MB 的二进制块
  
  return apiService.post('/files/chunked/part', form);
}
```

**关键特征**
- **5MB 分片**：每个文件切成 5MB 小块，降低大文件上传失败风险
- **并发控制**：最多 6 个分片同时上传，平衡速度和稳定性
- **断点续传**：记录已上传的分片，失败可重试缺失部分
- **路径保留**：使用 `webkitRelativePath` 保留完整目录结构
- **三步流程**：initiate → upload parts → complete

**后端接口**

```python
# src/backend/src/routes/v1/file.py:573-808

# 1. 发起上传会话
POST /files/chunked/initiate
Body: { filename, size, total_parts, content_type }
Response: { upload_id, key }

# 2. 上传单个分片（可并发调用）
POST /files/chunked/part
FormData:
  - upload_id: str
  - part_number: int
  - file: bytes (5MB chunk)

# 3. 完成合并
POST /files/chunked/complete
Body: { upload_id, filename, size }

# 4. 查询状态（用于断点续传）
GET /files/chunked/status/{upload_id}

# 5. 取消上传
POST /files/chunked/abort?upload_id=xxx
```

**分片服务实现**

```python
# src/backend/src/shared/infrastructure/storage/chunked_upload.py
class ChunkedUploadService:
    async def initiate(self, filename, total_size, total_parts, ...):
        # 创建 upload_id，建立临时目录
        # {upload_storage_dir}/.chunks/{upload_id}/_meta.json
        
    async def save_part(self, upload_id, part_number, data):
        # 写入分片文件
        # {upload_storage_dir}/.chunks/{upload_id}/part_00001
        
    async def complete(self, upload_id):
        # 按顺序合并所有分片
        # 校验 checksum
        # 转存到最终位置
        # 清理临时分片
```

---

### 2.4 方式四：对象存储路径（只传路径，不上传文件）

**典型场景**
- 模型注册 → 选择「对象存储」方式
- 文件已经存在 OBS/HuaweiCloud/S3 中，不需要浏览器上传

**用户操作**
- **不拖文件！** 只填写表单：
  - Endpoint（如 `https://obs.cn-north-4.myhuaweicloud.com`）
  - Access Key / Secret Key
  - Bucket 名称
  - **目录路径**（如 `/models/llama-7b/`）

**前端处理**

```typescript
// model-registry/register/page.tsx
const handleSubmit = async (values) => {
  if (values.upload_method === UploadMethod.OBJECT_STORAGE) {
    const params = {
      upload_method: UploadMethod.OBJECT_STORAGE,
      obs_path: values.obs_path,              // 用户填的路径
      obs_endpoint: values.obs_endpoint,      // OBS 地址
      obs_ak: values.obs_ak,                // Access Key
      obs_sk: values.obs_sk,                // Secret Key
      obs_bucket: values.obs_bucket,        // Bucket
      // ... 其他模型信息
    };
    
    // 直接提交，不走文件上传 API
    await modelRegistryService.createModel(params);
  }
};
```

**关键特征**
- **不上传文件**：浏览器不传输任何文件字节
- **服务端拉取**：后端用提供的 AK/SK 去对象存储拉取文件
- **路径校验**：前端会先校验路径存在且为目录
- **节省带宽**：大文件不用经过浏览器中转

**与方式三的区别**

| 特性 | 方式三 (文件夹上传) | 方式四 (OBS 路径) |
|------|------------------|-----------------|
| 文件来源 | 用户本地文件夹 | 对象存储 (云端) |
| 浏览器上传 | 是 (分片上传) | 否 |
| 传输方向 | 浏览器 → 后端 → 存储 | 后端 ← OBS (拉取) |
| 所需信息 | 文件本身 | 路径 + 鉴权信息 |
| 适用场景 | 本地开发/小模型 | 生产环境/大模型 |

---

### 2.5 方式五：镜像构建 - raw-file（单个 zip）

**典型场景**
- 镜像管理 → 创建镜像 → 上传包含 Dockerfile 的构建包

**用户操作**
- 选择**单个 zip 文件**
- 通过 `accept=".zip"` 限制只能选 zip

**前端处理**

```typescript
// DynamicForm/FieldRenderer/index.tsx:329-400
case 'raw-file': {
  const uploadProps = {
    beforeUpload: (file: File) => {
      // 1. 检查文件类型
      if (effectiveField.accept) {
        const acceptList = effectiveField.accept.split(',').map(...);
        const isMatch = acceptList.some(accept => {
          if (accept.startsWith('.')) {
            return fileName.endsWith(accept);  // 扩展名匹配
          }
          // MIME 类型匹配...
        });
        if (!isMatch) {
          message.error(`只能上传 ${effectiveField.accept} 文件`);
          return Upload.LIST_IGNORE;
        }
      }
      
      // 2. 保存 File 对象到表单，但不上传
      onChange(field.name, file);
      return false;  // ← 阻止 Antd 自动上传
    },
    onRemove: () => onChange(field.name, null),
    fileList: [...],
    maxCount: 1,
    accept: effectiveField.accept || '*',
  };
  
  return (
    <Upload {...uploadProps}>
      <Button icon={<UploadOutlined />}>选择文件</Button>
    </Upload>
  );
}

// 提交时才上传
// imageManage/create/page.tsx
const handleSubmit = async (formData) => {
  const params = {
    file: formData.file,      // File 对象
    name: formData.name,
    version: formData.version,
    cpu_arch: formData.cpu_arch,
    ...
  };
  await imageService.buildImage(params);
};
```

**Service 层**

```typescript
// src/frontend/services/model/image-service.ts
public async buildImage(params: IBuildImageParams): Promise<IImageDetail> {
  const formData = new FormData();
  formData.append('file', params.file);        // zip 文件
  formData.append('name', params.name);      // 镜像名
  formData.append('version', params.version); // 版本
  formData.append('cpu_arch', params.cpu_arch);
  formData.append('gpu_type', params.gpu_type);
  formData.append('framework', params.framework);
  if (params.description) {
    formData.append('description', params.description);
  }
  
  // 使用 upload 方法 (multipart/form-data)
  return apiService.upload(`${this.serviceURL}/build`, formData);
}
```

**关键特征**
- **伪上传**：选择时不传，提交表单时才传
- **整文件一次性**：没有分片，zip 作为一个整体上传
- **附带表单数据**：file 字段 + name/version/cpu_arch 等一起提交
- **专用接口**：走 `images/build` 不是通用 `files/upload`

---

### 2.6 方式六：智能体导入（单文件，JSON/YAML）

**典型场景**
- 智能体管理 → 导入智能体（支持 uAI NEXUS JSON 或 uMetaABP YAML）

**用户操作**
- 选择**单个文件**：`.json` 或 `.yml/.yaml`
- 最大 20MB

**前端处理**

```typescript
// UploadAgentModal/index.tsx
const beforeUpload: UploadProps['beforeUpload'] = file => {
  // 1. 检查文件扩展名
  if (!isAllowedFile(file, sourcePlatform)) {
    const exts = ACCEPTED_EXTENSIONS[sourcePlatform].join(' / ');
    messageApi.error(`仅支持上传 ${exts} 文件`);
    return Upload.LIST_IGNORE;
  }
  
  // 2. 检查大小
  const sizeMb = file.size / 1024 / 1024;
  if (sizeMb > MAX_SIZE_MB) {
    messageApi.error(`文件大小不能超过 ${MAX_SIZE_MB}MB`);
    return Upload.LIST_IGNORE;
  }
  
  return false;  // 阻止自动上传，手动触发
};

// 点击"创建"按钮时上传
const handleCreate = async () => {
  const formFileData = new FormData();
  formFileData.append('file', selectedFile);
  
  const ok = await uploadAgent(formFileData, fileName, sourcePlatform);
  // ...
};
```

**Service 层**

```typescript
// app-service.ts
public async importAgent(params: any, fileName?: string, sourcePlatform?: string) {
  const query = new URLSearchParams();
  if (fileName) query.set('new_name', fileName);
  if (sourcePlatform) query.set('source_platform', sourcePlatform);
  const qs = query.toString();
  const url = qs ? `/apps/import?${qs}` : '/apps/import';
  
  return apiService.upload(url, params, { isReturnCode: true });
}
```

**关键特征**
- **单文件限制**：严格限制 JSON/YAML
- **带查询参数**：URL 带 `new_name` 和 `source_platform`
- **业务专用**：走 `apps/import` 不是通用文件接口

---

### 2.7 方式七：CSV 批量运行（本地解析，不上传文件）

**典型场景**
- 批量运行 → 上传 CSV → 自动解析填表

**用户操作**
- 拖拽或选择**单个 CSV 文件**（也支持 TSV）

**前端处理**

```typescript
// CsvUploadZone/index.tsx
const decodeFile = (bytes: Uint8Array): string => {
  // 检测 UTF-16 LE (BOM: 0xFF 0xFE)
  const isUtf16Le = bytes[0] === 0xff && bytes[1] === 0xfe;
  if (isUtf16Le) {
    const decoder = new TextDecoder('utf-16le');
    return decoder.decode(bytes.slice(2));
  }
  
  // 默认 UTF-8
  const decoder = new TextDecoder('utf-8');
  const text = decoder.decode(bytes);
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;  // 去掉 BOM
};

const handleCsvParse = async (results, file) => {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const text = decodeFile(bytes);  // ← 浏览器内解码
  
  // 自动检测分隔符（逗号或制表符）
  const delimiter = detectDelimiter(text);
  
  // 用 PapaParse 在浏览器里解析
  const reparsed = Papa.parse<string[]>(text, {
    delimiter,
    header: false,
    skipEmptyLines: false,
  });
  
  // 传解析后的数据，不是文件本身
  onUploadAccepted(reparsed, file);
};
```

**关键特征**
- **不上传文件！** 文件在浏览器里解析完成
- **纯前端处理**：解码 → 检测分隔符 → 解析 → 得到 JSON 数组
- **业务数据传递**：最终提交的是解析后的表格数据，不是文件

**与真正上传的区别**

```
真正上传:  文件 → FormData → HTTP → 后端存储 → 返回文件路径
CSV解析:   文件 → 浏览器读取 → 前端解析 → 得到数据 → 业务API提交数据
```

---

## 3. 后端存储层

### 3.1 文件元数据表（PostgreSQL）

```sql
-- 文件记录表
files (
    id: UUID PK,
    name: varchar,           -- 文件名（不含扩展名）
    extension: varchar,        -- 扩展名
    size: bigint,            -- 文件大小（字节）
    mime_type: varchar,      -- MIME 类型
    storage_key: varchar,     -- 存储路径（相对路径）
    scope: varchar,          -- workspace / tenant
    platform: varchar,       -- agent / model / etc
    target_id: UUID,         -- 关联对象ID
    creator_id: UUID,
    created_at: timestamp,
    ...
)
```

### 3.2 存储路径结构

```
{upload_storage_dir}/              # 配置的根目录
├── .chunks/                      # 分片上传临时区
│   └── {upload_id}/
│       ├── _meta.json           # 上传会话元数据
│       ├── part_00001          # 分片文件
│       ├── part_00002
│       └── ...
├── {target_id}/                 # 最终文件区（按 target_id 组织）
│   └── {uuid}.{ext}             # 实际存储的文件
└── third_party/                 # 第三方同步专用
    └── {dir_id}/
```

### 3.3 对象存储适配

后端 `StorageService` 支持多种存储后端：
- **本地存储**：直接写文件系统
- **OBS** (Huawei Cloud Object Storage)
- **S3** (兼容接口)

---

## 4. 快速定位代码的方法

### 4.1 看到上传组件，怎么知道走哪条路？

| 组件/场景 | 对应方式 | 关键代码位置 |
|----------|---------|------------|
| `FileUpload` (通用) | 方式一 | `app/components/FileUpload/index.tsx` |
| `DatasetFileList` 上传 | 方式二 | `stores/data/dataset-management-store.ts:261` |
| 模型注册页 | 方式三/四 | `stores/model/model-registry-store.ts:640` |
| 镜像创建 `raw-file` | 方式五 | `DynamicForm/FieldRenderer:329` |
| `CsvUploadZone` | 方式七 | `CsvUploadZone/index.tsx` |
| `UploadAgentModal` | 方式六 | `UploadAgentModal/index.tsx` |

### 4.2 搜索关键词

```bash
# 找批量上传
rg "files/batch-upload" --type ts

# 找分片上传
rg "chunked/initiate" --type ts

# 找 XHR 直连
rg "new XMLHttpRequest" --type ts

# 找 raw-file
rg "'raw-file'" --type ts

# 后端文件路由
rg "@router.post.*upload" --type py
```

---

## 5. 常见问题 FAQ

### Q1: 为什么同一个平台有这么多种上传方式？

**A**: 历史演进 + 业务需求差异：
- 通用批量：最早实现，适合小文件快速上传
- 数据集 XHR：需要进度条，所以单独用 XHR
- 分片上传：模型文件太大，必须分片
- OBS 路径：生产环境大模型直接走对象存储
- CSV 解析：业务只需要数据，不需要存文件

### Q2: 能不能统一成一种方式？

**A**: 技术上可以，但产品上有取舍：
- 分片上传成本更高（需要维护临时文件、合并逻辑）
- 小文件整传更简单、更快
- 不同业务对进度可见性、断点续传需求不同

如果要统一，建议：
- 小文件 (< 10MB)：走整文件上传
- 大文件 (> 10MB)：自动切换分片
- 前端封装统一 `UploadFacade`，业务无感知

### Q3: 我想做 DICOM 上传，应该参考哪种方式？

**A**: 看 DICOM 设计稿的需求：
- 拖入文件夹 → **参考方式三**（模型注册分片上传）
- 输入网络路径 → **参考方式四**（OBS 路径）
- 解析进度反馈 → **需要新增 WebSocket/SSE 机制**

### Q4: zip 文件会上传后自动解压吗？

**A**: 不会。当前实现：
- 方式五（镜像构建）：zip 作为整体上传，后端解压处理
- 方式一（通用）：zip 如果允许上传，也是作为普通文件存储，不解压
- 没有通用的「上传 zip → 自动解压 → 存多个文件」功能

---

## 6. 附录：接口汇总表

| 接口 | 路径 | 方式 | Content-Type | 主要参数 |
|-----|------|-----|---------------|---------|
| 单文件上传 | POST `/files/upload` | 方式一 | multipart | `file`, `platform` |
| 批量上传 | POST `/files/batch-upload` | 方式一 | multipart | `files[]`, `platform`, `format` |
| 数据集上传 | POST `/data-hub/raw-datasets/{id}/files` | 方式二 | multipart | `file`, `prefix` (query) |
| 分片-发起 | POST `/files/chunked/initiate` | 方式三 | JSON | `filename`, `size`, `total_parts` |
| 分片-上传 | POST `/files/chunked/part` | 方式三 | multipart | `upload_id`, `part_number`, `file` |
| 分片-完成 | POST `/files/chunked/complete` | 方式三 | JSON | `upload_id`, `filename`, `size` |
| 分片-状态 | GET `/files/chunked/status/{upload_id}` | 方式三 | - | - |
| 分片-取消 | POST `/files/chunked/abort` | 方式三 | query | `upload_id` |
| 镜像构建 | POST `/images/build` | 方式五 | multipart | `file`, `name`, `version`, ... |
| 智能体导入 | POST `/apps/import` | 方式六 | multipart | `file`, `new_name`, `source_platform` |

---

## 7. 相关文档

- [文件管理架构设计](../architecture/data-management/flow_file_upload_download.md)
- [DICOM 上传设计稿](./DICOM_Upload_Parse_Design_Report.md) (如果存在)
- 后端代码：`src/backend/src/routes/v1/file.py`
- 分片服务：`src/backend/src/shared/infrastructure/storage/chunked_upload.py`
