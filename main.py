import asyncio
import logging
import os
import asyncpg
import uuid
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

logging.basicConfig(level=logging.INFO)

# Ключи берем из настроек Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None

async def init_db():
    global db_pool
    
    # === НАСТРОЙКА БАЗЫ ДАННЫХ ===
    # Просто впиши свой пароль от базы данных Supabase между кавычек:
    SUPABASE_PASSWORD = "Kristinabelozerskaya"
    
    # Прямой и самый надежный хост Supabase
    db_url = f"postgres://postgres.arthejhklkqfdcqjgqaz:{SUPABASE_PASSWORD}@db.arthejhklkqfdcqjgqaz.supabase.co:5432/postgres"

    db_pool = await asyncpg.create_pool(db_url)
    logging.info("База данных успешно подключена напрямую!")

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить через CryptoBot", callback_data="deposit_crypto")]
    ])

async def create_crypto_invoice(amount: int, order_id: str):
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount / 100),
        "payload": order_id
    }
    import aiohttp
    async with aiohttp.ClientSession() as session:
        url = "https://cryptofay.io" if "test" in CRYPTO_BOT_TOKEN else "https://cryptobot.app"
        async with session.post(url, json=payload, headers=headers) as resp:
            res = await resp.json()
            if res.get("result"):
                return res["result"]["pay_url"]
    return None

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Игрок"
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id, username, balance) VALUES ($1, $2, 0.00)", user_id, username)
            balance = 0.00
        else:
            balance = user['balance']
    await message.answer(f"🎰 **Casino Bot**\n\n💵 Баланс: **{balance} руб.**", parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "deposit_crypto")
async def process_deposit(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    order_id = str(uuid.uuid4())
    amount = 500

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO payments (order_id, user_id, amount, status) VALUES ($1, $2, $3, 'pending')", order_id, user_id, amount)

    pay_url = await create_crypto_invoice(amount, order_id)
    if pay_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Оплатить", url=pay_url)]])
        await callback.message.answer(f"Заявка создана. Сумма: **{amount} руб.**\nНажмите кнопку для оплаты:", parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer("❌ Ошибка генерации счета. Проверьте CRYPTO_BOT_TOKEN.")

async def handle_crypto_webhook(request):
    try:
        data = await request.json()
        if data.get("update_type") == "invoice_paid":
            payload = data["update_object"]["payload"]
            async with db_pool.acquire() as conn:
                payment = await conn.fetchrow("SELECT * FROM payments WHERE order_id = $1", payload)
                if payment and payment['status'] == 'pending':
                    await conn.execute("UPDATE payments SET status = 'success' WHERE order_id = $1", payload)
                    await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(payment['amount']), payment['user_id'])
                    await bot.send_message(chat_id=payment['user_id'], text="✅ Баланс успешно пополнен через CryptoBot!")
        return web.Response(text="OK", status=200)
    except Exception:
        return web.Response(text="Error", status=400)

async def main():
    await init_db()
    app = web.Application()
    app.router.add_post('/webhook/crypto', handle_crypto_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
