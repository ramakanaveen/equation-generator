# equation-generator — Project Context for Claude

## What this project is

A standalone pipeline that generates alpha trading equations (Ph1) and Java implementation
code (Ph2) using Claude AI. Designed to scale to thousands of equations via a file-based
queue, with versioned outputs so every run is traceable back to the policy that produced it.

**NOT** a general agent. No tool use, no skill system, no sessions.
Each phase = one direct Claude API call (with continuation if output is truncated).

---

## Architecture overview

```
policy/policy.md ──► Ph1 Generator ──► queue/v2/pending/ ──► Ph2 Code Generator ──► outputs/v2/java/
                          │                                           │
                     [Stop/config]                         [Start Coding button]
                                                                      │
                                                  outputs/v2/equations/  ← equation batches
                                                  outputs/v2/meta.json   ← policy snapshot + config
```

### Key design decisions (already agreed with user)

1. **File-based queue** — each batch of equations is a JSON file in `queue/vN/{pending,processing,done,failed}/`
2. **Versioned outputs** — every Generate run creates `v1`, `v2`, `v3`... so runs are comparable
3. **Ph2 is semi-manual** — user presses "Start Coding" at any point; Ph2 drains queue while Ph1 keeps filling it
4. **Stop condition** — `config.yaml: generation.target_count` (0 = unlimited) OR user presses Stop
5. **Token overflow** — both phases use `_call_with_continuation()` to handle `stop_reason == "max_tokens"`
6. **Providers** — Anthropic (default) or Vertex, same pattern as `skills-agent` project. Files already copied.

---

## What's already done

- `backend/providers/anthropic_provider.py` — copied verbatim from skills-agent ✅
- `backend/providers/vertex_provider.py` — copied verbatim from skills-agent ✅
- `backend/providers/__init__.py` ✅
- `backend/policy/policy.md` — seeded from user's alpha_generation_policy.md ✅
- `backend/policy/code.md` — Java code generation policy written ✅
- `backend/requirements.txt` ✅
- `.env.example` ✅
- `.gitignore` ✅

---

## What needs to be built (in order)

### Step 1 — `backend/config.py` + `backend/config.yaml`

Env var prefix: `EQ_GEN_` (not `SKILLS_AGENT_`).

```yaml
# config.yaml
provider: anthropic

vertex:
  project_id: ""
  region: us-east5

model:
  name: claude-sonnet-4-20250514
  vertex_name: claude-sonnet-4@20250514
  max_tokens: 16384

generation:
  target_count: 20        # 0 = unlimited until Stop
  eq_batch_size: 5        # equations per Ph1 API call
  code_batch_size: 2      # equations per Ph2 API call
  max_continuations: 3    # retries on max_tokens
```

Config dataclass pattern — copy exactly from skills-agent `config.py`:
- `_env(key, default)` helper reads `EQ_GEN_{KEY}` env vars
- `_load_yaml()` reads `config.yaml`
- `@dataclass class Config` with all fields
- `cfg = _build()` singleton at module level

Provider init (in `main.py` at startup):
```python
_provider = VertexProvider(cfg) if cfg.provider == "vertex" else AnthropicProvider(cfg)
```

---

### Step 2 — `backend/version_manager.py`

```python
import os, json, hashlib
from dataclasses import dataclass, asdict
from datetime import datetime

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
QUEUE_DIR   = os.path.join(os.path.dirname(__file__), "queue")

@dataclass
class VersionMeta:
    version: str            # "v1", "v2", ...
    created_at: str         # ISO UTC timestamp
    policy_hash: str        # SHA256 of policy.md content at run time
    policy_snapshot: str    # full policy.md text (for comparison)
    config_snapshot: dict   # cfg fields as dict
    equation_count: int = 0
    java_file_count: int = 0
    status: str = "generating"  # generating | coding | done

class VersionManager:
    def next_version(self) -> str:
        # scan outputs/ for v1, v2, v3... return next
    def create_version(self, policy_text: str, cfg) -> VersionMeta:
        # mkdir outputs/vN/equations, outputs/vN/java, queue/vN/pending etc.
        # write meta.json
    def update_meta(self, version: str, **kwargs):
        # read meta.json, update fields, write back
    def list_versions(self) -> list[VersionMeta]:
        # scan outputs/, read each meta.json, sort newest first
    def get_meta(self, version: str) -> VersionMeta:
    def equations_dir(self, version: str) -> str:
        return os.path.join(OUTPUTS_DIR, version, "equations")
    def java_dir(self, version: str) -> str:
        return os.path.join(OUTPUTS_DIR, version, "java")
    def queue_root(self, version: str) -> str:
        return os.path.join(QUEUE_DIR, version)
```

