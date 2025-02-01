import asyncio
import datetime
import requests
import logging
import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO
from bs4 import BeautifulSoup  # для парсинга HTML
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup
from aiogram.utils import executor
from aiogram.dispatcher.middlewares import BaseMiddleware  # для реализации throttling
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher import DEFAULT_RATE_LIMIT, Dispatcher

# ===== Конфигурация =====
API_TOKEN = "tgtoken"  # Ваш основной токен
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
BANKI_URL = "https://www.banki.ru/products/currency/cash/izhevsk/"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ===== Throttling Middleware =====
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1):
        self.rate_limit = limit
        super().__init__()

    async def on_process_message(self, message: types.Message, data: dict):
        # Для каждой входящей команды будем проверять задержку
        user_id = message.from_user.id
        current = asyncio.get_event_loop().time()
        last_time = dp.storage.data.get(user_id, 0)
        if current - last_time < self.rate_limit:
            # Если сообщение пришло слишком рано, отменяем обработку
            raise CancelHandler()
        # Записываем время последнего сообщения от пользователя
        dp.storage.data[user_id] = current

# Инициализируем хранилище для throttling (простой dict)
dp.storage.data = {}

# Регистрируем middleware (лимит в 1 секунду на сообщение, можно изменить)
dp.middleware.setup(ThrottlingMiddleware(limit=1))

# ===== Хранилище данных =====
user_data = {}     # для данных конвертации
subscribers = set()  # ID подписанных пользователей
# Изменяем alerts: теперь для каждого пользователя может быть список будильников
alerts = {}  # { user_id: [ {"currency": ..., "target": ...}, ... ] }

logging.basicConfig(level=logging.INFO)

# ===== Главное меню =====
def main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = [
        "USD", "EUR", "JPY", "TRY", "RUB",
        "📊 Подписаться", "❌ Отписаться",
        "🔔 Установить будильник", "📉 График курса",
        "📊 Лучшие обменники в Ижевске",
        "📋 Мои будильники"  # Новая кнопка для просмотра будильников
    ]
    keyboard.add(*buttons)
    return keyboard

# ===== Команда /start =====
@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    user_data.pop(message.from_user.id, None)  # Очистка данных пользователя
    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=main_keyboard())

# ===== Конвертация валют =====
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

@dp.message_handler(lambda message: message.text.replace(".", "", 1).isdigit() and message.from_user.id in user_data)
async def amount_selected(message: Message):
    user_data[message.from_user.id]["amount"] = float(message.text)
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = ["USD", "EUR", "JPY", "TRY", "RUB"]
    keyboard.add(*buttons)
    await message.reply("Теперь выберите валюту, в которую хотите конвертировать:", reply_markup=keyboard)

async def convert_currency(message: Message):
    from_currency = user_data[message.from_user.id]["from_currency"]
    to_currency = user_data[message.from_user.id]["to_currency"]
    amount = user_data[message.from_user.id]["amount"]

    rates = get_exchange_rates()
    if not rates:
        await message.reply("❌ Ошибка при получении данных.", reply_markup=main_keyboard())
        return

    result = (amount * rates[from_currency]) / rates[to_currency]
    await message.reply(f"💱 {amount} {from_currency} = {result:.2f} {to_currency}", reply_markup=main_keyboard())
    user_data.pop(message.from_user.id, None)  # Очистка данных после конвертации

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

# ===== График курса за 7 дней =====
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
        except Exception:
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
    plt.close()
    await message.reply_photo(buf, reply_markup=main_keyboard())

# ===== Подписка и отписка =====
@dp.message_handler(lambda message: message.text == "📊 Подписаться")
async def subscribe_command(message: Message):
    subscribers.add(message.from_user.id)
    await message.reply("✅ Вы подписаны на ежедневные курсы валют!", reply_markup=main_keyboard())

@dp.message_handler(lambda message: message.text == "❌ Отписаться")
async def unsubscribe_command(message: Message):
    subscribers.discard(message.from_user.id)
    await message.reply("❌ Вы отписаны от ежедневных курсов.", reply_markup=main_keyboard())

# ===== Установка будильника =====
@dp.message_handler(lambda message: message.text == "🔔 Установить будильник")
async def alert_start(message: Message):
    await message.reply("Введите команду в формате: `/alert USD 100.50`", reply_markup=main_keyboard())

