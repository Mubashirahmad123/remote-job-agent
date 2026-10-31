"""Background scrape-run registry (Phase 2 actions).

A full scrape (scrape_all -> curate) takes minutes, so POST /api/scrape only
*starts* a daemon-thread run and returns a run_id immediately; clients poll
GET /api/scrape/{run_id}. Lazy-import rule applies: pipeline modules are
imported inside the worker, never at module import (agents/curator.py:57-79
parses the CV on import). Only one active run at a time (409 on overlap).

Run dict: {run_id, status, phase, scraped, curated, error,
            started_at, finished_at}. status: queued|running|done|error.

No watchdog, deliberately (AUDIT B9, 2026-10-28): the worker is a plain
thread, and Python cannot terminate a hung thread — a watchdog could only
flip the record to "error" while the thread kept consuming resources, and
freeing the budget would let a second scrape start beside the hung one.
The registry is also in-memory by design, so the operator recovery is
defined and safe: `docker compose restart api` empties `_runs`, which
clears the 409 and lets a new run start; nothing on disk (Sheets, caches,
tracker files) is touched or left stale by a restart, and the hung thread
dies with the process. A single hung run blocking the "run" action budget
until restart is the accepted trade-off.
"""

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CURATED_JOBS_PATH = PROJECT_ROOT / "curated_jobs.json"

_lock = threading.Lock()
_runs: Dict[str, Dict[str, Any]] = {}
_MAX_KEPT = 20
_MAX_EVENTS = 120


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _public(run: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in run.items() if not key.startswith("_")}


def _add_event(
    run: Dict[str, Any],
    message: str,
    level: str = "info",
    event_type: str = "status",
    board: str = "",
) -> None:
    """Append a compact structured event while holding the registry lock."""
    events = run.setdefault("events", [])
    sequence = run.get("_event_sequence", 0) + 1
    run["_event_sequence"] = sequence
    events.append({
        "sequence": sequence,
        "timestamp": _now_iso(),
        "level": level,
        "type": event_type,
        "board": board,
        "message": message,
    })
    del events[:-_MAX_EVENTS]


