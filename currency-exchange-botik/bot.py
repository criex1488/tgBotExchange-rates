import asyncio
import datetime
import requests
import logging
import matplotlib.pyplot as plt
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup
from aiogram.utils import executor

API_TOKEN = "tgtoken"
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Хранилище данных
user_data = {}  # Для текущих конвертаций
subscribers = set()  # ID подписанных пользователей
alerts = {}  # Автоуведомления

logging.basicConfig(level=logging.INFO)

# 📌 Главное меню
def main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = [
        "USD", "EUR", "JPY", "TRY", "RUB",
        "📊 Подписаться", "❌ Отписаться",
        "🔔 Установить будильник", "📉 График курса"
    ]
    keyboard.add(*buttons)
    return keyboard

# 📌 Команда /start
@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    user_data.pop(message.from_user.id, None)  # Очистка данных пользователя
    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=main_keyboard())

# 📌 Выбор валюты
@dp.message_handler(lambda message: message.text in ["USD", "EUR", "JPY", "TRY", "RUB"])
async def currency_selected(message: Message):
    if message.from_user.id not in user_data:
        user_data[message.from_user.id] = {}

    if "amount" in user_data[message.from_user.id]:
        user_data[message.from_user.id]["to_currency"] = message.text
        await convert_currency(message)
    else:
        user_data[message.from_user.id]["from_currency"] = message.text
        await message.reply(f"Вы выбрали {message.text}. Введите сумму для конвертации:")

# 📌 Ввод суммы
@dp.message_handler(lambda message: message.text.replace(".", "", 1).isdigit() and message.from_user.id in user_data)
async def amount_selected(message: Message):
    user_data[message.from_user.id]["amount"] = float(message.text)

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = ["USD", "EUR", "JPY", "TRY", "RUB"]
    keyboard.add(*buttons)

    await message.reply("Теперь выберите валюту, в которую хотите конвертировать:", reply_markup=keyboard)

# 📌 Конвертация валюты
async def convert_currency(message: Message):
    from_currency = user_data[message.from_user.id]["from_currency"]
    to_currency = user_data[message.from_user.id]["to_currency"]
    amount = user_data[message.from_user.id]["amount"]

    rates = get_exchange_rates()
    if not rates:
        await message.reply("❌ Ошибка при получении данных.")
        return

    result = (amount * rates[from_currency]) / rates[to_currency]
    await message.reply(f"💱 {amount} {from_currency} = {result:.2f} {to_currency}", reply_markup=main_keyboard())

    user_data.pop(message.from_user.id, None)  # Очистка данных после конвертации

# 📌 Получение курсов
def get_exchange_rates():
    try:
        response = requests.get(CBR_API_URL)
        response.raise_for_status()
        data = response.json()

        rates = {
            "USD": data["Valute"]["USD"]["Value"],
            "EUR": data["Valute"]["EUR"]["Value"],
            "JPY": data["Valute"]["JPY"]["Value"] / 100,  # Курс за 100 JPY
            "TRY": data["Valute"]["TRY"]["Value"],
            "RUB": 1.0
        }
        return rates
    except requests.RequestException:
        return None

# 📌 График курса за 7 дней
@dp.message_handler(lambda message: message.text == "📉 График курса")
async def send_currency_graph(message: Message):
    currency = user_data.get(message.from_user.id, {}).get("from_currency", "USD")

    today = datetime.date.today()
    dates = []
    values = []

    for i in range(7):  # Последние 7 дней
        date = today - datetime.timedelta(days=i)
        date_str = date.strftime("%Y/%m/%d")
        url = f"https://www.cbr-xml-daily.ru/archive/{date_str}/daily_json.js"

        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if currency in data["Valute"]:
                    dates.append(date.strftime("%d.%m"))
                    values.append(data["Valute"][currency]["Value"])
        except:
            continue

    if len(dates) < 2:
        await message.reply("❌ Не удалось получить данные для графика.", reply_markup=main_keyboard())
        return

    plt.figure(figsize=(8, 4))
    plt.plot(dates[::-1], values[::-1], marker="o", linestyle="-", label=f"{currency} к RUB")
    plt.xlabel("Дата")
    plt.ylabel("Курс")
    plt.title(f"📉 График курса {currency} к RUB")
    plt.legend()
    plt.grid(True)

    buf = BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    await message.reply_photo(buf, reply_markup=main_keyboard())

# 📌 Подписка
@dp.message_handler(lambda message: message.text == "📊 Подписаться")
async def subscribe_command(message: Message):
    subscribers.add(message.from_user.id)
    await message.reply("✅ Вы подписаны на ежедневные курсы валют!", reply_markup=main_keyboard())

@dp.message_handler(lambda message: message.text == "❌ Отписаться")
async def unsubscribe_command(message: Message):
    subscribers.discard(message.from_user.id)
    await message.reply("❌ Вы отписаны от ежедневных курсов.", reply_markup=main_keyboard())

# 📌 Автоуведомления
@dp.message_handler(lambda message: message.text == "🔔 Установить будильник")
async def alert_start(message: Message):
    await message.reply("Введите команду в формате: `/alert USD 100.50`", reply_markup=main_keyboard())

@dp.message_handler(lambda message: message.text.startswith("/alert"))
async def set_alert(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ Неправильный формат! Используйте: `/alert USD 100.50`", reply_markup=main_keyboard())
        return

    currency = parts[1].upper()
    try:
        target_price = float(parts[2])
        alerts[message.from_user.id] = {"currency": currency, "target": target_price}
        await message.reply(f"🔔 Будильник установлен: {currency} → {target_price} RUB", reply_markup=main_keyboard())
    except ValueError:
        await message.reply("❌ Ошибка! Введите число, например: `/alert USD 100.50`", reply_markup=main_keyboard())

# 📌 Фоновые задачи
async def daily_exchange_rates():
    while True:
        await asyncio.sleep(86400)
        rates = get_exchange_rates()
        if subscribers and rates:
            text = "📊 **Курсы валют на сегодня:**\n" + "\n".join(f"💰 {c}: {v:.2f} RUB" for c, v in rates.items())
            for user_id in subscribers:
                await bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_keyboard())

async def check_alerts():
    while True:
        await asyncio.sleep(300)
        rates = get_exchange_rates()
        for user_id, alert in alerts.items():
            if rates[alert["currency"]] >= alert["target"]:
                await bot.send_message(user_id, f"🚀 {alert['currency']} достиг {alert['target']} RUB!", reply_markup=main_keyboard())

async def on_startup(_):
    asyncio.create_task(daily_exchange_rates())
    asyncio.create_task(check_alerts())

executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
