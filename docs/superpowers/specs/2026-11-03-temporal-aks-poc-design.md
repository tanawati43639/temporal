# Temporal บน AKS (POC) — Design Spec

วันที่: 2026-11-03
สถานะ: รออนุมัติ
ผู้เขียน: tanawati43639 + Claude

---

## 1. เป้าหมาย (Intent)

ยก Temporal Server ขึ้นรันบน AKS ที่มีอยู่แล้ว เป็น **POC** เพื่อยืนยันว่า
Temporal รันบน Kubernetes ฝั่ง Azure ได้ โดยใช้ **PostgreSQL ที่รันเป็น pod
ในคลัสเตอร์เดียวกัน** เป็น persistence ไม่พึ่ง managed Azure Database

**นิยามความสำเร็จ (Definition of Done):**

1. ทุก pod ใน namespace `temporal` อยู่สถานะ `Running` และ schema job เป็น `Completed`
2. namespace `default` ของ Temporal ถูกสร้างอัตโนมัติ
3. เปิด Temporal Web UI ผ่าน `kubectl port-forward` แล้วเห็นหน้า namespace `default` ได้

เมื่อถึง 3 ข้อนี้ = จบ POC รอบนี้

---

## 2. ขอบเขต (Scope)

### อยู่ในขอบเขตรอบนี้
- Deploy Temporal Server (frontend / history / matching / internal-frontend), admintools, และ Web UI ลง namespace `temporal`
- Deploy PostgreSQL เป็น pod ในคลัสเตอร์ (Deployment + PVC + Service + Secret) ใช้เป็นทั้ง `default` store และ `visibility` store (SQL visibility — ไม่ใช้ Elasticsearch)
- ให้ Helm chart สร้าง database และจัดการ schema (setup/update) อัตโนมัติ
- ให้ Helm chart สร้าง namespace `default` อัตโนมัติ
- เอกสารขั้นตอนสั่งแบบ copy-paste (`aks/README.md`)

### อยู่นอกขอบเขต (เก็บไว้รอบถัดไป)
- การ deploy **worker / workflow** ของโปรเจกต์ (โฟกัส server ก่อนตามที่ตกลง)
- TLS / mTLS บน frontend และ internode
- Authorizer / OIDC / namespace RBAC (ดู [[project-temporal-rbac]])
- Managed Azure Database for PostgreSQL
- HA / multi-replica / numHistoryShards tuning
- Public ingress / LoadBalancer (เข้าถึงผ่าน port-forward เท่านั้น)
- Prometheus / Grafana / ServiceMonitor
- Autoscaling (HPA/KEDA), backup/restore, disaster recovery

---

## 3. ข้อเท็จจริงของ Helm chart (verified 2026-11-03)

อ้างอิง repo `temporalio/helm-charts`, chart `temporal` **version 1.7.0**,
appVersion (Temporal server) **1.32.0**.

- **ไม่มี subchart ฐานข้อมูลแล้ว** — เวอร์ชันนี้ไม่มี `cassandra.enabled` /
  `postgresql.enabled` / `elasticsearch.enabled` / `prometheus` / `grafana`
  แบบ bundled อีกต่อไป ผู้ใช้ต้องจัดหา datastore เอง ไฟล์ตัวอย่าง
  `charts/temporal/values/values.postgresql.yaml` สมมติเป็น **external** Postgres
  (ให้กรอก host/user/password เอง) → **เราจึงต้อง deploy Postgres เองในคลัสเตอร์**
- chart รองรับ SQL datastore ผ่าน `server.config.persistence.datastores.<name>.sql`
  โดยมี field พิเศษของ Helm:
  - `createDatabase: true` → chart สั่งสร้าง database ให้ (ใช้ `defaultDb` เป็น admin DB)
  - `manageSchema: true` → chart รัน schema setup/update job ให้อัตโนมัติ
  - `existingSecret` / `secretKey` → อ่าน password จาก Kubernetes Secret ที่เตรียมไว้
- schema job ใช้ Helm hooks (`schema.useHelmHooks: true`) → รันก่อน server pod ขึ้น
- `server.config.persistence.namespaces.create: true` + รายการ `namespace`
  → สร้าง namespace `default` ให้ผ่าน Helm hook (ใช้ยืนยัน DoD ข้อ 2)
- `web.enabled: true` และ `admintools.enabled: true` เป็น default อยู่แล้ว
- `pluginName: postgres12` คือ SQL driver ของ Postgres

---

## 4. สถาปัตยกรรม

