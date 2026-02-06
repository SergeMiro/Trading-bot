<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## Полный Pipeline Trading Bot: Пошаговая логика графика

Это **полная технологическая схема** работы торгового бота от момента запуска до закрытия позиции. Каждый блок графика соответствует конкретному шагу в этом документе.

***

## PIPELINE OVERVIEW (Обзор потока данных)

```
TRIGGER (5:00 AM) 
   ↓
DATA SOURCES (SEC/Yahoo/IBKR) 
   ↓
AGENT-1 (Calendar)
   ↓
AGENT-2 (SEC Events)
   ↓
DECISION: Red Flag Check
   ↓ (No)              ↓ (Yes → SKIP)
AGENT-3 (IBKR Setup)
   ↓
TRIGGER (7:30 AM)
   ↓
AGENT-4 (Pre-Market Data)
   ↓
TRIGGER (10:00-10:15 AM)
   ↓
AGENT-5 (Scoring)
   ↓
AGENT-6 (Validation)
   ↓
DECISION: Validation Status
   ↓              ↓           ↓
  BUY          HOLD        SKIP
   ↓              ↓           ↓
MONITOR      →  EOD     →  EOD
   ↓
DECISION: Exit Condition?
   ↓ (Yes)         ↓ (No → Continue Monitor)
EXIT
   ↓
EOD (4:00 PM)
```


***

## БЛОК 0: INITIALIZATION (Инициализация системы)

**Время:** Один раз при запуске бота

**Действия:**

1. Загрузить конфигурацию:

```json
{
  "api_keys": {
    "sec_edgar": "API_KEY",
    "ibkr": "API_KEY",
    "claude": "API_KEY"
  },
  "settings": {
    "min_market_cap": 500000000,
    "max_monitoring_lines": 100,
    "score_threshold_buy": 70,
    "score_threshold_hold": 50,
    "target_gain": 0.08,
    "stop_loss": -0.05,
    "max_hold_days": 7
  }
}
```

2. Проверить доступность API:
    - SEC EDGAR: `GET https://data.sec.gov/submissions/`
    - IBKR: Подключение к TWS Gateway
    - Claude/GPT: Test API call
3. Инициализировать БД:
    - Таблица: `earnings_calendar`
    - Таблица: `sec_events`
    - Таблица: `agent_logs`
    - Таблица: `open_positions`

**Выход:** Система готова к работе

***

## БЛОК 1: DAILY TRIGGER (5:00 AM NY)

**Время:** Каждый день в 5:00 AM (New York Time)

**Действия:**

1. Проверить: это рабочий день NYSE? (пн-пт, не праздник)
    - Если НЕТ → STOP (пропустить день)
    - Если ДА → продолжить
2. Запустить Агента-1

**Логика триггера (cron):**

```bash
# UTC = NY + 5 hours (зимой)
0 10 * * 1-5  # 10:00 UTC = 5:00 AM NY
```


***

## БЛОК 2: DATA SOURCES (Источники данных)

### 2.1 SEC EDGAR API (Primary)

**Endpoint:** `https://data.sec.gov/submissions/CIK{company_cik}.json`

**Что даёт:**

- Earnings dates (из форм 8-K, 10-Q, 10-K)
- SEC filings: Form 4, 8-K, S-3

**Fallback условие:**

```python
try:
    response = requests.get(sec_url, timeout=10)
    if response.status_code == 200:
        data = response.json()
        source = "SEC_EDGAR"
    else:
        raise APIError
except (Timeout, APIError):
    # Переключение на Yahoo
    source = "YAHOO_FALLBACK"
```


### 2.2 Yahoo Finance API (Fallback)

**Библиотека:** `yfinance` (Python)

**Что даёт:**

- Earnings calendar (менее точный, но бесплатный)
- Исторические цены

**Код:**

```python
import yfinance as yf
ticker = yf.Ticker("AAPL")
earnings = ticker.earnings_dates
```


### 2.3 IBKR API

**Что даёт:**

- Real-time цены/объёмы
- Премаркет данные (7:30 AM NY)
- Исторические бары (для ATR расчёта)

**Запрос:**

```python
from ib_insync import IB, Stock
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
contract = Stock('AAPL', 'SMART', 'USD')
bars = ib.reqHistoricalData(
    contract, 
    endDateTime='', 
    durationStr='30 D',
    barSizeSetting='1 hour', 
    whatToShow='TRADES'
)
```


***

## БЛОК 3: AGENT-1 (Calendar Agent)

