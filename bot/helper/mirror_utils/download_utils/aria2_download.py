import threading

from time import sleep

from bot import aria2, download_dict_lock, download_dict, STOP_DUPLICATE, TORRENT_DIRECT_LIMIT, ZIP_UNZIP_LIMIT, LOGGER
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.ext_utils.bot_utils import is_magnet, getDownloadByGid, new_thread, get_readable_file_size
from bot.helper.mirror_utils.status_utils.aria_download_status import AriaDownloadStatus
from bot.helper.telegram_helper.message_utils import sendMarkup, sendStatusMessage, sendMessage


@new_thread
def __onDownloadStarted(api, gid):
    if STOP_DUPLICATE or TORRENT_DIRECT_LIMIT is not None or ZIP_UNZIP_LIMIT is not None:
        sleep(1.5)
        dl = getDownloadByGid(gid)
        download = api.get_download(gid)
        try:
            if STOP_DUPLICATE and dl is not None and not dl.getListener().isLeech:
                LOGGER.info('Checking File/Folder if already in Drive...')
                sname = download.name
                if dl.getListener().isZip:
                    sname = sname + ".zip"
                if not dl.getListener().extract:
                    gdrive = GoogleDriveHelper()
                    smsg, button = gdrive.drive_list(sname, True)
                    if smsg:
                        dl.getListener().onDownloadError('File/Folder already available in Drive.\n\n')
                        api.remove([download], force=True, files=True)
                        sendMarkup("Here are the search results:", dl.getListener().bot, dl.getListener().update, button)
                        return
            if dl is not None and (ZIP_UNZIP_LIMIT is not None or TORRENT_DIRECT_LIMIT is not None):
                sleep(1)
                limit = None
                if ZIP_UNZIP_LIMIT is not None and (dl.getListener().isZip or dl.getListener().extract):
                    mssg = f'Zip/Unzip limit is {ZIP_UNZIP_LIMIT}GB'
                    limit = ZIP_UNZIP_LIMIT
                elif TORRENT_DIRECT_LIMIT is not None:
                    mssg = f'Torrent/Direct limit is {TORRENT_DIRECT_LIMIT}GB'
                    limit = TORRENT_DIRECT_LIMIT
                if limit is not None:
                    LOGGER.info('Checking File/Folder Size...')
                    size = api.get_download(gid).total_length
                    if size > limit * 1024**3:
                        dl.getListener().onDownloadError(f'{mssg}.\nYour File/Folder size is {get_readable_file_size(size)}')
                        api.remove([download], force=True, files=True)
                        return
        except:
            LOGGER.error(f"onDownloadStart: {gid} stop duplicate and size check didn't pass")

@new_thread
def __onDownloadComplete(api, gid):
    LOGGER.info(f"onDownloadComplete: {gid}")
    dl = getDownloadByGid(gid)
    download = api.get_download(gid)
    if download.followed_by_ids:
        new_gid = download.followed_by_ids[0]
        new_download = api.get_download(new_gid)
        if dl is None:
            dl = getDownloadByGid(new_gid)
        with download_dict_lock:
            download_dict[dl.uid()] = AriaDownloadStatus(new_gid, dl.getListener())
        LOGGER.info(f'Changed gid from {gid} to {new_gid}')
    elif dl:
        threading.Thread(target=dl.getListener().onDownloadComplete).start()

@new_thread
def __onDownloadStopped(api, gid):
    sleep(4)
    dl = getDownloadByGid(gid)
    if dl:
        dl.getListener().onDownloadError('Dead torrent!')

@new_thread
def __onDownloadError(api, gid):
    LOGGER.info(f"onDownloadError: {gid}")
    sleep(0.5)
    dl = getDownloadByGid(gid)
    try:
        download = api.get_download(gid)
        error = download.error_message
        LOGGER.info(f"Download Error: {error}")
    except:
        pass
    if dl:
        dl.getListener().onDownloadError(error)

def start_listener():
    aria2.listen_to_notifications(threaded=True, on_download_start=__onDownloadStarted,
                                  on_download_error=__onDownloadError,
                                  on_download_stop=__onDownloadStopped,
                                  on_download_complete=__onDownloadComplete)

def add_aria2c_download(link: str, path, listener, filename):
    if is_magnet(link):
        download = aria2.add_magnet(link, {'dir': path, 'out': filename})
    else:
        download = aria2.add_uris([link], {'dir': path, 'out': filename})
    if download.error_message:
        error = str(download.error_message).replace('<', ' ').replace('>', ' ')
        LOGGER.info(f"Download Error: {error}")
        return sendMessage(error, listener.bot, listener.update)
    with download_dict_lock:
        download_dict[listener.uid] = AriaDownloadStatus(download.gid, listener)
        LOGGER.info(f"Started: {download.gid} DIR: {download.dir} ")
    sendStatusMessage(listener.update, listener.bot)

start_listener()
