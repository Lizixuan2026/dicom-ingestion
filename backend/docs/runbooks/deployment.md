# DICOM Ingestion Deployment Runbook

## Pre-Deployment Checklist

### 1. Database Migrations
```bash
alembic current
alembic heads
alembic upgrade head
```

### 2. Configuration Validation
```bash
python -m dicom_ingestion.ops.deployment_checks
```

### 3. Smoke Tests
```bash
python -m dicom_ingestion.ops.smoke_tests
```

## Deployment Steps

### Step 1: Blue-Green Deployment
```bash
deploy --target=green --version=$NEW_VERSION
run_smoke_tests --target=green
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

### 3. Test Ingestion
```bash
curl -X POST -F "file=@test.dcm" http://localhost:8080/upload
curl http://localhost:8080/metrics | grep "dicom_ingestion_items_total"
```

## Troubleshooting

### Issue: High Error Rate
1. Check logs: `docker-compose logs | grep ERROR`
2. Check database connection pool
3. Check object storage connectivity
4. Consider rollback if > 5% error rate

### Issue: Slow Ingestion
1. Check stage durations in metrics
2. Verify database query performance
3. Check object storage latency
4. Consider scaling workers

### Issue: Disk Space
1. Check raw object storage size
2. Verify old data archival policy
3. Clean up failed upload temp files
