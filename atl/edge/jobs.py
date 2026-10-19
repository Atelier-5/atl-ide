# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
jobs.py — long work in the background, one at a time, with progress and
Cancel. Owned by the edge layer.

A job kind is registered once with a function

    def run(spec: dict, progress: (phase, fraction) -> None, cancelled: () -> bool) -> result

that checks cancelled() between steps and raises Stopped when it is. The
page polls /api/jobs; an agent calls jobs() over MCP. The same job (kind and
spec) is never queued twice.
"""

from __future__ import annotations

import itertools
import threading
import time
import traceback
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

Runner = Callable[[Dict[str, Any], Callable[[str, float], None], Callable[[], bool]], Any]


class Stopped(Exception):
    """Raised by a runner when cancelled() said so."""


class Busy(Exception):
    """The same job is already queued or running."""


class Jobs:
    """Queued and running work. One worker."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.queue: Deque[str] = deque()
        self.all: Dict[str, Dict[str, Any]] = {}
        self.kinds: Dict[str, Runner] = {}
        self.ids = itertools.count(1)
        self.worker: Optional[threading.Thread] = None

    def register(self, kind: str, run: Runner) -> None:
        self.kinds[kind] = run

    def submit(self, kind: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        if kind not in self.kinds:
            raise KeyError(f"no job kind {kind}")
        with self.lock:
            busy = next((j for j in self.all.values()
                         if j["kind"] == kind and j["spec"] == spec and j["state"] in ("queued", "running")), None)
            if busy:
                raise Busy(f"the same {kind} is already {busy['state']} (job {busy['id']})")
            job = {"id": str(next(self.ids)), "kind": kind, "spec": spec, "state": "queued",
                   "phase": "waiting", "progress": 0.0, "result": None, "error": None,
                   "cancel": False, "created": time.time()}
            self.all[job["id"]] = job
            self.queue.append(job["id"])
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, name="job-worker", daemon=True)
                self.worker.start()
            self.wake.notify()
            return self.public(job)

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self.lock:
            job = self.all.get(job_id)
            if job is None:
                raise KeyError(f"no job {job_id}")
            if job["state"] == "queued":
                self.queue.remove(job_id)
                job["state"] = "cancelled"
            elif job["state"] == "running":
                job["cancel"] = True
            return self.public(job)

    def get(self, job_id: str) -> Dict[str, Any]:
        with self.lock:
            if job_id not in self.all:
                raise KeyError(f"no job {job_id}")
            return self.public(self.all[job_id])

    def list(self) -> list:
        with self.lock:
            return [self.public(j) for j in reversed(list(self.all.values()))]

    @staticmethod
    def public(job: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in job.items() if k != "cancel"}

    def _update(self, job: Dict[str, Any], **fields: Any) -> None:
        with self.lock:
            job.update(fields)

    def _run(self) -> None:
        while True:
            with self.lock:
                while not self.queue:
                    self.wake.wait()
                job = self.all[self.queue.popleft()]
                job["state"] = "running"
            self._work(job)

    def _work(self, job: Dict[str, Any]) -> None:
        def progress(phase: str, done: float) -> None:
            self._update(job, phase=phase, progress=round(max(0.0, min(1.0, done)), 3))

        try:
            result = self.kinds[job["kind"]](job["spec"], progress, lambda: job["cancel"])
            self._update(job, state="done", phase="done", progress=1.0, result=result)
        except Stopped:
            self._update(job, state="cancelled", phase="cancelled")
        except Exception as exc:                  # a job's failure is the job's, never the worker's
            traceback.print_exc()
            self._update(job, state="failed", phase="failed", error=str(exc)[:500])


JOBS = Jobs()
