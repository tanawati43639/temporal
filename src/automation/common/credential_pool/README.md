# Credential Pool — Shared Lock Pool for Temporal Workflows

ระบบ pool credentials กลาง ให้ทุก process ใช้ร่วมกันได้
ป้องกันไม่ให้หลาย workflow ใช้ credential เดียวกันพร้อมกัน

แนวคิดเทียบเท่า **Blue Prism Acquire Lock** แต่เป็นแบบ **pool** —
มี credential หลายตัวในกลุ่ม ระบบจะจ่ายตัวที่ว่างให้อัตโนมัติ

---

## สถาปัตยกรรม

```
                                    ┌─────────────────────────────────┐
  Workflow A                        │  CredentialPoolWorkflow          │
  ┌──────────┐   signal:acquire     │  ID: cred-pool-SAP_POOL         │
  │ acquire_ │ ───────────────────→ │                                  │
  │ credential│                     │  Pool:                           │
  │ (child)  │ ←───────────────── │  ├─ SAP_01  FREE                 │
  └──────────┘   signal:granted    │  ├─ SAP_02  🔒 Workflow B       │
       ↑                           │  └─ SAP_03  FREE                 │
       │ execute_child_workflow    │                                  │
  ┌────┴─────┐                     │  Queue: [C]                      │
  │ MyRPA    │                     └─────────────────────────────────┘
  │ Workflow │
  └──────────┘
```

### Flow ทีละขั้น

```
เวลา   Workflow A              Pool Manager                Workflow B
─────  ──────────────         ────────────────             ──────────────
 t1    acquire_credential()
       → child: acquire ──→   SAP_01 ว่าง → ให้ A
       ← CredentialInfo       pool: [🔒01, 02, 03]

 t2    ใช้ SAP_01 ทำงาน                                   acquire_credential()
                                                           → child: acquire ──→
                              SAP_02 ว่าง → ให้ B
                              pool: [🔒01, 🔒02, 03]      ← CredentialInfo

 t3    release_credential()
       signal: release  ──→   SAP_01 ว่างแล้ว
                              pool: [01, 🔒02, 03]
```

---

## การใช้งานจาก Workflow อื่น (สำคัญที่สุด)

### วิธีที่ 1: ใช้ helper functions (แนะนำ)

```python
from automation.common.credential_pool import acquire_credential, release_credential

@workflow.defn
class MyRPAWorkflow:
    @workflow.run
    async def run(self, input):
        # Acquire — ได้ credential ที่ว่างกลับมาเลย
        cred = await acquire_credential("SAP_POOL")
        # cred.name = "SAP_01", cred.username = "...", cred.password = "..."

        try:
            await workflow.execute_activity(
                login_and_process,
                cred,
                start_to_close_timeout=timedelta(minutes=10),
            )
        finally:
            # Release — คืน credential กลับ pool
            await release_credential("SAP_POOL", cred.name)
```

### วิธีที่ 2: ใช้ child workflow โดยตรง

```python
from automation.common.credential_pool.workflows.acquire import AcquireCredentialWorkflow
from automation.common.credential_pool.models.pool import AcquireFromPoolInput, ReleaseSignal

@workflow.defn
class MyRPAWorkflow:
    @workflow.run
    async def run(self, input):
        my_id = workflow.info().workflow_id

        # Acquire
        cred = await workflow.execute_child_workflow(
            AcquireCredentialWorkflow.run,
            AcquireFromPoolInput(pool_name="SAP_POOL"),
            id=f"{my_id}-acquire",
        )

        # ... ใช้งาน ...

        # Release
        pool = workflow.get_external_workflow_handle("cred-pool-SAP_POOL")
        await pool.signal("release", ReleaseSignal(
            requester_workflow_id=f"{my_id}-acquire",
            credential_name=cred.name,
        ))
```

---

## การตั้งค่าและเริ่มใช้งาน

### 1. ตั้งค่า Credential (Environment Variables)

```bash
export CRED_SAP_01_USER="bot_user_1"
export CRED_SAP_01_PASS="pass1"
export CRED_SAP_02_USER="bot_user_2"
export CRED_SAP_02_PASS="pass2"
export CRED_SAP_03_USER="bot_user_3"
export CRED_SAP_03_PASS="pass3"
```

