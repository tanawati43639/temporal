# Workflow Registry — Auto-generated REST API

FastAPI endpoints สำหรับทุก Temporal workflow ถูก generate อัตโนมัติจากไฟล์ registry
เพิ่ม workflow ใหม่ = เพิ่ม `WorkflowSpec` 1 entry → Swagger โชว์ 6–10 endpoints ให้ทันที

---

## โครงสร้างไฟล์

```
automation/api/
├── client.py       → shared Temporal client (singleton + lifespan)
├── schemas.py      → Pydantic request models ทั้งหมดของทุก workflow
├── registry.py     → WORKFLOWS list — single source of truth
├── factory.py      → register_workflow_endpoints(app, spec)
└── server.py       → FastAPI app + global endpoints (list/history/stats/registry)
```

**เพิ่ม workflow ใหม่ไม่ต้องแตะ `server.py` และ `factory.py` เลย** แก้แค่ `schemas.py` + `registry.py`

---

## Endpoints ที่ auto-generate ต่อ 1 workflow

| Method | Path | ประเภท | เงื่อนไข |
|---|---|---|---|
| `POST` | `/api/{name}/start` | typed Pydantic form | เสมอ |
| `GET` | `/api/{name}` | list by WorkflowType | เสมอ |
| `GET` | `/api/{name}/{wid}/describe` | metadata | เสมอ |
| `GET` | `/api/{name}/{wid}/status` | รัน queries ทั้งหมด | มี query อย่างน้อย 1 |
| `POST` | `/api/{name}/{wid}/signals/{signal}` | 1 endpoint ต่อ 1 signal | มี signal |
| `POST` | `/api/{name}/{wid}/updates/{update}` | 1 endpoint ต่อ 1 update | มี update |
| `POST` | `/api/{name}/{wid}/cancel` | graceful cancel | เสมอ |
| `POST` | `/api/{name}/{wid}/terminate` | force terminate | เสมอ |

### Global endpoints (ที่ `server.py`)

- `GET /api/workflows` — Visibility search ข้ามทุก type
- `GET /api/workflows/{id}/history` — event history
- `GET /api/dashboard/stats` — counts by status + by type
- `GET /api/registry` — introspect ว่า register workflow อะไรบ้าง

---

## การเพิ่ม workflow ใหม่ — 3 ขั้น

### 1. เขียน Pydantic request model ใน `schemas.py`

```python
class StartReportRequest(BaseModel):
    report_type: str = Field(default="sales", description="รายงานประเภทไหน")
    date: str = Field(default="2026-10-26")
    recipients: list[str] = Field(default_factory=list)
```

### 2. เพิ่ม `WorkflowSpec` ใน `registry.py` `WORKFLOWS` list

```python
WorkflowSpec(
    name="report",
    display_name="Report Generator",
    description="Nightly report generation",
    workflow_class=ReportWorkflow,
    run_method=ReportWorkflow.run,
    task_queue=BATCH_QUEUE,
    id_prefix="report",
    start_body_model=StartReportRequest,
    start_input_builder=lambda r: ReportInput(**r.model_dump()),
    signals={
        "retry": SignalSpec(ReportWorkflow.retry_now),
    },
    queries={
        "progress": QuerySpec(ReportWorkflow.get_progress),
    },
),
```

### 3. Restart server

```bash
uv run uvicorn automation.api.server:app --reload --port 8888
```

Swagger (`http://localhost:8888/docs`) โชว์ tag "Report Generator" พร้อม endpoints ครบ

---

## 🔒 Hard requirements (บังคับ)

ทุก workflow ที่จะใส่ใน registry ต้องมี:

### 1. Class ประกาศด้วย `@workflow.defn`
```python
@workflow.defn
class MyWorkflow:
    ...
```

### 2. มี `@workflow.run` method ตัวเดียว
```python
@workflow.run
async def run(self, input: MyInput) -> MyOutput:
    ...
```

### 3. Input = 1 argument เดียว (ไม่ใช่ positional หลายตัว)
```python
# ✅ ใช้ได้
async def run(self, input: ParentInput) -> ...
async def run(self) -> ...
async def run(self, order_id: str) -> ...

# ❌ ใช้ไม่ได้ ต้อง refactor
async def run(self, requester: str, approver: str, amount: float) -> ...
```

### 4. Input serializable ตาม Temporal Data Converter
- `@dataclass` ✅
- Pydantic model ✅ (ถ้า pass PydanticDataConverter)
- `dict`, `list`, primitives, `datetime` ✅
- `set`, generator, custom class ที่ซับซ้อน ❌

### 5. Workflow class importable จาก module path
- ประกาศที่ module top-level
- Import module ไม่มี side effect ที่พัง

### 6. Register กับ Worker ด้วย task queue เดียวกับ spec

```python
# worker.py
worker = Worker(
    client,
    task_queue=BATCH_QUEUE,       # ← ตรงกับ WorkflowSpec.task_queue
    workflows=[MyWorkflow, ...],  # ← มีในรายการ
)
```

ถ้าไม่ตรง: `start_workflow` สำเร็จแต่ไม่มี worker มารัน → ค้าง pending

### 7. Signal / Query / Update signatures

| ประเภท | Signature | หมายเหตุ |
|---|---|---|
| Signal | `(self)` หรือ `(self, arg: T)` | T ต้อง serializable |
| Query | `(self) -> R` หรือ `(self, arg: T) -> R` | ห้ามเปลี่ยน state |
| Update | `(self) -> R` หรือ `(self, arg: T) -> R` | รองรับ async |
| Validator | `(self, arg: T) -> None` | ห้าม await, ห้ามเปลี่ยน state |

