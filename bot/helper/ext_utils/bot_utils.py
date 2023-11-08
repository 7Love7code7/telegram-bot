from asyncio import (
    create_subprocess_exec,
    create_subprocess_shell,
    run_coroutine_threadsafe,
    sleep,
    gather,
)
from asyncio.subprocess import PIPE
from functools import partial, wraps
from concurrent.futures import ThreadPoolExecutor
from aiohttp import ClientSession

from bot import user_data, config_dict, bot_loop
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.ext_utils.telegraph_helper import telegraph
from bot.helper.ext_utils.help_messages import (
    MIRROR_HELP_MESSAGE,
    YT_HELP_MESSAGE,
    CLONE_HELP_MESSAGE,
)

THREADPOOL = ThreadPoolExecutor(max_workers=1000)

COMMAND_USAGE = {}


class setInterval:
    def __init__(self, interval, action, *args, **kwargs):
        self.interval = interval
        self.action = action
        self.task = bot_loop.create_task(self._set_interval(*args, **kwargs))

    async def _set_interval(self, *args, **kwargs):
        while True:
            await sleep(self.interval)
            await self.action(*args, **kwargs)

    def cancel(self):
        self.task.cancel()


def bt_selection_buttons(id_):
    gid = id_[:12] if len(id_) > 20 else id_
    pincode = "".join([n for n in id_ if n.isdigit()][:4])
    buttons = ButtonMaker()
    BASE_URL = config_dict["BASE_URL"]
    if config_dict["WEB_PINCODE"]:
        buttons.ubutton("Select Files", f"{BASE_URL}/app/files/{id_}")
        buttons.ibutton("Pincode", f"btsel pin {gid} {pincode}")
    else:
        buttons.ubutton(
            "Select Files", f"{BASE_URL}/app/files/{id_}?pin_code={pincode}"
        )
    buttons.ibutton("Done Selecting", f"btsel done {gid} {id_}")
    buttons.ibutton("Cancel", f"btsel cancel {gid}")
    return buttons.build_menu(2)


async def initiate_help_messages():
    mirror, yt, clone = await gather(
        telegraph.create_page(
            title="Mirror-Leech Command Usage", content=MIRROR_HELP_MESSAGE
        ),
        telegraph.create_page(title="YTDLP Command Usage", content=YT_HELP_MESSAGE),
        telegraph.create_page(title="Clone Command Usage", content=CLONE_HELP_MESSAGE),
    )
    buttons = ButtonMaker()
    buttons.ubutton("Usage Guide", f"https://telegra.ph/{mirror['path']}")
    COMMAND_USAGE["main"] = buttons.build_menu(1)
    buttons.reset()
    buttons.ubutton("Usage Guide", f"https://telegra.ph/{yt['path']}")
    COMMAND_USAGE["yt"] = buttons.build_menu(1)
    buttons.reset()
    buttons.ubutton("Usage Guide", f"https://telegra.ph/{clone['path']}")
    COMMAND_USAGE["clone"] = buttons.build_menu(1)


async def get_telegraph_list(telegraph_content):
    path = [
        (
            await telegraph.create_page(
                title="Mirror-Leech-Bot Drive Search", content=content
            )
        )["path"]
        for content in telegraph_content
    ]
    if len(path) > 1:
        await telegraph.edit_telegraph(path, telegraph_content)
    buttons = ButtonMaker()
    buttons.ubutton("🔎 VIEW", f"https://telegra.ph/{path[0]}")
    return buttons.build_menu(1)


def arg_parser(items, arg_base):
    if not items:
        return arg_base
    bool_arg_set = {"-b", "-e", "-z", "-s", "-j", "-d", "-sv"}
    t = len(items)
    i = 0
    arg_start = -1

    while i + 1 <= t:
        part = items[i]
        if part in arg_base:
            if arg_start == -1:
                arg_start = i
            if i + 1 == t and part in bool_arg_set or part in ["-s", "-j"]:
                arg_base[part] = True
            else:
                sub_list = []
                for j in range(i + 1, t):
                    item = items[j]
                    if item in arg_base:
                        if part in bool_arg_set and not sub_list:
                            arg_base[part] = True
                        break
                    sub_list.append(item)
                    i += 1
                if sub_list:
                    arg_base[part] = " ".join(sub_list)
        i += 1
    link = []
    if items[0] not in arg_base:
        if arg_start == -1:
            link.extend(iter(items))
        else:
            link.extend(items[r] for r in range(arg_start))
        if link:
            arg_base["link"] = " ".join(link)
    return arg_base


async def get_content_type(url):
    try:
        async with ClientSession(trust_env=True) as session:
            async with session.get(url, verify_ssl=False) as response:
                return response.headers.get("Content-Type")
    except:
        return None


def update_user_ldata(id_, key, value):
    user_data.setdefault(id_, {})
    user_data[id_][key] = value


async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    stdout = stdout.decode().strip()
    stderr = stderr.decode().strip()
    return stdout, stderr, proc.returncode


def new_task(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return bot_loop.create_task(func(*args, **kwargs))

    return wrapper


async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(THREADPOOL, pfunc)
    return await future if wait else future


def async_to_sync(func, *args, wait=True, **kwargs):
    future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
    return future.result() if wait else future


def new_thread(func):
    @wraps(func)
    def wrapper(*args, wait=False, **kwargs):
        future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
        return future.result() if wait else future

    return wrapper