**Вход:** Пустой (первый агент в цепочке)

**Процесс:**

### Шаг 3.1: Формирование запроса

```python
date_start = datetime.now()
date_end = date_start + timedelta(days=30)
request_params = {
    "date_range": f"{date_start} to {date_end}",
    "markets": ["NYSE", "NASDAQ"],
    "min_market_cap": 500000000
}
```


### Шаг 3.2: Запрос к SEC API

```python
# Псевдокод
companies = []
for cik in all_company_ciks:
    try:
        data = fetch_from_sec(cik)
        if data['earnings_date'] in date_range:
            if data['is_confirmed'] == True:
                if data['market_cap'] > 500000000:
                    companies.append(data)
    except:
        # Fallback на Yahoo
        data = fetch_from_yahoo(ticker)
        companies.append(data)
```


### Шаг 3.3: Формирование промпта для ИИ

```python
system_prompt = """
Ты — агент сбора календаря earnings.
Задачи:
1. Проанализируй список компаний
2. Оставь только подтверждённые даты (is_confirmed=true)
3. Отфильтруй по капитализации > $500M
4. Верни JSON
"""

user_prompt = f"""
Вот список компаний с earnings датами:
{json.dumps(raw_companies)}

Отфильтруй по правилам и верни в формате:
{{
  "source": "SEC_EDGAR",
  "count": X,
  "companies": [
    {{"ticker": "AAPL", "earnings_date": "2026-02-15", ...}}
  ]
}}
"""

response = claude_api.messages.create(
    model="claude-sonnet-4-20250514",
    system=system_prompt,
    messages=[{"role": "user", "content": user_prompt}]
)
```


### Шаг 3.4: Парсинг ответа ИИ

```python
output = json.loads(response.content[^0].text)
```

**Выход (JSON):**

```json
{
  "analysis": "Получено 47 компаний из SEC. 12 исключены (капитализация < $500M). Итого: 35.",
  "result": {
    "source": "SEC_EDGAR",
    "count": 35,
    "companies": [
      {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "earnings_date": "2026-02-15",
        "is_confirmed": true,
        "market_cap": 3200000000000,
        "sector": "Technology"
      }
    ]
  },
  "metadata": {
    "timestamp": "2026-02-06T05:00:00",
    "api_status": "ok"
  }
}
```

**Сохранение в БД:**

```sql
INSERT INTO earnings_calendar (ticker, earnings_date, market_cap, sector)
VALUES ('AAPL', '2026-02-15', 3200000000000, 'Technology');
```


***

## БЛОК 4: AGENT-2 (Event Detector Agent)

**Вход:** Список компаний от Агента-1

**Процесс:**

### Шаг 4.1: Для каждой компании запросить SEC EDGAR

```python
for company in agent1_output['companies']:
    ticker = company['ticker']
    
    # Запрос всех filings за последние 14 дней
    filings = get_sec_filings(ticker, days=14)
    
    events = []
    total_score = 0
    red_flag = False
    
    for filing in filings:
        if filing['form_type'] == 'Form 4':
            # Инсайдерская сделка
            if filing['transaction_type'] == 'BUY':
                events.append({
                    "type": "Form 4",
                    "description": f"{filing['insider_name']} купил ${filing['amount']}",
                    "weight": 15
                })
                total_score += 15
            elif filing['transaction_type'] == 'SELL':
                events.append({
                    "type": "Form 4",
                    "description": f"{filing['insider_name']} продал ${filing['amount']}",
                    "weight": -10
                })
                total_score -= 10
        
        elif filing['form_type'] == '8-K':
            # Анализ через ИИ (позитивное/негативное)
            analysis = analyze_8k_with_ai(filing['text'])
            if analysis['sentiment'] == 'positive':
                events.append({"type": "8-K", "weight": 10})
                total_score += 10
            else:
                events.append({"type": "8-K", "weight": -15})
                total_score -= 15
        
        elif filing['form_type'] == 'S-3':
            # КРАСНЫЙ ФЛАГ (допэмиссия)
            events.append({
                "type": "S-3",
                "description": f"Допэмиссия ${filing['offering_amount']}",
                "weight": -100
            })
            total_score = -100
            red_flag = True
```


### Шаг 4.2: Формирование выхода

```python
output = {
    "analysis": f"Найдено {len(events)} событий для {ticker}",
    "result": {
        "companies": [
            {
                "ticker": ticker,
                "events": events,
                "total_score": total_score,
                "red_flag": red_flag
            }
        ]
    }
}
```

