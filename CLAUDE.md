# equation-generator — Project Context for Claude

## What this project is

A pipeline that generates alpha trading equations (Ph1) and implementation code (Ph2)
using Claude AI. Runs as a web app (React + FastAPI) and as standalone CLI tools.
Scales to thousands of equations via a file-based queue with versioned outputs.

The CLI tools support **codebase-aware generation**: point `codegen.py` at any local project
(Java, Python, TypeScript, Kotlin, Go) and it will auto-detect the language, analyze the
codebase using 3 parallel Haiku subagents, then generate code that integrates correctly —
right base class, right package/module, right conventions.

---

## Architecture

```
Web UI flow:
  policy/policy.md ──► Ph1 Generator ──► queue/vN/{pending,processing,done,failed}/
                                                    │
                                         Ph2 Code Generator ──► outputs/vN/java/

CLI flow:
  python eqgen.py  ──► single equation (stdout)
  python codegen.py ──► single code file (stdout + optional --dir)
  python eqgen.py | python codegen.py --codebase /path ──► codebase-aware code
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
| `codebase_analyzer.py` | Language-agnostic analyzer: 3 parallel Haiku explorers + stateless synthesizer |
| `eqgen.py` | CLI: generate one equation |
| `codegen.py` | CLI: generate code for one equation, with optional `--codebase` |
| `version_manager.py` | Creates/manages versioned output directories, meta.json |
| `queue_manager.py` | File-based queue: pending → processing → done/failed |
| `equation_parser.py` | Parses Ph1 markdown into structured dicts |
| `providers/` | `AnthropicProvider` and `VertexProvider` — identical interface |
| `policy/policy.md` | System prompt for Ph1 (equation generation) — user-owned |
| `policy/code.md` | System prompt for Ph2 (code generation style) — user-owned, never modified by system |

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
   policy editor AI, codegen synthesizer, and verification pass.

2. **File-based queue** — each batch is a UUID-named JSON file moved between
   `pending/ → processing/ → done/` (or `failed/`). Survives server restarts.

3. **Versioned outputs** — every Generate run creates `outputs/vN/` with a `meta.json`
   that snapshots the policy text and config, so runs are always comparable.

4. **SSE streaming** — both Ph1 and Ph2 return `StreamingResponse` with `text/event-stream`.
   Frontend reads via `ReadableStream` with an `AbortController` for cancellation.

5. **Providers** — `AnthropicProvider` and `VertexProvider` share an identical interface.
   Switch by setting `provider: vertex` in `config.yaml`.

6. **Codebase analyzer** — language-agnostic, following Claude Code / DeepAgents patterns:
   - Language auto-detected from file extension counts
   - Symbol index built in Python (~1s) — never pre-dumped into context
   - `query_symbols` tool exposes index lazily; explorers call it on demand
   - 3 parallel **Haiku** explorers via `asyncio.gather()` (cheap + fast)
   - Synthesizer is a **stateless** `_call_with_continuation` call (no tool loop)
   - Orchestrator checks profile completeness; asks user if `UNCLEAR:` sections found,
     then re-synthesizes with full original reports preserved (lossless)
   - All tool results capped at 80K chars (~20K tokens, DeepAgents threshold)
   - `max_tokens` handled inline in explorer loop — no silent data loss
   - `policy/code.md` is user-owned and never touched; codebase profile appended at runtime

---

## CLI tools

```bash
cd backend

# Generate one equation
python eqgen.py
python eqgen.py -o "volatility-adjusted momentum" --file eq.md

# Generate code (default: follows code.md policy)
python codegen.py -i eq.md -d ./out/

# Generate code (codebase-aware — any language)
python codegen.py -i eq.md -d ./out/ --codebase /path/to/any/project

# Full pipeline
python eqgen.py | python codegen.py -d ./out/ --codebase /path/to/project
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
