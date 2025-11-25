import asyncio
import logging
from datetime import datetime
import sqlite3
import uuid
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery

# ⚙️ НАСТРОЙКИ
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))

DB_FILE = 'orders.db'

def init_db():
    """Инициализация БД"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Таблица клиентов с датой и ID
        cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
            user_id INTEGER PRIMARY KEY,
            order_id TEXT UNIQUE,
            order_date TEXT,
            is_paid INTEGER DEFAULT 0,
            created_at TEXT
        )''')
        
        # Таблица диапазонов статусов по датам
        cursor.execute('''CREATE TABLE IF NOT EXISTS status_ranges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_from TEXT,
            date_to TEXT,
            status TEXT,
            info TEXT,
            created_at TEXT
        )''')
        
        conn.commit()
        logging.info("✅ БД инициализирована")
    except Exception as e:
        logging.error(f"❌ Ошибка БД: {e}")
    finally:
        conn.close()

init_db()

# 🔄 СОСТОЯНИЯ
class RegisterOrderState(StatesGroup):
    waiting_order_date = State()

class SetStatusRangeState(StatesGroup):
    waiting_date_from = State()
    waiting_date_to = State()
    waiting_status = State()
    waiting_info = State()

class PaymentState(StatesGroup):
    waiting_user_id = State()
    waiting_action = State()

# 🤖 БОТ
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# 📊 СТАТУСЫ
STATUSES = {
    'waiting': '⏳ Ожидается',
    'in_transit': '🚚 В пути',
    'delivered': '✅ Пришли'
}

# 🛠️ ФУНКЦИИ
def validate_date(date_str):
    """Проверить формат даты"""
    try:
        datetime.strptime(date_str, '%d.%m.%Y')
        return True
    except:
        return False

def generate_order_id():
    """Генерировать уникальный ID заказа"""
    return str(uuid.uuid4())[:8].upper()

def get_customer_by_user_id(user_id):
    """Получить данные клиента по user_id"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT order_id, order_date, is_paid FROM customers WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except:
        return None

def get_customer_by_order_id(order_id):
    """Получить данные клиента по order_id"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, order_date, is_paid FROM customers WHERE order_id = ?', (order_id.upper(),))
        result = cursor.fetchone()
        conn.close()
        return result
    except:
        return None

def save_customer_order(user_id, order_date):
    """Сохранить заказ клиента с автогенерируемым ID"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        created_at = datetime.now().strftime('%d.%m.%Y %H:%M')
        
        # Генерируем ID пока не найдём уникальный
        while True:
            order_id = generate_order_id()
            cursor.execute('SELECT order_id FROM customers WHERE order_id = ?', (order_id,))
            if not cursor.fetchone():
                break
        
        cursor.execute('INSERT OR REPLACE INTO customers (user_id, order_id, order_date, is_paid, created_at) VALUES (?, ?, ?, ?, ?)',
                       (user_id, order_id, order_date, 1, created_at))
        conn.commit()
        conn.close()
        return order_id
    except:
        return None