---

### Step 3 — `backend/queue_manager.py`

```python
import os, json, uuid, shutil
from dataclasses import dataclass

@dataclass
class QueueItem:
    id: str
    equations: list[dict]   # parsed equation objects
    batch_number: int
    created_at: str
    status: str             # pending | processing | done | failed
    error: str | None = None

class QueueManager:
    def __init__(self, version: str, version_mgr: VersionManager):
        self._root = version_mgr.queue_root(version)
        # subdirs: pending/ processing/ done/ failed/ — created by version_mgr.create_version()

    def enqueue(self, equations: list[dict], batch_number: int) -> QueueItem:
        # write {uuid}.json to pending/
    def dequeue(self) -> QueueItem | None:
        # pick oldest pending item, move to processing/, return item (or None)
    def mark_done(self, item: QueueItem):
        # move processing/{id}.json → done/
    def mark_failed(self, item: QueueItem, error: str):
        # move processing/{id}.json → failed/ (with error recorded)
    def retry_failed(self) -> int:
        # move all failed/ → pending/, return count
    def counts(self) -> dict:
        # return {pending, processing, done, failed} counts
```

---

### Step 4 — `backend/equation_parser.py`

Parses Ph1 markdown output into structured dicts.
The policy defines this template per equation:

```
### Alpha {N}: {Name}
**Expression:** ...
**Pattern Family:** ...
**Economic Rationale:** ...
**Frequency:** ... minutes
**Parameter Specifications:** (table)
**Grid Search Configuration:** ...
```

```python
def parse_equations(markdown_text: str) -> list[dict]:
    """
    Returns list of dicts:
    {
      "number": int,
      "name": str,
      "expression": str,
      "family": str,
      "rationale": str,
      "frequency": str,
      "parameters": str,   # raw markdown table
      "grid": str,         # raw markdown block
      "raw_markdown": str  # full ### Alpha N: ... block
    }
    """
    # Split on "### Alpha " headings
    # Use regex to extract each field
```

---

### Step 5 — `backend/generator.py`

Contains both `_call_with_continuation()` (shared primitive) and `run_generator()`.

```python
import asyncio, os
from datetime import datetime

async def _call_with_continuation(system: str, messages: list, cfg, client, model: str):
    """
    Async generator yielding text chunks.
    Handles stop_reason == "max_tokens" by appending continuation messages.
    """
    for attempt in range(cfg.max_continuations + 1):
        response = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            system=system,
            messages=messages,
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        yield text
        if response.stop_reason != "max_tokens":
            return
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written."},
        ]


async def run_generator(policy_text, objective, queue, version, version_mgr, cfg, client, model, stop_event):
    """
    Ph1 loop. Yields SSE-ready dicts.
    Runs until stop_event is set OR target_count reached.
    Writes equation batch md files to outputs/vN/equations/.
    Enqueues parsed equations to queue.
    Updates version meta equation_count after each batch.
    """
    generated_total = 0
    batch_number = 0
    eq_dir = version_mgr.equations_dir(version)

    while not stop_event.is_set():
        if cfg.target_count > 0 and generated_total >= cfg.target_count:
            break

        remaining = (cfg.target_count - generated_total) if cfg.target_count > 0 else cfg.eq_batch_size
        ask_count = min(cfg.eq_batch_size, remaining)

        user_msg = (
            f"Generate exactly {ask_count} alpha equations following all rules in the policy. "
            f"This is batch {batch_number + 1}. Total equations already generated in previous batches: {generated_total}. "
            f"{('Additional objective: ' + objective) if objective else ''}"
        )

        full_text = ""
        async for chunk in _call_with_continuation(
            system=policy_text,
            messages=[{"role": "user", "content": user_msg}],
            cfg=cfg, client=client, model=model,
        ):
            full_text += chunk
            yield {"stage": "token", "text": chunk, "phase": "equations"}

        # Write raw batch file
        batch_file = os.path.join(eq_dir, f"batch_{batch_number + 1:03d}.md")
        with open(batch_file, "w") as f:
            f.write(full_text)

        equations = parse_equations(full_text)
        queue.enqueue(equations, batch_number)
        generated_total += len(equations)
        batch_number += 1
        version_mgr.update_meta(version, equation_count=generated_total)

        yield {"stage": "batch_done", "batch": batch_number, "count": len(equations), "total": generated_total}

    version_mgr.update_meta(version, status="coding")
    yield {"stage": "gen_complete", "total": generated_total}
```

