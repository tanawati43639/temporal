#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# สร้าง Kubernetes Secret ทั้งหมดที่ stack mTLS ต้องใช้ ใน namespace `temporal`:
#
#   temporal-mtls-pki   (generic)            — ca/cluster/frontend/client/admin + keys → mount /pki
#   temporal-ui-tls     (kubernetes.io/tls)  — client cert ให้ UI คุย frontend (tls.crt/tls.key/ca.crt)
#   temporal-server-env (generic)            — env ของ server จาก aks/server-env
#   temporal-ui-env     (generic)            — ค่าลับ OIDC จาก aks/ui-env
#
# PKI มาจากตัว gen เดิมของ compose (samples-server/compose/tls/run-mtls.sh) แล้ว
# ดึง cert "ทั้งหมด" ออกจาก docker volume temporal_mtls_pki (run-mtls คัดลอกให้ host
# แค่ ca/client/admin — cluster/frontend อยู่ใน volume เท่านั้น)
#
# ต้องมี: docker, kubectl (ชี้ context ที่ถูกต้อง), namespace `temporal` อยู่แล้ว
# ไม่ commit: aks/server-env, aks/ui-env, และไฟล์ cert ชั่วคราว
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."                      # repo root
NS=temporal
COMPOSE_DIR="samples-server/compose"
PKI_TMP="$(mktemp -d)"
trap 'rm -rf "$PKI_TMP"' EXIT

echo "─── 1/5  Generate PKI (compose/tls/run-mtls.sh) ───"
( cd "$COMPOSE_DIR" && ./tls/run-mtls.sh )

echo
echo "─── 2/5  Extract all certs from docker volume temporal_mtls_pki ───"
docker run --rm -v temporal_mtls_pki:/pki -v "$PKI_TMP:/out" alpine \
  sh -c 'cp /pki/*.pem /out/'
ls -1 "$PKI_TMP"

echo
echo "─── 3/5  Secret temporal-mtls-pki (ca/cluster/frontend/client/admin) ───"
kubectl -n "$NS" create secret generic temporal-mtls-pki \
  --from-file=ca.pem="$PKI_TMP/ca.pem" \
  --from-file=cluster.pem="$PKI_TMP/cluster.pem" \
  --from-file=cluster-key.pem="$PKI_TMP/cluster-key.pem" \
  --from-file=frontend.pem="$PKI_TMP/frontend.pem" \
  --from-file=frontend-key.pem="$PKI_TMP/frontend-key.pem" \
  --from-file=client.pem="$PKI_TMP/client.pem" \
  --from-file=client-key.pem="$PKI_TMP/client-key.pem" \
  --from-file=admin.pem="$PKI_TMP/admin.pem" \
  --from-file=admin-key.pem="$PKI_TMP/admin-key.pem" \
  --dry-run=client -o yaml | kubectl apply -f -

echo
echo "─── 4/5  Secret temporal-ui-tls (client cert ให้ UI) ───"
kubectl -n "$NS" create secret generic temporal-ui-tls \
  --type=kubernetes.io/tls \
  --from-file=tls.crt="$PKI_TMP/client.pem" \
  --from-file=tls.key="$PKI_TMP/client-key.pem" \
  --from-file=ca.crt="$PKI_TMP/ca.pem" \
  --dry-run=client -o yaml | kubectl apply -f -

echo
echo "─── 5/5  Secret temporal-server-env + temporal-ui-env (จาก env files) ───"
for f in server-env ui-env; do
  if [ ! -f "aks/$f" ]; then
    echo "  !! ไม่พบ aks/$f — คัดลอกจาก aks/$f.example แล้วเติมค่าก่อน" >&2
    exit 1
  fi
  if grep -q '__FILL_ME__' "aks/$f"; then
    echo "  !! aks/$f ยังมี __FILL_ME__ ที่ยังไม่เติม" >&2
    exit 1
  fi
done
kubectl -n "$NS" create secret generic temporal-server-env \
  --from-env-file=aks/server-env --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic temporal-ui-env \
  --from-env-file=aks/ui-env --dry-run=client -o yaml | kubectl apply -f -

echo
echo "เสร็จ — secret ใน namespace $NS:"
kubectl -n "$NS" get secret temporal-mtls-pki temporal-ui-tls temporal-server-env temporal-ui-env
