#!/bin/bash
# =========================================
# ONE-COMMAND SETUP — REDIS + CELERY FOR BUBBL.OOO
# =========================================
# Run as root on your DigitalOcean VPS:
#   chmod +x deploy/setup_redis_celery.sh
#   sudo ./deploy/setup_redis_celery.sh
#
# What this script does:
#   1. Installs Redis server (free, local, unlimited)
#   2. Configures Redis for low-memory usage (50MB cap)
#   3. Installs Python dependencies (celery, gevent, redis)
#   4. Installs the Celery systemd service
#   5. Starts everything

set -e  # Exit on any error

echo ""
echo "========================================="
echo "  BUBBL.OOO — Redis + Celery Setup"
echo "========================================="
echo ""

# --- 1. INSTALL REDIS ---
echo "[1/5] Installing Redis..."
apt update -qq
apt install redis-server -y -qq

# --- 2. CONFIGURE REDIS FOR 1GB DROPLET ---
echo "[2/5] Configuring Redis (50MB memory cap)..."

# Set max memory to 50MB (more than enough for task queues + cache)
sed -i 's/# maxmemory <bytes>/maxmemory 50mb/' /etc/redis/redis.conf
sed -i 's/# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/' /etc/redis/redis.conf

# Restart Redis to apply config
systemctl restart redis
systemctl enable redis

# Verify Redis is running
if redis-cli ping | grep -q "PONG"; then
    echo "  ✓ Redis is running (redis-cli ping → PONG)"
else
    echo "  ✗ Redis failed to start! Check: sudo systemctl status redis"
    exit 1
fi

# --- 3. INSTALL PYTHON DEPENDENCIES ---
echo "[3/5] Installing Python packages (celery, gevent, redis)..."
cd /root/Bubbl
source myenv/bin/activate
pip install celery==5.4.0 gevent==24.11.1 redis==5.2.1 -q

# --- 4. INSTALL CELERY SYSTEMD SERVICE ---
echo "[4/5] Installing Celery worker service..."
cp deploy/celery-bubbl.service /etc/systemd/system/celery-bubbl.service
systemctl daemon-reload
systemctl enable celery-bubbl

# --- 5. START CELERY WORKER ---
echo "[5/5] Starting Celery worker..."
systemctl start celery-bubbl

# Verify Celery is running
sleep 2
if systemctl is-active --quiet celery-bubbl; then
    echo "  ✓ Celery worker is running"
else
    echo "  ✗ Celery worker failed! Check: sudo journalctl -u celery-bubbl -f"
    exit 1
fi

echo ""
echo "========================================="
echo "  SETUP COMPLETE!"
echo "========================================="
echo ""
echo "  Redis:  running on localhost:6379 (50MB cap)"
echo "  Celery: running with gevent pool (20 concurrent tasks)"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status celery-bubbl    # Check worker status"
echo "    sudo journalctl -u celery-bubbl -f    # Live worker logs"
echo "    sudo systemctl restart celery-bubbl   # Restart worker"
echo "    redis-cli info memory                 # Check Redis memory"
echo ""
echo "  Next steps:"
echo "    1. Add REDIS_URL=redis://localhost:6379/0 to your .env (optional, defaults to this)"
echo "    2. Restart gunicorn: sudo systemctl restart bubbl"
echo "    3. Test: trigger a scrape from the dashboard"
echo ""
