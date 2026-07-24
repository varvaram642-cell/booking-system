import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date, timedelta
import plotly.express as px
import os
import json
from typing import Optional, List, Dict

st.set_page_config(page_title="Booking System Admin Dashboard", layout="wide", initial_sidebar_state="expanded")
st.title("🏆 Booking System — Админ-панель")

FASTAPI_API_URL = os.getenv("FASTAPI_API_URL", "http://localhost:8000")

@st.cache_data(ttl=60)
def fetch_from_api(endpoint: str, params: Optional[dict] = None) -> Optional[List[Dict]]:
    url = f"{FASTAPI_API_URL}/api/{endpoint}"
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        st.error(f"❌ Не удалось подключиться к API по адресу {FASTAPI_API_URL}. Убедитесь, что FastAPI запущен.")
        return None
    except requests.exceptions.Timeout:
        st.error(f"⏱️ Таймаут подключения к API ({endpoint}).")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"⚠️ Ошибка API ({endpoint}): {e}")
        return None
    except json.JSONDecodeError:
        st.error(f"⚠️ Ошибка парсинга ответа API ({endpoint}). Ответ: {response.text[:200] if 'response' in locals() else 'нет'}")
        return None

def post_to_api(endpoint: str, data: Dict) -> Optional[Dict]:
    url = f"{FASTAPI_API_URL}/api/{endpoint}"
    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"⚠️ Ошибка отправки в API ({endpoint}): {e}")
        if 'response' in locals():
            st.error(f"Ответ API: {response.text[:200]}")
        return None
    except json.JSONDecodeError:
        st.error(f"⚠️ Ошибка парсинга ответа API ({endpoint})")
        return None

@st.cache_data(ttl=60)
def load_all_data():
    services = fetch_from_api('services')
    masters = fetch_from_api('masters')
    
    bookings = fetch_from_api('bookings')
    if bookings is None:
        st.info("ℹ️ Эндпоинт /api/bookings не найден. Используются демо-данные.")
        bookings = [
            {"id": 1, "client_name": "Анна", "client_phone": "+79991234567", "service_id": 1, "master_id": 1, "booking_date": str(date.today()), "booking_time": "10:00", "status": "confirmed", "source": "telegram"},
            {"id": 2, "client_name": "Иван", "client_phone": "+79991234568", "service_id": 2, "master_id": 2, "booking_date": str(date.today()), "booking_time": "12:00", "status": "confirmed", "source": "site"},
            {"id": 3, "client_name": "Ольга", "client_phone": "+79991234569", "service_id": 3, "master_id": 3, "booking_date": str(date.today() + timedelta(days=1)), "booking_time": "15:00", "status": "confirmed", "source": "telegram"},
        ]
    
    services_map = {s['id']: s for s in services} if services else {}
    masters_map = {m['id']: m for m in masters} if masters else {}
    
    return bookings, services_map, masters_map

bookings_data, services_map, masters_map = load_all_data()

def get_service_details(service_id):
    return services_map.get(service_id, {'name': 'Неизвестно', 'price': 0, 'duration': 0})

def get_master_details(master_id):
    return masters_map.get(master_id, {'name': 'Неизвестно', 'specialization': ''})

st.sidebar.title("📌 Навигация")
menu = st.sidebar.radio("Выберите раздел:", [
    "📊 Главная",
    "📅 Записи",
    "➕ Новая запись",
    "👤 Мастера",
    "➕ Добавить мастера",
    "📋 Услуги",
    "➕ Добавить услугу",
    "📈 Статистика"
])

