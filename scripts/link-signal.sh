#!/bin/bash
# Signal Device Linking Script
# Run this once to link your Signal account

set -e

echo "=== Sunfish Relay - Signal Device Linking ==="
echo ""

# Start signal-api with port exposed for linking
echo "Starting Signal API for linking..."
docker run -d --rm \
    --name signal-link-temp \
    -p 127.0.0.1:8080:8080 \
    -v "$(pwd)/signal-data:/home/.local/share/signal-cli" \
    bbernhard/signal-cli-rest-api:latest

echo "Waiting for API to start..."
sleep 5

# Generate QR code
echo ""
echo "Generating linking QR code..."
curl -s -X GET "http://localhost:8080/v1/qrcodelink?device_name=Sunfish-Relay" --output /tmp/signal-qr.png

# Try to display QR code
if command -v open &> /dev/null; then
    open /tmp/signal-qr.png
    echo "QR code opened. Scan it with Signal on your phone:"
    echo "  Signal → Settings → Linked Devices → Link New Device"
elif command -v xdg-open &> /dev/null; then
    xdg-open /tmp/signal-qr.png
    echo "QR code opened. Scan it with Signal on your phone:"
    echo "  Signal → Settings → Linked Devices → Link New Device"
else
    echo "QR code saved to /tmp/signal-qr.png"
    echo "Open it and scan with Signal on your phone:"
    echo "  Signal → Settings → Linked Devices → Link New Device"
fi

echo ""
echo "Press Enter after you've scanned the QR code and confirmed linking..."
read

# Verify linking worked
echo ""
echo "Verifying link..."
sleep 2

# Try to get account info
if curl -s "http://localhost:8080/v1/about" | grep -q "version"; then
    echo "✓ Signal API is running"
else
    echo "✗ Could not verify Signal API"
fi

# Cleanup
echo ""
echo "Stopping temporary container..."
docker stop signal-link-temp 2>/dev/null || true

echo ""
echo "=== Linking Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit config/settings.yaml with your phone number"
echo "2. Get your group ID: docker-compose up signal-api -d && curl http://localhost:8080/v1/groups/YOUR_PHONE"
echo "3. Add group ID to config/settings.yaml"
echo "4. Run: docker-compose up -d"
