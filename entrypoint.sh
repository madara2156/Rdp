#!/bin/bash
set -e

echo "[$(date)] Starting xrdp-sesman..."
/usr/sbin/xrdp-sesman

echo "[$(date)] Starting xrdp on port 3389..."
/usr/sbin/xrdp --nodaemon &
XRDP_PID=$!

echo "[$(date)] xrdp is running (PID $XRDP_PID). Connect via Railway's TCP Proxy."

wait "$XRDP_PID"
