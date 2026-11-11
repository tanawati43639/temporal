# Credential Lock — Semaphore Pattern for Temporal

ระบบ lock credential สำหรับ Temporal workflow ใช้ Semaphore pattern
ป้องกันไม่ให้หลาย workflow ใช้ credential เดียวกันพร้อมกัน

แนวคิดเทียบเท่า **Blue Prism Acquire Lock / Release Lock**

---

## สถาปัตยกรรม

```
┌─────────────┐   signal:acquire   ┌──────────────────────────┐
│  Workflow A  │ ─────────────────→ │  CredentialLockWorkflow   │
│  (ต้องการ    │                    │  ID: cred-lock-SAP_01     │
│   credential)│ ←───────────────── │                           │
│              │  signal:granted    │  state:                   │
└─────────────┘                    │  ├─ holder: workflow ที่    │
                                   │  │  ถือ lock อยู่          │
┌─────────────┐   signal:acquire   │  ├─ queue: คิวรอ          │
│  Workflow B  │ ─────────────────→ │  └─ stats: จำนวน         │
│  (รอคิว)     │                    │     acquire/release       │
└─────────────┘                    └──────────────────────────┘
```

### Flow ทีละขั้นตอน

```
เวลา   Workflow A              Lock Manager               Workflow B
─────  ──────────────         ──────────────              ──────────────
 t1    signal: acquire  ──→   holder=A, queue=[]
       ← signal: granted     (ได้ credential คืนมา)

 t2    ใช้ credential ทำงาน
       - login
       - process data
                                                          signal: acquire ──→
 t3                           holder=A, queue=[B]         ⏳ รอ...

 t4    signal: release  ──→   holder=B, queue=[]
                              ← signal: granted  ────→   ได้ credential!
                                                          ใช้งาน...
 t5                                                       signal: release ──→
                              holder=None, queue=[]
```

---

## การใช้งาน

### 1. ตั้งค่า Credential (Environment Variables)

Credential ถูกเก็บเป็น env var ตาม pattern `CRED_{NAME}_USER` / `CRED_{NAME}_PASS`:

```bash
export CRED_SAP_01_USER="sap_bot_user"
export CRED_SAP_01_PASS="s3cret"
export CRED_ORACLE_DB_USER="db_reader"
export CRED_ORACLE_DB_PASS="p@ssw0rd"
```

> **หมายเหตุ:** ใน production ควรเปลี่ยนไปใช้ secret manager (Azure Key Vault,
> AWS Secrets Manager, HashiCorp Vault) โดยแก้ที่ `activities/credential_store.py`

### 2. เริ่ม Worker

```bash
uv run python -m automation.processes.credential_lock.workers.worker
```

### 3. สร้าง Lock Manager สำหรับ Credential

```bash
# สร้าง lock manager สำหรับ SAP_01 (timeout 5 นาที = default)
uv run python -m automation.processes.credential_lock.clients.starter \
    --credential SAP_01

# กำหนด timeout เอง (10 นาที)
uv run python -m automation.processes.credential_lock.clients.starter \
    --credential SAP_01 --timeout 600
```

Lock manager จะรันค้างอยู่ตลอด (long-running workflow)
โดย 1 credential = 1 lock manager workflow

### 4. ใช้งานผ่าน CLI

```bash
# ดูสถานะ lock
uv run python -m automation.processes.credential_lock.clients.control \
    --credential SAP_01 --action status

# ขอ lock (ระบุ workflow ID ของผู้ขอ)
uv run python -m automation.processes.credential_lock.clients.control \
    --credential SAP_01 --action acquire --requester my-workflow-123

# ปล่อย lock
uv run python -m automation.processes.credential_lock.clients.control \
    --credential SAP_01 --action release --requester my-workflow-123

# ปิด lock manager
uv run python -m automation.processes.credential_lock.clients.control \
    --credential SAP_01 --action shutdown
```

### 5. ใช้งานจาก Workflow อื่น (programmatic)

```python
from temporalio import workflow

@workflow.defn
class MyRPAWorkflow:

    def __init__(self):
        self._credential = None

    @workflow.signal
    async def credential_granted(self, grant):
        """Lock manager จะ signal กลับมาเมื่อได้ lock"""
        self._credential = grant

    @workflow.run
    async def run(self, input):
        my_id = workflow.info().workflow_id
        lock_handle = workflow.get_external_workflow_handle("cred-lock-SAP_01")

        # 1. Acquire Lock
        await lock_handle.signal("acquire", AcquireRequest(
            requester_workflow_id=my_id,
            credential_name="SAP_01",
        ))

        # 2. รอจนได้ credential กลับมา
        await workflow.wait_condition(lambda: self._credential is not None)

        # 3. ใช้ credential ทำงาน
        await workflow.execute_activity(
            login_sap,
            self._credential,
            start_to_close_timeout=timedelta(minutes=5),
        )

        # 4. Release Lock
        await lock_handle.signal("release", ReleaseRequest(
            requester_workflow_id=my_id,
        ))
```

---

## คุณสมบัติ

| Feature | รายละเอียด |
|---------|-----------|
| **FIFO Queue** | คิวรอตามลำดับ ใครมาก่อนได้ก่อน |
| **Auto-release** | ถ้า holder ไม่ release ภายใน timeout → ปล่อย lock อัตโนมัติ |
| **Crash recovery** | Temporal เก็บ state ใน history — worker crash แล้ว restart ได้เลย |
| **Continue-as-new** | History ไม่บวม ต่อให้รันเป็นเดือน |
| **Query** | ดู holder + queue + stats ได้ realtime |
| **Shutdown** | ปิด lock manager ได้อย่าง graceful |

---

## เทียบกับ Blue Prism

| Blue Prism | Temporal Credential Lock |
|------------|------------------------|
| `Acquire Lock("SAP_01")` | `signal: acquire(requester_wf_id)` |
| `Release Lock("SAP_01")` | `signal: release(requester_wf_id)` |
| `Get Credential("SAP_01")` | `activity: get_credential` (รวมอยู่ใน acquire flow) |
| Lock ค้างเมื่อ bot crash | Auto-release เมื่อ timeout |
| ดู lock ผ่าน Control Room | `query: status()` หรือ Temporal UI |

---

## ไฟล์ในโมดูลนี้

```
credential_lock/
├── models/credential.py          # dataclasses: AcquireRequest, LockStatus, CredentialInfo
├── configs/queues.py             # task queue, timeout, concurrency settings
├── workflows/lock_manager.py     # CredentialLockWorkflow (semaphore core)
├── activities/credential_store.py # get_credential, notify_granted
├── clients/starter.py            # CLI: สร้าง lock manager
├── clients/control.py            # CLI: acquire/release/status/shutdown
├── workers/worker.py             # Temporal worker
├── register.py                   # REST API auto-discovery
└── README.md                     # เอกสารนี้
```
