"""PHI (Protected Health Information) filtering for logs."""

from typing import Any, Dict, List, Set, Union


class PhiFilter:
    """Filters PHI from data structures before logging."""
    
    PHI_FIELDS: Set[str] = {
        "patient_name",
        "patient_id",
        "patient_birth_date",
        "patient_birth_time",
        "patient_sex",
        "patient_age",
        "patient_weight",
        "patient_address",
        "patient_phone",
        "patient_mothers_maiden_name",
        "patient_ssn",
        "patient_insurance",
        "referring_physician_name",
        "performing_physician_name",
        "operator_name",
        "physician_of_record",
        "study_description",
        "series_description",
        "raw_dicom_tags",
    }
    
    SAFE_UID_FIELDS: Set[str] = {
        "study_instance_uid",
        "series_instance_uid",
        "sop_instance_uid",
        "sop_class_uid",
        "transfer_syntax_uid",
    }
    
    SAFE_DICOM_TAGS: Set[str] = {
        "Modality",
        "BodyPartExamined",
        "StudyDate",
        "StudyTime",
        "SeriesNumber",
        "InstanceNumber",
        "Rows",
        "Columns",
        "PixelSpacing",
        "SliceThickness",
        "KVP",
        "ExposureTime",
        "XRayTubeCurrent",
    }
    
    REDACTION_TOKEN = "[REDACTED-PHI]"
    
    @classmethod
    def filter_for_logging(cls, data: Any) -> Any:
        """Recursively filter PHI from data structure."""
        if isinstance(data, dict):
            return cls._filter_dict(data)
        elif isinstance(data, list):
            return [cls.filter_for_logging(item) for item in data]
        else:
            return data
    
    @classmethod
    def _filter_dict(cls, data: Dict) -> Dict:
        """Filter PHI from a dictionary."""
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            
            if key_lower in cls.PHI_FIELDS:
                result[key] = cls.REDACTION_TOKEN
            elif key_lower in cls.SAFE_UID_FIELDS:
                result[key] = value
            elif isinstance(value, (dict, list)):
                result[key] = cls.filter_for_logging(value)
            else:
                result[key] = value
        
        return result
    
    @classmethod
    def is_phi_field(cls, field_name: str) -> bool:
        """Check if a field name is considered PHI."""
        return field_name.lower() in cls.PHI_FIELDS
    
    @classmethod
    def is_safe_dicom_tag(cls, tag_name: str) -> bool:
        """Check if a DICOM tag is safe to log."""
        return tag_name in cls.SAFE_DICOM_TAGS
