"""Wakeable deadline scheduler with bounded dispatch and receiver serialization."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
import threading
import time


class Cancellation:
    def __init__(self):
        self.read_fd, self.write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.event = threading.Event()

    def cancel(self):
        if not self.event.is_set():
            self.event.set()
            try:
                os.write(self.write_fd, b'x')
            except BlockingIOError:
                pass

    def close(self):
        os.close(self.read_fd)
        os.close(self.write_fd)


@dataclass
class Job:
    key: str
    resource: str
    work: object
    done: object
    interval: float | None
    due: float
    cancellation: Cancellation
    running: bool = False
    pending: bool = False
    removed: bool = False
    exclusive: bool = False


class Scheduler:
    def __init__(self, workers=2, clock=time.monotonic):
        if type(workers) is not int or workers < 1:
            raise ValueError('workers must be positive')
        self.clock, self.workers = clock, workers
        self.condition = threading.Condition()
        self.jobs, self.running = {}, {}
        self.closing = False
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='battery-io')
        self.thread = threading.Thread(target=self._run, name='battery-scheduler', daemon=False)
        self.thread.start()

    def add(self, key, resource, work, done, interval=None, exclusive=False):
        if interval is not None and interval <= 0:
            raise ValueError('interval must be positive')
        with self.condition:
            if self.closing:
                raise RuntimeError('service is closing')
            if key in self.jobs:
                raise ValueError('duplicate job')
            self.jobs[key] = Job(key, resource, work, done, interval, self.clock(), Cancellation(), exclusive=exclusive)
            self.condition.notify_all()

    def refresh(self, key):
        with self.condition:
            job = self.jobs.get(key)
            if self.closing or job is None or job.removed:
                return False
            if job.running:
                job.pending = True
            else:
                job.due = self.clock()
            self.condition.notify_all()
            return True

    def set_interval(self, interval):
        if interval <= 0:
            raise ValueError('interval must be positive')
        with self.condition:
            for job in self.jobs.values():
                if job.interval is not None:
                    job.interval = interval
                    job.due = self.clock() + interval
            self.condition.notify_all()

    def remove(self, key):
        with self.condition:
            job = self.jobs.get(key)
            if job is None:
                return
            job.removed = True
            job.cancellation.cancel()
            if not job.running:
                self.jobs.pop(key)
                job.cancellation.close()
            self.condition.notify_all()

    def busy(self, key=None):
        with self.condition:
            return bool(self.running) if key is None else key in self.running

    def wake(self):
        with self.condition:
            self.condition.notify_all()

    def close(self, wait=True):
        with self.condition:
            self.closing = True
            for job in self.jobs.values():
                job.cancellation.cancel()
            self.condition.notify_all()
        if wait:
            self.thread.join()

    def _eligible(self, job, now):
        if job.running or job.removed or job.due > now:
            return False
        if job.exclusive:
            return not self.running
        return not any(j.exclusive or j.resource == job.resource for j in self.running.values())

    def _run(self):
        try:
            with self.condition:
                while not self.closing:
                    now = self.clock()
                    # Explicit debug operations form a conservative global barrier.
                    # Once queued they drain active reads before starting.
                    exclusive = [j for j in self.jobs.values() if j.exclusive and not j.running and not j.removed]
                    candidates = exclusive if exclusive else list(self.jobs.values())
                    available = sorted((j for j in candidates if self._eligible(j, now)), key=lambda j: j.due)
                    if available and len(self.running) < self.workers:
                        job = available[0]
                        job.running = True
                        self.running[job.key] = job
                        self.pool.submit(self._execute, job)
                        continue
                    # Block until a real deadline or command/completion; never spin
                    # on an already-due job that is blocked by another receiver.
                    deadlines = [j.due for j in candidates if not j.running and not j.removed and j.due > now]
                    timeout = max(0, min(deadlines) - now) if deadlines else None
                    self.condition.wait(timeout)
        finally:
            self.pool.shutdown(wait=True)
            with self.condition:
                for job in self.jobs.values():
                    job.cancellation.close()
                self.jobs.clear()

    def _execute(self, job):
        result, error = None, None
        try:
            try:
                result = job.work(job.cancellation)
            except Exception as caught:
                error = caught
            if not job.cancellation.event.is_set():
                job.done(result, error)
        finally:
            with self.condition:
                self.running.pop(job.key, None)
                job.running = False
                if job.removed or job.interval is None:
                    if self.jobs.get(job.key) is job:
                        self.jobs.pop(job.key)
                    job.cancellation.close()
                else:
                    job.due = self.clock() if job.pending else self.clock() + job.interval
                    job.pending = False
                self.condition.notify_all()
