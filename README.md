# **tgBotExchange-rates**

Данный Telegram-бот предоставляет актуальные курсы обмена валют и выполняет конвертацию валют на основе пользовательского ввода. Теперь он также поддерживает **графики курсов, автоуведомления и подписку на ежедневные обновления**.

## **📌 Возможности**

✅ Отображение текущих курсов популярных валют (**USD, JPY, EUR, TRY, RUB**).  
✅ **Конвертация** сумм между валютами.  
✅ Удобный **интерфейс с кнопками** для быстрого выбора.  
✅ Просмотр **графика курса за 7 дней**.  
✅ **Подписка** на ежедневные обновления курсов.  
✅ **Автоуведомления** при достижении заданного курса.  

## **⚙️ Как это работает**

### 🔹 **Основные команды**  
- **`/start`** – Запуск бота, отображение кнопок.
- **Выбор валюты** – Пользователь выбирает валюту для конвертации.
- **Ввод суммы** – Бот запрашивает сумму.
- **Конвертация** – Выбор конечной валюты, бот рассчитывает обмен.
- **📉 График курса** – Бот показывает изменения курса за последние 7 дней.
- **📊 Подписка** – Бот ежедневно присылает актуальные курсы.
- **❌ Отписаться** – Отключение подписки.
- **🔔 Установить будильник** – Бот уведомит, когда курс достигнет заданного значения.

### 🔹 **Пример использования**
1. Пользователь: `/start`
2. Бот: "Добро пожаловать! Выберите валюту."
   - `[USD] [JPY] [EUR] [TRY] [RUB]`
3. Пользователь выбирает **USD**.
4. Бот: `"Вы выбрали USD. Введите сумму."`
5. Пользователь вводит `100`.
6. Бот: `"Вы выбрали 100 USD. В какую валюту хотите конвертировать?"`
   - `[JPY] [EUR] [TRY] [RUB]`
7. Пользователь выбирает **RUB**.
8. Бот: `"💱 100 USD = 10,000 RUB (по текущему курсу)."`

### 🔹 **Пример графика курса**
1. Пользователь нажимает кнопку **📉 График курса**.
2. Бот отправляет график изменения курса USD/RUB за последние 7 дней.

### 🔹 **Пример подписки на курс валют**
1. Пользователь нажимает кнопку **📊 Подписаться**.
2. Бот подтверждает: `"✅ Вы подписаны на ежедневные курсы валют!"`
3. Каждый день бот отправляет актуальные курсы валют.

### 🔹 **Пример автоуведомления**
1. Пользователь вводит: `/alert USD 100.50`
2. Бот: `"🔔 Будильник установлен: USD → 100.50 RUB"`
3. Когда курс достигнет 100.50 RUB, бот уведомит пользователя.

## **📥 Установка**

1. Клонируйте репозиторий:
   
   git clone https://github.com/criex1488/tgBotExchange-rates.git
   cd tgBotExchange-rates
  

2. Установите зависимости:
   
   pip install -r requirements.txt
  

3. Запустите бота:
   
   python bot.py
  

## **🚀 Попробовать бота**
[**@tg_currency_exchange_bot**](https://t.me/tg_currency_exchange_bot)
