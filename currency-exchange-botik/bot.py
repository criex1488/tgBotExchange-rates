import asyncio
import datetime
import logging
import time
from io import BytesIO

import matplotlib.pyplot as plt
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup
from aiogram.utils import executor
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler

# ===== Конфигурация =====
API_TOKEN = "tgtoken"
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
BANKI_API_URL = (
    "https://www.banki.ru/products/currencyNodejsApi/getBanksOrExchanges/"
    "?currencyId=840&regionUrl=izhevsk&amount=100&latitude=56.852775&longitude=53.211463"
    "&isExchangeOffices=1&sortAttribute=buy&order=desc&page=1&pagePath=currencyCashCity"
)

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

# ===== Глобальные переменные =====
user_data = {}       # Для состояния конвертации
subscribers = set()  # ID подписанных пользователей
alerts = {}          # Будильники

logging.basicConfig(level=logging.INFO)

# ===== Главное меню =====
def main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = [
        "USD", "EUR", "JPY", "TRY", "RUB", "AED",
        "📊 Подписаться", "❌ Отписаться",
        "🔔 Установить будильник", "📉 График курса",
        "📊 Лучшие обменники в Ижевске",
        "📋 Мои будильники"
    ]
    keyboard.add(*buttons)
    return keyboard

# ===== Приветствие (/start) =====
@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    user_data.pop(message.from_user.id, None)
    welcome_text = (
        "👋 Добро пожаловать в бота для валютных конвертаций и поиска лучших обменников!\n\n"
        "Функциональные возможности:\n"
        "• Конвертация валют по актуальным курсам.\n"
        "• Отображение графика курса USD к RUB за последние 7 дней (текстовая история и график).\n"
        "• Поиск лучших обменников в Ижевске с объединением адресов (каждый адрес на новой строке и кликабельный).\n"
        "• Установка будильников для оповещения об изменении курса (срабатывает, когда курс становится выше или ниже заданного значения).\n"
        "• Ежедневная рассылка обновлённых курсов для подписанных пользователей.\n"
        "github: https://github.com/criex1488/tgBotExchange-rates (all source code)\n\n"
        "Выберите нужное действие из меню ниже:"
    )
    await message.answer(welcome_text, reply_markup=main_keyboard())

# ===== Конвертация валют =====
@dp.message_handler(lambda message: message.text in ["USD", "EUR", "JPY", "TRY", "RUB", "AED"])
async def currency_selected(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}
    # Если уже введена сумма, проверяем, чтобы выбранная валюта не совпадала с исходной
    if "amount" in user_data[user_id]:
        if user_data[user_id].get("from_currency") == message.text:
            await message.reply("❌ Валюта для конвертации должна отличаться от исходной. Выберите другую валюту:")
            return
        user_data[user_id]["to_currency"] = message.text
        await convert_currency(user_id, message)
    else:
        user_data[user_id]["from_currency"] = message.text
        await message.reply(f"Вы выбрали {message.text}. Введите сумму для конвертации:")

def is_number(text: str) -> bool:
    try:
        float(text.replace(',', '.'))
        return True
    except ValueError:
        return False

@dp.message_handler(lambda message: message.from_user.id in user_data 
                    and "from_currency" in user_data[message.from_user.id] 
                    and "amount" not in user_data[message.from_user.id])
async def amount_selected(message: Message):
    t = message.text.replace(',', '.')
    try:
        float(t)
    except ValueError:
        await message.reply("❌ Неверный формат суммы!", reply_markup=main_keyboard())
        return

    if '.' in t:
        _, fraction = t.split('.', 1)
        if len(fraction) > 2:
            await message.reply("❌ Слишком много цифр после десятичной точки. Максимум 2 цифры допустимо.", reply_markup=main_keyboard())
            return

    amount = float(t)
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
    inline_kb = types.InlineKeyboardMarkup(row_width=3)
    buttons = [
        types.InlineKeyboardButton(text=cur, callback_data=f"to_currency:{cur}")
        for cur in ["USD", "EUR", "JPY", "TRY", "RUB", "AED"]
    ]
    inline_kb.add(*buttons)
    await message.answer("Теперь выберите валюту, в которую хотите конвертировать:", reply_markup=inline_kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("to_currency:"))
