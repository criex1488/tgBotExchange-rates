import asyncio
import datetime
import logging
import time
from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup
from aiogram.utils import executor
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ===== Конфигурация =====
API_TOKEN = "tgtoken"
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
BANKI_URL = "https://www.banki.ru/products/currency/cash/izhevsk/"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ===== Throttling Middleware (ограничение на скорость для всех сообщений) =====
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1):
        self.rate_limit = limit
        super().__init__()

    async def on_process_message(self, message: types.Message, data: dict):
        user_id = message.from_user.id
        current = asyncio.get_event_loop().time()
        last_time = dp.storage.data.get(user_id, 0)
        if current - last_time < self.rate_limit:
            try:
                await message.reply("Вы слишком быстро отправляете сообщения, пожалуйста, подождите.")
            except Exception as e:
                logging.error(f"Ошибка отправки уведомления: {e}")
            raise CancelHandler()
        dp.storage.data[user_id] = current


dp.storage.data = {}
dp.middleware.setup(ThrottlingMiddleware(limit=1))

# ===== Хранилище данных =====
user_data = {}       # Для состояния конвертации
subscribers = set()  # ID подписанных пользователей
alerts = {}          # Будильники

logging.basicConfig(level=logging.INFO)

# ===== Главное меню =====
def main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = [
        "USD", "EUR", "JPY", "TRY", "RUB",
        "📊 Подписаться", "❌ Отписаться",
        "🔔 Установить будильник", "📉 График курса",
        "📊 Лучшие обменники в Ижевске",
        "📋 Мои будильники"
    ]
    keyboard.add(*buttons)
    return keyboard

# ===== Команда /start =====
@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    user_data.pop(message.from_user.id, None)
    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=main_keyboard())

# ===== Конвертация валют =====
@dp.message_handler(lambda message: message.text in ["USD", "EUR", "JPY", "TRY", "RUB"])
async def currency_selected(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}
    if "amount" in user_data[user_id]:
        if user_data[user_id].get("from_currency") == message.text:
            await message.reply("❌ Валюта для конвертации должна отличаться от исходной. Выберите другую валюту:")
            return
        user_data[user_id]["to_currency"] = message.text
        await convert_currency(message)
    else:
        user_data[user_id]["from_currency"] = message.text
        await message.reply(f"Вы выбрали {message.text}. Введите сумму для конвертации:")

def is_number(text: str) -> bool:
    try:
        float(text.replace(',', '.'))
        return True
    except ValueError:
        return False

@dp.message_handler(lambda message: (
    message.from_user.id in user_data and 
    "from_currency" in user_data[message.from_user.id] and 
    "amount" not in user_data[message.from_user.id] and 
    is_number(message.text)
))
async def amount_selected(message: Message):
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.reply("❌ Неверный формат суммы!", reply_markup=main_keyboard())
        return
    if amount <= 0:
        user_data.pop(message.from_user.id, None)
        await message.reply("❌ Сумма должна быть положительной!", reply_markup=main_keyboard())
        return
    if amount < 0.01:
        user_data.pop(message.from_user.id, None)
        await message.reply("❌ Сумма должна быть не меньше 0.01!", reply_markup=main_keyboard())
        return
    if amount > 1_000_000_000:
        user_data.pop(message.from_user.id, None)
        await message.reply("❌ Слишком большая сумма. Введите сумму меньше 1,000,000,000.", reply_markup=main_keyboard())
        return
    user_data[message.from_user.id]["amount"] = amount
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
    if 0 < result < 0.01:
        result_str = f"{result:.6f}"
    else:
        result_str = f"{result:.2f}"
    await message.reply(f"💱 {amount} {from_currency} = {result_str} {to_currency}", reply_markup=main_keyboard())
    user_data.pop(message.from_user.id, None)

def get_exchange_rates():
    try:
        import requests
        response = requests.get(CBR_API_URL)
        response.raise_for_status()
        data = response.json()
        rates = {
            "USD": data["Valute"]["USD"]["Value"],
            "EUR": data["Valute"]["EUR"]["Value"],
            "JPY": data["Valute"]["JPY"]["Value"] / 100,
            "TRY": data["Valute"]["TRY"]["Value"],
            "RUB": 1.0
        }
        return rates
    except Exception as e:
        logging.error(f"Ошибка получения курсов: {e}")
        return None

# ===== График курса (USD к RUB) с защитой от спама =====
# Для защиты от спама для команды "График курса" используем отдельные словари:
graph_currency_lock = {}         # Для каждого пользователя: объект asyncio.Lock
graph_currency_last_time = {}      # Время последнего запроса по user_id
GRAPH_CURRENCY_COOLDOWN = 30       # Интервал в секундах между запросами от одного пользователя