**Выход (пример):**

```json
{
  "result": {
    "companies": [
      {
        "ticker": "AAPL",
        "events": [
          {"type": "Form 4", "description": "CEO купил $2M", "weight": 15}
        ],
        "total_score": 15,
        "red_flag": false
      },
      {
        "ticker": "NVDA",
        "events": [
          {"type": "S-3", "description": "Допэмиссия $500M", "weight": -100}
        ],
        "total_score": -100,
        "red_flag": true
      }
    ]
  }
}
```


***

## БЛОК 5: DECISION POINT 1 (Red Flag Check)

**Условие:**

```python
for company in agent2_output['companies']:
    if company['red_flag'] == True:
        # SKIP (исключить из дальнейшей обработки)
        action = "SKIP"
        log_decision(company['ticker'], action, reason="S-3 filing detected")
    else:
        # Продолжить к Агенту-3
        action = "CONTINUE"
```

**Логика ветвления на графике:**

- **Зелёная стрелка (No red flag):** → Агент-3
- **Красная стрелка (S-3 detected):** → SKIP → EOD

***

## БЛОК 6: AGENT-3 (IBKR Setup Agent)

**Вход:** Отфильтрованный список (без red_flag)

**Процесс:**

### Шаг 6.1: Сортировка по total_score

```python
companies = agent2_output['companies']
companies_filtered = [c for c in companies if c['red_flag'] == False]
companies_sorted = sorted(companies_filtered, key=lambda x: x['total_score'], reverse=True)
```


### Шаг 6.2: Взять топ-100

```python
top_100 = companies_sorted[:100]

# Если меньше 100 → добавить топ S&P500
if len(top_100) < 100:
    sp500_tickers = get_sp500_list()
    remaining_slots = 100 - len(top_100)
    top_100 += sp500_tickers[:remaining_slots]
```


### Шаг 6.3: Настроить IBKR мониторинг

```python
from ib_insync import IB, Stock

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

for ticker in top_100:
    contract = Stock(ticker, 'SMART', 'USD')
    
    # Запросить исторические данные (30 дней)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='30 D',
        barSizeSetting='1 hour',
        whatToShow='TRADES',
        useRTH=False  # включить премаркет
    )
    
    # Сохранить в БД
    save_to_db(ticker, bars)
```

**Выход:**

```json
{
  "result": {
    "tickers": ["AAPL", "MSFT", "GOOGL", ...],  // 100 тикеров
    "ibkr_config": {
      "contract_type": "STK",
      "exchange": "SMART",
      "currency": "USD",
      "historical_period": "30 D",
      "bar_size": "1 hour"
    }
  },
  "metadata": {
    "total_lines": 100,
    "earnings_candidates": 34,
    "sp500_filler": 66
  }
}
```


***

## БЛОК 7: WAIT UNTIL 7:30 AM (NY)

**Логика:**

```python
while True:
    now = datetime.now(timezone('America/New_York'))
    
    # Проверить: есть ли компании с earnings сегодня?
    today_earnings = get_companies_with_earnings_today()
    
    if len(today_earnings) > 0 and now.hour == 7 and now.minute == 30:
        # Запустить Агента-4
        trigger_agent4(today_earnings)
        break
    
    time.sleep(60)  # Проверять каждую минуту
```


***

## БЛОК 8: AGENT-4 (Pre-Market Data Agent)

**Триггер:** 7:30 AM (NY), только для компаний с отчётом сегодня

**Вход:**

```json
{
  "trigger_date": "2026-02-15",
  "tickers_with_earnings_today": ["AAPL", "AMD"]
}
```

**Процесс:**

### Шаг 8.1: Запросить премаркет данные

```python
for ticker in tickers:
    # Текущая цена в премаркет
    premarket_price = ib.reqMktData(ticker, snapshot=True)
    
    # Объём премаркет (7:30 AM)
    premarket_volume = get_volume_at_time(ticker, time="07:30")
    
    # Средний объём в 7:30 AM за последние 14 дней
    avg_volume_14d = calculate_avg_volume(ticker, time="07:30", days=14)
    
    volume_ratio = premarket_volume / avg_volume_14d
    
    # ATR (волатильность за 5 дней)
    atr_5d = calculate_atr(ticker, period=5)
```


### Шаг 8.2: Запросить индексы

```python
# S&P500
sp500_change = get_index_change("SPY", timeframe="overnight")

# Сектор компании
sector = get_company_sector(ticker)
sector_change = get_sector_change(sector, timeframe="overnight")
```


