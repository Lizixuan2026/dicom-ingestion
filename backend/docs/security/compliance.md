# DICOM Ingestion Security & Compliance Documentation

## Overview

This document describes the security controls and compliance measures implemented in the DICOM ingestion system.

## Regulatory Compliance

### HIPAA (Health Insurance Portability and Accountability Act)

Applicable Rules:
- Privacy Rule (45 CFR Part 160 and Subparts A and E of Part 164)
- Security Rule (45 CFR Part 160 and Subparts A and C of Part 164)
- Breach Notification Rule (45 CFR Part 164 Subpart D)

Implemented Controls:

#### Administrative Safeguards
- Access Management: Role-based access control (RBAC) for all PHI operations
- Audit Controls: Comprehensive audit logging of all PHI access (AuditLogger)
- Integrity Controls: SHA-256 checksums for all DICOM objects
- Security Training: Documented procedures for operators

#### Technical Safeguards
- Access Control: Input validation prevents unauthorized access (InputValidator)
- Transmission Security: TLS 1.2+ for all data in transit
- Audit Logs: Immutable audit trail stored separately from application logs
- Data Integrity: Content verification on upload and retrieval

### GDPR (General Data Protection Regulation)

Applicable Articles:
- Article 32: Security of processing
- Article 33: Notification of personal data breaches
- Article 35: Data protection impact assessment

Implemented Controls:
- Data minimization: Only necessary PHI fields stored
- Purpose limitation: Data used only for ingestion processing
- Storage limitation: Retention policies enforced

## PHI Handling

### Fields Considered PHI

Patient Identifiers:
- patient_name, patient_id, patient_birth_date, patient_birth_time
- patient_sex, patient_age, patient_weight, patient_address
- patient_phone, patient_mothers_maiden_name

Provider Identifiers:
- referring_physician_name, performing_physician_name
- operator_name, physician_of_record

Care Information:
- study_description, series_description
- raw DICOM tag values (unless explicitly allowlisted)

### PHI Protection Measures

#### 1. Logging Restrictions (PhiFilter)
- PHI fields are automatically redacted in all logs
- [REDACTED-PHI] token replaces actual values
- Structured logging ensures consistent filtering

#### 2. Audit Logging (AuditLogger)
- All PHI access is logged with: Actor ID, Resource ID, PHI fields accessed, Timestamp, Success/failure
- Logs are immutable and tamper-evident

#### 3. Input Validation (InputValidator)
- Path traversal prevention
- Null byte injection protection
- DICOM UID validation
- Filename sanitization

### Safe Fields (Non-PHI)

Technical Identifiers:
- study_instance_uid, series_instance_uid, sop_instance_uid
- sop_class_uid, transfer_syntax_uid

Allowlisted DICOM Tags:
- Modality, BodyPartExamined, StudyDate, StudyTime
- SeriesNumber, InstanceNumber, Rows, Columns
- PixelSpacing, SliceThickness, KVP, ExposureTime

## Security Controls

### Input Validation
- Path Validation: Max 4096 chars, path traversal detection, null byte detection
- UID Validation: DICOM UID format compliance, max 64 chars, digits and dots only

### Audit Controls
Logged Events:
- PHI access (read/write/update/delete)
- Ingestion job creation
- Replay operations
- Binding resolution
- Export operations

Log Format: Structured JSON with timestamp (ISO 8601 UTC), action, actor_id, resource_type/id, phi_accessed, phi_fields, success, correlation_id

## Testing and Verification

### Security Test Suite
```bash
python -m pytest tests/security/ -v
```

### Compliance Checklist

Before Each Release:
- All PHI fields identified and documented
- PhiFilter tests pass
- Audit logging tests pass
- No PHI in application logs (verify via grep)
- Input validation tests pass
- Security runbook reviewed

Quarterly:
- Audit log review
- Access control review
- Security incident review
- Compliance training verification

## Incident Response

### PHI Breach Response

Immediate (0-1 hour):
- Contain the breach
- Preserve evidence
- Notify security team

Short-term (1-24 hours):
- Assess scope of breach
- Identify affected individuals
- Document timeline

Notification (24-72 hours):
- HIPAA: Notify within 60 days if >500 individuals
- GDPR: Notify DPA within 72 hours if required
- Notify affected individuals as required

Remediation:
- Fix security gap
- Update procedures
- Post-incident review

## Contacts

- Security Team: security@example.com
- Compliance Officer: compliance@example.com
- On-Call Engineer: See PagerDuty
