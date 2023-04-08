from asyncio import create_subprocess_exec, gather
from asyncio.subprocess import PIPE
from re import findall as re_findall, I
from json import loads
from aiofiles.os import path as aiopath, mkdir, listdir
from aiofiles import open as aiopen
from configparser import ConfigParser
from random import randrange
from logging import getLogger

from bot import config_dict, GLOBAL_EXTENSION_FILTER
from bot.helper.ext_utils.bot_utils import cmd_exec, sync_to_async
from bot.helper.ext_utils.fs_utils import get_mime_type, count_files_and_folders


LOGGER = getLogger(__name__)


class RcloneTransferHelper:
    def __init__(self, listener, name=''):
        self.__listener = listener
        self.__proc = None
        self.__transferred_size = '0 B'
        self.__eta = '-'
        self.__percentage = '0%'
        self.__speed = '0 B/s'
        self.__is_cancelled = False
        self.__is_download = False
        self.__sa_count = 1
        self.__sa_index = 0
        self.__sa_number = 100
        self.name = name

    @property
    def transferred_size(self):
        return self.__transferred_size

    @property
    def percentage(self):
        return self.__percentage

    @property
    def speed(self):
        return self.__speed

    @property
    def eta(self):
        return self.__eta

    async def __progress(self):
        while not (self.__proc is None or self.__is_cancelled):
            data = (await self.__proc.stdout.readline()).decode()
            if not data:
                break
            if data := re_findall(r'Transferred:\s+([\d.]+\s*\w+)\s+/\s+([\d.]+\s*\w+),\s+([\d.]+%)\s*,\s+([\d.]+\s*\w+/s),\s+ETA\s+([\dwdhms]+)', data):
                self.__transferred_size, _, self.__percentage, self.__speed, self.__eta = data[
                    0]

    def __switchServiceAccount(self):
        if self.__sa_index == self.__sa_number - 1:
            self.__sa_index = 0
        else:
            self.__sa_index += 1
        self.__sa_count += 1
        remote = f'sa{self.__sa_index:03}'
        LOGGER.info(f"Switching to {remote} remote")
        return remote

    async def __create_rc_sa(self, remote, remote_opts):
        sa_conf_dir = 'rclone_sa'
        sa_conf_file = f'{sa_conf_dir}/{remote}.conf'
        if not await aiopath.isdir(sa_conf_dir):
            await mkdir(sa_conf_dir)
        elif await aiopath.isfile(sa_conf_file):
            return sa_conf_file

        if gd_id := remote_opts.get('team_drive'):
            option = 'team_drive'
        elif gd_id := remote_opts.get('root_folder_id'):
            option = 'root_folder_id'
        else:
            return 'rclone.conf'

        files = await listdir('accounts')
        text = ''.join(f"[sa{i:03}]\ntype = drive\nscope = drive\nservice_account_file = accounts/{sa}\n{option} = {gd_id}\n\n"
                       for i, sa in enumerate(files))

        async with aiopen(sa_conf_file, 'w') as f:
            await f.write(text)
        return sa_conf_file

    async def __start_download(self, cmd):
        self.__proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        _, return_code = await gather(self.__progress(), self.__proc.wait())

        if self.__is_cancelled:
            return

        if return_code == 0:
            await self.__listener.onDownloadComplete()
        elif return_code != -9:
            error = (await self.__proc.stderr.read()).decode().strip()
            LOGGER.error(error)

            if re_findall(".*User.*Rate.*(Limit|Quota).*Exceeded.*", error, flags=I):
                if self.__sa_count < self.__sa_number:
                    remote = self.__switchServiceAccount()
                    cmd[6] = f"{remote}:{cmd[6].split(':', 1)[1]}"
                    if self.__is_cancelled:
                        return
                    return self.__start_download(cmd)
                else:
                    LOGGER.info(
                        f"Reached maximum number of service accounts switching, which is {self.__sa_count}")

            await self.__listener.onDownloadError(error[:4000])

    async def download(self, remote, rc_path, config_path, path):
        self.__is_download = True
        remote_opts = await self.__get_remote_options(config_path, remote)
        remote_type = remote_opts['type']

        if remote_type == 'drive' and config_dict['USE_SERVICE_ACCOUNTS'] and config_path == 'rclone.conf' \
                and await aiopath.isdir('accounts'):
            config_path = await self.__create_rc_sa(remote, remote_opts)
            if config_path != 'rclone.conf':
                sa_files = await listdir('accounts')
                self.__sa_number = len(sa_files)
                self.__sa_index = randrange(self.__sa_number)
                remote = f'sa{self.__sa_index:03}'
                LOGGER.info(f'Upload with service account {remote}')

        cmd = await self.__getUpdatedCommand(config_path, f'{remote}:{rc_path}', path)

        if remote_type == 'drive' and not config_dict['RCLONE_FLAGS'] and not self.__listener.rcFlags:
            cmd.append('--drive-acknowledge-abuse')

        await self.__start_download(cmd)

    async def __start_upload(self, cmd):
        self.__proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        _, return_code = await gather(self.__progress(), self.__proc.wait())

        if self.__is_cancelled:
            return False

        if return_code == -9:
            return False
        elif return_code != 0:
            error = (await self.__proc.stderr.read()).decode().strip()
            LOGGER.error(error)
            if re_findall(".*User.*Rate.*(Limit|Quota).*Exceeded.*", error, flags=I):
                if self.__sa_count < self.__sa_number:
                    remote = self.__switchServiceAccount()
                    cmd[7] = f"{remote}:{cmd[7].split(':', 1)[1]}"
                    return False if self.__is_cancelled else self.__start_upload(cmd)
                else:
                    LOGGER.info(
                        f"Reached maximum number of service accounts switching, which is {self.__sa_count}")
            await self.__listener.onUploadError(error[:4000])
            return False
        else:
            return True

    async def upload(self, path, size):
        rc_path = self.__listener.upPath.strip('/')
        if rc_path == 'rc':
            rc_path = config_dict['RCLONE_PATH']
        if rc_path.startswith('mrcc:'):
            rc_path = rc_path.split('mrcc:', 1)[1]
            oconfig_path = f'rclone/{self.__listener.message.from_user.id}.conf'
        else:
            oconfig_path = 'rclone.conf'

        oremote, rc_path = rc_path.split(':', 1)

        if await aiopath.isdir(path):
            mime_type = 'Folder'
            rc_path += f"/{self.name}" if rc_path else self.name
        else:
            mime_type = 'File'

        remote_opts = await self.__get_remote_options(oconfig_path, oremote)
        remote_type = remote_opts['type']

        fremote = oremote
        fconfig_path = oconfig_path
        if remote_type == 'drive' and config_dict['USE_SERVICE_ACCOUNTS'] and fconfig_path == 'rclone.conf' \
                and await aiopath.isdir('accounts'):
            fconfig_path = await self.__create_rc_sa(oremote, remote_opts)
            if fconfig_path != 'rclone.conf':
                sa_files = await listdir('accounts')
                self.__sa_number = len(sa_files)
                self.__sa_index = randrange(self.__sa_number)
                fremote = f'sa{self.__sa_index:03}'
                LOGGER.info(f'Upload with service account {fremote}')

        cmd = await self.__getUpdatedCommand(fconfig_path, path, f'{fremote}:{rc_path}')
        if remote_type == 'drive' and not config_dict['RCLONE_FLAGS'] and not self.__listener.rcFlags:
            cmd.extend(('--drive-chunk-size', '64M',
                       '--drive-upload-cutoff', '32M'))

        result = await self.__start_upload(cmd)
        if not result:
            return

        if mime_type == 'Folder':
            folders, files = await count_files_and_folders(path)
        else:
            mime_type = await sync_to_async(get_mime_type, path)
            folders = 0
            files = 1

        if remote_type == 'drive':
            if mime_type == 'Folder':
                epath = rc_path.strip('/').rsplit('/', 1)
                epath = f'{oremote}:{epath[0]}' if len(
                    epath) > 1 else f'{oremote}:'
                destination = f'{oremote}:{rc_path}'
            elif rc_path:
                epath = f"{oremote}:{rc_path}/{self.name}"
                destination = epath
            else:
                epath = f"{oremote}:{rc_path}{self.name}"
                destination = epath

            cmd = ['rclone', 'lsjson', '--fast-list', '--no-mimetype',
                   '--no-modtime', '--config', oconfig_path, epath]
            res, err, code = await cmd_exec(cmd)

            if self.__is_cancelled:
                return

            if code == 0:
                result = loads(res)
                fid = 'err'
                for r in result:
                    if r['Path'] == self.name:
                        fid = r['ID']
                link = f'https://drive.google.com/drive/folders/{fid}' if mime_type == 'Folder' else f'https://drive.google.com/uc?id={fid}&export=download'
            elif code != -9:
                LOGGER.error(
                    f'while getting drive link. Path: {destination}. Stderr: {err}')
                link = ''
        else:
            if mime_type == 'Folder':
                destination = f"{oremote}:{rc_path}"
            elif rc_path:
                destination = f"{oremote}:{rc_path}/{self.name}"
            else:
                destination = f"{oremote}:{self.name}"

            cmd = ['rclone', 'link', '--config', oconfig_path, destination]
            res, err, code = await cmd_exec(cmd)

            if self.__is_cancelled:
                return

            if code == 0:
                link = res
            elif code != -9:
                LOGGER.error(
                    f'while getting link. Path: {destination} | Stderr: {err}')
                link = ''
        LOGGER.info(f'Upload Done. Path: {destination}')
        await self.__listener.onUploadComplete(link, size, files, folders, mime_type, self.name, destination)

    async def __getUpdatedCommand(self, config_path, source, destination):
        ext = '*.{' + ','.join(GLOBAL_EXTENSION_FILTER) + '}'
        cmd = ['rclone', 'copy', '--fast-list', '--config', config_path, '-P', source, destination,
               '--exclude', ext, '--ignore-case']
        if rcf := self.__listener.rcFlags or config_dict['RCLONE_FLAGS']:
            rcflags = rcf.split('|')
            for flag in rcflags:
                if ":" in flag:
                    key, value = flag.split(":")
                    cmd.extend((key, value))
                elif len(flag) > 0:
                    cmd.append(flag)
        return cmd

    @staticmethod
    async def __get_remote_options(config_path, remote):
        config = ConfigParser()
        async with aiopen(config_path, 'r') as f:
            contents = await f.read()
            config.read_string(contents)
        options = config.options(remote)
        return {opt: config.get(remote, opt) for opt in options}

    async def cancel_download(self):
        self.__is_cancelled = True
        if self.__proc is not None:
            try:
                self.__proc.kill()
            except:
                pass
        if self.__is_download:
            LOGGER.info(f"Cancelling Download: {self.name}")
            await self.__listener.onDownloadError('Download stopped by user!')
        else:
            LOGGER.info(f"Cancelling Upload: {self.name}")
            await self.__listener.onUploadError('your upload has been stopped!')
