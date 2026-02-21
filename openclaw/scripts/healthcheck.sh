#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Trading Bot v2 — System Health Check
# Run via cron every 30 minutes on the host
# ═══════════════════════════════════════════════════════════════

set -e

TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
STATUS="OK"
ISSUES=""

echo "=== Health Check: $TIMESTAMP ==="

# 1. Check PostgreSQL
if docker compose -f ~/trading-bot/openclaw/docker-compose.yml ps postgres | grep -q "running"; then
    echo "[OK] PostgreSQL is running"
else
    STATUS="DEGRADED"
    ISSUES="$ISSUES\n- PostgreSQL is not running"
    echo "[FAIL] PostgreSQL is NOT running"
fi

# 2. Check OpenClaw Gateway
if systemctl is-active --quiet openclaw 2>/dev/null; then
    echo "[OK] OpenClaw Gateway is running"
else
    STATUS="DEGRADED"
    ISSUES="$ISSUES\n- OpenClaw Gateway is not running"
    echo "[FAIL] OpenClaw Gateway is NOT running"
fi

# 3. Check IBKR Gateway
if ss -tlnp | grep -q ":7497"; then
    echo "[OK] IBKR Gateway is listening on port 7497"
elif ss -tlnp | grep -q ":7496"; then
    echo "[OK] IBKR Gateway is listening on port 7496 (LIVE)"
else
    STATUS="DEGRADED"
    ISSUES="$ISSUES\n- IBKR Gateway is not listening"
    echo "[WARN] IBKR Gateway port not detected"
fi

# 4. Check SEC RSS Monitor
if docker compose -f ~/trading-bot/openclaw/docker-compose.yml ps sec-rss-monitor | grep -q "running"; then
    echo "[OK] SEC RSS Monitor is running"
else
    STATUS="DEGRADED"
    ISSUES="$ISSUES\n- SEC RSS Monitor is not running"
    echo "[WARN] SEC RSS Monitor is NOT running"
fi

# 5. Check disk space
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo "[OK] Disk usage: ${DISK_USAGE}%"
else
    STATUS="DEGRADED"
    ISSUES="$ISSUES\n- Disk usage is ${DISK_USAGE}%"
    echo "[WARN] Disk usage high: ${DISK_USAGE}%"
fi

# 6. Check data freshness (calendar.json should be from today on weekdays)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -le 5 ]; then
    DATA_FILE=~/trading-bot/openclaw/data/calendar.json
    if [ -f "$DATA_FILE" ]; then
        FILE_AGE=$(( $(date +%s) - $(stat -c %Y "$DATA_FILE") ))
        if [ "$FILE_AGE" -lt 86400 ]; then
            echo "[OK] calendar.json is fresh (${FILE_AGE}s old)"
        else
            echo "[WARN] calendar.json is stale (${FILE_AGE}s old)"
        fi
    else
        echo "[INFO] No calendar.json yet"
    fi
fi

echo ""
echo "Overall Status: $STATUS"
if [ "$STATUS" != "OK" ]; then
    echo -e "Issues:$ISSUES"
fi
echo "=== End Health Check ==="
