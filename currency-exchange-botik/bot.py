from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Укажите токен вашего бота
API_TOKEN = "YOUR_TELEGRAM_BOT_API_KEY"  # Замените на ваш токен

# Создаём экземпляры бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Команда /start
@dp.message_handler(commands=["start"])
async def start_command(message: types.Message):
    # Создаём клавиатуру с валютами
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = ["USD", "EUR", "JPY", "TRY", "RUB"]
    keyboard.add(*buttons)
    
    await message.answer("Добро пожаловать! Выберите валюту:", reply_markup=keyboard)

# Обработка выбора валюты
@dp.message_handler(lambda message: message.text in ["USD", "EUR", "JPY", "TRY", "RUB"])
async def currency_selected(message: types.Message):
    selected_currency = message.text
    await message.reply(f"Вы выбрали {selected_currency}. Введите сумму для конвертации:")

# Запуск бота
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
