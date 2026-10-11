import asyncio
import logging
import os
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

# База данных прямо в памяти (балансы и платежи)
users_db = {}     
payments_db = {}  

# Главное меню казино
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Играть в Слоты (100 руб)", callback_data="play_slots")],
        [InlineKeyboardButton(text="🎲 Бросить Кости (100 руб)", callback_data="play_dice")],
        [InlineKeyboardButton(text="💣 Проверить Мины (🤖 WebApp)", callback_data="play_mines")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit_crypto")]
    ])

async def create_crypto_invoice(amount: int, order_id: str):
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "asset": "USDT",
        "amount": str(amount / 100),
        "payload": order_id
    }
    import aiohttp
    async with aiohttp.ClientSession() as session:
        is_test = "test" in CRYPTO_BOT_TOKEN.lower() or CRYPTO_BOT_TOKEN.startswith("T-")
        url = "https://crypt.bot" if is_test else "https://crypt.bot"
        async with session.post(url, json=payload, headers=headers) as resp:
            res = await resp.json()
            if res.get("ok") and res.get("result"):
                return res["result"]["pay_url"]
    return None

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in users_db:
        users_db[user_id] = 5000.00  # Дарим 5000 рублей для теста
        
    balance = users_db[user_id]
    await message.answer(
        f"🎰 **ДОБРО ПОЖАЛОВАТЬ В PREMIUM CASINO!** 🎰\n\n"
        f"💵 Ваш баланс: **{balance} руб.**\n\n"
        f"Выбирайте игру ниже и крутите удачу:", 
        parse_mode="Markdown", 
        reply_markup=get_main_keyboard()
    )

# ИГРА 1: АНИМИРОВАННЫЕ СЛОТЫ TELEGRAM
@dp.callback_query(F.data == "play_slots")
async def play_slots(callback: CallbackQuery):
    user_id = callback.from_user.id
    if users_db.get(user_id, 0) < 100:
        await callback.answer("❌ Недостаточно баланса! Пополните счет.", show_alert=True)
        return
        
    users_db[user_id] -= 100
    await callback.message.answer("🎰 Крутим барабаны...")
    
    msg = await bot.send_dice(chat_id=callback.message.chat.id, emoji="🎰")
    value = msg.dice.value
    
    await asyncio.sleep(4)  # Ждем завершения анимации
    
    # 1, 22, 43, 64 — это джекпоты в Telegram (три в ряд)
    if value in:
        win = 1000
        users_db[user_id] += win
        await callback.message.answer(
            f"🎉 **ВЫИГРЫШ! Три в ряд!** 🎉\n Начислено: +{win} руб.\nБаланс: {users_db[user_id]} руб.", 
            parse_mode="Markdown", 
            reply_markup=get_main_keyboard()
        )
    else:
        await callback.message.answer(f"😢 Не повезло. Попробуйте еще раз!\nБаланс: {users_db[user_id]} руб.", reply_markup=get_main_keyboard())

# ИГРА 2: ЖИВЫЕ КУБИКИ
@dp.callback_query(F.data == "play_dice")
async def play_dice(callback: CallbackQuery):
    user_id = callback.from_user.id
    if users_db.get(user_id, 0) < 100:
        await callback.answer("❌ Недостаточно баланса!", show_alert=True)
        return
        
    users_db[user_id] -= 100
    await callback.message.answer("🎲 Бросаем кости...")
    
    msg = await bot.send_dice(chat_id=callback.message.chat.id, emoji="🎲")
    value = msg.dice.value
    await asyncio.sleep(4)
    
    if value >= 4:
        win = 200
        users_db[user_id] += win
        await callback.message.answer(f" На кубике выпало {value}! **Вы выиграли!**\n Начислено: +{win} руб.", parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await callback.message.answer(f" На кубике выпало {value}. Проигрыш. Попробуйте снова!", reply_markup=get_main_keyboard())

# ИГРА 3: ВСТРОЕННЫЙ WEBAPP ДЛЯ МИН
@dp.callback_query(F.data == "play_mines")
async def play_mines(callback: CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💣 Открыть Минное Поле", web_app=web.WebAppInfo(url="https://netlify.app"))
    ]])
    await callback.message.answer(" Нажмите кнопку ниже, чтобы открыть графическое поле игры **Мины**:", reply_markup=kb)

# ПОПОЛНЕНИЕ БАЛАНСА
@dp.callback_query(F.data == "deposit_crypto")
async def process_deposit(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    order_id = str(uuid.uuid4())
    amount = 500
    payments_db[order_id] = {"user_id": user_id, "amount": amount, "status": "pending"}

    pay_url = await create_crypto_invoice(amount, order_id)
    if pay_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Оплатить через CryptoBot", url=pay_url)]])
        await callback.message.answer(f"Счет на 500 руб. создан.\nНажмите кнопку для оплаты:", reply_markup=kb)
    else:
        await callback.message.answer("❌ Ошибка платежки. Проверьте CRYPTO_BOT_TOKEN.")

async def handle_crypto_webhook(request):
    try:
        data = await request.json()
        if data.get("update_type") == "invoice_paid":
            payload = data["update_object"]["payload"]
            payment = payments_db.get(payload)
            if payment and payment['status'] == 'pending':
                payment['status'] = 'success'
                user_id = payment['user_id']
                users_db[user_id] = users_db.get(user_id, 0) + float(payment['amount'])
                await bot.send_message(chat_id=user_id, text="✅ Баланс успешно пополнен через CryptoBot!")
        return web.Response(text="OK", status=200)
    except Exception:
        return web.Response(text="Error", status=400)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    app = web.Application()
    app.router.add_post('/webhook/crypto', handle_crypto_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

