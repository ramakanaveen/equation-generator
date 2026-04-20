# Equation Generator

A pipeline that generates alpha trading equations (Ph1) and Java implementation code (Ph2) using Claude AI. Designed to scale to thousands of equations via a file-based queue, with versioned outputs so every run is traceable back to the policy that produced it.

## How it works

```
policy/policy.md ──► Ph1 Generator ──► queue/vN/pending/ ──► Ph2 Code Generator ──► outputs/vN/java/
```

1. **Phase 1** — Claude reads `policy.md` and generates batches of alpha equations in markdown
2. **Phase 2** — Claude reads `code.md` and converts each equation into a Java implementation
3. Every run creates a new versioned output (`v1`, `v2`, ...) with a full policy snapshot so runs are always comparable

## Features

- Real-time streaming output in the browser as equations and code are generated
- File-based queue with `pending / processing / done / failed` states
- Versioned outputs — switch between runs in the UI
- Regenerate Java for any version (archives old files to `java_archive/run_NNN/`)
- Download all Java files for a version as a ZIP
- Edit `policy.md` and `code.md` directly from the UI, with AI-assisted rewriting
- **CLI tools** — generate a single equation or codebase-aware Java class from the command line (no UI needed)
- Configurable port and CORS via env vars — no hardcoded localhost
- All blocking I/O is async so the server stays responsive during generation

## Stack

