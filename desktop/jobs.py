import asyncio
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from vpn.errors import VPNError


class Signals(QObject):
    success = Signal(object)
    failure = Signal(str)


class Job(QRunnable):
    def __init__(self, work):
        super().__init__()
        self.work, self.signals = work, Signals()

    def run(self):
        try:
            result = self.work()
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            self.signals.success.emit(result)
        except VPNError as error:
            self.signals.failure.emit(str(error))
        except Exception:
            self.signals.failure.emit("Operation failed. Open safe diagnostics or run Setup Repair.")


def submit(work, success, failure):
    job = Job(work)
    job.signals.success.connect(success)
    job.signals.failure.connect(failure)
    QThreadPool.globalInstance().start(job)
