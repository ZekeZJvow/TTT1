#!/bin/bash
# =============================================================
# A股人气榜 · Linux 一键部署脚本（Ubuntu/Debian）
# 用法：sudo bash deploy/install.sh
# =============================================================
set -e

APP_DIR="/opt/stock-popularity"

echo "=========================================="
echo "  A股人气榜 · 部署脚本"
echo "=========================================="

# 1. 系统依赖
echo "[1/7] 安装系统依赖..."
apt update -y
apt install -y python3 python3-pip python3-venv nginx curl git

# 2. Node.js（hithink-finance CLI 需要）
if ! command -v node >/dev/null 2>&1; then
    echo "[2/7] 安装 Node.js 22..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt install -y nodejs
else
    echo "[2/7] Node.js 已存在，跳过"
fi

# 3. 复制代码
echo "[3/7] 部署代码到 $APP_DIR ..."
mkdir -p "$APP_DIR"
cp -r ./* "$APP_DIR/" 2>/dev/null || true
cd "$APP_DIR"

# 4. Python 虚拟环境
echo "[4/7] 创建虚拟环境并安装依赖..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

# 5. 权限
echo "[5/7] 设置权限..."
chown -R www-data:www-data "$APP_DIR"
touch /var/log/stock-popularity.log
chown www-data:www-data /var/log/stock-popularity.log

# 6. systemd 服务
echo "[6/7] 注册 systemd 服务..."
cp deploy/stock-popularity.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable stock-popularity
systemctl restart stock-popularity

# 7. Nginx
echo "[7/7] 配置 Nginx..."
echo "  ⚠️ 请先修改 deploy/nginx.conf 里的 YOUR_DOMAIN，再执行："
echo "     cp deploy/nginx.conf /etc/nginx/conf.d/stock-popularity.conf"
echo "     nginx -t && systemctl reload nginx"

echo ""
echo "=========================================="
echo "  完成！检查服务状态："
echo "    systemctl status stock-popularity"
echo "    curl http://127.0.0.1:5000/api/trading-days?n=1"
echo "=========================================="
