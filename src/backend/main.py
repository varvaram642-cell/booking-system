import logging
import os
import re
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional, List

from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.database import (
    create_booking,
    get_all_masters,
    get_all_services,
    get_db,
    get_master_by_id,
    get_service_by_id,
    now_local,
    ServiceMaster,
    Booking,
    get_masters_for_service
)
from bot.booking_utils import get_free_slots

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Booking System API",
    description="API для записи клиентов через сайт",
    version="1.0.0",
)

ALLOWED_ORIGINS_STR = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS_STR.split(',')]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Ошибка базы данных FastApi")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Внутренняя ошибка сервера. Попробуйте позже."}
    )

class BookingCreate(BaseModel):
    client_name: str = Field(min_length=2, max_length=100, description="Имя клиента")
    client_phone: str = Field(description="Телефон клиента в любом формате")
    service_id: int = Field(gt=0, description="ID услуги")
    master_id: int = Field(gt=0, description="ID мастера")
    booking_date: date = Field(description="Дата записи в формате YYYY-MM-DD")
    booking_time: str = Field(description="Время записи в формате HH:MM")

    @field_validator("client_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        cleaned = re.sub(r"\D", "", value)
        if len(cleaned) < 10 or len(cleaned) > 15:
            raise ValueError("Некорректный номер телефона")
        if not cleaned.startswith("7") and not cleaned.startswith("8"):
            cleaned = "7" + cleaned
        if cleaned.startswith("8"):
            cleaned = "7" + cleaned[1:]
        return f"+{cleaned}"
    
    @field_validator("booking_time")
    @classmethod
    def validate_booking_time(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%H:%M").time()
        except ValueError:
            raise ValueError("Некорректный формат времени. Ожидается HH:MM.")
        return value

class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message: str
    booking_date: date
    booking_time: str
    master_name: str
    service_name: str
    price: Decimal

class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    duration: int
    price: Decimal

class MasterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    specialization: Optional[str] = None
    is_active: bool

class FreeSlotResponse(BaseModel):
    date: date
    slots: List[str]

@app.get("/", summary="Корневой эндпоинт API", response_description="Состояние API")
async def root():
    logger.info("Root endpoint accessed")
    return {"message": "Booking System API", "status": "running", "version": app.version}

@app.get("/api/services", response_model=list[ServiceResponse], summary="Получить список всех услуг", response_description="Список доступных услуг")
async def get_services(db: Session = Depends(get_db)):
    services_list = get_all_services(db)
    logger.info(f"Retrieved {len(services_list)} services")
    return services_list

@app.get("/api/masters", response_model=list[MasterResponse], summary="Получить список всех активных мастеров", response_description="Список активных мастеров")
async def get_masters(service_id: Optional[int] = None, db: Session = Depends(get_db)):
    if service_id:
        masters_list = get_masters_for_service(db, service_id)
        logger.info(f"Retrieved {len(masters_list)} masters for service_id={service_id}")
        return masters_list
    masters_list = get_all_masters(db, only_active=True)
    logger.info(f"Retrieved {len(masters_list)} active masters")
    return masters_list

@app.get("/api/free-slots", response_model=List[FreeSlotResponse], summary="Возвращает свободные слоты для мастера на выбранную услугу")
async def get_free_slots_api(
    master_id: int = Field(gt=0, description="ID мастера"),
    service_id: int = Field(gt=0, description="ID услуги"),
    days_ahead: int = Field(default=7, gt=0, le=30, description="Количество дней вперед для поиска слотов (макс. 30)"),
    db: Session = Depends(get_db)
):
    service = get_service_by_id(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Услуга не найдена")
    
    master = get_master_by_id(db, master_id)
    if not master:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
    
    if not master.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Мастер не активен или временно не принимает записи")
    
    from bot.database import get_available_dates
    
    today = now_local().date()
    result = []
    available_master_dates = get_available_dates(db, master_id, days_ahead=days_ahead)

    for i in range(days_ahead):
        booking_date = today + timedelta(days=i)
        if booking_date not in available_master_dates:
            continue
        slots = get_free_slots(db, master_id, service, booking_date)
        if slots:
            result.append(FreeSlotResponse(
                date=booking_date,
                slots=[s.strftime("%H:%M") for s in slots]
            ))
    logger.info(f"Returned {len(result)} free slot dates for master {master_id}, service {service_id}")
    return result

@app.post("/api/book", response_model=BookingResponse, status_code=status.HTTP_201_CREATED, summary="Создать новую запись", response_description="Подтверждение создания записи")
async def create_booking_api(
    booking: BookingCreate,
    db: Session = Depends(get_db),
):
    logger.info(f"Получен запрос на создание записи: {booking.model_dump()}")

    service = get_service_by_id(db, booking.service_id)
    if not service:
        logger.warning(f"Попытка бронирования с несуществующей услугой ID: {booking.service_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Услуга не найдена",
        )

    master = get_master_by_id(db, booking.master_id)
    if not master:
        logger.warning(f"Попытка бронирования с несуществующим мастером ID: {booking.master_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мастер не найден",
        )

    if not master.is_active:
        logger.warning(f"Попытка бронирования к неактивному мастеру ID: {master.id}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Мастер временно не принимает записи")

    service_master = db.query(ServiceMaster).filter_by(
        service_id=booking.service_id,
        master_id=booking.master_id,
    ).first()
    if not service_master:
        logger.warning(f"Мастер {master.name} не оказывает услугу {service.name}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Мастер {master.name} не оказывает услугу {service.name}",
        )

    booking_time_obj = datetime.strptime(
        booking.booking_time,
        "%H:%M",
    ).time()

    booking_datetime_local = datetime.combine(booking.booking_date, booking_time_obj).replace(tzinfo=now_local().tzinfo)
    if booking_datetime_local <= now_local():
        logger.warning(f"Попытка записи на прошедшее или текущее время: {booking_datetime_local}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя записаться в прошлое или текущее время",
        )
    
    free_slots = get_free_slots(db, master.id, service, booking.booking_date)
    if booking_time_obj not in free_slots:
        logger.warning(f"Попытка записи на занятый слот: мастер {master.id}, дата {booking.booking_date}, время {booking_time_obj}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Выбранное время уже занято или недоступно. Пожалуйста, выберите другое время."
        )

    try:
        new_booking = create_booking(
            db=db,
            client_id=None,
            service_id=booking.service_id,
            master_id=booking.master.id,
            booking_date=booking.booking_date,
            booking_time=booking_time_obj,
            client_name=booking.client_name.strip(),
            client_phone=booking.client_phone,
            source="site",
        )

        logger.info(
            f"Запись успешно создана: ID {new_booking.id} "
            f"для {booking.client_name} "
            f"к мастеру {master.name} "
            f"на {booking.booking_date} {booking_time_obj}"
        )

        return BookingResponse(
            id=new_booking.id,
            message="Запись успешно создана",
            booking_date=new_booking.booking_date,
            booking_time=new_booking.booking_time.strftime("%H:%M"),
            master_name=master.name,
            service_name=service.name,
            price=service.price,
        )

    except ValueError as e:
        logger.warning(f"Ошибка валидации при создании записи: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except IntegrityError as e:
        db.rollback()
        logger.exception("Конфликт записи: вероятно, слот занят.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Это время уже занято. Выберите другое время.",
        )
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception(f"Ошибка SQLAlchemy при создании записи: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Произошла внутренняя ошибка базы данных."
        )
    except Exception as e:
        db.rollback()
        logger.exception(f"Непредвиденная ошибка при создании записи: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Произошла непредвиденная ошибка сервера."
        )

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    logger.info("Запуск FastAPI приложения...")
    uvicorn.run(
        "src.backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
