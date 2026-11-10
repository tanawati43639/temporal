# Temporal บน AKS — multi-role + mTLS + Azure AD RBAC

พอร์ต `samples-server/compose/docker-compose-mtls.yaml` ขึ้น AKS โดย **ต่อยอด**
Helm chart `temporal/temporal` 1.7.0 ที่ POC เดิมใช้ (ดู [`README.md`](README.md))

ส่วนนี้เพิ่ม 3 ชั้นที่ POC server-only ยังไม่มี:

1. **authz-server image** — binary ที่ฝัง Azure AD claim mapper + authorizer (RBAC จาก claim `roles`)
2. **mTLS** ทุก hop — internode (`cluster.pem`) + frontend external `:7233` (บังคับ client cert)
3. **Azure AD OIDC** บน UI + **JWKS** verification บน frontend

> **ทำไมไม่ตั้งค่าผ่าน chart config:** `temporal-authz-server` โหลด config จาก
> **env ล้วน** (`config.Load(config.WithEmbedded)`) ไม่อ่านไฟล์ config ของ chart
> → เราใช้ chart ปั๊ม Deployment/Service/Job/UI แล้วฉีด config ทาง env + secret
> (`temporal-server-env`, `temporal-mtls-pki`) ค่า persistence ใน `temporal-values.yaml`
> ยังใช้โดย **schema job** ของ chart (คุย Postgres ตรง ๆ ไม่ผ่าน frontend)

ไฟล์ในชุดนี้:

| ไฟล์ | หน้าที่ |
|---|---|
| `authz-server/Dockerfile` + `entrypoint.sh` | image = authz binary + entrypoint ที่ตั้ง broadcast address แล้วรัน `temporal-authz-server` |
| `temporal-values.mtls.yaml` | overlay บน `temporal-values.yaml`: ชี้ image, additionalEnvSecret, mount `/pki`, TLS บน UI, ปิด namespace job ของ chart |
| `server-env.example` / `ui-env.example` | template env (คัดลอกเป็น `server-env`/`ui-env` แล้วเติมค่า, ไม่ commit) |
| `make-secrets.sh` | gen PKI + สร้าง 4 Secret |
| `namespace-job.yaml` | Job สร้าง `default/dev/uat/prod` ด้วย admin cert |

---

## ก่อนเริ่ม

ต้องมี POC พื้นฐานอยู่ก่อน (namespace `temporal`, Secret `temporal-db-password`,
Postgres pod `Running`) — ทำตาม [`README.md`](README.md) ข้อ 1-3 ให้เสร็จก่อน
ถ้ายังไม่ได้ติดตั้ง chart ก็ข้ามข้อ 4 ของไฟล์นั้นมาทำ **ข้อ 3 ของไฟล์นี้แทน**

ต้องมี: `docker` (+ buildx), `az` (ล็อกอิน ACR ได้), `kubectl` ชี้ context `aks-temporal-woker`, `helm`

> ⚠️ คลัสเตอร์ `aks-temporal-woker` **คิดเงินตลอดเวลาที่รัน** — ปิดเมื่อไม่ใช้ (ดูหัวข้อ cleanup)

---

## ขั้นตอน deploy

### 1. Build + push image authz ขึ้น ACR

```bash
cd /Users/bestder/Coding/Python/Demo_Temporal

# 1a) base authz image (จาก compose) — ต้องตรง TEMPORAL_VERSION กับ go.mod (1.31.0)
#     --platform linux/amd64 สำคัญ: node AKS เป็น amd64 และชั้น 1b FROM image นี้
docker build --platform linux/amd64 -t temporal-authz:dev \
  --build-arg TEMPORAL_VERSION=1.31.0 \
  samples-server/compose/authz-server

# 1b) ชั้น entrypoint สำหรับ AKS
az acr login -n acrtemporal25243
docker build --platform linux/amd64 \
  -t acrtemporal25243.azurecr.io/temporal-authz-aks:v1 \
  aks/authz-server
docker push acrtemporal25243.azurecr.io/temporal-authz-aks:v1
```

