import asyncio
import logging
import os
import asyncpg
import hashlib
import uuid
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Update
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
AAIO_MERCHANT_ID = os.getenv("AAIO_MERCHANT_ID")
AAIO_SECRET_1 = os.getenv("AAIO_SECRET_1")
AAIO_SECRET_2 = os.getenv("AAIO_SECRET_2")
PORT = int(os.getenv("PORT", 10000))

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

class PaymentStates(StatesGroup):
    waiting_for_amount = State()

# Подключение к базе данных
async def init_db():
    global db_pool
    db_url = DATABASE_URL.replace("postgresql://", "postgres://") if DATABASE_URL else DATABASE_URL
    db_pool = await asyncpg.create_pool(db_url)
    logging.info("Успешное подключение к базе данных Supabase!")

# Главная клавиатура
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🎰 Играть (Скоро)", callback_data="play_game")]
    ])

# Генерация ссылки на оплату
def generate_aaio_url(amount: int, order_id: str) -> str:
    currency = "RUB"
    desc = "Пополнение баланса в Casino Bot"
    sign_str = f"{AAIO_MERCHANT_ID}:{amount}:{currency}:{AAIO_SECRET_1}:{order_id}"
    sign = hashlib.sha256(sign_str.encode('utf-8')).hexdigest()
    
    pay_url = (
        f"https://aaio.io?"
        f"merchant_id={AAIO_MERCHANT_ID}&"
        f"amount={amount}&"
        f"currency={currency}&"
        f"order_id={order_id}&"
        f"sign={sign}&"
        f"desc={desc}"
    )
    return pay_url

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Игрок"

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = \$1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id, username, balance) VALUES (\$1, \$2, 0.00)", user_id, username)
            balance = 0.00
        else:
            balance = user['balance']

    text = f"🎰 **Casino Bot**\n\n💵 Ваш баланс: **{balance} руб.**"
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# Нажатие кнопки пополнения
@dp.callback_query(F.data == "deposit")
async def process_deposit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("✏️ Введите сумму пополнения в рублях (минимум 100):")
    await state.set_state(PaymentStates.waiting_for_amount)

# Ввод суммы
@dp.message(PaymentStates.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    amount_text = message.text.strip()
    
    if not amount_text.isdigit() or int(amount_text) < 100:
        await message.answer("❌ Сумма должна быть числом и не менее 100 руб.")
        return

    amount = int(amount_text)
    user_id = message.from_user.id
    await state.clear()

    order_id = str(uuid.uuid4())

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO payments (order_id, user_id, amount, status) VALUES (\$1, \$2, \$3, 'pending')",
            order_id, user_id, amount
        )

    payment_link = generate_aaio_url(amount, order_id)
    pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить картой", url=payment_link)]
    ])

    await message.answer(
        f"Заявка на пополнение №`{order_id[:8]}` создана.\nСумма: **{amount} руб.**\n\nНажмите кнопку ниже для оплаты:",
        parse_mode="Markdown",
        reply_markup=pay_keyboard
    )

# ОБРАБОТЧИК WEBHOOK ОТ ПЛАТЕЖНОЙ СИСТЕМЫ AAIO
async def handle_aaio_webhook(request):
    try:
        data = await request.post()
        
        # Получаем данные от AAIO
        merchant_id = data.get('merchant_id')
        amount = data.get('amount')
        order_id = data.get('order_id')
        sign = data.get('sign')
        
        # Проверяем подпись безопасности по правилам AAIO (используем SECRET_2)
        sign_str = f"{merchant_id}:{amount}:{order_id}:{AAIO_SECRET_2}"
        my_sign = hashlib.sha256(sign_str.encode('utf-8')).hexdigest()
        
        if my_sign != sign:
            logging.warning("Неверная подпись Webhook!")
            return web.Response(text="Wrong signature", status=400)
            
        async with db_pool.acquire() as conn:
            # Ищем платеж в базе
            payment = await conn.fetchrow("SELECT * FROM payments WHERE order_id = \$1", order_id)
            
            if payment and payment['status'] == 'pending':
                user_id = payment['user_id']
                pay_amount = float(amount)
                
                # Обновляем статус платежа на 'success'
                await conn.execute("UPDATE payments SET status = 'success' WHERE order_id = \$1", order_id)
                
                # Начисляем баланс пользователю
                await conn.execute("UPDATE users SET balance = balance + \$1 WHERE user_id = \$2", pay_amount, user_id)
                
                # Отправляем сообщение пользователю в Telegram
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ **Баланс успешно пополнен на {pay_amount} руб.!**\nУдачи в игре! 🎰",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение юзеру: {e}")
                    
                return web.Response(text="OK", status=200)
                
        return web.Response(text="Payment not found or already processed", status=200)
        
    except Exception as e:
        logging.error(f"Ошибка при обработке Webhook: {e}")
        return web.Response(text="Error", status=500)

# Эндпоинт для проверки активности сервера (чтобы Render не спал)
async def handle_ping(request):
    return web.Response(text="pong", status=200)

# Главная функция запуска
async def main():
    await init_db()
    
    # Создаем aiohttp веб-приложение
    app = web.Application()
    app.router.add_post('/webhook/aaio', handle_aaio_webhook)
    app.router.add_get('/ping', handle_ping)
    
    # Настраиваем запуск бота параллельно с веб-сервером
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"Веб-сервер запущен на порту {PORT}")
    
    try:
        logging.info("Бот запущен в режиме совмещенного веб-сервера!")
        await dp.start_polling(bot)
    finally:
        await db_pool.close()

if __name__ == "__main__":
    asyncio.run(main())

