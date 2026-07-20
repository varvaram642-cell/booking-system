import os
import sys
import logging
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Dict, Any, Optional, List, Iterator
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, Integer, String, Numeric, DateTime, 
    BigInteger, Text, Boolean, Date, Time, ForeignKey, 
    UniqueConstraint, Index, func, and_, or_, Enum
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("DatabaseConfig")

# ===== ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ =====
load_dotenv()

# ===== TELEGRAM =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен!")
    sys.exit(1)

ADMIN_CHAT_ID_STR = os.getenv("ADMIN_CHAT_ID")
if not ADMIN_CHAT_ID_STR:
    logger.warning("ADMIN_CHAT_ID не установлен.")
    ADMIN_CHAT_ID = 0
else:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_STR)
    except ValueError:
        logger.error("ADMIN_CHAT_ID должен быть числом!")
        sys.exit(1)

# ===== POSTGRESQL =====
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

if not all([POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]):
    logger.error("Переменные PostgreSQL не установлены!")
    sys.exit(1)

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# ===== FASTAPI (опционально) =====
SECRET_KEY = os.getenv("SECRET_KEY")

# ===== DASHBOARD (опционально) =====
ADMIN_PASSWORD_DASHBOARD = os.getenv("ADMIN_PASSWORD_DASHBOARD")

# ===== ЧАСОВОЙ ПОЯС =====
LOCAL_TIMEZONE = ZoneInfo("Europe/Moscow")

def now_local() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)

def today_local() -> date:
    return now_local().date()


# ===== ENUM ДЛЯ СТАТУСОВ =====
class BookingStatus(PyEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    ARCHIVED = "archived"

class RequestStatus(PyEnum):
    WAITING = "waiting"
    ACTIVE = "active"
    CLOSED = "closed"


# ===== SQLALCHEMY SETUP =====
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True
)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)
Base = declarative_base()


# ===========================
# ===== ТАБЛИЦЫ БАЗЫ ДАННЫХ =====
# ===========================

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    bookings = relationship("Booking", back_populates="client_obj", lazy="selectin")
    operator_requests = relationship("OperatorRequest", back_populates="client_obj", lazy="selectin")
    blacklist_entry = relationship("Blacklist", back_populates="client_obj", uselist=False, lazy="selectin")


class Master(Base):
    __tablename__ = "masters"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    specialization = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    master_services = relationship("ServiceMaster", back_populates="master", cascade="all, delete-orphan", lazy="selectin")
    schedule = relationship("MasterSchedule", back_populates="master", cascade="all, delete-orphan", lazy="selectin")
    bookings = relationship("Booking", back_populates="master_obj", lazy="selectin")


class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    duration = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    service_masters = relationship("ServiceMaster", back_populates="service", cascade="all, delete-orphan", lazy="selectin")
    bookings = relationship("Booking", back_populates="service_obj", lazy="selectin")