def generate_currency_graph():
    """
    Функция выполняет запросы к API ЦБ и строит график курса USD к RUB за последние 7 дней.
    Возвращает изображение графика в виде байтов.
    """
    currency = "USD"
    today = datetime.date.today()
    dates = []
    values = []
    for i in range(7):
        date = today - datetime.timedelta(days=i)
        date_str = date.strftime("%Y/%m/%d")
        url = f"https://www.cbr-xml-daily.ru/archive/{date_str}/daily_json.js"
        try:
            import requests
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if currency in data["Valute"]:
                    dates.append(date.strftime("%d.%m"))
                    values.append(data["Valute"][currency]["Value"])
        except Exception:
            continue

    if len(dates) < 2:
        raise Exception("Недостаточно данных для графика.")
        
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
    return buf.getvalue()

@dp.message_handler(lambda message: message.text == "📉 График курса")
async def send_currency_graph(message: Message):
    user_id = message.from_user.id
    current_time = asyncio.get_event_loop().time()

    # Если пользователь отправил запрос слишком недавно, отказываем
    if user_id in graph_currency_last_time and (current_time - graph_currency_last_time[user_id] < GRAPH_CURRENCY_COOLDOWN):
        await message.reply("Слишком быстро отправляете запросы. Пожалуйста, подождите немного.")
        return
    graph_currency_last_time[user_id] = current_time

    # Если для пользователя ещё нет lock – создаём его
    if user_id not in graph_currency_lock:
        graph_currency_lock[user_id] = asyncio.Lock()
    lock = graph_currency_lock[user_id]

    # Если уже идёт обработка запроса, сразу сообщаем об этом
    if lock.locked():
        await message.reply("Ваш запрос уже в обработке. Пожалуйста, подождите.")
        return

    async with lock:
        try:
            loop = asyncio.get_event_loop()
            # Выполняем тяжёлую операцию в пуле потоков
            image_bytes = await loop.run_in_executor(None, generate_currency_graph)
        except Exception as e:
            logging.error(f"Ошибка генерации графика: {e}")
            await message.reply("❌ Не удалось получить данные для графика.", reply_markup=main_keyboard())
            return
        await message.reply_photo(image_bytes, reply_markup=main_keyboard())

# ===== Подписка =====
@dp.message_handler(lambda message: message.text == "📊 Подписаться")
async def subscribe_command(message: Message):
    subscribers.add(message.from_user.id)
    await message.reply("✅ Вы подписаны на ежедневные курсы валют!", reply_markup=main_keyboard())

@dp.message_handler(lambda message: message.text == "❌ Отписаться")
async def unsubscribe_command(message: Message):
    subscribers.discard(message.from_user.id)
    await message.reply("❌ Вы отписаны от ежедневных курсов.", reply_markup=main_keyboard())

# ===== Будильники =====
@dp.message_handler(lambda message: message.text == "🔔 Установить будильник")
async def alert_start(message: Message):
    await message.reply("Введите команду в формате: `/alert USD 100.50`", reply_markup=main_keyboard())

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
        direction = "up" if target_price > current_rate else "down"
        user_id = message.from_user.id
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

# ===== Фоновые задачи =====
async def daily_exchange_rates():
    while True:
        await asyncio.sleep(86400)
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
        await asyncio.sleep(300)
        rates = get_exchange_rates()
        if not rates:
            continue
        for user_id, user_alerts in list(alerts.items()):
            new_alerts = []
            for alert in user_alerts:
                curr_rate = rates.get(alert["currency"])
                if curr_rate is None:
                    new_alerts.append(alert)
                    continue
                if alert["direction"] == "up" and curr_rate >= alert["target"]:
                    try:
                        await bot.send_message(user_id, f"🚀 {alert['currency']} достиг {alert['target']} RUB!", reply_markup=main_keyboard())
                    except Exception as e:
                        logging.error(f"Ошибка отправки alert для {user_id}: {e}")
                    continue
                elif alert["direction"] == "down" and curr_rate <= alert["target"]:
                    try:
                        await bot.send_message(user_id, f"🚀 {alert['currency']} достиг {alert['target']} RUB!", reply_markup=main_keyboard())
                    except Exception as e:
                        logging.error(f"Ошибка отправки alert для {user_id}: {e}")
                    continue
                new_alerts.append(alert)
            if new_alerts:
                alerts[user_id] = new_alerts
            else:
                alerts.pop(user_id)

# ===== Кэширование данных лучших обменников =====
best_rates_cache = {
    "timestamp": 0,
    "data": None
}
CACHE_DURATION = 300  # 5 минут

