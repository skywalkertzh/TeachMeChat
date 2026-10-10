import multiprocessing
import time
import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal


class ProcessActor(QObject):
    received = Signal(str, object)
    failed = Signal(str)

    def __init__(self, target, runtime, parent=None, deadline=180):
        super().__init__(parent)
        self.runtime = str(runtime)
        self.deadline = deadline
        self.started = 0.0
        self.stopping = False
        self.stop_started = 0.0
        self.busy = False
        self.disposed = False
        context = multiprocessing.get_context("spawn")
        self.cancelled = context.Event()
        self.pipe, remote = context.Pipe()
        self.process = context.Process(target=target, args=(remote, self.cancelled, self.runtime), daemon=False)
        self.process.start()
        remote.close()
        self.inbox = queue.Queue()
        self.receiver = threading.Thread(target=self._receive, daemon=True)
        self.receiver.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(80)

    def _receive(self):
        try:
            while not self.cancelled.is_set():
                self.inbox.put(self.pipe.recv())
        except (EOFError, OSError, BrokenPipeError):
            pass

    def _send(self, operation, payload):
        try:
            self.pipe.send((operation, payload))
        except (EOFError, OSError, BrokenPipeError):
            self.inbox.put(("_failed", "后台任务连接已断开。"))

    def submit(self, operation, payload):
        if self.stopping or self.busy or not self.process.is_alive():
            return False
        self.busy = True
        self.started = time.monotonic()
        threading.Thread(target=self._send, args=(operation, payload), daemon=True).start()
        return True

    def poll(self):
        if self.stopping:
            if not self.process.is_alive() or time.monotonic() - self.stop_started > .6:
                self.dispose()
            return
        try:
            while not self.inbox.empty():
                kind, result = self.inbox.get_nowait()
                if kind == "_failed":
                    self.failed.emit(result)
                    self.stop()
                    return
                if kind != "progress":
                    self.busy = False
                self.received.emit(kind, result)
            if not self.process.is_alive():
                self.failed.emit("后台任务已结束，请重新连接。")
                self.stop()
            elif self.busy and time.monotonic() - self.started > self.deadline:
                self.failed.emit("任务超过执行时限，已停止本程序任务；微信未被关闭。")
                self.stop()
        except (EOFError, BrokenPipeError, OSError):
            self.failed.emit("后台任务连接已结束。")
            self.stop()

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        self.cancelled.set()
        self.stop_started = time.monotonic()
        if not self.busy:
            try:
                self.pipe.send(("stop", {}))
            except (OSError, BrokenPipeError):
                pass

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        self.timer.stop()
        self.cancelled.set()
        if self.process.is_alive():
            # Only terminate descendants of this application's isolated worker.
            try:
                import psutil
                children = psutil.Process(self.process.pid).children(recursive=True)
            except Exception:
                children = []
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            self.process.terminate()
            self.process.join(.3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(.3)
        else:
            self.process.join(0)
        self.pipe.close()
        self.busy = False
        self.stopping = True
