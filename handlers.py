import re
import asyncio
import logging
import signal
import sys

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, \
    KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
from sqlalchemy import func

from db_connection import *
from config import CHANNEL_ID, CHANNEL_URL, ADMINS, ADMIN_USERNAME

logger = logging.getLogger(__name__)
router = Router()


class VacancyForm(StatesGroup):
    all_info = State()


# Шаблоны полей и телефонный формат
TEMPLATE = {
    "address": r"^📍\s*Адрес:\s*(.+)$",
    "title": r"^📝\s*Задача:\s*(.+)$",
    "payment": r"^💵\s*Оплата:\s*(.+)$",
    "contact": r"^☎️\s*Контакт:\s*(.+)$",
    "extra": r"^📌\s*Примечание:\s*(.*)$",
}
PHONE_RE = re.compile(r"^\+?\d[\d\s\-]{7,}\d$")

kb_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✉️ Выложить вакансию")],
        [KeyboardButton(text="💳 Оплатить")],
        [KeyboardButton(text="📞 Связаться с админом")],
        [KeyboardButton(text="📋 Мои вакансии")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие"
)


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: Message):
    """Приветствие и меню"""
    try:
        insert_user(msg.from_user.id, msg.from_user.username or "")
    except Exception as e:
        logger.error(f"Ошибка при добавлении пользователя: {e}")

    await msg.answer(
        "👋 Привет! Я бот для публикации вакансий.\n\n"
        "🎁 Первая публикация бесплатно!\n"
        "📝 Для следующих вакансий:\n"
        "• Оплатить 100 сом\n"
        "• Или добавить 5 друзей в группу",
        reply_markup=kb_menu
    )


@router.message(F.text == "✉️ Выложить вакансию")
async def prepare_vacancy_button(msg: Message, state: FSMContext):
    """Обработчик кнопки создания вакансии"""
    await prepare_vacancy_impl(msg, state)


@router.callback_query(F.data == "create")
async def prepare_vacancy(call: CallbackQuery, state: FSMContext):
    """Обработчик callback для создания вакансии"""
    await call.answer()
    await prepare_vacancy_impl(call.message, state)


async def prepare_vacancy_impl(msg: Message, state: FSMContext):
    """Общая логика подготовки вакансии"""
    user_id = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id

    # Проверяем возможность публикации
    can_post, message, invites_count = can_post_more_extended(user_id)

    if not can_post:
        if user_id not in ADMINS:
            await msg.answer(
                f"🔒 {message}\n"
                f"👥 Вы добавили: {invites_count}/5 друзей\n\n"
                f"💰 Оплатить: https://t.me/{ADMIN_USERNAME}\n"
                f"👥 Или добавьте ещё {5 - invites_count} друзей в группу",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Админ", url=f"https://t.me/{ADMIN_USERNAME}")],
                    [InlineKeyboardButton(text="👥 Группа", url=CHANNEL_URL)]
                ])
            )
            return

    await msg.answer(
        "📄 Заполните вакансию по шаблону, без изменений наименований:\n\n"
        "📍 Адрес: \n"
        "📝 Задача: \n"
        "💵 Оплата: \n"
        "☎️ Контакт: \n"
        "📌 Примечание: (необязательно)\n\n"
        "⚠️ Строго соблюдайте формат!",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(VacancyForm.all_info)


@router.message(F.text == "📋 Мои вакансии")
async def my_vacancies(msg: Message):
    """Показать список вакансий пользователя"""
    try:
        with SessionLocal() as session:
            jobs = session.query(Job).filter_by(user_id=msg.from_user.id).order_by(Job.created_at.desc()).all()
            
            if not jobs:
                await msg.answer(
                    "📭 У вас пока нет опубликованных вакансий.",
                    reply_markup=kb_menu
                )
                return
            
            for job in jobs:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_job_{job.id}"),
                        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_job_{job.id}")
                    ]
                ])
                
                job_text = (
                    f"<b>🔥 {job.all_info['title']}</b>\n\n"
                    f"📍 <b>Адрес:</b> {job.all_info['address']}\n"
                    f"💵 <b>Оплата:</b> {job.all_info['payment']}\n"
                    f"☎️ <b>Контакт:</b> {job.all_info['contact']}"
                )
                
                if job.all_info.get('extra'):
                    job_text += f"\n📌 <b>Примечание:</b> {job.all_info['extra']}"
                
                job_text += f"\n\n📅 Опубликовано: {job.created_at.strftime('%d.%m.%Y %H:%M')}"
                
                await msg.answer(
                    job_text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML
                )
    
    except Exception as e:
        logger.error(f"Ошибка при получении списка вакансий: {e}")
        await msg.answer("❌ Произошла ошибка при получении списка вакансий.")


