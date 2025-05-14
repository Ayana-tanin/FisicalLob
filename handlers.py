import re
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db_connection import insert_user, can_post_more, mark_user_allowed, update_invite_count, save_job, get_user_jobs, delete_job_by_id
from config import ADMINS, ADMIN_USERNAME, CHANNEL_ID

router = Router()
logger = logging.getLogger(__name__)

class Form(StatesGroup):
    job = State()

TEMPLATE = {
    "address": r"^📍\s*Адрес:\s*(.+)$",
    "title":   r"^📝\s*Задача:\s*(.+)$",
    "payment": r"^💵\s*Оплата:\s*(.+)$",
    "contact": r"^☎️\s*Контакт:\s*(.+)$",
    "extra":   r"^📌\s*Примечание:\s*(.*)$",
}

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start(msg: Message):
    insert_user(msg.from_user.id, msg.from_user.username or "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Выложить вакансию", callback_data="create")],
        [InlineKeyboardButton(text="📋 Мои вакансии", callback_data="myjobs")],
    ])
    await msg.answer("Привет! Что хотите сделать?", reply_markup=kb)

@router.callback_query(F.data == "create")
async def prompt_job(call: CallbackQuery, state: FSMContext):
    await call.message.answer(
        "📄 Введите вакансию по шаблону:\n\n"
        "📍 Адрес: Бишкек\n"
        "📝 Задача: Курьер\n"
        "💵 Оплата: 1000 сом\n"
        "☎️ Контакт: +996501234567\n"
        "📌 Примечание: ..."
    )
    await state.set_state(Form.job)

@router.message(Form.job)
async def handle_job(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    if not text:
        return await message.reply("❌ Вакансия не может быть пустой. Пожалуйста, введите текст вакансии:")

    user_id = message.from_user.id
    if not can_post_more(user_id):
        await message.answer(
            "🔒 Вы уже опубликовали вакансию. Чтобы опубликовать ещё, оплатите 100 сом админам или пригласите 5 друзей."
            f"\nСвяжитесь с админом: https://t.me/{ADMIN_USERNAME}"
        )
        await state.clear()
        return

    # Публикация вакансии
    await bot.send_message(CHANNEL_ID, text)
    # Сохранение вакансии в базе/памяти
    save_job(user_id, text)
    # Обновление счётчика приглашений
    update_invite_count(user_id)
    await message.answer(
        "✅ Вакансия опубликована!\nДля удаления вызовите 'Мои вакансии'.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Выложить вакансию", callback_data="create")],
            [InlineKeyboardButton(text="📋 Мои вакансии", callback_data="myjobs")],
        ])
    )
    await state.clear()

@router.callback_query(F.data == "myjobs")
async def list_jobs(call: CallbackQuery):
    user_id = call.from_user.id
    jobs = await asyncio.get_running_loop().run_in_executor(None, get_user_jobs, user_id)
    if not jobs:
        return await call.message.answer("Нет активных вакансий.")
    for job in jobs:
        info = job.all_info
        text = (
            f"<b>Вакансия #{job.id}</b>\n"
            f"📍 Адрес: {info.get('address', '—')}\n"
            f"📝 Задача: {info.get('title', '—')}\n"
            f"💵 Оплата: {info.get('payment', '—')}\n"
            f"☎️ Контакт: {info.get('contact', '—')}"
        )
        if info.get("extra"):
            text += f"\n📌 {info['extra']}"
        await call.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Удалить", callback_data=f"del:{job.id}")]
            ]),
            parse_mode="HTML"
        )

@router.callback_query(lambda c: c.data.startswith("del:"))
async def delete_job(call: CallbackQuery, bot: Bot):
    job_id = int(call.data.split(":")[1])
    job = await asyncio.get_running_loop().run_in_executor(None, delete_job_by_id, job_id)
    if job:
        try:
            await bot.delete_message(CHANNEL_ID, job.message_id)
        except Exception as e:
            logging.warning(f"Ошибка при удалении сообщения из канала: {e}")
        await call.message.answer(f"✅ Вакансия #{job_id} удалена.")
    else:
        await call.message.answer("❌ Вакансия не найдена или уже удалена.")

