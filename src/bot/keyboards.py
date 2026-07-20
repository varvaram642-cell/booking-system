from typing import Iterable, List, Optional
from datetime import date, time
from decimal import Decimal

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData

from .database import Service, Master


# ===========================
# ===== CALLBACK DATA =====
# ===========================

class ServiceCallback(CallbackData, prefix="service"):
    """Callback для выбора услуги."""
    id: int


class MasterCallback(CallbackData, prefix="master"):
    """Callback для выбора мастера."""
    id: int


class DateCallback(CallbackData, prefix="date"):
    """Callback для выбора даты."""
    date: str  # в формате YYYY-MM-DD


class TimeCallback(CallbackData, prefix="time"):
    """Callback для выбора времени."""
    time: str  # в формате HH:MM


# ===========================
# ===== КЛАВИАТУРЫ =====
# ===========================

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Записаться", callback_data="book")
    builder.button(text="📋 Мои записи", callback_data="my_bookings")
    builder.button(text="💬 Связаться с оператором", callback_data="call_operator")
    
    if is_admin:
        builder.button(text="👨‍💼 Админ-панель", callback_data="admin_panel")
    
    builder.adjust(1)
    return builder.as_markup()


def services_menu(services: Iterable[Service]) -> InlineKeyboardMarkup:
    """
    Меню выбора услуги.
    
    Args:
        services: Список услуг для отображения.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с услугами.
    """
    builder = InlineKeyboardBuilder()
    
    for service in services:
        # Исправлено: преобразование Decimal в int без потери точности
        price_display = int(service.price) if service.price == int(service.price) else float(service.price)
        builder.button(
            text=f"{service.name} — {price_display} руб.",
            callback_data=ServiceCallback(id=service.id).pack()
        )
    
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def masters_menu(masters: Iterable[Master]) -> InlineKeyboardMarkup:
    """
    Меню выбора мастера.
    
    Args:
        masters: Список мастеров для отображения.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с мастерами.
    """
    builder = InlineKeyboardBuilder()
    
    for master in masters:
        spec = f" ({master.specialization})" if master.specialization else ""
        builder.button(
            text=f"👤 {master.name}{spec}",
            callback_data=MasterCallback(id=master.id).pack()
        )
    
    builder.button(text="🔙 Назад", callback_data="back_to_services")
    builder.adjust(1)
    return builder.as_markup()


def dates_menu(dates: Iterable[date]) -> InlineKeyboardMarkup:
    """
    Меню выбора даты.
    
    Args:
        dates: Список доступных дат.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с датами.
    """
    builder = InlineKeyboardBuilder()
    
    for booking_date in dates:  # Исправлено: date_obj -> booking_date
        builder.button(
            text=booking_date.strftime("%d.%m.%Y"),
            callback_data=DateCallback(date=booking_date.strftime("%Y-%m-%d")).pack()
        )
    
    builder.button(text="🔙 Назад", callback_data="back_to_masters")
    builder.adjust(2)
    return builder.as_markup()


def time_slots_menu(slots: Iterable[time]) -> InlineKeyboardMarkup:
    """
    Меню выбора времени.
    
    Args:
        slots: Список доступных временных слотов.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура со временем.
    """
    builder = InlineKeyboardBuilder()
    
    for slot in slots:
        builder.button(
            text=slot.strftime("%H:%M"),
            callback_data=TimeCallback(time=slot.strftime("%H:%M")).pack()
        )
    
    builder.button(text="🔙 Назад", callback_data="back_to_dates")
    builder.adjust(3)
    return builder.as_markup()


def confirmation_menu() -> InlineKeyboardMarkup:
    """
    Меню подтверждения записи.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками подтверждения/отмены.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_booking")
    builder.button(text="❌ Отмена", callback_data="cancel_booking")
    builder.adjust(2)
    return builder.as_markup()


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура админ-панели.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с функциями администратора.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Записи на сегодня", callback_data="admin_today")
    builder.button(text="👤 Управление мастерами", callback_data="admin_masters")
    builder.button(text="📅 Управление расписанием", callback_data="admin_schedule")
    builder.button(text="🚫 Черный список", callback_data="admin_blacklist")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="🔙 Выйти", callback_data="admin_exit")
    builder.adjust(1)
    return builder.as_markup()


def back_to_admin_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопка возврата в админ-панель.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой назад.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад в админку", callback_data="back_to_admin")
    builder.adjust(1)
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопка отмены действия.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой отмены.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="cancel_action")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопка возврата в главное меню.
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопкой назад.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()
