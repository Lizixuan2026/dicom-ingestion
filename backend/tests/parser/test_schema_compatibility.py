"""
Test Schema Compatibility

P1-2: Schema 兼容性单测
- 主版本变化
- 次版本新增 required
- 次版本仅新增 optional
- Patch 版本变化
"""
import pytest
from datetime import datetime
from unittest.mock import Mock

from dicom_ingestion.parser.schema_manager import (
    SchemaCompatibilityChecker,
    SchemaDefinition,
    SchemaRegistry,
    SchemaManager,
    CompatibilityLevel,
)


class TestSchemaCompatibilityChecker:
    """P1-2: SchemaCompatibilityChecker 测试"""

    def test_major_version_change_is_incompatible(self):
        """测试：主版本变更 = 不兼容"""
        checker = SchemaCompatibilityChecker()

        old_schema = SchemaDefinition(
            version="1.5.5",
            name="default",
            description="旧版本",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        new_schema = SchemaDefinition(
            version="2.0.0",
            name="default",
            description="新版本",
            required_fields={"a", "b", "x"},
            optional_fields={"c"}
        )

        level, reasons = checker.check(old_schema, new_schema)

        assert level == CompatibilityLevel.INCOMPATIBLE
        assert "Major version" in reasons[0]

    def test_minor_version_new_required_requires_reparse(self):
        """测试：次版本新增 required 字段 = 需要重解析"""
        checker = SchemaCompatibilityChecker()

        old_schema = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="初始版本",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        new_schema = SchemaDefinition(
            version="1.1.0",
            name="default",
            description="新增 required 字段",
            required_fields={"a", "b", "d"},  # 新增 d (required)
            optional_fields={"c"}
        )

        level, reasons = checker.check(old_schema, new_schema)

        assert level == CompatibilityLevel.REQUIRES_REPARSE
        assert "d" in reasons[0]
        assert "required" in reasons[0].lower()

    def test_minor_version_only_optional_additions_is_compatible(self):
        """测试：次版本仅新增 optional 字段 = 完全兼容"""
        checker = SchemaCompatibilityChecker()

        old_schema = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="初始版本",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        new_schema = SchemaDefinition(
            version="1.1.0",
            name="default",
            description="新增可选字段",
            required_fields={"a", "b"},
            optional_fields={"c", "d"}  # 新增 d (optional)
        )

        level, reasons = checker.check(old_schema, new_schema)

        assert level == CompatibilityLevel.FULLY_COMPATIBLE
        assert "optional" in reasons[0].lower()

    def test_optional_to_required_upgrade_requires_reparse(self):
        """测试：optional 升级为 required = 需要重解析"""
        checker = SchemaCompatibilityChecker()

        old_schema = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="初始版本",
            required_fields={"a", "b"},
            optional_fields={"c"}  # c 是 optional
        )

        new_schema = SchemaDefinition(
            version="1.1.0",
            name="default",
            description="c 升级为 required",
            required_fields={"a", "b", "c"},  # c 升级为 required
            optional_fields=set()
        )

        level, reasons = checker.check(old_schema, new_schema)

        assert level == CompatibilityLevel.REQUIRES_REPARSE
        assert "c" in reasons[0]

    def test_patch_version_change_is_compatible(self):
        """测试：Patch 版本变更 = 完全兼容"""
        checker = SchemaCompatibilityChecker()

        old_schema = SchemaDefinition(
            version="1.0.5",
            name="default",
            description="旧版本",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        new_schema = SchemaDefinition(
            version="1.0.10",
            name="default",
            description="新版本",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        level, reasons = checker.check(old_schema, new_schema)

        assert level == CompatibilityLevel.FULLY_COMPATIBLE
        assert "Patch" in reasons[0]

    def test_same_version_is_compatible(self):
        """测试：相同版本 = 完全兼容"""
        checker = SchemaCompatibilityChecker()

        old_schema = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        new_schema = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="",
            required_fields={"a", "b"},
            optional_fields={"c"}
        )

        level, reasons = checker.check(old_schema, new_schema)

        assert level == CompatibilityLevel.FULLY_COMPATIBLE


class TestSchemaRegistry:
    """P1-2: SchemaRegistry 测试"""

    def test_register_and_get_schema(self):
        """测试：注册和获取 schema"""
        registry = SchemaRegistry()

        schema = SchemaDefinition(
            version="1.0.0",
            name="default",
            description="测试",
            required_fields={"a"},
            optional_fields={"b"}
        )

        registry.register(schema)
        retrieved = registry.get("1.0.0")

        assert retrieved == schema
        assert retrieved.version == "1.0.0"

    def test_set_and_get_current_version(self):
        """测试：设置和获取当前版本"""
        registry = SchemaRegistry()

        schema = SchemaDefinition(
            version="2.0.0",
            name="default",
            description="",
            required_fields=set(),
            optional_fields=set()
        )

        registry.register(schema)
        registry.set_current("2.0.0")

        assert registry.get_current_version() == "2.0.0"
        assert registry.get_current() == schema

    def test_list_versions(self):
        """测试：列出所有版本"""
        registry = SchemaRegistry()

        for v in ["1.0.0", "1.1.0", "2.0.0"]:
            registry.register(SchemaDefinition(
                version=v,
                name="default",
                description="",
                required_fields=set(),
                optional_fields=set()
            ))

        versions = registry.list_versions()
        assert len(versions) == 3
        assert "1.0.0" in versions


class TestSchemaManagerCompatibility:
    """P1-2: SchemaManager 兼容性集成测试"""

    def test_check_compatibility_returns_tuple(self):
        """测试：check_schema_compatibility 返回 (bool, str)"""
        # 初始化默认 schemas
        SchemaManager.initialize_with_default_schemas()

        mock_db = Mock()
        manager = SchemaManager(mock_db)

        # 1.0.0 -> 1.1.0 (新增 optional) = 兼容
        is_compatible, reason = manager.check_schema_compatibility("1.1.0", "1.0.0")
        assert is_compatible is True
        assert "compatible" in reason.lower() or "optional" in reason.lower()

    def test_check_compatibility_new_required_triggers_reparse(self):
        """测试：1.0.0 -> 1.2.0 (新增 required) = 需要重解析"""
        SchemaManager.initialize_with_default_schemas()

        mock_db = Mock()
        manager = SchemaManager(mock_db)

        # 1.0.0 -> 1.2.0 (新增 device_serial required)
        is_compatible, reason = manager.check_schema_compatibility("1.2.0", "1.0.0")

        assert is_compatible is False
        assert "required" in reason.lower() or "device_serial" in reason

    def test_check_compatibility_major_change_incompatible(self):
        """测试：1.0.0 -> 2.0.0 = 不兼容"""
        SchemaManager.initialize_with_default_schemas()

        mock_db = Mock()
        manager = SchemaManager(mock_db)

        is_compatible, reason = manager.check_schema_compatibility("2.0.0", "1.0.0")

        assert is_compatible is False
        assert "Major" in reason or "incompatible" in reason.lower()

    def test_unknown_schema_returns_incompatible(self):
        """测试：未知 schema 版本返回不兼容（保守策略）"""
        SchemaManager.initialize_with_default_schemas()

        mock_db = Mock()
        manager = SchemaManager(mock_db)

        # 检查未注册的版本
        is_compatible, reason = manager.check_schema_compatibility("9.9.9", "1.0.0")

        assert is_compatible is False
        assert "not found" in reason.lower()


class TestSchemaMigrationStats:
    """P1-2: Schema 迁移统计测试"""

    def test_get_migration_stats(self):
        """测试：获取迁移统计信息"""
        SchemaManager.initialize_with_default_schemas()

        # 模拟数据库返回
        mock_db = Mock()
        mock_row = Mock()
        mock_row.__getitem__ = Mock(side_effect=lambda i: 100 if i == 0 else 10)
        mock_db.execute.return_value.fetchone.return_value = mock_row

        manager = SchemaManager(mock_db)
        stats = manager.get_schema_migration_stats()

        assert "total_series" in stats
        assert "current_schema" in stats
        assert stats["current_schema"] == "1.0.0"


class TestCheckAndMarkStale:
    """P1-2: check_and_mark_stale_for_all 测试"""

    def test_mark_stale_by_version(self):
        """测试：标记特定版本为陈旧"""
        SchemaManager.initialize_with_default_schemas()

        # 模拟数据库
        mock_db = Mock()
        mock_result = Mock()
        mock_result.rowcount = 5
        mock_db.execute.return_value = mock_result

        manager = SchemaManager(mock_db)
        marked = manager._mark_stale_by_version("1.0.0", "新增 required 字段")

        assert marked == 5

        # 验证 SQL 参数
        call = mock_db.execute.call_args
        assert call[0][1]["stored_version"] == "1.0.0"
        assert "required" in call[0][1]["reason"]


class TestDefaultSchemaInitialization:
    """P1-2: 默认 Schema 初始化测试"""

    def test_initialize_creates_expected_schemas(self):
        """测试：初始化创建预期的 schema 版本"""
        registry = SchemaManager.initialize_with_default_schemas()

        versions = registry.list_versions()

        assert "1.0.0" in versions
        assert "1.1.0" in versions
        assert "1.2.0" in versions
        assert "2.0.0" in versions

    def test_v12_has_device_serial_required(self):
        """测试：1.2.0 有 device_serial 作为 required 字段"""
        registry = SchemaManager.initialize_with_default_schemas()

        schema = registry.get("1.2.0")

        assert "device_serial" in schema.required_fields
        assert "device_serial" not in schema.optional_fields

    def test_v11_has_manufacturer_optional(self):
        """测试：1.1.0 有 manufacturer 作为 optional 字段"""
        registry = SchemaManager.initialize_with_default_schemas()

        schema = registry.get("1.1.0")

        assert "manufacturer" in schema.optional_fields
        assert "manufacturer" not in schema.required_fields


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