```
namespace: temporal
┌─────────────────────────────────────────────────────────┐
│                                                           │
│  Secret: temporal-db-password  (key: password)           │
│     │ อ้างโดยทั้ง Postgres pod และ Temporal chart         │
│     ▼                                                     │
│  ┌──────────────────────┐                                │
│  │ PostgreSQL (pod)      │◄── PVC (PersistentVolume, AKS) │
│  │ Service:             │    เก็บ state ถาวร              │
│  │  temporal-postgres   │    DB: temporal,                │
│  │  :5432               │        temporal_visibility      │
│  └──────────┬───────────┘    (chart สร้างให้)             │
│             │ sql (postgres12)                            │
│             ▼                                             │
│  ┌──────────────────────────────────────────┐            │
│  │ Temporal Server (Helm chart)              │            │
│  │  frontend / history / matching /          │            │
│  │  internal-frontend  (replicaCount=1)      │            │
│  │  Service: temporal-frontend :7233         │            │
│  └──────────┬────────────────────┬───────────┘            │
│             │                    │                        │
│        ┌────▼─────┐        ┌─────▼───────┐                │
│        │ admintools│        │ Web UI      │                │
│        │ (CLI pod) │        │ Service:    │                │
│        └───────────┘        │ temporal-web│                │
│                             │ :8080       │                │
│                             └─────────────┘                │
└─────────────────────────────────────────────────────────┘
       ▲                              ▲
       │ port-forward :7233           │ port-forward :8080
   (client รอบหน้า)              นักพัฒนาเปิด UI ในเบราว์เซอร์
```

---

## 5. Components

### 5.1 PostgreSQL ในคลัสเตอร์ (เราเขียน manifest เอง)
- **หน้าที่:** เป็น SQL datastore ของทั้ง default และ visibility store
- **รูปแบบ:** manifest เดียว `aks/postgres.yaml` ประกอบด้วย Service + PVC +
  Deployment (image `postgres:16-alpine` pin tag) + อ้าง Secret สำหรับ password
- **ตัวเลือกที่พิจารณา:** Bitnami postgresql chart / CloudNativePG operator —
  ตัดออกเพราะ POC ต้องการความโปร่งใสและไม่เพิ่ม dependency ภายนอก; manifest
  ที่เราคุมเองอ่านง่ายและแก้ง่ายกว่า
- **superuser:** ใช้ `postgres` (default) เพื่อให้ chart `createDatabase` สร้าง
  `temporal` และ `temporal_visibility` ได้โดยไม่ชนกับ db ที่ image สร้างให้ตอน init
- **ข้อจำกัดที่ยอมรับ:** replica เดียว, ไม่มี backup/HA — เหมาะกับ POC เท่านั้น
  (ถ้า pod ตายและ PVC ยังอยู่ data ไม่หาย; ถ้า PVC หาย = งานหาย)

### 5.2 Temporal Server (ผ่าน Helm chart)
- **หน้าที่:** core durable execution engine
- **รูปแบบ:** `helm install` chart `temporal/temporal` (pin version 1.7.0)
  ด้วยไฟล์ override `aks/temporal-values.yaml`
- **ค่าหลักใน values:**
  - `server.replicaCount: 1` (ทุก role รันแบบ single replica)
  - `server.config.persistence` → default + visibility ชี้ `sql` ที่
    `connectAddr: temporal-postgres.temporal.svc:5432`, `pluginName: postgres12`,
    `createDatabase: true`, `manageSchema: true`, `existingSecret: temporal-db-password`
  - `server.config.persistence.namespaces.create: true` + `namespace: [{name: default, retention: 3d}]`
  - `web.enabled: true`, `admintools.enabled: true`
  - ปิดของที่ไม่ใช้: `server.metrics.serviceMonitor.enabled: false`
  - `resources` ตั้งแบบประหยัด (requests เล็กพอให้รันบน node ทั่วไป)
  - `numHistoryShards: 512` (ค่า default; **เปลี่ยนภายหลังไม่ได้** — ยอมรับ default ไว้)

### 5.3 Web UI
- มากับ chart (`web.enabled`) Service ชื่อประมาณ `temporal-web` :8080
  (ยืนยันชื่อจริงด้วย `kubectl get svc -n temporal` ตอน deploy)
- เข้าถึงผ่าน `kubectl port-forward` เท่านั้น ไม่เปิด public

