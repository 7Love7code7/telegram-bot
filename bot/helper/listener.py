#!/usr/bin/env python3
from requests import utils as rutils
from aiofiles.os import path as aiopath, remove as aioremove, listdir, rename, makedirs
from os import walk, path as ospath
from html import escape
from aioshutil import move
from asyncio import create_subprocess_exec, sleep, Event

from bot import Interval, aria2, DOWNLOAD_DIR, download_dict, download_dict_lock, LOGGER, DATABASE_URL, MAX_SPLIT_SIZE, config_dict, status_reply_dict_lock, user_data, non_queued_up, non_queued_dl, queued_up, queued_dl, queue_dict_lock
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.fs_utils import get_base_name, get_path_size, split_file, clean_download, clean_target, is_first_archive_split, is_archive, is_archive_split
from bot.helper.ext_utils.exceptions import NotSupportedExtractionArchive
from bot.helper.ext_utils.queued_starter import start_from_queued
from bot.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from bot.helper.mirror_utils.status_utils.zip_status import ZipStatus
from bot.helper.mirror_utils.status_utils.split_status import SplitStatus
from bot.helper.mirror_utils.status_utils.upload_status import UploadStatus
from bot.helper.mirror_utils.status_utils.tg_upload_status import TgUploadStatus
from bot.helper.mirror_utils.status_utils.queue_status import QueueStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.mirror_utils.upload_utils.pyrogramEngine import TgUploader
from bot.helper.telegram_helper.message_utils import sendMessage, delete_all_messages, update_all_messages
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.ext_utils.db_handler import DbManger