@router.callback_query(F.data.startswith("edit_job_"))
async def edit_job_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования вакансии"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена")
                return
            
            # Сохраняем ID вакансии в состоянии
            await state.update_data(editing_job_id=job_id)
            
            # Формируем текущий текст вакансии
            current_text = (
                "📄 Текущая вакансия:\n\n"
                f"📍 Адрес: {job.all_info['address']}\n"
                f"📝 Задача: {job.all_info['title']}\n"
                f"💵 Оплата: {job.all_info['payment']}\n"
                f"☎️ Контакт: {job.all_info['contact']}"
            )
            if job.all_info.get('extra'):
                current_text += f"\n📌 Примечание: {job.all_info['extra']}"
            
            current_text += "\n\nОтправьте новую версию вакансии в том же формате:"
            
            await callback.message.edit_text(
                current_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_edit_{job_id}")]
                ])
            )
            
            await state.set_state(VacancyForm.all_info)
            await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при редактировании вакансии: {e}")
        await callback.answer("❌ Произошла ошибка при редактировании")


@router.callback_query(F.data.startswith("delete_job_"))
async def delete_job_callback(callback: CallbackQuery):
    """Обработчик удаления вакансии"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена")
                return
            
            # Удаляем сообщение из канала
            try:
                await callback.bot.delete_message(
                    chat_id=CHANNEL_ID,
                    message_id=job.message_id
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение из канала: {e}")
            
            # Удаляем из базы
            session.delete(job)
            session.commit()
            
            await callback.message.edit_text(
                "✅ Вакансия успешно удалена",
                reply_markup=None
            )
            await callback.answer("✅ Вакансия удалена")
    
    except Exception as e:
        logger.error(f"Ошибка при удалении вакансии: {e}")
        await callback.answer("❌ Произошла ошибка при удалении")


@router.callback_query(F.data.startswith("cancel_edit_"))
async def cancel_edit_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования вакансии"""
    try:
        await state.clear()
        await callback.message.edit_text(
            "❌ Редактирование отменено",
            reply_markup=None
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при отмене редактирования: {e}")
        await callback.answer("❌ Произошла ошибка")


@router.message(F.text == "💳 Оплатить")
async def payment_button(msg: Message):
    """Обработчик кнопки оплаты"""
    await msg.answer(
        "💰 Для оплаты свяжитесь с админом:\n\n"
        "💵 Стоимость: 100 сом\n"
        "⏰ После оплаты возможность публикации одной вакнсии",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Связаться с админом", url=f"https://t.me/{ADMIN_USERNAME}")]
        ])
    )


@router.message(F.text == "📞 Связаться с админом")
async def contact_admin_button(msg: Message):
    """Обработчик кнопки связи с админом"""
    await msg.answer(
        "👤 Свяжитесь с админом для решения вопросов:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Написать админу", url=f"https://t.me/AkylaiMamyt")]
        ])
    )


