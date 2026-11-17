#!/usr/bin/env bash
# Cloudflare IP 대역을 받아 Nginx real_ip 설정 파일을 다시 만듭니다.
# 운영 서버 방화벽(80/443 허용 대역)도 같은 목록을 기준으로 맞춥니다.
set -euo pipefail

out="$(dirname "$0")/../deploy/nginx/cloudflare-ips.conf"
tmp="$(mktemp)"

{
  echo "# Cloudflare IP 대역 — scripts/update_cloudflare_ips.sh로 생성. 직접 수정하지 마세요."
  echo "# 생성: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for v in 4 6; do
    # 응답 끝에 줄바꿈이 없으므로 echo로 보충
    { curl -sf "https://www.cloudflare.com/ips-v$v"; echo; } | sed '/^$/d; s/.*/set_real_ip_from &;/'
  done
  echo "real_ip_header CF-Connecting-IP;"
} > "$tmp"

mv "$tmp" "$out"
echo "갱신 완료: $out"
