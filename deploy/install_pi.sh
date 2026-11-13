#!/usr/bin/env bash
# Cài HAR demo lên Raspberry Pi 4. Chạy từ thư mục gói:  bash deploy/install_pi.sh
# An toàn khi chạy lại: không ghi đè har_demo.toml đã có, không tạo lại token đã có.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/har
CONF_DIR=/etc/har
CONF="$CONF_DIR/har_demo.toml"
USER_NAME="$(id -un)"

for required in har collector requirements-har.txt har_runs/own_rf_01 data/har_own; do
    if [ ! -e "$SRC/$required" ]; then
        echo "thiếu $required trong $SRC" >&2
        exit 1
    fi
done

echo "1/5 chép mã và mô hình vào $DEST"
sudo install -d -o "$USER_NAME" -g "$USER_NAME" "$DEST" "$DEST/data" "$DEST/har_runs"
cp -r "$SRC/har" "$SRC/collector" "$SRC/requirements-har.txt" "$DEST/"
cp -r "$SRC/har_runs/own_rf_01" "$DEST/har_runs/"
cp -r "$SRC/data/har_own" "$DEST/data/"

echo "2/5 môi trường Python"
if [ ! -x "$DEST/.venv/bin/python" ]; then
    python3 -m venv "$DEST/.venv"
fi
"$DEST/.venv/bin/pip" install --quiet --upgrade pip
"$DEST/.venv/bin/pip" install --quiet -r "$DEST/requirements-har.txt"

echo "3/5 cấu hình $CONF"
sudo install -d -o "$USER_NAME" -g "$USER_NAME" "$CONF_DIR"
if [ ! -f "$CONF" ]; then
    cp "$DEST/har/har_demo.example.toml" "$CONF"
    echo "   đã tạo từ mẫu: sửa esp = ... cho đúng IP ESP32 trong $CONF"
fi
if ! grep -q '^token ' "$CONF"; then
    TOKEN="$("$DEST/.venv/bin/python" -m har new-token)"
    printf 'token = "%s"\n' "$TOKEN" >> "$CONF"
    echo "   đã thêm token truy cập vào $CONF (mở trang: http://<IP-Pi4>:8080/?token=<token>)"
fi
chmod 600 "$CONF"

echo "4/5 dịch vụ systemd"
sudo install -m 644 "$SRC/deploy/har-demo.service" /etc/systemd/system/har-demo.service
sudo sed -i "s#^User=.*#User=$USER_NAME#" /etc/systemd/system/har-demo.service
sudo systemctl daemon-reload
sudo systemctl enable har-demo.service

echo "5/5 khởi động"
sudo systemctl restart har-demo.service
sleep 3
systemctl --no-pager --lines=5 status har-demo.service || true
echo "xong. Kiểm tra sức khỏe: curl -H 'Authorization: Bearer <token>' http://127.0.0.1:8080/health"
