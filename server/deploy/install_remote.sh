#!/usr/bin/env bash
set -euo pipefail
APP=/opt/epaper
mkdir -p "$APP/data" "$APP/static" "$APP/deploy"
cd "$APP"

python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --upgrade pip
"$APP/venv/bin/pip" install -r "$APP/requirements.txt"

install -m 600 "$APP/deploy/epaper.env" "$APP/epaper.env"
install -m 644 "$APP/deploy/epaper.service" /etc/systemd/system/epaper.service

# Inject nginx location once
NGINX_SITE=/etc/nginx/sites-enabled/onlyclaws.world
if ! grep -q 'location /epaper/' "$NGINX_SITE"; then
  python3 - <<'PY'
from pathlib import Path
path = Path("/etc/nginx/sites-enabled/onlyclaws.world")
text = path.read_text()
snippet = """
    # BEGIN EPAPER
    location = /epaper { return 301 /epaper/; }
    location /epaper/ {
        proxy_pass         http://127.0.0.1:8787/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_buffering    off;
        client_max_body_size 2m;
    }
    # END EPAPER
"""
marker = "# BEGIN UMBRA_SUBPATH"
if marker in text:
    text = text.replace(marker, snippet + "\n" + marker, 1)
else:
    # insert before last closing brace of first server block
    idx = text.find("\n}")
    if idx == -1:
        raise SystemExit("cannot find nginx insert point")
    text = text[:idx] + "\n" + snippet + text[idx:]
path.write_text(text)
print("nginx snippet inserted")
PY
fi

nginx -t
systemctl daemon-reload
systemctl enable epaper
systemctl restart epaper
systemctl reload nginx
systemctl --no-pager --full status epaper | head -30
curl -sS http://127.0.0.1:8787/api/health
echo
