#!/bin/sh
set -eu
umask 077

# Railway volumes overlay /data at runtime, after Dockerfile RUN chown.
# Repair ownership of the mounted filesystem as root, then DROP privileges
# before starting API/MCP/Whisper processes.
DATA_DIR="${AUTOCLIPS_HOME:-/data}"
if [ -d "$DATA_DIR" ]; then
  chown -R autoclips:autoclips "$DATA_DIR"
else
  mkdir -p "$DATA_DIR"
  chown -R autoclips:autoclips "$DATA_DIR"
fi
exec gosu autoclips "$@"
