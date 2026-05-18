# DICOM Ingestion Incident Response Runbook

## Severity Levels

### P1 - Critical (Service Down)
- Complete ingestion pipeline failure
- Data loss or corruption detected
- Security breach suspected
Response: Page on-call immediately, war room within 15 minutes

### P2 - High (Degraded Service)
- Error rate > 5%
- Ingestion latency > 30 seconds
- Partial functionality unavailable
Response: Page on-call, start investigation within 30 minutes

### P3 - Medium (Minor Impact)
- Error rate 1-5%
- Non-critical alerts firing
- Performance degradation
Response: Investigate during business hours

### P4 - Low (No User Impact)
- Warnings, capacity alerts
- Monitoring gaps
Response: Track in backlog

## Alert Response Procedures

### Alert: High Error Rate
Trigger: dicom_ingestion_items_total{status="failed"} > 0.05
Response:
1. Check error logs: grep ERROR /var/log/dicom-ingestion/app.log
2. Identify failing stage from metrics
3. Check database connectivity
4. Check object storage connectivity
5. If error rate > 10%, initiate rollback

### Alert: Items Stuck
Trigger: dicom_ingestion_items_stuck_total > 0
Response:
1. Query stuck items: SELECT * FROM dicom_ingestion_items WHERE status_axes->>'scan_status' = 'in_progress' AND updated_at < NOW() - INTERVAL '10 minutes'
2. Identify stage where items are stuck
3. Check for deadlocks: SELECT * FROM pg_locks
4. Restart stuck items via replay API

### Alert: Database Connection Pool Exhausted
Trigger: Connection pool utilization > 80%
Response:
1. Check active connections: SELECT count(*) FROM pg_stat_activity
2. Identify long-running queries
3. Kill stale connections if needed
4. Consider increasing pool size temporarily

### Alert: PHI Access Anomaly
Trigger: Unusual PHI access patterns in audit log
Response:
1. Review audit logs: tail -f /var/log/dicom-ingestion/audit.log
2. Verify actor_ids are legitimate
3. Check for unauthorized access attempts
4. Escalate to security team if breach suspected

## Escalation Path

1. L1 - On-call Engineer: Initial response and triage, standard playbook procedures, 30-minute time box
2. L2 - Senior Engineer: Complex issues requiring deep system knowledge, cross-service coordination, 1-hour time box
3. L3 - Team Lead / Manager: Resource allocation decisions, external communication, rollback authorization
4. L4 - Security Team: PHI access incidents, compliance violations, data breach response

## Post-Incident Review

Within 24 hours of incident resolution:
1. Timeline Documentation: Alert firing time, response start time, resolution time, total downtime
2. Root Cause Analysis: Technical cause, contributing factors, process gaps
3. Remediation Actions: Immediate fixes applied, short-term improvements (1 week), long-term improvements (1 month)
4. Review Meeting: Schedule within 3 business days, include all responders, document lessons learned
