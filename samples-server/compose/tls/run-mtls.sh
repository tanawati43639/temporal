#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# One-time PKI bootstrap for docker-compose-mtls.yaml.
#
# 1) Builds the cert-generator image from tls/Dockerfile.mtls.
# 2) Creates the named Docker volume `temporal_mtls_pki` and populates it
#    with CA + cluster + frontend + client certs.
# 3) Copies ca.pem, client.pem, client-key.pem out to ./.pki/ on the host
#    so you can point SDK clients outside Docker at the server.
#
# Re-run anytime to regenerate — the volume is dropped first, so any
# previously-issued client certs become invalid.
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

echo "─── 1/3  Building PKI generator image ───"
docker build -t temporal_mtls:dev -f tls/Dockerfile.mtls .

echo
echo "─── 2/3  Recreating pki volume ───"
docker volume rm -f temporal_mtls_pki >/dev/null 2>&1 || true
docker volume create temporal_mtls_pki >/dev/null

echo
echo "─── 3/3  Generating certs (CA + cluster + frontend + client) ───"
mkdir -p .pki
docker run --rm \
  -v temporal_mtls_pki:/pki \
  -v "$PWD/.pki:/pki-out" \
  temporal_mtls:dev

echo
echo "─── Done.  Host-side copies: ───"
ls -la .pki/

cat <<'DONE'

Next:
  docker compose -f docker-compose-mtls.yaml up -d
  # wait for temporal-frontend to be healthy, then:
  open http://localhost:8080

External SDK clients (outside Docker) use:
  address      = localhost:7233
  tls_cert     = ./.pki/client.pem
  tls_key      = ./.pki/client-key.pem
  tls_ca       = ./.pki/ca.pem
  server_name  = temporal-frontend
DONE
