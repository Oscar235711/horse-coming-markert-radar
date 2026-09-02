"""Local task-page and API contracts."""

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from threading import Event, Thread
import time
from types import ModuleType
from urllib.request import Request, urlopen

from opportunity_radar.server import RunManager, ScheduleManager, build_server
from opportunity_radar.cli import build_parser, main
from opportunity_radar.dashboard import dashboard_html


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
        "keywords": ["cummins"],
    }


def test_dashboard_offers_multiplatform_hot30_and_reddit_range_modes() -> None:
    """The landing page must make the two research contracts explicit."""
    page = dashboard_html(("Cummins", "Duramax"), ("cummins",))

    assert 'data-mode="hot30"' in page
    assert 'data-mode="range"' in page
    assert "多平台热点" in page
    assert "Reddit 时间范围研究" in page
    assert "四个核心社区只是后台种子" in page


def test_hot30_accepts_missing_focus_and_uses_local_adapter(tmp_path, monkeypatch) -> None:
    """Dropping the hot30 default topic or adapter call would break the new entry point."""
    calls = []
    module = ModuleType("opportunity_radar.last30days_adapter")

    class Adapter:
        def run_hot30(self, topic, output_dir, env=None, emit="compact", cancel_event=None):
            calls.append((topic, Path(output_dir), env, emit, cancel_event))
            artifact_dir = Path(output_dir)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for name in ("brief.html", "brief.md", "trends.json", "source_status.json"):
                (artifact_dir / name).write_text(name, encoding="utf-8")
            return {
                "status": "completed",
                "stage": "exported",
                "artifacts": {
                    "brief_html": str(artifact_dir / "brief.html"),
                    "brief_md": str(artifact_dir / "brief.md"),
                    "trends": str(artifact_dir / "trends.json"),
                    "source_status": str(artifact_dir / "source_status.json"),
                },
            }

    module.Last30DaysAdapter = Adapter
    monkeypatch.setitem(sys.modules, "opportunity_radar.last30days_adapter", module)
    manager = RunManager(
        app=object(), config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )

    created = manager.create_run({"mode": "hot30"})
    manager.wait(created["run_id"], timeout=2)
    state = manager.snapshot(created["run_id"])

    assert state["mode"] == "hot30"
    assert state["focus"] == "北美柴油皮卡改装"
    assert calls[0][0] == "北美柴油皮卡改装"
    assert calls[0][3] == "compact"
    assert isinstance(calls[0][4], Event)
    assert manager.artifact_path(created["run_id"], "brief_html").name == "brief.html"
    persisted = json.loads((tmp_path / created["run_id"] / "state.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"


def test_range_requires_dates_but_accepts_an_optional_focus(tmp_path) -> None:
    """A missing range boundary is invalid, while an omitted question remains compatible."""
    manager = RunManager(
        app=BlockingApp(tmp_path / "report.html"), config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )

    try:
        manager.create_run({"mode": "range", "focus": "拖挂高温"})
    except ValueError as error:
        assert "无效采集日期" in str(error)
    else:
        raise AssertionError("range mode must require start and end dates")

    validated = manager._validate_payload({
        "mode": "range", "start_date": "2026-08-01", "end_date": "2026-08-31",
    })
    assert validated[5] == "柴油皮卡改装市场机会扫描"


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


def test_active_run_can_be_cancelled_and_cannot_overwrite_interrupted_state(tmp_path) -> None:
    """Cancellation must take effect immediately and remain interrupted after the worker returns."""
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    app = BlockingApp(report, block=True)
    manager = RunManager(
        app=app, config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )

    created = manager.create_run(_payload())
    assert app.started.wait(timeout=2)

    cancelled = manager.cancel_run(created["run_id"])
    assert cancelled["status"] == "interrupted"
    assert cancelled["stage"] == "cancelled"

    app.release.set()
    manager.wait(created["run_id"], timeout=2)
    assert manager.snapshot(created["run_id"])["status"] == "interrupted"


def test_local_http_page_exposes_cancel_endpoint_for_active_run(tmp_path) -> None:
    """The browser must offer a direct cancel action instead of requiring a process kill."""
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    app = BlockingApp(report, block=True)
    manager = RunManager(
        app=app, config_path="config.yaml", runs_root=tmp_path,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    server = build_server(manager, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        home = urlopen(base + "/", timeout=3).read().decode("utf-8")
        assert "取消任务" in home
        request = Request(
            base + "/api/runs", data=json.dumps(_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        created = json.loads(urlopen(request, timeout=3).read().decode("utf-8"))
        assert app.started.wait(timeout=2)
        cancel_request = Request(base + f"/api/runs/{created['run_id']}/cancel", method="POST")
        cancelled = json.loads(urlopen(cancel_request, timeout=3).read().decode("utf-8"))
        assert cancelled["status"] == "interrupted"
        app.release.set()
        manager.wait(created["run_id"], timeout=2)
    finally:
        app.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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
        assert "取消请求失败" in home
        assert "删除请求失败" in home

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


def test_unlimited_complete_mode_is_the_default_user_entrypoint() -> None:
    """A new run must not silently fall back to the capped standard preset."""
    arguments = build_parser().parse_args(["run", "--config", "configs/diesel_90d.yaml"])
    assert arguments.depth == "complete"
    page = dashboard_html(("Cummins",), ("cummins",))
    assert '<option value="complete" selected>' in page
    assert "完整模式不设项目数量上限" in page


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


def test_schedule_manager_persists_rolling_window_and_toggles(tmp_path) -> None:
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    manager = RunManager(app=BlockingApp(report), config_path="config.yaml", runs_root=tmp_path,
                         now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC))
    schedules = ScheduleManager(manager, tmp_path / "schedules.json",
                                now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC))
    created = schedules.create({
        "name": "每周扫描", "frequency": "weekly", "at_time": "09:00",
        "window_days": 90, "depth": "standard", "communities": ["cummins"],
        "keywords": ["cummins"],
    })
    assert created["enabled"] is True
    assert created["next_run_at"].startswith("2026-09-07T09:00")
    toggled = schedules.toggle(created["schedule_id"])
    assert toggled["enabled"] is False
    assert schedules.list()[0]["keywords"] == ["cummins"]


def test_schedule_api_creates_and_lists_schedule(tmp_path) -> None:
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    manager = RunManager(app=BlockingApp(report), config_path="config.yaml", runs_root=tmp_path,
                         now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC))
    schedules = ScheduleManager(manager, tmp_path / "schedules.json",
                                now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC))
    server = build_server(manager, schedule_manager=schedules, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = Request(base + "/api/schedules", data=json.dumps({
            "name": "定时测试", "frequency": "daily", "at_time": "09:00",
            "window_days": 30, "depth": "quick", "communities": ["Cummins"], "keywords": ["cummins"],
        }).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        created = json.loads(urlopen(request, timeout=3).read().decode("utf-8"))
        rows = json.loads(urlopen(base + "/api/schedules", timeout=3).read().decode("utf-8"))["schedules"]
        assert rows[0]["schedule_id"] == created["schedule_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_local_http_page_can_delete_a_finished_run(tmp_path) -> None:
    """Deleting a finished run removes only its local run directory."""
    report = tmp_path / "report.html"
    report.write_text("report", encoding="utf-8")
    runs_root = tmp_path / "runs"
    manager = RunManager(
        app=BlockingApp(report), config_path="config.yaml", runs_root=runs_root,
        now=lambda: datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    server = build_server(manager, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = Request(
            base + "/api/runs", data=json.dumps(_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        created = json.loads(urlopen(request, timeout=3).read().decode("utf-8"))
        manager.wait(created["run_id"], timeout=2)
        delete_request = Request(base + f"/api/runs/{created['run_id']}", method="DELETE")
        deleted = json.loads(urlopen(delete_request, timeout=3).read().decode("utf-8"))
        assert deleted == {"status": "deleted", "run_id": created["run_id"]}
        assert not (runs_root / created["run_id"]).exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
