#!/bin/bash
# Production Deployment Script
# Runs security checks before deploying

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Sunfish Relay Production Deployment ==="
echo ""

# Run security check first
echo "Running security pre-flight check..."
echo ""
./scripts/check-security.sh

echo ""
echo "Security check passed. Deploying..."
echo ""

# Lock down signal-data permissions if it exists
if [ -d "signal-data" ]; then
    chmod 700 signal-data
    echo "Locked signal-data/ permissions"
fi

# Deploy with docker-compose
docker-compose up -d

echo ""
echo "=== Deployment Complete ==="
echo ""
docker-compose ps
