from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    """Состояния для процесса записи."""
    choosing_service = State()
    choosing_master = State()
    choosing_date = State()
    choosing_time = State()
    confirming = State()


class OperatorStates(StatesGroup):
    """Состояния для чата с оператором."""
    active_chat = State()


class AdminStates(StatesGroup):
    """Состояния для админ-команд."""
    waiting_for_schedule = State()
    waiting_for_master_name = State()
    waiting_for_master_specialization = State()
    waiting_for_schedule_date = State()
    waiting_for_schedule_intervals = State()
    waiting_for_blacklist_id = State()
    waiting_for_blacklist_reason = State()
    waiting_for_unblacklist_id = State()
