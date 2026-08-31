"""Localhost task page and JSON API for Opportunity Radar runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import RLock, Thread
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
import webbrowser

from .models import CollectionScope


FIXED_COMMUNITIES = ("Cummins", "Duramax", "powerstroke", "FordDiesels")


class RunManager:
    """Serialize Chrome-backed collections and expose secret-free run state."""

    def __init__(
        self,
        *,
        app: Any,
        config_path: str | Path,
        runs_root: str | Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._app = app
        self._config_path = str(config_path)
        self._runs_root = Path(runs_root).resolve()
        self._runs_root.mkdir(parents=True, exist_ok=True)
        self._now = now or datetime.now
        self._lock = RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, Thread] = {}

    def create_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        scope, communities, engine = self._validate_payload(payload)
        with self._lock:
            if any(state.get("status") in {"queued", "running"} for state in self._states.values()):
                raise RuntimeError("已有Reddit采集任务正在运行，请等待完成后再启动。")
            run_id = self._now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
            state = {
                "run_id": run_id,
                "status": "queued",
                "stage": "queued",
                "start_date": scope.start_date.isoformat(),
                "end_date": scope.end_date.isoformat(),
                "depth": scope.depth,
                "analysis_engine": engine,
                "selected_communities": list(communities),
                "counts": {},
                "artifacts": {},
                "failures": [],
            }
            self._states[run_id] = state
            thread = Thread(
                target=self._execute,
                args=(run_id, scope, communities, engine),
                name=f"radar-{run_id}",
                daemon=True,
            )
            self._threads[run_id] = thread
            thread.start()
            return dict(state)

    def resume_run(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        with self._lock:
            if any(state.get("status") in {"queued", "running"} for state in self._states.values()):
                raise RuntimeError("已有Reddit采集任务正在运行，请等待完成后再继续。")
            state = self.snapshot(run_id)
            state["status"] = "queued"
            state["stage"] = "resume_queued"
            self._states[run_id] = state
            thread = Thread(target=self._resume, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
            thread.start()
            return dict(state)

    def list_runs(self) -> list[dict[str, Any]]:
        run_ids = set(self._states)
        run_ids.update(path.name for path in self._runs_root.iterdir() if path.is_dir())
        rows = []
        for run_id in sorted(run_ids, reverse=True):
            try:
                rows.append(self.snapshot(run_id))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
        return rows

    def snapshot(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        with self._lock:
            memory = dict(self._states.get(run_id, {}))
        state_path = self._runs_root / run_id / "state.json"
        if state_path.exists():
            disk = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(disk, Mapping):
                memory = {**memory, **dict(disk)}
        if not memory:
            raise FileNotFoundError(run_id)
        return memory

    def wait(self, run_id: str, *, timeout: float | None = None) -> None:
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout=timeout)

    def artifact_path(self, run_id: str, name: str) -> Path:
        state = self.snapshot(run_id)
        artifact_keys = {
            "report_html": "report_html",
            "analysis_json": "analysis_json",
            "workbook": "community_topics_xlsx",
        }
        configured = state.get("artifacts", {}).get(artifact_keys[name]) if isinstance(state.get("artifacts"), Mapping) else None
        fallback_names = {
            "report_html": "report.html",
            "analysis_json": "analysis.json",
            "workbook": "community_topics.xlsx",
        }
        target = Path(str(configured)) if configured else self._runs_root / run_id / "artifacts" / fallback_names[name]
        target = target.resolve()
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target

    def _execute(self, run_id: str, scope: CollectionScope, communities: tuple[str, ...], engine: str) -> None:
        self._set_state(run_id, status="running", stage="configured")
        try:
            result = self._app.run(
                self._config_path,
                run_id=run_id,
                scope=scope,
                analysis_engine=engine,
                selected_communities=communities,
            )
            self._replace_state(run_id, result)
        except Exception as error:
            self._set_state(
                run_id,
                status="failed",
                stage="failed",
                failures=[{"stage": "run", "message": f"{type(error).__name__}: {error}"}],
            )

    def _resume(self, run_id: str) -> None:
        self._set_state(run_id, status="running", stage="resuming")
        try:
            self._replace_state(run_id, self._app.resume(run_id))
        except Exception as error:
            self._set_state(run_id, status="failed", stage="failed", failures=[{"stage": "resume", "message": str(error)}])

    def _replace_state(self, run_id: str, result: Mapping[str, Any]) -> None:
        with self._lock:
            prior = self._states.get(run_id, {})
            self._states[run_id] = {**prior, **dict(result)}

    def _set_state(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            self._states[run_id] = {**self._states.get(run_id, {"run_id": run_id}), **changes}

    def _validate_payload(self, payload: Mapping[str, Any]) -> tuple[CollectionScope, tuple[str, ...], str]:
        try:
            scope = CollectionScope(
                date.fromisoformat(str(payload["start_date"])),
                date.fromisoformat(str(payload["end_date"])),
                str(payload.get("depth", "standard")),
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"无效采集日期或深度：{error}") from error
        today = self._now().date()
        if scope.end_date > today:
            raise ValueError("结束日期不能晚于今天。")
        raw_communities = payload.get("communities", FIXED_COMMUNITIES)
        if not isinstance(raw_communities, list) or not raw_communities:
            raise ValueError("至少选择一个社区。")
        canonical = {item.casefold(): item for item in FIXED_COMMUNITIES}
        requested = tuple(dict.fromkeys(str(item).strip() for item in raw_communities if str(item).strip()))
        unknown = [item for item in requested if item.casefold() not in canonical]
        if unknown:
            raise ValueError(f"不支持的社区：{', '.join(unknown)}")
        communities = tuple(canonical[item.casefold()] for item in requested)
        engine = str(payload.get("analysis_engine", "codex"))
        if engine != "codex":
            raise ValueError("当前网页任务仅支持Codex分析。")
        return scope, communities, engine

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("invalid run id")


def build_server(manager: RunManager, *, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path == "/":
                    return self._html(_dashboard_html())
                if path == "/api/runs":
                    return self._json({"runs": manager.list_runs()})
                parts = [part for part in path.split("/") if part]
                if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                    return self._json(manager.snapshot(parts[2]))
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "analysis":
                    return self._file(manager.artifact_path(parts[2], "analysis_json"), "application/json; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "report":
                    return self._file(manager.artifact_path(parts[1], "report_html"), "text/html; charset=utf-8")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "workbook":
                    return self._file(manager.artifact_path(parts[1], "workbook"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                return self._error(HTTPStatus.NOT_FOUND, "页面不存在")
            except FileNotFoundError:
                return self._error(HTTPStatus.NOT_FOUND, "任务或产物不存在")
            except ValueError as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path == "/api/runs":
                    return self._json(manager.create_run(self._read_json()), status=HTTPStatus.ACCEPTED)
                parts = [part for part in path.split("/") if part]
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "resume":
                    return self._json(manager.resume_run(parts[2]), status=HTTPStatus.ACCEPTED)
                return self._error(HTTPStatus.NOT_FOUND, "接口不存在")
            except RuntimeError as error:
                return self._error(HTTPStatus.CONFLICT, str(error))
            except (ValueError, json.JSONDecodeError) as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _read_json(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("请求必须是JSON对象")
            return value

        def _json(self, value: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def _html(self, value: str) -> None:
            self._send(value.encode("utf-8"), "text/html; charset=utf-8", HTTPStatus.OK)

        def _file(self, path: Path, content_type: str) -> None:
            self._send(path.read_bytes(), content_type, HTTPStatus.OK)

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._json({"status": "error", "message": message}, status=status)

        def _send(self, body: bytes, content_type: str, status: HTTPStatus) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def serve_local(
    app: Any,
    *,
    config_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> dict[str, Any]:
    runs_root = getattr(app, "runs_root", Path.cwd() / ".local" / "runs")
    manager = RunManager(app=app, config_path=config_path, runs_root=runs_root)
    server = build_server(manager, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"status": "stopped", "url": url}


def _dashboard_html() -> str:
    communities = "".join(
        f'<label class="community"><input type="checkbox" name="community" value="{name}" checked> r/{name}</label>'
        for name in FIXED_COMMUNITIES
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Opportunity Radar</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f0ea;color:#24211e;font:14px system-ui,sans-serif}}main{{max-width:1080px;margin:0 auto;padding:38px 22px}}h1{{font:700 34px Georgia,serif;margin:0}}.sub{{color:#756f67;margin:8px 0 28px}}.panel{{background:#fff;border:1px solid #ded8cf;border-radius:16px;padding:22px;box-shadow:0 14px 35px #675b4a12}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.field label.title{{display:block;font-weight:650;margin-bottom:8px}}input[type=date],select{{width:100%;padding:11px;border:1px solid #d8d1c7;border-radius:9px;background:#fff}}.presets{{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}}button{{border:0;border-radius:9px;padding:10px 14px;cursor:pointer}}.preset{{background:#eee9e2;color:#5f584f}}.primary{{background:#d76d28;color:#fff;font-weight:700;font-size:15px}}.communities{{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}}.community{{padding:10px;border:1px solid #e3ddd5;border-radius:9px}}.actions{{display:flex;align-items:center;gap:12px;margin-top:20px}}#message{{color:#87602f}}.runs{{margin-top:24px}}.run{{background:#fff;border:1px solid #e0dad2;border-radius:12px;padding:15px;margin:9px 0;display:flex;justify-content:space-between;gap:15px}}.meta{{color:#787169;font-size:12px;margin-top:5px}}.progress{{color:#805a2d;font-size:12px;margin-top:5px}}.failure{{color:#a33f34;font-size:12px;margin-top:5px}}a{{color:#b85218;text-decoration:none;font-weight:650}}@media(max-width:700px){{.grid,.communities{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>Opportunity Radar</h1><div class="sub">选择社区和时间范围，直接采集Reddit并由本机Codex生成可追溯报告。</div><section class="panel"><div class="grid"><div class="field"><label class="title">时间范围</label><div class="presets"><button class="preset" data-days="30">最近30天</button><button class="preset" data-days="90">最近90天</button><button class="preset" data-days="180">最近180天</button><button class="preset" data-days="365">最近365天</button></div><div class="grid"><input id="start" type="date"><input id="end" type="date"></div></div><div class="field"><label class="title">采集深度</label><select id="depth"><option value="quick">快速 · 30篇/社区</option><option value="standard" selected>标准 · 80篇/社区</option><option value="deep">深度 · 150篇/社区</option></select><p class="meta">列表最多约1,000篇/社区；覆盖不足会明确标记为“部分覆盖”。</p></div><div class="field"><label class="title">固定社区</label><div class="communities">{communities}</div></div><div class="field"><label class="title">分析方式</label><div class="community">本机Codex · 只读 · 结构化证据分析</div></div></div><div class="actions"><button id="start-run" class="primary">开始采集</button><span id="message"></span></div></section><section class="runs"><h2>任务记录</h2><div id="runs"></div></section></main><script>
const iso=d=>d.toISOString().slice(0,10);function preset(days){{const end=new Date(),start=new Date();start.setDate(end.getDate()-days+1);document.querySelector('#start').value=iso(start);document.querySelector('#end').value=iso(end)}}document.querySelectorAll('[data-days]').forEach(b=>b.onclick=()=>preset(Number(b.dataset.days)));preset(90);
async function refresh(){{const data=await fetch('/api/runs').then(r=>r.json());document.querySelector('#runs').innerHTML=(data.runs||[]).map(r=>`<div class="run"><div><b>${{r.run_id}}</b><div class="meta">${{r.start_date||r.collection_scope?.start_date||''}} → ${{r.end_date||r.collection_scope?.end_date||''}} · ${{r.depth||r.collection_scope?.depth||''}} · ${{r.stage||''}}</div><div class="progress">${{r.progress?.message||''}} ${{r.progress?.total?`(${{r.progress.completed||0}}/${{r.progress.total}})`:''}}</div><div class="failure">${{(r.failures||[]).slice(0,2).map(f=>f.message||f.stage).join('；')}}</div></div><div>${{r.status==='completed'?`<a href="/runs/${{r.run_id}}/report">打开报告</a> · <a href="/runs/${{r.run_id}}/workbook">下载Excel</a>`:r.status}}</div></div>`).join('')||'<div class="meta">尚无任务</div>'}}
document.querySelector('#start-run').onclick=async()=>{{const message=document.querySelector('#message');message.textContent='正在创建任务…';const payload={{start_date:document.querySelector('#start').value,end_date:document.querySelector('#end').value,depth:document.querySelector('#depth').value,analysis_engine:'codex',communities:[...document.querySelectorAll('[name=community]:checked')].map(x=>x.value)}};const response=await fetch('/api/runs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});const result=await response.json();message.textContent=response.ok?'任务已启动，可在下方查看进度':result.message;refresh()}};refresh();setInterval(refresh,2500);
</script></body></html>"""