### Шаг 8.3: Определить market sentiment

```python
if sp500_change > 0.002:  # +0.2%
    market_sentiment = "bullish"
elif sp500_change < -0.002:
    market_sentiment = "bearish"
else:
    market_sentiment = "neutral"
```

**Выход:**

```json
{
  "result": {
    "market_sentiment": "bullish",
    "sp500_change": 0.003,
    "stocks": [
      {
        "ticker": "AAPL",
        "premarket_price": 182.50,
        "premarket_volume": 1250000,
        "avg_volume_14d": 590000,
        "volume_ratio": 2.12,
        "atr_5d": 3.45,
        "sector": "Technology",
        "sector_change": 0.005
      }
    ]
  }
}
```


***

## БЛОК 9: WAIT UNTIL 9:30 AM (Открытие рынка)

**Действие:** НЕ ВХОДИТЬ

**Причина:** Первые 30 минут (9:30–10:00 AM) — высокая волатильность, "шум", искусственные движения от алгоритмов и маркет-мейкеров.

**Логика:**

```python
while datetime.now(tz).time() < time(10, 0):
    time.sleep(60)  # Ждать
```


***

## БЛОК 10: TRIGGER 10:00-10:15 AM (NY)

**Действие:** Запустить Агента-5 (Scoring)

***

## БЛОК 11: AGENT-5 (Scoring Agent)

**Вход:** Объединённые данные от Агента-2 + Агента-4

**Процесс:**

### Шаг 11.1: Рассчитать баллы по параметрам

```python
def calculate_score(company, premarket_data):
    score = 0
    breakdown = {}
    
    # 1. Volume Score
    volume_ratio = premarket_data['volume_ratio']
    if volume_ratio > 2.0:
        breakdown['volume_score'] = 25
        score += 25
    elif volume_ratio > 1.5:
        breakdown['volume_score'] = 20
        score += 20
    elif volume_ratio > 1.0:
        breakdown['volume_score'] = 10
        score += 10
    else:
        breakdown['volume_score'] = 0
    
    # 2. Volatility Score (ATR)
    atr = premarket_data['atr_5d']
    if 2 <= atr <= 5:
        breakdown['volatility_score'] = 10
        score += 10
    elif 5 < atr <= 10:
        breakdown['volatility_score'] = 5
        score += 5
    else:
        breakdown['volatility_score'] = 0
    
    # 3. Market Score
    sentiment = premarket_data['market_sentiment']
    if sentiment == "bullish":
        breakdown['market_score'] = 15
        score += 15
    elif sentiment == "neutral":
        breakdown['market_score'] = 5
        score += 5
    else:
        breakdown['market_score'] = 0
    
    # 4. Sector Score
    sector_change = premarket_data['sector_change']
    if sector_change > 0:
        breakdown['sector_score'] = 15
        score += 15
    else:
        breakdown['sector_score'] = 0
    
    # 5. SEC Events Score (from Agent-2)
    sec_score = company['total_score']
    breakdown['sec_score'] = sec_score
    score += sec_score
    
    return score, breakdown
```


### Шаг 11.2: Определить рекомендацию

```python
final_score, breakdown = calculate_score(company, premarket_data)

if final_score > 70:
    recommendation = "BUY"
elif final_score >= 50:
    recommendation = "HOLD"
else:
    recommendation = "SKIP"
```


### Шаг 11.3: Рассчитать confidence

```python
# Confidence = нормализованный скор
confidence = min(final_score / 100, 1.0)
```

**Выход:**

```json
{
  "result": {
    "ticker": "AAPL",
    "final_score": 75,
    "recommendation": "BUY",
    "breakdown": {
      "volume_score": 20,
      "volatility_score": 10,
      "market_score": 15,
      "sector_score": 15,
      "sec_score": 15
    },
    "entry_time": "10:15 AM NY",
    "target_gain": "8-10%",
    "stop_loss": "-5%"
  },
  "confidence": 0.75
}
```


***

## БЛОК 12: AGENT-6 (Validation Agent)

**Вход:** Все выходы агентов 1–5

**Процесс:**

### Шаг 12.1: Проверка логики