def get_status_for_date(order_date):
    """Найти статус для даты заказа"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''SELECT status, info FROM status_ranges 
                         WHERE date_from <= ? 
                         AND date_to >= ?
                         ORDER BY id DESC LIMIT 1''',
                       (order_date, order_date))
        result = cursor.fetchone()
        conn.close()
        
        return result
    except:
        return None

def set_status_range(date_from, date_to, status, info):
    """Установить статус на диапазон дат"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        created_at = datetime.now().strftime('%d.%m.%Y %H:%M')
        cursor.execute('''INSERT INTO status_ranges (date_from, date_to, status, info, created_at)
                         VALUES (?, ?, ?, ?, ?)''',
                       (date_from, date_to, status, info, created_at))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_all_ranges():
    """Все диапазоны"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT id, date_from, date_to, status, info, created_at FROM status_ranges ORDER BY id DESC')
        ranges = cursor.fetchall()
        conn.close()
        return ranges
    except:
        return []

def delete_range(range_id):
    """Удалить диапазон"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM status_ranges WHERE id = ?', (range_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def create_client_keyboard():
    """Клавиатура для клиента"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📦 Мой статус')],
            [KeyboardButton(text='🔄 Изменить дату')]
        ],
        resize_keyboard=True
    )

# ========== КЛИЕНТЫ ==========

@router.message(Command('start'))
async def start(message: Message, state: FSMContext):
    """Начало"""
    user_id = message.from_user.id
    existing = get_customer_by_user_id(user_id)
    
    await state.clear()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📝 Ввести дату заказа', callback_data='register_order')],
        [InlineKeyboardButton(text='🔍 Проверить статус', callback_data='quick_check')]
    ])
    
    if existing:
        order_id, order_date, is_paid = existing
        paid_status = '✅ Оплачено' if is_paid else '❌ Не оплачено'
        await message.answer(
            f'👋 Привет!\n\n'
            f'🔖 Номер заказа: {order_id}\n'
            f'📅 Дата: {order_date}\n'
            f'💳 {paid_status}',
            reply_markup=create_client_keyboard()
        )
    else:
        await message.answer(
            '👋 Привет в DripUz! 👗\n\n'
            'Что ты хочешь сделать?',
            reply_markup=keyboard
        )

@router.callback_query(lambda c: c.data == 'register_order')
async def register_order_callback(callback: CallbackQuery, state: FSMContext):
    """Регистрация даты заказа"""
    await state.clear()
    await callback.message.edit_text('📝 Введи дату заказа\n\nФормат: ДД.MM.ГГГГ\nПример: 25.11.2025')
    await state.set_state(RegisterOrderState.waiting_order_date)
    await callback.answer()

@router.callback_query(lambda c: c.data == 'quick_check')
async def quick_check_callback(callback: CallbackQuery, state: FSMContext):
    """Быстрая проверка"""
    await state.clear()
    await callback.message.edit_text('🔍 Введи дату заказа для проверки:\n\nФормат: ДД.MM.ГГГГ')
    await state.set_state(RegisterOrderState.waiting_order_date)
    await callback.answer()

@router.message(RegisterOrderState.waiting_order_date)
async def register_order(message: Message, state: FSMContext):
    """Регистрация даты заказа"""
    order_date = message.text.strip()
    
    if not validate_date(order_date):
        await message.answer('❌ Неверный формат!\n\nФормат: ДД.MM.ГГГГ\nПример: 25.11.2025')
        return
    
    order_id = save_customer_order(message.from_user.id, order_date)
    
    if order_id:
        await message.answer(
            f'✅ Готово!\n\n'
            f'🔖 Номер заказа: {order_id}\n'
            f'📅 Дата: {order_date}',
            reply_markup=create_client_keyboard()
        )
    else:
        await message.answer('❌ Ошибка! Попробуй позже')
    
    await state.clear()

@router.message(lambda m: m.text == '📦 Мой статус')
async def check_my_status(message: Message):
    """Проверить статус"""
    user_id = message.from_user.id
    customer = get_customer_by_user_id(user_id)
    
    if not customer:
        await message.answer('❌ Заказ не найден!\n\nНажми /start')
        return
    
    order_id, order_date, is_paid = customer
    
    if not is_paid:
        await message.answer(
            f'❌ ЗАКАЗ НЕ ОПЛАЧЕН\n\n'
            f'🔖 Номер: {order_id}\n'
            f'📅 Дата: {order_date}\n\n'
            f'Пожалуйста, оплати заказ чтобы начать отслеживание статуса 💳',
            reply_markup=create_client_keyboard()
        )
        return
    
    result = get_status_for_date(order_date)
    
    if result:
        status_code, info = result
        status_text = STATUSES.get(status_code, status_code)
        await message.answer(
            f'✅ СТАТУС ТВОЕГО ЗАКАЗА\n\n'
            f'🔖 Номер: {order_id}\n'
            f'📅 Дата: {order_date}\n'
            f'📊 Статус: {status_text}\n'
            f'📝 {info}',
            reply_markup=create_client_keyboard()
        )
    else:
        await message.answer(
            f'⏳ Заказ {order_id} от {order_date}\n\n'
            f'❌ Статус ещё не установлен\n\n'
            f'Попробуй позже 👍',
            reply_markup=create_client_keyboard()
        )

@router.message(lambda m: m.text == '🔄 Изменить дату')
async def change_order_btn(message: Message, state: FSMContext):
    """Изменить дату заказа"""
    await state.clear()
    await message.answer('📝 Введи новую дату заказа:\n\nФормат: ДД.MM.ГГГГ')
    await state.set_state(RegisterOrderState.waiting_order_date)

# ========== АДМИН ==========

@router.message(Command('admin'))
async def admin_start(message: Message, state: FSMContext):
    """Админ панель"""
    if message.from_user.id != ADMIN_ID:
        await message.answer('❌ Только админ может это делать')
        return
    
    await state.clear()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📊 Установить статусы')],
            [KeyboardButton(text='📋 Просмотреть диапазоны')],
            [KeyboardButton(text='💳 Управлять оплатой')],
            [KeyboardButton(text='❌ Выход из админа')]
        ],
        resize_keyboard=True
    )
    await message.answer('⚙️ АДМИН-ПАНЕЛЬ', reply_markup=keyboard)

@router.message(lambda m: m.text == '📊 Установить статусы')
async def set_range_btn(message: Message, state: FSMContext):
    """Установить диапазон статусов по датам"""
    if message.from_user.id != ADMIN_ID:
        await message.answer('❌ Только админ')
        return
    
    await state.clear()
    await message.answer('📝 Введи начальную дату:\n\nФормат: ДД.MM.ГГГГ\nПример: 01.11.2025')
    await state.set_state(SetStatusRangeState.waiting_date_from)

@router.message(SetStatusRangeState.waiting_date_from)
async def date_from(message: Message, state: FSMContext):
    date_from = message.text.strip()
    if not validate_date(date_from):
        await message.answer('❌ Неверный формат!\n\nФормат: ДД.MM.ГГГГ')
        return
    await state.update_data(date_from=date_from)
    await message.answer('📝 Введи конечную дату:\n\nФормат: ДД.MM.ГГГГ\nПример: 10.11.2025')
    await state.set_state(SetStatusRangeState.waiting_date_to)

@router.message(SetStatusRangeState.waiting_date_to)
async def date_to(message: Message, state: FSMContext):
    date_to = message.text.strip()
    if not validate_date(date_to):
        await message.answer('❌ Неверный формат!\n\nФормат: ДД.MM.ГГГГ')
        return
    await state.update_data(date_to=date_to)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='⏳ Ожидается', callback_data='status_waiting')],
        [InlineKeyboardButton(text='🚚 В пути', callback_data='status_in_transit')],
        [InlineKeyboardButton(text='✅ Пришли', callback_data='status_delivered')]
    ])
    await message.answer('📊 Выбери статус:', reply_markup=keyboard)
    await state.set_state(SetStatusRangeState.waiting_status)

@router.callback_query(lambda c: c.data.startswith('status_'), SetStatusRangeState.waiting_status)
async def choose_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.replace('status_', '')
    await state.update_data(status=status)
    await callback.message.edit_text('📝 Добавь комментарий (максимум 100 символов)\n\nПример: "Завтра доставим"')
    await state.set_state(SetStatusRangeState.waiting_info)
    await callback.answer()

@router.message(SetStatusRangeState.waiting_info)
async def set_info(message: Message, state: FSMContext):
    data = await state.get_data()
    info = message.text.strip()[:100]
    
    if set_status_range(data['date_from'], data['date_to'], data['status'], info):
        status_text = STATUSES.get(data['status'])
        await message.answer(
            f'✅ ГОТОВО!\n\n'
            f'📅 Даты: {data["date_from"]} - {data["date_to"]}\n'
            f'📊 Статус: {status_text}\n'
            f'📝 {info}'
        )
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text='📊 Установить статусы')],
                [KeyboardButton(text='📋 Просмотреть диапазоны')],
                [KeyboardButton(text='💳 Управлять оплатой')],
                [KeyboardButton(text='❌ Выход из админа')]
            ],
            resize_keyboard=True
        )
        await message.answer('⚙️ АДМИН-ПАНЕЛЬ', reply_markup=keyboard)
    else:
        await message.answer('❌ Ошибка!')
    
    await state.clear()

@router.message(lambda m: m.text == '📋 Просмотреть диапазоны')
async def view_ranges(message: Message):
    """Просмотреть все диапазоны"""
    if message.from_user.id != ADMIN_ID:
        await message.answer('❌ Только админ')
        return
    
    ranges = get_all_ranges()
    
    if not ranges:
        text = '❌ Нет установленных диапазонов'
    else:
        text = '📋 ВСЕ ДИАПАЗОНЫ:\n\n'
        for rid, date_from, date_to, status, info, created in ranges:
            status_text = STATUSES.get(status)
            text += f'🔖 №{rid}\n'
            text += f'📅 Даты: {date_from} → {date_to}\n'
            text += f'📊 {status_text}\n'
            text += f'📝 {info}\n'
            text += f'⏰ {created}\n'
            text += f'➡️ /delete_{rid}\n\n'
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📊 Установить статусы')],
            [KeyboardButton(text='📋 Просмотреть диапазоны')],
            [KeyboardButton(text='💳 Управлять оплатой')],
            [KeyboardButton(text='❌ Выход из админа')]
        ],
        resize_keyboard=True
    )
    await message.answer(text, reply_markup=keyboard)

@router.message(lambda m: m.text and m.text.startswith('/delete_'))
async def delete_btn(message: Message):
    """Удалить диапазон"""
    if message.from_user.id != ADMIN_ID:
        await message.answer('❌ Только админ')
        return
    
    try:
        rid = int(message.text.replace('/delete_', ''))
        if delete_range(rid):
            await message.answer(
                f'✅ Диапазон №{rid} удален!',
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text='📊 Установить статусы')],
                        [KeyboardButton(text='📋 Просмотреть диапазоны')],
                        [KeyboardButton(text='💳 Управлять оплатой')],
                        [KeyboardButton(text='❌ Выход из админа')]
                    ],
                    resize_keyboard=True
                )
            )
        else:
            await message.answer('❌ Не найден')
    except:
        await message.answer('❌ Ошибка')

@router.message(lambda m: m.text == '💳 Управлять оплатой')
async def manage_payment_btn(message: Message, state: FSMContext):
    """Управление оплатой"""
    if message.from_user.id != ADMIN_ID:
        await message.answer('❌ Только админ')
        return
    
    await state.clear()
    await message.answer('💳 Введи order_id клиента:')
    await state.set_state(PaymentState.waiting_user_id)

@router.message(PaymentState.waiting_user_id)
async def get_order_id(message: Message, state: FSMContext):
    """Получить order_id"""
    try:
        order_id = message.text.strip().upper()
        
        customer = get_customer_by_order_id(order_id)
        
        if not customer:
            await message.answer('❌ Заказ не найден!')
            await state.clear()
            return
        
        user_id, order_date, is_paid = customer
        status_text = '✅ Оплачено' if is_paid else '❌ Не оплачено'
        
        await state.update_data(order_id=order_id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ Оплачено', callback_data='payment_yes')],
            [InlineKeyboardButton(text='❌ Не оплачено', callback_data='payment_no')]
        ])
        
        await message.answer(
            f'📦 Заказ: {order_id}\n'
            f'📅 Дата: {order_date}\n'
            f'💳 Статус: {status_text}\n\n'
            f'Выбери статус оплаты:',
            reply_markup=keyboard
        )
        await state.set_state(PaymentState.waiting_action)
    except:
        await message.answer('❌ Ошибка! Проверь order_id')

@router.callback_query(lambda c: c.data.startswith('payment_'), PaymentState.waiting_action)
async def set_payment(callback: CallbackQuery, state: FSMContext):
    """Установить статус оплаты"""
    data = await state.get_data()
    order_id = data['order_id']
    
    is_paid = 1 if callback.data == 'payment_yes' else 0
    status_text = '✅ Оплачено' if is_paid else '❌ Не оплачено'
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('UPDATE customers SET is_paid = ? WHERE order_id = ?', (is_paid, order_id))
        conn.commit()
        conn.close()
        
        await callback.message.edit_text(
            f'✅ ГОТОВО!\n\n'
            f'📦 Заказ: {order_id}\n'
            f'💳 Новый статус: {status_text}'
        )
    except:
        await callback.message.edit_text('❌ Ошибка!')
    
    await state.clear()
    await callback.answer()

@router.message(lambda m: m.text == '❌ Выход из админа')
async def exit_admin(message: Message, state: FSMContext):
    """Выход из админ панели"""
    await state.clear()
    await message.answer(
        '👋 Вышел из админ-панели',
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text='📦 Мой статус')]],
            resize_keyboard=True,
            one_time_keyboard=False
        )
    )

# 🚀 ЗАПУСК
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    try:
        logging.info("🚀 Бот запущен")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ {e}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("⏹️ Бот остановлен")