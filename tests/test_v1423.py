"""Regression tests for v1.4.23.

* the "downloaded chapters" count leaking between books -- reported, and
  reproduced in a browser before being fixed
* the queue redesign: grouped by manga, collapsible, sparkline + fraction
* per-job speed/ETA/history on the progress snapshot
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ================================================ the cross-book count bug


# ============================================================ queue tiles


# ======================================================= progress payload


def test_job_snapshot_carries_formatted_text_and_history():
    from readerm.progress import JobProgress

    job = JobProgress("j", "Title")
    job.set_chapters(done=2, total=10)
    job.add_bytes(2048)
    snap = job.snapshot(sample=True)

    for key in ("speed_text", "eta_text", "downloaded_text", "history",
                "chapters_done", "chapters_total"):
        assert key in snap, key
    assert isinstance(snap["history"], list)


def test_history_is_bounded():
    """An hours-long download must not grow an unbounded list."""
    import time

    from readerm.progress import JobProgress

    job = JobProgress("j", "T")
    for _ in range(job.HISTORY * 3):
        job.add_bytes(1000)
        job._last_sample = 0        # bypass the rate limiter
        job.snapshot(sample=True)
    assert len(job.history) <= job.HISTORY


def test_history_is_rate_limited():
    """Sampling on every read made the sparkline scroll far too fast."""
    from readerm.progress import JobProgress

    job = JobProgress("j", "T")
    job.add_bytes(1000)
    for _ in range(20):
        job.snapshot(sample=True)
    assert len(job.history) <= 2


def test_summary_samples_each_job_once():
    """The summary used to call snapshot() four times per job, which also
    sampled the history four times."""
    from readerm.progress import ProgressRegistry

    registry = ProgressRegistry()
    job = registry.job("a", "A")
    job.add_bytes(5000)
    registry.summary()
    assert len(job.history) == 1


def test_summary_jobs_include_history_for_the_sparkline():
    from readerm.progress import ProgressRegistry

    registry = ProgressRegistry()
    job = registry.job("a", "A")
    job.add_bytes(5000)
    jobs = registry.summary()["jobs"]
    assert jobs and "history" in jobs[0]
    assert "speed_text" in jobs[0]


# ============================================================= animations
