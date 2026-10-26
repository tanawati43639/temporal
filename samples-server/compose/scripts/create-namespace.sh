#!/bin/sh
set -eu

# Space/comma separated list of namespaces to create.
# Falls back to DEFAULT_NAMESPACE for backward compatibility.
NAMESPACES=${NAMESPACES:-${DEFAULT_NAMESPACE:-default}}
NAMESPACES=$(echo "$NAMESPACES" | tr ',' ' ')
TEMPORAL_ADDRESS=${TEMPORAL_ADDRESS:-temporal:7233}
NAMESPACE_RETENTION=${NAMESPACE_RETENTION:-72h}
MAX_ATTEMPTS=${TEMPORAL_HEALTH_CHECK_MAX_ATTEMPTS:-30}
SLEEP_SECONDS=${TEMPORAL_HEALTH_CHECK_SLEEP_SECONDS:-5}

echo "Waiting for Temporal server port to be available..."
SERVER_HOST=$(echo "$TEMPORAL_ADDRESS" | cut -d: -f1)
SERVER_PORT=$(echo "$TEMPORAL_ADDRESS" | cut -d: -f2)
attempt=1
while ! nc -z -w 10 "$SERVER_HOST" "$SERVER_PORT"; do
  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "Temporal server port did not become available after $MAX_ATTEMPTS attempts"
    exit 1
  fi

  echo "Temporal server port not ready yet, waiting... (attempt $attempt/$MAX_ATTEMPTS)"
  attempt=$((attempt + 1))
  sleep "$SLEEP_SECONDS"
done
echo 'Temporal server port is available'

echo 'Waiting for Temporal server to be healthy...'
attempt=1
while :; do
  if temporal operator cluster health --address "$TEMPORAL_ADDRESS"; then
    break
  fi

  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "Server did not become healthy after $MAX_ATTEMPTS attempts"
    exit 1
  fi

  echo "Server not ready yet, waiting... (attempt $attempt/$MAX_ATTEMPTS)"
  attempt=$((attempt + 1))
  sleep "$SLEEP_SECONDS"
done
echo 'Server is healthy'

create_namespace() {
  ns=$1
  attempt=1
  while :; do
    if temporal operator namespace describe -n "$ns" --address "$TEMPORAL_ADDRESS" >/dev/null 2>&1; then
      echo "Namespace '$ns' already exists"
      return 0
    fi

    if temporal operator namespace create -n "$ns" --retention "$NAMESPACE_RETENTION" --address "$TEMPORAL_ADDRESS" >/dev/null 2>&1; then
      echo "Namespace '$ns' created (retention $NAMESPACE_RETENTION)"
      return 0
    fi

    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
      echo "Failed to create namespace '$ns' after $MAX_ATTEMPTS attempts"
      return 1
    fi

    echo "Namespace '$ns' not ready yet, waiting... (attempt $attempt/$MAX_ATTEMPTS)"
    attempt=$((attempt + 1))
    sleep "$SLEEP_SECONDS"
  done
}

for ns in $NAMESPACES; do
  create_namespace "$ns"
done

echo 'All namespaces are ready'