# Обработка формы и публикация вакансии
@router.message(VacancyForm.all_info)
async def process_vacancy(msg: Message, state: FSMContext, bot: Bot):
    """Обработка заполненной формы вакансии"""
    try:
        # Получаем данные о редактировании
        state_data = await state.get_data()
        editing_job_id = state_data.get('editing_job_id')
        
        uid = msg.from_user.id

        # Проверяем существование пользователя в базе
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=uid).first()
            if not user:
                # Если пользователя нет, создаем его
                try:
                    insert_user(uid, msg.from_user.username or "")
                    user = session.query(User).filter_by(telegram_id=uid).first()
                except Exception as e:
                    logger.error(f"Ошибка при создании пользователя {uid}: {e}")
                    # Отправляем ошибку админам
                    for admin_id in ADMINS:
                        try:
                            await bot.send_message(
                                admin_id,
                                f"❌ Ошибка при создании пользователя:\n"
                                f"User ID: {uid}\n"
                                f"Username: {msg.from_user.username}\n"
                                f"Error: {str(e)}"
                            )
                        except Exception as admin_e:
                            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
                    
                    await msg.answer(
                        "❌ Произошла ошибка. Пожалуйста, попробуйте позже или обратитесь к администратору.",
                        reply_markup=kb_menu
                    )
                    await state.clear()
                    return

        # Проверка на спам (только для новых вакансий)
        if not editing_job_id:
            with SessionLocal() as session:
                last_job = session.query(Job).filter(
                    Job.user_id == uid,
                    Job.created_at >= datetime.now() - timedelta(minutes=5)
                ).first()
                
                if last_job and (datetime.now() - last_job.created_at).total_seconds() < 300:
                    await msg.answer(
                        "⏳ Подождите 5 минут перед публикацией следующей вакансии.",
                        reply_markup=kb_menu
                    )
                    await state.clear()
                    return

        # Парсинг данных
        data = {}
        lines = msg.text.strip().splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            for key, pat in TEMPLATE.items():
                m = re.match(pat, line)
                if m:
                    data[key] = m.group(1).strip()
                    break

        # Валидация обязательных полей
        required_fields = ["address", "title", "payment", "contact"]
        missing_fields = []

        for field in required_fields:
            if field not in data or not data[field]:
                missing_fields.append(field)

        if missing_fields:
            field_names = {
                "address": "📍 Адрес",
                "title": "📝 Задача",
                "payment": "💵 Оплата",
                "contact": "☎️ Контакт"
            }
            missing_names = [field_names[f] for f in missing_fields]
            await msg.reply(
                f"❌ Не заполнены поля: {', '.join(missing_names)}\n\n"
                "Пожалуйста, заполните форму заново по шаблону:"
            )
            await prepare_vacancy_impl(msg, state)
            return

        # Валидация телефона
        if not PHONE_RE.match(data['contact']):
            await msg.reply(
                "❌ Неверный формат телефона. Используйте формат: +996XXXXXXXXX\n"
                "Пожалуйста, заполните форму заново:"
            )
            await prepare_vacancy_impl(msg, state)
            return

        # Повторная проверка возможности публикации
        can_post, message, invites_count = can_post_more_extended(uid)
        if not can_post and uid not in ADMINS:
            await msg.answer(
                f"🔒 {message}\n"
                f"👥 Вы добавили: {invites_count}/5 друзей\n\n"
                f"💰 Оплатить: https://t.me/{ADMIN_USERNAME}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Админ", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])
            )
            await state.clear()
            return

        # Если это редактирование
        if editing_job_id:
            with SessionLocal() as session:
                job = session.query(Job).filter_by(id=editing_job_id, user_id=msg.from_user.id).first()
                if not job:
                    await msg.answer("❌ Вакансия не найдена")
                    await state.clear()
                    return
                
                # Обновляем данные
                job.all_info = data
                
                # Обновляем сообщение в канале
                vacancy_text = (
                    f"<b>Вакансия {data['title']}</b>\n\n"
                    f"📍 <b>Адрес:</b> {data['address']}\n"
                    f"💵 <b>Оплата:</b> {data['payment']}\n"
                    f"☎️ <b>Контакт:</b> {data['contact']}"
                )
                
                if data.get('extra'):
                    vacancy_text += f"\n📌 <b>Примечание:</b> {data['extra']}"
                
                try:
                    # Обновляем текст сообщения
                    await bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=job.message_id,
                        text=vacancy_text,
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Обновляем кнопку отклика
                    response_button = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="📨 Откликнуться",
                            url=f"https://t.me/{msg.from_user.username}" if msg.from_user.username
                            else f"tg://user?id={msg.from_user.id}"
                        )]
                    ])
                    
                    await bot.edit_message_reply_markup(
                        chat_id=CHANNEL_ID,
                        message_id=job.message_id,
                        reply_markup=response_button
                    )
                    
                    session.commit()
                    await msg.answer(
                        "✅ Вакансия успешно обновлена!",
                        reply_markup=kb_menu
                    )
                except Exception as e:
                    logger.error(f"Ошибка при обновлении сообщения в канале: {e}")
                    await msg.answer(
                        "❌ Не удалось обновить вакансию в канале. Попробуйте позже.",
                        reply_markup=kb_menu
                    )
        else:
            try:
                # Публикация в канал
                vacancy_text = (
                    f"<b>Вакансия {data['title']}</b>\n\n"
                    f"📍 <b>Адрес:</b> {data['address']}\n"
                    f"💵 <b>Оплата:</b> {data['payment']}\n"
                    f"☎️ <b>Контакт:</b> {data['contact']}"
                )

                if data.get('extra'):
                    vacancy_text += f"\n📌 <b>Примечание:</b> {data['extra']}"

                posted = await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=vacancy_text,
                    parse_mode=ParseMode.HTML
                )

                # Кнопка отклика
                response_button = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="📨 Откликнуться",
                        url=f"https://t.me/{msg.from_user.username}" if msg.from_user.username
                        else f"tg://user?id={msg.from_user.id}"
                    )]
                ])

                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=posted.message_id,
                    reply_markup=response_button
                )

                # Сохранение в базу
                try:
                    saved = await asyncio.to_thread(save_job_db, uid, posted.message_id, data)
                    if not saved:
                        raise Exception("Не удалось сохранить вакансию в базу данных")
                except Exception as e:
                    # Отправляем ошибку админам
                    for admin_id in ADMINS:
                        try:
                            await bot.send_message(
                                admin_id,
                                f"❌ Ошибка при сохранении вакансии:\n"
                                f"User ID: {uid}\n"
                                f"Message ID: {posted.message_id}\n"
                                f"Error: {str(e)}\n"
                                f"Data: {data}"
                            )
                        except Exception as admin_e:
                            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
                    
                    # Удаляем сообщение из канала, так как не смогли сохранить в базу
                    try:
                        await bot.delete_message(chat_id=CHANNEL_ID, message_id=posted.message_id)
                    except Exception as delete_e:
                        logger.error(f"Не удалось удалить сообщение из канала: {delete_e}")
                    
                    await msg.answer(
                        "❌ Произошла ошибка при сохранении вакансии. Пожалуйста, попробуйте позже или обратитесь к администратору.",
                        reply_markup=kb_menu
                    )
                    await state.clear()
                    return

                # Уменьшение счетчика публикаций (только если это не админ, не can_post=True и не первая публикация)
                try:
                    with SessionLocal() as session:
                        user = session.query(User).filter_by(telegram_id=uid).first()
                        if user:
                            # Проверяем, первая ли это публикация
                            job_count = session.query(func.count(Job.id)).filter_by(user_id=uid).scalar()
                            
                            # Уменьшаем счетчик только если:
                            # 1. Это не первая публикация
                            # 2. У пользователя нет постоянного разрешения (can_post=False)
                            # 3. Есть доступные публикации
                            if job_count > 1 and not user.can_post and user.allowed_posts > 0:
                                user.allowed_posts -= 1
                                session.commit()
                                logger.info(f"Уменьшен счетчик публикаций для пользователя {uid}")
                except Exception as e:
                    logger.error(f"Ошибка при обновлении счетчика публикаций: {e}")
                    # Отправляем ошибку админам
                    for admin_id in ADMINS:
                        try:
                            await bot.send_message(
                                admin_id,
                                f"❌ Ошибка при обновлении счетчика публикаций:\n"
                                f"User ID: {uid}\n"
                                f"Error: {str(e)}"
                            )
                        except Exception as admin_e:
                            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")

                await msg.answer(
                    "✅ Ваша вакансия успешно опубликована!\n\n"
                    f"📄 Ссылка: {CHANNEL_URL}/{posted.message_id}\n"
                    "📋 Для управления вакансиями используйте 'Мои вакансии' \n Это даст возможность удалить или отредактировать вакансию",
                    reply_markup=kb_menu
                )

            except Exception as e:
                logger.error(f"Ошибка при публикации вакансии: {e}")
                # Отправляем ошибку админам
                for admin_id in ADMINS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"❌ Ошибка при публикации вакансии:\n"
                            f"User ID: {uid}\n"
                            f"Error: {str(e)}\n"
                            f"Data: {data}"
                        )
                    except Exception as admin_e:
                        logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
                
                await msg.answer(
                    "❌ Произошла ошибка при публикации вакансии. Пожалуйста, попробуйте позже или обратитесь к администратору.",
                    reply_markup=kb_menu
                )

        await state.clear()

    except Exception as e:
        logger.error(f"Критическая ошибка при обработке вакансии: {e}")
        # Отправляем ошибку админам
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f"❌ Критическая ошибка при обработке вакансии:\n"
                    f"User ID: {msg.from_user.id}\n"
                    f"Error: {str(e)}"
                )
            except Exception as admin_e:
                logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
        
        await msg.answer(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже или обратитесь к администратору.",
            reply_markup=kb_menu
        )
        await state.clear()


