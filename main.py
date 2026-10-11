import asyncio
import logging
import os
import uuid
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, WebAppInfo

logging.basicConfig(level=logging.INFO)

# Ключи берутся автоматически из настроек Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище прямо в памяти сервера (балансы и платежи)
users_db = {}     
payments_db = {}  

# Главная меню-клавиатура с сочными играми
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 МИНЫ (Сочная WebApp Графика) 💥", web_app=WebAppInfo(url="https://minesweeper-game.netlify.app"))],
        [InlineKeyboardButton(text="🎰 Крутить Слоты (100 руб)", callback_data="play_slots")],
        [InlineKeyboardButton(text="🎲 Бросить Кости (100 руб)", callback_data="play_dice")],
        [InlineKeyboardButton(text="💰 Пополнить баланс через CryptoBot", callback_data="deposit_crypto")]
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
        users_db[user_id] = 5000.00  # Дарим 5000 рублей каждому игроку для теста
        
    balance = users_db[user_id]
    await message.answer(
        f"🎰 **ДОБРО ПОЖАЛОВАТЬ В PREMIUM CASINO!** 🎰\n\n"
        f"💵 Ваш текущий баланс: **{balance} руб.**\n\n"
        f"Нажмите кнопку ниже, чтобы открыть сочную графическую игру или испытать удачу в классических слотах:", 
        parse_mode="Markdown", 
        reply_markup=get_main_keyboard()
    )

# ИГРА: АНИМИРОВАННЫЕ СЛОТЫ TELEGRAM
@dp.callback_query(F.data == "play_slots")
async def play_slots(callback: CallbackQuery):
    user_id = callback.from_user.id
    if users_db.get(user_id, 0) < 100:
        await callback.answer("❌ Недостаточно баланса для ставки!", show_alert=True)
        return
        
    users_db[user_id] -= 100
    await callback.message.answer("🎰 Барабаны вращаются...")
    
    msg = await bot.send_dice(chat_id=callback.message.chat.id, emoji="🎰")
    value = msg.dice.value
    
    await asyncio.sleep(4)  # Ожидание окончания прокрутки
    
    # Исправленное синтаксическое условие комбинаций (1, 22, 43, 64)
    if value in [1, 22, 43, 64]:
        win = 2500
        users_db[user_id] += win
        await callback.message.answer(f"🎉 **💥 ДЖЕКПОТ! ТРИ В РЯД! 💥** 🎉\n\nВы выиграли: +**{win} руб.**\nНовый баланс: **{users_db[user_id]} руб.**", parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await callback.message.answer(f"😢 Мимо! Попробуйте еще раз.\nВаш баланс: **{users_db[user_id]} руб.**", parse_mode="Markdown", reply_markup=get_main_keyboard())

# ИГРА: КУБИКИ
@dp.callback_query(F.data == "play_dice")
async def play_dice(callback: CallbackQuery):
    user_id = callback.from_user.id
    if users_db.get(user_id, 0) < 100:
        await callback.answer("❌ Недостаточно баланса!", show_alert=True)
        return
        
    users_db[user_id] -= 100
    await callback.message.answer("🎲 Кости брошены...")
    
    msg = await bot.send_dice(chat_id=callback.message.chat.id, emoji="🎲")
    value = msg.dice.value
    await asyncio.sleep(4)
    
    if value >= 4:
        win = 200
        users_db[user_id] += win
        await callback.message.answer(f" На кубике выпало {value}! **Победа!**\nВы выиграли: +**{win} руб.**", parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await callback.message.answer(f" На кубике выпало {value}. Проигрыш. Баланс: **{users_db[user_id]} руб.**", parse_mode="Markdown", reply_markup=get_main_keyboard())

# ОПЛАТА КРИПТОЙ
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
        await callback.message.answer(f"Счет на пополнение (500 руб.) успешно создан.\nНажмите кнопку для оплаты:", reply_markup=kb)
    else:
        await callback.message.answer("❌ Ошибка генерации счета. Проверьте ваш токен CRYPTO_BOT_TOKEN на Render.")

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
