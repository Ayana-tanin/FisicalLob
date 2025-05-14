import re
import json
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db_connection import insert_user, can_post_more, mark_user_allowed, get_user_jobs, delete_user_job, update_invite_count
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
async def handle_job(msg: Message, state: FSMContext, bot: Bot):
    user_id = msg.from_user.id
    text = msg.text.strip()
    data = {}
    for line in text.splitlines():
        for key, pattern in TEMPLATE.items():
            m = re.match(pattern, line.strip())
            if m:
                data[key] = m.group(1).strip()

    # Проверка наличия контакта (номер телефона)
    if "contact" not in data:
        return await msg.reply(
            "❌ Контакт (номер телефона) обязателен. Пожалуйста, укажите его в формате:\n"
            "☎️ Контакт: +996501234567"
        )

    if not can_post_more(user_id):
        await msg.answer(
            "🔒 Вы уже выложили 1 вакансию. Чтобы продолжить:\n\n"
            "💰 Оплатите 100 сом админу или\n"
            "👥 Пригласите 5 друзей в группу.\n\n"
            "После этого админ может дать вам разрешение.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👤 Связаться с админом", url=f"https://t.me/{ADMIN_USERNAME}")]
            ])
        )
        await state.clear()
        return

    # публикация в канал
    job_text = (
        f"<b>Вакансия: {data.get('title', '')}</b>\n"
        f"📍 Адрес: {data.get('address', '')}\n"
        f"💵 Оплата: {data.get('payment', '')}\n"
        f"☎️ Контакт: {data['contact']}"
    )
    if data.get("extra"):
        job_text += f"\n📌 {data['extra']}"
    await bot.send_message(CHANNEL_ID, job_text)

    update_invite_count(user_id)
    await msg.answer("✅ Вакансия опубликована!")
    await state.clear()

@router.callback_query(F.data == "myjobs")
async def list_jobs(call: CallbackQuery):
    jobs = get_user_jobs(call.from_user.id)
    if not jobs:
        return await call.message.answer("Нет вакансий.")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"Удалить: {j[:20]}", callback_data=f"del:{i}")
        ] for i, j in enumerate(jobs)]
    )
    await call.message.answer("Ваши вакансии:", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("del:"))
async def delete_job(call: CallbackQuery):
    job_id = int(call.data.split(":")[1])
    if delete_user_job(call.from_user.id, job_id):
        await call.message.answer("✅ Вакансия удалена.")
    else:
        await call.message.answer("❌ Не удалось удалить.")

@router.message(Command("allow_posting"), F.chat.type == ChatType.PRIVATE)
async def allow_posting(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.reply("❌ Нет доступа.")
    args = msg.text.split()
    if len(args) != 2:
        return await msg.reply("Формат: /allow_posting ID")
    try:
        uid = int(args[1])
        mark_user_allowed(uid)
        await msg.reply(f"✅ Пользователь {uid} теперь может публиковать.")
    except:
        await msg.reply("❌ Ошибка ID")

@router.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def restrict_group_msgs(msg: Message):
    if msg.from_user.id not in ADMINS:
        await msg.delete()
