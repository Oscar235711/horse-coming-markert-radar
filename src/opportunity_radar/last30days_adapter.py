"""Project-local orchestration for the vendored ``last30days`` skill.

The adapter deliberately owns only filesystem boundaries and command assembly.
The vendored engine remains an unmodified snapshot; discovery retrieval is
performed only when a caller explicitly executes one of the returned commands.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Event
import time
from typing import Any, Callable, Mapping

from .hot30_overview import build_hot30_overview, _safe_int


DEFAULT_HOT30_DOMAIN = "North American diesel pickup aftermarket"
DEFAULT_HOT30_SUBREDDITS = ("Cummins", "Duramax", "powerstroke", "FordDiesels")
# ``--discover`` is intentionally limited to the four river feeds supported
# by the Skill's discovery protocol. A normal topic run uses the complete
# multi-platform source surface below; operators can still override it with
# ``RADAR_LAST30DAYS_SOURCES`` without changing code.
# Mirror the normal last30days Skill source surface.  Sources that need an
# account/key remain visible in the run's source_status as unavailable until
# configured; free/keyless sources are used immediately when their adapters
# are present.
DEFAULT_SKILL_SOURCES = (
    # X is intentionally opt-in; the project does not configure or query it.
    "reddit", "youtube", "tiktok", "instagram",
    "hackernews", "polymarket", "github", "digg", "arxiv", "techmeme", "grounding",
)


@dataclass(frozen=True)
class VendorPaths:
    """Locations in the checked-in last30days snapshot."""

    skill_dir: Path
    script_path: Path


@dataclass(frozen=True)
class Hot30RunPaths:
    """Per-run, project-controlled files for the three discovery legs."""

    root: Path
    work_dir: Path
    artifacts_dir: Path
    judgments_path: Path
    angles_path: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "work_dir": str(self.work_dir),
            "artifacts_dir": str(self.artifacts_dir),
            "judgments_path": str(self.judgments_path),
            "angles_path": str(self.angles_path),
        }


@dataclass(frozen=True)
class Hot30Artifacts:
    """Stable Radar-facing names projected from the engine's final report."""

    source_status: Path
    brief: Path
    trends: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "source_status": str(self.source_status),
            "brief": str(self.brief),
            "trends": str(self.trends),
        }


@dataclass(frozen=True)
class Hot30Commands:
    """The three engine commands for host-judged discovery."""

    nominate: tuple[str, ...]
    judge: tuple[str, ...]
    finalize: tuple[str, ...]

    def as_tuple(self) -> tuple[tuple[str, ...], ...]:
        return (self.nominate, self.judge, self.finalize)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "nominate": list(self.nominate),
            "judge": list(self.judge),
            "finalize": list(self.finalize),
        }


def project_root() -> Path:
    """Return the repository root without consulting a user skill directory."""
    return Path(__file__).resolve().parents[2]


def resolve_vendor_paths(root: Path | None = None) -> VendorPaths:
    """Resolve and validate the project-local engine entrypoint."""
    base = (root or project_root()).resolve()
    skill_dir = base / "vendor" / "last30days"
    script_path = skill_dir / "scripts" / "last30days.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Vendored last30days entrypoint is missing: {script_path}")
    return VendorPaths(skill_dir=skill_dir, script_path=script_path)


def _validate_run_id(run_id: str) -> str:
    cleaned = str(run_id or "").strip()
    candidate = Path(cleaned)
    if not cleaned or candidate.name != cleaned or cleaned in {".", ".."}:
        raise ValueError("run_id must be a single, non-empty path segment")
    return cleaned


def _json_file(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _vendor_discovery_domain(topic: str) -> str:
    """Use searchable English terms while retaining the UI's Chinese focus."""
    normalized = " ".join(str(topic or "").split())
    if not normalized:
        return DEFAULT_HOT30_DOMAIN
    if any("\u4e00" <= character <= "\u9fff" for character in normalized):
        return DEFAULT_HOT30_DOMAIN
    return normalized


Judge = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class Hot30Cancelled(RuntimeError):
    """The caller cancelled a running last30days command."""


class Hot30TimedOut(RuntimeError):
    """A last30days command exceeded the project-local deadline."""


class Hot30CommandFailed(RuntimeError):
    """A command exited unsuccessfully; its output is intentionally not persisted."""


class Hot30ModelUnavailable(Hot30CommandFailed):
    """The optional host model cannot safely complete the judgment leg."""


class Hot30Adapter:
    """Assemble a project-scoped nominate -> judge -> finalize protocol.

    ``environment`` is read only for an optional caller-owned DeepSeek client.
    Secrets are neither added to command arguments nor serialized into run files.
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        runs_root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        python_executable: str | None = None,
        judge: Judge | None = None,
        command_timeout_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.vendor = resolve_vendor_paths(self._project_root)
        self.runs_root = (runs_root or self._project_root / "outputs" / "hot30").resolve()
        self.environment = dict(environment or {})
        self.python_executable = python_executable or sys.executable
        self._judge = judge
        # A full multi-platform Skill run can legitimately exceed five
        # minutes (for example, GitHub enrichment plus Reddit retries). Keep
        # the existing 300s default for callers/tests, while allowing the
        # website operator to set a larger project-local deadline.
        if command_timeout_seconds == 300.0:
            configured_timeout = os.environ.get("RADAR_LAST30DAYS_TIMEOUT_SECONDS")
            if configured_timeout:
                try:
                    command_timeout_seconds = float(configured_timeout)
                except (TypeError, ValueError):
                    pass
        self.command_timeout_seconds = max(0.1, float(command_timeout_seconds))
        self._clock = clock or time.monotonic

    def prepare_run(self, run_id: str) -> Hot30RunPaths:
        """Create an isolated run directory without writing configuration or keys."""
        root = self.runs_root / _validate_run_id(run_id)
        work_dir = root / "work"
        artifacts_dir = root / "artifacts"
        work_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return Hot30RunPaths(
            root=root,
            work_dir=work_dir,
            artifacts_dir=artifacts_dir,
            judgments_path=work_dir / "discover-judgments.json",
            angles_path=work_dir / "discover-angles.json",
        )

    def protocol_commands(
        self,
        run: Hot30RunPaths,
        *,
        domain: str = DEFAULT_HOT30_DOMAIN,
        emit: str = "brief",
        subreddits: tuple[str, ...] = DEFAULT_HOT30_SUBREDDITS,
    ) -> Hot30Commands:
        """Build safe argv tuples; the adapter does not launch them itself."""
        normalized_domain = _vendor_discovery_domain(domain)
        normalized_subreddits = tuple(
            dict.fromkeys(
                str(value).strip().removeprefix("r/")
                for value in subreddits
                if str(value).strip()
            )
        ) or DEFAULT_HOT30_SUBREDDITS
        base = (self.python_executable, str(self.vendor.script_path), "--discover")
        subreddit_args = ("--subreddits", ",".join(normalized_subreddits))
        # ``--discover`` takes an optional positional domain. Keep the domain
        # immediately after the flag; placing another option before it makes
        # argparse treat the domain as an unexpected positional argument.
        nominate = (*base, normalized_domain, *subreddit_args, "--nominate-only", "--save-dir", str(run.work_dir))
        judge = (*base, *subreddit_args, "--judgments", str(run.judgments_path), "--save-dir", str(run.work_dir))
        finalize = (*base, *subreddit_args, "--finalize", "--angles", str(run.angles_path), f"--emit={emit}", "--save-dir", str(run.work_dir))
        return Hot30Commands(nominate=nominate, judge=judge, finalize=finalize)

    def deepseek_judge_request(self, nominations: Mapping[str, Any]) -> dict[str, Any]:
        """Return a DeepSeek-compatible JSON request without sending it.

        A configured HTTP client may submit this request and pass the parsed
        response to :meth:`write_judgments`; keeping that transport outside
        this adapter prevents credentials from entering the run directory.
        """
        return {
            "model": "deepseek-chat",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Judge discovery nominations. Return JSON only with bundle_id and judgments.",
                },
                {"role": "user", "content": json.dumps(nominations, ensure_ascii=False)},
            ],
        }

    def write_judgments(self, run: Hot30RunPaths, payload: Mapping[str, Any]) -> Path:
        """Persist host/DeepSeek judgments in the vendor handoff location."""
        return _json_file(run.judgments_path, payload)

    def write_angles(self, run: Hot30RunPaths, payload: Mapping[str, Any]) -> Path:
        """Persist host-written content angles for the finalization leg."""
        return _json_file(run.angles_path, payload)

    def judge_and_write(self, run: Hot30RunPaths, nominations: Mapping[str, Any], judge: Judge) -> Path:
        """Invoke an injected DeepSeek-compatible judge and write its JSON result."""
        return self.write_judgments(run, judge(self.deepseek_judge_request(nominations)))

    def project_finalize_output(
        self,
        run: Hot30RunPaths,
        *,
        brief: str,
        trends: Mapping[str, Any],
    ) -> Hot30Artifacts:
        """Project final output into stable artifact names for later UI work."""
        artifacts = Hot30Artifacts(
            source_status=run.artifacts_dir / "source_status.json",
            brief=run.artifacts_dir / "brief.md",
            trends=run.artifacts_dir / "trends.json",
        )
        _json_file(artifacts.source_status, dict(trends.get("source_status") or {}))
        _json_file(artifacts.trends, dict(trends))
        artifacts.brief.write_text(str(brief), encoding="utf-8")
        return artifacts

    @staticmethod
    def _write_html_brief(path: Path, brief: str, trends: Mapping[str, Any] | None = None) -> Path:
        """Render a readable visual brief from the canonical projected trends.

        The vendored Skill's markdown remains available below the fold for
        auditability, but it is no longer the primary user-facing report.
        Every visible metric and evidence link comes from ``trends.json``.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        projected = trends if isinstance(trends, Mapping) else {}
        cards = projected.get("trends") if isinstance(projected.get("trends"), list) else []
        source_status = projected.get("source_status") if isinstance(projected.get("source_status"), Mapping) else {}
        evidence_count = sum(
            len(card.get("evidence", ()))
            for card in cards
            if isinstance(card, Mapping) and isinstance(card.get("evidence"), list)
        )
        source_labels = {"reddit": "Reddit", "x": "X", "hackernews": "Hacker News", "digg": "Digg"}
        state_labels = {
            "ok": "已获取",
            "no-results": "无结果",
            "skipped-unconfigured": "未配置",
            "error": "获取失败",
        }
        source_items = []
        for source, value in source_status.items():
            if not isinstance(value, Mapping):
                continue
            label = source_labels.get(str(source).casefold(), str(source))
            state = state_labels.get(str(value.get("state") or "unknown"), str(value.get("state") or "未知"))
            count = value.get("items_returned")
            count_text = f" · {int(count)} 条" if isinstance(count, (int, float)) else ""
            source_items.append(
                f'<div class="source-card"><div class="source-name">{html.escape(label)}</div>'
                f'<div class="source-state">{html.escape(state)}{count_text}</div></div>'
            )
        source_html = "".join(source_items) or '<div class="empty">没有可展示的来源状态。</div>'

        card_items = []
        for index, card in enumerate(cards, start=1):
            if not isinstance(card, Mapping):
                continue
            name = Hot30Adapter._localized_text(card, "name", "title", default="未命名热点")
            cluster = str(card.get("cluster_id") or "未分组")
            evidence = card.get("evidence") if isinstance(card.get("evidence"), list) else []
            evidence_rows = []
            seen_urls: set[str] = set()
            for item in evidence:
                if not isinstance(item, Mapping):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                source = source_labels.get(str(item.get("source") or "").casefold(), str(item.get("source") or "来源未知"))
                title = Hot30Adapter._localized_text(item, "title", "snippet", default="打开原始证据")
                original_title = str(item.get("title") or "").strip()
                published = str(item.get("published_at") or "日期未知")
                evidence_rows.append(
                    f'<li><span class="evidence-meta">{html.escape(source)} · {html.escape(published)}</span>'
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(title)}</a>'
                    f'{f"<details class=\"original\"><summary>查看英文原题</summary><span>{html.escape(original_title)}</span></details>" if original_title and original_title != title else ""}</li>'
                )
            evidence_html = "".join(evidence_rows) or '<li class="muted">当前没有可回溯链接。</li>'
            source_names = sorted({
                source_labels.get(str(item.get("source") or "").casefold(), str(item.get("source") or "来源未知"))
                for item in evidence if isinstance(item, Mapping) and item.get("source")
            })
            source_tags = "".join(f'<span class="tag">{html.escape(label)}</span>' for label in source_names)
            card_items.append(
                f'<article class="topic-card"><div class="topic-top"><span class="rank">{index:02d}</span>'
                f'<div><h3>{html.escape(name)}</h3><div class="topic-meta">{html.escape(cluster)} · '
                f'{len(seen_urls)} 条证据 {source_tags}</div></div></div>'
                f'<div class="topic-summary">这是本轮 Skill 筛选后的热点。页面优先展示中文译文，英文原题仅在证据卡中按需展开。</div>'
                f'<details class="evidence"><summary>查看证据（{len(seen_urls)} 条）</summary><ul>{evidence_html}</ul></details></article>'
            )
        cards_html = "".join(card_items) or '<div class="empty">当前没有通过判断的热点。请检查来源状态或调整研究主题。</div>'
        window = ""
        for line in str(brief or "").splitlines():
            if line.casefold().startswith("window:"):
                window = line.split(":", 1)[1].strip()
                break
        source_count = len(source_status)
        html_document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>近30天热点雷达</title>
