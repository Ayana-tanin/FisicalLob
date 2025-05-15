import re
import asyncio
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db_connection import (
    insert_user,
    can_post_more,
    mark_user_allowed,
    save_job,
    get_user_jobs,
    delete_job_by_id,
    update_invite_count,
)
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
            await msg.reply(f"❌ Поле '{fld}' не найдено. Повторите по шаблону.")
            return

    uid = msg.from_user.id
    # Лимит публикаций
    if not can_post_more(uid):
        if msg.from_user.id not in ADMINS:
            await msg.answer(
                "🔒 Вы уже опубликовали вакансию. Чтобы постить ещё, оплатите 100 сом или пригласите 5 друзей.\n"
                f"Свяжитесь с админом: https://t.me/{ADMIN_USERNAME}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Админ", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])
            )
            await state.clear()
            return

    save_job(uid, msg.text)
    update_invite_count(uid)

    # Публикация в канал
    posted = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=(f"<b>Вакансия: {data['title']}</b>\n"
              f"📍 Адрес: {data['address']}\n"
              f"💵 Оплата: {data['payment']}\n"
              f"☎️ Контакт: {data['contact']}"
              + (f"\n📌 Примечание: {data['extra']}" if data.get('extra') else "")),
        parse_mode=ParseMode.HTML
    )

    await msg.answer(
        "✅ Ваша вакансия опубликована. Чтобы удалить — выберите 'Мои вакансии'.",
        reply_markup=kb_menu
    )
    await state.clear()

    # URL для отклика
    # if msg.from_user.username:
    #     reply_url = f"https://t.me/{msg.from_user.username}"
    # else:
    #     reply_url = f"tg://user?id={msg.from_user.id}"
    # markup = InlineKeyboardMarkup(inline_keyboard=[
    #     [InlineKeyboardButton(text="💬 Откликнуться", url=reply_url)]
    # ])


# Просмотр вакансий с заголовками
@router.callback_query(F.data == "list")
async def list_vacancies(call: CallbackQuery):
    await call.answer()
    jobs = get_user_jobs(call.from_user.id)
    if not jobs:
        return await call.message.answer("У вас пока нет вакансий.")

    buttons = []
    for idx, text in enumerate(jobs):
        snippet = text if len(text) <= 20 else text[:17] + "..."
        buttons.append([
            InlineKeyboardButton(text=f"❌ Удалить: {snippet}", callback_data=f"del:{idx}")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer("Ваши вакансии:", reply_markup=kb)

@router.callback_query(lambda c: c.data and c.data.startswith("del:"))
async def delete_vacancy_handler(call: CallbackQuery):
    await call.answer()
    idx = int(call.data.split(":")[1])
    if delete_job_by_id(call.from_user.id, idx):
        await call.message.answer("✅ Вакансия удалена.")
    else:
        await call.message.answer("❌ Ошибка при удалении.")

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