### 5.4 เอกสาร `aks/README.md`
- ขั้นตอน copy-paste: สร้าง namespace → สร้าง Secret → apply `postgres.yaml` →
  `helm repo add/update` → `helm install` → `kubectl get pods -w` → `port-forward` → เปิด UI
- คำสั่ง uninstall/cleanup สำหรับรื้อ POC

---

## 6. Data flow / ลำดับการ deploy

1. สร้าง namespace `temporal`
2. สร้าง Secret `temporal-db-password` (key `password`) — **ไม่ commit ค่า
   plaintext**; README ใช้ `kubectl create secret generic`
3. `kubectl apply -f aks/postgres.yaml` → Postgres pod + PVC + Service ขึ้น
4. รอ Postgres `Running` แล้ว `helm install temporal ... -f aks/temporal-values.yaml`
   - Helm hook: schema job (createDatabase + setup/update schema) รันก่อน
   - server pods (frontend/history/matching/internal-frontend) ขึ้น
   - Helm hook: namespace job สร้าง `default`
   - web + admintools ขึ้น
5. `port-forward svc/temporal-web 8080` → เปิด UI ยืนยัน

---

## 7. Error handling / กรณีพลาดที่คาดไว้

| อาการ | สาเหตุที่น่าจะเป็น | ทางแก้ |
|---|---|---|
| schema job `Error` / server pod `CrashLoopBackOff` ต่อ DB ไม่ได้ | Postgres ยังไม่พร้อม หรือ Secret/connectAddr ผิด | ตรวจ `kubectl logs job/...`, ยืนยัน Service DNS + password ตรงกัน |
| `createDatabase` ล้มเพราะ db ชนกับที่ image init สร้าง | ตั้ง `POSTGRES_USER` ให้ image ไปสร้าง db ชื่อเดียวกับที่ chart จะสร้าง | ใช้ superuser `postgres` + `defaultDb: postgres` ไม่ตั้ง `POSTGRES_DB` ให้ตรงชื่อ |
| PVC `Pending` | storageClass ของ AKS ไม่ตรง | ปล่อยใช้ default storageClass ของ AKS หรือระบุให้ตรง |
| UI ขึ้นแต่ว่าง ไม่มี namespace | namespace job ยังไม่จบ / `namespaces.create` ไม่ได้เปิด | ตรวจ `kubectl get jobs -n temporal` รอ namespace job `Completed` |
| helm install timeout | schema setup ใช้เวลานาน | `--timeout 15m` และดู job logs |

---

## 8. การทดสอบ / ยืนยัน (Verification)

ไม่มี unit test (เป็นงาน infra) — ยืนยันด้วยการสังเกต state จริง:

1. `kubectl get pods -n temporal` → ทุก pod `Running`, schema job `Completed`
2. `kubectl get jobs -n temporal` → namespace job `Completed`
3. `kubectl exec` เข้า admintools แล้ว `temporal operator namespace list` → เห็น `default`
4. `kubectl port-forward svc/temporal-web 8080:8080` → เปิด `http://localhost:8080`
   เห็น namespace `default` ในหน้า UI → **ผ่าน**

---

## 9. ไฟล์ที่จะสร้าง (ของใหม่ทั้งหมด ไม่แตะโค้ด Python เดิม)

- `aks/postgres.yaml` — Service + PVC + Deployment ของ PostgreSQL ในคลัสเตอร์
- `aks/temporal-values.yaml` — Helm values override สำหรับ chart `temporal/temporal`
- `aks/README.md` — ขั้นตอน deploy/verify/cleanup

> หมายเหตุ: `aks/worker-deployment.yaml`, `aks/worker.py`, `aks/Dockerfile` ฯลฯ
> ที่มีอยู่แล้ว **ไม่แตะในรอบนี้** (เป็นของรอบ worker)

---

## 10. ความเสี่ยง / ข้อควรรู้

- **numHistoryShards เปลี่ยนภายหลังไม่ได้** — ใช้ default 512; ถ้าจะไป production
  ด้วย data ชุดนี้ต้องตัดสินใจเรื่องนี้ตั้งแต่ตอนนี้ (POC นี้ยอมรับ default)
- **Postgres ใน pod ไม่มี HA/backup** — ตั้งใจให้เป็นแบบนี้สำหรับ POC; production
  ควรย้ายไป Azure Database for PostgreSQL (เปลี่ยนแค่ `connectAddr`/secret ใน values)
- **password เก็บใน Secret ที่สร้างด้วยมือ** ไม่ commit ลง git
- chart/appVersion ถูก pin (1.7.0 / 1.32.0) เพื่อให้ reproducible
