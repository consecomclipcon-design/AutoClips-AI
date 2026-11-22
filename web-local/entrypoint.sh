#!/bin/sh
set -eu
: "${API_URL:=}"
: "${SUPABASE_URL:=}"
: "${SUPABASE_PUBLISHABLE_KEY:=}"
: "${GOOGLE_CLIENT_ID:=}"
case "$API_URL" in ""|https://*) ;; *) echo "API_URL must be HTTPS" >&2; exit 1;; esac
case "$SUPABASE_URL" in ""|https://*) ;; *) echo "SUPABASE_URL must be HTTPS" >&2; exit 1;; esac
case "$SUPABASE_PUBLISHABLE_KEY" in sb_secret_*|eyJ*) echo "Do NOT serve Supabase secret/service_role keys" >&2; exit 1;; esac
case "$GOOGLE_CLIENT_ID" in ""|*apps.googleusercontent.com) ;; *) echo "Invalid GOOGLE_CLIENT_ID" >&2; exit 1;; esac
if [ -z "$API_URL" ] || [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_PUBLISHABLE_KEY" ] || [ -z "$GOOGLE_CLIENT_ID" ]; then
  echo "AUTOCLIPS_PREVIEW_ONLY: frontend ready, SaaS login/billing not configured" >&2
fi
envsubst '${API_URL} ${SUPABASE_URL} ${SUPABASE_PUBLISHABLE_KEY} ${GOOGLE_CLIENT_ID}' \
  < /tmp/saas-config.template.json > /usr/share/nginx/html/saas-config.json
envsubst '${API_URL} ${SUPABASE_URL}' \
  < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
