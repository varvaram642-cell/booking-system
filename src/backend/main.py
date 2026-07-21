import logging
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
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
)
from bot.booking_utils import get_free_slots

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


app = FastAPI(
    title="Booking System API",
    description="API для записи клиентов через сайт",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BookingCreate(BaseModel):
    client_name: str = Field(min_length=2, max_length=100)
    client_phone: str
    service_id: int = Field(gt=0)
    master_id: int = Field(gt=0)
    booking_date: date
    booking_time: str

    @field_validator("client_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        cleaned = re.sub(r"\D", "", value)
        if len(cleaned) < 10 or len(cleaned) > 15:
            raise ValueError("Некорректный номер телефона")
        return cleaned


class BookingResponse(BaseModel):
    id: int
    message: str


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


@app.get("/")
async def root():
    return {
        "message": "Booking System API",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/api/services", response_model=list[ServiceResponse])
async def get_services(db: Session = Depends(get_db)):
    return get_all_services(db)


@app.get("/api/masters", response_model=list[MasterResponse])
async def get_masters(db: Session = Depends(get_db)):
    return get_all_masters(db, only_active=True)


@app.post("/api/book", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking_api(
    booking: BookingCreate,
    db: Session = Depends(get_db),
):
    service = get_service_by_id(db, booking.service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Услуга не найдена",
        )

    master = get_master_by_id(db, booking.master_id)
    if not master:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мастер не найден",
        )

    if not master.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Мастер временно не принимает записи",
        )

    # Проверка: мастер оказывает эту услугу
    service_master = db.query(ServiceMaster).filter_by(
        service_id=booking.service_id,
        master_id=booking.master_id,
    ).first()
    if not service_master:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Мастер {master.name} не оказывает услугу {service.name}",
        )

    try:
        booking_time = datetime.strptime(booking.booking_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный формат времени. Используйте ЧЧ:ММ",
        )

    now = now_local()

    if booking.booking_date < now.date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя записаться на прошедшую дату",
        )

    if booking.booking_date == now.date() and booking_time <= now.time():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Это время уже прошло",
        )

    free_slots = get_free_slots(db, master.id, service, booking.booking_date)
    if booking_time not in free_slots:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Это время уже занято. Выберите другое время.",
        )

    try:
        new_booking = create_booking(
            db=db,
            client_id=None,
            service_id=booking.service_id,
            master_id=booking.master_id,
            booking_date=booking.booking_date,
            booking_time=booking_time,
            client_name=booking.client_name.strip(),
            client_phone=booking.client_phone,
            source="site",
        )

        return BookingResponse(
            id=new_booking.id,
            message="Запись успешно создана",
        )

    except ValueError as e:
        logger.warning(f"Ошибка валидации: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except IntegrityError as e:
        db.rollback()
        logger.error(f"Конфликт записи: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Это время уже занято. Выберите другое время.",
        )

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Ошибка базы данных: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера. Попробуйте позже.",
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Неизвестная ошибка: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера. Попробуйте позже.",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
