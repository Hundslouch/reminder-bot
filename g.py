import logging
import os
import asyncio
from datetime import datetime
import pytz
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import select, update, ForeignKey
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column, relationship

# -----------------------------
# settings.py
# -----------------------------
load_dotenv()
TOKEN = os.getenv("TOKEN")
DATABASE_URL = "sqlite+aiosqlite:///reminders.db"
DEFAULT_TZ = os.getenv("TZ", "Europe/Moscow")

# -----------------------------
# db.py
# -----------------------------
engine = create_async_engine(DATABASE_URL, echo=True)
db = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# -----------------------------
# models.py
# -----------------------------
class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column()
    timezone: Mapped[str] = mapped_column()

    reminders = relationship("Reminder", back_populates="user")


class Reminder(Base):
    __tablename__ = "reminders"
    reminder_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    reminder_text: Mapped[str] = mapped_column()
    reminder_time: Mapped[datetime] = mapped_column()

    user = relationship("User", back_populates="reminders")


# -----------------------------
# dao.py
# -----------------------------
class UserDAO:
    @staticmethod
    async def get_user(session, user_id):
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(session, user_id, username, timezone):
        new_user = User(user_id=user_id, username=username, timezone=timezone)
        session.add(new_user)
        await session.commit()

    @staticmethod
    async def update_timezone(session, user_id, timezone):
        await session.execute(
            update(User).where(User.user_id == user_id).values(timezone=timezone)
        )
        await session.commit()


class ReminderDAO:
    @staticmethod
    async def add_reminder(session, user_id, text, time):
        reminder = Reminder(user_id=user_id, reminder_text=text, reminder_time=time)
        session.add(reminder)
        await session.commit()

    @staticmethod
    async def get_all_reminders(session):
        result = await session.execute(select(Reminder).join(User))
        return result.scalars().all()

    @staticmethod
    async def delete_reminder(session, reminder):
        await session.delete(reminder)
        await session.commit()

# -----------------------------
# utils.py
# -----------------------------
def validate_timezone(tz: str):
    if tz not in pytz.all_timezones:
        raise ValueError("Неверный часовой пояс.")

def parse_datetime(date_str, time_str):
    date = datetime.strptime(date_str, "%d.%m.%Y").date()
    time = datetime.strptime(time_str, "%H:%M").time()
    return datetime.combine(date, time)

# -----------------------------
# handlers.py
# -----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot=bot)

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.first_name

    async with db() as session:
        user = await UserDAO.get_user(session, user_id)
        if not user:
            await UserDAO.create_user(session, user_id, username, DEFAULT_TZ)

    await message.reply(
        f"Привет, {username}, я твой бот-напоминалка. \n"
        f"Используй /set_reminder, чтобы создать напоминание. \n"
        "Используй /set_timezone, чтобы установить свой часовой пояс."
    )


@dp.message_handler(commands=["set_timezone"])
async def set_timezone(message: types.Message):
    async with db() as session:
        try:
            args = message.text.split(" ", 1)
            if len(args) < 2:
                raise ValueError("Пример: /set_timezone Europe/Moscow")

            tz = args[1]
            validate_timezone(tz)

            user_id = message.from_user.id
            user = await UserDAO.get_user(session, user_id)
            if user:
                await UserDAO.update_timezone(session, user_id, tz)
            else:
                await UserDAO.create_user(session, user_id, message.from_user.username, tz)

            await message.reply(f"Часовой пояс установлен: {tz}")

        except ValueError as e:
            await message.reply(str(e))


@dp.message_handler(commands=["set_reminder"])
async def set_reminder(message: types.Message):
    async with db() as session:
        try:
            args = message.text.split(" ", 3)
            if len(args) < 4:
                raise ValueError("Пример: /set_reminder 15.10.2024 18:30 текст")

            reminder_datetime = parse_datetime(args[1], args[2])
            reminder_text = args[3]

            user_id = message.from_user.id
            user = await UserDAO.get_user(session, user_id)

            user_timezone = user.timezone if user else DEFAULT_TZ
            local_tz = pytz.timezone(user_timezone)
            local_dt = local_tz.localize(reminder_datetime)
            reminder_time_utc = local_dt.astimezone(pytz.utc)

            now_utc = datetime.now(pytz.utc).replace(second=0, microsecond=0)
            if reminder_time_utc < now_utc:
                raise ValueError("Дата и время не могут быть меньше текущих.")

            await ReminderDAO.add_reminder(session, user_id, reminder_text, reminder_time_utc)

            await message.reply(
                f"Напоминание установлено на {reminder_datetime} ({user_timezone}): {reminder_text}"
            )

        except ValueError as e:
            await message.reply(str(e))


async def check_reminders():
    while True:
        async with db() as session:
            now_utc = datetime.now(pytz.utc).replace(second=0, microsecond=0)
            reminders = await ReminderDAO.get_all_reminders(session)

            for reminder in reminders:
                user = await session.get(User, reminder.user_id)
                user_tz = pytz.timezone(user.timezone)
                local_time = reminder.reminder_time.astimezone(user_tz).replace(second=0, microsecond=0)

                if local_time <= now_utc.astimezone(user_tz):
                    await bot.send_message(
                        reminder.user_id,
                        f"{user.username}, не забудь: {reminder.reminder_text}"
                    )
                    await ReminderDAO.delete_reminder(session, reminder)

        await asyncio.sleep(60)

# -----------------------------
# main.py
# -----------------------------
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("База данных и таблицы инициализированы")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    loop.create_task(check_reminders())
    executor.start_polling(dp)
