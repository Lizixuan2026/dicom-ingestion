# Batch 7 / Batch 8 评审落地（Phase 1）v0.2

**评审日期**: 2026-05-19  
**复核对象**: `dc7ab3f` (`fix(tests): 修复测试并验证 P0/P1 修复`)  
**文档目的**: 仅记录 v0.2 复核结论（不重复 v0.1 历史正文）

---

## 一、v0.2 复核结论

- **当前状态建议**: `DONE_WITH_CONCERNS`（暂不建议 GREEN）
- **是否可进入 GREEN**: **否**

### 结论依据
1. 本轮提交包含大量 `backend/.site-packages/` 第三方依赖文件，存在仓库污染与可维护性风险。
2. 本地复核测试未达全绿：
   - `backend/tests/parser/test_schema_compatibility.py`
   - `backend/tests/parser/test_configurable_parser.py`
   - `backend/tests/storage/test_local_nas_path_control.py`
   - 复核结果：`7 failed, 40 passed`
3. 失败集中在 `test_configurable_parser.py` 的 `pydicom` 依赖导入（`ModuleNotFoundError`），说明“测试通过”结论与复核环境不一致。

---

## 二、风险分级

- **P1（发布阻断前置项）**
  - 不清理 `.site-packages` 即合入，会显著增大仓库体积并引入审查噪声。
  - 未统一测试依赖策略会导致 CI/本地复现不一致，影响发布可信度。

---

## 三、达到 GREEN 的最小闭环条件

1. 从版本控制中移除 `backend/.site-packages` 全量文件，并补充 `.gitignore` 防回归。
2. 统一 `pydicom` 依赖策略（二选一）：
   - 在测试环境显式安装并锁定版本；
   - 改造测试边界，避免直接依赖外部模块导入。
3. 在同一执行环境下重跑以下测试并保留可复核结果：
   - `backend/tests/parser/test_schema_compatibility.py`
   - `backend/tests/parser/test_configurable_parser.py`
   - `backend/tests/storage/test_local_nas_path_control.py`

---

## 四、状态建议

- `READY_FOR_PHASE2`：**暂缓**
- 建议维持 `DONE_WITH_CONCERNS`，待上述闭环完成后再升级为 `READY_FOR_PHASE2` / GREEN。
