import logging
import os
import asyncio
from datetime import datetime
import pytz
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("TOKEN")
DEFAULT_TZ = os.getenv("TZ", "Europe/Moscow")
MSG = "{}, не забудь: {}"


bot = Bot(token=TOKEN)
dp = Dispatcher(bot=bot)


DATABASE_URL = "sqlite+aiosqlite:///reminders.db"
engine = create_async_engine(DATABASE_URL, echo=True)
db = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Таблица 'reminders' создана")


@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.first_name

    async with db() as session:

        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not user:

            new_user = User(
                user_id=user_id,
                username=username,
                timezone="Europe/Moscow",
            )
            session.add(new_user)
            await session.commit()

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
                raise ValueError(
                    "Неверный формат команды. Пример: /set_timezone America/New_York"
                )

            user_timezone = args[1]

            if user_timezone not in pytz.all_timezones:
                raise ValueError(
                    "Неверный часовой пояс. Используйте команду /set_timezone <Часовой пояс>"
                )

            user_id = message.from_user.id
            username = message.from_user.username

            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()

            if user:

                await session.execute(
                    update(User)
                    .where(User.user_id == user_id)
                    .values(timezone=user_timezone)
                )
            else:

                new_user = User(
                    user_id=user_id, username=username, timezone=user_timezone
                )
                session.add(new_user)

            await session.commit()

            await message.reply(f"Часовой пояс установлен: {user_timezone}")

        except ValueError as error:
            await message.reply(str(error))


@dp.message_handler(commands=["set_reminder"])
async def set_reminder(message: types.Message):
    async with db() as session:
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

            if reminder_text == "":
                raise ValueError("Текст напоминания не может быть пустым.")

            user_id = message.from_user.id
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalars().first()
            if user:
                user_timezone = user.timezone if user.timezone else DEFAULT_TZ
            else:
                user_timezone = DEFAULT_TZ

            local_tz = pytz.timezone(user_timezone)
            local_dt = local_tz.localize(reminder_datetime)
            reminder_time_utc = local_dt.astimezone(pytz.utc)

            now_utc = datetime.now(pytz.utc).replace(second=0, microsecond=0)
            if reminder_time_utc < now_utc:
                raise ValueError(
                    "Указанная дата и время не могут быть меньше текущей даты и времени."
                )

            reminder = Reminder(
                user_id=user_id,
                reminder_text=reminder_text,
                reminder_time=reminder_time_utc,
            )
            session.add(reminder)
            await session.commit()

            await message.reply(
                f"Напоминание установлено на {reminder_datetime} ({user_timezone}): {reminder_text}"
            )

        except ValueError as error:
            await message.reply(str(error))


async def check_reminders():
    while True:
        async with db() as session:
            now_utc = datetime.now(pytz.utc).replace(second=0, microsecond=0)

            result = await session.execute(
                select(Reminder).join(User, Reminder.user_id == User.user_id)
            )
            reminders = result.scalars().all()

            for reminder in reminders:
                user = await session.get(User, reminder.user_id)
                user_tz = pytz.timezone(user.timezone)
                reminder_time_local = reminder.reminder_time.astimezone(
                    user_tz
                ).replace(second=0, microsecond=0)

                if reminder_time_local <= now_utc.astimezone(user_tz):
                    await bot.send_message(
                        reminder.user_id,
                        MSG.format(user.username, reminder.reminder_text),
                    )

                    await session.delete(reminder)
                    await session.commit()

        await asyncio.sleep(60)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    loop.create_task(check_reminders())
    executor.start_polling(dp)