async def process_currency_callback(callback_query: types.CallbackQuery):
    to_currency = callback_query.data.split(":", 1)[1]
    user_id = callback_query.from_user.id

    if user_id not in user_data or "from_currency" not in user_data[user_id] or "amount" not in user_data[user_id]:
        await bot.answer_callback_query(callback_query.id, "Сначала выберите исходную валюту и введите сумму!")
        return

    if user_data[user_id].get("from_currency") == to_currency:
        await bot.answer_callback_query(callback_query.id, "❌ Валюта для конвертации должна отличаться от исходной!")
        return

    user_data[user_id]["to_currency"] = to_currency
    await bot.answer_callback_query(callback_query.id)
    await convert_currency(user_id, callback_query.message)

async def convert_currency(user_id: int, message: Message):
    data = user_data.get(user_id)
    if not data:
        await message.reply("❌ Ошибка данных пользователя.", reply_markup=main_keyboard())
        return

    from_currency = data["from_currency"]
    to_currency = data["to_currency"]
    amount = data["amount"]

    rates = get_exchange_rates()
    if not rates:
        await message.reply("❌ Ошибка при получении данных.", reply_markup=main_keyboard())
        return

    if rates.get(from_currency) is None or rates.get(to_currency) is None:
        await message.reply("❌ Не удалось получить курс для выбранной валюты.", reply_markup=main_keyboard())
        user_data.pop(user_id, None)
        return

    result = (amount * rates[from_currency]) / rates[to_currency]
    if 0 < result < 0.01:
        result_str = f"{result:.6f}"
    else:
        result_str = f"{result:.2f}"
    await message.reply(f"💱 {amount} {from_currency} = {result_str} {to_currency}", reply_markup=main_keyboard())
    user_data.pop(user_id, None)

