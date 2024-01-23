from bot import LOGGER
from bot.helper.ext_utils.status_utils import get_readable_file_size, MirrorStatus


class SampleVideoStatus:
    def __init__(self, listener, gid):
        self.listener = listener
        self._gid = gid
        self._size = self.listener.size

    def gid(self):
        return self._gid

    def progress(self):
        return "0"

    def speed(self):
        return "0"

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self._size)

    def eta(self):
        return "0s"

    def status(self):
        return MirrorStatus.STATUS_SAMVID

    def processed_bytes(self):
        return 0

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling Sample Video: {self.listener.name}")
        self.listener.cancelled = True
        if self.listener.suproc is not None and self.listener.suproc.returncode is None:
            self.listener.suproc.kill()
        await self.listener.onUploadError("Creating sample video stopped by user!")
