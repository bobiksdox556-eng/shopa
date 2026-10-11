import asyncio
import logging
import os
import uuid
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

logging.basicConfig(level=logging.INFO)

# Берем токены напрямую из настроек Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ВРЕМЕННАЯ БАЗА ДАННЫХ ПРЯМО В ПАМЯТИ СЕРВЕРА
users_db = {}     # Тут храним балансы {user_id: balance}
payments_db = {}  # Тут храним платежи {order_id: {"user_id": user_id, "amount": amount, "status": status}}

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
    
    # Если пользователя нет в нашей памяти — даем ему 0 рублей
    if user_id not in users_db:
        users_db[user_id] = 0.00
        
    balance = users_db[user_id]
    await message.answer(f"🎰 **Casino Bot**\n\n💵 Баланс: **{balance} руб.**", parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "deposit_crypto")
async def process_deposit(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    order_id = str(uuid.uuid4())
    amount = 500

    # Сохраняем платеж в память
    payments_db[order_id] = {
        "user_id": user_id,
        "amount": amount,
        "status": "pending"
    }

    pay_url = await create_crypto_invoice(amount, order_id)
    if pay_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Оплатить", url=pay_url)]])
        await callback.message.answer(f"Заявка создана. Сумма: **{amount} руб.**\nНажмите кнопку для оплаты:", parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer("❌ Ошибка генерации счета. Проверьте CRYPTO_BOT_TOKEN в Render.")

async def handle_crypto_webhook(request):
    try:
        data = await request.json()
        if data.get("update_type") == "invoice_paid":
            payload = data["update_object"]["payload"]
            
            # Проверяем платеж в памяти
            payment = payments_db.get(payload)
            if payment and payment['status'] == 'pending':
                payment['status'] = 'success'
                user_id = payment['user_id']
                
                # Начисляем баланс в памяти
                if user_id in users_db:
                    users_db[user_id] += float(payment['amount'])
                else:
                    users_db[user_id] = float(payment['amount'])
                    
                await bot.send_message(chat_id=user_id, text="✅ Баланс успешно пополнен через CryptoBot!")
        return web.Response(text="OK", status=200)
    except Exception:
        return web.Response(text="Error", status=400)

async def main():
    app = web.Application()
    app.router.add_post('/webhook/crypto', handle_crypto_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    logging.info("Бот успешно запущен в упрощенном режиме!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
