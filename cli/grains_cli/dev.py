"""`grains dev` -- local task API backed by stdlib http.server."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import tomllib
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from grains import Task, agent


class _TaskStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def create(self) -> str:
        task_id = uuid.uuid4().hex
        with self._lock:
            self._tasks[task_id] = {"status": "queued", "reply": None, "error": None}
        return task_id

    def set(self, task_id: str, **fields) -> None:
        with self._lock:
            self._tasks[task_id].update(fields)

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task is not None else None


def _load_entrypoint(target: Path, entrypoint: str):
    module_name, _, func_name = entrypoint.partition(":")
    if not module_name or not func_name:
        raise ValueError(f"invalid entrypoint {entrypoint!r}; expected 'module:function'")
    module_path = target / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(target))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(target))
    return getattr(module, func_name)


_NODE_RUNNER = str(Path(__file__).resolve().parent / "_node_runner.mjs")


def _run_task_node(task_id, store, text, payload, app_dir, entrypoint) -> None:
    store.set(task_id, status="working")
    task_json = json.dumps({"task_id": task_id, "text": text, "payload": payload}).encode()
    try:
        proc = subprocess.run(
            ["node", _NODE_RUNNER, str(app_dir), entrypoint],
            input=task_json, capture_output=True, timeout=300,
        )
    except FileNotFoundError:
        store.set(task_id, status="failed", error="node not found on PATH")
        return
    except subprocess.TimeoutExpired:
        store.set(task_id, status="failed", error="task timed out")
        return
    last = (proc.stdout.decode(errors="replace").strip().splitlines() or [""])[-1]
    try:
        result = json.loads(last)
    except json.JSONDecodeError:
        err = proc.stderr.decode(errors="replace")[-2000:] or "no output from node runner"
        store.set(task_id, status="failed", error=err)
        return
    if result.get("status") == "failed":
        store.set(task_id, status="failed", error=result.get("error"))
        return
    store.set(task_id, status="done", reply=result.get("reply"), charges=result.get("charges", []))


def _run_task(task_id: str, store: _TaskStore, text: str, payload: dict) -> None:
    store.set(task_id, status="working")
    task = Task(id=task_id, text=text, payload=payload)
    try:
        reply = asyncio.run(agent.invoke(task))
    except Exception as exc:  # noqa: BLE001 -- surface any handler failure to the caller
        store.set(task_id, status="failed", error=str(exc))
        return
    store.set(
        task_id,
        status="done",
        reply={"text": reply.text, "data": reply.data},
        charges=[{"value": c.value, "currency": c.currency} for c in task.charges],
    )


class _Handler(BaseHTTPRequestHandler):
    store: _TaskStore
    runner: dict

    def log_message(self, *args) -> None:  # silence default request logging
        pass

    def _json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if self.path.startswith("/tasks/"):
            task_id = self.path[len("/tasks/"):]
            task = self.store.get(task_id)
            if task is None:
                self._json(404, {"error": "task not found"})
                return
            self._json(200, task)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/tasks":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return
        task_id = self.store.create()
        r = self.runner
        if r["is_node"]:
            target_fn = _run_task_node
            args = (task_id, self.store, body.get("text", ""), body.get("payload", {}),
                    r["target"], r["entrypoint"])
        else:
            target_fn = _run_task
            args = (task_id, self.store, body.get("text", ""), body.get("payload", {}))
        threading.Thread(target=target_fn, args=args, daemon=True).start()
        self._json(202, {"task_id": task_id})


def serve(path: str, port: int = 0) -> ThreadingHTTPServer:
    """Load grains.toml + the entrypoint and start the task API in a background thread."""
    target = Path(path).resolve()
    config = tomllib.loads((target / "grains.toml").read_text())
    entrypoint = config["agent"]["entrypoint"]
    runtime = str(config["agent"].get("runtime", "python3.12"))
    is_node = runtime.startswith(("node", "nodejs"))
    if is_node and not shutil.which("node"):
        raise RuntimeError("this is a Node agent but `node` is not on PATH")
    if not is_node:
        agent.handler(_load_entrypoint(target, entrypoint))

    store = _TaskStore()
    runner = {"is_node": is_node, "target": target, "entrypoint": entrypoint}
    bound_handler = type("_BoundHandler", (_Handler,), {"store": store, "runner": runner})
    server = ThreadingHTTPServer(("127.0.0.1", port), bound_handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def cmd_dev(args) -> int:
    server = serve(args.path, args.port)
    host, port = server.server_address
    print(f"grains dev listening on http://{host}:{port}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0