> Production: แก้ `activities/pool_activities.py` → `fetch_credential()`
> ให้ดึงจาก Azure Key Vault / AWS Secrets Manager

### 2. เริ่ม Pool Worker

```bash
uv run python -m automation.common.credential_pool.worker
```

### 3. สร้าง Pool

```bash
uv run python -m automation.common.credential_pool start \
    --pool SAP_POOL --credentials SAP_01 SAP_02 SAP_03
```

### 4. ดูสถานะ

```bash
uv run python -m automation.common.credential_pool status --pool SAP_POOL
```

Output:
```
Pool: SAP_POOL
Stats: 5 acquires, 3 releases
Queue: (empty)
Credentials:
  SAP_01               LOCKED  by rpa-wf-001-acquire  since 2026-11-11T10:30:00
  SAP_02               FREE
  SAP_03               LOCKED  by rpa-wf-003-acquire  since 2026-11-11T10:31:15
```

### 5. Admin: Force Release

```bash
uv run python -m automation.common.credential_pool release \
    --pool SAP_POOL --credential SAP_01 --holder rpa-wf-001-acquire
```

### 6. ปิด Pool

```bash
uv run python -m automation.common.credential_pool shutdown --pool SAP_POOL
```

---

## Worker Registration

Process ที่ใช้ credential pool ต้อง register workflow ทั้ง 2 ตัวใน worker:

```python
from automation.common.credential_pool.workflows.pool_manager import CredentialPoolWorkflow
from automation.common.credential_pool.workflows.acquire import AcquireCredentialWorkflow
from automation.common.credential_pool.activities.pool_activities import ACTIVITIES as POOL_ACTIVITIES

worker = Worker(
    client,
    task_queue=YOUR_QUEUE,
    workflows=[YourWorkflow, AcquireCredentialWorkflow],
    activities=[*YOUR_ACTIVITIES, *POOL_ACTIVITIES],
)
```

หรือใช้ shared pool worker แยกต่างหาก (แนะนำ):
```bash
uv run python -m automation.common.credential_pool.worker
```

---

## คุณสมบัติ

| Feature | รายละเอียด |
|---------|-----------|
| **Pool-based** | 1 pool = หลาย credentials, จ่ายตัวที่ว่างให้อัตโนมัติ |
| **FIFO Queue** | ถ้าไม่มีว่าง เข้าคิวรอตามลำดับ |
| **Auto-release** | Timeout = ปล่อย lock อัตโนมัติ (default 5 นาที) |
| **Helper functions** | `acquire_credential()` / `release_credential()` ใช้ง่ายเหมือน activity |
| **Crash recovery** | State อยู่ใน Temporal history — worker restart ได้เลย |
| **Continue-as-new** | History ไม่บวม ต่อให้รันเป็นเดือน |
| **Shared** | อยู่ใน `automation.common` — ทุก process import ได้ |

---

## เทียบกับ Blue Prism

| Blue Prism | Temporal Credential Pool |
|------------|------------------------|
| Acquire Lock → Get Credential | `await acquire_credential("SAP_POOL")` |
| Release Lock | `await release_credential("SAP_POOL", cred.name)` |
| Credential pool (multiple bots) | Pool workflow จัดการหลาย credentials |
| Bot crash → lock ค้าง | Auto-release เมื่อ timeout |
| ดูผ่าน Control Room | `status --pool SAP_POOL` หรือ Temporal UI |

---

## ไฟล์

```
automation/common/credential_pool/
├── __init__.py                    # re-export: acquire_credential, release_credential
├── __main__.py                    # python -m entrypoint
├── cli.py                         # CLI: start / status / release / shutdown
├── helpers.py                     # acquire_credential() / release_credential()
├── worker.py                      # shared pool worker
├── models/pool.py                 # dataclasses
├── configs/pool_config.py         # queue, timeout settings
├── workflows/
│   ├── pool_manager.py            # CredentialPoolWorkflow (pool core)
│   └── acquire.py                 # AcquireCredentialWorkflow (child wrapper)
├── activities/pool_activities.py  # fetch_credential, signal_requester_granted
└── README.md                      # เอกสารนี้
```
