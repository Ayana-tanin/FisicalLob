import re
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType
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
async def handle_job(msg: Message, state: FSMContext, bot: Bot):
    user_id = msg.from_user.id
    text = msg.text.strip()
    data = {}
    for line in text.splitlines():
        for key, pattern in TEMPLATE.items():
            m = re.match(pattern, line.strip())
            if m:
                data[key] = m.group(1).strip()
    if not all(k in data for k in ("address", "title", "payment", "contact")):
        return await msg.reply("❌ Все обязательные поля должны быть заполнены по шаблону.")

    if not can_post_more(user_id):
        await msg.answer(
            "🔒 Вы уже выложили 1 вакансию. Чтобы продолжить:\n\n"
            "💰 Оплатите 100 сом админу <b> или<b/>\n"
            "👥 Пригласите 5 друзей в группу.\n\n"
            "После этого админ может дать вам разрешение.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👤 Связаться с админом", url=f"https://t.me/{ADMIN_USERNAME}")]
            ])
        )
        await state.clear()
        return

    job_text = (
        f"<b>Вакансия: {data['title']}</b>\n"
        f"📍 Адрес: {data['address']}\n"
        f"💵 Оплата: {data['payment']}\n"
        f"☎️ Контакт: {data['contact']}"
    )
    if data.get("extra"):
        job_text += f"\n📌 {data['extra']}"

    msg_sent = await bot.send_message(CHANNEL_ID, job_text)
    save_job(user_id=user_id, message_id=msg_sent.message_id, all_info=data)
    # print(f"[DEBUG] Сохраняю в БД: {user_id=}, {msg_sent.message_id=}, {data=}")

    update_invite_count(user_id)
    await msg.answer("✅ Вакансия опубликована!")
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
