# Temporal บน AKS — multi-role + mTLS + Azure AD RBAC (self-contained)

Bundle แยกตัวสำหรับ deploy Temporal แบบ 5 service + mTLS ทุก hop + Azure AD RBAC
ลง AKS โดยต่อยอด Helm chart `temporal/temporal` 1.7.0 (พอร์ตจาก
`samples-server/compose/docker-compose-mtls.yaml`)

> **หลักการ:** `temporal-authz-server` โหลด config จาก **env ล้วน**
> (`config.Load(config.WithEmbedded)`) ไม่อ่าน config template ของ chart →
> เราใช้ chart ปั๊ม Deployment/Service/Job/UI แล้วฉีด config ทาง env + Secret
> (`temporal-server-env`, `temporal-mtls-pki`)

## โครงไฟล์

```
aks_deployment/
  authz/                     # Go source + Dockerfile (build ขั้นเดียว) + entrypoint.sh
  tls/                       # ตัว gen PKI (cfssl): run-mtls.sh + Dockerfile.mtls
  postgres.yaml              # Postgres in-cluster (default + visibility store)
  temporal-values.yaml       # values พื้นฐาน (persistence, namespaces ของ schema job)
  temporal-values.mtls.yaml  # overlay: image authz, env secret, /pki, TLS UI, ปิด namespace job chart
  server-env.example         # env ของ server (คัดลอก → server-env → เติมค่า)
  ui-env.example             # ค่าลับ OIDC (คัดลอก → ui-env → เติมค่า)
  make-secrets.sh            # gen PKI + สร้าง 4 Secret
  namespace-job.yaml         # Job สร้าง default/dev/uat/prod ด้วย admin cert (mTLS)
```

## ต้องมีก่อน

`docker` (+ buildx), `az` (ล็อกอิน ACR ได้), `kubectl` ชี้ context `aks-temporal-woker`, `helm`

> ⚠️ คลัสเตอร์ `aks-temporal-woker` **คิดเงินตลอดที่รัน** — `az aks stop -n aks-temporal-woker -g rg-temporal` เมื่อไม่ใช้

---

## ขั้นตอน (รันจากในโฟลเดอร์ `aks_deployment`)

```bash
cd /Users/bestder/Coding/Python/Demo_Temporal/aks_deployment
```

### 1. Build + push image authz (ขั้นเดียว)

```bash
az acr login -n acrtemporal25243
docker build --platform linux/amd64 \
  --build-arg TEMPORAL_VERSION=1.31.0 \
  -t acrtemporal25243.azurecr.io/temporal-authz-aks:v1 \
  authz
docker push acrtemporal25243.azurecr.io/temporal-authz-aks:v1
```

> บน Apple Silicon ถ้าติดเรื่อง platform ใช้
> `docker buildx build --platform linux/amd64 ... --push authz` (build+push ทีเดียว)

### 2. พื้นฐานคลัสเตอร์ (ถ้ายังไม่มี)

```bash
kubectl create namespace temporal

# password ของ Postgres (เปลี่ยน CHANGE_ME) — ถูกอ้างทั้ง Postgres pod และ server-env
kubectl -n temporal create secret generic temporal-db-password \
  --from-literal=password='CHANGE_ME_strong_pw'

kubectl apply -f postgres.yaml
kubectl -n temporal rollout status deploy/temporal-postgres
```

### 3. เตรียม env + สร้าง Secret

```bash
cp server-env.example server-env
cp ui-env.example     ui-env
# เติม __FILL_ME__:
#   server-env : POSTGRES_PWD (= ค่าใน temporal-db-password), TEMPORAL_JWT_KEY_SOURCE1 (JWKS URI)
#   ui-env     : TEMPORAL_AUTH_PROVIDER_URL / CLIENT_ID / CLIENT_SECRET

./make-secrets.sh
```

### 4. ติดตั้ง chart ด้วย values สองไฟล์

```bash
helm repo add temporal https://go.temporal.io/helm-charts && helm repo update

helm upgrade --install temporal temporal/temporal \
  --namespace temporal --version 1.7.0 \
  -f temporal-values.yaml \
  -f temporal-values.mtls.yaml \
  --timeout 15m
```

### 5. สร้าง namespace (ผ่าน mTLS ด้วย admin cert)

```bash
kubectl apply -f namespace-job.yaml
kubectl -n temporal logs -f job/temporal-create-namespace
```

---

## ยืนยัน

```bash
kubectl -n temporal get pods
kubectl -n temporal exec deploy/temporal-admintools -- temporal operator cluster health
kubectl -n temporal exec deploy/temporal-admintools -- temporal operator namespace list
kubectl -n temporal port-forward svc/temporal-web 8080:8080   # → http://localhost:8080 (ล็อกอิน Azure AD)
```

---

## หมายเหตุ / ยังไม่ครอบคลุม

- **SDK worker** ยังไม่อยู่ใน bundle นี้ และต้องเติม client cert (`client.pem`) เมื่อ frontend บังคับ mTLS
- `NUM_HISTORY_SHARDS=512` ต้องตรงกับ `temporal-values.yaml` และเปลี่ยนไม่ได้หลัง deploy ครั้งแรก
- Postgres เป็น pod เดียว (ไม่มี HA/backup) — production ย้ายไป Azure Database for PostgreSQL แล้วแก้ `POSTGRES_SEEDS` + password
- PKI self-signed อายุ 5 ปี — หมุน cert = รัน `make-secrets.sh` ใหม่ แล้ว `kubectl -n temporal rollout restart deploy`

## Cleanup

```bash
helm uninstall temporal -n temporal
kubectl delete -f postgres.yaml
kubectl -n temporal delete secret temporal-db-password temporal-mtls-pki temporal-ui-tls temporal-server-env temporal-ui-env
# หรือ: kubectl delete namespace temporal
az aks stop -n aks-temporal-woker -g rg-temporal     # หยุดคิดเงิน
```