---

## 📐 Soft conventions (ไม่บังคับ แต่ควรทำ)

### A. แยก input class ไว้ที่ `models/`
```
automation/
├── models/
│   ├── batch.py       → ParentInput, BatchInput, BatchResult
│   ├── approval.py    → ApprovalRequest, ApprovalDecision
│   └── notify.py      → NotifyInput
└── processes/
    ├── batch_controllable/parent.py
    └── approval/approval_workflow.py
```

### B. ID prefix ชัดเจน
```python
id_prefix="ctl-batch"   # → ctl-batch-abc12345
```
จำง่าย filter ใน UI สะดวก

### C. Workflow class name เป็น PascalCase
ใช้เป็น `WorkflowType` ใน Visibility API
```python
'WorkflowType="ControllableBatchParentWorkflow"'
```

### D. Dataclass field มี default value
```python
@dataclass
class ParentInput:
    total_items: int                 # required
    batch_size: int = 100            # optional (default)
```
Swagger form โชว์ default ให้ user

### E. แยก "user input" ออกจาก "state fields"

Field ที่เป็น state (เช่น `next_offset`, `processed`, `failed`) **ไม่ควร** ให้ user กรอก → ซ่อนใน Pydantic model

```python
# dataclass (ground truth)
@dataclass
class ParentInput:
    total_items: int                 # user
    batch_size: int = 100            # user
    max_concurrent_children: int = 5 # user
    batches_per_run: int = 20        # user
    next_offset: int = 0             # ← state, ซ่อน
    processed: int = 0               # ← state, ซ่อน
    failed: int = 0                  # ← state, ซ่อน

# Pydantic (ส่วนที่ user เห็น)
class StartBatchRequest(BaseModel):
    total_items: int = 1000
    batch_size: int = 100
    concurrency: int = 5          # ← rename ให้ friendly
    batches_per_run: int = 4

# แปลงผ่าน start_input_builder
start_input_builder=lambda r: ParentInput(
    total_items=r.total_items,
    batch_size=r.batch_size,
    max_concurrent_children=r.concurrency,
    batches_per_run=r.batches_per_run,
)
```

**เหตุผลที่ไม่ auto-generate Pydantic จาก dataclass** — ต้องการแยก state ออกจาก input และ rename ให้ user-friendly

---

## 📋 Checklist เพิ่ม workflow ใหม่

ก่อนเพิ่มเข้า registry เช็ค 7 ข้อ:

- [ ] มี `@workflow.defn` และ `@workflow.run`
- [ ] `run()` รับ argument 1 ตัวเท่านั้น (หรือไม่มีเลย)
- [ ] Input class เป็น `@dataclass` อยู่ใน `models/` (หรือ inline แต่ import ได้)
- [ ] Workflow class register ใน `workers/worker.py` ด้วย task queue เดียวกัน
- [ ] Pydantic request model เขียนใน `schemas.py` (ซ่อน state fields)
- [ ] `start_input_builder` map Pydantic → dataclass ครบทุก field ที่ workflow ต้องการ
- [ ] Signal / query / update ที่อยาก expose ประกาศใน spec (ไม่ประกาศ = ไม่มี endpoint)

---

## การใช้งาน

### Start workflow ผ่าน Swagger (วิธีง่ายสุด)
```
http://localhost:8888/docs
→ ขยาย POST /api/controllable-batch/start
→ Try it out → กรอก 4 ตัวเลข → Execute
```

### Start workflow ผ่าน curl
```bash
WF=$(curl -s -X POST http://localhost:8888/api/controllable-batch/start \
     -H 'Content-Type: application/json' \
     -d '{"total_items":100,"batch_size":5,"concurrency":5,"batches_per_run":4}' \
     | jq -r .workflow_id)

# เช็ค status
curl -s http://localhost:8888/api/controllable-batch/$WF/status | jq

# pause / resume / stop
curl -s -X POST http://localhost:8888/api/controllable-batch/$WF/signals/pause
curl -s -X POST http://localhost:8888/api/controllable-batch/$WF/signals/resume
curl -s -X POST http://localhost:8888/api/controllable-batch/$WF/signals/stop

# pause แบบรอยืนยัน (update, synchronous)
curl -s -X POST http://localhost:8888/api/controllable-batch/$WF/updates/pause-wait | jq

# cancel / terminate
curl -s -X POST http://localhost:8888/api/controllable-batch/$WF/cancel
curl -s -X POST http://localhost:8888/api/controllable-batch/$WF/terminate
```

### Introspect ว่า registry มีอะไรบ้าง
```bash
curl -s http://localhost:8888/api/registry | jq
```

---

## ตัวอย่างที่ลงทะเบียนไว้แล้ว

| Workflow | Signals | Queries | Updates |
|---|---|---|---|
| `controllable-batch` | pause, resume, stop | state, progress | pause-wait |
| `batch` | — | progress | — |
| `approval` | decide | state, status | update-amount |
| `notify` | — | — | — |
| `mcp` | — | — | — |

ดู full detail ที่ `GET /api/registry`

---

## Defensive validation (optional)

เพิ่มการเช็คตอน startup ให้ throw ตั้งแต่ import time ถ้า spec ผิด — ดูตัวอย่างใน
section "บังคับใช้ contract ตอน startup" ของเอกสาร design

เช่น:
- `@workflow.defn` existence
- `run` method signature (≤ 1 arg)
- Signal/update fn เป็น method จริงของ class
- `start_body_model` เป็น Pydantic `BaseModel`
