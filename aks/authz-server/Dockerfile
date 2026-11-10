# ──────────────────────────────────────────────────────────────────
# ชั้นบาง ๆ บน image authz เดิม (temporal-authz:dev ที่ build จาก
# samples-server/compose/authz-server) — เปลี่ยนแค่ ENTRYPOINT ให้รัน
# temporal-authz-server + ตั้ง broadcast address เอง เพื่อให้ใช้กับ Helm chart ได้
# (chart ไม่มีช่อง override command — ดู aks-entrypoint.sh)
#
# Build 2 ขั้น (ดู aks/README.mtls.md):
#   1) docker build -t temporal-authz:dev \
#        --build-arg TEMPORAL_VERSION=1.31.0 \
#        samples-server/compose/authz-server
#   2) docker build --platform linux/amd64 \
#        -t acrtemporal25243.azurecr.io/temporal-authz-aks:v1 \
#        aks/authz-server
# ──────────────────────────────────────────────────────────────────
ARG BASE_IMAGE=temporal-authz:dev
FROM ${BASE_IMAGE}

COPY --chmod=0755 entrypoint.sh /usr/local/bin/aks-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/aks-entrypoint.sh"]
