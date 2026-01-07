#!/bin/bash
# Security Pre-flight Check
# Run this before deploying to production

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

echo "=== Sunfish Relay Security Check ==="
echo ""

# Check 1: No override file
if [ -f "docker-compose.override.yml" ]; then
    echo -e "${RED}[FAIL]${NC} docker-compose.override.yml exists"
    echo "       This file exposes ports and should be deleted for production."
    echo "       Run: rm docker-compose.override.yml"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}[PASS]${NC} No override file (ports not exposed)"
fi

# Check 2: signal-data permissions
if [ -d "signal-data" ]; then
    PERMS=$(stat -f "%OLp" signal-data 2>/dev/null || stat -c "%a" signal-data 2>/dev/null)
    if [ "$PERMS" != "700" ]; then
        echo -e "${YELLOW}[WARN]${NC} signal-data/ permissions are $PERMS (should be 700)"
        echo "       Run: chmod 700 signal-data"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${GREEN}[PASS]${NC} signal-data/ has restricted permissions"
    fi
else
    echo -e "${GREEN}[PASS]${NC} No signal-data/ directory yet (will be created)"
fi

# Check 3: Config file not in git
if [ -f "config/settings.yaml" ]; then
    if git ls-files --error-unmatch config/settings.yaml &>/dev/null; then
        echo -e "${RED}[FAIL]${NC} config/settings.yaml is tracked by git"
        echo "       Run: git rm --cached config/settings.yaml"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "${GREEN}[PASS]${NC} config/settings.yaml is not tracked by git"
    fi
fi

# Check 4: signal-data not in git
if [ -d "signal-data" ]; then
    if git ls-files --error-unmatch signal-data &>/dev/null 2>&1; then
        echo -e "${RED}[FAIL]${NC} signal-data/ is tracked by git"
        echo "       This contains encryption keys! Remove immediately:"
        echo "       git rm -r --cached signal-data"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "${GREEN}[PASS]${NC} signal-data/ is not tracked by git"
    fi
fi

# Check 5: Docker network is internal
if [ -f "docker-compose.yml" ]; then
    if grep -q "ports:" docker-compose.yml; then
        echo -e "${RED}[FAIL]${NC} docker-compose.yml has exposed ports"
        echo "       Production config should not expose any ports."
        ERRORS=$((ERRORS + 1))
    else
        echo -e "${GREEN}[PASS]${NC} docker-compose.yml has no exposed ports"
    fi
fi

# Check 6: .gitignore has required entries
if [ -f ".gitignore" ]; then
    MISSING=""
    grep -q "signal-data" .gitignore || MISSING="$MISSING signal-data"
    grep -q "settings.yaml" .gitignore || MISSING="$MISSING settings.yaml"

    if [ -n "$MISSING" ]; then
        echo -e "${YELLOW}[WARN]${NC} .gitignore missing:$MISSING"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${GREEN}[PASS]${NC} .gitignore has required entries"
    fi
fi

echo ""
echo "=== Summary ==="

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}$ERRORS error(s) found - DO NOT deploy until fixed${NC}"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}$WARNINGS warning(s) - review before deploying${NC}"
    exit 0
else
    echo -e "${GREEN}All checks passed - safe to deploy${NC}"
    exit 0
fi
