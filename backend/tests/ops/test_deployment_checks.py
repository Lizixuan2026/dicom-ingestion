import pytest
from dicom_ingestion.ops.deployment_checks import DeploymentValidator, MigrationCheck, ConfigurationCheck, CheckResult


class TestMigrationCheck:
    def test_migration_check_passes(self):
        def mock_current_revision():
            return "abc123"
        
        def mock_expected_revision():
            return "abc123"
        
        check = MigrationCheck(mock_current_revision, mock_expected_revision)
        result = check.validate()
        
        assert result.valid
        assert "migrations up to date" in result.message.lower()

    def test_migration_check_fails(self):
        def mock_current_revision():
            return "old123"
        
        def mock_expected_revision():
            return "new456"
        
        check = MigrationCheck(mock_current_revision, mock_expected_revision)
        result = check.validate()
        
        assert not result.valid
        assert "migration mismatch" in result.message.lower()


class TestConfigurationCheck:
    def test_config_check_passes(self):
        def mock_get_config(key):
            return "some_value"
        
        check = ConfigurationCheck(mock_get_config)
        result = check.validate()
        
        assert result.valid

    def test_config_check_fails(self):
        def mock_get_config(key):
            return None
        
        check = ConfigurationCheck(mock_get_config)
        result = check.validate()
        
        assert not result.valid
