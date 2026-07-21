import logging
import re
from datetime import datetime, timedelta, date, time
from decimal import Decimal
from typing import List

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from .database import (
    SessionLocal,
    get_or_create_client, is_client_blocked,
    get_all_services, get_service_by_id,
    get_all_masters, get_master_by_id, get_masters_for_service,
    get_master_schedule_intervals, get_available_dates,
    get_bookings_for_master_on_date,
    create_booking, cancel_booking, get_client_bookings,
    save_operator_request, get_active_operator_session,
    get_today_bookings, get_stats,
    add_master, add_to_blacklist, remove_from_blacklist,
    get_client_by_telegram_id,
    update_request_status, close_operator_session,
    get_booking_by_id,
    get_request_by_id,
    ADMIN_CHAT_ID, RequestStatus,
    Client, Booking, Service, Blacklist,
    today_local, now_local, LOCAL_TIMEZONE
)
from .booking_utils import get_free_slots  # <-- ЭТО НОВАЯ СТРОКА
from .states import BookingStates, OperatorStates
from .keyboards import (
    main_menu, services_menu, masters_menu, dates_menu, time_slots_menu,
    confirmation_menu, admin_panel_keyboard, back_to_admin_keyboard,
    ServiceCallback, MasterCallback, DateCallback, TimeCallback
)

logger = logging.getLogger(__name__)
router = Router()
BOOKING_DAYS_AHEAD = 14

def get_session():
    return SessionLocal()


def _get_booking_durations(db, booking_ids: list) -> dict:
    if not booking_ids:
        return {}
    result = (
        db.query(Booking.id, Service.duration)
        .join(Service, Booking.service_id == Service.id)
        .filter(Booking.id.in_(booking_ids))
        .all()
    )
    return {row.id: row.duration for row in result}


def _check_interval_overlap(start1, end1, start2, end2) -> bool:
    return start1 < end2 and start2 < end1


def _get_free_slots(db, master_id: int, service, booking_date: date) -> List[time]:
    schedule = get_master_schedule_intervals(db, master_id, booking_date)
    if not schedule:
        return []
    
    bookings = get_bookings_for_master_on_date(db, master_id, booking_date)
    booking_ids = [b.id for b in bookings]
    durations = _get_booking_durations(db, booking_ids)
    
    free_slots = []
    service_duration = timedelta(minutes=service.duration)
    
    for interval in schedule:
        current = datetime.combine(booking_date, interval.start_time).replace(tzinfo=LOCAL_TIMEZONE)
        end = datetime.combine(booking_date, interval.end_time).replace(tzinfo=LOCAL_TIMEZONE)
        
        while current + service_duration <= end:
            slot_time = current.time()
            slot_start = current
            slot_end = slot_start + service_duration
            
            if booking_date == today_local() and slot_start < now_local():
                current += timedelta(minutes=30)
                continue
            
            is_booked = False
            for booked in bookings:
                booked_duration = durations.get(booked.id)
                if booked_duration is None:
                    continue
                booked_start = datetime.combine(booking_date, booked.booking_time).replace(tzinfo=LOCAL_TIMEZONE)
                booked_end = booked_start + timedelta(minutes=booked_duration)
                
                if _check_interval_overlap(slot_start, slot_end, booked_start, booked_end):
                    is_booked = True
                    break
            
            if not is_booked:
                free_slots.append(slot_time)
            current += timedelta(minutes=30)
    
    return free_slots


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    is_admin = _is_admin(message.from_user.id)

    with get_session() as db:
        if is_client_blocked(db, message.from_user.id):
            await message.answer("🚫 Запись недоступна. Обратитесь к администратору.")
            return
        
        get_or_create_client(
            db,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name or "",
            phone=None
        )
    
    await message.answer(
        f"👋 Привет, {message.from_user.full_name or 'друг'}!\n\n"
        f"Я бот для записи в салон.\n"
        f"Выберите действие:",
        reply_markup=main_menu(is_admin=is_admin)
    )


