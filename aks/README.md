# Temporal บน AKS — POC (server-only)

Deploy Temporal Server + Web UI พร้อม PostgreSQL ในคลัสเตอร์ ลง namespace
`temporal` บน AKS ที่มีอยู่แล้ว

- Chart: `temporal/temporal` **1.7.0** (Temporal server **1.32.0**, UI 2.54.1)
- Persistence: PostgreSQL เป็น pod ในคลัสเตอร์ (`postgres.yaml`) ใช้เป็นทั้ง
  default และ visibility store
- Scope รอบนี้: **เฉพาะ server** — worker/workflow ยังไม่ deploy
- Design เต็ม: [`docs/superpowers/specs/2026-11-03-temporal-aks-poc-design.md`](../docs/superpowers/specs/2026-11-03-temporal-aks-poc-design.md)

---

## ก่อนเริ่ม

ยืนยันว่าชี้ไปที่ AKS cluster ที่ถูกต้อง:

```bash
kubectl config current-context     # ต้องเป็นคลัสเตอร์ AKS ของคุณ
kubectl get nodes                  # เห็น node ของ AKS
helm version                       # มี helm v3
```

---

## ขั้นตอน deploy

### 1. สร้าง namespace

```bash
kubectl create namespace temporal
```

### 2. สร้าง Secret password ของ Postgres

ไม่เก็บ password ลง git — สร้างเป็น Secret โดยตรง (เปลี่ยน `CHANGE_ME_strong_pw`
เป็นรหัสของคุณ):

```bash
kubectl create secret generic temporal-db-password \
  --namespace temporal \
  --from-literal=password='CHANGE_ME_strong_pw'
```

> Secret นี้ถูกอ้างทั้งโดย Postgres pod (`POSTGRES_PASSWORD`) และ Temporal chart
> (`existingSecret`) ค่าต้องเป็นตัวเดียวกัน

### 3. Deploy PostgreSQL

```bash
kubectl apply -f aks/postgres.yaml
kubectl -n temporal rollout status deploy/temporal-postgres   # รอจน available
```

### 4. Deploy Temporal server ผ่าน Helm

```bash
helm repo add temporal https://go.temporal.io/helm-charts
helm repo update

helm install temporal temporal/temporal \
  --namespace temporal \
  --version 1.7.0 \
  -f aks/temporal-values.yaml \
  --timeout 15m
```

Helm hooks จะ (1) รัน schema setup/update job, แล้ว (2) สร้าง namespace `default`
ให้เองหลัง frontend พร้อม

---

## ยืนยันว่าใช้ได้ (Definition of Done)

```bash
# 1) ทุก pod Running, schema job Completed
kubectl -n temporal get pods

# 2) namespace job Completed
kubectl -n temporal get jobs

# 3) เห็น namespace default ผ่าน admintools
kubectl -n temporal exec deploy/temporal-admintools -- \
  temporal operator namespace list

# 4) เปิด Web UI
kubectl -n temporal port-forward svc/temporal-web 8080:8080
# → เปิดเบราว์เซอร์ http://localhost:8080 เห็นหน้า namespace default = ผ่าน
```

(ถ้าจะต่อ client/worker จากเครื่อง dev: `kubectl -n temporal port-forward
svc/temporal-frontend 7233:7233` แล้วตั้ง `TEMPORAL_ADDRESS=localhost:7233`)

---

## แก้ปัญหาที่พบบ่อย

| อาการ | ตรวจ / แก้ |
|---|---|
| server pod `CrashLoopBackOff` ต่อ DB ไม่ได้ | `kubectl -n temporal logs deploy/temporal-frontend` — เช็กว่า Postgres `Running` และ password ใน Secret ตรงกับที่ Postgres ใช้ |
| schema job `Error` | `kubectl -n temporal logs job/<schema-job>` — มักเกิดตอน Postgres ยังไม่พร้อม ลอง `helm uninstall` แล้วติดตั้งใหม่หลัง Postgres ready |
| PVC `Pending` | `kubectl -n temporal get pvc` — คลัสเตอร์อาจไม่มี default StorageClass ให้ใส่ `storageClassName` ใน `postgres.yaml` |
| UI ว่าง ไม่มี namespace | `kubectl -n temporal get jobs` รอ namespace job `Completed` |

---

## รื้อ POC (cleanup)

```bash
helm uninstall temporal -n temporal
kubectl delete -f aks/postgres.yaml
kubectl delete secret temporal-db-password -n temporal
# ลบ PVC ด้วยถ้าต้องการลบ data ถาวร:
kubectl delete pvc temporal-postgres-data -n temporal
# หรือลบทั้ง namespace:
kubectl delete namespace temporal
```
