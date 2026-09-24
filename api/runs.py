"""Background scrape-run registry (Phase 2 actions).

A full scrape (scrape_all -> curate) takes minutes, so POST /api/scrape only
*starts* a daemon-thread run and returns a run_id immediately; clients poll
GET /api/scrape/{run_id}. Lazy-import rule applies: pipeline modules are
imported inside the worker, never at module import (agents/curator.py:57-79
parses the CV on import). Only one active run at a time (409 on overlap).

Run dict: {run_id, status, phase, scraped, curated, error,
            started_at, finished_at}. status: queued|running|done|error.
"""

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


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _public(run: Dict[str, Any]) -> Dict[str, Any]:
    return dict(run)


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
    from agents.scrapper import MASTER_BOARDS, scrape_all
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
    summary = _summarize_boards(tracker.boards, len(MASTER_BOARDS))
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

    def pump() -> None:
        while not stop_pump.wait(5.0):
            try:
                total = _board_total()
            except Exception:
                total = 0
            summary = _summarize_boards(tracker.boards, total)
            with _lock:
                run = _runs.get(run_id)
                if run is None or run["status"] not in ("queued", "running"):
                    return
                run.update(summary)

    with _lock:
        run = _runs.get(run_id)
        if run is None:
            return
        run["status"] = "running"
        run["phase"] = "starting"
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
                run["finished_at"] = _now_iso()
        # Fresh reads after a run — never let cache refresh break the record.
        try:
            from api import cache

            cache.refresh()
        except Exception:
            pass
    except Exception as e:
        with _lock:
            run = _runs.get(run_id)
            if run is not None:
                run["status"] = "error"
                run["phase"] = "error"
                run["error"] = f"{type(e).__name__}: {e}"[:500]
                run["finished_at"] = _now_iso()
    finally:
        stop_pump.set()


def _board_total() -> int:
    """Number of boards scrape_all iterates (import-time cheap, no CV parse)."""
    from agents.scrapper import MASTER_BOARDS

    return len(MASTER_BOARDS)


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
            "started_at": _now_iso(),
            "finished_at": "",
        }
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
