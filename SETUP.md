# Sunfish Relay Setup Guide

Two ways to run this:
- **Native Mode** (Mac development) - simpler, no Docker needed
- **Docker Mode** (VPS deployment) - containerized, self-contained

---

## Option A: Native Mode (Recommended for Testing Tonight)

### 1. Install signal-cli

```bash
brew install signal-cli
```

### 2. Link to Your Signal Account

```bash
signal-cli link -n "Sunfish-Relay"
```

This prints a URI. Convert to QR code:
```bash
# Install qrencode if needed: brew install qrencode
signal-cli link -n "Sunfish-Relay" 2>&1 | grep -o 'sgnl://.*' | qrencode -t ANSI
```

On your phone: **Signal → Settings → Linked Devices → Scan QR**

### 3. Get Your Group ID

```bash
signal-cli -u +1YOURNUMBER listGroups
```

Copy the group ID (base64 string) for the group you want to use.

### 4. Configure

```bash
cd sunfish-relay
cp config/settings.example.yaml config/settings.yaml
```

Edit `config/settings.yaml`:
```yaml
signal:
  phone_number: "+1YOURNUMBER"
  mode: "native"
  allowed_group_ids:
    - "YOUR_GROUP_ID_HERE"

project_path: "./stream-project"
```

### 5. Install Python Dependencies

```bash
cd orchestrator
pip install -r requirements.txt
```

### 6. Login to Claude Code (One-Time)

```bash
claude
# Follow OAuth prompts to login with your Claude Pro/Max subscription
# Ctrl+C after login completes
```

### 7. Run

```bash
python main.py
```

### 8. Test

Send a message to your Signal group: "What time is it?"

---

## Option B: Docker Mode (VPS Deployment)

### 1. Copy Signal Data from Local Setup

If you already tested locally, just copy your linked account:
```bash
cp -r ~/.local/share/signal-cli ./signal-data
chmod 700 signal-data
```

Or link fresh using the script:
```bash
./scripts/link-signal.sh
```

### 2. Configure

```bash
cp config/settings.example.yaml config/settings.yaml
```

Edit with your phone number, group ID, and set `mode: "docker"`.

### 3. Login to Claude Code on VPS

SSH to VPS and run:
```bash
claude
# Complete OAuth login
```

### 4. Run Security Check

```bash
./scripts/check-security.sh
```

This verifies:
- No ports exposed
- Secrets not in git
- Correct file permissions

### 5. Deploy

```bash
./scripts/deploy.sh
```

This runs the security check automatically before deploying.

---

## Authentication

Claude Code supports multiple auth methods:

| Method | Setup |
|--------|-------|
| **Claude Pro/Max** (recommended) | Run `claude` and follow OAuth login |
| **API Key** | `export ANTHROPIC_API_KEY="sk-ant-..."` |
| **Amazon Bedrock** | Configure AWS credentials |
| **Google Vertex** | Configure GCP credentials |

Your subscription works for both claude.ai web and Claude Code.

---

## Privacy & Security

**The default configuration exposes zero ports.** This is intentional.

### What's Protected

| Asset | Protection |
|-------|------------|
| `signal-data/` | Gitignored, 700 permissions, contains encryption keys |
| `config/settings.yaml` | Gitignored, contains phone number |
| Docker network | Internal only, no ports exposed to host or internet |
| Signal traffic | End-to-end encrypted by Signal protocol |

### Security Scripts

```bash
# Check for security issues before deploying
./scripts/check-security.sh

# Deploy (runs security check first, fails if issues found)
./scripts/deploy.sh
```

### Development Mode (Exposed Ports)

If you need to debug the Signal API directly, you must explicitly request it:

```bash
# Explicit dev mode - ONLY for local debugging
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# This exposes localhost:8080 - never use in production
```

### What Could Go Wrong

| Mistake | Consequence | Prevention |
|---------|-------------|------------|
| Commit `signal-data/` | Encryption keys leaked | Gitignored by default |
| Use override file in prod | API exposed to network | Override file doesn't exist by default |
| Weak VPS security | Root access = full compromise | Standard VPS hardening (SSH keys, firewall) |

---

## Using Claude Code as VPS Sysadmin

Via Signal message:
- "Check stream health"
- "What's eating CPU?"
- "Edit prompt.yaml to be more concise"
- "Restart OBS"
- "Show last 20 lines of error log"

Via SSH:
```bash
claude -p "Set up OBS with optimal encoding settings for this GPU"
claude -p "Diagnose why the stream dropped 5 minutes ago"
claude -p "Install and configure nginx as reverse proxy"
```