@router.callback_query(F.data == "book")
async def cmd_book(callback: CallbackQuery, state: FSMContext):
    is_admin = _is_admin(callback.from_user.id)

    with get_session() as db:
        if is_client_blocked(db, callback.from_user.id):
            await callback.answer("🚫 Доступ запрещен", show_alert=True)
            return
        
        services = get_all_services(db)
        if not services:
            await callback.message.edit_text("😔 Услуги временно не доступны.")
            await callback.answer()
            return
        
        await state.set_state(BookingStates.choosing_service)
        await callback.message.edit_text(
            "📋 Шаг 1/4: Выберите услугу:",
            reply_markup=services_menu(services)
        )
        await callback.answer()


@router.callback_query(BookingStates.choosing_service, ServiceCallback.filter())
async def process_service(callback: CallbackQuery, callback_data: ServiceCallback, state: FSMContext):
    service_id = callback_data.id
    await state.update_data(service_id=service_id)
    is_admin = _is_admin(callback.from_user.id)
    
    with get_session() as db:
        service = get_service_by_id(db, service_id)
        if not service:
            await callback.answer("❌ Услуга не найдена", show_alert=True)
            await callback.message.edit_text("❌ Услуга не найдена.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
            
        masters = get_masters_for_service(db, service_id)
        if not masters:
            await callback.message.edit_text("😔 Нет мастеров для этой услуги.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
        
        await state.set_state(BookingStates.choosing_master)
        await callback.message.edit_text(
            "👤 Шаг 2/4: Выберите мастера:",
            reply_markup=masters_menu(masters)
        )
        await callback.answer()


@router.callback_query(BookingStates.choosing_master, MasterCallback.filter())
async def process_master(callback: CallbackQuery, callback_data: MasterCallback, state: FSMContext):
    master_id = callback_data.id
    await state.update_data(master_id=master_id)
    is_admin = _is_admin(callback.from_user.id)
    
    with get_session() as db:
        master = get_master_by_id(db, master_id)
        if not master:
            await callback.answer("❌ Мастер не найден", show_alert=True)
            await callback.message.edit_text("❌ Мастер не найден.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
            
        dates = get_available_dates(db, master_id, days_ahead=BOOKING_DAYS_AHEAD)
        if not dates:
            await callback.message.edit_text("😔 У мастера нет свободных дат.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
        
        await state.set_state(BookingStates.choosing_date)
        await callback.message.edit_text(
            "📅 Шаг 3/4: Выберите дату:",
            reply_markup=dates_menu(dates)
        )
        await callback.answer()


@router.callback_query(BookingStates.choosing_date, DateCallback.filter())
async def process_date(callback: CallbackQuery, callback_data: DateCallback, state: FSMContext):
    date_str = callback_data.date
    booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    await state.update_data(booking_date=booking_date)
    is_admin = _is_admin(callback.from_user.id)
    
    data = await state.get_data()
    master_id = data.get("master_id")
    service_id = data.get("service_id")
    
    with get_session() as db:
        service = get_service_by_id(db, service_id)
        master = get_master_by_id(db, master_id)
        
        if not service or not master:
            await callback.answer("❌ Ошибка данных", show_alert=True)
            await callback.message.edit_text("❌ Ошибка. Начните заново.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
            
        free_slots = _get_free_slots(db, master_id, service, booking_date)
        
        if not free_slots:
            dates = get_available_dates(db, master_id, days_ahead=BOOKING_DAYS_AHEAD)
            await callback.message.edit_text(
                "😔 На эту дату нет свободного времени. Выберите другую:",
                reply_markup=dates_menu(dates)
            )
            await callback.answer("Нет свободного времени!", show_alert=True)
            return
        
        await state.set_state(BookingStates.choosing_time)
        await callback.message.edit_text(
            f"🕐 Шаг 4/4: Выберите время на {booking_date.strftime('%d.%m.%Y')}:",
            reply_markup=time_slots_menu(free_slots)
        )
        await callback.answer()


@router.callback_query(BookingStates.choosing_time, TimeCallback.filter())
async def process_time(callback: CallbackQuery, callback_data: TimeCallback, state: FSMContext):
    time_str = callback_data.time
    booking_time = datetime.strptime(time_str, "%H:%M").time()
    await state.update_data(booking_time=booking_time)
    is_admin = _is_admin(callback.from_user.id)
    
    data = await state.get_data()
    
    with get_session() as db:
        service = get_service_by_id(db, data.get("service_id"))
        master = get_master_by_id(db, data.get("master_id"))
        booking_date = data.get("booking_date")
        
        if not service or not master or not booking_date:
            await callback.answer("❌ Ошибка данных", show_alert=True)
            await callback.message.edit_text("❌ Ошибка. Начните заново.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
        
        await state.set_state(BookingStates.confirming)
        
        price_display = f"{service.price:.2f}" if isinstance(service.price, Decimal) else str(service.price)
        
        await callback.message.edit_text(
            f"✅ Подтвердите запись:\n\n"
            f"📋 Услуга: {service.name}\n"
            f"👤 Мастер: {master.name}\n"
            f"📅 Дата: {booking_date.strftime('%d.%m.%Y')}\n"
            f"🕐 Время: {booking_time.strftime('%H:%M')}\n"
            f"💰 Цена: {price_display} руб.\n\n"
            f"Всё верно?",
            reply_markup=confirmation_menu()
        )
        await callback.answer()


@router.callback_query(BookingStates.confirming, F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    is_admin = _is_admin(callback.from_user.id)

    with get_session() as db:
        client = get_client_by_telegram_id(db, callback.from_user.id)
        if not client:
            await callback.message.edit_text("❌ Клиент не найден. Напишите /start", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return
            
        service = get_service_by_id(db, data.get("service_id"))
        master = get_master_by_id(db, data.get("master_id"))
        booking_date = data.get("booking_date")
        booking_time = data.get("booking_time")
        
        if not service or not master or not booking_date or not booking_time:
            await callback.message.edit_text("❌ Данные потеряны. Начните заново.", reply_markup=main_menu(is_admin=is_admin))
            await state.clear()
            return

        current_free_slots = _get_free_slots(db, master.id, service, booking_date)
        if booking_time not in current_free_slots:
            await callback.message.edit_text(
                "❌ Это время уже занято! Выберите другое время.",
                reply_markup=main_menu(is_admin=is_admin)
            )
            await callback.answer("Время уже занято!", show_alert=True)
            await state.clear()
            return
            
        try:
            create_booking(
                db,
                client_id=client.id,
                service_id=service.id,
                master_id=master.id,
                booking_date=booking_date,
                booking_time=booking_time,
                source="telegram"
            )
            
            price_display = f"{service.price:.2f}" if isinstance(service.price, Decimal) else str(service.price)
            await state.clear()
            
            await callback.message.edit_text(
                f"🎉 Вы успешно записаны!\n\n"
                f"📋 Услуга: {service.name}\n"
                f"👤 Мастер: {master.name}\n"
                f"📅 Дата: {booking_date.strftime('%d.%m.%Y')}\n"
                f"🕐 Время: {booking_time.strftime('%H:%M')}\n"
                f"💰 Цена: {price_display} руб.\n\n"
                f"Мы ждем вас!",
                reply_markup=main_menu(is_admin=is_admin)
            )
            await callback.answer("Запись подтверждена!", show_alert=True)
            
        except (ValueError, IntegrityError) as e:
            await state.clear()
            await callback.message.edit_text(f"❌ Ошибка записи: {str(e)}", reply_markup=main_menu(is_admin=is_admin))
            await callback.answer("Ошибка!", show_alert=True)
        except SQLAlchemyError as e:
            logger.error(f"Ошибка БД: {e}")
            await state.clear()
            await callback.message.edit_text("❌ Внутренняя ошибка. Попробуйте позже.", reply_markup=main_menu(is_admin=is_admin))
            await callback.answer("Ошибка!", show_alert=True)


@router.callback_query(F.data == "cancel_booking")
async def cancel_booking_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = _is_admin(callback.from_user.id)
    await callback.message.edit_text(
        "❌ Вы отменили запись.",
        reply_markup=main_menu(is_admin=is_admin)
    )
    await callback.answer()


@router.callback_query(F.data == "my_bookings")
async def my_bookings(callback: CallbackQuery):
    is_admin = _is_admin(callback.from_user.id)
    
    with get_session() as db:
        bookings = get_client_bookings(db, callback.from_user.id)
        
        if not bookings:
            await callback.message.edit_text(
                "📭 У вас нет активных записей.",
                reply_markup=main_menu(is_admin=is_admin)
            )
            await callback.answer()
            return
        
        text = "📋 Ваши записи:\n\n"
        for b in bookings:
            service_name = b.service_obj.name if b.service_obj else "Услуга удалена"
            master_name = b.master_obj.name if b.master_obj else "Мастер удален"
            text += f"📌 {b.booking_date.strftime('%d.%m.%Y')} {b.booking_time.strftime('%H:%M')}\n"
            text += f"   {service_name} → {master_name}\n"
            text += f"   /cancel_{b.id}\n\n"
        
        await callback.message.edit_text(text, reply_markup=main_menu(is_admin=is_admin))
        await callback.answer()


@router.message(F.text.regexp(r"^/cancel_\d+$"))
async def cancel_booking_command(message: Message):
    booking_id = int(message.text.split("_")[1])
    is_admin = _is_admin(message.from_user.id)

    with get_session() as db:
        booking = get_booking_by_id(db, booking_id)
        if not booking:
            await message.answer("❌ Запись не найдена.")
            return
        
        client = get_client_by_telegram_id(db, message.from_user.id)
        if not client or booking.client_id != client.id:
            await message.answer("❌ Вы не можете отменить эту запись.")
            return
        
        cancel_booking(db, booking_id)
        await message.answer(f"✅ Запись #{booking_id} отменена.", reply_markup=main_menu(is_admin=is_admin))


@router.callback_query(F.data == "call_operator")
async def call_operator(callback: CallbackQuery):
    is_admin = _is_admin(callback.from_user.id)

    with get_session() as db:
        client = get_client_by_telegram_id(db, callback.from_user.id)
        if not client:
            await callback.message.edit_text("❌ Клиент не найден. Напишите /start", reply_markup=main_menu(is_admin=is_admin))
            return
        
        request = save_operator_request(db, client.id, callback.from_user.username)
        
        await callback.bot.send_message(
            ADMIN_CHAT_ID,
            f"🔔 НОВЫЙ ЗАПРОС НА СВЯЗЬ!\n\n"
            f"👤 Клиент: {callback.from_user.full_name}\n"
            f"🆔 @{callback.from_user.username}\n"
            f"📝 Запрос #{request.id}\n\n"
            f"Чтобы принять: /take_{request.id}"
        )
        
        await callback.message.edit_text(
            "🟢 Оператор получил ваш запрос. Он свяжется с вами."
        )
        await callback.answer()


@router.message(F.text.regexp(r"^/take_\d+$"))
async def take_request(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав.")
        return
    
    request_id = int(message.text.split("_")[1])
    
    with get_session() as db:
        request = get_request_by_id(db, request_id)
        if not request:
            await message.answer("❌ Запрос не найден.")
            return
        
        if request.status == RequestStatus.ACTIVE:
            await message.answer(f"⚠️ Запрос #{request.id} уже активен.")
            return

        update_request_status(db, request_id, RequestStatus.ACTIVE)
        await state.set_state(OperatorStates.active_chat)
        await state.update_data(client_id=request.client_id, request_id=request.id)
        
        await message.answer(
            f"✅ Вы приняли диалог #{request.id}.\n"
            f"Для завершения: /end_chat"
        )
        
        client = db.get(Client, request.client_id)
        if client:
            await message.bot.send_message(
                client.telegram_id,
                "👋 Оператор принял ваш запрос. Задайте вопрос."
            )


@router.message(StateFilter(OperatorStates.active_chat), F.chat.id == ADMIN_CHAT_ID)
async def forward_from_operator(message: Message, state: FSMContext):
    if not message.text:
        return
        
    data = await state.get_data()
    client_id = data.get("client_id")
    if not client_id:
        await message.answer("❌ Ошибка: клиент не найден.")
        await state.clear()
        return
    
    with get_session() as db:
        client = db.get(Client, client_id)
        if client:
            await message.bot.send_message(client.telegram_id, f"👨‍💼 Оператор: {message.text}")
            await message.answer("✅ Отправлено.")
        else:
            await message.answer("❌ Клиент не найден.")
            await state.clear()


@router.message(F.chat.type == "private")
async def forward_from_client(message: Message):
    if not message.text or message.text.startswith("/"):
        return
    
    with get_session() as db:
        client = get_client_by_telegram_id(db, message.from_user.id)
        if not client:
            return
            
        active_session = get_active_operator_session(db, client.id)
        if active_session:
            await message.bot.send_message(
                ADMIN_CHAT_ID,
                f"💬 Клиент (@{message.from_user.username}): {message.text}"
            )
        else:
            await message.answer(
                "Я бот и отвечаю только на команды.\n"
                "Если вопрос к оператору, нажмите «Связаться с оператором»."
            )


@router.message(Command("end_chat"))
async def end_chat(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав.")
        return
    
    data = await state.get_data()
    client_id = data.get("client_id")
    request_id = data.get("request_id")
    
    if request_id:
        with get_session() as db:
            close_operator_session(db, request_id)
    
    await state.clear()
    await message.answer("🔚 Диалог завершен.")
    
    if client_id:
        with get_session() as db:
            client = db.get(Client, client_id)
            if client:
                await message.bot.send_message(
                    client.telegram_id,
                    "🔚 Оператор завершил диалог."
                )


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👨‍💼 Админ-панель\n\nВыберите действие:",
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_today")
async def admin_today(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    
    with get_session() as db:
        bookings = get_today_bookings(db)
        
        if not bookings:
            await callback.message.edit_text(
                "📭 На сегодня нет записей.",
                reply_markup=back_to_admin_keyboard()
            )
            return
        
        text = f"📋 Записи на {today_local().strftime('%d.%m.%Y')}:\n\n"
        for b in bookings:
            service_name = b.service_obj.name if b.service_obj else "Услуга удалена"
            master_name = b.master_obj.name if b.master_obj else "Мастер удален"
            
            client_info = "Неизвестный клиент"
            if b.client_obj:
                client_info = b.client_obj.full_name or b.client_obj.username or f"Клиент ID: {b.client_obj.id}"
            elif b.client_name:
                client_info = b.client_name
            
            text += f"• {b.booking_time.strftime('%H:%M')} — {service_name} → {master_name}\n"
            text += f"  Клиент: {client_info}\n\n"
        
        await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
        await callback.answer()


@router.callback_query(F.data == "admin_masters")
async def admin_masters(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    
    with get_session() as db:
        masters = get_all_masters(db, only_active=False)
        if not masters:
            await callback.message.edit_text(
                "👤 Список мастеров пуст.\n/add_master Имя | Специализация",
                reply_markup=back_to_admin_keyboard()
            )
            return
        
        text = "👤 Список мастеров:\n\n"
        for m in masters:
            status = "✅" if m.is_active else "❌"
            text += f"{status} {m.id}. {m.name} ({m.specialization or 'без специализации'})\n"
        text += "\n/add_master Имя | Специализация"
        
        await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
        await callback.answer()


@router.message(Command("add_master"))
async def add_master_command(message: Message):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав.")
        return
    
    try:
        parts = message.text.split(" ", 1)[1].split(" | ", 1)
        name = parts[0].strip()
        specialization = parts[1].strip() if len(parts) > 1 else ""
    except (IndexError, ValueError):
        await message.answer("❌ /add_master Имя | Специализация")
        return
    
    with get_session() as db:
        master = add_master(db, name, specialization)
        await message.answer(f"✅ Мастер {master.name} добавлен!")


@router.callback_query(F.data == "admin_blacklist")
async def admin_blacklist(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    
    with get_session() as db:
        blocked_entries = db.query(Blacklist).options(selectinload(Blacklist.client_obj)).all()
        
        if not blocked_entries:
            await callback.message.edit_text(
                "🚫 Черный список пуст.\n/blacklist <telegram_id> <причина>",
                reply_markup=back_to_admin_keyboard()
            )
            return
        
        text = "🚫 Черный список:\n\n"
        for b_entry in blocked_entries:
            client_info = "Неизвестный клиент"
            if b_entry.client_obj:
                client_info = b_entry.client_obj.full_name or b_entry.client_obj.username or f"Клиент ID: {b_entry.client_obj.id}"
            text += f"• {client_info}\n"
            text += f"  Причина: {b_entry.reason or 'Не указана'}\n\n"
        text += "\n/unblacklist <telegram_id>"
        
        await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
        await callback.answer()


@router.message(Command("blacklist"))
async def add_blacklist_command(message: Message):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав.")
        return
    
    try:
        parts = message.text.split(" ", 2)
        telegram_id = int(parts[1])
        reason = parts[2] if len(parts) > 2 else "Без причины"
    except (IndexError, ValueError):
        await message.answer("❌ /blacklist <telegram_id> <причина>")
        return
    
    with get_session() as db:
        try:
            add_to_blacklist(db, telegram_id, reason, ADMIN_CHAT_ID)
            await message.answer(f"✅ Клиент {telegram_id} заблокирован.\nПричина: {reason}")
        except ValueError as e:
            await message.answer(f"❌ {str(e)}")


@router.message(Command("unblacklist"))
async def remove_blacklist_command(message: Message):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав.")
        return
    
    try:
        telegram_id = int(message.text.split(" ")[1])
    except (IndexError, ValueError):
        await message.answer("❌ /unblacklist <telegram_id>")
        return
    
    with get_session() as db:
        client = get_client_by_telegram_id(db, telegram_id)
        if not client:
            await message.answer(f"❌ Клиент {telegram_id} не найден.")
            return
        
        if not db.query(Blacklist).filter(Blacklist.client_id == client.id).first():
            await message.answer(f"✅ Клиент {telegram_id} уже не в черном списке.")
            return

        remove_from_blacklist(db, telegram_id)
        await message.answer(f"✅ Клиент {telegram_id} разблокирован.")


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    
    with get_session() as db:
        stats = get_stats(db)
        
        await callback.message.edit_text(
            f"📊 Статистика:\n\n"
            f"👤 Мастеров: {stats['total_masters']}\n"
            f"📋 Услуг: {stats['total_services']}\n"
            f"📅 Записей всего: {stats['total_bookings']}\n"
            f"📆 Записей сегодня: {stats['today_bookings']}",
            reply_markup=back_to_admin_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "admin_exit")
async def admin_exit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = _is_admin(callback.from_user.id)
    await callback.message.edit_text(
        "👋 Вы вышли из админ-панели.",
        reply_markup=main_menu(is_admin=is_admin)
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    await admin_panel(callback)
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = _is_admin(callback.from_user.id)
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu(is_admin=is_admin)
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_services")
async def back_to_services(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingStates.choosing_service)
    is_admin = _is_admin(callback.from_user.id)

    with get_session() as db:
        services = get_all_services(db)
        await callback.message.edit_text(
            "📋 Выберите услугу:",
            reply_markup=services_menu(services)
        )
        await callback.answer()


@router.callback_query(F.data == "back_to_masters")
async def back_to_masters(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service_id = data.get("service_id")
    
    if not service_id:
        await state.clear()
        await callback.message.edit_text("❌ Ошибка. Начните заново.")
        await callback.answer(show_alert=True)
        return

    with get_session() as db:
        masters = get_masters_for_service(db, service_id)
        await state.set_state(BookingStates.choosing_master)
        await callback.message.edit_text(
            "👤 Выберите мастера:",
            reply_markup=masters_menu(masters)
        )
        await callback.answer()


@router.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    master_id = data.get("master_id")
    
    if not master_id:
        await state.clear()
        await callback.message.edit_text("❌ Ошибка. Начните заново.")
        await callback.answer(show_alert=True)
        return

    with get_session() as db:
        dates = get_available_dates(db, master_id, days_ahead=BOOKING_DAYS_AHEAD)
        await state.set_state(BookingStates.choosing_date)
        await callback.message.edit_text(
            "📅 Выберите дату:",
            reply_markup=dates_menu(dates)
        )
        await callback.answer()


@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = _is_admin(callback.from_user.id)
    await callback.message.edit_text(
        "Действие отменено.",
        reply_markup=main_menu(is_admin=is_admin)
    )
    await callback.answer()
