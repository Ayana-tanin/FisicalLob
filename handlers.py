import re
import asyncio
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db_connection import *
from config import CHANNEL_ID, CHANNEL_URL, ADMINS, ADMIN_USERNAME

logger = logging.getLogger(__name__)
router = Router()

class VacancyForm(StatesGroup):
    all_info = State()

# Шаблоны полей и телефонный формат
TEMPLATE = {
    "address": r"^📍\s*Адрес:\s*(.+)$",
    "title":   r"^📝\s*Задача:\s*(.+)$",
    "payment": r"^💵\s*Оплата:\s*(.+)$",
    "contact": r"^☎️\s*Контакт:\s*(.+)$",
    "extra":   r"^📌\s*Примечание:\s*(.*)$",
}
PHONE_RE = re.compile(r"^\+?\d[\d\s\-]{7,}\d$")
kb_menu = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Выложить вакансию", callback_data="create")],
        [InlineKeyboardButton(text="📋 Мои вакансии", callback_data="list")],
        [InlineKeyboardButton(text="🌐 Канал", url=CHANNEL_URL)]
    ])

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: Message):
    """Приветствие и меню"""
    insert_user(msg.from_user.id, msg.from_user.username or "")
    await msg.answer(
        "👋 Привет! Я помогу опубликовать вашу вакансию. Выберите действие:",
        reply_markup=kb_menu
    )

@router.callback_query(F.data == "create")
async def prepare_vacancy(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "📄 Отправьте вакансию по шаблону, без изменений до :\n\n"
        "📍 Адрес: Бишкек, ул. Ленина 1\n"
        "📝 Задача: Курьер на 2 часа\n"
        "💵 Оплата: 500 сом\n"
        "☎️ Контакт: +996501234567\n"
        "📌 Примечание: (необязательно)",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(VacancyForm.all_info)

# Обработка формы и публикация вакансии
@router.message(VacancyForm.all_info)
async def process_vacancy(msg: Message, state: FSMContext, bot: Bot):
    data = {}
    for line in msg.text.splitlines():
        for key, pat in TEMPLATE.items():
            m = re.match(pat, line.strip())
            if m:
                data[key] = m.group(1).strip()
    # Валидация
    for fld in ("address", "title", "payment", "contact"):
        if fld not in data:
            await msg.reply(f"❌ Поле '{fld}' не найдено. Повторите по шаблону. В точности, без изменений")
            return

    uid = msg.from_user.id
    if not can_post_more(uid):
        if uid not in ADMINS:
            await msg.answer(
                "🔒 Вы уже опубликовали вакансию. Чтобы постить ещё, оплатите 100 сом или добавьте 5 друзей в группу.\n"
                f"Свяжитесь с админом: https://t.me/{ADMIN_USERNAME}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Админ", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])
            )
            await state.clear()
            return

    # Публикация вакансии в канал
    posted = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=(f"<b>Вакансия: {data['title']}</b>\n"
              f"📍 Адрес: {data['address']}\n"
              f"💵 Оплата: {data['payment']}\n"
              f"☎️ Контакт: {data['contact']}"
              + (f"\n📌 Примечание: {data['extra']}" if data.get('extra') else "")),
        parse_mode=ParseMode.HTML
    )

    # Сохраняем вакансию в базу
    saved = await asyncio.to_thread(save_job_db, uid, posted.message_id, data)
    if not saved:
        await msg.answer("❌ Ошибка при сохранении вакансии в базе.")
        return

    update_invite_count(uid)

    await msg.answer(
        "✅ Ваша вакансия опубликована. Чтобы удалить — выберите 'Мои вакансии'.",
        reply_markup=kb_menu
    )
    await state.clear()


#осмотр вакансий с заголовками
@router.callback_query(F.data == "list")
async def list_vacancies(call: CallbackQuery):
    await call.answer()
    jobs = await asyncio.to_thread(get_user_jobs_db, call.from_user.id)
    if not jobs:
        await call.message.edit_text("У вас пока нет вакансий.")
        return

    buttons = []
    for idx, job in enumerate(jobs):
        title = job.all_info.get("title", "Без названия")
        snippet = title if len(title) <= 20 else title[:17] + "..."
        buttons.append([
            InlineKeyboardButton(text=f"❌ Удалить: {snippet}", callback_data=f"del:{idx}")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("Ваши вакансии:", reply_markup=kb)

@router.callback_query(lambda c: c.data and c.data.startswith("del:"))
async def delete_vacancy_handler(call: CallbackQuery):
    await call.answer()
    idx = int(call.data.split(":")[1])
    user_id = call.from_user.id

    message_id, success = await asyncio.to_thread(delete_job_and_get_message, user_id, idx)
    if not success:
        await call.message.answer("❌ Вакансия не найдена или не удалена.")
        return

    try:
        await call.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение в Telegram: {e}")

    jobs = await asyncio.to_thread(get_user_jobs_db, user_id)
    if not jobs:
        await call.message.edit_text("У вас пока нет вакансий.")
        return

    buttons = []
    for i, job in enumerate(jobs):
        title = job.all_info.get("title", "Без названия")
        snippet = title if len(title) <= 20 else title[:17] + "..."
        buttons.append([
            InlineKeyboardButton(text=f"❌ Удалить: {snippet}", callback_data=f"del:{i}")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("Ваши вакансии:", reply_markup=kb)

@router.message(Command("allow_posting"))
async def allow_posting_handler(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("❗️ Использование: /allow_posting @username или /allow_posting user_id")
        return

    args = parts[1].strip()

    success, response_msg = allow_user_posting(args)
    await message.answer(response_msg)


@router.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def block_non_admins(message: Message):
    """Блокирует сообщения в группах от не-админов"""
    if message.from_user and message.from_user.id not in ADMINS:
        await message.delete()
        bot = message.bot
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Опубликовать вакансию",
                url=f"https://t.me/{(await bot.get_me()).username}"
            )]
        ])
        warn = await message.answer(
            "<b>Сообщения в группе от пользователей запрещены.</b>\n"
            "Чтобы опубликовать вакансию — пишите боту в личку.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(120)
        try:
            await warn.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить предупреждение: {e}")