> บน Apple Silicon ถ้า step 1b ขึ้น error เรื่อง platform ให้ใช้
> `docker buildx build --platform linux/amd64 ... --push` แทน (build + push ทีเดียว)

### 2. เตรียม env + สร้าง Secret ทั้งหมด

```bash
cp aks/server-env.example aks/server-env
cp aks/ui-env.example     aks/ui-env
# เติมค่า __FILL_ME__:
#   server-env : POSTGRES_PWD (= ค่าใน temporal-db-password), TEMPORAL_JWT_KEY_SOURCE1 (JWKS URI)
#   ui-env     : TEMPORAL_AUTH_PROVIDER_URL / CLIENT_ID / CLIENT_SECRET

./aks/make-secrets.sh
# สร้าง: temporal-mtls-pki, temporal-ui-tls, temporal-server-env, temporal-ui-env
```

### 3. ติดตั้ง/อัปเกรด chart ด้วย values สองไฟล์

```bash
helm repo add temporal https://go.temporal.io/helm-charts && helm repo update

helm upgrade --install temporal temporal/temporal \
  --namespace temporal \
  --version 1.7.0 \
  -f aks/temporal-values.yaml \
  -f aks/temporal-values.mtls.yaml \
  --timeout 15m
```

### 4. สร้าง namespace (ผ่าน mTLS ด้วย admin cert)

```bash
kubectl apply -f aks/namespace-job.yaml
kubectl -n temporal logs -f job/temporal-create-namespace
```

---

## ยืนยันว่าใช้ได้

```bash
# ทุก server pod (frontend/internal-frontend/history/matching/worker) Running
kubectl -n temporal get pods

# cluster health ผ่าน mTLS (admintools มี admin cert ติดมาแล้ว)
kubectl -n temporal exec deploy/temporal-admintools -- temporal operator cluster health

# เห็น namespace ครบ
kubectl -n temporal exec deploy/temporal-admintools -- temporal operator namespace list

# UI + Azure AD login (callback คง localhost:8080 ตาม app registration เดิม)
kubectl -n temporal port-forward svc/temporal-web 8080:8080
# → http://localhost:8080 ควร redirect ไปล็อกอิน Azure AD ก่อนเข้าถึงหน้า UI
```

---

## หมายเหตุ / ยังไม่ครอบคลุม

- **SDK worker** (`worker-deployment.yaml`) ตอนนี้ต่อ frontend แบบ **ไม่มี TLS** —
  เมื่อ frontend บังคับ mTLS แล้ว worker ต้องแนบ client cert (`client.pem`) + token
  หรือ cert ที่ claim mapper รับ ยังไม่ได้แก้ในชุดนี้ (เป็น step ถัดไป)
- **numHistoryShards = 512** ต้องตรงกันระหว่าง `NUM_HISTORY_SHARDS` ใน `server-env`
  กับ `temporal-values.yaml` และ **เปลี่ยนไม่ได้** หลัง deploy ครั้งแรก
- Postgres ยังเป็น in-cluster pod เดียว (ไม่มี HA/backup) — production ย้ายไป
  Azure Database for PostgreSQL แล้วแก้ `connectAddr`/`POSTGRES_SEEDS` + password
- PKI เป็น self-signed อายุ 5 ปี หมุน cert = รัน `make-secrets.sh` ใหม่ (ลบ/สร้าง secret
  ใหม่) แล้ว `kubectl -n temporal rollout restart deploy` ทุกตัว

---

## รื้อเฉพาะส่วน mTLS / cleanup

```bash
# กลับไป POC server-only (ไม่มี mTLS/authz):
helm upgrade temporal temporal/temporal -n temporal --version 1.7.0 \
  -f aks/temporal-values.yaml --timeout 15m

# ลบ secret ของ mTLS:
kubectl -n temporal delete secret temporal-mtls-pki temporal-ui-tls temporal-server-env temporal-ui-env

# รื้อทั้ง POC: ดู README.md หัวข้อ cleanup
```