---

### Step 6 — `backend/coder.py`

```python
import asyncio, os, re
from .generator import _call_with_continuation

async def run_coder(code_policy_text, queue, version, version_mgr, cfg, client, model, stop_event):
    """
    Ph2 loop. Yields SSE-ready dicts.
    Drains queue. When queue empty + stop_event set → exits.
    Writes Java files to outputs/vN/java/.
    Updates version meta java_file_count.
    """
    coded_total = 0
    java_dir = version_mgr.java_dir(version)

    while True:
        item = queue.dequeue()
        if item is None:
            if stop_event.is_set():
                break
            await asyncio.sleep(1.5)
            continue

        try:
            eq_text = _format_equations_for_coding(item.equations)
            user_msg = f"Generate Java code for these {len(item.equations)} alpha equations:\n\n{eq_text}"

            full_code = ""
            async for chunk in _call_with_continuation(
                system=code_policy_text,
                messages=[{"role": "user", "content": user_msg}],
                cfg=cfg, client=client, model=model,
            ):
                full_code += chunk
                yield {"stage": "token", "text": chunk, "phase": "code"}

            count = _write_java_files(full_code, java_dir)
            queue.mark_done(item)
            coded_total += count
            version_mgr.update_meta(version, java_file_count=coded_total)
            yield {"stage": "code_batch_done", "batch_id": item.id, "count": count, "total": coded_total}

        except Exception as e:
            queue.mark_failed(item, str(e))
            yield {"stage": "error", "text": str(e), "batch_id": item.id}

    version_mgr.update_meta(version, status="done")
    yield {"stage": "code_complete", "total": coded_total}


def _format_equations_for_coding(equations: list[dict]) -> str:
    # Reconstruct compact markdown from parsed equation dicts for the code prompt
    return "\n\n---\n\n".join(eq.get("raw_markdown", str(eq)) for eq in equations)


def _write_java_files(code_text: str, java_dir: str) -> int:
    """
    Parse === FILE: Alpha_Name.java === ... === END FILE === blocks.
    Write each to java_dir. Returns count of files written.
    """
    pattern = r"=== FILE: (.+?) ===\n(.*?)=== END FILE ==="
    matches = re.findall(pattern, code_text, re.DOTALL)
    for filename, content in matches:
        path = os.path.join(java_dir, filename.strip())
        with open(path, "w") as f:
            f.write(content.strip())
    return len(matches)
```

---

### Step 7 — `backend/main.py`