class ServiceMaster(Base):
    __tablename__ = "service_master"
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    master_id = Column(Integer, ForeignKey("masters.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("service_id", "master_id", name="uq_service_master"),
    )

    service = relationship("Service", back_populates="service_masters")
    master = relationship("Master", back_populates="master_services")


class MasterSchedule(Base):
    __tablename__ = "master_schedule"
    id = Column(Integer, primary_key=True, index=True)
    master_id = Column(Integer, ForeignKey("masters.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    __table_args__ = (
        UniqueConstraint("master_id", "date", "start_time", "end_time", name="uq_master_schedule"),
        Index("idx_schedule_master_date", "master_id", "date"),
    )

    master = relationship("Master", back_populates="schedule")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    client_name = Column(String(255), nullable=True)
    client_phone = Column(String(20), nullable=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    master_id = Column(Integer, ForeignKey("masters.id", ondelete="SET NULL"), nullable=True, index=True)
    booking_date = Column(Date, nullable=False, index=True)
    booking_time = Column(Time, nullable=False)
    status = Column(
        Enum(BookingStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=BookingStatus.CONFIRMED
    )
    source = Column(String(50), default="telegram", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_bookings_master_date", "master_id", "booking_date"),
        Index("idx_bookings_client_status", "client_id", "status"),
        Index("idx_bookings_status_archived", "status", "archived_at"),
        UniqueConstraint("master_id", "booking_date", "booking_time", name="uq_booking_slot"),
    )

    client_obj = relationship("Client", back_populates="bookings")
    service_obj = relationship("Service", back_populates="bookings")
    master_obj = relationship("Master", back_populates="bookings")


class OperatorRequest(Base):
    __tablename__ = "operator_requests"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(255), nullable=True)
    status = Column(
        Enum(RequestStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=RequestStatus.WAITING
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    client_obj = relationship("Client", back_populates="operator_requests")


class Blacklist(Base):
    __tablename__ = "blacklist"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    reason = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    client_obj = relationship("Client", back_populates="blacklist_entry")


# ===========================
# ===== CRUD ФУНКЦИИ =====
# ===========================

def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def _fits_into_schedule(intervals: List[MasterSchedule], start_time: time, end_time: time) -> bool:
    for interval in intervals:
        if interval.start_time <= start_time and end_time <= interval.end_time:
            return True
    return False


def _validate_interval(start_time: time, end_time: time) -> None:
    if start_time >= end_time:
        raise ValueError("Время начала должно быть меньше времени окончания")


def _get_service_durations(db: Session, booking_ids: List[int]) -> Dict[int, int]:
    """Получает длительности услуг для списка бронирований одним запросом."""
    if not booking_ids:
        return {}
    
    # Исправлено: оптимизированный запрос без лишнего списка
    result = (
        db.query(Booking.id, Service.duration)
        .join(Service, Booking.service_id == Service.id)
        .filter(Booking.id.in_(booking_ids))
        .all()
    )
    return {row.id: row.duration for row in result}


def _create_booking_atomic(
    db: Session,
    client_id: int,
    service_id: int,
    master_id: int,
    booking_date: date,
    booking_time: time,
    duration: int,
    client_name: Optional[str] = None,
    client_phone: Optional[str] = None,
    source: str = "telegram"
) -> Booking:
    """Атомарное создание бронирования с блокировкой FOR UPDATE."""
    intervals = db.query(MasterSchedule).filter(
        MasterSchedule.master_id == master_id,
        MasterSchedule.date == booking_date
    ).with_for_update().all()
    
    if not intervals:
        raise ValueError("У мастера нет рабочего времени на эту дату")
    
    end_time = (datetime.combine(booking_date, booking_time) + timedelta(minutes=duration)).time()
    
    if not _fits_into_schedule(intervals, booking_time, end_time):
        raise ValueError("Время не входит в рабочие часы мастера")
    
    existing_bookings = db.query(Booking).filter(
        Booking.master_id == master_id,
        Booking.booking_date == booking_date,
        Booking.status == BookingStatus.CONFIRMED
    ).with_for_update().all()
    
    if existing_bookings:
        booking_ids = [b.id for b in existing_bookings]
        durations = _get_service_durations(db, booking_ids)
        
        new_start = datetime.combine(booking_date, booking_time)
        new_end = datetime.combine(booking_date, end_time)
        
        for existing in existing_bookings:
            existing_duration = durations.get(existing.id)
            if existing_duration is None:
                continue
            existing_start = datetime.combine(booking_date, existing.booking_time)
            existing_end = existing_start + timedelta(minutes=existing_duration)
            
            if new_start < existing_end and existing_start < new_end:
                raise ValueError("Время пересекается с существующей записью")
    
    booking = Booking(
        client_id=client_id,
        client_name=client_name,
        client_phone=client_phone,
        service_id=service_id,
        master_id=master_id,
        booking_date=booking_date,
        booking_time=booking_time,
        source=source
    )
    db.add(booking)
    db.flush()
    db.refresh(booking)
    return booking


# ===== КЛИЕНТЫ =====

def get_or_create_client(
    db: Session,
    telegram_id: int,
    username: Optional[str],
    full_name: Optional[str],
    phone: Optional[str] = None
) -> Client:
    client = db.query(Client).filter(Client.telegram_id == telegram_id).first()
    if client:
        client.username = username
        client.full_name = full_name
        if phone:
            client.phone = phone
        try:
            db.commit()
            db.refresh(client)
        except SQLAlchemyError:
            db.rollback()
            raise
        return client

    client = Client(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        phone=phone
    )
    db.add(client)
    try:
        db.commit()
        db.refresh(client)
        return client
    except IntegrityError:
        db.rollback()
        client = db.query(Client).filter(Client.telegram_id == telegram_id).first()
        if not client:
            raise RuntimeError(f"Не удалось создать клиента {telegram_id}")
        return client
    except SQLAlchemyError:
        db.rollback()
        raise


def get_client_by_telegram_id(db: Session, telegram_id: int) -> Optional[Client]:
    return db.query(Client).filter(Client.telegram_id == telegram_id).first()


# ===== ЧЕРНЫЙ СПИСОК =====

def is_client_blocked(db: Session, telegram_id: int) -> bool:
    client = get_client_by_telegram_id(db, telegram_id)
    if not client:
        return False
    return db.query(Blacklist).filter(Blacklist.client_id == client.id).first() is not None


def add_to_blacklist(db: Session, telegram_id: int, reason: str, admin_id: int):
    client = get_client_by_telegram_id(db, telegram_id)
    if not client:
        raise ValueError(f"Клиент {telegram_id} не найден")
    if db.query(Blacklist).filter(Blacklist.client_id == client.id).first():
        raise ValueError(f"Клиент {telegram_id} уже в ЧС")

    entry = Blacklist(client_id=client.id, reason=reason, created_by=admin_id)
    db.add(entry)
    try:
        db.commit()
        db.refresh(entry)
    except IntegrityError:
        db.rollback()
        raise ValueError(f"Клиент {telegram_id} уже в ЧС")
    except SQLAlchemyError:
        db.rollback()
        raise


def remove_from_blacklist(db: Session, telegram_id: int):
    client = get_client_by_telegram_id(db, telegram_id)
    if not client:
        return
    entry = db.query(Blacklist).filter(Blacklist.client_id == client.id).first()
    if entry:
        db.delete(entry)
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise


# ===== МАСТЕРА =====

def get_all_masters(db: Session, only_active: bool = True) -> List[Master]:
    query = db.query(Master)
    if only_active:
        query = query.filter(Master.is_active.is_(True))
    return query.all()


def get_master_by_id(db: Session, master_id: int) -> Optional[Master]:
    return db.query(Master).filter(Master.id == master_id).first()


def get_masters_for_service(db: Session, service_id: int) -> List[Master]:
    return (
        db.query(Master)
        .join(ServiceMaster)
        .filter(
            ServiceMaster.service_id == service_id,
            Master.is_active.is_(True)
        )
        .all()
    )


def add_master(db: Session, name: str, specialization: str = "", phone: Optional[str] = None) -> Master:
    master = Master(name=name, specialization=specialization, phone=phone)
    db.add(master)
    try:
        db.commit()
        db.refresh(master)
    except SQLAlchemyError:
        db.rollback()
        raise
    return master


# ===== УСЛУГИ =====

def get_all_services(db: Session) -> List[Service]:
    return db.query(Service).all()


def get_service_by_id(db: Session, service_id: int) -> Optional[Service]:
    return db.query(Service).filter(Service.id == service_id).first()


def get_service_by_name(db: Session, name: str) -> Optional[Service]:
    return db.query(Service).filter(Service.name == name).first()


def add_service(db: Session, name: str, duration: int, price: Decimal) -> Service:
    service = Service(name=name, duration=duration, price=price)
    db.add(service)
    try:
        db.commit()
        db.refresh(service)
    except SQLAlchemyError:
        db.rollback()
        raise
    return service


def link_service_to_master(db: Session, service_id: int, master_id: int) -> ServiceMaster:
    existing = (
        db.query(ServiceMaster)
        .filter_by(service_id=service_id, master_id=master_id)
        .first()
    )
    if existing:
        return existing

    link = ServiceMaster(service_id=service_id, master_id=master_id)
    db.add(link)
    try:
        db.commit()
        db.refresh(link)
    except IntegrityError:
        db.rollback()
        return db.query(ServiceMaster).filter_by(service_id=service_id, master_id=master_id).first()
    except SQLAlchemyError:
        db.rollback()
        raise
    return link


# ===== РАСПИСАНИЕ =====

def get_master_schedule_intervals(db: Session, master_id: int, booking_date: date) -> List[MasterSchedule]:
    return (
        db.query(MasterSchedule)
        .filter(
            MasterSchedule.master_id == master_id,
            MasterSchedule.date == booking_date
        )
        .order_by(MasterSchedule.start_time)
        .all()
    )


def add_master_schedule_interval(
    db: Session,
    master_id: int,
    booking_date: date,
    start_time: time,
    end_time: time
) -> MasterSchedule:
    _validate_interval(start_time, end_time)

    existing_intervals = db.query(MasterSchedule).filter(
        MasterSchedule.master_id == master_id,
        MasterSchedule.date == booking_date
    ).with_for_update().all()
    
    for interval in existing_intervals:
        if start_time < interval.end_time and interval.start_time < end_time:
            raise ValueError(f"Интервал пересекается с существующим")

    schedule = MasterSchedule(
        master_id=master_id,
        date=booking_date,
        start_time=start_time,
        end_time=end_time
    )
    db.add(schedule)
    try:
        db.commit()
        db.refresh(schedule)
    except IntegrityError:
        db.rollback()
        return db.query(MasterSchedule).filter(
            MasterSchedule.master_id == master_id,
            MasterSchedule.date == booking_date,
            MasterSchedule.start_time == start_time,
            MasterSchedule.end_time == end_time
        ).first()
    except SQLAlchemyError:
        db.rollback()
        raise
    return schedule


def clear_master_schedule_for_day(db: Session, master_id: int, booking_date: date):
    db.query(MasterSchedule).filter(
        MasterSchedule.master_id == master_id,
        MasterSchedule.date == booking_date
    ).delete()
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def get_available_dates(db: Session, master_id: int, days_ahead: int = 14) -> List[date]:
    today = today_local()
    end_date = today + timedelta(days=days_ahead)
    dates = (
        db.query(MasterSchedule.date)
        .filter(
            MasterSchedule.master_id == master_id,
            MasterSchedule.date >= today,
            MasterSchedule.date <= end_date
        )
        .distinct()
        .order_by(MasterSchedule.date)
        .all()
    )
    return [d[0] for d in dates]


# ===== БРОНИРОВАНИЯ =====

def get_bookings_for_master_on_date(db: Session, master_id: int, booking_date: date) -> List[Booking]:
    return (
        db.query(Booking)
        .filter(
            Booking.master_id == master_id,
            Booking.booking_date == booking_date,
            Booking.status == BookingStatus.CONFIRMED
        )
        .all()
    )


def get_booking_by_id(db: Session, booking_id: int) -> Optional[Booking]:
    return db.query(Booking).filter(Booking.id == booking_id).first()


def create_booking(
    db: Session,
    client_id: int,
    service_id: int,
    master_id: int,
    booking_date: date,
    booking_time: time,
    client_name: Optional[str] = None,
    client_phone: Optional[str] = None,
    source: str = "telegram"
) -> Booking:
    service = get_service_by_id(db, service_id)
    if not service:
        raise ValueError(f"Услуга {service_id} не найдена")

    master = get_master_by_id(db, master_id)
    if not master:
        raise ValueError(f"Мастер {master_id} не найден")

    service_master = db.query(ServiceMaster).filter_by(
        service_id=service_id,
        master_id=master_id
    ).first()
    if not service_master:
        raise ValueError(f"Мастер {master.name} не оказывает услугу {service.name}")

    # ИСПРАВЛЕНО: приводим booking_datetime к тому же часовому поясу, что и now
    now = now_local()
    booking_datetime = datetime.combine(booking_date, booking_time, tzinfo=LOCAL_TIMEZONE)
    
    if booking_datetime <= now:
        raise ValueError("Нельзя записаться в прошлое или текущее время")

    try:
        booking = _create_booking_atomic(
            db, client_id, service_id, master_id,
            booking_date, booking_time, service.duration,
            client_name, client_phone, source
        )
        db.commit()
        db.refresh(booking)
        return booking
    except IntegrityError:
        db.rollback()
        raise ValueError("Это время уже занято")
    except SQLAlchemyError:
        db.rollback()
        raise


def cancel_booking(db: Session, booking_id: int) -> Optional[Booking]:
    booking = get_booking_by_id(db, booking_id)
    if booking:
        booking.status = BookingStatus.CANCELLED
        try:
            db.commit()
            db.refresh(booking)
        except SQLAlchemyError:
            db.rollback()
            raise
    return booking


def get_client_bookings(db: Session, telegram_id: int) -> List[Booking]:
    client = get_client_by_telegram_id(db, telegram_id)
    if not client:
        return []

    now = now_local()
    today = now.date()
    current_time = now.time()

    return (
        db.query(Booking)
        .filter(
            Booking.client_id == client.id,
            Booking.status == BookingStatus.CONFIRMED,
            or_(
                Booking.booking_date > today,
                and_(
                    Booking.booking_date == today,
                    Booking.booking_time >= current_time
                )
            )
        )
        .order_by(Booking.booking_date, Booking.booking_time)
        .all()
    )


# ===== ОПЕРАТОР =====

def save_operator_request(db: Session, client_id: int, username: Optional[str]) -> OperatorRequest:
    request = OperatorRequest(client_id=client_id, username=username)
    db.add(request)
    try:
        db.commit()
        db.refresh(request)
    except SQLAlchemyError:
        db.rollback()
        raise
    return request


def get_request_by_id(db: Session, request_id: int) -> Optional[OperatorRequest]:
    return db.query(OperatorRequest).filter(OperatorRequest.id == request_id).first()


def update_request_status(db: Session, request_id: int, status: RequestStatus) -> Optional[OperatorRequest]:
    request = get_request_by_id(db, request_id)
    if request:
        request.status = status
        if status == RequestStatus.CLOSED:
            request.closed_at = now_local()
        try:
            db.commit()
            db.refresh(request)
        except SQLAlchemyError:
            db.rollback()
            raise
    return request


def get_active_operator_session(db: Session, client_id: int) -> Optional[OperatorRequest]:
    return (
        db.query(OperatorRequest)
        .filter(
            OperatorRequest.client_id == client_id,
            OperatorRequest.status == RequestStatus.ACTIVE
        )
        .first()
    )


def close_operator_session(db: Session, request_id: int) -> Optional[OperatorRequest]:
    return update_request_status(db, request_id, RequestStatus.CLOSED)


# ===== ЗАПИСИ НА СЕГОДНЯ =====

def get_today_bookings(db: Session) -> List[Booking]:
    today = today_local()
    return (
        db.query(Booking)
        .filter(
            Booking.booking_date == today,
            Booking.status == BookingStatus.CONFIRMED
        )
        .order_by(Booking.booking_time)
        .all()
    )


# ===== СТАТИСТИКА =====

def get_stats(db: Session) -> Dict[str, Any]:
    total_bookings = db.query(Booking).filter(
        Booking.status == BookingStatus.CONFIRMED
    ).count()
    
    today = today_local()
    today_bookings = (
        db.query(Booking)
        .filter(
            Booking.booking_date == today,
            Booking.status == BookingStatus.CONFIRMED
        )
        .count()
    )
    
    total_masters = db.query(Master).count()
    total_services = db.query(Service).count()
    
    return {
        "total_bookings": total_bookings,
        "today_bookings": today_bookings,
        "total_masters": total_masters,
        "total_services": total_services
    }


# ===== АРХИВИРОВАНИЕ =====

def archive_old_bookings(db: Session, days: int = 90) -> int:
    """
    Архивирует старые записи, устанавливая статус ARCHIVED и заполняя archived_at.
    """
    cutoff_date = today_local() - timedelta(days=days)
    
    bookings = db.query(Booking).filter(
        Booking.booking_date < cutoff_date,
        Booking.status.in_([
            BookingStatus.COMPLETED,
            BookingStatus.CANCELLED,
            BookingStatus.NO_SHOW
        ])
    ).all()
    
    count = 0
    for booking in bookings:
        booking.status = BookingStatus.ARCHIVED
        booking.archived_at = now_local()
        count += 1
    
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    
    return count


def get_archived_bookings(
    db: Session,
    limit: int = 100,
    offset: int = 0
) -> List[Booking]:
    """Получение архивированных записей с пагинацией."""
    return (
        db.query(Booking)
        .filter(Booking.status == BookingStatus.ARCHIVED)
        .order_by(Booking.archived_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


# ===========================
# ===== ИНИЦИАЛИЗАЦИЯ БД =====
# ===========================

def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Таблицы созданы/проверены.")

        with SessionLocal() as db:
            if db.query(Service).count() == 0:
                services = [
                    Service(name="Стрижка", duration=60, price=Decimal("1500.00")),
                    Service(name="Маникюр", duration=90, price=Decimal("2000.00")),
                    Service(name="Массаж (60 мин)", duration=60, price=Decimal("3000.00")),
                    Service(name="Массаж (90 мин)", duration=90, price=Decimal("4000.00")),
                    Service(name="Консультация", duration=30, price=Decimal("1000.00")),
                ]
                db.add_all(services)
                db.commit()
                logger.info("✅ Услуги добавлены")

            if db.query(Master).count() == 0:
                masters = [
                    Master(name="Анна", specialization="Стрижки, окрашивание", phone="+79001234567"),
                    Master(name="Екатерина", specialization="Маникюр, педикюр", phone="+79001234568"),
                    Master(name="Дмитрий", specialization="Массаж", phone="+79001234569"),
                ]
                db.add_all(masters)
                db.commit()
                logger.info("✅ Мастера добавлены")

            if db.query(ServiceMaster).count() == 0:
                anna = db.query(Master).filter_by(name="Анна").first()
                katya = db.query(Master).filter_by(name="Екатерина").first()
                dima = db.query(Master).filter_by(name="Дмитрий").first()

                strizhka = db.query(Service).filter_by(name="Стрижка").first()
                manikyur = db.query(Service).filter_by(name="Маникюр").first()
                massage_60 = db.query(Service).filter_by(name="Массаж (60 мин)").first()
                massage_90 = db.query(Service).filter_by(name="Массаж (90 мин)").first()

                if anna and strizhka:
                    link_service_to_master(db, strizhka.id, anna.id)
                if katya and manikyur:
                    link_service_to_master(db, manikyur.id, katya.id)
                if dima and massage_60:
                    link_service_to_master(db, massage_60.id, dima.id)
                if dima and massage_90:
                    link_service_to_master(db, massage_90.id, dima.id)
                logger.info("✅ Связи услуг и мастеров добавлены")

            if db.query(MasterSchedule).count() == 0:
                anna = db.query(Master).filter_by(name="Анна").first()
                if anna:
                    today = today_local()
                    add_master_schedule_interval(db, anna.id, today, time(10, 0), time(14, 0))
                    add_master_schedule_interval(db, anna.id, today, time(15, 0), time(19, 0))

                    tomorrow = today + timedelta(days=1)
                    add_master_schedule_interval(db, anna.id, tomorrow, time(9, 0), time(18, 0))
                    logger.info("✅ Расписание добавлено")

    except IntegrityError as e:
        logger.warning(f"Дублирующиеся данные: {e}")
    except OperationalError as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        sys.exit(1)
    except SQLAlchemyError as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        sys.exit(1)


if __name__ == "__main__":
    logger.info("Запуск инициализации БД...")
    init_db()
    logger.info("База данных успешно инициализирована!")