<style>
*{{box-sizing:border-box}}:root{{--ink:#2c2925;--muted:#7b746c;--line:#e5ddd4;--paper:#fffdf9;--accent:#bd5d30;--soft:#f5efe8;--green:#36795d}}
body{{margin:0;background:#f4f0ea;color:var(--ink);font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
.shell{{max-width:1080px;margin:0 auto;padding:38px 24px 64px}}.eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.15em;text-transform:uppercase}}
h1{{font:700 clamp(30px,5vw,46px)/1.08 Georgia,serif;margin:8px 0 8px}}h2{{font-size:19px;margin:0}}h3{{font-size:18px;margin:0 0 4px;line-height:1.3}}
.subtitle{{color:var(--muted);max-width:720px;margin:0 0 24px}}.panel{{background:rgba(255,253,249,.94);border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:0 12px 30px #604a3212;margin-top:16px}}
.hero{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end}}.hero-mark{{width:64px;height:64px;border:1px solid #d2bca8;border-radius:50%;display:grid;place-items:center;color:var(--accent);font:700 25px Georgia,serif;background:#fffaf4}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:22px}}.metric{{background:var(--soft);border-radius:12px;padding:13px 14px}}.metric b{{display:block;font-size:23px;line-height:1.1}}.metric span{{font-size:12px;color:var(--muted)}}
.section-head{{display:flex;justify-content:space-between;align-items:baseline;gap:14px;margin-bottom:14px}}.section-note{{font-size:12px;color:var(--muted)}}.sources{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}.source-card{{border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff}}.source-name{{font-weight:750}}.source-state{{color:var(--green);font-size:12px;margin-top:3px}}
.topics{{display:grid;gap:12px}}.topic-card{{background:#fff;border:1px solid var(--line);border-radius:15px;padding:17px 18px}}.topic-top{{display:flex;gap:13px;align-items:flex-start}}.rank{{width:31px;height:31px;border-radius:50%;display:grid;place-items:center;background:#f8e6d8;color:var(--accent);font-weight:800;font-size:12px;flex:none}}.topic-meta{{font-size:12px;color:var(--muted);display:flex;gap:7px;flex-wrap:wrap;align-items:center}}.tag{{border:1px solid #e4cfc1;border-radius:999px;padding:1px 7px;color:#946145;background:#fff9f4;font-size:11px}}.topic-summary{{color:#5e574f;margin:13px 0 8px;background:#faf6f1;border-radius:9px;padding:10px 12px;font-size:13px}}
details{{border-top:1px solid #eee8e1;padding-top:9px}}summary{{cursor:pointer;color:var(--accent);font-weight:700;font-size:13px}}ul{{margin:9px 0 0;padding-left:19px}}li{{margin:8px 0}}li a{{color:#8d451f;text-decoration:none}}li a:hover{{text-decoration:underline}}.evidence-meta{{display:block;color:var(--muted);font-size:11px}}.muted,.empty{{color:var(--muted)}}.empty{{padding:18px;border:1px dashed var(--line);border-radius:12px;text-align:center}}
.raw{{margin-top:18px}}.raw pre{{white-space:pre-wrap;word-break:break-word;color:#756e66;background:#faf8f5;border-radius:10px;padding:15px;max-height:420px;overflow:auto;font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}}.footer{{color:var(--muted);font-size:12px;margin-top:24px}}
@media(max-width:720px){{.shell{{padding:25px 14px 46px}}.hero{{align-items:flex-start}}.hero-mark{{display:none}}.metrics,.sources{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body><main class="shell">
<div class="eyebrow">SuncentAuto · Opportunity Radar</div><div class="hero"><div><h1>近30天热点雷达</h1>
<p class="subtitle">多平台发现 → 模型判断 → 证据下钻。这里展示的是本轮保留下来的热点提名，不把原始抓取文本直接当成结论。</p></div><div class="hero-mark">30</div></div>
<section class="panel"><div class="section-head"><h2>本轮概览</h2><span class="section-note">{html.escape(window or "时间窗口未记录")}</span></div>
<div class="metrics"><div class="metric"><b>{len(cards)}</b><span>保留热点</span></div><div class="metric"><b>{evidence_count}</b><span>证据链接</span></div><div class="metric"><b>{source_count}</b><span>来源渠道</span></div><div class="metric"><b>{html.escape(str(projected.get("status") or "未知"))}</b><span>数据状态</span></div></div></section>
<section class="panel"><div class="section-head"><h2>来源状态</h2><span class="section-note">不同来源独立显示，不代表全网覆盖率</span></div><div class="sources">{source_html}</div></section>
<section class="panel"><div class="section-head"><h2>热点卡片</h2><span class="section-note">按 Skill 返回顺序展示 · 点击证据进入原始讨论</span></div><div class="topics">{cards_html}</div></section>
<section class="panel raw"><details><summary>展开原始 last30days Skill 简报（用于复核）</summary><pre>{html.escape(brief or "当前没有原始简报")}</pre></details></section>
<div class="footer">说明：本页只重排已有 Skill 结果，不新增事实。热点名称、来源和链接均来自同一份趋势数据；请在进入产品决策前进一步核验原帖上下文。</div>
</main></body></html>"""
        path.write_text(html_document, encoding="utf-8")
        return path

    def _execution_environment(self, supplied: Mapping[str, str] | None) -> dict[str, str]:
        """Merge caller configuration only in memory for subprocesses and HTTPS."""
        merged = os.environ.copy()
        merged.update(self.environment)
        if supplied:
            merged.update({str(key): str(value) for key, value in supplied.items()})
        # The dashboard can be launched from a Windows console using a
        # legacy code page. Force UTF-8 for the vendored Python process so a
        # Chinese research question remains intact in the planner trace and
        # saved JSON rather than being converted to mojibake.
        merged.setdefault("PYTHONUTF8", "1")
        merged.setdefault("PYTHONIOENCODING", "utf-8")
        # Keep the vendored Skill self-contained on Windows.  Its free CLIs
        # may be installed into the project venv or Printing Press' per-user
        # bin directory, neither of which is guaranteed to be on the PATH of
        # a long-running dashboard process started before installation.
        path_key = "Path" if os.name == "nt" and "Path" in merged else "PATH"
        path_value = merged.get(path_key, "")
        skill_bins = [
            self._project_root / ".venv" / "Scripts",
            Path.home() / "AppData" / "Local" / "Programs" / "PrintingPress" / "bin",
            Path.home() / ".local" / "bin",
        ]
        existing: list[str] = []
        for path in skill_bins:
            # The dashboard may run in a restricted desktop process that
            # cannot stat another user-scoped directory even though the child
            # runtime can execute a binary from it.  Adding a missing path is
            # harmless; dropping it would make freshly installed Skill CLIs
            # invisible until the server is manually restarted elsewhere.
            try:
                if path.exists():
                    existing.append(str(path))
            except OSError:
                existing.append(str(path))
        if existing:
            merged[path_key] = os.pathsep.join(existing + ([path_value] if path_value else []))
        return merged

    @staticmethod
    def _stop_process(process: Any) -> None:
        """Terminate a child without exposing its stdout/stderr in an error path."""
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.communicate(timeout=1)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            process.kill()
        except OSError:
            return
        try:
            process.communicate(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _run_command(
        self,
        command: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        cancel_event: Event | None,
    ) -> str:
        """Run one protocol leg while observing cancellation and a bounded deadline."""
        if cancel_event is not None and cancel_event.is_set():
            raise Hot30Cancelled()
        process = subprocess.Popen(
            list(command),
            cwd=str(self.vendor.skill_dir),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = self._clock() + self.command_timeout_seconds
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._stop_process(process)
                raise Hot30Cancelled()
            remaining = deadline - self._clock()
            if remaining <= 0:
                self._stop_process(process)
                raise Hot30TimedOut()
            try:
                stdout, _stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0:
            # stderr can contain environment-dependent diagnostics. Keep the
            # persisted result safe and reproducible by recording only the code.
            raise Hot30CommandFailed(f"last30days exited with status {process.returncode}")
        return stdout

    @staticmethod
    def _read_object(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise Hot30CommandFailed(f"required handoff file was unavailable: {path.name}") from error
        if not isinstance(payload, dict):
            raise Hot30CommandFailed(f"required handoff file was not an object: {path.name}")
        return payload

    @staticmethod
    def _normalize_judgments(nominations: Mapping[str, Any], judged: Mapping[str, Any]) -> dict[str, Any]:
        rows = judged.get("judgments")
        return {
            "bundle_id": str(nominations.get("bundle_id") or ""),
            "judgments": [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else [],
        }

    @staticmethod
    def _model_angles(nominations: Mapping[str, Any], judged: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[str, Any]:
        """Keep only model supplied angle rows bound to surviving pending ids."""
        allowed = set((pending.get("angle_inputs") or {}).keys())
        rows = judged.get("angles")
        angles = [
            dict(row) for row in rows
            if isinstance(row, Mapping) and str(row.get("id") or "") in allowed
        ] if isinstance(rows, list) else []
        return {"bundle_id": str(nominations.get("bundle_id") or ""), "angles": angles}

    @staticmethod
    def _project_trends(nominations: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[str, Any]:
        """Deterministically expose only source evidence already present in handoffs."""
        report = pending.get("report")
        if not isinstance(report, Mapping):
            return {"status": "unknown", "trends": [], "reason": "pending_report_missing"}
        rows = nominations.get("nominations")
        if not isinstance(rows, list):
            return {"status": "unknown", "trends": [], "reason": "nomination_evidence_missing"}
        input_names = pending.get("angle_inputs")
        input_names = input_names if isinstance(input_names, Mapping) else {}
        cards: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identifier = str(row.get("id") or "")
            if identifier not in input_names:
                # ``angle_inputs`` only names rows that survived the judge leg.
                continue
            cluster_id = str(row.get("cluster_id") or "")
            nomination = row.get("nomination")
            items = nomination.get("items") if isinstance(nomination, Mapping) else None
            evidence = [
                {key: item[key] for key in ("url", "source", "title", "published_at") if key in item}
                for item in items if isinstance(item, Mapping) and item.get("url")
            ] if isinstance(items, list) else []
            if not identifier or not cluster_id or not evidence:
                continue
            name_hint = input_names.get(identifier)
            name = name_hint.get("name") if isinstance(name_hint, Mapping) else None
            if not name and isinstance(nomination, Mapping):
                name = nomination.get("name")
            cards.append({
                "id": identifier,
                "name": str(name or ""),
                "cluster_id": cluster_id,
                "evidence": evidence,
            })
        if not cards:
            return {"status": "unknown", "trends": [], "reason": "evidence_or_cluster_unavailable"}
        source_status = report.get("source_status")
        return {
            "status": "ok",
            "trends": cards,
            "source_status": dict(source_status) if isinstance(source_status, Mapping) else {},
        }

    @staticmethod
    def _http_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any]):
        from .deepseek import openai_http_transport

        return openai_http_transport(method, url, headers, payload)

    def _judge_nominations(self, nominations: Mapping[str, Any], environment: Mapping[str, str]) -> Mapping[str, Any]:
        if self._judge is not None:
            return self._judge(nominations)
        if not environment.get("DEEPSEEK_API_KEY"):
            raise Hot30ModelUnavailable("DeepSeek is not configured")
        from .deepseek import DeepSeekClient

        client = DeepSeekClient(transport=self._http_transport, environment=environment)
        try:
            response = client.chat_json((
                {"role": "system", "content": (
                    "Judge the supplied discovery nominations. Return JSON only with a judgments list; "
                    "each row has id, name, junk, worthiness. You may include an optional angles list "
                    "with id, podcast, x_article. Never invent evidence."
                )},
                {"role": "user", "content": json.dumps(nominations, ensure_ascii=False)},
            ))
        except Exception as error:
            raise Hot30ModelUnavailable("DeepSeek judgment was unavailable") from error
        return response

    @staticmethod
    def _parse_json_stdout(stdout: str) -> dict[str, Any]:
        """Parse the normal Skill JSON export without trusting incidental logs.

        The vendored CLI keeps diagnostics on stderr, but a provider or a
        wrapper may still prepend a harmless line to stdout.  Accept the first
        complete JSON object and reject anything else so a partial report is
        never presented as a successful run.
        """
        text = str(stdout or "").strip()
        candidates = [text]
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            candidates.append(text[first:last + 1])
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise Hot30CommandFailed("last30days JSON 输出无效或为空")

    @staticmethod
    def _skill_source_status(report: Mapping[str, Any]) -> dict[str, Any]:
        value = report.get("source_status")
        if not isinstance(value, Mapping):
            return {}
        return {str(key): dict(item) if isinstance(item, Mapping) else {"state": str(item)} for key, item in value.items()}

    @staticmethod
    def _skill_items(report: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
        value = report.get("items_by_source")
        if not isinstance(value, Mapping):
            return {}
        return {
            str(source): [dict(item) for item in items if isinstance(item, Mapping)]
            for source, items in value.items()
            if isinstance(items, list)
        }

    @staticmethod
    def _localized_text(row: Mapping[str, Any], *fallback_keys: str, default: str = "") -> str:
        """Choose a Chinese display value while keeping raw English in JSON.

        The vendored Skill deliberately stores source text verbatim.  The
        project report, however, is a Chinese-facing UI.  Newer runs attach
        ``*_zh`` values during the optional translation pass; this helper is
        kept defensive so older runs still render with an honest Chinese
        placeholder instead of silently exposing a long English paragraph.
        """
        for key in ("title_zh", "name_zh", "summary_zh", "snippet_zh", "tldr_zh", "translation_zh"):
            value = str(row.get(key) or "").strip()
            if value:
                return value
        for key in fallback_keys:
            value = str(row.get(key) or "").strip()
            if value:
                # Older runs predate the translation pass.  Keep their cards
                # usable with a small deterministic diesel-domain fallback;
                # the original English title remains available in the JSON
                # and evidence link for audit.
                return Hot30Adapter._fallback_translate(value)
        return default

    @staticmethod
    def _fallback_translate(value: str) -> str:
        """Translate common short source labels when no model translation exists."""
        text = " ".join(str(value or "").split()).strip()
        if not text or any("\u4e00" <= char <= "\u9fff" for char in text):
            return text
        phrases = {
            "7.3 engine replacement. upgrades to do before putting in": "7.3 发动机更换：装回前应完成哪些升级",
            "update: i think i'm finally starting to like this damn truck": "更新：我开始喜欢上这辆卡车了",
            "gmc 2500 diesel 2023 vs 2024": "GMC 2500 柴油版：2023 对比 2024",
            "semi, duramax, powerstroke, cummins etc": "半挂车、Duramax、Powerstroke、Cummins 等车型",
        }
        lowered = text.casefold()
        if lowered in phrases:
            return phrases[lowered]
        replacements = (
            (r"\bengine\b", "发动机"), (r"\breplacement\b", "更换"), (r"\bupgrade(?:s|d)?\b", "升级"),
            (r"\binstall(?:ation|ed)?\b", "安装"), (r"\brepair(?:s|ed)?\b", "维修"), (r"\bfix(?:es|ed)?\b", "修复"),
            (r"\bproblem(?:s)?\b", "问题"), (r"\bissue(?:s)?\b", "故障"), (r"\btruck(?:s)?\b", "卡车"),
            (r"\bdiesel\b", "柴油"), (r"\btowing\b", "拖挂"), (r"\btune(?:r|d|ing)?\b", "调校"),
            (r"\bdelete\b", "删除/改装"), (r"\bkit\b", "套件"), (r"\bdownpipe\b", "下降管"),
            (r"\bexhaust\b", "排气"), (r"\boil\b", "机油"), (r"\bfuel\b", "燃油"),
            (r"\bturbo\b", "涡轮"), (r"\bcoolant\b", "冷却液"), (r"\boverheating\b", "过热"),
            (r"\bbrakes?\b", "刹车"), (r"\bsteering\b", "转向"), (r"\btires?\b", "轮胎"),
            (r"\bprice(?:d)?\b", "价格"), (r"\bbuy(?:ing)?\b", "购买"), (r"\bsale\b", "出售"),
            (r"\bused\b", "二手"), (r"\bnew\b", "新"), (r"\bvs\.?\b", "对比"),
            (r"\bhelp\b", "求助"), (r"\badvice\b", "建议"), (r"\bwhat should i\b", "应该如何"),
            (r"\bneed\b", "需要"), (r"\blooking for\b", "寻找"), (r"\bhow to\b", "如何"),
            (r"\bsemi\b", "半挂车"), (r"\betc\.?\b", "等"),
        )
        translated = text
        for pattern, replacement in replacements:
            translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
        if any("\u4e00" <= char <= "\u9fff" for char in translated):
            return translated
        return "中文译文暂未生成（可展开查看英文原文）"

    @staticmethod
    def _localized_summary(row: Mapping[str, Any]) -> str:
        """Return only a translated summary; never leak a long raw snippet."""
        for key in ("summary_zh", "snippet_zh", "tldr_zh", "translation_zh"):
            value = str(row.get(key) or "").strip()
            if value:
                return value
        raw = str(row.get("snippet") or row.get("summary") or row.get("body") or "").strip()
        if not raw:
            return "中文译文暂未生成（可展开查看英文原文）"
        return Hot30Adapter._fallback_translate(raw)

    @staticmethod
    def _translate_skill_report(report: Mapping[str, Any], environment: Mapping[str, str]) -> dict[str, Any]:
        """Attach concise Chinese labels to visible Skill cards in one batch.

        Retrieval remains source-faithful: English titles/snippets are never
        replaced.  When the configured Higress DeepSeek gateway is available,
        only the short labels used by the report are sent for translation;
        failures leave the original JSON untouched so a translation outage
        cannot turn a successful retrieval into a failed run.
        """
        if not environment.get("DEEPSEEK_API_KEY"):
            return dict(report)
        ranked = report.get("ranked_candidates") if isinstance(report.get("ranked_candidates"), list) else []
        clusters = report.get("clusters") if isinstance(report.get("clusters"), list) else []
        records: list[dict[str, str]] = []
        for row in ranked[:80]:
            if not isinstance(row, Mapping):
                continue
            identifier = str(row.get("candidate_id") or row.get("item_id") or "").strip()
            title = str(row.get("title") or "").strip()
            snippet = str(row.get("snippet") or row.get("summary") or row.get("body") or "").strip()
            if identifier and (title or snippet):
                records.append({"id": f"candidate:{identifier}", "title": title[:220], "summary": snippet[:420]})
        for row in clusters[:40]:
            if not isinstance(row, Mapping):
                continue
            identifier = str(row.get("cluster_id") or row.get("id") or "").strip()
            title = str(row.get("title") or row.get("name") or "").strip()
            summary = str(row.get("summary") or row.get("tldr") or "").strip()
            if identifier and (title or summary):
                records.append({"id": f"cluster:{identifier}", "title": title[:220], "summary": summary[:420]})
        if not records:
            return dict(report)
        try:
            from .deepseek import DeepSeekClient

            client = DeepSeekClient(transport=Hot30Adapter._http_transport, environment=environment)
            translated = client.chat_json((
                {"role": "system", "content": (
                    "你是中文市场研究报告翻译器。只返回 JSON："
                    "{translations:[{id,title_zh,summary_zh}]}。将输入的英文标题和摘要准确翻译成简体中文，"
                    "保留 Reddit、车型、发动机、产品和品牌英文专名；不得添加原文没有的事实。"
                )},
                {"role": "user", "content": json.dumps({"records": records}, ensure_ascii=False)},
            ), model=environment.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash"))
            rows = translated.get("translations") if isinstance(translated, Mapping) else []
            by_id = {
                str(row.get("id")): row for row in rows
                if isinstance(row, Mapping) and str(row.get("id") or "").strip()
            } if isinstance(rows, list) else {}
            if not by_id:
                return dict(report)
        except Exception:
            return dict(report)

        # JSON round-trip gives us a detached object without sharing mutable
        # lists with the parser or the caller.
        localized = json.loads(json.dumps(report, ensure_ascii=False))
        for row in localized.get("ranked_candidates", []) if isinstance(localized.get("ranked_candidates"), list) else []:
            if not isinstance(row, dict):
                continue
            item = by_id.get(f"candidate:{row.get('candidate_id') or row.get('item_id')}")
            if isinstance(item, Mapping):
                if str(item.get("title_zh") or "").strip(): row["title_zh"] = str(item["title_zh"]).strip()
                if str(item.get("summary_zh") or "").strip(): row["summary_zh"] = str(item["summary_zh"]).strip()
        for row in localized.get("clusters", []) if isinstance(localized.get("clusters"), list) else []:
            if not isinstance(row, dict):
                continue
            item = by_id.get(f"cluster:{row.get('cluster_id') or row.get('id')}")
            if isinstance(item, Mapping):
                if str(item.get("title_zh") or "").strip(): row["title_zh"] = str(item["title_zh"]).strip()
                if str(item.get("summary_zh") or "").strip(): row["summary_zh"] = str(item["summary_zh"]).strip()
        localized["display_language"] = "zh-CN"
        localized["translation_status"] = "deepseek"
        return localized

    @staticmethod
    def _overview_snapshot(report: Mapping[str, Any]) -> dict[str, Any]:
        overview = report.get("overview") if isinstance(report.get("overview"), Mapping) else {}
        snapshot = overview.get("data_snapshot") if isinstance(overview.get("data_snapshot"), Mapping) else {}
        return dict(snapshot)

    @staticmethod
    def _overview_topics(report: Mapping[str, Any], *, watchlist: bool = False) -> list[Mapping[str, Any]]:
        overview = report.get("overview") if isinstance(report.get("overview"), Mapping) else {}
        key = "watchlist" if watchlist else "topics"
        rows = overview.get(key) if isinstance(overview.get(key), list) else []
        return [row for row in rows if isinstance(row, Mapping)]

    @staticmethod
    def _overview_brief(report: Mapping[str, Any], *, sources: tuple[str, ...], days: int) -> str:
        """Render a concise Chinese Markdown overview from canonical JSON."""
        overview = report.get("overview") if isinstance(report.get("overview"), Mapping) else {}
        snapshot = Hot30Adapter._overview_snapshot(report)
        lines = [
            "# 近30天热点总览",
            "",
            f"研究主题：{str(report.get('topic') or DEFAULT_HOT30_DOMAIN)}",
            f"时间窗口：最近 {days} 天",
            f"有效证据：{_safe_int(snapshot.get('evidence_count'))} 条 · 来源：{_safe_int(snapshot.get('source_count'))} 个 · 正式话题：{_safe_int(snapshot.get('formal_topic_count'))} 个 · 弱信号：{_safe_int(snapshot.get('weak_signal_count'))} 个",
            "",
            "## 这30天大家在讨论什么",
        ]
        summary = overview.get("executive_summary_zh") if isinstance(overview.get("executive_summary_zh"), list) else []
        if summary:
            lines.extend(f"- {str(item).strip()}" for item in summary if str(item).strip())
        else:
            lines.append(f"- {str(overview.get('headline_zh') or '当前尚未形成可验证的中文热点结论。')}")
        lines.extend(["", "## 正式热点话题"])
        topics = Hot30Adapter._overview_topics(report)
        if not topics:
            lines.append("- 当前没有达到正式证据门槛的话题。")
        for index, topic in enumerate(topics, start=1):
            lines.extend([
                f"### {index}. {str(topic.get('title_zh') or '未命名话题')}",
                str(topic.get("one_line_zh") or topic.get("discussion_zh") or "当前证据未形成一句话概括。"),
                f"- 用户在讨论什么：{str(topic.get('discussion_zh') or '证据不足')}",
                f"- 为什么值得关注：{str(topic.get('why_watch_zh') or '证据不足')}",
                f"- 机会假设：{str(topic.get('opportunity_hypothesis_zh') or '暂不形成产品机会')}",
                f"- 证据：{len(topic.get('evidence', [])) if isinstance(topic.get('evidence'), list) else 0} 条",
                "",
            ])
        watchlist = Hot30Adapter._overview_topics(report, watchlist=True)
        if watchlist:
            lines.extend(["## 弱信号观察区", ""])
            for item in watchlist:
                lines.append(f"- {str(item.get('title_zh') or '未命名')}：{str(item.get('one_line_zh') or item.get('discussion_zh') or '证据不足')}（{len(item.get('evidence', [])) if isinstance(item.get('evidence'), list) else 0} 条证据）")
        limitations = overview.get("limitations_zh") if isinstance(overview.get("limitations_zh"), list) else []
        if limitations:
            lines.extend(["", "## 数据限制", *[f"- {str(item)}" for item in limitations if str(item).strip()]])
        lines.extend(["", f"> 来源请求：{', '.join(sources)}。本页结论只代表最近 {days} 天的采集样本。"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _write_overview_html(path: Path, report: Mapping[str, Any], *, sources: tuple[str, ...], days: int) -> Path:
        """Render the Chinese-first overview page used by the dashboard."""
        path.parent.mkdir(parents=True, exist_ok=True)
        overview = report.get("overview") if isinstance(report.get("overview"), Mapping) else {}
        snapshot = Hot30Adapter._overview_snapshot(report)
        source_status = Hot30Adapter._skill_source_status(report)
        items_by_source = Hot30Adapter._skill_items(report)
        labels = {"reddit": "Reddit", "youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram", "hackernews": "Hacker News", "github": "GitHub", "digg": "Digg", "arxiv": "arXiv", "techmeme": "Techmeme", "grounding": "网页检索", "polymarket": "Polymarket"}
        states = {"ok": "已获取", "no-results": "无结果", "skipped-unconfigured": "未配置", "partial": "部分成功", "rate-limited": "被限流", "auth-failed": "需登录", "timeout": "超时", "error": "失败", "unreachable": "不可达"}
        source_cards = []
        for source in sources:
            outcome = source_status.get(source) or {}
            state = str(outcome.get("state") or "unknown") if isinstance(outcome, Mapping) else str(outcome)
            count = len(items_by_source.get(source, []))
            source_cards.append(f'<div class="source"><b>{html.escape(labels.get(source, source))}</b><span class="state">{html.escape(states.get(state, state))}</span><strong>{count:,}</strong><small>条来源证据</small></div>')

        def evidence_html(topic: Mapping[str, Any]) -> str:
            rows = topic.get("evidence") if isinstance(topic.get("evidence"), list) else []
            rendered = []
            for row in rows[:6]:
                if not isinstance(row, Mapping):
                    continue
                url = str(row.get("url") or "").strip()
                if not url:
                    continue
                title_zh = str(row.get("title_zh") or row.get("title_original") or "打开原始证据")
                excerpt_zh = str(row.get("excerpt_zh") or "中文摘录暂未生成")
                original = str(row.get("excerpt_original") or row.get("title_original") or "")
                raw = f'<details class="original"><summary>查看英文原文</summary><span>{html.escape(original[:700])}</span></details>' if original else ""
                rendered.append(f'<li><span class="evidence-source">{html.escape(labels.get(str(row.get("source") or ""), str(row.get("source") or "来源未知")))} · {html.escape(str(row.get("published_at") or "日期未知"))}</span><a href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(title_zh)}</a><p>{html.escape(excerpt_zh[:360])}</p>{raw}</li>')
            return "".join(rendered) or '<li class="muted">当前没有可回溯证据。</li>'

        def topic_card(topic: Mapping[str, Any], index: int, weak: bool = False) -> str:
            title = str(topic.get("title_zh") or "未命名话题")
            heat = topic.get("heat") if isinstance(topic.get("heat"), Mapping) else {}
            evidence = topic.get("evidence") if isinstance(topic.get("evidence"), list) else []
            raw_title = str(topic.get("title_en") or "")
            original = f'<details class="original"><summary>查看英文话题名</summary><span>{html.escape(raw_title)}</span></details>' if raw_title else ""
            heat_text = f'{_safe_int(heat.get("score"))} 分样本热度 · ' if heat.get("score") is not None else ""
            participant_text = f' · {_safe_int(heat.get("participant_count"))} 位已识别作者' if heat.get("participant_count") is not None else ""
            return f'''<article class="topic {'weak' if weak else ''}"><div class="topic-head"><em>{index:02d}</em><div><h3>{html.escape(title)}</h3>{original}<small>{heat_text}{_safe_int(heat.get("evidence_count"), len(evidence))} 条证据 · {_safe_int(heat.get("source_count"))} 个来源{participant_text} · {'弱信号' if weak else '正式热点'}</small></div></div><div class="topic-grid"><div><h4>用户在讨论什么</h4><p>{html.escape(str(topic.get("discussion_zh") or "当前证据不足"))}</p></div><div><h4>涉及场景与需求</h4><p>{html.escape(str(topic.get("user_context_zh") or topic.get("pain_need_zh") or "当前证据不足"))}</p></div><div><h4>为什么值得关注</h4><p>{html.escape(str(topic.get("why_watch_zh") or "当前证据不足"))}</p></div><div><h4>机会假设</h4><p>{html.escape(str(topic.get("opportunity_hypothesis_zh") or "暂不形成产品机会"))}</p></div></div><details class="evidence"><summary>查看代表证据（{len(evidence)} 条）</summary><ul>{evidence_html(topic)}</ul></details></article>'''

        topics = Hot30Adapter._overview_topics(report)
        watchlist = Hot30Adapter._overview_topics(report, watchlist=True)
        topic_html = "".join(topic_card(item, i) for i, item in enumerate(topics, start=1)) or '<div class="empty">当前没有达到正式证据门槛的话题。请检查分析状态或重新分析。</div>'
        watch_html = "".join(topic_card(item, i, True) for i, item in enumerate(watchlist, start=1))
        summary = overview.get("executive_summary_zh") if isinstance(overview.get("executive_summary_zh"), list) else []
        summary_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in summary if str(item).strip()) or f"<li>{html.escape(str(overview.get('headline_zh') or '中文总览尚未生成，请重新分析。'))}</li>"
        limitations = overview.get("limitations_zh") if isinstance(overview.get("limitations_zh"), list) else []
        limits_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in limitations if str(item).strip()) or "<li>本页只代表本轮采集到的公开样本。</li>"
        topic_count = _safe_int(snapshot.get("formal_topic_count"), len(topics))
        html_document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>近30天热点总览</title><style>
*{{box-sizing:border-box}}:root{{--ink:#2d2924;--muted:#776f67;--line:#e5ddd4;--paper:#fffdf9;--canvas:#f3eee8;--accent:#b9542b;--soft:#f8eee6;--green:#34775a}}body{{margin:0;background:radial-gradient(circle at 10% -10%,#fff8ef 0,#f3eee8 52%,#ece4db 100%);color:var(--ink);font:14px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}.shell{{max-width:1160px;margin:auto;padding:36px 24px 64px}}.eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}}h1{{font:700 clamp(30px,5vw,48px)/1.08 Georgia,serif;margin:8px 0}}h2{{font-size:20px;margin:0}}h3{{font-size:19px;margin:0 0 3px}}h4{{font-size:13px;margin:0 0 4px;color:#7f4329}}.subtitle,.note{{color:var(--muted)}}.subtitle{{max-width:850px;margin:0 0 22px}}.panel{{background:rgba(255,253,250,.96);border:1px solid var(--line);border-radius:18px;padding:22px;margin-top:16px;box-shadow:0 12px 30px #62472b14}}.head{{display:flex;justify-content:space-between;align-items:baseline;gap:15px;margin-bottom:14px}}.metrics{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}}.metric{{background:var(--soft);border-radius:12px;padding:13px}}.metric b{{display:block;font-size:23px}}.metric span{{font-size:12px;color:var(--muted)}}.summary{{margin:0;padding-left:20px}}.summary li{{margin:8px 0;font-size:15px}}.sources{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}}.source{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;display:grid;grid-template-columns:1fr auto;gap:2px 8px;align-items:center}}.source strong{{font-size:22px;grid-row:span 2}}.source small{{color:var(--muted);font-size:11px}}.state{{font-size:11px;color:var(--green);justify-self:end}}.topics{{display:grid;gap:14px}}.topic{{border:1px solid var(--line);border-radius:15px;background:#fff;padding:18px}}.topic.weak{{background:#fffaf5;border-style:dashed}}.topic-head{{display:flex;gap:12px;align-items:flex-start}}.topic-head em{{font-style:normal;width:32px;height:32px;display:grid;place-items:center;border-radius:50%;background:#f8e4d7;color:var(--accent);font-weight:800;font-size:12px;flex:none}}.topic-head small{{color:var(--muted);font-size:12px}}.topic-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}}.topic-grid>div{{background:#faf6f1;border-radius:10px;padding:11px 13px}}.topic-grid p{{margin:0;color:#504a44;font-size:13px}}details{{border-top:1px solid #eee8e1;padding-top:10px}}summary{{cursor:pointer;color:var(--accent);font-weight:750;font-size:13px}}ul{{margin:9px 0 0;padding-left:18px}}li{{margin:9px 0}}.evidence-source{{display:block;color:var(--muted);font-size:11px}}li a{{color:#8f431e;text-decoration:none;font-weight:750}}li a:hover{{text-decoration:underline}}li p{{margin:2px 0;color:#686057;font-size:12px}}.original{{margin-top:5px;color:var(--muted);font-size:11px}}.original summary{{font-size:11px}}.original span{{display:block;white-space:pre-wrap;word-break:break-word;color:#77706a;font-weight:400}}.empty{{padding:22px;border:1px dashed var(--line);border-radius:12px;text-align:center;color:var(--muted)}}.limits{{margin:0;padding-left:20px;color:#6d655e}}.footer{{color:var(--muted);font-size:12px;margin-top:22px}}@media(max-width:760px){{.shell{{padding:25px 14px 48px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.topic-grid{{grid-template-columns:1fr}}}}
</style></head><body><main class="shell"><div class="eyebrow">SuncentAuto · Opportunity Radar · last30days Skill</div><h1>近30天全平台 Skill 热点总览</h1><p class="subtitle">先看全局讨论，再下钻到具体话题和原始证据。正文优先使用简体中文，英文只在复核时展开。</p><section class="panel"><div class="head"><h2>本轮数据概览</h2><span class="note">最近 {days} 天 · {html.escape(str(report.get('topic') or DEFAULT_HOT30_DOMAIN))}</span></div><div class="metrics"><div class="metric"><b>{_safe_int(snapshot.get('evidence_count')):,}</b><span>有效证据</span></div><div class="metric"><b>{_safe_int(snapshot.get('source_count')):,}</b><span>来源渠道</span></div><div class="metric"><b>{topic_count:,}</b><span>正式热点</span></div><div class="metric"><b>{_safe_int(snapshot.get('weak_signal_count')):,}</b><span>弱信号</span></div><div class="metric"><b>{html.escape(str(overview.get('status') or '未知'))}</b><span>分析状态</span></div></div></section><section class="panel"><div class="head"><h2>这30天大家在讨论什么</h2><span class="note">模型归纳 · 证据约束</span></div><ul class="summary">{summary_html}</ul></section><section class="panel"><div class="head"><h2>正式热点话题</h2><span class="note">每个话题至少3条独立证据</span></div><div class="topics">{topic_html}</div></section>{f'<section class="panel"><div class="head"><h2>弱信号观察区</h2><span class="note">暂不作为正式机会</span></div><div class="topics">{watch_html}</div></section>' if watch_html else ''}<section class="panel"><div class="head"><h2>来源状态</h2><span class="note">未配置/限流平台如实显示</span></div><div class="sources">{"".join(source_cards)}</div></section><section class="panel"><div class="head"><h2>数据限制</h2></div><ul class="limits">{limits_html}</ul></section><div class="footer">本页所有数字和结论来自同一份 analysis.json。原始英文数据保留在 JSON 和证据折叠区；机会内容仅表示待验证假设。</div></main></body></html>'''
        path.write_text(html_document, encoding="utf-8")
        return path

    @staticmethod
    def _skill_brief(report: Mapping[str, Any], *, sources: tuple[str, ...], days: int) -> str:
        """Create a compact Chinese handoff for the local dashboard."""
        if isinstance(report.get("overview"), Mapping):
            return Hot30Adapter._overview_brief(report, sources=sources, days=days)
        topic = str(report.get("topic") or DEFAULT_HOT30_DOMAIN)
        source_status = Hot30Adapter._skill_source_status(report)
        items = Hot30Adapter._skill_items(report)
        clusters = report.get("clusters") if isinstance(report.get("clusters"), list) else []
        lines = [
            "# 近30天全平台 Skill 检索",
            "",
            f"研究主题：{topic}",
            f"时间窗口：最近 {days} 天",
            f"请求来源：{', '.join(sources)}",
            "",
            "## 来源状态",
        ]
        for source in sources:
            outcome = source_status.get(source) or {}
            state = outcome.get("state", "未返回") if isinstance(outcome, Mapping) else str(outcome)
            count = len(items.get(source, []))
            lines.append(f"- {source}: {state}，{count} 条")
        lines.extend(["", "## 话题聚类（来自 Skill 的标准检索结果）"])
        if not clusters:
            lines.append("- 当前没有可验证的聚类；请查看来源状态并调整主题或配置。")
        else:
            ranked = report.get("ranked_candidates") if isinstance(report.get("ranked_candidates"), list) else []
            by_id = {str(row.get("candidate_id")): row for row in ranked if isinstance(row, Mapping)}
            for index, cluster in enumerate(clusters, start=1):
                if not isinstance(cluster, Mapping):
                    continue
                title = Hot30Adapter._localized_text(cluster, "title", "name", default="未命名话题")
                candidate_ids = cluster.get("representative_ids") or cluster.get("candidate_ids") or []
                evidence = []
                for candidate_id in candidate_ids[:3] if isinstance(candidate_ids, list) else []:
                    row = by_id.get(str(candidate_id))
                    if not row:
                        continue
                    evidence_title = Hot30Adapter._localized_text(
                        row, "title", "snippet", default="打开原始证据"
                    )
                    evidence.append(f"{evidence_title} ({row.get('url') or '无链接'})")
                lines.append(f"{index}. {title}")
                if evidence:
                    lines.append("   - 代表证据：" + "；".join(evidence))
                else:
                    lines.append("   - 代表证据：当前未返回可点击证据")
        lines.extend([
            "",
            "> 说明：本文件是 vendored last30days Skill 的检索结果摘要。来源状态和证据链接以同目录的 analysis.json 为准；未配置的平台不会被伪装成已采集。",
        ])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _write_skill_html(path: Path, report: Mapping[str, Any], *, sources: tuple[str, ...], days: int) -> Path:
        """Render a self-contained visual report from one canonical JSON."""
        if isinstance(report.get("overview"), Mapping):
            return Hot30Adapter._write_overview_html(path, report, sources=sources, days=days)
        path.parent.mkdir(parents=True, exist_ok=True)
        topic = str(report.get("topic") or DEFAULT_HOT30_DOMAIN)
        source_status = Hot30Adapter._skill_source_status(report)
        items_by_source = Hot30Adapter._skill_items(report)
        clusters = report.get("clusters") if isinstance(report.get("clusters"), list) else []
        ranked = report.get("ranked_candidates") if isinstance(report.get("ranked_candidates"), list) else []
        by_id = {str(row.get("candidate_id")): row for row in ranked if isinstance(row, Mapping)}
        label_map = {
            "reddit": "Reddit", "x": "X", "youtube": "YouTube", "tiktok": "TikTok",
            "instagram": "Instagram", "hackernews": "Hacker News", "digg": "Digg",
        }
        state_map = {
            "ok": "已获取", "no-results": "无结果", "skipped-unconfigured": "未配置",
            "partial": "部分成功", "rate-limited": "被限流", "auth-failed": "需登录",
            "timeout": "超时", "error": "失败", "unreachable": "不可达",
        }
        source_cards = []
        total_items = 0
        for source in sources:
            outcome = source_status.get(source) or {}
            state = str(outcome.get("state") or "unknown") if isinstance(outcome, Mapping) else str(outcome)
            count = len(items_by_source.get(source, []))
            total_items += count
            source_cards.append(
                f'<div class="source"><b>{html.escape(label_map.get(source, source))}</b>'
                f'<span class="state {html.escape(state)}">{html.escape(state_map.get(state, state))}</span>'
                f'<strong>{count:,}</strong><small>条证据</small></div>'
            )
        topic_cards = []
        for index, cluster in enumerate(clusters, start=1):
            if not isinstance(cluster, Mapping):
                continue
            title = Hot30Adapter._localized_text(cluster, "title", "name", default="未命名话题")
            candidate_ids = cluster.get("representative_ids") or cluster.get("candidate_ids") or []
            rows = [by_id.get(str(item)) for item in candidate_ids if by_id.get(str(item))] if isinstance(candidate_ids, list) else []
            evidence_html = []
            for row in rows[:5]:
                url = str(row.get("url") or "").strip()
                if not url:
                    continue
                source = str(row.get("source") or "")
                title_text = Hot30Adapter._localized_text(row, "title", "snippet", default="查看原始证据")
                snippet = Hot30Adapter._localized_summary(row)
                original_title = str(row.get("title") or "").strip()
                original_snippet = str(row.get("snippet") or row.get("summary") or "").strip()
                original_html = (
                    f'<details class="original"><summary>查看英文原文</summary>'
                    f'<span>{html.escape(original_snippet[:600])}</span></details>'
                    if original_snippet and original_snippet != snippet else ""
                )
                evidence_html.append(
                    f'<li><span>{html.escape(label_map.get(source, source))}</span>'
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(title_text)}</a>'
                    f'{f"<p>{html.escape(snippet[:280])}</p>" if snippet else ""}{original_html}</li>'
                )
            topic_cards.append(
                f'<article class="topic"><div class="topic-head"><em>{index:02d}</em><div><h3>{html.escape(title)}</h3>'
                f'<small>{len(rows)} 条代表证据 · {html.escape(", ".join(str(s) for s in (cluster.get("sources") or [])))}</small></div></div>'
                f'<p class="topic-note">这是 Skill 的跨来源聚类结果。点击下方证据查看原始讨论；本页不把来源数量误写成市场规模。</p>'
                f'<ul>{"".join(evidence_html) or "<li class=muted>当前没有可点击的代表证据</li>"}</ul></article>'
            )
        if not topic_cards:
            topic_cards.append('<div class="empty">当前没有可展示的聚类。请检查平台配置或更换研究主题。</div>')
        html_document = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>近30天全平台 Skill 检索</title><style>
*{{box-sizing:border-box}}:root{{--ink:#28231e;--muted:#7a7167;--line:#e6ddd4;--paper:#fffdfa;--canvas:#f3eee8;--accent:#bd5c2f;--soft:#f7efe8;--green:#34775a}}
body{{margin:0;background:radial-gradient(circle at 10% -10%,#fff8ef 0,#f3eee8 50%,#ece4db 100%);color:var(--ink);font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
.shell{{max-width:1100px;margin:auto;padding:38px 24px 60px}}.eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.15em;text-transform:uppercase}}h1{{font:700 clamp(30px,5vw,45px)/1.1 Georgia,serif;margin:8px 0}}h2{{font-size:19px;margin:0}}h3{{font-size:18px;margin:0 0 3px;line-height:1.3}}.subtitle{{color:var(--muted);max-width:800px;margin:0 0 24px}}.panel{{background:rgba(255,253,250,.95);border:1px solid var(--line);border-radius:18px;padding:22px;margin-top:16px;box-shadow:0 12px 30px #62472b14}}.head{{display:flex;justify-content:space-between;align-items:baseline;gap:15px;margin-bottom:14px}}.note{{color:var(--muted);font-size:12px}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.metric{{background:var(--soft);border-radius:12px;padding:13px}}.metric b{{display:block;font-size:23px}}.metric span{{font-size:12px;color:var(--muted)}}.sources{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}.source{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;display:grid;grid-template-columns:1fr auto;gap:2px 8px;align-items:center}}.source b{{font-weight:800}}.source strong{{font-size:22px;grid-row:span 2}}.source small{{color:var(--muted);font-size:11px}}.state{{font-size:11px;color:var(--green);justify-self:end}}.state.skipped-unconfigured,.state.no-results{{color:#92713b}}.state.error,.state.auth-failed,.state.rate-limited{{color:#a43b31}}.topics{{display:grid;gap:12px}}.topic{{border:1px solid var(--line);border-radius:15px;background:#fff;padding:17px 18px}}.topic-head{{display:flex;gap:12px;align-items:flex-start}}.topic-head em{{font-style:normal;width:31px;height:31px;display:grid;place-items:center;border-radius:50%;background:#f8e4d7;color:var(--accent);font-weight:800;font-size:12px;flex:none}}.topic-head small{{color:var(--muted);font-size:12px}}.topic-note{{background:#faf6f1;color:#615950;border-radius:9px;padding:10px 12px;margin:13px 0 8px;font-size:13px}}ul{{margin:9px 0 0;padding-left:18px}}li{{margin:9px 0}}li span{{color:var(--muted);font-size:11px;display:block}}li a{{color:#8f431e;text-decoration:none;font-weight:700}}li a:hover{{text-decoration:underline}}li p{{margin:2px 0 0;color:#686057;font-size:12px}}.empty{{padding:20px;border:1px dashed var(--line);border-radius:12px;text-align:center;color:var(--muted)}}.footer{{color:var(--muted);font-size:12px;margin-top:22px}}@media(max-width:680px){{.shell{{padding:25px 14px 45px}}.metrics{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main class="shell"><div class="eyebrow">SuncentAuto · Opportunity Radar · last30days Skill</div><h1>近30天全平台 Skill 检索</h1><p class="subtitle">按研究主题调用 vendored last30days 的标准多平台流程。热点标题与摘要优先展示简体中文，英文原文仅在需要复核时展开。</p>
<section class="panel"><div class="head"><h2>本轮概览</h2><span class="note">最近 {days} 天 · {html.escape(topic)}</span></div><div class="metrics"><div class="metric"><b>{len(clusters):,}</b><span>跨平台话题</span></div><div class="metric"><b>{total_items:,}</b><span>去重后来源证据</span></div><div class="metric"><b>{sum(1 for source in sources if str((source_status.get(source) or {}).get("state")) == "ok")}</b><span>已返回来源</span></div></div></section>
<section class="panel"><div class="head"><h2>来源状态</h2><span class="note">Skill 支持的来源按实际配置显示</span></div><div class="sources">{"".join(source_cards)}</div></section>
<section class="panel"><div class="head"><h2>话题与证据</h2><span class="note">点击证据进入原始讨论</span></div><div class="topics">{"".join(topic_cards)}</div></section>
<div class="footer">说明：本页和 analysis.json 使用同一份 Skill 原始 JSON；报告只展示已返回的证据，平台覆盖取决于本机登录态、API Key、工具安装和网络状态。</div></main></body></html>'''
        path.write_text(html_document, encoding="utf-8")
        return path


class Last30DaysAdapter(Hot30Adapter):
    """Execute the vendored, host-judged Hot 30 protocol for the local server."""

    def run_multiplatform(
        self,
        topic: str,
        output_dir: Path | str,
        env: Mapping[str, str] | None = None,
        *,
        days: int = 30,
        sources: tuple[str, ...] | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Run the complete normal ``last30days`` Skill pipeline.

        This is deliberately separate from :meth:`run_hot30`: discovery mode
        has a four-source protocol (Reddit/HN/Digg/X), while a normal topic
        run is the Skill's full multi-platform path and can activate
        YouTube/TikTok/Instagram when the operator has configured them.  The
        vendored JSON is copied unchanged into ``analysis.json`` and every
        other artifact is rendered from that one object.
        """
        artifact_dir = Path(output_dir).resolve()
        root = artifact_dir.parent
        work_dir = root / "work"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        focus = " ".join(str(topic or "").split()) or DEFAULT_HOT30_DOMAIN
        try:
            days_value = max(1, int(days))
        except (TypeError, ValueError):
            days_value = 30
        configured = self.environment.get("RADAR_LAST30DAYS_SOURCES") or self.environment.get("LAST30DAYS_SKILL_SOURCES")
        raw_sources = sources or tuple(
            token.strip().lower()
            for token in (configured or ",".join(DEFAULT_SKILL_SOURCES)).split(",")
            if token.strip()
        )
        selected_sources = tuple(dict.fromkeys(raw_sources)) or DEFAULT_SKILL_SOURCES
        # High-recall defaults are intentional here.  A caller can lower them
        # via RADAR_LAST30DAYS_MAX_* without ever putting credentials into argv.
        max_results = str(self.environment.get("RADAR_LAST30DAYS_MAX_RESULTS") or "1000")
        max_per_source = str(self.environment.get("RADAR_LAST30DAYS_MAX_PER_SOURCE") or "1000")
        max_source_fetches = str(self.environment.get("RADAR_LAST30DAYS_MAX_SOURCE_FETCHES") or "10")
        command = (
            self.python_executable,
            str(self.vendor.script_path),
            focus,
            "--search", ",".join(selected_sources),
            "--deep",
            "--days", str(days_value),
            "--max-results", max_results,
            "--max-per-source", max_per_source,
            "--max-source-fetches", max_source_fetches,
            "--emit=json", "--json-profile=raw",
            "--save-dir", str(work_dir),
            "--subreddits", ",".join(DEFAULT_HOT30_SUBREDDITS),
        )
        environment = self._execution_environment(env)
        try:
            stdout = self._run_command(command, environment=environment, cancel_event=cancel_event)
            report = self._parse_json_stdout(stdout)
            raw_report = json.loads(json.dumps(report, ensure_ascii=False))
            source_data_path = work_dir / "source_data.json"
            _json_file(source_data_path, raw_report)
            # Keep the Skill's source-faithful English payload intact.  The
            # Hot30 overview layer below is the single translation/insight
            # boundary; avoiding a second legacy translation request makes
            # each run faster and keeps one canonical set of evidence fields.
            report["overview"] = build_hot30_overview(
                report,
                environment=environment,
                cache_path=work_dir / "hot30_item_analysis.jsonl",
            )
            source_status = self._skill_source_status(report)
            items_by_source = self._skill_items(report)
            clusters = report.get("clusters") if isinstance(report.get("clusters"), list) else []
            ranked = report.get("ranked_candidates") if isinstance(report.get("ranked_candidates"), list) else []
            overview = report.get("overview") if isinstance(report.get("overview"), Mapping) else {}
            overview_topics = overview.get("topics") if isinstance(overview.get("topics"), list) else []
            # The landing page exposes one Hot30 action, but the Skill has two
            # complementary surfaces: normal topic retrieval and discovery.
            # Run discovery into its own sibling directory, then keep its
            # evidence/counts in the same canonical analysis object. A failed
            # companion must remain visible without discarding successful
            # normal-topic evidence.
            discovery_dir = root / "discovery"
            try:
                discovery_result = self.run_hot30(
                    focus,
                    discovery_dir / "artifacts",
                    env=environment,
                    emit="compact",
                    cancel_event=cancel_event,
                )
            except Hot30Cancelled:
                raise
            except Exception as error:
                discovery_result = {
                    "status": "failed",
                    "stage": "discovery_failed",
                    "failures": [{"stage": "discovery", "message": f"{type(error).__name__}: discovery failed"}],
                    "counts": {},
                }
            discovery_counts = discovery_result.get("counts") if isinstance(discovery_result, Mapping) else {}
            discovery_payload: dict[str, Any] = {
                "status": str(discovery_result.get("status") or "unknown") if isinstance(discovery_result, Mapping) else "unknown",
                "stage": str(discovery_result.get("stage") or "unknown") if isinstance(discovery_result, Mapping) else "unknown",
                "counts": dict(discovery_counts) if isinstance(discovery_counts, Mapping) else {},
                "artifacts": dict(discovery_result.get("artifacts") or {}) if isinstance(discovery_result, Mapping) and isinstance(discovery_result.get("artifacts"), Mapping) else {},
            }
            if isinstance(discovery_result, Mapping) and isinstance(discovery_result.get("failures"), list):
                discovery_payload["failures"] = [dict(item) for item in discovery_result["failures"] if isinstance(item, Mapping)]
            report["discovery"] = discovery_payload
            analysis_path = artifact_dir / "analysis.json"
            _json_file(analysis_path, report)
            brief = self._skill_brief(report, sources=selected_sources, days=days_value)
            brief_md = artifact_dir / "brief.md"
            brief_md.write_text(brief, encoding="utf-8")
            brief_html = artifact_dir / "brief.html"
            self._write_skill_html(brief_html, report, sources=selected_sources, days=days_value)
            source_path = artifact_dir / "source_status.json"
            _json_file(source_path, source_status)
            trend_payload = {
                "status": "ok" if overview.get("status") == "completed" else str(overview.get("status") or ("ok" if clusters or ranked else "no-results")),
                "mode": "skill_multiplatform",
                "topic": focus,
                "days": days_value,
                "requested_sources": list(selected_sources),
                "source_status": source_status,
                "cluster_count": len(clusters),
                "overview_topic_count": len(overview_topics),
                "evidence_count": sum(len(items) for items in items_by_source.values()),
            }
            trends_path = artifact_dir / "trends.json"
            _json_file(trends_path, trend_payload)
            discovery_candidate_count = _safe_int(discovery_counts.get("candidate_count")) if isinstance(discovery_counts, Mapping) else 0
            discovery_topic_count = _safe_int(discovery_counts.get("topic_count")) if isinstance(discovery_counts, Mapping) else 0
            incomplete_source_states = {
                str(value.get("state") or "unknown").casefold()
                for value in source_status.values()
                if isinstance(value, Mapping)
                and str(value.get("state") or "unknown").casefold() not in {"ok", "no-results"}
            }
            analysis_status = str(overview.get("status") or "").casefold()
            model_incomplete = bool(environment.get("DEEPSEEK_API_KEY")) and analysis_status not in {"", "completed"}
            result_status = "degraded" if incomplete_source_states or model_incomplete else "completed"
            return {
                "mode": "skill30",
                "status": result_status,
                "stage": "exported",
                "focus": focus,
                "paths": {"root": str(root), "work_dir": str(work_dir), "artifacts_dir": str(artifact_dir)},
                "artifacts": {
                    "analysis_json": str(analysis_path),
                    "brief_html": str(brief_html),
                    "brief_md": str(brief_md),
                    "source_status": str(source_path),
                    "trends": str(trends_path),
                    "source_data": str(source_data_path),
                    "hot30_item_analysis": str(work_dir / "hot30_item_analysis.jsonl"),
                },
                "counts": {
                    "candidate_count": max(
                        _safe_int(overview.get("data_snapshot", {}).get("evidence_count")) if isinstance(overview.get("data_snapshot"), Mapping) else len(ranked),
                        discovery_candidate_count,
                    ),
                    "deep_read_count": _safe_int(overview.get("data_snapshot", {}).get("evidence_count")) if isinstance(overview.get("data_snapshot"), Mapping) else len(ranked),
                    "analyzed_posts": len(overview_topics),
                    "topic_count": max(len(overview_topics), discovery_topic_count),
                    "failure_count": sum(
                        1 for value in source_status.values()
                        if isinstance(value, Mapping)
                        and str(value.get("state")) not in {"ok", "no-results", "skipped-unconfigured"}
                    ),
                },
                "progress": {"stage": "exported", "message": "last30days Skill 已完成采集、中文提取和热点总览。" if result_status == "completed" else "last30days Skill 已完成可用来源采集，但部分来源或模型分析未完整覆盖。"},
                "protocol": {
                    "mode": "normal_topic_pipeline",
                    "sources": list(selected_sources),
                    "command": "last30days --search … --deep --emit=json",
                    "discovery": "merged",
                },
                "discovery": discovery_payload,
            }
        except Hot30Cancelled:
            return {
                "mode": "skill30", "status": "interrupted", "stage": "cancelled", "focus": focus,
                "paths": {"root": str(root), "work_dir": str(work_dir), "artifacts_dir": str(artifact_dir)},
                "progress": {"stage": "cancelled", "message": "全平台 Skill 检索已取消，已保留检查点。"},
            }
        except Hot30TimedOut:
            return {
                "mode": "skill30", "status": "failed", "stage": "skill30_timed_out", "focus": focus,
                "paths": {"root": str(root), "work_dir": str(work_dir), "artifacts_dir": str(artifact_dir)},
                "failures": [{"stage": "skill30", "message": "last30days Skill 执行超时，已终止外部检索。"}],
            }
        except Exception as error:
            return {
                "mode": "skill30", "status": "failed", "stage": "skill30_failed", "focus": focus,
                "paths": {"root": str(root), "work_dir": str(work_dir), "artifacts_dir": str(artifact_dir)},
                "failures": [{"stage": "skill30", "message": f"{type(error).__name__}: {error}"}],
            }

    def reanalyze_saved(
        self,
        artifacts_dir: Path | str,
        *,
        sources: tuple[str, ...] | None = None,
        days: int = 30,
        env: Mapping[str, str] | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Rebuild the Chinese overview from saved Skill JSON only."""
        artifact_dir = Path(artifacts_dir).resolve()
        root = artifact_dir.parent
        work_dir = root / "work"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        source_data = work_dir / "source_data.json"
        analysis_path = artifact_dir / "analysis.json"
        input_path = source_data if source_data.is_file() else analysis_path
        if not input_path.is_file():
            raise FileNotFoundError("保存的 Hot30 原始数据不存在")
        report = self._read_object(input_path)
        # Older runs predate the explicit source-data boundary. Preserve a
        # model-free copy now so every subsequent replay can avoid touching
        # the platform collectors and can restore the prior overview safely.
        if input_path == analysis_path and not source_data.is_file():
            raw_report = dict(report)
            raw_report.pop("overview", None)
            _json_file(source_data, raw_report)
        if analysis_path.is_file() and input_path != analysis_path:
            backup = artifact_dir / "analysis.pre-overview.json"
            if not backup.exists():
                shutil.copy2(analysis_path, backup)
        selected_sources = tuple(sources or tuple(str(key) for key in self._skill_source_status(report)))
        environment = self._execution_environment(env)
        if cancel_event is not None and cancel_event.is_set():
            raise Hot30Cancelled()
        overview = build_hot30_overview(
            report,
            environment=environment,
            cache_path=work_dir / "hot30_item_analysis.jsonl",
        )
        report["overview"] = overview
        _json_file(analysis_path, report)
        brief_path = artifact_dir / "brief.md"
        html_path = artifact_dir / "brief.html"
        if brief_path.is_file() and not (artifact_dir / "brief.pre-overview.md").exists():
            shutil.copy2(brief_path, artifact_dir / "brief.pre-overview.md")
        if html_path.is_file() and not (artifact_dir / "brief.pre-overview.html").exists():
            shutil.copy2(html_path, artifact_dir / "brief.pre-overview.html")
        brief = self._skill_brief(report, sources=selected_sources, days=max(1, int(days)))
        brief_path.write_text(brief, encoding="utf-8")
        self._write_skill_html(html_path, report, sources=selected_sources, days=max(1, int(days)))
        _json_file(artifact_dir / "source_status.json", self._skill_source_status(report))
        snapshot = overview.get("data_snapshot") if isinstance(overview.get("data_snapshot"), Mapping) else {}
        trends = {
            "status": str(overview.get("status") or "unknown"),
            "mode": "skill_multiplatform",
            "topic": str(report.get("topic") or DEFAULT_HOT30_DOMAIN),
            "days": max(1, int(days)),
            "requested_sources": list(selected_sources),
            "source_status": self._skill_source_status(report),
            "overview_topic_count": _safe_int(snapshot.get("formal_topic_count")),
            "evidence_count": _safe_int(snapshot.get("evidence_count")),
        }
        _json_file(artifact_dir / "trends.json", trends)
        return {
            "mode": "skill30",
            "status": "completed",
            "stage": "exported",
            "focus": str(report.get("topic") or DEFAULT_HOT30_DOMAIN),
            "artifacts": {
                "analysis_json": str(analysis_path), "brief_html": str(html_path), "brief_md": str(brief_path),
                "source_status": str(artifact_dir / "source_status.json"), "trends": str(artifact_dir / "trends.json"),
                "source_data": str(source_data), "hot30_item_analysis": str(work_dir / "hot30_item_analysis.jsonl"),
            },
            "counts": {
                "candidate_count": _safe_int(snapshot.get("evidence_count")),
                "deep_read_count": _safe_int(snapshot.get("evidence_count")),
                "analyzed_posts": _safe_int(snapshot.get("formal_topic_count")),
                "topic_count": _safe_int(snapshot.get("formal_topic_count")),
                "failure_count": 0,
            },
            "progress": {"stage": "exported", "message": "已使用保存数据重新生成中文热点总览。"},
        }

    def run_hot30(
        self,
        topic: str,
        output_dir: Path | str,
        env: Mapping[str, str] | None = None,
        emit: str = "compact",
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        artifact_dir = Path(output_dir).resolve()
        run = Hot30RunPaths(
            root=artifact_dir.parent,
            work_dir=artifact_dir.parent / "work",
            artifacts_dir=artifact_dir,
            judgments_path=artifact_dir.parent / "work" / "discover-judgments.json",
            angles_path=artifact_dir.parent / "work" / "discover-angles.json",
        )
        run.work_dir.mkdir(parents=True, exist_ok=True)
        run.artifacts_dir.mkdir(parents=True, exist_ok=True)
        commands = self.protocol_commands(run, domain=topic, emit=emit)
        environment = self._execution_environment(env)
        focus = " ".join(str(topic or "").split())
        vendor_domain = _vendor_discovery_domain(focus)
        fallback = (
            self.python_executable, str(self.vendor.script_path), "--discover",
            *( (vendor_domain,) if vendor_domain else () ), f"--emit={emit}", "--save-dir", str(run.work_dir),
            "--subreddits", ",".join(DEFAULT_HOT30_SUBREDDITS),
        )

        def artifacts_for(brief: str, trends: Mapping[str, Any], source_status: Mapping[str, Any]) -> dict[str, str]:
            brief_md = run.artifacts_dir / "brief.md"
            brief_html = run.artifacts_dir / "brief.html"
            trends_path = run.artifacts_dir / "trends.json"
            source_path = run.artifacts_dir / "source_status.json"
            brief_md.write_text(brief, encoding="utf-8")
            self._write_html_brief(brief_html, brief, trends)
            _json_file(trends_path, dict(trends))
            _json_file(source_path, dict(source_status))
            return {
                "brief_html": str(brief_html),
                "brief_md": str(brief_md),
                "trends": str(trends_path),
                "source_status": str(source_path),
            }

        nominations: Mapping[str, Any] = {}
        try:
            # Leg 1 intentionally happens even without model access: it creates
            # the canonical handoff bundle and retains the vendor's discovery
            # behavior rather than replacing it with local heuristics.
            self._run_command(commands.nominate, environment=environment, cancel_event=cancel_event)
            nominations = self._read_object(run.work_dir / "discover-nominations.json")
            judged = self._judge_nominations(nominations, environment)
            judgments = self._normalize_judgments(nominations, judged)
            self.write_judgments(run, judgments)
            self._run_command(commands.judge, environment=environment, cancel_event=cancel_event)
            pending = self._read_object(run.work_dir / "discover-pending.json")
            angles = self._model_angles(nominations, judged, pending)
            self.write_angles(run, angles)
            brief = self._run_command(commands.finalize, environment=environment, cancel_event=cancel_event)
            trends = self._project_trends(nominations, pending)
            source_status = trends.get("source_status") if isinstance(trends.get("source_status"), Mapping) else {}
            nomination_count = len(nominations.get("nominations", ())) if isinstance(nominations.get("nominations"), list) else 0
            source_items = sum(
                int(value.get("items_returned", 0) or 0)
                for value in source_status.values()
                if isinstance(value, Mapping)
            )
            judged_rows = judgments.get("judgments") if isinstance(judgments, Mapping) else None
            judged_count = len(judged_rows) if isinstance(judged_rows, list) else 0
            topic_count = len(trends.get("trends", ())) if isinstance(trends.get("trends"), list) else 0
            return {
                "mode": "hot30", "status": "completed", "stage": "exported", "focus": focus,
                "paths": run.as_dict(), "artifacts": artifacts_for(brief, trends, source_status),
                "counts": {
                    "candidate_count": max(source_items, nomination_count),
                    "deep_read_count": 0,
                    "analyzed_posts": judged_count,
                    "topic_count": topic_count,
                    "failure_count": 0,
                },
                "progress": {"stage": "exported", "message": "近30天多平台热点研究已完成。"},
                "protocol": {"mode": "host_judged", "angles": "model" if angles["angles"] else "empty_no_safe_angle_generation"},
            }
        except Hot30Cancelled:
            return {
                "mode": "hot30", "status": "interrupted", "stage": "cancelled", "focus": focus,
                "paths": run.as_dict(), "progress": {"stage": "cancelled", "message": "热点研究已取消，已终止外部采集。"},
            }
        except Hot30TimedOut:
            return {
                "mode": "hot30", "status": "failed", "stage": "hot30_timed_out", "focus": focus,
                "paths": run.as_dict(), "failures": [{"stage": "hot30", "message": "last30days 执行超时，已终止外部采集。"}],
            }
        except Exception as error:
            # One (and only one) one-shot sweep is the documented recovery for
            # missing host judgment or a failed handoff leg. Its compact output
            # is a real engine brief, but it lacks trusted handoff evidence, so
            # trends are explicitly unknown instead of locally fabricated.
            try:
                brief = self._run_command(fallback, environment=environment, cancel_event=cancel_event)
            except Hot30Cancelled:
                return {
                    "mode": "hot30", "status": "interrupted", "stage": "cancelled", "focus": focus,
                    "paths": run.as_dict(), "progress": {"stage": "cancelled", "message": "热点研究已取消，已终止外部采集。"},
                }
            except Hot30TimedOut:
                return {
                    "mode": "hot30", "status": "failed", "stage": "hot30_timed_out", "focus": focus,
                    "paths": run.as_dict(), "failures": [{"stage": "hot30", "message": "last30days 执行超时，已终止外部采集。"}],
                }
            except Exception:
                return {
                    "mode": "hot30", "status": "failed", "stage": "hot30_failed", "focus": focus,
                    "paths": run.as_dict(), "failures": [{"stage": "hot30", "message": "last30days 多平台流程未能完成。"}],
                }
            trends = {"status": "unknown", "trends": [], "reason": "host_judgment_unavailable"}
            source_status = {"status": "unknown", "reason": "host_judgment_unavailable"}
            if isinstance(error, Hot30ModelUnavailable):
                # A configured gateway can still fail at the transport or
                # response-validation boundary.  Do not misreport that as a
                # missing key; operators need the actionable distinction.
                message = (
                    "DeepSeek调用失败，已降级为单次扫描；趋势不可用。"
                    if environment.get("DEEPSEEK_API_KEY")
                    else "DeepSeek未配置，已降级为单次扫描；趋势不可用。"
                )
            else:
                message = "模型判断不可用，已降级为单次扫描；趋势不可用。"
            return {
                "mode": "hot30", "status": "degraded", "stage": "hot30_degraded", "focus": focus,
                "paths": run.as_dict(), "artifacts": artifacts_for(brief, trends, source_status),
                "counts": {
                    "candidate_count": len(nominations.get("nominations", ())) if isinstance(nominations, Mapping) and isinstance(nominations.get("nominations"), list) else 0,
                    "deep_read_count": 0,
                    "analyzed_posts": 0,
                    "topic_count": 0,
                    "failure_count": 1,
                },
                "progress": {"stage": "hot30_degraded", "message": message},
                "failures": [{"stage": "host_judgment", "message": message}],
                "protocol": {"mode": "one_shot_fallback", "angles": "not_generated_without_host_judgment"},
            }
