#!/usr/bin/with-contenv bashio
set -euo pipefail

export SUPERK_LOG_LEVEL="$(bashio::config 'log_level')"
export SUPERK_HOST="$(bashio::config 'host')"
export SUPERK_PORT="$(bashio::config 'port')"

bashio::log.info "Starting SuperK addon"
bashio::log.info "Host: ${SUPERK_HOST} / Port: ${SUPERK_PORT} / Level: ${SUPERK_LOG_LEVEL}"

exec python3 /app/src/web_app.py
