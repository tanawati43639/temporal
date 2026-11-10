#!/bin/sh
# ──────────────────────────────────────────────────────────────────
# Entrypoint สำหรับรัน temporal-authz-server บน Kubernetes/Helm.
#
# ทำหน้าที่เหมือน `command:` ใน docker-compose-mtls.yaml: ตั้ง BIND_ON_IP และ
# TEMPORAL_BROADCAST_ADDRESS (ที่ ringpop/membership ใช้ให้ node อื่นเรียกถึง)
# แล้ว exec ไป temporal-authz-server
#
# จำเป็นต้องทำที่ระดับ image เพราะ Helm chart temporal/temporal ไม่มีช่อง
# override container command — image เดิม (temporalio/server) จะรัน
# `temporal-server` (stock) ไม่ใช่ binary ที่ฝัง Azure AD authorizer ของเรา
#
# role (frontend/history/matching/internal-frontend/worker) มาจาก env
# TEMPORAL_SERVICES ที่ chart set ให้ต่อ Deployment อยู่แล้ว — main.go อ่านตัวนี้
# ──────────────────────────────────────────────────────────────────
set -eu

: "${BIND_ON_IP:=$(getent hosts "$(hostname)" | awk '{print $1;}')}"
export BIND_ON_IP

if [ "${BIND_ON_IP}" = "0.0.0.0" ] || [ "${BIND_ON_IP}" = "::0" ]; then
  : "${TEMPORAL_BROADCAST_ADDRESS:=$(getent hosts "$(hostname)" | awk '{print $1;}')}"
  export TEMPORAL_BROADCAST_ADDRESS
fi

exec temporal-authz-server
