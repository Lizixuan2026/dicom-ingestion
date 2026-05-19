"""
Schema Manager

管理Tag Schema的版本控制和迁移。
决策 Gap-4: 按需重解析（Lazy）+ 投影标记陈旧
"""
import json
from datetime import datetime
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class SchemaManager:
    """
    Schema版本管理
    决策 Gap-4: 按需重解析（Lazy）+ 投影标记陈旧
    """

    def __init__(self, db_session):
        self.db = db_session

    def check_schema_compatibility(
        self,
        current_schema: str,
        stored_schema: str
    ) -> bool:
        """
        检查存储的Schema是否与当前兼容

        返回True表示兼容，无需重解析
        返回False表示不兼容，需要重解析
        """
        current = self._parse_version(current_schema)
        stored = self._parse_version(stored_schema)

        # 主版本变更需要重解析
        if current[0] != stored[0]:
            return False

        # 次版本变更 - 检查是否有新增必填字段
        if current[1] > stored[1]:
            return self._check_additions_required(current_schema, stored_schema)

        return True

    def mark_stale_projections(self, schema_version: str) -> int:
        """
        标记使用旧Schema的投影为陈旧
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

    def _parse_version(self, version: str) -> tuple:
        """解析版本号 x.y.z"""
        parts = version.split('.')
        return tuple(int(p) for p in parts[:3])

    def _check_additions_required(self, current: str, stored: str) -> bool:
        """检查是否有新增必填字段"""
        # 简化实现：次版本变更如果有新的required字段，返回False
        # 实际实现应比较两个版本的schema配置
        return True  # 默认兼容

    def _get_current_schema_version(self) -> str:
        """获取当前schema版本"""
        # 从配置或代码获取
        return "1.0"

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
