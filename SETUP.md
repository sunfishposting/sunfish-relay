# Sunfish Relay Setup Guide

## Prerequisites

- Python 3.10+
- Java 21+ (for signal-cli)
- Claude Code CLI (`claude` command)
- A Signal account with a phone number

---

## Windows Server Setup (VPS)

### 1. Install Dependencies

```powershell
# Install Chocolatey if not present
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install Java, Python, Git
choco install temurin python git -y

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

### 2. Install signal-cli

Check latest version at: https://github.com/AsamK/signal-cli/releases

```powershell
$version = "0.13.22"  # Update to latest
$url = "https://github.com/AsamK/signal-cli/releases/download/v$version/signal-cli-$version.tar.gz"
Invoke-WebRequest -Uri $url -OutFile "$env:USERPROFILE\Downloads\signal-cli.tar.gz"

New-Item -ItemType Directory -Path "C:\signal-cli" -Force
tar -xzf "$env:USERPROFILE\Downloads\signal-cli.tar.gz" -C "C:\signal-cli"

# Add to PATH
$env:Path += ";C:\signal-cli\signal-cli-$version\bin"
[Environment]::SetEnvironmentVariable("Path", $env:Path, "Machine")

# Verify
signal-cli --version
```

### 3. Link signal-cli to Your Signal Account

```powershell
# Generate link URI
signal-cli link -n "Sunfish-Relay"
```

This outputs a `sgnl://` URI. Generate a QR code:

```powershell
python -m pip install qrcode
python -c "import qrcode; qr = qrcode.QRCode(); qr.add_data('PASTE_SGNL_URI_HERE'); qr.print_ascii()"
```

Scan with Signal app: **Settings → Linked Devices → Link New Device**

### 4. Get Your Group ID

```powershell
signal-cli -u +YOUR_PHONE receive  # Sync first
signal-cli -u +YOUR_PHONE listGroups
```

Copy the group ID (base64 string).

### 5. Clone and Configure

```powershell
cd C:\Users\Administrator
git clone https://github.com/YOUR_ORG/sunfish-relay.git
cd sunfish-relay

copy config\settings.example.yaml config\settings.yaml
notepad config\settings.yaml
```

Fill in:
- `phone_number`: Your Signal number
- `allowed_group_ids`: The group ID from step 4
- `trigger_word`: How to summon Claude (default: `@claude`)

### 6. Install Python Dependencies

```powershell
cd orchestrator
python -m pip install -r requirements.txt
```

### 7. Configure Claude Code

Claude Code needs to be authenticated. Either:

**Option A: OAuth (Claude Pro/Max subscription)**
```powershell
claude
# Follow browser prompts to authenticate
```

**Option B: OpenRouter**
Create `.claude/settings.local.json` in the repo:
```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
    "ANTHROPIC_AUTH_TOKEN": "sk-or-v1-YOUR-KEY",
    "ANTHROPIC_API_KEY": ""
  }
}
```

### 8. Run

```powershell
cd C:\Users\Administrator\sunfish-relay\orchestrator
python main.py
```

### 9. Test

Send to your Signal group: `@claude status`

---

## Auto-Start on Boot

### Automatic Setup (Recommended)

Run the setup script as Administrator:

```powershell
cd C:\Users\Administrator\sunfish-relay\scripts
powershell -ExecutionPolicy Bypass -File setup-autostart.ps1
```

This creates a Windows Task Scheduler task that:
- Starts on boot (before login)
- Runs as SYSTEM
- Auto-restarts on crash
- Has no time limit

### Manual Setup

If you prefer to set it up manually:

1. Open Task Scheduler (taskschd.msc)
2. Create Task (not Basic Task)
3. General tab:
   - Name: "Sunfish-Relay"
   - Run whether user is logged on or not
   - Run with highest privileges
4. Triggers tab:
   - New → At startup
5. Actions tab:
   - New → Start a program
   - Program: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Administrator\sunfish-relay\scripts\start-windows.ps1"`
6. Settings tab:
   - Allow task to be run on demand
   - If task fails, restart every 1 minute
   - Stop task if runs longer than: (disable/uncheck)

### Verify Auto-Start

```powershell
# Check task exists
Get-ScheduledTask -TaskName "Sunfish-Relay"

# Test run
Start-ScheduledTask -TaskName "Sunfish-Relay"

# Check if running
Get-Process python -ErrorAction SilentlyContinue
```

---

## macOS / Linux Setup

### 1. Install signal-cli

```bash
# macOS
brew install signal-cli

# Linux (check latest version)
VERSION=0.13.22
wget https://github.com/AsamK/signal-cli/releases/download/v${VERSION}/signal-cli-${VERSION}.tar.gz
tar xf signal-cli-${VERSION}.tar.gz -C /opt
ln -s /opt/signal-cli-${VERSION}/bin/signal-cli /usr/local/bin/
```

### 2. Link to Signal

```bash
signal-cli link -n "Sunfish-Relay"
# Scan QR code with Signal app
```

### 3. Clone and Configure

```bash
git clone https://github.com/YOUR_ORG/sunfish-relay.git
cd sunfish-relay
cp config/settings.example.yaml config/settings.yaml
# Edit settings.yaml with your values
```

### 4. Install Dependencies

```bash
cd orchestrator
pip install -r requirements.txt
```

### 5. Run

```bash
python main.py
```

---

## Configuration Reference

See `config/settings.example.yaml` for all options. Key settings:

| Setting | Description |
|---------|-------------|
| `signal.phone_number` | Your Signal phone number |
| `signal.allowed_group_ids` | Groups that can send commands |
| `trigger_word` | Word that triggers Claude (e.g., `@claude`) |
| `proactive_alerts` | Send alerts when thresholds exceeded |
| `monitors.*` | Enable/configure system monitors |

---

## Troubleshooting

### signal-cli not found
Ensure it's in your PATH. On Windows, restart terminal after PATH changes.

### Java errors
signal-cli requires Java 21+. Check with `java -version`.

### Claude not responding
1. Check trigger word matches your message
2. Verify `claude --version` works
3. Check orchestrator logs for errors

### Messages not received
1. Run `signal-cli -u +PHONE receive` manually
2. Verify group ID is correct
3. Check phone number format (+1XXXXXXXXXX)

---

## Security Notes

- `signal-data/` contains encryption keys - never commit
- `config/settings.yaml` contains your phone number - gitignored
- No ports are exposed by default
- All communication goes through Signal's E2E encryption
