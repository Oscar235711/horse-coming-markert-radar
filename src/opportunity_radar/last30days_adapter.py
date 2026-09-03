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
import subprocess
import sys
from threading import Event
import time
from typing import Any, Callable, Mapping


DEFAULT_HOT30_DOMAIN = "North American diesel pickup aftermarket"
DEFAULT_HOT30_SUBREDDITS = ("Cummins", "Duramax", "powerstroke", "FordDiesels")


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
            name = str(card.get("name") or "未命名热点")
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
                title = str(item.get("title") or "打开原始证据")
                published = str(item.get("published_at") or "日期未知")
                evidence_rows.append(
                    f'<li><span class="evidence-meta">{html.escape(source)} · {html.escape(published)}</span>'
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(title)}</a></li>'
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
                f'<div class="topic-summary">这是本轮模型筛选后保留的热点提名。请从下方证据链接进入原始讨论，结合上下文判断是否值得继续研究。</div>'
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


class Last30DaysAdapter(Hot30Adapter):
    """Execute the vendored, host-judged Hot 30 protocol for the local server."""

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
