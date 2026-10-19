# SPDX-License-Identifier: GPL-3.0-or-later
"""Background jobs: run, report, refuse a duplicate, cancel, survive a failure."""

from __future__ import annotations

import threading
import time

import pytest

from atl.edge.jobs import Busy, Jobs, Stopped


def wait(jobs, jid, states=("done", "failed", "cancelled")):
    for _ in range(200):
        j = jobs.get(jid)
        if j["state"] in states:
            return j
        time.sleep(0.02)
    raise AssertionError(jobs.get(jid))


def test_a_job_runs_and_reports():
    jobs = Jobs()
    jobs.register("add", lambda spec, progress, cancelled: (progress("adding", 0.5), spec["a"] + spec["b"])[1])
    j = wait(jobs, jobs.submit("add", {"a": 1, "b": 2})["id"])
    assert j["state"] == "done" and j["result"] == 3 and "cancel" not in j


def test_the_same_job_is_not_queued_twice_and_cancel_stops_it():
    jobs = Jobs()
    go = threading.Event()

    def slow(spec, progress, cancelled):
        go.set()
        while not cancelled():
            time.sleep(0.01)
        raise Stopped()
    jobs.register("slow", slow)
    jid = jobs.submit("slow", {})["id"]
    go.wait(2)
    with pytest.raises(Busy):
        jobs.submit("slow", {})
    jobs.cancel(jid)
    assert wait(jobs, jid)["state"] == "cancelled"


def test_a_failing_job_fails_alone():
    jobs = Jobs()
    jobs.register("boom", lambda *a: 1 / 0)
    jobs.register("ok", lambda *a: "fine")
    assert wait(jobs, jobs.submit("boom", {})["id"])["state"] == "failed"
    assert wait(jobs, jobs.submit("ok", {})["id"])["result"] == "fine"
