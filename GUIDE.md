# User Guide — Equation Generator

## Overview

Two ways to use this tool:

| Mode | When to use |
|---|---|
| **Web UI** | Generate large batches, browse equations visually, download ZIP |
| **CLI** | Quick one-offs, pipe into other tools, codebase-aware code generation |

---

## Web UI

### Start the app

```bash
# Terminal 1 — backend
cd backend && uvicorn main:app --reload --port 8200

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**

---

### Generate equations (Phase 1)

1. Optionally type an objective in the text field — e.g. *"focus on volatility mean-reversion"*
2. Click **Generate ▶**
3. Equations stream into the center panel in real time
4. Click **Stop ■** at any time — already-generated equations are saved

Each run creates a new version (`v1`, `v2`, ...) shown in the top-right tab strip.

---

### Generate code (Phase 2)

1. After equations finish (or while they're still running), click **Start Coding ▶**
2. Java files are generated from the queue and streamed into the right panel
3. Switch between versions using the tab strip to compare runs

---

### Download

- Click **Download ZIP** in the Java tab to get all `.java` files for a version as a single archive

---

### Regenerate code for an existing version

- Click **Regenerate Java** to re-run Phase 2 against the same equations with the current `code.md`
- Old Java files are archived to `java_archive/run_NNN/` — nothing is deleted

---

### Edit policies

Click **Edit Policies** (top right) to open the policy editor.

| Policy | Controls |
|---|---|
| `policy.md` | What equations are generated — scope, families, format, parameter conventions |
| `code.md` | How equations are translated to code — base interface, class template, rules |

**AI-assisted rewriting:** describe the change you want in natural language, click **Rewrite with AI**, review the diff, then **Save** or **Revert**.

Changes apply on the next Generate / Start Coding run.

---

## CLI tools

All CLI tools run from the `backend/` directory and use the same `config.yaml` and `.env` as the web app.

```bash
cd backend
```

---

### `eqgen.py` — generate one equation

```bash
# Stream one equation to stdout
python eqgen.py

# With an objective
python eqgen.py -o "volatility-adjusted momentum"

# Save to file as well
python eqgen.py -o "mean reversion" --file eq.md
```

Output streams to the terminal as Claude generates it.

---

### `codegen.py` — generate code for one equation

```bash
# Read equation from a file, print code to stdout
python codegen.py -i eq.md

# Write output files to a directory
python codegen.py -i eq.md -d ./out/

# Read equation from stdin (pipe from eqgen.py)
python eqgen.py | python codegen.py -d ./out/
```

---

### Codebase-aware generation

Pass `--codebase` to point `codegen.py` at a real project. The analyzer auto-detects the language,
explores the codebase structure, and generates code that integrates correctly — using the actual
base class/interface, package, imports, and conventions it discovers.

Works with any language: **Java, Python, TypeScript, Kotlin, Go**.

```bash
python codegen.py -i eq.md -d ./out/ --codebase /path/to/your/project
```

**What happens under the hood:**

```
1. Language detected from file extension counts
2. Symbol index built in Python (~1s, all source files) — kept in memory, never dumped to context
3. Three Haiku subagents run in parallel (cheap + fast):
     Explorer 1 — calls query_symbols to find the base class / interface / protocol
     Explorer 2 — calls query_symbols(test=false) to find a production implementation pattern
     Explorer 3 — reads CLAUDE.md, README, build manifest for package + rules
   Each explorer has its own isolated context; only its final report flows out.
4. Stateless synthesizer — single _call_with_continuation call merges the 3 reports.
   If a critical field is UNCLEAR:, the orchestrator asks you directly, then
   re-synthesizes with the full original reports preserved (lossless).
5. Code generated using codegen.md policy + CodebaseProfile — LLM has live access to
   read_file, search_code, and query_symbols during generation (not just the profile).
```

**Progress output:**

```
[Language: python | Symbols: 42 (3 base types, 18 with inheritance) | Explorers: claude-haiku-... | Launching 3 in parallel]
  [Explorer-1 (Base Types)] query_symbols({"kind":"abstract class"})
  [Explorer-2 (Implementations)] query_symbols({"kind":"class","test":false})
  [Explorer-3 (Build + Conventions)] read_file({"path":"CLAUDE.md"})
  ...
[Explorer-1 (Base Types): done]
[Explorer-2 (Implementations): done]
[Explorer-3 (Build + Conventions): done]
[Synthesizer: merging reports]
[Phase 1: Codebase Analysis] 7 calls · 45,230 in + 8,120 out = 53,350 tokens

[Phase 2: Generating code]
[Written: ./out/volume_weighted_momentum_alpha.py]

[Phase 2: Code Generation] 4 calls · 12,450 in + 3,210 out = 15,660 tokens
```

On a repeated run (same codebase, any equation):

```
[Language: python | Profile cache hit — skipping analysis]
[Phase 1: Codebase Analysis] 0 calls · (cache hit)
```

**If the analyzer can't determine the base type** (multiple plausible candidates), it will ask:

```
┌─ Codebase analysis needs your input ──────────────────────
│  Which base class should new signals extend?
│  1. BaseSignal (trading.signals.base)
│  2. AbstractFactor (trading.factors.core)
│
│  Enter number or answer (Enter = let Claude decide):
```

**Full pipeline:**

```bash
python eqgen.py -o "mean reversion" | python codegen.py -d ./out/ --codebase /path/to/project
```

---

## How policies work

The system uses three policies, all editable directly (two also from the UI):

```
backend/policy/policy.md   — equation generation rules (web UI + CLI)
backend/policy/code.md     — standalone code generation style guide (used when no --codebase)
backend/policy/codegen.md  — codebase-aware generation rules (used with --codebase)
```

`code.md` and `codegen.md` are **your** files — the system never modifies them.

When `--codebase` is used, the discovered CodebaseProfile is appended to `codegen.md` at runtime:

```
[your codegen.md]

## Codebase Profile

## Language
python

## Package / Module
trading.signals

## Base Type
class BaseSignal(ABC): ...
...
```

The generator reads both: `codegen.md` provides generation rules and style, the profile provides
language-specific integration facts. The profile cache means this analysis only runs once per
codebase — any subsequent equation on the same unchanged codebase gets a cache hit.

---

## Configuration

`backend/config.yaml`:

```yaml
provider: anthropic        # or vertex

model:
  name: claude-sonnet-4-20250514
  max_tokens: 16384

generation:
  target_count: 25         # equations to generate per run (0 = unlimited)
  eq_batch_size: 5
  code_batch_size: 2
  max_continuations: 3
```

All fields overridable via environment variables: `EQ_GEN_TARGET_COUNT=50`, etc.

---

## Output structure

```
backend/outputs/
└── v1/
    ├── meta.json          # policy snapshot, config, counts
    ├── equations/
    │   ├── batch_001.md
    │   └── batch_002.md
    ├── java/
    │   └── Alpha_*.java
    └── java_archive/
        └── run_001/       # previous codegen run, archived on Regenerate
```