```python
from dotenv import load_dotenv
load_dotenv()  # load .env from project root

import asyncio, json, os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from config import cfg
from providers import AnthropicProvider, VertexProvider
from version_manager import VersionManager
from queue_manager import QueueManager
from generator import run_generator
from coder import run_coder

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["*"], allow_headers=["*"])

_provider = VertexProvider(cfg) if cfg.provider == "vertex" else AnthropicProvider(cfg)
_version_mgr = VersionManager()

# Active run state
_active_version: str | None = None
_gen_stop: asyncio.Event = asyncio.Event()
_code_stop: asyncio.Event = asyncio.Event()
_active_queue: QueueManager | None = None


def sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# --- Generate (Ph1) ---

class GenerateRequest(BaseModel):
    objective: str = ""

@app.post("/api/generate")
async def start_generate(body: GenerateRequest):
    global _active_version, _gen_stop, _active_queue
    _gen_stop = asyncio.Event()  # fresh event each run
    policy_text = _read_policy("policy.md")
    version = _version_mgr.create_version(policy_text, cfg).version
    _active_version = version
    _active_queue = QueueManager(version, _version_mgr)
    return StreamingResponse(
        _gen_stream(body.objective, policy_text, version),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

async def _gen_stream(objective, policy_text, version):
    client = _provider.get_client()
    model  = _provider.model_name
    yield sse({"stage": "start", "version": version})
    async for event in run_generator(policy_text, objective, _active_queue, version, _version_mgr, cfg, client, model, _gen_stop):
        yield sse(event)

@app.post("/api/generate/stop")
async def stop_generate():
    _gen_stop.set()
    return {"ok": True}


# --- Code (Ph2) ---

@app.post("/api/code/{version}")
async def start_code(version: str):
    global _code_stop
    _code_stop = asyncio.Event()
    if not _active_queue or _active_version != version:
        # load queue for existing version
        queue = QueueManager(version, _version_mgr)
    else:
        queue = _active_queue
    code_policy = _read_policy("code.md")
    return StreamingResponse(
        _code_stream(code_policy, queue, version),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

async def _code_stream(code_policy, queue, version):
    client = _provider.get_client()
    model  = _provider.model_name
    yield sse({"stage": "start", "version": version, "phase": "code"})
    async for event in run_coder(code_policy, queue, version, _version_mgr, cfg, client, model, _code_stop):
        yield sse(event)

@app.post("/api/code/stop")
async def stop_code():
    _code_stop.set()
    return {"ok": True}


# --- Versions ---

@app.get("/api/versions")
async def list_versions():
    return [v.__dict__ for v in _version_mgr.list_versions()]

@app.get("/api/versions/{version}")
async def get_version(version: str):
    return _version_mgr.get_meta(version).__dict__

@app.get("/api/versions/{version}/queue")
async def get_queue_status(version: str):
    q = QueueManager(version, _version_mgr)
    return q.counts()

@app.post("/api/versions/{version}/queue/retry")
async def retry_failed(version: str):
    q = QueueManager(version, _version_mgr)
    return {"retried": q.retry_failed()}

@app.get("/api/versions/{version}/equations")
async def list_equations(version: str):
    eq_dir = _version_mgr.equations_dir(version)
    if not os.path.isdir(eq_dir): return []
    return sorted(f for f in os.listdir(eq_dir) if not f.startswith("."))

@app.get("/api/versions/{version}/equations/{filename}")
async def get_equation_file(version: str, filename: str):
    path = os.path.join(_version_mgr.equations_dir(version), filename)
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path)

@app.get("/api/versions/{version}/java")
async def list_java(version: str):
    java_dir = _version_mgr.java_dir(version)
    if not os.path.isdir(java_dir): return []
    return sorted(f for f in os.listdir(java_dir) if not f.startswith("."))

@app.get("/api/versions/{version}/java/{filename}")
async def get_java_file(version: str, filename: str):
    path = os.path.join(_version_mgr.java_dir(version), filename)
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path)


# --- Policy ---

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policy")

@app.get("/api/policy/{name}")
async def get_policy(name: str):
    path = os.path.join(POLICY_DIR, name)
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path, media_type="text/markdown")

@app.put("/api/policy/{name}")
async def update_policy(name: str, request: Request):
    path = os.path.join(POLICY_DIR, name)
    body = await request.body()
    with open(path, "wb") as f: f.write(body)
    return {"ok": True}


def _read_policy(name: str) -> str:
    with open(os.path.join(POLICY_DIR, name), encoding="utf-8") as f:
        return f.read()
```

---

### Step 8 — Frontend