def get_exchange_rates():
    try:
        response = requests.get(CBR_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        rates = {
            "USD": data["Valute"]["USD"]["Value"],
            "EUR": data["Valute"]["EUR"]["Value"],
            "JPY": data["Valute"]["JPY"]["Value"] / 100,
            "TRY": data["Valute"]["TRY"]["Value"],
            "RUB": 1.0,
            "AED": data["Valute"]["AED"]["Value"] if "AED" in data["Valute"] else None
        }
        return rates
    except Exception as e:
        logging.error(f"Ошибка получения курсов: {e}")
        return None

# ===== График курса (USD к RUB) =====
def generate_currency_graph():
    """
    Собирает данные за последние 7 дней, формирует текстовую историю изменения курса,
    строит график и возвращает кортеж: (текст, изображение в виде байтов).
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
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if currency in data["Valute"]:
                    dates.append(date.strftime("%d.%m"))
                    values.append(data["Valute"][currency]["Value"])
        except Exception:
            continue

    if len(dates) < 2:
        raise Exception("Недостаточно данных для графика.")

    # Для текстовой истории используем данные в хронологическом порядке (от старых к новым)
    hist_text = "История курса USD к RUB за последние 7 дней:\n" + "\n".join(
        f"{d}: {v:.2f}₽" for d, v in zip(dates[::-1], values[::-1])
    )

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
    return hist_text, buf.getvalue()

graph_currency_lock = {}
graph_currency_last_time = {}
GRAPH_CURRENCY_COOLDOWN = 30

@dp.message_handler(lambda message: message.text == "📉 График курса")
async def send_currency_graph(message: Message):
    user_id = message.from_user.id
    current_time = asyncio.get_event_loop().time()

    if user_id in graph_currency_last_time and (current_time - graph_currency_last_time[user_id] < GRAPH_CURRENCY_COOLDOWN):
        await message.reply("Слишком быстро отправляете запросы. Пожалуйста, подождите немного.")
        return
    graph_currency_last_time[user_id] = current_time

    if user_id not in graph_currency_lock:
        graph_currency_lock[user_id] = asyncio.Lock()
    lock = graph_currency_lock[user_id]

    if lock.locked():
        await message.reply("Ваш запрос уже в обработке. Пожалуйста, подождите.")
        return

    async with lock:
        try:
            loop = asyncio.get_event_loop()
            # Получаем и текстовую историю, и изображение графика
            hist_text, image_bytes = await loop.run_in_executor(None, generate_currency_graph)
        except Exception as e:
            logging.error(f"Ошибка генерации графика: {e}")
            await message.reply("❌ Не удалось получить данные для графика.", reply_markup=main_keyboard())
            return
        await message.reply(hist_text)
        await message.reply_photo(image_bytes, reply_markup=main_keyboard())

# ===== Подписка =====
@dp.message_handler(lambda message: message.text == "📊 Подписаться")
async def subscribe_command(message: Message):
    subscribers.add(message.from_user.id)
    await message.reply("✅ Вы подписаны на ежедневные курсы валют!", reply_markup=main_keyboard())

@dp.message_handler(lambda message: message.text == "❌ Отписаться")
async def unsubscribe_command(message: Message):
    subscribers.discard(message.from_user.id)
    await message.reply("❌ Вы отписались от ежедневных курсов.", reply_markup=main_keyboard())

# ===== Будильники =====
@dp.message_handler(lambda message: message.text == "🔔 Установить будильник")
async def alert_start(message: Message):
    await message.reply("Введите команду в формате:\n"
                        "`/alert USD 100.50` или `/alert USD > 100.02` или `/alert USD < 94.30`",
                        reply_markup=main_keyboard())

@dp.message_handler(lambda message: message.text.lower().startswith("/alert"))
async def set_alert(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ Неправильный формат! Используйте:\n"
                            "`/alert USD 100.50` или `/alert USD > 100.02`",
                            reply_markup=main_keyboard())
        return
    currency = parts[1].upper()
    allowed_currencies = ["USD", "EUR", "JPY", "TRY", "RUB", "AED"]
    if currency not in allowed_currencies:
        await message.reply(f"❌ Валюта {currency} не поддерживается. Доступны: {', '.join(allowed_currencies)}",
                            reply_markup=main_keyboard())
        return
    try:
        # Поддержка формата с оператором: /alert USD > 100.02 или /alert USD < 94.30
        if parts[2] in [">", "<"] and len(parts) >= 4:
            operator = parts[2]
            target_price = float(parts[3])
        else:
            target_price = float(parts[2])
            rates = get_exchange_rates()
            if not rates or currency not in rates:
                await message.reply("❌ Не удалось получить текущий курс. Попробуйте позже.", reply_markup=main_keyboard())
                return
            current_rate = rates[currency]
            operator = ">" if target_price > current_rate else "<"
        direction = "up" if operator == ">" else "down"
        user_id = message.from_user.id
        if user_id not in alerts:
            alerts[user_id] = []
        alerts[user_id].append({
            "currency": currency,
            "target": target_price,
            "direction": direction
        })
        await message.reply(f"🔔 Будильник установлен: {currency} {'>' if direction=='up' else '<'} {target_price}₽",
                            reply_markup=main_keyboard())
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
        text_lines.append(f"{idx}. {alert['currency']} {'>' if alert['direction']=='up' else '<'} {alert['target']}₽")
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
        await message.reply(f"✅ Будильник {removed['currency']} {'>' if removed['direction']=='up' else '<'} {removed['target']}₽ удалён.",
                            reply_markup=main_keyboard())
    except ValueError:
        await message.reply("❌ Неверный формат номера. Используйте: `/delete_alert 1`", reply_markup=main_keyboard())

# ===== Кэширование данных лучших обменников =====
best_rates_cache = {
    "timestamp": 0,
    "data": None
}
CACHE_DURATION = 300  # 5 минут

def get_best_exchange_rates(force_update: bool = False):
    """
    Если force_update==False, то если данные в кэше не устарели, возвращаем их.
    Иначе выполняем HTTP-запрос к API banki.ru и обновляем кэш.
    """
    global best_rates_cache
    current_time = time.time()
    if (not force_update and best_rates_cache["data"] is not None and
            (current_time - best_rates_cache["timestamp"] < CACHE_DURATION)):
        logging.info("Используем закэшированные данные для обменников.")
        return best_rates_cache["data"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/130.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru,en;q=0.9",
        "Referer": "https://www.banki.ru/products/currency/cash/izhevsk/?buttonId=2&location=%D0%B3+%D0%98%D0%B6%D0%B5%D0%B2%D1%81%D0%BA&latitude=56.852775&longitude=53.211463&amount=100",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": "_flpt_percent_zone=10; _flpt_sso_auth_user_in_segment=off; _gcl_au=1.1.1558551762.1737809557; _ga=GA1.2.840259073.1737809558; non_auth_user_region_id=508; uxs_uid=fceb3e50-db1b-11ef-8910-6fed71a169ad; __lhash_=03e5c24c899eb1ff0e109d0c2e4c764d; gtm-session-start=1739019645006; _gid=GA1.2.1108255462.1739019648; __hash_=e53d727ad88b20e2078fb1da6b19e342; _gat=1; banki_prev_page=/products/currencyNodejsApi/getBanksOrExchanges/; BANKI_RU_MYBANKI_ID=4895db1c-7df1-46d1-8fd2-6f4ddb5a3db2; _banki_ru_mybanki_id_migration=2024-08-14-updatedCookieDomain; counter_session=3; aff_sub3=/products/currency/cash/izhevsk/"
    }
    try:
        response = requests.get(BANKI_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        banks_list = data.get("list", [])
        banks = []
        for bank in banks_list:
            exchange = bank.get("exchange", {})
            contact = bank.get("contactInformation", {})
            bank_name = bank.get("bankName", "Неизвестный банк")
            address = contact.get("address", "Адрес не указан")
            buy = exchange.get("buy", 0)
            sale = exchange.get("sale", 0)
            refresh_date = exchange.get("refreshDate", "")
            # Формирование ссылки: заменяем префикс, если требуется
            relative_url = bank.get("@id", "")
            if relative_url.startswith("/currency/api/v1/exchange_offices/"):
                relative_url = relative_url.replace(
                    "/currency/api/v1/exchange_offices/",
                    "/products/currency/exchange/"
                )
                if not relative_url.endswith("/"):
                    relative_url += "/"
            link = f"https://www.banki.ru{relative_url}" if relative_url else ""
            banks.append((bank_name, address, buy, sale, refresh_date, link))
    except Exception as e:
        logging.error(f"Ошибка получения данных с banki.ru: {e}")
        banks = []

    best_rates_cache["timestamp"] = current_time
    best_rates_cache["data"] = banks
    logging.info("Данные лучших обменников обновлены и сохранены в кэш.")
    return banks

def generate_best_rates_text(banks):
    """
    Формирует отформатированное текстовое сообщение со списком лучших обменников.
    Если банк присутствует несколько раз, объединяются адреса, при этом каждый адрес выводится на новой строке
    и отображается как кликабельная ссылка (сам адрес является ссылкой).
    """
    grouped = {}
    for bank in banks:
        bank_name, address, buy, sale, refresh_date, link = bank
        key = bank_name.strip()
        if key in grouped:
            if (address, link) not in grouped[key]["addresses"]:
                grouped[key]["addresses"].append((address, link))
        else:
            grouped[key] = {
                "addresses": [(address, link)],
                "buy": buy,
                "sale": sale,
                "refresh_date": refresh_date
            }

    lines = ["📊 *Лучшие обменники в Ижевске (выгодные для продажи USD):*\n"]
    for i, (bank_name, info) in enumerate(grouped.items(), start=1):
        # Для каждого адреса создаём строку; если есть ссылка – сам адрес оборачиваем в Markdown‑ссылку
        address_lines = []
        for addr, link in info["addresses"]:
            if link:
                address_lines.append(f"[{addr}]({link})")
            else:
                address_lines.append(addr)
        # Объединяем адреса, каждый с новой строки с отступом
        addresses_str = "\n    ".join(address_lines)
        lines.append(f"*{i}. {bank_name}*")
        lines.append(f"  📍 Адрес:\n    {addresses_str}")
        lines.append(f"  🔹 Покупка: *{info['buy']}₽*")
        lines.append(f"  🔸 Продажа: *{info['sale']}₽*")
        lines.append(f"  ⏰ Обновлено: `{info['refresh_date']}`\n")
    return "\n".join(lines)

async def best_rates_cache_refresher():
    """
    Фоновый таск, который каждые CACHE_DURATION секунд обновляет кэш данных лучших обменников.
    """
    while True:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: get_best_exchange_rates(force_update=True))
        except Exception as e:
            logging.error(f"Ошибка обновления кэша лучших обменников: {e}")
        await asyncio.sleep(CACHE_DURATION)

best_rates_lock = {}
best_rates_last_time = {}
BEST_RATES_COOLDOWN = 30

@dp.message_handler(commands=['best_rates'])
@dp.message_handler(lambda message: message.text == "📊 Лучшие обменники в Ижевске")
async def best_rates_handler(message: Message):
    user_id = message.from_user.id
    current_time = asyncio.get_event_loop().time()

    if user_id in best_rates_last_time and (current_time - best_rates_last_time[user_id] < BEST_RATES_COOLDOWN):
        await message.reply("Слишком быстро отправляете запросы. Пожалуйста, подождите немного.")
        return
    best_rates_last_time[user_id] = current_time

    if user_id not in best_rates_lock:
        best_rates_lock[user_id] = asyncio.Lock()
    lock = best_rates_lock[user_id]

    if lock.locked():
        await message.reply("Ваш запрос уже в обработке. Пожалуйста, подождите.")
        return

    async with lock:
        if best_rates_cache["data"] is None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: get_best_exchange_rates(force_update=True))
        
        banks = best_rates_cache["data"]
        if not banks:
            await message.reply("Не удалось получить данные о курсах валют.", reply_markup=main_keyboard())
            return

        text = generate_best_rates_text(banks)
        await message.reply(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=main_keyboard())

async def daily_exchange_rates():
    while True:
        await asyncio.sleep(86400)
        rates = get_exchange_rates()
        if subscribers and rates:
            text = "📊 **Курсы валют на сегодня:**\n" + "\n".join(f"💰 {c}: {v:.2f} RUB" for c, v in rates.items() if v is not None)
            for user_id in subscribers:
                try:
                    await bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_keyboard())
                except Exception as e:
                    logging.error(f"Ошибка при отправке подписчику {user_id}: {e}")

async def check_alerts():
    while True:
        await asyncio.sleep(5)
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
                if alert["direction"] == "up" and curr_rate > alert["target"]:
                    try:
                        await bot.send_message(
                            user_id,
                            f"🚀 {alert['currency']} достиг значения больше {alert['target']}₽ (текущий: {curr_rate}₽)!",
                            reply_markup=main_keyboard()
                        )
                    except Exception as e:
                        logging.error(f"Ошибка отправки alert для {user_id}: {e}")
                    continue
                elif alert["direction"] == "down" and curr_rate < alert["target"]:
                    try:
                        await bot.send_message(
                            user_id,
                            f"🚀 {alert['currency']} достиг значения меньше {alert['target']}₽ (текущий: {curr_rate}₽)!",
                            reply_markup=main_keyboard()
                        )
                    except Exception as e:
                        logging.error(f"Ошибка отправки alert для {user_id}: {e}")
                    continue
                new_alerts.append(alert)
            if new_alerts:
                alerts[user_id] = new_alerts
            else:
                alerts.pop(user_id)
                
# ===== Фоновые задачи =====
async def on_startup(_):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: get_best_exchange_rates(force_update=True))
    asyncio.create_task(best_rates_cache_refresher())
    asyncio.create_task(daily_exchange_rates())
    asyncio.create_task(check_alerts())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
