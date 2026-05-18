# DICOM Ingestion Deployment Runbook

## Pre-Deployment Checklist

### 1. Database Migrations
```bash
alembic current
alembic heads
alembic upgrade head
```

### 2. Configuration Validation

**Basic validation:**
```bash
python -m dicom_ingestion.ops.deployment_checks
```

**With configuration check:**
```bash
python -m dicom_ingestion.ops.deployment_checks --check-config
```

**JSON output (for automation):**
```bash
python -m dicom_ingestion.ops.deployment_checks --json
# Expected output example:
# {
#   "valid": true,
#   "checks": [
#     {"check_name": "deployment", "valid": true, "message": "..."}
#   ]
# }
```

**Exit codes:**
- `0` - All checks passed
- `1` - One or more checks failed
- `2` - Internal error

### 3. Smoke Tests

**Basic smoke test:**
```bash
python -m dicom_ingestion.ops.smoke_tests
```

**JSON output (for automation):**
```bash
python -m dicom_ingestion.ops.smoke_tests --json
# Expected output example:
# {
#   "service": "dicom_ingestion",
#   "timestamp": "2026-05-18T09:30:00Z",
#   "success": true,
#   "total_duration_ms": 150.5,
#   "tests": {
#     "health": {"passed": true, "status": "passed", "message": "..."}
#   }
# }
```

**Exit codes:**
- `0` - All tests passed
- `1` - One or more tests failed
- `2` - Internal error

## Deployment Steps

### Step 1: Blue-Green Deployment
```bash
deploy --target=green --version=$NEW_VERSION
python -m dicom_ingestion.ops.smoke_tests --target=green
switch_traffic --from=blue --to=green
monitor --duration=5m --alert_on_error_rate=0.01
```

### Step 2: Database Migration
```bash
alembic upgrade head
alembic current
```

### Step 3: Service Startup
```bash
docker-compose up -d
docker-compose ps
curl http://localhost:8080/metrics
```

## Rollback Procedures

### Automatic Rollback Triggers
- Error rate > 1% for 2 minutes
- Health check failures > 3 in 1 minute
- Latency p99 > 10 seconds

### Manual Rollback
```bash
switch_traffic --from=green --to=blue
docker-compose -f docker-compose.green.yml down
curl http://localhost:8080/health
```

### Database Rollback (Emergency Only)
```bash
alembic history --verbose
alembic downgrade -1
alembic current
```

## Post-Deployment Verification

### 1. Health Checks
```bash
curl http://localhost:8080/health | jq .
```

### 2. Metrics Collection
```bash
curl http://localhost:8080/metrics | grep "dicom_ingestion_"
```

### 3. Dashboard Verification

**Key operational panels to verify:**
- Ingestion Rate (items/min) - Panel ID 1
- Error Rate by Stage - Panel ID 2
- Stage Duration (p99) - Panel ID 3
- Stuck Items (with alert) - Panel ID 4
- **Replay Operations** - Panel ID 8
- **Conflict Resolution Status** - Panel ID 9
- **Indexing Lag** (with alert) - Panel ID 10
- **Recovery Time (MTTR)** - Panel ID 11

### 4. Test Ingestion
```bash
curl -X POST -F "file=@test.dcm" http://localhost:8080/upload
curl http://localhost:8080/metrics | grep "dicom_ingestion_items_total"
```

## Troubleshooting

### Issue: High Error Rate
1. Check logs: `docker-compose logs | grep ERROR`
2. Check database connection pool
3. Check object storage connectivity
4. **Check Replay Operations panel** for recovery success rate
5. **Check Conflict Resolution Status** for pending conflicts
6. Consider rollback if > 5% error rate

### Issue: Slow Ingestion
1. Check stage durations in metrics
2. Verify database query performance
3. Check object storage latency
4. **Check Indexing Lag panel** for search index delays
5. Consider scaling workers

### Issue: Items Stuck
1. **Check Stuck Items panel** - alert fires when items stuck > 0
2. **Check Indexing Lag panel** - indexing delays can cause stuck items
3. **Check Replay Operations** - verify replay success for failed items
4. Query stuck items: `SELECT * FROM dicom_ingestion_items WHERE status_axes->>'scan_status' = 'in_progress' AND updated_at < NOW() - INTERVAL '10 minutes'`
5. Restart stuck items via replay API

### Issue: Conflict Resolution
1. **Check Conflict Resolution Status panel** - alert fires for unresolved conflicts
2. Review binding policy rules
3. Manually resolve conflicts if needed

### Issue: Disk Space
1. Check raw object storage size
2. Verify old data archival policy
3. Clean up failed upload temp files

## Dashboard to Runbook Mapping

| Dashboard Panel | Runbook Section | Action When Alert Fires |
|----------------|-----------------|------------------------|
| Stuck Items | Issue: Items Stuck | Query stuck items, check for deadlocks, restart via replay API |
| Replay Operations | Issue: High Error Rate | Check replay success rate, verify raw bytes in storage |
| Conflict Resolution Status | Issue: Conflict Resolution | Review binding policy, manually resolve if needed |
| Indexing Lag | Issue: Slow Ingestion | Check search index performance, verify indexing pipeline |
| Recovery Time (MTTR) | Post-Deployment Verification | Monitor recovery efficiency |