def can_post_more_extended(user_id: int) -> tuple[bool, str, int]:
    """
    Расширенная проверка возможности публикации вакансии
    Возвращает: (может_публиковать, сообщение, количество_приглашений)
    """
    try:
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()

            if not user:
                # Новый пользователь - первая публикация бесплатно
                return True, "Первая публикация бесплатно!", 0

            # Если у пользователя can_post = True - всегда можем публиковать
            if user.can_post:
                return True, "У вас есть постоянное разрешение на публикацию", user.invites

            # Проверка месячной подписки
            if user.can_post_until and user.can_post_until > datetime.now():
                return True, f"У вас есть месячная подписка до {user.can_post_until.strftime('%d.%m.%Y %H:%M')}", user.invites

            # Проверка разовых публикаций
            if user.allowed_posts > 0:
                return True, f"Осталось публикаций: {user.allowed_posts}", user.invites

            # Проверка первой бесплатной публикации
            job_count = session.query(func.count(Job.id)).filter_by(user_id=user_id).scalar()
            if job_count == 0:
                return True, "Первая публикация бесплатно!", user.invites

            # Проверка приглашенных друзей (5+ друзей = 1 публикация)
            if user.invites >= 5:
                # Даем одну публикацию и сбрасываем счетчик приглашений
                user.allowed_posts = 1
                user.invites = 0  # Сбрасываем счетчик
                session.commit()
                return True, "Получена публикация за приглашение друзей!", 0

            return False, "У вас нет доступных публикаций.", user.invites

    except Exception as e:
        logger.error(f"Ошибка при can_post_more_extended для пользователя {user_id}: {e}")
        return False, "Ошибка при проверке прав доступа.", 0