def _board_snapshot(boards: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return JSON-safe board diagnostics without exposing tracker internals."""
    snapshot = {}
    for name, entry in (boards or {}).items():
        if not isinstance(entry, dict):
            continue
        snapshot[str(name)] = {
            key: entry[key]
            for key in ("status", "fetched", "error", "updated_at")
            if key in entry
        }
    return snapshot


def list_runs() -> List[Dict[str, Any]]:
    with _lock:
        ordered = sorted(_runs.values(), key=lambda r: r["started_at"], reverse=True)
        return [_public(r) for r in ordered]


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        run = _runs.get((run_id or "").strip())
        return _public(run) if run else None


def active_run() -> Optional[Dict[str, Any]]:
    with _lock:
        for run in _runs.values():
            if run["status"] in ("queued", "running"):
                return _public(run)
    return None


def _run_simple_pipeline(progress, tracker=None) -> Dict[str, int]:
    """Execute scrape_all -> curate (mirrors main.run_simple_scraper).

    progress(phase, scraped) reports coarse phases. Shares the caller's
    YieldTracker (created by the worker) so the pump can read per-board
    stats live. Returns counts plus a board summary. Separated for tests:
    monkeypatch this, never the real pipeline.
    """
    from agents.curator import curate
    from agents.scrapper import scrape_all
    from tools.yield_tracker import YieldTracker

    tracker = tracker or YieldTracker()
    progress("scraping", 0)
    jobs = scrape_all(debug=False, tracker=tracker)
    progress("curating", len(jobs))
    result = curate(jobs or [], tracker=tracker)
    top = result.get("top_jobs", []) if isinstance(result, dict) else []
    _write_curated_cache(jobs or [], top)
    try:
        tracker.save()
    except Exception:
        pass
    summary = _summarize_boards(tracker.snapshot(), _board_total())
    summary["scraped"] = len(jobs or [])
    summary["curated"] = len(top)
    return summary


def _summarize_boards(boards: Dict[str, Dict[str, Any]], total: int) -> Dict[str, int]:
    """Pure per-board rollup: done/failed/empty counts + fetched sum."""
    done = failed = empty = fetched = 0
    for entry in (boards or {}).values():
        if not isinstance(entry, dict):
            continue
        status = (entry.get("status") or "")
        if status == "error":
            failed += 1
        elif status == "empty" or status.startswith("skipped"):
            empty += 1
        elif status == "ok":
            done += 1
        try:
            fetched += int(entry.get("fetched", 0) or 0)
        except (TypeError, ValueError):
            pass
    return {
        "boards_total": total,
        "boards_done": done + failed + empty,
        "boards_ok": done,
        "boards_failed": failed,
        "boards_empty": empty,
        "fetched": fetched,
    }


def _write_curated_cache(jobs: list, top_jobs: list) -> None:
    """Mirror main.run_simple_scraper: cache score>=70 jobs to curated_jobs.json.

    Keeps the API enrichment join (`curated_jobs_loaded`), standalone
    `apply`/`resume` modes, and cross-container runs fresh. Write failure
    never fails the scrape itself (Sheets already persisted by curate()).
    """
    import json

    try:
        from datetime import datetime, timezone

        curated = [j for j in top_jobs if (j.get("match_score", 0) or 0) >= 70]
        if not curated:
            return
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_count": len(jobs),
            "jobs": curated,
        }
        with open(CURATED_JOBS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _worker(run_id: str) -> None:
    """Run the pipeline; pump live board stats into the record every 5s."""
    from tools.yield_tracker import YieldTracker

    tracker = YieldTracker()
    stop_pump = threading.Event()

    def progress(phase: str, scraped: int) -> None:
        with _lock:
            run = _runs.get(run_id)
            if run is not None:
                run["phase"] = phase
                run["scraped"] = scraped
                _add_event(
                    run,
                    "Starting board scan" if phase == "scraping" else f"{phase.title()} phase started",
                    event_type="phase",
                )

    def pump() -> None:
        while not stop_pump.wait(5.0):
            try:
                total = _board_total()
            except Exception:
                total = 0
            boards = tracker.snapshot()
            summary = _summarize_boards(boards, total)
            with _lock:
                run = _runs.get(run_id)
                if run is None or run["status"] not in ("queued", "running"):
                    return
                run.update(summary)
                run["boards"] = _board_snapshot(boards)
                previous = run.setdefault("_event_board_state", {})
                for board, details in run["boards"].items():
                    state = (details.get("status"), details.get("fetched", 0))
                    if previous.get(board) == state:
                        continue
                    previous[board] = state
                    status = details.get("status", "unknown")
                    _add_event(
                        run,
                        f"{board}: {status} ({details.get('fetched', 0) or 0} jobs)",
                        level="error" if status == "error" else "info",
                        event_type="board",
                        board=board,
                    )

    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return
        run["status"] = "running"
        run["phase"] = "starting"
        _add_event(run, "Scrape worker started", event_type="lifecycle")
    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()
    try:
        counts = _run_simple_pipeline(progress, tracker)
        with _lock:
            run = _runs.get(run_id)
            if run is not None:
                run["status"] = "done"
                run["phase"] = "done"
                for key in ("scraped", "curated", "boards_total", "boards_done",
                            "boards_ok", "boards_failed", "boards_empty", "fetched"):
                    if key in counts:
                        run[key] = counts[key]
                run["boards"] = _board_snapshot(tracker.snapshot())
                run.pop("_event_board_state", None)
                _add_event(
                    run,
                    f"Scrape complete: {run.get('scraped', 0)} scraped, {run.get('curated', 0)} curated",
                    event_type="complete",
                )
                run["finished_at"] = _now_iso()
        # Fresh reads after a run — never let cache refresh break the record.
        try:
            from api import cache

            cache.refresh()
        except Exception:
            pass
    except Exception as e:
        # Q6 (PM quick win, 2026-10-18): the raw exception text used to go
        # into the run record verbatim — a free description of internals
        # (paths, call graph) for any dashboard user, and no greppable
        # anchor for the operator. Same incident-id pattern as
        # api/errors.py: the full traceback goes to the server log, the
        # record carries the action + id.
        incident = uuid.uuid4().hex[:8]
        logging.getLogger("api.runs").error(
            "Scrape run %s failed (incident %s)", run_id, incident, exc_info=True)
        with _lock:
            run = _runs.get(run_id)
            if run is not None:
                run["status"] = "error"
                run["phase"] = "error"
                run["error"] = (
                    f"Scrape failed. The server logged the details under "
                    f"incident {incident} ({type(e).__name__})."
                )
                run.pop("_event_board_state", None)
                _add_event(run, run["error"], level="error", event_type="error")
                run["finished_at"] = _now_iso()
    finally:
        stop_pump.set()


def _board_total() -> int:
    """Planned tracker work items: board loop plus three optional passes.

    These synthetic rows are scraper stages, not additional independent job
    boards. A union also prevents double-counting if a configured name is ever
    reused. Import remains lazy and does not parse the CV.
    """
    from agents.scrapper import MASTER_BOARDS, SYNTHETIC_TRACKER_BOARDS

    return len(set(MASTER_BOARDS) | set(SYNTHETIC_TRACKER_BOARDS))


def start_scrape() -> Dict[str, Any]:
    """Start a background scrape run. Raises RuntimeError when one is active."""
    with _lock:
        for run in _runs.values():
            if run["status"] in ("queued", "running"):
                raise RuntimeError(f"Run {run['run_id']} already {run['status']}")
        run_id = uuid.uuid4().hex[:12]
        _runs[run_id] = {
            "run_id": run_id,
            "status": "queued",
            "phase": "queued",
            "scraped": 0,
            "curated": 0,
            "error": "",
            "boards_total": 0,
            "boards_done": 0,
            "boards_ok": 0,
            "boards_failed": 0,
            "boards_empty": 0,
            "fetched": 0,
            "boards": {},
            "events": [],
            "started_at": _now_iso(),
            "finished_at": "",
        }
        _add_event(_runs[run_id], "Scrape queued", event_type="lifecycle")
        # Keep memory bounded; drop oldest finished runs first.
        finished = sorted(
            (r for r in _runs.values() if r["status"] in ("done", "error")),
            key=lambda r: r["started_at"],
        )
        while len(_runs) > _MAX_KEPT and finished:
            _runs.pop(finished.pop(0)["run_id"], None)
        snapshot = _public(_runs[run_id])
    thread = threading.Thread(target=_worker, args=(run_id,), daemon=True)
    thread.start()
    return snapshot


def reset_registry() -> None:
    """Test helper: clear all runs."""
    with _lock:
        _runs.clear()