```python
issues = []

# Проверка 1: Все компании из Agent-1 прошли через Agent-2?
agent1_tickers = set([c['ticker'] for c in agent1_output['companies']])
agent2_tickers = set([c['ticker'] for c in agent2_output['companies']])
if agent1_tickers != agent2_tickers:
    issues.append("Missing tickers in Agent-2 output")

# Проверка 2: Нет противоречий (red_flag=true, но BUY)?
for rec in agent5_output['recommendations']:
    ticker = rec['ticker']
    company_data = find_in_agent2(ticker)
    if company_data['red_flag'] == True and rec['recommendation'] == 'BUY':
        issues.append(f"{ticker}: red_flag=true but recommendation=BUY")

# Проверка 3: Полнота данных
for rec in agent5_output['recommendations']:
    if rec['final_score'] is None or rec['confidence'] is None:
        issues.append(f"{rec['ticker']}: incomplete data")
```


### Шаг 12.2: Оценка confidence

```python
# Средний confidence по всем рекомендациям
avg_confidence = sum([r['confidence'] for r in agent5_output]) / len(agent5_output)
```


### Шаг 12.3: Финальный вердикт

```python
if len(issues) == 0 and avg_confidence > 0.7:
    status = "APPROVED"
elif len(issues) > 0:
    status = "REJECTED"
else:
    status = "NEEDS_REVIEW"
```

**Выход:**

```json
{
  "result": {
    "status": "APPROVED",
    "issues": [],
    "confidence": 0.82,
    "final_recommendations": [
      {"ticker": "AAPL", "action": "BUY", "score": 75},
      {"ticker": "MSFT", "action": "HOLD", "score": 62}
    ]
  }
}
```


***

## БЛОК 13: DECISION POINT 2 (Validation Status)

**Ветвление:**

```python
if validation_status == "APPROVED":
    for rec in recommendations:
        if rec['action'] == "BUY":
            execute_buy(rec['ticker'])
        elif rec['action'] == "HOLD":
            send_notification(f"HOLD: {rec['ticker']} (score: {rec['score']})")
        elif rec['action'] == "SKIP":
            log_skip(rec['ticker'])

elif validation_status == "REJECTED":
    log_error("Validation failed")
    send_alert("System error: validation rejected")

elif validation_status == "NEEDS_REVIEW":
    send_notification("Manual review required")
```

**Логика на графике:**

- **APPROVED + Score > 70:** → BUY (зелёная стрелка)
- **APPROVED + Score 50-70:** → HOLD (жёлтая стрелка)
- **APPROVED + Score < 50 OR REJECTED:** → SKIP (красная стрелка)

***

## БЛОК 14: ACTION - BUY

**Процесс:**

### Шаг 14.1: Выполнить ордер через IBKR

```python
from ib_insync import MarketOrder

contract = Stock(ticker, 'SMART', 'USD')

# Рассчитать размер позиции (risk management)
account_balance = ib.accountSummary()
position_size = calculate_position_size(
    balance=account_balance,
    risk_per_trade=0.02,  # 2% от капитала
    stop_loss=0.05  # -5%
)

# Купить
order = MarketOrder('BUY', position_size)
trade = ib.placeOrder(contract, order)

# Записать в БД
save_position(ticker, entry_price=trade.avgFillPrice, size=position_size, timestamp=datetime.now())
```


### Шаг 14.2: Установить стоп-лосс и тейк-профит

```python
entry_price = trade.avgFillPrice

# Stop-loss: -5%
stop_price = entry_price * 0.95

# Take-profit: +8-10%
target_price = entry_price * 1.09

# Разместить bracket orders
stop_order = StopOrder('SELL', position_size, stop_price)
limit_order = LimitOrder('SELL', position_size, target_price)

ib.placeOrder(contract, stop_order)
ib.placeOrder(contract, limit_order)
```

**Переход:** → MONITOR

***

## БЛОК 15: ACTION - HOLD

**Процесс:**

```python
send_telegram_message(f"""
⚠️ HOLD Signal
Ticker: {ticker}
Score: {score}
Reason: Score в зоне 50-70, требуется ручная проверка.
Data: {json.dumps(company_data)}
""")
```

**Переход:** → EOD (не входить в сделку)

***

## БЛОК 16: ACTION - SKIP

**Процесс:**

```python
log_skip(ticker, reason="Score < 50 or red flag")
```

**Переход:** → EOD

***

## БЛОК 17: MONITOR POSITION

**Процесс:** Непрерывный мониторинг открытых позиций