# ===== Установка будильника =====
@dp.message_handler(lambda message: message.text.lower().startswith("/alert"))
async def set_alert(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ Неправильный формат! Используйте: `/alert USD 100.50`", reply_markup=main_keyboard())
        return

    currency = parts[1].upper()
    allowed_currencies = ["USD", "EUR", "JPY", "TRY", "RUB"]
    if currency not in allowed_currencies:
        await message.reply(f"❌ Валюта {currency} не поддерживается. Доступны: {', '.join(allowed_currencies)}", reply_markup=main_keyboard())
        return

    try:
        target_price = float(parts[2])
        rates = get_exchange_rates()
        if not rates or currency not in rates:
            await message.reply("❌ Не удалось получить текущий курс. Попробуйте позже.", reply_markup=main_keyboard())
            return

        current_rate = rates[currency]
        # Определяем направление: если цель выше текущего курса — ждём роста, иначе — падения.
        if target_price > current_rate:
            direction = "up"
        else:
            direction = "down"

        user_id = message.from_user.id
        # Инициализируем список, если ранее для пользователя не было будильников
        if user_id not in alerts:
            alerts[user_id] = []
        alerts[user_id].append({
            "currency": currency,
            "target": target_price,
            "direction": direction
        })
        await message.reply(f"🔔 Будильник установлен: {currency} → {target_price} RUB (ожидаем {'роста' if direction=='up' else 'падения'})", reply_markup=main_keyboard())
    except ValueError:
        await message.reply("❌ Ошибка! Введите число, например: `/alert USD 100.50`", reply_markup=main_keyboard())

# ===== Функция просмотра установленных будильников =====
@dp.message_handler(commands=["myalerts"])
@dp.message_handler(lambda message: message.text == "📋 Мои будильники")
async def view_alerts(message: Message):
    user_id = message.from_user.id
    if user_id not in alerts or not alerts[user_id]:
        await message.reply("У вас нет установленных будильников.", reply_markup=main_keyboard())
        return

    text_lines = ["Ваши будильники:"]
    for idx, alert in enumerate(alerts[user_id], start=1):
        text_lines.append(f"{idx}. {alert['currency']} → {alert['target']} RUB")
    text_lines.append("\nЧтобы удалить будильник, используйте команду:\n`/delete_alert <номер>`")
    await message.reply("\n".join(text_lines), parse_mode="Markdown", reply_markup=main_keyboard())

# ===== Удаление будильника =====
@dp.message_handler(commands=["delete_alert"])
async def delete_alert(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Укажите номер будильника для удаления, например: `/delete_alert 1`", reply_markup=main_keyboard())
        return

    try:
        index = int(parts[1]) - 1
        user_id = message.from_user.id
        if user_id not in alerts or index < 0 or index >= len(alerts[user_id]):
            await message.reply("❌ Будильник с таким номером не найден.", reply_markup=main_keyboard())
            return

        removed = alerts[user_id].pop(index)
        await message.reply(f"✅ Будильник {removed['currency']} → {removed['target']} RUB удалён.", reply_markup=main_keyboard())
    except ValueError:
        await message.reply("❌ Неверный формат номера. Используйте: `/delete_alert 1`", reply_markup=main_keyboard())

# ===== Фоновая рассылка и проверка будильников =====
async def daily_exchange_rates():
    while True:
        await asyncio.sleep(86400)  # 24 часа
        rates = get_exchange_rates()
        if subscribers and rates:
            text = "📊 **Курсы валют на сегодня:**\n" + "\n".join(f"💰 {c}: {v:.2f} RUB" for c, v in rates.items())
            for user_id in subscribers:
                try:
                    await bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_keyboard())
                except Exception as e:
                    logging.error(f"Ошибка при отправке подписчику {user_id}: {e}")

async def check_alerts():
    while True:
        await asyncio.sleep(300)  # каждые 5 минут
        rates = get_exchange_rates()
        if not rates:
            continue
        # Создаем копию alerts для безопасной итерации
        for user_id, user_alerts in list(alerts.items()):
            new_alerts = []
            for alert in user_alerts:
                curr_rate = rates.get(alert["currency"])
                if curr_rate is None:
                    new_alerts.append(alert)
                    continue

                # Проверяем в зависимости от направления
                if alert["direction"] == "up":
                    # Ожидаем роста: срабатываем, если курс стал >= цели
                    if curr_rate >= alert["target"]:
                        try:
                            await bot.send_message(user_id, f"🚀 {alert['currency']} достиг {alert['target']} RUB!", reply_markup=main_keyboard())
                        except Exception as e:
                            logging.error(f"Ошибка отправки alert для {user_id}: {e}")
                        continue  # не добавляем сработавший alert в новый список
                else:
                    # Ожидаем падения: срабатываем, если курс стал <= цели
                    if curr_rate <= alert["target"]:
                        try:
                            await bot.send_message(user_id, f"🚀 {alert['currency']} достиг {alert['target']} RUB!", reply_markup=main_keyboard())
                        except Exception as e:
                            logging.error(f"Ошибка отправки alert для {user_id}: {e}")
                        continue  # не добавляем сработавший alert в новый список

                new_alerts.append(alert)
            if new_alerts:
                alerts[user_id] = new_alerts
            else:
                alerts.pop(user_id)


# ===== Функциональность «Лучшие обменники» (интеграция из первого кода) =====
def get_best_exchange_rates():
    response = requests.get(BANKI_URL)
    soup = BeautifulSoup(response.text, 'html.parser')
    banks = []
    
    # Ищем нужные элементы с данными
    for item in soup.find_all('div', {'data-test': 'currency__rates-form__result-item'}):
        name_elem = item.find('div', {'data-test': 'currenct--result-item--name'})
        if not name_elem:
            continue
        name = name_elem.text.strip()
        buy_elem = item.find('div', {'data-test': 'currency--result-item---rate-buy'})
        sell_elem = item.find('div', {'data-test': 'currency--result-item---rate-sell'})
        if buy_elem and sell_elem:
            buy_divs = buy_elem.find_all('div')
            sell_divs = sell_elem.find_all('div')
            if buy_divs and sell_divs:
                try:
                    buy = float(buy_divs[-1].text.strip().replace('₽', '').replace(',', '.'))
                    sell = float(sell_divs[-1].text.strip().replace('₽', '').replace(',', '.'))
                    banks.append((name, buy, sell))
                except Exception:
                    continue
    # Сортируем по курсу покупки (от большего к меньшему)
    return sorted(banks, key=lambda x: x[1], reverse=True)

async def best_rates(message: Message):
    banks = get_best_exchange_rates()
    if not banks:
        await message.reply("Не удалось получить данные о курсах валют.", reply_markup=main_keyboard())
        return

    banks = banks[:10]  # Берём топ-10
    names = [bank[0] for bank in banks]
    buy_rates = [bank[1] for bank in banks]
    sell_rates = [bank[2] for bank in banks]

    y = np.arange(len(names))
    width = 0.4  # Ширина столбцов

    plt.figure(figsize=(12, 6))
    plt.barh(y - width/2, buy_rates, width, color='green', label='Покупка')
    plt.barh(y + width/2, sell_rates, width, color='red', label='Продажа')

    plt.yticks(y, names)
    plt.xlabel('Курс (₽)')
    plt.ylabel('Банки')
    plt.title('Лучшие курсы обмена в Ижевске')
    plt.legend()
    plt.grid(axis='x')

    for i, (buy, sell) in enumerate(zip(buy_rates, sell_rates)):
        plt.text(buy + 0.5, i - width/2, f'{buy:.2f}₽', va='center', fontsize=10)
        plt.text(sell + 0.5, i + width/2, f'{sell:.2f}₽', va='center', fontsize=10)

    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    await message.reply_photo(buf, reply_markup=main_keyboard())

# Обработчик для команды /best_rates (если потребуется)
@dp.message_handler(commands=['best_rates'])
async def best_rates_command(message: Message):
    await best_rates(message)

# Обработчик для нажатия кнопки «📊 Лучшие обменники»
@dp.message_handler(lambda message: message.text == "📊 Лучшие обменники в Ижевске")
async def best_rates_handler(message: Message):
    await best_rates(message)

# ===== Фоновые задачи =====
async def on_startup(_):
    asyncio.create_task(daily_exchange_rates())
    asyncio.create_task(check_alerts())

# ===== Запуск бота =====
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
