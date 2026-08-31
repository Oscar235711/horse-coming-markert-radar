"""Local task-page and API contracts."""

from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Event, Thread
import time
from urllib.request import Request, urlopen

from opportunity_radar.server import RunManager, build_server
from opportunity_radar.cli import main


class BlockingApp:
    def __init__(self, report_path: Path, *, block: bool = False) -> None:
        self.report_path = report_path
        self.block = block
        self.started = Event()
        self.release = Event()
        self.calls = []

    def run(self, config, **kwargs):
        self.calls.append((config, kwargs))
        self.started.set()
        if self.block:
            self.release.wait(timeout=5)
        return {
            "run_id": kwargs["run_id"],
            "status": "completed",
            "stage": "exported",
            "artifacts": {"report_html": str(self.report_path)},
            "counts": {"candidate_count": 12},
        }

    def status(self, run_id):
        return {"run_id": run_id, "status": "completed"}

    def resume(self, run_id):
        return {"run_id": run_id, "status": "completed"}


def _payload() -> dict:
    return {
        "start_date": "2026-01-01",
        "end_date": "2026-08-31",
        "depth": "standard",
        "analysis_engine": "codex",
        "communities": ["Cummins", "Duramax", "powerstroke", "FordDiesels"],
    }


def test_run_manager_blocks_a_second_chrome_collection(tmp_path) -> None:
    """Two active OpenCLI tasks would compete for one persistent Chrome session."""
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    app = BlockingApp(report, block=True)
    manager = RunManager(app=app, config_path="config.yaml", runs_root=tmp_path, now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC))

    first = manager.create_run(_payload())
    assert app.started.wait(timeout=2)
    try:
        manager.create_run(_payload())
    except RuntimeError as error:
        assert "正在运行" in str(error)
    else:
        raise AssertionError("expected one-active-run guard")
    app.release.set()
    manager.wait(first["run_id"], timeout=2)

    assert app.calls[0][1]["analysis_engine"] == "codex"
    assert app.calls[0][1]["scope"].depth == "standard"
    assert app.calls[0][1]["selected_communities"] == tuple(_payload()["communities"])


def test_local_http_page_creates_run_and_returns_status(tmp_path) -> None:
    """The browser task page must drive the real run contract instead of only generating a command."""
    report = tmp_path / "report.html"
    report.write_text("<h1>topic report</h1>", encoding="utf-8")
    manager = RunManager(
        app=BlockingApp(report), config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    server = build_server(manager, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        home = urlopen(base + "/", timeout=3).read().decode("utf-8")
        assert "开始采集" in home
        assert "最近365天" in home
        assert "r.progress?.message" in home
        assert "r.failures" in home

        request = Request(
            base + "/api/runs",
            data=json.dumps(_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        created = json.loads(urlopen(request, timeout=3).read().decode("utf-8"))
        manager.wait(created["run_id"], timeout=2)
        status = json.loads(urlopen(base + f"/api/runs/{created['run_id']}", timeout=3).read().decode("utf-8"))
        assert status["status"] == "completed"
        report_html = urlopen(base + f"/runs/{created['run_id']}/report", timeout=3).read().decode("utf-8")
        assert "topic report" in report_html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_serve_cli_dispatches_local_host_and_port(monkeypatch, capsys) -> None:
    """The documented radar serve command must start the local task application."""
    received = {}

    def fake_serve(app, *, config_path, host, port, open_browser):
        received.update(config_path=config_path, host=host, port=port, open_browser=open_browser)
        return {"status": "stopped", "url": f"http://{host}:{port}"}

    monkeypatch.setattr("opportunity_radar.cli.serve_local", fake_serve)
    assert main([
        "serve", "--config", "configs/diesel_90d.yaml", "--host", "127.0.0.1",
        "--port", "9900", "--no-open",
    ], app=object()) == 0

    assert received == {
        "config_path": "configs/diesel_90d.yaml", "host": "127.0.0.1",
        "port": 9900, "open_browser": False,
    }
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"


def test_completed_run_can_resume_without_locking_the_task_manager(tmp_path) -> None:
    """Calling snapshot while holding a non-reentrant lock would freeze the resume endpoint."""
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    manager = RunManager(
        app=BlockingApp(report), config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    created = manager.create_run(_payload())
    manager.wait(created["run_id"], timeout=2)

    resumed = manager.resume_run(created["run_id"])
    manager.wait(created["run_id"], timeout=2)

    assert resumed["stage"] == "resume_queued"
    assert manager.snapshot(created["run_id"])["status"] == "completed"
