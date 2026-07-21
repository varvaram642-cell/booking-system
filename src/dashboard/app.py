import sys
import os

# Добавляем путь к корню проекта, чтобы работали импорты
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from bot.database import SessionLocal, get_today_bookings, get_all_masters, get_all_services

st.set_page_config(page_title="Booking Dashboard", layout="wide")
st.title("📊 Booking System Dashboard")


def safe_get_attr(obj, attr, default=None):
    """Безопасно получает атрибут объекта."""
    return getattr(obj, attr, default) if obj else default


tab1, tab2, tab3 = st.tabs(["📅 Записи", "👤 Мастера", "📋 Услуги"])

with tab1:
    st.subheader("📅 Записи на сегодня")
    
    try:
        with SessionLocal() as db:
            bookings = get_today_bookings(db)
            
            if bookings:
                data = []
                for b in bookings:
                    service = safe_get_attr(b.service_obj, "name", "Неизвестно")
                    master = safe_get_attr(b.master_obj, "name", "Неизвестно")
                    
                    client_obj = safe_get_attr(b, "client_obj")
                    if client_obj:
                        client = safe_get_attr(client_obj, "full_name") or safe_get_attr(client_obj, "username") or "Неизвестно"
                    else:
                        client = b.client_name or "Неизвестно"
                    
                    data.append({
                        "Время": b.booking_time.strftime("%H:%M"),
                        "Клиент": client,
                        "Услуга": service,
                        "Мастер": master,
                        "Источник": b.source or "telegram",
                    })
                
                st.dataframe(pd.DataFrame(data), use_container_width=True)
                st.caption(f"Всего записей на сегодня: {len(data)}")
            else:
                st.info("На сегодня записей нет")
                
    except SQLAlchemyError as e:
        st.error(f"❌ Ошибка подключения к базе данных: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Непредвиденная ошибка: {e}")
        st.stop()


with tab2:
    st.subheader("👤 Список мастеров")
    
    try:
        with SessionLocal() as db:
            masters = get_all_masters(db)
            
            if masters:
                data = []
                for m in masters:
                    data.append({
                        "ID": m.id,
                        "Имя": m.name,
                        "Специализация": safe_get_attr(m, "specialization", "-"),
                        "Телефон": safe_get_attr(m, "phone", "-"),
                        "Активен": "✅" if safe_get_attr(m, "is_active", False) else "❌",
                    })
                st.dataframe(pd.DataFrame(data), use_container_width=True)
                st.caption(f"Всего мастеров: {len(data)}")
            else:
                st.info("Мастеров в системе нет")
                
    except SQLAlchemyError as e:
        st.error(f"❌ Ошибка подключения к базе данных: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Непредвиденная ошибка: {e}")
        st.stop()


with tab3:
    st.subheader("📋 Список услуг")
    
    try:
        with SessionLocal() as db:
            services = get_all_services(db)
            
            if services:
                data = []
                for s in services:
                    price = safe_get_attr(s, "price")
                    if price is None:
                        price_display = "Цена не указана"
                    else:
                        try:
                            price_display = f"{float(price):.0f} руб."
                        except (TypeError, ValueError):
                            price_display = str(price)
                    
                    data.append({
                        "ID": s.id,
                        "Название": s.name,
                        "Длительность": f"{safe_get_attr(s, 'duration', 0)} мин",
                        "Цена": price_display,
                    })
                st.dataframe(pd.DataFrame(data), use_container_width=True)
                st.caption(f"Всего услуг: {len(data)}")
            else:
                st.info("Услуг в системе нет")
                
    except SQLAlchemyError as e:
        st.error(f"❌ Ошибка подключения к базе данных: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Непредвиденная ошибка: {e}")
        st.stop()


# Кнопка обновления
if st.button("🔄 Обновить данные"):
    st.rerun()