def get_best_exchange_rates_selenium(force_update: bool = False):
    """
    Если force_update==False, то если данные в кэше не устарели, возвращаем их.
    Иначе запускаем Selenium и обновляем кэш.
    """
    global best_rates_cache
    current_time = time.time()
    if (not force_update and best_rates_cache["data"] is not None and
            (current_time - best_rates_cache["timestamp"] < CACHE_DURATION)):
        logging.info("Используем закэшированные данные для обменников.")
        return best_rates_cache["data"]

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    
    driver.get(BANKI_URL)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-test='currency__rates-form__result-item']"))
        )
    except Exception as e:
        logging.error(f"Timeout или ошибка ожидания: {e}")
        driver.quit()
        return []
    
    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, 'html.parser')
    banks = []
    items = soup.find_all('div', {'data-test': 'currency__rates-form__result-item'})
    logging.info(f"Найдено элементов с курсами: {len(items)}")
    for item in items:
        name_elem = item.find('div', {'data-test': 'currenct--result-item--name'})
        if not name_elem:
            continue
        name = name_elem.text.strip()

        buy_elem = item.find('div', {'data-test': 'currency--result-item---rate-buy'})
        sell_elem = item.find('div', {'data-test': 'currency--result-item---rate-sell'})
        if not (buy_elem and sell_elem):
            continue

        buy_divs = buy_elem.find_all('div')
        sell_divs = sell_elem.find_all('div')
        if not (buy_divs and sell_divs):
            continue

        try:
            buy_str = buy_divs[-1].text.strip().replace('₽', '').replace(',', '.')
            sell_str = sell_divs[-1].text.strip().replace('₽', '').replace(',', '.')
            buy = float(buy_str)
            sell = float(sell_str)
        except Exception as e:
            logging.error(f"Ошибка парсинга курсов для банка {name}: {e}")
            continue

        refresh_elem = item.find('div', {'data-test': 'currency--result-item--refresh-date'})
        refresh_text = refresh_elem.text.strip() if refresh_elem else ""

        banks.append((name, buy, sell, refresh_text))
    
    best_rates_cache["timestamp"] = current_time
    best_rates_cache["data"] = sorted(banks, key=lambda x: x[1], reverse=True)
    logging.info("Данные лучших обменников обновлены и сохранены в кэш.")
    return best_rates_cache["data"]

async def best_rates_cache_refresher():
    """
    Фоновый таск, который каждые CACHE_DURATION секунд обновляет кэш данных лучших обменников.
    """
    while True:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: get_best_exchange_rates_selenium(force_update=True))
        except Exception as e:
            logging.error(f"Ошибка обновления кэша лучших обменников: {e}")
        await asyncio.sleep(CACHE_DURATION)

# ===== Защита от спама для команды "Лучшие обменники" =====
# (аналогично "График курса" – для каждого пользователя разрешаем один запрос за заданный интервал)
graph_generation_lock = {}         # Для каждого пользователя: объект asyncio.Lock
graph_generation_last_time = {}      # Время последнего запроса по user_id
GRAPH_GENERATION_COOLDOWN = 30       # Интервал в секундах между запросами

def generate_chart(banks):
    """
    Генерирует график лучших обменников с использованием Matplotlib и возвращает изображение в виде байтов.
    """
    names = [bank[0] for bank in banks]
    buy_rates = [bank[1] for bank in banks]
    sell_rates = [bank[2] for bank in banks]
    refresh_texts = [bank[3] for bank in banks]

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

    for i, (buy, sell, refresh) in enumerate(zip(buy_rates, sell_rates, refresh_texts)):
        plt.text(buy + 0.5, i - width/2, f'{buy:.2f}₽', va='center', fontsize=10, color='black')
        plt.text(sell + 0.5, i + width/2, f'{sell:.2f}₽', va='center', fontsize=10, color='black')
        if refresh:
            if buy >= sell:
                x_center = buy / 2
                y_center = i - width/2
            else:
                x_center = sell / 2
                y_center = i + width/2
            plt.text(x_center, y_center, refresh, va='center', ha='center', fontsize=8, 
                     color='white', weight='bold')

    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf.getvalue()

@dp.message_handler(commands=['best_rates'])
@dp.message_handler(lambda message: message.text == "📊 Лучшие обменники в Ижевске")
async def best_rates_handler(message: Message):
    user_id = message.from_user.id
    current_time = asyncio.get_event_loop().time()

    if user_id in graph_generation_last_time and (current_time - graph_generation_last_time[user_id] < GRAPH_GENERATION_COOLDOWN):
        await message.reply("Слишком быстро отправляете запросы. Пожалуйста, подождите немного.")
        return
    graph_generation_last_time[user_id] = current_time

    if user_id not in graph_generation_lock:
        graph_generation_lock[user_id] = asyncio.Lock()
    lock = graph_generation_lock[user_id]

    if lock.locked():
        await message.reply("Ваш запрос уже в обработке. Пожалуйста, подождите.")
        return

    async with lock:
        if best_rates_cache["data"] is None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: get_best_exchange_rates_selenium(force_update=True))
        
        banks = best_rates_cache["data"]
        if not banks:
            await message.reply("Не удалось получить данные о курсах валют.", reply_markup=main_keyboard())
            return

        banks = banks[:10]  # Берем топ-10
        loop = asyncio.get_event_loop()
        image_bytes = await loop.run_in_executor(None, generate_chart, banks)
        await message.reply_photo(image_bytes, reply_markup=main_keyboard())

# ===== on_startup: предзагрузка кэша и запуск фоновых задач =====
async def on_startup(_):
    loop = asyncio.get_event_loop()
    # Предзагружаем кэш лучших обменников
    await loop.run_in_executor(None, lambda: get_best_exchange_rates_selenium(force_update=True))
    # Запускаем фоновые таски
    asyncio.create_task(best_rates_cache_refresher())
    asyncio.create_task(daily_exchange_rates())
    asyncio.create_task(check_alerts())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
