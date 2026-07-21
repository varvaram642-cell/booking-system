from datetime import datetime, timedelta, date, time
from typing import List

from sqlalchemy.orm import Session

from .database import (
    get_master_schedule_intervals,
    get_bookings_for_master_on_date,
    get_service_by_id,
    Booking,
    Service,
    LOCAL_TIMEZONE,
    today_local,
    now_local,
)


def _get_booking_durations(db: Session, booking_ids: list) -> dict:
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


def get_free_slots(db: Session, master_id: int, service, booking_date: date) -> List[time]:
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