| Layer | Tech |
|---|---|
| AI | [Anthropic Claude](https://anthropic.com) (or Vertex AI) |
| Backend | Python 3.13 · FastAPI · uvicorn |
| Frontend | React 18 · Vite |

---

## Setup

### 1. Clone

```bash
git clone https://github.com/ramakanaveen/equation-generator.git
cd equation-generator
```

### 2. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env
npm install
```

---

## Running locally

```bash
# Terminal 1 — Backend (from repo root)
source .venv/bin/activate
cd backend
uvicorn main:app --reload --port 8200

# Terminal 2 — Frontend (from repo root)
cd frontend
npm run dev   # http://localhost:5173
```

### Custom ports

Edit `frontend/.env`:

```env
VITE_PORT=5200
VITE_BACKEND_URL=http://localhost:8200
```

Edit `backend/config.yaml` or set env vars:

```bash
EQ_GEN_PORT=8200
```

---

## Configuration

### `backend/config.yaml`

```yaml
provider: anthropic        # or vertex

model:
  name: claude-sonnet-4-20250514
  max_tokens: 16384

generation:
  target_count: 20         # 0 = unlimited until Stop
  eq_batch_size: 5         # equations per Ph1 API call
  code_batch_size: 2       # equations per Ph2 API call
  max_continuations: 3     # retries on max_tokens
```

All fields can be overridden with `EQ_GEN_*` environment variables (e.g. `EQ_GEN_TARGET_COUNT=50`).

### Vertex AI

```yaml
provider: vertex
vertex:
  project_id: your-gcp-project
  region: us-east5
```

---

## Usage

1. Open **http://localhost:5173**
2. Optionally add an objective (e.g. *"focus on mean-reversion"*)
3. Click **Generate ▶** — equations stream into the center panel in real time
4. Click **Start Coding ▶** — Java files are generated from the queue
5. Switch versions using the tab strip in the top-right panel
6. Download a full version as a ZIP using **Download ZIP** in the Java tab
7. Click **Edit Policies** to modify `policy.md` or `code.md` — changes apply on the next run
8. Click **Regenerate Java** to re-run Ph2 with a new `code.md` — old files are archived

---

## CLI tools

For quick one-off generation without the web UI, two standalone scripts are available in `backend/`.

### `eqgen.py` — generate a single equation

```bash
cd backend

# Stream one equation to stdout
python eqgen.py

# With an objective
python eqgen.py -o "volatility-adjusted momentum"

# Save output to a file as well
python eqgen.py --file eq.md
```

### `codegen.py` — generate Java code for one equation

```bash
# From a file produced by eqgen.py
python codegen.py -i eq.md

# Write .java files to an output directory
python codegen.py -i eq.md -d ./out/

# Read equation from stdin (supports piping)
cat eq.md | python codegen.py -d ./out/
```

### Codebase-aware generation

Pass `--codebase` to point `codegen.py` at an existing Java project. It will analyze the codebase first, then generate a class that integrates seamlessly — using the actual base interface, package, imports, and conventions it discovers.

```bash
python codegen.py -i eq.md -d ./out/ --codebase /path/to/java/project
```

The analyzer runs in three phases:

1. **Type index** — Python regex-scans all `.java` files in ~1 second regardless of codebase size, building a full structural map (class names, kinds, extends/implements, methods) before any Claude call
2. **3 parallel explorer subagents** — modelled on the Claude Code Ultra pattern, three Claude agents run simultaneously via `asyncio.gather()`:
   - *Explorer 1* — finds the base interface / abstract class
   - *Explorer 2* — finds a concrete implementation to use as a pattern
   - *Explorer 3* — reads `CLAUDE.md`, `README`, `pom.xml` for build constraints and package conventions
   Each explorer gets a focused slice of the type index and its own tool-use loop (`glob`, `read_file` with line ranges, `search_code`). No hardcoded naming patterns — exploration is guided by the equation being implemented.
3. **Synthesizer** — merges the three reports into a `CodebaseProfile`. Has an `ask_followup_question` tool that presents specific options if critical info (base interface, package) is missing.
4. **Verification pass** — a final Claude call checks the generated class for correct interface implementation, all abstract methods, required imports, and lifecycle contract compliance.

```bash
# Full pipeline: generate equation and codebase-aware Java in one shot
python eqgen.py | python codegen.py -d ./out/ --codebase /path/to/java/project
```

Example output for a codebase where signals implement `Computable` (not `AlphaExpression`):

```
[Phase 1: Analyzing codebase at /path/to/project]
[Type index: 142 classes | Launching 3 parallel explorers]
  [Explorer-1 (Base Types)] read_file({"path":"src/.../Computable.java"})
  [Explorer-2 (Implementations)] search_code({"directory":"src","pattern":"implements Computable"})
  [Explorer-3 (Build + Conventions)] read_file({"path":"CLAUDE.md"})
  ...
[Explorer-1 (Base Types): done]
[Explorer-2 (Implementations): done]
[Explorer-3 (Build + Conventions): done]
[Synthesizer: merging reports]
[Phase 2: Generating code]
[Phase 3: Verifying output]
[Verified ✓]
[Written: ./out/Alpha_MySignal.java]
```

The generated class uses `implements Computable`, `package com.trading.signals`, and follows the exact pattern of existing implementations — ready to drop into the project.

### Pipeline — equation → code in one shot

```bash
python eqgen.py | python codegen.py -d ./out/
ls out/
# AlphaExpression.java  Alpha_MyStrategy.java
```

Both scripts stream output to the terminal as Claude generates it, and use the same `config.yaml` and `.env` as the web backend.

---

## Output structure

```
backend/
├── outputs/
│   └── v1/
│       ├── meta.json          # policy hash, config snapshot, counts, status
│       ├── equations/
│       │   ├── batch_001.md
│       │   └── batch_002.md
│       ├── java/
│       │   └── Alpha_*.java
│       └── java_archive/
│           └── run_001/       # archived on Regenerate Java
└── queue/
    └── v1/
        ├── pending/
        ├── processing/
        ├── done/
        └── failed/
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for Anthropic provider |
| `EQ_GEN_PORT` | `8000` | Backend port |
| `EQ_GEN_PROVIDER` | `anthropic` | `anthropic` or `vertex` |
| `EQ_GEN_TARGET_COUNT` | `20` | Equations to generate (0 = unlimited) |
| `EQ_GEN_EQ_BATCH_SIZE` | `5` | Equations per Ph1 call |
| `EQ_GEN_CODE_BATCH_SIZE` | `2` | Equations per Ph2 call |
| `EQ_GEN_MAX_TOKENS` | `16384` | Max tokens per API call |
| `EQ_GEN_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
