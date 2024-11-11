import logging
import os
import asyncio
from datetime import datetime
import pytz
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("TOKEN")
TZ = os.getenv("TZ", "Europe/Moscow")
MSG = "{}, не забудь: {}"


bot = Bot(token=TOKEN)
dp = Dispatcher(bot=bot)


DATABASE_URL = "sqlite:///reminders.db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()


class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    username = Column(String)
    reminder_text = Column(String)
    reminder_time = Column(DateTime)
    timezone = Column(String)


Base.metadata.create_all(engine)
logger.info("Таблица 'reminders' создана")


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

        reminder = Reminder(
            user_id=message.from_user.id,
            username=message.from_user.username,
            reminder_text=reminder_text,
            reminder_time=reminder_time_utc,
            timezone=user_timezone,
        )
        session.add(reminder)
        session.commit()

        await message.reply(
            f"Напоминание установлено на {reminder_datetime} ({user_timezone}): {reminder_text}"
        )

    except ValueError as error:
        await message.reply(str(error))


async def check_reminders():
    while True:
        now = datetime.now(pytz.utc)

        reminders = session.query(Reminder).filter(Reminder.reminder_time <= now).all()

        for reminder in reminders:

            await bot.send_message(
                reminder.user_id, MSG.format(reminder.username, reminder.reminder_text)
            )

            session.delete(reminder)
            session.commit()

        await asyncio.sleep(60)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(check_reminders())
    executor.start_polling(dp)