# Блокировка сообщений в группах
@router.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def block_non_admins(message: Message):
    try:
        user_id = message.from_user.id if message.from_user else None
        if user_id not in ADMINS:
            logger.info(f"Удаляем сообщение от {user_id} в чате {message.chat.id}")
            await message.delete()
            bot_user = await message.bot.get_me()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📝 Опубликовать вакансию",
                    url=f"https://t.me/{bot_user.username}"                )]
            ])
            warn = await message.answer(
                "<b>Сообщения в группе не от бота запрещены!</b>\n\n"
                "Чтобы опубликовать вакансию, перейдите в личку бота.",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(120)
            try:
                await warn.delete()
            except Exception as e:
                logger.error(f"Не удалось удалить предупреждение: {e}")
    except Exception as e:
        logger.error(f"Ошибка в block_non_admins: {e}")

import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db_connection import (
    insert_user,
    can_post_more,
    mark_user_allowed,
    get_user_jobs,
    delete_job_by_id,
    update_invite_count,
)
from config import ADMINS, ADMIN_USERNAME, CHANNEL_ID

router = Router()
logger = logging.getLogger(__name__)

class Form(StatesGroup):
    job = State()

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start_handler(message: Message):
    insert_user(message.from_user.id, message.from_user.username or "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Выложить вакансию", callback_data="create")],
        [InlineKeyboardButton(text="📋 Мои вакансии", callback_data="myjobs")],
    ])
    await message.answer("Привет! Выберите действие:", reply_markup=kb)

@router.callback_query(F.data == "create")
async def create_job_prompt(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📄 Введите текст вакансии (непустая строка):")
    await state.set_state(Form.job)

@router.message(Form.job)
async def handle_job(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    if not text:
        return await message.reply("❌ Вакансия не может быть пустой. Пожалуйста, введите текст вакансии:")

    user_id = message.from_user.id
    if not can_post_more(user_id):
        await message.answer(
            "🔒 Вы уже опубликовали вакансию. Чтобы опубликовать ещё, оплатите 100 сом админам или пригласите 5 друзей.\n"
            f"Свяжитесь с админом: https://t.me/{ADMIN_USERNAME}"
        )
        await state.clear()
        return

    # Публикация вакансии
    await bot.send_message(CHANNEL_ID, text)
    update_invite_count(user_id)
    await message.answer("✅ Вакансия опубликована!")
    await state.clear()

@router.callback_query(F.data == "myjobs")
async def list_jobs(call: CallbackQuery):
    jobs = get_user_jobs(call.from_user.id)
    if not jobs:
        return await call.message.answer("У вас нет опубликованных вакансий.")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Удалить: {j[:20]}", callback_data=f"del:{i}")]
            for i, j in enumerate(jobs)
        ]
    )
    await call.message.answer("Ваши вакансии:", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("del:"))
async def delete_job(call: CallbackQuery):
    idx = int(call.data.split(":")[1])
    if delete_job_by_id(call.from_user.id, idx):
        await call.message.answer("✅ Вакансия удалена.")
    else:
        await call.message.answer("❌ Не удалось удалить вакансию.")

@router.message(Command("allow_posting"), F.chat.type == ChatType.PRIVATE)
async def allow_posting(msg: Message):
    # Проверка прав администратора
    if msg.from_user.id not in ADMINS:
        return await msg.reply("❌ У вас нет прав.")
    parts = msg.text.split()
    # Ожидаем '/allow_posting <user_id>'
    if len(parts) != 2 or not parts[1].isdigit():
        return await msg.reply("Использование: /allow_posting <user_id>")
    uid = int(parts[1])
    # Даем право публиковать без дополнительных проверок
    mark_user_allowed(uid)
    await msg.reply(f"✅ Пользователь {uid} теперь может публиковать.")

@router.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def restrict_group_msgs(msg: Message):
    if msg.from_user.id not in ADMINS:
        await msg.delete()
