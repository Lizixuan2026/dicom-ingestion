我又看了一遍。先给结论：

**这轮比上一版明显更接近 green 了，但 Batch 1 还不能算完全放行。**  
上次我提的 4 个 blocker 里，**2 个已经基本修好，2 个还没有真正闭环**。

另外先澄清一个状态：  
你这次让我看的“当前更新”目前还是 **本地未提交改动**；`origin/main` 仍停在 `453c515`，还没包含这轮修订。

## 已经修好的部分

### 1. RawObjectStore 的主路径逃逸问题，代码层面已修
这次从 `startswith()` 改成了 `os.path.commonpath()`，并且把 `get / exists / delete` 都收口到 `_resolve_safe_path()`，这比上一版稳很多。

### 2. `pydicom` 依赖补上了
这个 blocker 已消失。

### 3. canonical FK 的两个关键测试补上了
你补了：
- 合法 circular insert
- cross-instance canonical observation rejection

这两个补得对，说明你是在补“真正的 schema invariant”，不是只补表面测试。

---

# 这轮我仍然会卡住放行的点

## P1. Fixture corpus 还没有真正对齐 Batch 1 规格

这是现在最大的剩余问题。

### 具体有三层：

#### a) `generate_fixtures.py` 现在**不再生成**一批原先 Batch 1 明确要求的 fixture
目前脚本只生成了新那批：
- identity duplicate
- content duplicate
- private tags
- SEG reference
- mixed zip

但它已经不再生成：
- `valid_ct_multi_frame.dcm`
- `valid_rtstruct.dcm`
- `valid_sr.dcm`
- `valid_zip_42_files.zip`
- `zip_bomb.zip`
- `zip_path_traversal.zip`
- `zip_nested_3_deep.zip`

这些文件现在之所以还在目录里，只是因为它们是之前 commit 留下来的。  
**如果从干净环境重新跑生成脚本，golden set 会缩水。**

这意味着当前 fixture 集合其实有“两套真相”：
- 磁盘上现有文件
- 脚本可再生文件

Batch 1 需要的是后者也完整，否则测试资产不可重建。

#### b) `missing_required_tag.dcm` 和 backlog 不一致
你现在改成了缺 `SOPClassUID`，但 `012_migration_first_backlog.md` 明确写的是：

- `missing_required_tag.dcm` — **no `SOPInstanceUID`**

这不是小文案问题，而是会影响后面 parser 错误码与 acceptance case 的定义。  
要么改 fixture 回去，要么正式改 backlog/spec；现在两边不一致。

#### c) `content_dup_a/b` 还没有满足当前 backlog 的判定标准
你 README 写的是“相同 pixel data”，这在医学语义上可以理解。  
但当前 backlog 里写得更具体：

- content duplicate: **same `whole_file_sha256` for different SOP UID**

而我直接算了这两个文件的 SHA256，它们是不同的。  
所以当前 fixture **不能证明你文档里写的那条 acceptance criterion**。

这里本质上有个更深的规格冲突：

- 如果 content duplicate 定义为“相同像素内容”，那它不应该靠 `whole_file_sha256`
- 如果定义为“相同 whole-file bytes”，那不同 SOP UID 又天然会让 whole-file hash 不同

所以你这里需要做一次明确选择，而不是继续让 fixture 去迎合两个互相拉扯的定义。  
**我建议你把 content duplicate 收敛为 pixel/content digest，不要再用 whole-file SHA 作为主定义。**

---

## P1. `accepted DICOM item` 必须绑定 `series_ingestion_attempt_id` 这条 invariant 还没闭环

`012` 里你们已经定了：

- DB 允许 `series_ingestion_attempt_id = NULL`
- 但一旦 `terminal_outcome = accepted`，应用层必须保证它已被设置

这轮我重新搜了 `backend/src` 和 `backend/tests`，目前还没看到：
- repository-layer assertion
- service-layer guard
- 对应 invariant test

换句话说，现在 schema 已经给了这条链路，但**还没有任何地方真正阻止“accepted 但没有 series attempt”的 item 出现**。

这条我仍然会算 blocker，因为它不是测试洁癖，而是会直接破坏后续 Series-level conflict summarization 的前提。

---

# 还剩两个非阻塞但建议顺手收掉的点

## P2. RawObjectStore 的回归测试还没补到位
实现已经修了，但测试还只覆盖：
- `/etc/passwd`
- put traversal

还缺这几个更贴近这次 bug 的 case：
- sibling-prefix bypass：`/tmp/base_evil/file`
- `exists()` 越界拒绝
- `delete()` 越界拒绝

也就是说，**bug 修了，但没有测试把这次修复钉住**。

## P2. `pydicom` 还没 pin version
现在是裸 `pydicom`。  
不一定阻塞 Batch 1，但你们已经在做“可重复 golden fixtures”，那依赖版本最好也可重复。

---

# 我对当前状态的判断

| 项目 | 当前判断 |
|---|---|
| Raw storage | **基本 green** |
| schema invariants | **接近 green，但 accepted-item invariant 仍缺** |
| fixture corpus | **还没 green** |
| Batch 1 整体 | **暂不建议放行 Batch 2** |

## 最短收口路径

如果你想把 Batch 1 真正关掉，我建议按这个顺序补：

1. **先统一 content duplicate 的正式定义**  
   我建议改成 pixel/content digest，不要继续写 `whole_file_sha256`。

2. **把 fixture generator 补回完整 golden set**
   - 保留这次新增的 5 类
   - 恢复之前那批安全性和模态覆盖 fixture
   - 让 README 只描述脚本能稳定重建的集合

3. **补 accepted-item assertion + test**
   - 这是目前剩下的唯一真正业务 invariant blocker

4. **补 raw store 的 3 个回归测试**
   - 这个很快，但能把这次修复真正封住

如果你愿意，我下一步可以直接给你做一份 **“这轮剩余修改清单 + 建议 patch 顺序”**，按文件级别列到可以直接继续改。