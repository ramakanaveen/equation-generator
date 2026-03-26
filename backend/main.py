from dotenv import load_dotenv
load_dotenv()

import asyncio
import io
import json
import os
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from config import cfg
from providers import AnthropicProvider, VertexProvider
from version_manager import VersionManager
from queue_manager import QueueManager
from generator import run_generator
from coder import run_coder


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_provider = VertexProvider(cfg) if cfg.provider == "vertex" else AnthropicProvider(cfg)
_version_mgr = VersionManager()

# Active run state
_active_version: str | None = None
_gen_stop: asyncio.Event = asyncio.Event()
_code_stop: asyncio.Event = asyncio.Event()
_active_queue: QueueManager | None = None

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policy")


@app.get("/api/health")
async def health():
    return {"ok": True}


def sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _read_policy(name: str) -> str:
    with open(os.path.join(POLICY_DIR, name), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Generate (Ph1)
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    objective: str = ""


@app.post("/api/generate")
async def start_generate(body: GenerateRequest):
    global _active_version, _gen_stop, _active_queue
    _gen_stop = asyncio.Event()
    policy_text = await asyncio.to_thread(_read_policy, "policy.md")
    meta = await asyncio.to_thread(_version_mgr.create_version, policy_text, cfg)
    _active_version = meta.version
    _active_queue = QueueManager(meta.version, _version_mgr)
    return StreamingResponse(
        _gen_stream(body.objective, policy_text, meta.version),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _gen_stream(objective: str, policy_text: str, version: str):
    client = _provider.get_client()
    model = _provider.model_name
    yield sse({"stage": "start", "version": version})
    async for event in run_generator(
        policy_text, objective, _active_queue, version, _version_mgr, cfg, client, model, _gen_stop
    ):
        yield sse(event)


@app.post("/api/generate/stop")
async def stop_generate():
    _gen_stop.set()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Code (Ph2)
# ---------------------------------------------------------------------------

@app.post("/api/code/{version}")
async def start_code(version: str):
    global _code_stop
    _code_stop = asyncio.Event()
    if not _active_queue or _active_version != version:
        queue = QueueManager(version, _version_mgr)
    else:
        queue = _active_queue
    code_policy = await asyncio.to_thread(_read_policy, "code.md")
    return StreamingResponse(
        _code_stream(code_policy, queue, version),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _code_stream(code_policy: str, queue: QueueManager, version: str):
    client = _provider.get_client()
    model = _provider.model_name
    yield sse({"stage": "start", "version": version, "phase": "code"})
    async for event in run_coder(
        code_policy, queue, version, _version_mgr, cfg, client, model, _code_stop
    ):
        yield sse(event)


@app.post("/api/code/stop")
async def stop_code():
    _code_stop.set()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@app.get("/api/versions")
async def list_versions():
    versions = await asyncio.to_thread(_version_mgr.list_versions)
    return [v.__dict__ for v in versions]


@app.get("/api/versions/{version}")
async def get_version(version: str):
    try:
        meta = await asyncio.to_thread(_version_mgr.get_meta, version)
        return meta.__dict__
    except FileNotFoundError:
        raise HTTPException(404)


@app.get("/api/versions/{version}/queue")
async def get_queue_status(version: str):
    q = QueueManager(version, _version_mgr)
    return await asyncio.to_thread(q.counts)


@app.post("/api/versions/{version}/queue/retry")
async def retry_failed(version: str):
    q = QueueManager(version, _version_mgr)
    retried = await asyncio.to_thread(q.retry_failed)
    return {"retried": retried}


@app.get("/api/versions/{version}/equations")
async def list_equations(version: str):
    eq_dir = _version_mgr.equations_dir(version)
    if not os.path.isdir(eq_dir):
        return []
    return await asyncio.to_thread(lambda: sorted(f for f in os.listdir(eq_dir) if not f.startswith(".")))


@app.get("/api/versions/{version}/equations/{filename}")
async def get_equation_file(version: str, filename: str):
    path = os.path.join(_version_mgr.equations_dir(version), filename)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/versions/{version}/java")
async def list_java(version: str):
    java_dir = _version_mgr.java_dir(version)
    if not os.path.isdir(java_dir):
        return []
    return await asyncio.to_thread(lambda: sorted(f for f in os.listdir(java_dir) if not f.startswith(".")))


@app.get("/api/versions/{version}/java/{filename}")
async def get_java_file(version: str, filename: str):
    path = os.path.join(_version_mgr.java_dir(version), filename)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/versions/{version}/java-zip")
async def download_java_zip(version: str):
    java_dir = _version_mgr.java_dir(version)
    if not os.path.isdir(java_dir):
        raise HTTPException(404, "No Java files for this version")

    def _build_zip() -> bytes:
        files = [f for f in os.listdir(java_dir) if f.endswith(".java")]
        if not files:
            return b""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename in sorted(files):
                zf.write(os.path.join(java_dir, filename), filename)
        return buf.getvalue()

    data = await asyncio.to_thread(_build_zip)
    if not data:
        raise HTTPException(404, "No Java files for this version")

    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=equations-{version}.zip"},
    )


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@app.get("/api/policy/{name}")
async def get_policy(name: str):
    path = os.path.join(POLICY_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="text/markdown")


@app.put("/api/policy/{name}")
async def update_policy(name: str, request: Request):
    path = os.path.join(POLICY_DIR, name)
    body = await request.body()
    with open(path, "wb") as f:
        f.write(body)
    return {"ok": True}