@router.message(Command("allow_posting"))
async def allow_posting_handler(message: Message):
    """Команда для админов - предоставление прав публикации"""
    if message.from_user.id not in ADMINS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.answer(
                "📝 Использование:\n"
                "/allow_posting @username - одна публикация\n"
                "/allow_posting month @username - месяц публикаций\n"
                "/allow_posting permanent @username - постоянное разрешение"
            )
            return

        is_month = (len(parts) == 3 and parts[1].lower() == "month")
        is_permanent = (len(parts) == 3 and parts[1].lower() == "permanent")
        username_or_id = parts[2] if (is_month or is_permanent) else parts[1]

        with SessionLocal() as session:
            user = None

            if username_or_id.startswith("@"):
                user = session.query(User).filter_by(username=username_or_id[1:]).first()
            elif username_or_id.isdigit():
                user = session.query(User).filter_by(telegram_id=int(username_or_id)).first()

            if not user:
                await message.answer("❌ Пользователь не найден в базе.")
                return

            # Сохраняем старые значения для логирования
            old_can_post = user.can_post
            old_can_post_until = user.can_post_until
            old_allowed_posts = user.allowed_posts

            try:
                if is_permanent:
                    # Постоянное разрешение - устанавливаем can_post = True
                    user.can_post = True
                    user.can_post_until = None
                    user.allowed_posts = 0
                    msg = f"✅ Пользователю {username_or_id} предоставлено постоянное разрешение на публикацию."
                    logger.info(
                        f"Админ {message.from_user.id} выдал постоянное разрешение пользователю {user.telegram_id} "
                        f"(было: can_post={old_can_post}, can_post_until={old_can_post_until}, allowed_posts={old_allowed_posts})"
                    )
                elif is_month:
                    # Месячная подписка - сбрасываем can_post
                    user.can_post = False
                    user.can_post_until = datetime.now() + timedelta(days=30)
                    user.allowed_posts = 0
                    msg = f"✅ Пользователю {username_or_id} предоставлен месяц публикаций до {user.can_post_until.strftime('%d.%m.%Y %H:%M')}"
                    logger.info(
                        f"Админ {message.from_user.id} выдал месячную подписку пользователю {user.telegram_id} "
                        f"(было: can_post={old_can_post}, can_post_until={old_can_post_until}, allowed_posts={old_allowed_posts})"
                    )
                else:
                    # Разовая публикация - сбрасываем can_post
                    user.can_post = False
                    user.can_post_until = None
                    user.allowed_posts += 1
                    msg = f"✅ Пользователю {username_or_id} добавлена 1 публикация. Всего: {user.allowed_posts}"
                    logger.info(
                        f"Админ {message.from_user.id} добавил публикацию пользователю {user.telegram_id} "
                        f"(было: can_post={old_can_post}, can_post_until={old_can_post_until}, allowed_posts={old_allowed_posts})"
                    )

                session.commit()
                
                # Проверяем, что изменения сохранились
                session.refresh(user)
                if is_permanent and not user.can_post:
                    raise Exception("Не удалось установить постоянное разрешение")
                
                await message.answer(msg)
                
                # Отправляем уведомление пользователю
                try:
                    await message.bot.send_message(
                        user.telegram_id,
                        f"🎉 {msg}\n\n"
                        "Теперь вы можете опубликовать вакансию через меню бота."
                    )
                except Exception as notify_e:
                    logger.error(f"Не удалось отправить уведомление пользователю {user.telegram_id}: {notify_e}")
                
            except Exception as e:
                logger.error(f"Ошибка при обновлении прав пользователя {user.telegram_id}: {e}")
                session.rollback()
                await message.answer(
                    "❌ Произошла ошибка при обновлении прав. Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
                )
                return

    except Exception as e:
        logger.error(f"Ошибка в allow_posting_handler: {e}")
        await message.answer(
            "❌ Произошла ошибка при выполнении команды. Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )


@router.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def handle_group_messages(message: Message):
    """Обработка сообщений в группах"""
    try:
        # Отслеживание новых участников для системы приглашений
        if message.new_chat_members:
            for new_member in message.new_chat_members:
                if not new_member.is_bot and message.from_user:
                    try:
                        with SessionLocal() as session:
                            # Получаем пользователя-приглашающего
                            inviter = session.query(User).filter_by(telegram_id=message.from_user.id).first()
                            if not inviter:
                                continue
                            
                            # Увеличиваем счетчик приглашений
                            inviter.invites += 1
                            
                            # Если достигли 5 приглашений, даем публикацию
                            if inviter.invites >= 5 and inviter.invites % 5 == 0:
                                inviter.allowed_posts += 1
                            
                            session.commit()
                            logger.info(f"Пользователь {message.from_user.id} пригласил {new_member.id}")
                    except Exception as e:
                        logger.error(f"Ошибка при обновлении счетчика приглашений: {e}")
            return

        # Обработка выхода пользователей
        if message.left_chat_member:
            try:
                with SessionLocal() as session:
                    # Получаем пользователя, который пригласил ушедшего участника
                    # (это может быть любой пользователь, который приглашал участников)
                    inviter = session.query(User).filter(
                        User.invites > 0  # Берем пользователя, у которого есть приглашения
                    ).order_by(User.invites.desc()).first()
                    
                    if inviter:
                        # Уменьшаем счетчик приглашений
                        if inviter.invites > 0:
                            inviter.invites -= 1
                            
                            # Если количество приглашений стало меньше 5,
                            # отменяем бонусную публикацию
                            if inviter.invites < 5 and inviter.allowed_posts > 0:
                                inviter.allowed_posts -= 1
                            
                            session.commit()
                            logger.info(f"Пользователь {message.left_chat_member.id} покинул группу")
            except Exception as e:
                logger.error(f"Ошибка при обработке выхода пользователя: {e}")
            return

        # Блокировка сообщений от не-админов
        if message.from_user and message.from_user.id not in ADMINS:
            await message.delete()

            bot = message.bot
            bot_info = await bot.get_me()

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📝 Опубликовать вакансию",
                    url=f"https://t.me/{bot_info.username}"
                )]
            ])

            warn = await message.answer(
                "<b>⚠️ Сообщения в группе запрещены!</b>\n\n"
                "📝 Для публикации вакансий пишите боту в личные сообщения.\n"
                "👥 Приглашайте друзей для получения бесплатных публикаций!",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )

            # Удаляем предупреждение через 2 минуты
            await asyncio.sleep(120)
            try:
                await warn.delete()
            except Exception as e:
                logger.error(f"Не удалось удалить предупреждение: {e}")

    except Exception as e:
        logger.error(f"Ошибка в handle_group_messages: {e}")


