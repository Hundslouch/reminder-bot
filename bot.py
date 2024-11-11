import time
import logging
import os
import asyncio
import sqlite3
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("TOKEN")
MSG = "{}, не забудь: {}"


bot = Bot(token=TOKEN)
dp = Dispatcher(bot=bot)


conn = sqlite3.connect("reminders.db")
cursor = conn.cursor()


cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        reminder_text TEXT NOT NULL,
        reminder_time INTEGER NOT NULL
    )
"""
)
conn.commit()


@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    user_full_name = message.from_user.full_name
    logging.info(f"{user_id=} {user_full_name=} {time.asctime()}")
    await message.reply(
        f"Привет, {user_full_name}, я твой бот-напоминалка. Используй /set_reminder, чтобы создать напоминание."
    )


@dp.message_handler(commands=["set_reminder"])
async def set_reminder(message: types.Message):
    try:

        command_parts = message.text.split(" ", 2)
        if len(command_parts) < 3:
            await message.reply(
                "Пожалуйста, используй формат: /set_reminder <время в секундах> <сообщение>"
            )
            return

        delay = int(command_parts[1])
        reminder_text = command_parts[2]
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        reminder_time = int(time.time()) + delay

        cursor.execute(
            """
            INSERT INTO reminders (user_id, user_name, reminder_text, reminder_time)
            VALUES (?, ?, ?, ?)
        """,
            (user_id, user_name, reminder_text, reminder_time),
        )
        conn.commit()

        await message.reply(
            f"Напоминание установлено через {delay} секунд: {reminder_text}"
        )

        asyncio.create_task(reminder_task(user_id, user_name, reminder_text, delay))

    except ValueError:
        await message.reply("Неверный формат времени. Укажи время в секундах.")


async def reminder_task(user_id, user_name, reminder_text, delay):
    await asyncio.sleep(delay)
    await bot.send_message(user_id, MSG.format(user_name, reminder_text))


async def check_reminders():
    while True:
        current_time = int(time.time())
        cursor.execute(
            "SELECT id, user_id, user_name, reminder_text FROM reminders WHERE reminder_time <= ?",
            (current_time,),
        )
        reminders_to_send = cursor.fetchall()

        for reminder in reminders_to_send:
            reminder_id, user_id, user_name, reminder_text = reminder
            await bot.send_message(user_id, MSG.format(user_name, reminder_text))

            cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()

        await asyncio.sleep(60)


async def main():

    asyncio.create_task(check_reminders())

    await dp.start_polling()


if __name__ == "__main__":
    asyncio.run(main())
