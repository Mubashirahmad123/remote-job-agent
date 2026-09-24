"""Row -> schema converters shared by routers."""

from api.schemas import JobOut, TrackerEntry


def to_job_out(row: dict) -> JobOut:
    return JobOut(**{k: row.get(k) for k in JobOut.model_fields if k in row})


def to_tracker_entry(row: dict) -> TrackerEntry:
    return TrackerEntry(
        **{k: row.get(k) for k in TrackerEntry.model_fields if k in row}
    )
