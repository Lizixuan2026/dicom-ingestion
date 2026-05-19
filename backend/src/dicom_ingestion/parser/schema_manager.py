"""
Schema Manager

管理Tag Schema的版本控制和迁移。
决策 Gap-4: 按需重解析（Lazy）+ 投影标记陈旧
P1-2: 真实兼容性判断 + Schema Registry
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, List, Set, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CompatibilityLevel(Enum):
    """P1-2: 兼容性级别"""
    FULLY_COMPATIBLE = "compatible"      # 完全兼容，无需重解析
    REQUIRES_REPARSE = "requires_reparse"  # 需要重解析（新增 required 字段）
    INCOMPATIBLE = "incompatible"         # 不兼容（主版本变更）


@dataclass
class SchemaDefinition:
    """P1-2: Schema 定义数据类"""
    version: str
    name: str
    description: str
    extractors: Dict[str, List[Dict]] = field(default_factory=dict)
    required_fields: Set[str] = field(default_factory=set)
    optional_fields: Set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.now)

    def get_all_fields(self) -> Set[str]:
        """获取所有字段名"""
        return self.required_fields | self.optional_fields


class SchemaRegistry:
    """
    P1-2: Schema Registry
    统一存储和管理所有 schema 版本
    """

    def __init__(self):
        self._schemas: Dict[str, SchemaDefinition] = {}
        self._current_version: Optional[str] = None

    def register(self, schema: SchemaDefinition):
        """注册 schema 定义"""
        self._schemas[schema.version] = schema
        logger.info(f"Registered schema version {schema.version}: {schema.name}")

    def get(self, version: str) -> Optional[SchemaDefinition]:
        """获取指定版本的 schema"""
        return self._schemas.get(version)

    def set_current(self, version: str):
        """设置当前版本"""
        if version not in self._schemas:
            raise ValueError(f"Schema version {version} not registered")
        self._current_version = version
        logger.info(f"Set current schema version to {version}")

    def get_current(self) -> Optional[SchemaDefinition]:
        """获取当前 schema"""
        if self._current_version:
            return self._schemas.get(self._current_version)
        return None

    def get_current_version(self) -> str:
        """获取当前版本号"""
        return self._current_version or "1.0"

    def list_versions(self) -> List[str]:
        """列出所有注册版本"""
        return list(self._schemas.keys())


class SchemaCompatibilityChecker:
    """
    P1-2: Schema 兼容性检查器
    真实实现 schema 版本间的兼容性判断
    """

    def check(
        self,
        old_schema: SchemaDefinition,
        new_schema: SchemaDefinition
    ) -> tuple[CompatibilityLevel, List[str]]:
        """
        检查两个 schema 的兼容性

        Returns:
            (compatibility_level, reasons)
        """
        old_version = self._parse_version(old_schema.version)
        new_version = self._parse_version(new_schema.version)

        # 主版本变更 = 不兼容
        if new_version[0] != old_version[0]:
            return (
                CompatibilityLevel.INCOMPATIBLE,
                [f"Major version changed: {old_schema.version} -> {new_schema.version}"]
            )

        # 次版本变更 = 检查新增 required 字段
        if new_version[1] > old_version[1]:
            new_required = self._detect_new_required_fields(old_schema, new_schema)
            if new_required:
                return (
                    CompatibilityLevel.REQUIRES_REPARSE,
                    [f"New required fields added: {', '.join(new_required)}"]
                )
            else:
                return (
                    CompatibilityLevel.FULLY_COMPATIBLE,
                    ["Minor version with only optional additions"]
                )

        # 修订版本变更 = 完全兼容
        if new_version[2] > old_version[2]:
            return (
                CompatibilityLevel.FULLY_COMPATIBLE,
                ["Patch version change only"]
            )

        # 相同版本
        return (
            CompatibilityLevel.FULLY_COMPATIBLE,
            ["Same version"]
        )

    def _detect_new_required_fields(
        self,
        old_schema: SchemaDefinition,
        new_schema: SchemaDefinition
    ) -> Set[str]:
        """检测新增的 required 字段"""
        old_required = old_schema.required_fields
        new_required = new_schema.required_fields

        # 新增的 required = 新 required 减去旧所有字段
        new_fields = new_required - old_required

        # 从 optional 升级为 required 也算新增 required
        upgraded_fields = (new_required & old_schema.optional_fields) - old_required

        return new_fields | upgraded_fields

    def _parse_version(self, version: str) -> tuple:
        """解析版本号 x.y.z"""
        parts = version.split('.')
        while len(parts) < 3:
            parts.append('0')
        return tuple(int(p) for p in parts[:3])


class SchemaManager:
    """
    Schema版本管理
    决策 Gap-4: 按需重解析（Lazy）+ 投影标记陈旧
    P1-2: 真实兼容性判断 + Schema Registry 集成
    """

    # P1-2: 类级别的共享 Registry
    _registry: Optional[SchemaRegistry] = None
    _checker: SchemaCompatibilityChecker = None

    def __init__(self, db_session, registry: Optional[SchemaRegistry] = None):
        self.db = db_session
        # P1-2: 可使用传入的 registry 或共享 registry
        if registry:
            self._registry = registry
        elif self._registry is None:
            self._registry = SchemaRegistry()
            self._checker = SchemaCompatibilityChecker()

    @classmethod
    def get_shared_registry(cls) -> SchemaRegistry:
        """P1-2: 获取共享的 Schema Registry"""
        if cls._registry is None:
            cls._registry = SchemaRegistry()
        return cls._registry

    @classmethod
    def initialize_with_default_schemas(cls):
        """P1-2: 使用默认 schema 初始化 Registry"""
        registry = cls.get_shared_registry()

        # Schema 1.0.0
        schema_v1 = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="初始Schema",
            extractors={
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0010,0020)", "alias": "patient_id"},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ]
            },
            required_fields={"patient_name", "study_uid", "series_uid", "sop_instance_uid", "modality"},
            optional_fields={"patient_id"}
        )

        # Schema 1.1.0 - 新增可选字段
        schema_v1_1 = SchemaDefinition(
            version="1.1.0",
            name="default",
            description="新增可选字段",
            extractors={
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0010,0020)", "alias": "patient_id"},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                    {"tag": "(0008,0070)", "alias": "manufacturer"},  # 新增可选
                ]
            },
            required_fields={"patient_name", "study_uid", "series_uid", "sop_instance_uid", "modality"},
            optional_fields={"patient_id", "manufacturer"}  # manufacturer 新增
        )

        # Schema 1.2.0 - 新增 required 字段（需要重解析）
        schema_v1_2 = SchemaDefinition(
            version="1.2.0",
            name="default",
            description="新增 required 字段 device_serial",
            extractors={
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0010,0020)", "alias": "patient_id"},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                    {"tag": "(0008,0070)", "alias": "manufacturer"},
                    {"tag": "(0018,1000)", "alias": "device_serial", "required": True},  # 新增 required
                ]
            },
            required_fields={"patient_name", "study_uid", "series_uid", "sop_instance_uid", "modality", "device_serial"},
            optional_fields={"patient_id", "manufacturer"}
        )

        # Schema 2.0.0 - 主版本变更（不兼容）
        schema_v2 = SchemaDefinition(
            version="2.0.0",
            name="default",
            description="主版本重构",
            extractors={
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ]
            },
            required_fields={"patient_name", "study_uid", "series_uid", "sop_instance_uid", "modality"},
            optional_fields=set()
        )

        # 注册所有 schema
        for schema in [schema_v1, schema_v1_1, schema_v1_2, schema_v2]:
            registry.register(schema)

        # 设置当前版本
        registry.set_current("1.0.0")

        return registry

    def check_schema_compatibility(
        self,
        current_schema: str,
        stored_schema: str
    ) -> tuple[bool, str]:
        """
        P1-2: 真实的 Schema 兼容性检查

        Args:
            current_schema: 当前使用的 schema 版本（如 "1.2.0"）
            stored_schema: 已存储数据的 schema 版本（如 "1.0.0"）

        Returns:
            (is_compatible, reason)
            is_compatible: True 表示兼容，无需重解析
            reason: 兼容性判断的详细说明
        """
        # 获取两个 schema 的定义
        current_def = self._registry.get(current_schema)
        stored_def = self._registry.get(stored_schema)

        if not current_def or not stored_def:
            # 如果无法获取定义，保守地返回不兼容
            logger.warning(f"Cannot find schema definition: current={current_schema}, stored={stored_schema}")
            return (False, f"Schema definition not found for {current_schema} or {stored_schema}")

        # 使用兼容性检查器
        level, reasons = self._checker.check(stored_def, current_def)

        is_compatible = (level == CompatibilityLevel.FULLY_COMPATIBLE)
        reason = "; ".join(reasons)

        logger.info(
            f"Schema compatibility check: {stored_schema} -> {current_schema}: "
            f"{level.value} ({reason})"
        )

        return (is_compatible, reason)

    def check_and_mark_stale_for_all(self) -> Dict[str, int]:
        """
        P1-2: 检查所有存储的 schema 版本并标记陈旧的

        Returns:
            统计信息：{compatible, requires_reparse, incompatible}
        """
        stats = {"compatible": 0, "requires_reparse": 0, "incompatible": 0, "unknown": 0}

        # 获取所有不同的存储 schema 版本
        query = """
        SELECT DISTINCT extracted_schema_version
        FROM dicom_series
        WHERE projection_status = 'current'
        """
        rows = self.db.execute(query).fetchall()

        current_version = self._get_current_schema_version()

        for (stored_version,) in rows:
            is_compatible, reason = self.check_schema_compatibility(current_version, stored_version)

            if not is_compatible:
                # 标记该版本的所有投影为陈旧
                marked = self._mark_stale_by_version(stored_version, reason)
                if "required" in reason.lower():
                    stats["requires_reparse"] += marked
                elif "Major" in reason:
                    stats["incompatible"] += marked
                else:
                    stats["unknown"] += marked
            else:
                stats["compatible"] += 1

        return stats

    def _mark_stale_by_version(self, stored_version: str, reason: str) -> int:
        """标记特定 schema 版本的所有投影为陈旧"""
        query = """
        UPDATE dicom_series
        SET projection_status = 'stale',
            stale_reason = :reason,
            needs_reparse = TRUE,
            updated_at = NOW()
        WHERE extracted_schema_version = :stored_version
          AND projection_status = 'current'
        """
        result = self.db.execute(query, {
            "stored_version": stored_version,
            "reason": reason[:255]  # 限制长度
        })
        return result.rowcount

    def mark_stale_projections(self, schema_version: str) -> int:
        """
        P1-2: 标记使用旧Schema的投影为陈旧
        异步任务会按需重解析

        决策 Gap-4: 按需重解析（Lazy）+ 投影标记陈旧
        """
        query = """
        UPDATE dicom_series
        SET projection_status = 'stale',
            stale_reason = 'schema_updated',
            needs_reparse = TRUE,
            updated_at = NOW()
        WHERE extracted_schema_version != :schema_version
          AND projection_status = 'current'
        """

        result = self.db.execute(query, {"schema_version": schema_version})
        affected = result.rowcount

        logger.info(f"Marked {affected} projections as stale due to schema update")

        return affected

    def get_projection_reparse_queue(
        self,
        limit: int = 100,
        priority: str = "high"
    ) -> List[Dict]:
        """
        获取需要重解析的投影队列

        Args:
            limit: 返回数量限制
            priority: 优先级 (high, normal, low)
        """
        query = """
        SELECT
            s.id,
            s.series_uid,
            s.study_uid,
            s.modality,
            s.extracted_schema_version as old_schema,
            :current_schema as new_schema,
            s.updated_at as marked_stale_at
        FROM dicom_series s
        WHERE s.needs_reparse = TRUE
          AND s.projection_status = 'stale'
        ORDER BY
            CASE
                WHEN s.modality IN ('CT', 'MR') THEN 1
                ELSE 2
            END,
            s.updated_at ASC
        LIMIT :limit
        """

        rows = self.db.execute(query, {
            "current_schema": self._get_current_schema_version(),
            "limit": limit
        }).fetchall()

        return [dict(row) for row in rows]

    def mark_projection_reparsed(
        self,
        series_id: int,
        new_schema_version: str,
        success: bool = True
    ):
        """标记投影已重解析"""
        if success:
            query = """
            UPDATE dicom_series
            SET projection_status = 'current',
                stale_reason = NULL,
                needs_reparse = FALSE,
                extracted_schema_version = :schema_version,
                last_reparsed_at = NOW(),
                updated_at = NOW()
            WHERE id = :series_id
            """
        else:
            query = """
            UPDATE dicom_series
            SET projection_status = 'reparse_failed',
                stale_reason = 'reparse_error',
                reparse_error_count = COALESCE(reparse_error_count, 0) + 1,
                updated_at = NOW()
            WHERE id = :series_id
            """

        self.db.execute(query, {
            "series_id": series_id,
            "schema_version": new_schema_version
        })

    def _get_current_schema_version(self) -> str:
        """P1-2: 从 Registry 获取当前 schema 版本"""
        return self._registry.get_current_version()

    def get_schema_migration_stats(self) -> Dict:
        """获取Schema迁移统计"""
        query = """
        SELECT
            COUNT(*) as total_stale,
            SUM(CASE WHEN projection_status = 'stale' THEN 1 ELSE 0 END) as stale_count,
            SUM(CASE WHEN projection_status = 'reparse_failed' THEN 1 ELSE 0 END) as failed_count,
            SUM(CASE WHEN needs_reparse = TRUE THEN 1 ELSE 0 END) as pending_count
        FROM dicom_series
        """

        row = self.db.execute(query).fetchone()
        return {
            "total_series": row[0],
            "stale_count": row[1] or 0,
            "failed_count": row[2] or 0,
            "pending_reparse": row[3] or 0,
            "current_schema": self._get_current_schema_version()
        }
