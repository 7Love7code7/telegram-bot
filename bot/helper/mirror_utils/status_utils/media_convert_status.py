from bot import LOGGER, subprocess_lock
from bot.helper.ext_utils.status_utils import get_readable_file_size, MirrorStatus


class MediaConvertStatus:
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
        return MirrorStatus.STATUS_CONVERTING

    def processed_bytes(self):
        return 0

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling Converting: {self.listener.name}")
        self.listener.cancelled = True
        async with subprocess_lock:
            if (
                self.listener.suproc is not None
                and self.listener.suproc.returncode is None
            ):
                self.listener.suproc.kill()
        await self.listener.onUploadError("Converting stopped by user!")
