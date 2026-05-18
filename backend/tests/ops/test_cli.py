"""CLI layer tests for ops modules."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# Base directory for the backend
BACKEND_DIR = Path(__file__).parent.parent.parent
SRC_DIR = BACKEND_DIR / "src"

# Environment with PYTHONPATH set
CLI_ENV = {
    **os.environ,
    "PYTHONPATH": str(SRC_DIR),
}


class TestSmokeTestsCLI:
    """Test smoke_tests CLI entry point."""
    
    def test_cli_help(self):
        """Test CLI help output."""
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.smoke_tests", "--help"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=CLI_ENV,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "smoke tests" in result.stdout.lower()
    
    def test_cli_passes(self):
        """Test CLI with passing tests."""
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.smoke_tests"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=CLI_ENV,
        )
        # Should pass with basic health check
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "PASSED" in result.stdout
    
    def test_cli_json_output(self):
        """Test CLI JSON output format."""
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.smoke_tests", "--json"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=CLI_ENV,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Verify valid JSON
        output = json.loads(result.stdout)
        assert "success" in output
        assert "tests" in output
        assert "timestamp" in output


class TestDeploymentChecksCLI:
    """Test deployment_checks CLI entry point."""
    
    def test_cli_help(self):
        """Test CLI help output."""
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.deployment_checks", "--help"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=CLI_ENV,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "deployment" in result.stdout.lower()
    
    def test_cli_basic_check_passes(self):
        """Test CLI basic check passes."""
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.deployment_checks"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=CLI_ENV,
        )
        # Basic deployment check should pass
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "PASSED" in result.stdout
    
    def test_cli_config_check_fails_without_env(self):
        """Test CLI config check fails when env vars not set."""
        # Clear relevant env vars
        env = {
            **CLI_ENV,
            "DATABASE_URL": "",
            "OBJECT_STORAGE_URL": "",
            "LOG_LEVEL": "",
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.deployment_checks", "--check-config"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=env,
        )
        # Should fail because env vars are not set
        assert result.returncode == 1, f"Expected failure, got: {result.returncode}"
        assert "FAILED" in result.stdout or "Missing" in result.stdout
    
    def test_cli_json_output(self):
        """Test CLI JSON output format."""
        result = subprocess.run(
            [sys.executable, "-m", "dicom_ingestion.ops.deployment_checks", "--json"],
            capture_output=True,
            text=True,
            cwd=str(BACKEND_DIR),
            env=CLI_ENV,
        )
        assert result.returncode in [0, 1], f"stderr: {result.stderr}"  # Pass or fail is fine
        # Verify valid JSON
        output = json.loads(result.stdout)
        assert "valid" in output or "error" in output