```python
while True:
    open_positions = get_open_positions_from_db()
    
    for position in open_positions:
        ticker = position['ticker']
        entry_price = position['entry_price']
        entry_date = position['entry_date']
        
        # Получить текущую цену
        current_price = ib.reqMktData(ticker, snapshot=True)
        
        # Рассчитать P&L
        pnl_pct = (current_price - entry_price) / entry_price
        
        # Проверить условия выхода (переход к Decision Point 3)
        check_exit_conditions(position, pnl_pct)
    
    time.sleep(60)  # Проверять каждую минуту
```


***

## БЛОК 18: DECISION POINT 3 (Exit Condition?)

**Условия выхода:**

```python
def check_exit_conditions(position, pnl_pct):
    ticker = position['ticker']
    entry_date = position['entry_date']
    days_held = (datetime.now() - entry_date).days
    
    # Условие 1: Цель достигнута (+8-10%)
    if pnl_pct >= 0.08:
        exit_position(ticker, reason="Target reached", pnl=pnl_pct)
        return True
    
    # Условие 2: Стоп-лосс (-5%)
    if pnl_pct <= -0.05:
        exit_position(ticker, reason="Stop-loss hit", pnl=pnl_pct)
        return True
    
    # Условие 3: Max hold period (7 дней)
    if days_held >= 7:
        exit_position(ticker, reason="Max hold period", pnl=pnl_pct)
        return True
    
    # Условие 4: EOD (4:00 PM) - принудительное закрытие
    now = datetime.now(timezone('America/New_York'))
    if now.hour == 16 and now.minute == 0:
        exit_position(ticker, reason="EOD forced exit", pnl=pnl_pct)
        return True
    
    # Иначе: продолжать мониторинг
    return False
```

**Ветвление на графике:**

- **Exit condition = True:** → EXIT (красная стрелка)
- **Exit condition = False:** → MONITOR (зелёная пунктирная петля)

***

## БЛОК 19: ACTION - EXIT

**Процесс:**

### Шаг 19.1: Закрыть позицию

```python
def exit_position(ticker, reason, pnl):
    contract = Stock(ticker, 'SMART', 'USD')
    position_size = get_position_size(ticker)
    
    # Продать
    order = MarketOrder('SELL', position_size)
    trade = ib.placeOrder(contract, order)
    
    # Записать результат
    save_trade_result(
        ticker=ticker,
        exit_price=trade.avgFillPrice,
        pnl_pct=pnl,
        reason=reason,
        timestamp=datetime.now()
    )
    
    # Уведомление
    send_telegram_message(f"""
    ✅ Position Closed
    Ticker: {ticker}
    P&L: {pnl:.2%}
    Reason: {reason}
    """)
```

**Переход:** → EOD

***

## БЛОК 20: EOD (End of Day - 4:00 PM NY)

**Процесс:**

### Шаг 20.1: Генерация дневного отчёта

```python
def generate_daily_report():
    # Собрать статистику
    today_trades = get_trades_today()
    total_pnl = sum([t['pnl_pct'] for t in today_trades])
    win_rate = len([t for t in today_trades if t['pnl_pct'] > 0]) / len(today_trades)
    
    report = f"""
    📊 Daily Report - {datetime.now().date()}
    
    Trades executed: {len(today_trades)}
    Total P&L: {total_pnl:.2%}
    Win Rate: {win_rate:.1%}
    
    Details:
    {json.dumps(today_trades, indent=2)}
    """
    
    send_email(report)
    save_to_log(report)
```


### Шаг 20.2: Очистка и подготовка к следующему дню

```python
# Закрыть все соединения
ib.disconnect()

# Архивировать логи
archive_logs()

# Завершить до следующего триггера (5:00 AM)
```


***

## SUMMARY: Полный цикл одного дня

```
05:00 AM → Агент-1 (календарь) → Агент-2 (SEC события) → Decision (red flag?)
           ↓
           Агент-3 (настройка IBKR, 100 линий)
           ↓
07:30 AM → Агент-4 (премаркет данные)
           ↓
09:30 AM → [Ожидание 30 минут]
           ↓
10:00 AM → Агент-5 (скоринг) → Агент-6 (валидация) → Decision (score?)
           ↓                    ↓                  ↓
          BUY                 HOLD               SKIP
           ↓                    ↓                  ↓
        MONITOR  ←──────────────┴──────────────────┘
           ↓
        [Петля мониторинга до exit condition]
           ↓
04:00 PM → EXIT → EOD (отчёт, архивация)
```


***

Это **полная техническая спецификация pipeline**, по которой построен график. Каждый блок = конкретный код/логика/API-запрос.
<span style="display:none">[^1]</span>

<div align="center">⁂</div>

[^1]: file-1.ogg

