from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
import requests

API_TOKEN = "tgtoken"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = ["USD", "EUR", "JPY", "TRY", "RUB", "Узнать курс валют", "Узнать выгодные обменники в Ижевске"]
    keyboard.add(*buttons)

    await message.answer(
        "Добро пожаловать! Я—бот для курса валют. Выбери в кнопках интересующую валюту.",
        reply_markup=keyboard
    )

@dp.message_handler(lambda message: message.text in ["USD", "EUR", "JPY", "TRY", "RUB"])
async def currency_selected(message: Message):
    selected_currency = message.text
    await message.reply(f"Вы выбрали {selected_currency}. Введите сумму для конвертации:")

@dp.message_handler(lambda message: message.text == "Узнать курс валют")
async def ask_for_amount(message: Message):
    await message.reply("Введите сумму для получения актуального курса валют:")

@dp.message_handler(lambda message: message.text.isdigit())
async def get_exchange_rates(message: Message):
    amount = float(message.text)

    try:
        response = requests.get("https://api.exchangerate-api.com/v4/latest/USD")
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        await message.reply("Ошибка при получении данных. Попробуйте позже.")
        return

    rates = {}
    for currency in ["USD", "EUR", "JPY", "TRY", "RUB"]:
        if currency in data['rates']:
            rates[currency] = data['rates'][currency] * amount

    rates_message = "Актуальный курс валют на текущий период:\n"
    for currency, converted_amount in rates.items():
        rates_message += f"{currency}: {converted_amount:.2f}\n"

    await message.reply(rates_message)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
