from bot import LOGGER, jd_lock, jd_downloads
from bot.helper.ext_utils.jdownloader_booter import jdownloader
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.status_utils import (
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
)


def get_download(gid, old_info={}):
    try:
        return jdownloader.device.downloads.query_packages(
            [
                {
                    "bytesLoaded": True,
                    "bytesTotal": True,
                    "enabled": True,
                    "packageUUIDs": [gid],
                    "speed": True,
                    "eta": True,
                    "status": True,
                    "hosts": True,
                }
            ]
        )[0]
    except:
        return old_info


class JDownloaderStatus:
    def __init__(self, listener, gid):
        self.listener = listener
        self._gid = gid
        self._info = {}

    def _update(self):
        self._info = get_download(int(self._gid), self._info)

    def progress(self):
        try:
            return f"{round((self._info.get('bytesLoaded', 0) / self._info.get('bytesTotal', 0)) * 100, 2)}%"
        except:
            return "0%"

    def processed_bytes(self):
        return get_readable_file_size(self._info.get("bytesLoaded", 0))

    def speed(self):
        return f"{get_readable_file_size(self._info.get('speed', 0))}/s"

    def name(self):
        return self._info.get("name", self.listener.name)

    def size(self):
        return get_readable_file_size(self._info.get("bytesTotal", 0))

    def eta(self):
        eta = self._info.get("eta", False)
        if eta:
            return get_readable_time(eta)
        else:
            return "-"

    def status(self):
        self._update()
        state = self._info.get("status", "paused")
        if state == "paused":
            return MirrorStatus.STATUS_PAUSED
        else:
            return state

    def task(self):
        return self

    def gid(self):
        return self._gid

    async def cancel_task(self):
        LOGGER.info(f"Cancelling Download: {self.name()}")
        await sync_to_async(
            jdownloader.device.downloads.cleanup,
            "DELETE_ALL",
            "REMOVE_LINKS_AND_DELETE_FILES",
            "ALL",
            package_ids=[int(self._gid)],
        )
        async with jd_lock:
            del jd_downloads[int(self._gid)]
        await self.listener.onDownloadError("Download cancelled by user!")
