# equation-generator — Project Context for Claude

## What this project is

A pipeline that generates alpha trading equations (Ph1) and Java implementation code (Ph2)
using Claude AI. Runs as a web app (React + FastAPI) and as standalone CLI tools.
Scales to thousands of equations via a file-based queue with versioned outputs.

The CLI tools also support **codebase-aware generation**: point `codegen.py` at a real Java
project and it will analyze the codebase using 3 parallel subagents, then generate a Java
class that integrates correctly — right base interface, right package, right conventions.

---

## Architecture

```
Web UI flow:
  policy/policy.md ──► Ph1 Generator ──► queue/vN/{pending,processing,done,failed}/
                                                    │
                                         Ph2 Code Generator ──► outputs/vN/java/

CLI flow:
  python eqgen.py  ──► single equation (stdout)
  python codegen.py ──► single Java class (stdout + optional --dir)
  python eqgen.py | python codegen.py --codebase /path ──► codebase-aware Java
```

---

## Key files

### Backend (`backend/`)

| File | Role |
|---|---|
| `main.py` | FastAPI app — all HTTP endpoints, SSE streaming for Ph1 and Ph2 |
| `config.py` + `config.yaml` | Config dataclass, `EQ_GEN_*` env var overrides |
| `generator.py` | `_call_with_continuation()` primitive + `run_generator()` (Ph1 loop) |
| `coder.py` | `run_coder()` (Ph2 loop) — drains queue, writes Java files |
| `codebase_analyzer.py` | 3 parallel explorer subagents + synthesizer for codebase-aware codegen |
| `eqgen.py` | CLI: generate one equation |
| `codegen.py` | CLI: generate Java for one equation, with optional `--codebase` |
| `version_manager.py` | Creates/manages versioned output directories, meta.json |
| `queue_manager.py` | File-based queue: pending → processing → done/failed |
| `equation_parser.py` | Parses Ph1 markdown into structured dicts |
| `providers/` | `AnthropicProvider` and `VertexProvider` — identical interface |
| `policy/policy.md` | System prompt for Ph1 (equation generation) |
| `policy/code.md` | System prompt for Ph2 (Java code generation) |

### Frontend (`frontend/src/`)

| File | Role |
|---|---|
| `App.jsx` | Root state, SSE streams, layout |
| `components/ControlBar.jsx` | Generate/Stop/Code buttons, queue badges |
| `components/StreamLog.jsx` | Scrolling terminal for Ph1 and Ph2 token streams |
| `components/VersionSelector.jsx` | Horizontal tab strip per version |
| `components/EquationsPanel.jsx` | Renders equation batch markdown files |
| `components/CodePanel.jsx` | Java file viewer with syntax highlighting + download |
| `components/PolicyEditor.jsx` | Edit policy.md / code.md, AI-assisted rewriting |
| `config.js` | All API endpoint paths |
| `mdComponents.jsx` | Shared ReactMarkdown component overrides |

---

## Key design decisions

1. **`_call_with_continuation()`** — shared async generator in `generator.py`. Handles
   `stop_reason == "max_tokens"` by appending continuation messages. Used by Ph1, Ph2,
   policy editor AI, and codegen verification pass.

2. **File-based queue** — each batch is a UUID-named JSON file moved between
   `pending/ → processing/ → done/` (or `failed/`). Survives server restarts.

3. **Versioned outputs** — every Generate run creates `outputs/vN/` with a `meta.json`
   that snapshots the policy text and config, so runs are always comparable.

4. **SSE streaming** — both Ph1 and Ph2 return `StreamingResponse` with `text/event-stream`.
   Frontend reads via `ReadableStream` with an `AbortController` for cancellation.

5. **Providers** — `AnthropicProvider` and `VertexProvider` share an identical interface.
   Switch by setting `provider: vertex` in `config.yaml`.

6. **Codebase analyzer** uses 3 parallel Claude subagents (Claude Code Ultra pattern):
   - Explorer 1: finds base interfaces / abstract classes
   - Explorer 2: finds a concrete implementation to use as a pattern
   - Explorer 3: reads build manifest + package conventions
   All run simultaneously via `asyncio.gather()`. A Synthesizer merges the reports.
   Has `ask_followup_question` tool when critical info is missing.
   Type index (Python regex scan of all .java files) is pre-built before Claude starts.

---

## CLI tools

```bash
cd backend

# Generate one equation
python eqgen.py
python eqgen.py -o "volatility-adjusted momentum" --file eq.md

# Generate Java (generic)
python codegen.py -i eq.md -d ./out/

# Generate Java (codebase-aware — 3 parallel subagents + verify)
python codegen.py -i eq.md -d ./out/ --codebase /path/to/java/project

# Full pipeline
python eqgen.py | python codegen.py -d ./out/ --codebase /path/to/java/project
```

---

## Running locally

```bash
# Backend
cd backend && uvicorn main:app --reload --port 8200

# Frontend
cd frontend && npm run dev   # http://localhost:5173
```

---

## Config reference (`backend/config.yaml`)

```yaml
provider: anthropic        # or vertex

model:
  name: claude-sonnet-4-20250514
  max_tokens: 16384

generation:
  target_count: 25         # 0 = unlimited
  eq_batch_size: 5
  code_batch_size: 2
  max_continuations: 3
```

All fields overridable via `EQ_GEN_*` env vars.