@router.message(Command("stats"))
async def stats_handler(message: Message):
    """Статистика для админов"""
    if message.from_user.id not in ADMINS:
        return

    try:
        with SessionLocal() as session:
            total_users = session.query(func.count(User.id)).scalar()
            total_jobs = session.query(func.count(Job.id)).scalar()
            active_subscriptions = session.query(func.count(User.id)).filter(
                User.can_post_until > datetime.now()
            ).scalar()
            permanent_users = session.query(func.count(User.id)).filter(
                User.can_post == True
            ).scalar()

        await message.answer(
            f"📊 <b>Статистика бота:</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"📄 Всего вакансий: {total_jobs}\n"
            f"💳 Активных подписок: {active_subscriptions}\n"
            f"🔐 Постоянных разрешений: {permanent_users}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка в stats_handler: {e}")
        await message.answer("❌ Ошибка при получении статистики.")


@router.message(Command("user_info"))
async def user_info_handler(message: Message):
    """Информация о пользователе для админов"""
    if message.from_user.id not in ADMINS:
        return

    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.answer("Используй: /user_info @username или /user_info user_id")
            return

        identifier = parts[1]

        with SessionLocal() as session:
            user = None

            if identifier.startswith("@"):
                user = session.query(User).filter_by(username=identifier[1:]).first()
            elif identifier.isdigit():
                user = session.query(User).filter_by(telegram_id=int(identifier)).first()

            if not user:
                await message.answer("❌ Пользователь не найден.")
                return

            job_count = session.query(func.count(Job.id)).filter_by(user_id=user.telegram_id).scalar()

            info_text = (
                f"👤 <b>Информация о пользователе:</b>\n\n"
                f"🆔 ID: {user.telegram_id}\n"
                f"📝 Username: @{user.username or 'не указан'}\n"
                f"📅 Регистрация: {user.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📄 Всего вакансий: {job_count}\n"
                f"👥 Приглашений: {user.invites}\n"
                f"🎫 Разовых публикаций: {user.allowed_posts}\n"
                f"🔐 Постоянное разрешение: {'Да' if user.can_post else 'Нет'}\n"
            )

            if user.can_post_until:
                info_text += f"⏰ Подписка до: {user.can_post_until.strftime('%d.%m.%Y %H:%M')}\n"

            await message.answer(info_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Ошибка в user_info_handler: {e}")
        await message.answer("❌ Ошибка при получении информации о пользователе.")


# Обработчик неизвестных сообщений в приватном чате
@router.message(F.chat.type == ChatType.PRIVATE)
async def unknown_message(message: Message):
    """Обработчик неизвестных сообщений"""
    await message.answer(
        "Не понимаю вас \n",
        "Используйте кнопки меню для навигации:",
        reply_markup=kb_menu
    )


async def on_shutdown(bot: Bot):
    """Корректное завершение работы бота"""
    logger.info("Shutting down...")
    await bot.session.close()

def handle_exit(signum, frame):
    """Обработчик сигналов завершения"""
    logger.info(f"Received exit signal {signum}")
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)