class MirrorLeechListener:
    def __init__(self, message, isZip=False, extract=False, isQbit=False, isLeech=False, pswd=None, tag=None, select=False, seed=False, sameDir={}):
        self.message = message
        self.uid = message.id
        self.extract = extract
        self.isZip = isZip
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.pswd = pswd
        self.tag = tag
        self.seed = seed
        self.newDir = ""
        self.dir = f"{DOWNLOAD_DIR}{self.uid}"
        self.select = select
        self.isSuperGroup = message.chat.type.name in ['SUPERGROUP', 'CHANNEL']
        self.suproc = None
        self.queuedUp = None
        self.sameDir = sameDir

    async def clean(self):
        try:
            async with status_reply_dict_lock:
                if Interval:
                    Interval[0].cancel()
                    Interval.clear()
            await sync_to_async(aria2.purge)
            await delete_all_messages()
        except:
            pass

    async def onDownloadStart(self):
        if self.isSuperGroup and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            await DbManger().add_incomplete_task(self.message.chat.id, self.message.link, self.tag)

    async def onDownloadComplete(self):
        if len(self.sameDir) == 1:
            await sleep(3)
        multi_links = False
        async with download_dict_lock:
            if len(self.sameDir) > 1:
                self.sameDir.remove(self.uid)
                folder_name = (await listdir(self.dir))[-1]
                path = f"{self.dir}/{folder_name}"
                des_path = f"{DOWNLOAD_DIR}{list(self.sameDir)[0]}/{folder_name}"
                await makedirs(des_path, exist_ok=True)
                for subdir in await listdir(path):
                    sub_path = f"{self.dir}/{folder_name}/{subdir}"
                    if subdir in await listdir(des_path):
                        sub_path = await rename(sub_path, f"{self.dir}/{folder_name}/1-{subdir}")
                    await move(sub_path, des_path)
                multi_links = True
            download = download_dict[self.uid]
            name = str(download.name()).replace('/', '')
            gid = download.gid()
        LOGGER.info(f"Download completed: {name}")
        if multi_links:
            await self.onUploadError('Downloaded! Waiting for other tasks...')
            return
        if name == "None" or self.isQbit or not await aiopath.exists(f"{self.dir}/{name}"):
            name = (await listdir(self.dir))[-1]
        m_path = f"{self.dir}/{name}"
        size = await get_path_size(m_path)
        async with queue_dict_lock:
            if self.uid in non_queued_dl:
                non_queued_dl.remove(self.uid)
        await start_from_queued()
        user_dict = user_data.get(self.message.from_user.id, {})
        if self.isZip:
            if self.seed and self.isLeech:
                self.newDir = f"{self.dir}10000"
                path = f"{self.newDir}/{name}.zip"
            else:
                path = f"{m_path}.zip"
            async with download_dict_lock:
                download_dict[self.uid] = ZipStatus(name, size, gid, self)
            LEECH_SPLIT_SIZE = user_dict.get('split_size', False) or config_dict['LEECH_SPLIT_SIZE']
            cmd = ["7z", f"-v{LEECH_SPLIT_SIZE}b", "a", "-mx=0", f"-p{self.pswd}", path, m_path]
            if self.isLeech and int(size) > LEECH_SPLIT_SIZE:
                if self.pswd is None:
                    del cmd[4]
                LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}.0*')
            else:
                del cmd[1]
                if self.pswd is None:
                    del cmd[3]
                LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}')
            self.suproc = await create_subprocess_exec(*cmd)
            await self.suproc.wait()
            if self.suproc.returncode == -9:
                return
            elif not self.seed:
                await clean_target(m_path)
        elif self.extract:
            try:
                if await aiopath.isfile(m_path):
                    path = get_base_name(m_path)
                LOGGER.info(f"Extracting: {name}")
                async with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, size, gid, self)
                if await aiopath.isdir(m_path):
                    if self.seed:
                        self.newDir = f"{self.dir}10000"
                        path = f"{self.newDir}/{name}"
                    else:
                        path = m_path
                    for dirpath, subdir, files in await sync_to_async(walk, m_path, topdown=False):
                        for file_ in files:
                            if is_first_archive_split(file_) or is_archive(file_) and not file_.endswith('.rar'):
                                f_path = ospath.join(dirpath, file_)
                                t_path = dirpath.replace(self.dir, self.newDir) if self.seed else dirpath
                                cmd = ["7z", "x", f"-p{self.pswd}", f_path, f"-o{t_path}", "-aot", "-xr!@PaxHeader"]
                                if self.pswd is None:
                                    del cmd[2]
                                self.suproc = await create_subprocess_exec(*cmd)
                                await self.suproc.wait()
                                if self.suproc.returncode == -9:
                                    return
                                elif self.suproc.returncode != 0:
                                    LOGGER.error('Unable to extract archive splits!')
                        if not self.seed and self.suproc is not None and self.suproc.returncode == 0:
                            for file_ in files:
                                if is_archive_split(file_) or is_archive(file_):
                                    del_path = ospath.join(dirpath, file_)
                                    try:
                                        await aioremove(del_path)
                                    except:
                                        return
                else:
                    if self.seed and self.isLeech:
                        self.newDir = f"{self.dir}10000"
                        path = path.replace(self.dir, self.newDir)
                    cmd = ["7z", "x", f"-p{self.pswd}", m_path, f"-o{path}", "-aot", "-xr!@PaxHeader"]
                    if self.pswd is None:
                        del cmd[2]
                    self.suproc = await create_subprocess_exec(*cmd)
                    await self.suproc.wait()
                    if self.suproc.returncode == -9:
                        return
                    elif self.suproc.returncode == 0:
                        LOGGER.info(f"Extracted Path: {path}")
                        if not self.seed:
                            try:
                                await aioremove(m_path)
                            except:
                                return
                    else:
                        LOGGER.error('Unable to extract archive! Uploading anyway')
                        self.newDir = ""
                        path = m_path
            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                self.newDir = ""
                path = m_path
        else:
            path = m_path
        up_dir, up_name = path.rsplit('/', 1)
        size = await get_path_size(up_dir)
        if self.isLeech:
            m_size = []
            o_files = []
            if not self.isZip:
                checked = False
                LEECH_SPLIT_SIZE = user_dict.get('split_size', False) or config_dict['LEECH_SPLIT_SIZE']
                for dirpath, subdir, files in await sync_to_async(walk, up_dir, topdown=False):
                    for file_ in files:
                        f_path = ospath.join(dirpath, file_)
                        f_size = await aiopath.getsize(f_path)
                        if f_size > LEECH_SPLIT_SIZE:
                            if not checked:
                                checked = True
                                async with download_dict_lock:
                                    download_dict[self.uid] = SplitStatus(up_name, size, gid, self)
                                LOGGER.info(f"Splitting: {up_name}")
                            res = await split_file(f_path, f_size, file_, dirpath, LEECH_SPLIT_SIZE, self)
                            if not res:
                                return
                            if res == "errored":
                                if f_size <= MAX_SPLIT_SIZE:
                                    continue
                                try:
                                    await aioremove(f_path)
                                except:
                                    return
                            elif not self.seed or self.newDir:
                                try:
                                    await aioremove(f_path)
                                except:
                                    return
                            else:
                                m_size.append(f_size)
                                o_files.append(file_)

        up_limit = config_dict['QUEUE_UPLOAD']
        all_limit = config_dict['QUEUE_ALL']
        added_to_queue = False
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            up = len(non_queued_up)
            if (all_limit and dl + up >= all_limit and (not up_limit or up >= up_limit)) or (up_limit and up >= up_limit):
                added_to_queue = True
                LOGGER.info(f"Added to Queue/Upload: {name}")
                queued_up[self.uid] = self
        if added_to_queue:
            async with download_dict_lock:
                download_dict[self.uid] = QueueStatus(name, size, gid, self, 'Up')
            self.queuedUp = Event()
            await self.queuedUp.wait()
            async with download_dict_lock:
                if self.uid not in download_dict.keys():
                    return
            LOGGER.info(f'Start from Queued/Upload: {name}')
        async with queue_dict_lock:
            non_queued_up.add(self.uid)

        if self.isLeech:
            size = await get_path_size(up_dir)
            for s in m_size:
                size = size - s
            LOGGER.info(f"Leech Name: {up_name}")
            tg = TgUploader(up_name, up_dir, size, self)
            tg_upload_status = TgUploadStatus(tg, size, gid, self)
            async with download_dict_lock:
                download_dict[self.uid] = tg_upload_status
            await update_all_messages()
            await tg.upload(o_files, m_size)
        else:
            up_path = f'{up_dir}/{up_name}'
            size = await get_path_size(up_path)
            LOGGER.info(f"Upload Name: {up_name}")
            drive = GoogleDriveHelper(up_name, up_dir, size, self)
            upload_status = UploadStatus(drive, size, gid, self)
            async with download_dict_lock:
                download_dict[self.uid] = upload_status
            await update_all_messages()
            await sync_to_async(drive.upload, up_name)

    async def onUploadComplete(self, link: str, size, files, folders, typ, name):
        if self.isSuperGroup and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            await DbManger().rm_complete_task(self.message.link)
        msg = f"<b>Name: </b><code>{escape(name)}</code>\n\n<b>Size: </b>{size}"
        if self.isLeech:
            msg += f'\n<b>Total Files: </b>{folders}'
            if typ != 0:
                msg += f'\n<b>Corrupted Files: </b>{typ}'
            msg += f'\n<b>cc: </b>{self.tag}\n\n'
            if not files:
                await sendMessage(self.message, msg)
            else:
                fmsg = ''
                for index, (link, name) in enumerate(files.items(), start=1):
                    fmsg += f"{index}. <a href='{link}'>{name}</a>\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        await sendMessage(self.message, msg + fmsg)
                        await sleep(1)
                        fmsg = ''
                if fmsg != '':
                    await sendMessage(self.message, msg + fmsg)
            if self.seed:
                if self.newDir:
                    await clean_target(self.newDir)
                async with queue_dict_lock:
                    if self.uid in non_queued_up:
                        non_queued_up.remove(self.uid)
                return
        else:
            msg += f'\n\n<b>Type: </b>{typ}'
            if typ == "Folder":
                msg += f'\n<b>SubFolders: </b>{folders}'
                msg += f'\n<b>Files: </b>{files}'
            msg += f'\n\n<b>cc: </b>{self.tag}'
            buttons = ButtonMaker()
            buttons.ubutton("☁️ Drive Link", link)
            LOGGER.info(f'Done Uploading {name}')
            if INDEX_URL:= config_dict['INDEX_URL']:
                url_path = rutils.quote(f'{name}')
                share_url = f'{INDEX_URL}/{url_path}'
                if typ == "Folder":
                    share_url += '/'
                    buttons.ubutton("⚡ Index Link", share_url)
                else:
                    buttons.ubutton("⚡ Index Link", share_url)
                    if config_dict['VIEW_LINK']:
                        share_urls = f'{INDEX_URL}/{url_path}?a=view'
                        buttons.ubutton("🌐 View Link", share_urls)
            await sendMessage(self.message, msg, buttons.build_menu(2))
            if self.seed:
                if self.isZip:
                    await clean_target(f"{self.dir}/{name}")
                elif self.newDir:
                    await clean_target(self.newDir)
                async with queue_dict_lock:
                    if self.uid in non_queued_up:
                        non_queued_up.remove(self.uid)
                return
        await clean_download(self.dir)
        async with download_dict_lock:
            if self.uid in download_dict.keys():
                del download_dict[self.uid]
            count = len(download_dict)
        if count == 0:
            await self.clean()
        else:
            await update_all_messages()

        async with queue_dict_lock:
            if self.uid in non_queued_up:
                non_queued_up.remove(self.uid)

        await start_from_queued()

    async def onDownloadError(self, error, button=None):
        await clean_download(self.dir)
        if self.newDir:
            await clean_download(self.newDir)
        async with download_dict_lock:
            if self.uid in download_dict.keys():
                del download_dict[self.uid]
            count = len(download_dict)
            if self.uid in self.sameDir:
                self.sameDir.remove(self.uid)
        msg = f"{self.tag} your download has been stopped due to: {escape(error)}"
        await sendMessage(self.message, msg, button)
        if count == 0:
            await self.clean()
        else:
            await update_all_messages()

        if self.isSuperGroup and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            await DbManger().rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.uid in queued_dl:
                del queued_dl[self.uid]
            if self.uid in non_queued_dl:
                non_queued_dl.remove(self.uid)
            if self.uid in queued_up:
                del queued_up[self.uid]
            if self.uid in non_queued_up:
                non_queued_up.remove(self.uid)
        if self.queuedUp is not None:
            self.queuedUp.set()
        await start_from_queued()

    async def onUploadError(self, error):
        await clean_download(self.dir)
        if self.newDir:
            await clean_download(self.newDir)
        async with download_dict_lock:
            if self.uid in download_dict.keys():
                del download_dict[self.uid]
            count = len(download_dict)
            if self.uid in self.sameDir:
                self.sameDir.remove(self.uid)
        await sendMessage(self.message, f"{self.tag} {escape(error)}")
        if count == 0:
            await self.clean()
        else:
            await update_all_messages()

        if self.isSuperGroup and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            await DbManger().rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.uid in queued_dl:
                del queued_dl[self.uid]
            if self.uid in non_queued_dl:
                non_queued_dl.remove(self.uid)
            if self.uid in queued_up:
                del queued_up[self.uid]
            if self.uid in non_queued_up:
                non_queued_up.remove(self.uid)

        if self.queuedUp is not None:
            self.queuedUp.set()
        await start_from_queued()