if menu == "📊 Главная":
    st.subheader("📊 Обзор системы")
    
    if bookings_data:
        df = pd.DataFrame(bookings_data)
        df['service_name'] = df['service_id'].apply(lambda x: get_service_details(x)['name'])
        df['master_name'] = df['master_id'].apply(lambda x: get_master_details(x)['name'])
        df['price'] = df['service_id'].apply(lambda x: get_service_details(x)['price'])
        
        today = date.today()
        confirmed = df[df['status'] == 'confirmed']
        today_confirmed = confirmed[pd.to_datetime(confirmed['booking_date']).dt.date == today]
        total_clients = df['client_phone'].nunique()
        total_revenue = df[df['status'].isin(['confirmed', 'completed'])]['price'].sum()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📅 Записей сегодня", len(today_confirmed))
        col2.metric("👤 Всего клиентов", total_clients)
        col3.metric("👤 Мастеров", len(masters_map))
        col4.metric("💰 Доход", f"{total_revenue:,.0f} ₽")
        
        st.subheader("📈 Динамика записей")
        df['booking_date'] = pd.to_datetime(df['booking_date'])
        daily = df.groupby(df['booking_date'].dt.date).size().reset_index(name='count')
        fig = px.line(daily, x='booking_date', y='count', title='Записи по дням')
        st.plotly_chart(fig, use_container_width=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📊 Популярность услуг")
            service_counts = df['service_name'].value_counts().reset_index()
            service_counts.columns = ['Услуга', 'Количество']
            fig2 = px.bar(service_counts, x='Услуга', y='Количество', title='По услугам')
            st.plotly_chart(fig2, use_container_width=True)
        with col2:
            st.subheader("📊 Загрузка мастеров")
            master_counts = df['master_name'].value_counts().reset_index()
            master_counts.columns = ['Мастер', 'Количество']
            fig3 = px.bar(master_counts, x='Мастер', y='Количество', title='По мастерам')
            st.plotly_chart(fig3, use_container_width=True)

elif menu == "📅 Записи":
    st.subheader("📅 Все записи")
    
    if bookings_data:
        df = pd.DataFrame(bookings_data)
        df['service_name'] = df['service_id'].apply(lambda x: get_service_details(x)['name'])
        df['master_name'] = df['master_id'].apply(lambda x: get_master_details(x)['name'])
        
        col1, col2 = st.columns(2)
        with col1:
            status_filter = st.selectbox("Статус", ["Все", "confirmed", "cancelled", "completed", "no_show"])
        with col2:
            date_filter = st.date_input("Дата", value=None)
        
        filtered = df.copy()
        if status_filter != "Все":
            filtered = filtered[filtered['status'] == status_filter]
        if date_filter:
            filtered = filtered[pd.to_datetime(filtered['booking_date']).dt.date == date_filter]
        
        st.dataframe(
            filtered[["id", "client_name", "client_phone", "service_name", "master_name", "booking_date", "booking_time", "status", "source"]]
            .rename(columns={
                "id": "ID", "client_name": "Клиент", "client_phone": "Телефон",
                "service_name": "Услуга", "master_name": "Мастер",
                "booking_date": "Дата", "booking_time": "Время",
                "status": "Статус", "source": "Источник"
            }),
            use_container_width=True,
            hide_index=True
        )

elif menu == "➕ Новая запись":
    st.subheader("➕ Создать новую запись")
    
    services = fetch_from_api('services')
    masters = fetch_from_api('masters')
    
    if not services or not masters:
        st.warning("⚠️ Не удалось загрузить услуги или мастеров.")
    else:
        service_options = {s['name']: s['id'] for s in services}
        master_options = {m['name']: m['id'] for m in masters if m.get('is_active', True)}
        
        with st.form("new_booking_form"):
            col1, col2 = st.columns(2)
            with col1:
                client_name = st.text_input("Имя клиента*")
                client_phone = st.text_input("Телефон* (+7...)")
                service_name = st.selectbox("Услуга*", list(service_options.keys()))
            with col2:
                master_name = st.selectbox("Мастер*", list(master_options.keys()))
                booking_date = st.date_input("Дата*", min_value=date.today())
                booking_time = st.text_input("Время (ЧЧ:ММ)*", value="10:00")
            
            if st.form_submit_button("💾 Создать запись"):
                if not all([client_name, client_phone, service_name, master_name, booking_date, booking_time]):
                    st.error("❌ Заполните все поля!")
                else:
                    data = {
                        "client_name": client_name,
                        "client_phone": client_phone,
                        "service_id": service_options[service_name],
                        "master_id": master_options[master_name],
                        "booking_date": booking_date.strftime("%Y-%m-%d"),
                        "booking_time": booking_time,
                    }
                    response = post_to_api('book', data)
                    if response and response.get('id'):
                        st.success(f"✅ Запись #{response['id']} создана!")
                        st.cache_data.clear()
                        st.rerun()
                    elif response and response.get('detail'):
                        st.error(f"❌ {response['detail']}")

elif menu == "👤 Мастера":
    st.subheader("👤 Список мастеров")
    
    masters = fetch_from_api('masters')
    if masters:
        df = pd.DataFrame(masters)
        st.dataframe(
            df[["id", "name", "specialization", "phone", "is_active"]]
            .rename(columns={
                "id": "ID", "name": "Имя", "specialization": "Специализация",
                "phone": "Телефон", "is_active": "Активен"
            }),
            use_container_width=True,
            hide_index=True
        )

elif menu == "➕ Добавить мастера":
    st.subheader("➕ Добавить мастера")
    st.warning("⚠️ Эта функция требует добавления POST /api/masters в FastAPI")
    with st.form("add_master_form"):
        name = st.text_input("Имя мастера*")
        specialization = st.text_input("Специализация")
        phone = st.text_input("Телефон")
        if st.form_submit_button("Добавить"):
            st.info("ℹ️ Добавление мастеров через API пока не реализовано. Добавьте POST /api/masters в FastAPI.")

elif menu == "📋 Услуги":
    st.subheader("📋 Список услуг")
    
    services = fetch_from_api('services')
    if services:
        df = pd.DataFrame(services)
        st.dataframe(
            df[["id", "name", "duration", "price"]]
            .rename(columns={
                "id": "ID", "name": "Название", "duration": "Длительность (мин)", "price": "Цена"
            }),
            use_container_width=True,
            hide_index=True
        )

elif menu == "➕ Добавить услугу":
    st.subheader("➕ Добавить услугу")
    st.warning("⚠️ Эта функция требует добавления POST /api/services в FastAPI")
    with st.form("add_service_form"):
        name = st.text_input("Название услуги*")
        duration = st.number_input("Длительность (мин)", min_value=5, value=60)
        price = st.number_input("Цена (руб.)", min_value=100, value=1500)
        if st.form_submit_button("Добавить"):
            st.info("ℹ️ Добавление услуг через API пока не реализовано. Добавьте POST /api/services в FastAPI.")

elif menu == "📈 Статистика":
    st.subheader("📈 Расширенная статистика")
    st.info("ℹ️ Здесь будут более детальные графики и отчёты.")
    
    if bookings_data:
        df = pd.DataFrame(bookings_data)
        df['service_name'] = df['service_id'].apply(lambda x: get_service_details(x)['name'])
        df['master_name'] = df['master_id'].apply(lambda x: get_master_details(x)['name'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📊 Статусы записей")
            status_counts = df['status'].value_counts().reset_index()
            status_counts.columns = ['status', 'count']
            fig = px.pie(status_counts, values='count', names='status', title='По статусам')
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            st.subheader("📊 Источники записей")
            source_counts = df['source'].value_counts().reset_index()
            source_counts.columns = ['source', 'count']
            fig = px.pie(source_counts, values='count', names='source', title='По источникам')
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Нет данных для статистики.")
