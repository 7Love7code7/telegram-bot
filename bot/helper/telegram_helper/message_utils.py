import time

from telegram import InlineKeyboardMarkup
from telegram.message import Message
from telegram.update import Update
from telegram.error import RetryAfter
from pyrogram.errors import FloodWait

from bot import AUTO_DELETE_MESSAGE_DURATION, LOGGER, status_reply_dict, status_reply_dict_lock, \
                Interval, DOWNLOAD_STATUS_UPDATE_INTERVAL, RSS_CHAT_ID, rss_session, bot
from bot.helper.ext_utils.bot_utils import get_readable_message, setInterval


def sendMessage(text: str, bot, update: Update):
    try:
        return bot.send_message(update.message.chat_id,
                            reply_to_message_id=update.message.message_id,
                            text=text, allow_sending_without_reply=True, parse_mode='HTMl', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.error(str(r))
        time.sleep(r.retry_after * 1.5)
        return sendMessage(text, bot, update)
    except Exception as e:
        LOGGER.error(str(e))

def sendMarkup(text: str, bot, update: Update, reply_markup: InlineKeyboardMarkup):
    try:
        return bot.send_message(update.message.chat_id,
                            reply_to_message_id=update.message.message_id,
                            text=text, reply_markup=reply_markup, allow_sending_without_reply=True,
                            parse_mode='HTMl', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        time.sleep(r.retry_after * 1.5)
        return sendMarkup(text, bot, update, reply_markup)
    except Exception as e:
        LOGGER.error(str(e))

def editMessage(text: str, message: Message, reply_markup=None):
    try:
        bot.edit_message_text(text=text, message_id=message.message_id,
                              chat_id=message.chat.id,reply_markup=reply_markup,
                              parse_mode='HTMl', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        time.sleep(r.retry_after * 1.5)
        return editMessage(text, message, reply_markup)
    except Exception as e:
        LOGGER.error(str(e))

def sendRss(text: str, bot):
    if rss_session is None:
        try:
            return bot.send_message(RSS_CHAT_ID, text, parse_mode='HTMl', disable_web_page_preview=True)
        except RetryAfter as r:
            LOGGER.warning(str(r))
            time.sleep(r.retry_after * 1.5)
            return sendRss(text, bot)
        except Exception as e:
            LOGGER.error(str(e))
    else:
        try:
            return rss_session.send_message(RSS_CHAT_ID, text, parse_mode='HTMl', disable_web_page_preview=True)
        except FloodWait as e:
            LOGGER.warning(str(e))
            time.sleep(e.x * 1.5)
            return sendRss(text, bot)
        except Exception as e:
            LOGGER.error(str(e))

def deleteMessage(bot, message: Message):
    try:
        bot.delete_message(chat_id=message.chat.id,
                           message_id=message.message_id)
    except Exception as e:
        LOGGER.error(str(e))

def sendLogFile(bot, update: Update):
    with open('log.txt', 'rb') as f:
        bot.send_document(document=f, filename=f.name,
                          reply_to_message_id=update.message.message_id,
                          chat_id=update.message.chat_id)

def auto_delete_message(bot, cmd_message: Message, bot_message: Message):
    if AUTO_DELETE_MESSAGE_DURATION != -1:
        time.sleep(AUTO_DELETE_MESSAGE_DURATION)
        try:
            # Skip if None is passed meaning we don't want to delete bot xor cmd message
            deleteMessage(bot, cmd_message)
            deleteMessage(bot, bot_message)
        except AttributeError:
            pass

def delete_all_messages():
    with status_reply_dict_lock:
        for message in list(status_reply_dict.values()):
            try:
                deleteMessage(bot, message)
                del status_reply_dict[message.chat.id]
            except Exception as e:
                LOGGER.error(str(e))

def update_all_messages():
    msg, buttons = get_readable_message()
    with status_reply_dict_lock:
        for chat_id in list(status_reply_dict.keys()):
            if status_reply_dict[chat_id] and msg != status_reply_dict[chat_id].text:
                if buttons == "":
                    editMessage(msg, status_reply_dict[chat_id])
                else:
                    editMessage(msg, status_reply_dict[chat_id], buttons)
                status_reply_dict[chat_id].text = msg

def sendStatusMessage(msg, bot):
    if len(Interval) == 0:
        Interval.append(setInterval(DOWNLOAD_STATUS_UPDATE_INTERVAL, update_all_messages))
    progress, buttons = get_readable_message()
    with status_reply_dict_lock:
        if msg.message.chat.id in list(status_reply_dict.keys()):
            try:
                message = status_reply_dict[msg.message.chat.id]
                deleteMessage(bot, message)
                del status_reply_dict[msg.message.chat.id]
            except Exception as e:
                LOGGER.error(str(e))
                del status_reply_dict[msg.message.chat.id]
        if buttons == "":
            message = sendMessage(progress, bot, msg)
        else:
            message = sendMarkup(progress, bot, msg, buttons)
        status_reply_dict[msg.message.chat.id] = message