#### `frontend/package.json`
Copy from `skills-agent` frontend, rename project to `equation-generator-ui`, remove unused deps (no ReactMarkdown needed initially — add later for equation preview).

Minimal deps needed:
- `react`, `react-dom`
- `vite`, `@vitejs/plugin-react`
- `react-markdown`, `remark-gfm` (for EquationsPanel)

#### `frontend/vite.config.js`
```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
```

#### `frontend/src/config.js`
```js
export const API = {
  generate:               '/api/generate',
  generateStop:           '/api/generate/stop',
  code:        (v)    =>  `/api/code/${v}`,
  codeStop:               '/api/code/stop',
  versions:               '/api/versions',
  version:     (v)    =>  `/api/versions/${v}`,
  queueStatus: (v)    =>  `/api/versions/${v}/queue`,
  queueRetry:  (v)    =>  `/api/versions/${v}/queue/retry`,
  equations:   (v)    =>  `/api/versions/${v}/equations`,
  equationFile:(v,f)  =>  `/api/versions/${v}/equations/${f}`,
  java:        (v)    =>  `/api/versions/${v}/java`,
  javaFile:    (v,f)  =>  `/api/versions/${v}/java/${f}`,
  policy:      (n)    =>  `/api/policy/${n}`,
}
```

#### `frontend/src/App.jsx` — state & layout
```jsx
// State:
// ph1Running, ph2Running, activeVersion, selectedVersion
// versions (list of metas), queueCounts
// ph1Log (token chunks), ph2Log (token chunks)

// Layout (3-column):
// Left:   ControlBar (full height)
// Center: StreamLog tabs (Ph1 | Ph2)
// Right:  Tabs: Equations | Java (version-scoped)

// VersionSelector sits above the right panel
```

#### `frontend/src/components/ControlBar.jsx`
Buttons + live counters:
- **Generate ▶** — POST /api/generate, start Ph1 SSE
- **Stop Ph1** — POST /api/generate/stop
- **Start Coding ▶** — POST /api/code/{activeVersion}, start Ph2 SSE
- **Stop Ph2** — POST /api/code/stop
- **Retry Failed** — POST /api/versions/{v}/queue/retry
- Live display: `v3 · 47 equations | 32 java files`
- QueueStatus badges: `pending · processing · done · failed`

#### `frontend/src/components/VersionSelector.jsx`
Horizontal tab strip. Each tab: `vN  · X eq  · Y java  · date`.
Active version highlighted. Clicking switches `selectedVersion` in App state.

#### `frontend/src/components/StreamLog.jsx`
Two tabs: Ph1 | Ph2. Each is a scrolling terminal box.
Appends `token` events as they arrive from SSE. Auto-scrolls to bottom.

#### `frontend/src/components/EquationsPanel.jsx`
Fetches `/api/versions/{selectedVersion}/equations` (list of batch files).
Fetches each file's markdown content and renders with ReactMarkdown.
Re-fetches when version changes or queueCounts.done increases.

#### `frontend/src/components/CodePanel.jsx`
Fetches `/api/versions/{selectedVersion}/java` (list of .java files).
Click a file to preview (plain text pre block). Download button per file.
Re-fetches when version changes or javaFileCount in meta increases.

---

## Running locally

```bash
# Backend
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

---

## Verification checklist (run after implementation)

1. Press **Generate** → `outputs/v1/` created, `meta.json` has policy snapshot
2. Batches appear in `queue/v1/pending/`, equation md files in `outputs/v1/equations/`
3. Press **Start Coding** → queue drains, Java files in `outputs/v1/java/`
4. `VersionSelector` shows `v1` with counts
5. Press **Generate** again → `outputs/v2/` created, both versions selectable
6. Edit `policy/policy.md`, Generate → `outputs/v3/meta.json` has new policy hash
7. Switch versions in selector → Equations and Code panels update
8. Press **Stop Ph1** mid-run → stops after current batch; partial version usable
9. Force a queue item failure → lands in `failed/`; retry works
10. Set `provider: vertex` in config.yaml → verify Vertex client works
