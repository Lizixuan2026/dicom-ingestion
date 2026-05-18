"""
Pytest configuration for DICOM ingestion backend tests.

This file ensures the src directory is in the Python path for imports.
"""
import sys
import os

# Add src directory to Python path
src_path = os.path.join(os.path.dirname(__file__), '..', 'src')
src_path = os.path.abspath(src_path)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Database configuration from environment or defaults
DB_HOST = os.environ.get("DICOM_TEST_DB_HOST", "localhost")
DB_PORT = os.environ.get("DICOM_TEST_DB_PORT", "5432")
DB_USER = os.environ.get("DICOM_TEST_DB_USER", "postgres")
DB_PASS = os.environ.get("DICOM_TEST_DB_PASS", "postgres")
DB_NAME = os.environ.get("DICOM_TEST_DB_NAME", "dicom_test")

# Construct DATABASE_URL
DATABASE_URL = os.environ.get(
    "DICOM_TEST_DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
