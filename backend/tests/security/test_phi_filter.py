import pytest
from dicom_ingestion.security.phi_filter import PhiFilter


class TestPhiFilter:
    def test_filter_patient_name(self):
        data = {
            "patient_name": "John Doe",
            "study_description": "Chest X-Ray",
            "rows": 512
        }
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered["patient_name"] == "[REDACTED-PHI]"
        assert filtered["study_description"] == "[REDACTED-PHI]"
        assert filtered["rows"] == 512

    def test_filter_nested_phi(self):
        data = {
            "header": {
                "patient_id": "P12345",
                "patient_birth_date": "19800101"
            },
            "metadata": {
                "modality": "CT"
            }
        }
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered["header"]["patient_id"] == "[REDACTED-PHI]"
        assert filtered["header"]["patient_birth_date"] == "[REDACTED-PHI]"
        assert filtered["metadata"]["modality"] == "CT"

    def test_filter_list_items(self):
        data = [
            {"patient_name": "John", "study": "A"},
            {"patient_name": "Jane", "study": "B"}
        ]
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered[0]["patient_name"] == "[REDACTED-PHI]"
        assert filtered[1]["patient_name"] == "[REDACTED-PHI]"

    def test_safe_uids_not_filtered(self):
        data = {
            "study_instance_uid": "1.2.3.4",
            "patient_name": "John"
        }
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered["study_instance_uid"] == "1.2.3.4"
        assert filtered["patient_name"] == "[REDACTED-PHI]"
