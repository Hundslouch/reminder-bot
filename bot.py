import logging
import os
import sqlite3
import asyncio
from datetime import datetime
import pytz
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("TOKEN")
TZ = os.getenv("TZ", "Europe/Moscow")
MSG = "{}, не забудь: {}"


bot = Bot(token=TOKEN)
dp = Dispatcher(bot=bot)


conn = sqlite3.connect("reminders.db")
cursor = conn.cursor()


cursor.execute(
    """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    reminder_text TEXT,
    reminder_time TEXT,
    timezone TEXT
)
"""
)
conn.commit()


@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    user_full_name = message.from_user.full_name
    await message.reply(
        f"Привет, {user_full_name}, я твой бот-напоминалка. "
        "Используй /set_reminder, чтобы создать напоминание."
    )


@dp.message_handler(commands=["set_reminder"])
async def set_reminder(message: types.Message):
    try:

        args = message.text.split(" ", 3)

        if len(args) < 3:
            raise ValueError(
                "Неверный формат команды. Пример: /set_reminder 15.10.2024 18:30 текст_напоминания"
            )

        date = datetime.strptime(args[1], "%d.%m.%Y").date()
        time = datetime.strptime(args[2], "%H:%M").time()
        reminder_datetime = datetime.combine(date, time)
        reminder_text = args[3]

        user_timezone = TZ

        local_tz = pytz.timezone(user_timezone)
        local_dt = local_tz.localize(reminder_datetime)
        reminder_time_utc = local_dt.astimezone(pytz.utc)

        now_utc = datetime.now(pytz.utc).replace(second=0, microsecond=0)
        if reminder_time_utc < now_utc:
            raise ValueError(
                "Указанная дата и время не могут быть меньше текущей даты и времени."
            )

        cursor.execute(
            "INSERT INTO reminders (user_id, reminder_text, reminder_time, timezone) "
            "VALUES (?, ?, ?, ?)",
            (
                message.from_user.id,
                reminder_text,
                reminder_time_utc.isoformat(),
                user_timezone,
            ),
        )
        conn.commit()

        await message.reply(
            f"Напоминание установлено на {reminder_datetime} ({user_timezone}): {reminder_text}"
        )

    except ValueError as error:
        await message.reply(str(error))


async def check_reminders():
    while True:
        now = datetime.now(pytz.utc)

        cursor.execute(
            "SELECT id, user_id, reminder_text FROM reminders WHERE reminder_time <= ?",
            (now.isoformat(),),
        )
        reminders = cursor.fetchall()

        for reminder in reminders:
            reminder_id, user_id, reminder_text = reminder

            await bot.send_message(user_id, MSG.format(user_id, reminder_text))

            cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()

        await asyncio.sleep(60)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(check_reminders())
    executor.start_polling(dp)
