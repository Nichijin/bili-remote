"""Short timestamp interpolation; no prediction, unbounded queue, or GUI timers."""
import ctypes
import math
import os
import threading
import time
from collections import deque
from ctypes import wintypes


class MotionTimeline:
    BUFFER = .016
    MAX_AGE = .120

    def __init__(self):
        self.points = deque(maxlen=32)
        self.offset = None
        self.seq = 0
        self.source_time = 0
        self.x = self.y = 0.0
        self.applied_x = self.applied_y = 0

    def submit(self, message, now):
        stamp = message["t"] / 1000
        if message["seq"] <= self.seq or stamp < self.source_time:
            return False
        x, y = message["x"], message["y"]
        if max(abs(x-self.x), abs(y-self.y)) > 8192:
            raise ValueError("鼠标累计位移变化过大，请重新进入鼠标模式")
        gap = stamp-self.source_time
        self.seq, self.source_time, self.x, self.y = message["seq"], stamp, x, y
        self.offset = now-stamp if self.offset is None else min(self.offset, now-stamp)
        if now-(stamp+self.offset) > self.MAX_AGE:
            # Skip stale travel instead of playing it after a network stall.
            self.applied_x, self.applied_y = math.trunc(x), math.trunc(y)
            self.points.clear()
            self.points.append((now, x, y))
            return True
        due = stamp+self.offset+self.BUFFER
        if not self.points or gap > .040:
            self.points.clear()
            self.points.append((now, self.applied_x, self.applied_y))
        if self.points and due <= self.points[-1][0]:
            self.points[-1] = (due, x, y)
        else:
            self.points.append((due, x, y))
        return True

    def tick(self, now):
        while len(self.points) > 1 and self.points[1][0] <= now:
            self.points.popleft()
        if not self.points:
            return 0, 0
        when, x, y = self.points[0]
        if len(self.points) > 1:
            end, tx, ty = self.points[1]
            ratio = max(0, min(1, (now-when)/max(.000001, end-when)))
            x, y = x+(tx-x)*ratio, y+(ty-y)*ratio
        return self.apply(x, y)

    def apply(self, x, y):
        ix, iy = math.trunc(x), math.trunc(y)
        delta = ix-self.applied_x, iy-self.applied_y
        self.applied_x, self.applied_y = ix, iy
        return delta

    def pending(self, now):
        return bool(self.points and self.points[-1][0] > now)

    def flush(self, now):
        self.points.clear()
        self.points.append((now, self.x, self.y))
        return self.apply(self.x, self.y)


class PreciseWait:
    """Per-worker high resolution timer; never change global timer resolution."""
    def __init__(self):
        self.handle = None
        if os.name == "nt":
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self.api.CreateWaitableTimerExW.restype = wintypes.HANDLE
            self.api.SetWaitableTimer.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
            self.api.SetWaitableTimer.restype = wintypes.BOOL
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.WaitForSingleObject.restype = wintypes.DWORD
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.api.CreateWaitableTimerExW(None, None, 2, 0x1F0003)

    def wait(self, delay):
        if delay <= 0:
            return
        if self.handle:
            due = ctypes.c_longlong(-max(1, round(delay*10_000_000)))
            if self.api.SetWaitableTimer(self.handle, ctypes.byref(due), 0, None, None, False):
                self.api.WaitForSingleObject(self.handle, 100)
                return
        # Python 3.11+ also uses a waitable timer on Windows for time.sleep.
        time.sleep(delay)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class MotionWorker:
    INTERVAL = .008

    def __init__(self, backend, clock=time.perf_counter):
        self.backend, self.clock = backend, clock
        self.timeline = MotionTimeline()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, name="mouse-output", daemon=True)
        self.thread.start()

    def check(self):
        if self.error:
            raise RuntimeError(str(self.error))
        if self.stopped.is_set():
            raise RuntimeError("鼠标输出已结束，请重新进入")

    def submit(self, message):
        with self.lock:
            self.check()
            self.timeline.submit(message, self.clock())
        self.wake.set()

    def click(self, button):
        with self.lock:
            self.check()
            self.move(self.timeline.flush(self.clock()))
            self.backend.click(button)

    def move(self, delta):
        if delta != (0, 0):
            self.backend.move(*delta)

    def run(self):
        timer = PreciseWait()
        try:
            deadline = self.clock()
            while not self.stopped.is_set():
                self.wake.wait()
                self.wake.clear()
                if deadline < self.clock()-self.INTERVAL:
                    deadline = self.clock()
                while not self.stopped.is_set():
                    timer.wait(max(0, deadline-self.clock()))
                    if self.stopped.is_set():
                        break
                    with self.lock:
                        now = self.clock()
                        self.move(self.timeline.tick(now))
                        pending = self.timeline.pending(now)
                    deadline += self.INTERVAL
                    if deadline <= now:
                        deadline = now+self.INTERVAL
                    if not pending:
                        break
        except Exception as exc:
            self.error = exc
            self.stopped.set()
        finally:
            timer.close()

    def close(self):
        self.stopped.set()
        self.wake.set()
        self.thread.join(timeout=.5)
        if self.thread.is_alive():
            raise RuntimeError("鼠标输出线程尚未停止")
