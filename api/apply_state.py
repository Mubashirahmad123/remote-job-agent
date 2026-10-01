"""Persistent fill artifacts for apply intents and Greenhouse submission."""

import os
import sqlite3
from pathlib import Path
from typing import Any

from api.apply_claims import initialize_claim_store
from api.apply_intents import initialize_intent_store


DB_PATH = Path(os.getenv("APPLY_STATE_DB_PATH", "data/apply_submit.db"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    initialize_claim_store(connection)
    initialize_intent_store(connection)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS apply_review_artifacts (
            job_fingerprint TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            job_title TEXT NOT NULL,
            apply_url TEXT NOT NULL,
            package_path TEXT NOT NULL,
            screenshot_path TEXT,
            confirmation_path TEXT,
            confirmation_message TEXT,
            match_ratio REAL NOT NULL,
            fill_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resume_path TEXT,
            cover_letter_text TEXT
        )"""
    )
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(apply_review_artifacts)").fetchall()
    }
    if "fill_status" not in columns:
        connection.execute(
            "ALTER TABLE apply_review_artifacts "
            "ADD COLUMN fill_status TEXT NOT NULL DEFAULT 'filled_ready'"
        )
    if "resume_path" not in columns:
        connection.execute(
            "ALTER TABLE apply_review_artifacts ADD COLUMN resume_path TEXT"
        )
    if "cover_letter_text" not in columns:
        connection.execute(
            "ALTER TABLE apply_review_artifacts ADD COLUMN cover_letter_text TEXT"
        )
    connection.commit()
    return connection


def save_review_artifact(artifact: dict[str, Any]) -> None:
    connection = connect()
    try:
        connection.execute(
            """INSERT INTO apply_review_artifacts
            (job_fingerprint, platform, job_title, apply_url, package_path,
             screenshot_path, confirmation_path, confirmation_message,
             match_ratio, fill_status, created_at, resume_path, cover_letter_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_fingerprint) DO UPDATE SET
              platform=excluded.platform,
              job_title=excluded.job_title,
              apply_url=excluded.apply_url,
              package_path=excluded.package_path,
              screenshot_path=excluded.screenshot_path,
              confirmation_path=excluded.confirmation_path,
              confirmation_message=excluded.confirmation_message,
              match_ratio=excluded.match_ratio,
              fill_status=excluded.fill_status,
              created_at=excluded.created_at,
              resume_path=excluded.resume_path,
              cover_letter_text=excluded.cover_letter_text""",
            (
                artifact["job_fingerprint"],
                artifact["platform"],
                artifact["job_title"],
                artifact["apply_url"],
                artifact["package_path"],
                artifact.get("screenshot_path"),
                artifact.get("confirmation_path"),
                artifact.get("confirmation_message"),
                artifact["match_ratio"],
                artifact["fill_status"],
                artifact["created_at"],
                artifact.get("resume_path"),
                artifact.get("cover_letter_text"),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_review_artifact(job_fingerprint: str) -> dict[str, Any] | None:
    connection = connect()
    try:
        row = connection.execute(
            "SELECT * FROM apply_review_artifacts WHERE job_fingerprint = ?",
            (job_fingerprint,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def get_claim_status(job_fingerprint: str) -> str | None:
    connection = connect()
    try:
        row = connection.execute(
            "SELECT status FROM apply_claims WHERE job_fingerprint = ?",
            (job_fingerprint,),
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()