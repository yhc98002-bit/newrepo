#!/usr/bin/env bash
set -euo pipefail

proxy_url="${SA3_PROXY_URL:-http://127.0.0.1:7890}"

exec env \
  HTTP_PROXY="$proxy_url" \
  HTTPS_PROXY="$proxy_url" \
  ALL_PROXY="$proxy_url" \
  http_proxy="$proxy_url" \
  https_proxy="$proxy_url" \
  all_proxy="$proxy_url" \
  "$@"
