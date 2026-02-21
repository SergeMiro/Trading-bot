# Trading Bot v2 — VPS Deployment Guide

## Полный план развёртывания на Ubuntu 22.04 (Hetzner VPS)

---

## Фаза 0: Подготовка VPS

### Требования к серверу
- **OS:** Ubuntu 22.04 LTS
- **CPU:** 4 vCPU (минимум 2)
- **RAM:** 8 GB (минимум 4 GB)
- **SSD:** 40 GB
- **Сеть:** Публичный IP, порты 22 (SSH), 3000 (OpenClaw), 3001 (Grafana)

### 0.1. Обновление системы и базовые пакеты

```bash
# Подключение к VPS
ssh root@YOUR_VPS_IP

# Обновление системы
apt update && apt upgrade -y

# Установка базовых пакетов
apt install -y \
  curl wget git vim htop \
  build-essential libpq-dev \
  python3 python3-pip python3-venv \
  ufw fail2ban

# Настройка firewall
ufw allow 22/tcp      # SSH
ufw allow 3000/tcp    # OpenClaw Gateway
ufw allow 3001/tcp    # Grafana (опционально)
ufw --force enable

# Настройка fail2ban (защита SSH)
systemctl enable fail2ban
systemctl start fail2ban
```

### 0.2. Создание пользователя (не root)

```bash
adduser trading
usermod -aG sudo trading
su - trading
```

### 0.3. Установка Node.js 22+ (для OpenClaw)

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # Должно быть >= 22.x
```

### 0.4. Установка Docker & Docker Compose

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker trading
newgrp docker

# Проверка
docker --version
docker compose version
```

---

## Фаза 1: Установка OpenClaw Gateway

### 1.1. Установка OpenClaw

```bash
curl -fsSL https://openclaw.ai/install.sh | bash

# Запуск мастера настройки
openclaw onboard --install-daemon

# Проверка статуса
openclaw gateway status
```

### 1.2. Настройка автозапуска OpenClaw (systemd)

```bash
sudo tee /etc/systemd/system/openclaw.service << 'EOF'
[Unit]
Description=OpenClaw Gateway
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=trading
WorkingDirectory=/home/trading/trading-bot/openclaw
ExecStart=/usr/local/bin/openclaw gateway start
Restart=always
RestartSec=10
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
```

---

## Фаза 2: Развёртывание Trading Bot

### 2.1. Клонирование репозитория

```bash
cd /home/trading
git clone https://github.com/SergeMiro/Trading-bot.git trading-bot
cd trading-bot/openclaw
```

### 2.2. Настройка Python окружения

```bash
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3. Конфигурация переменных окружения

```bash
# Скопировать шаблон
cp .env.example .env

# Отредактировать .env — заполнить реальные значения
vim .env

# Критически важные переменные:
# - POSTGRES_PASSWORD (сильный пароль)
# - ANTHROPIC_API_KEY (ваш ключ Anthropic)
# - TELEGRAM_BOT_TOKEN (от @BotFather)
# - TELEGRAM_USER_ID (ваш ID из @userinfobot)
# - SEC_USER_AGENT (ваш реальный email)
# - IBKR_PORT=7497 (paper trading на первой фазе!)
```

### 2.4. Запуск PostgreSQL

```bash
# Запуск базы данных
docker compose up -d postgres

# Проверка
docker compose ps
docker compose logs postgres

# Инициализация Python-таблиц (дополнительно к init.sql)
source venv/bin/activate
cd scripts
python3 db_utils.py
cd ..
```

### 2.5. Запуск SEC RSS Monitor

```bash
docker compose up -d sec-rss-monitor

# Проверка логов
docker compose logs -f sec-rss-monitor
```

### 2.6. Настройка OpenClaw конфигурации

```bash
# Скопировать openclaw.json в домашнюю директорию OpenClaw
# (Путь может отличаться — проверить `openclaw config path`)
mkdir -p ~/.openclaw
cp openclaw.json ~/.openclaw/openclaw.json

# Скопировать crons и webhooks
cp -r crons/ ~/.openclaw/crons/
cp -r webhooks/ ~/.openclaw/webhooks/

# Подставить реальные значения из .env
# OpenClaw может автоматически подставлять ${VAR} из окружения
# Или вручную отредактировать openclaw.json:
source .env
sed -i "s|\${TELEGRAM_BOT_TOKEN}|$TELEGRAM_BOT_TOKEN|g" ~/.openclaw/openclaw.json
sed -i "s|\${TELEGRAM_USER_ID}|$TELEGRAM_USER_ID|g" ~/.openclaw/openclaw.json
sed -i "s|\${ANTHROPIC_API_KEY}|$ANTHROPIC_API_KEY|g" ~/.openclaw/openclaw.json
sed -i "s|\${ANTHROPIC_MODEL}|$ANTHROPIC_MODEL|g" ~/.openclaw/openclaw.json
```

### 2.7. Перезапуск OpenClaw с новой конфигурацией

```bash
sudo systemctl restart openclaw

# Проверка
openclaw gateway status
openclaw cron list
```

---

## Фаза 3: Установка IBKR TWS / IB Gateway

### 3.1. Установка IB Gateway (headless, для VPS)

```bash
# Скачать IB Gateway
cd /tmp
wget https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh

chmod +x ibgateway-stable-standalone-linux-x64.sh
sudo ./ibgateway-stable-standalone-linux-x64.sh

# Для headless VPS нужен Xvfb (виртуальный дисплей)
sudo apt install -y xvfb

# Запуск IB Gateway через Xvfb
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
/opt/ibgateway/ibgateway
```

### 3.2. Автозапуск IB Gateway (systemd)

```bash
sudo tee /etc/systemd/system/ibgateway.service << 'EOF'
[Unit]
Description=Interactive Brokers Gateway
After=network.target

[Service]
Type=simple
User=trading
Environment=DISPLAY=:99
ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1024x768x24
ExecStart=/opt/ibgateway/ibgateway
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ibgateway
```

### 3.3. Настройка IB Gateway API

В IB Gateway GUI (через VNC или при первом запуске):
- **Configuration → API → Settings:**
  - Enable ActiveX and Socket Clients: ✅
  - Socket port: 7497 (paper) или 7496 (live)
  - Allow connections from localhost only: ✅
  - Master API client ID: Leave empty
- **Login:**
  - Используйте paper trading аккаунт для фазы 1-2

---

## Фаза 4: Тестирование

### 4.1. Проверка всех компонентов

```bash
# 1. PostgreSQL
docker compose exec postgres psql -U trading_bot -d trading_bot -c "SELECT 1;"

# 2. OpenClaw Gateway
openclaw gateway status

# 3. Python скрипты
cd /home/trading/trading-bot/openclaw
source venv/bin/activate

# Тест календаря (без IBKR)
python3 scripts/fetch_calendar.py \
  --date-start "$(date +%Y-%m-%d)" \
  --date-end "$(date -d '+30 days' +%Y-%m-%d)"

# Тест SEC events
python3 scripts/fetch_sec_events.py --tickers "AAPL,MSFT,NVDA" --days 14

# 4. IBKR подключение
python3 -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=99)
print('Connected to IBKR!')
print(f'Accounts: {ib.managedAccounts()}')
ib.disconnect()
"

# 5. Telegram бот
# Отправьте "status" вашему боту в Telegram
# OpenClaw должен ответить через Master Orchestrator
```

### 4.2. Запуск pipeline вручную

```bash
# Тестовый прогон утреннего pipeline
openclaw run "TRIGGER: START_PIPELINE: calendar → events → ibkr_setup"

# Проверить данные
ls -la data/
cat data/calendar.json | python3 -m json.tool | head -20
```

---

## Фаза 5: Мониторинг

### 5.1. Grafana (опционально)

```bash
# Запуск с профилем monitoring
docker compose --profile monitoring up -d grafana

# Открыть: http://YOUR_VPS_IP:3001
# Login: admin / (из .env GRAFANA_PASSWORD)
# Добавить PostgreSQL datasource:
#   Host: postgres:5432
#   Database: trading_bot
#   User: trading_bot
```

### 5.2. Мониторинг логов

```bash
# OpenClaw логи
tail -f /home/trading/trading-bot/openclaw/logs/openclaw.log

# Docker логи
docker compose logs -f

# Системные логи
journalctl -u openclaw -f
journalctl -u ibgateway -f
```

### 5.3. Healthcheck cron

```bash
# Добавить в crontab хост-машины (не OpenClaw)
crontab -e

# Проверка каждые 30 минут что всё работает
*/30 * * * * /home/trading/trading-bot/openclaw/scripts/healthcheck.sh >> /var/log/trading-bot-health.log 2>&1
```

---

## Фаза 6: OpenClaw Canvas (мобильный интерфейс)

### Когда подключать
Canvas подключается в **Фазе 3 проекта** (месяц 2+), когда:
- Система показала стабильный винрейт > 65% на paper trading
- Вы перешли на live trading
- Количество сделок > 5/неделю

### 6.1. Подготовка сервера для Canvas

```bash
# Canvas подключается к OpenClaw Gateway через WebSocket
# Необходимо открыть порт и настроить SSL

# Установка Nginx как reverse proxy
sudo apt install -y nginx certbot python3-certbot-nginx

# Настройка домена (необходим домен, например: trading.yourdomain.com)
sudo tee /etc/nginx/sites-available/openclaw << 'EOF'
server {
    listen 80;
    server_name trading.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket timeout
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/openclaw /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# SSL сертификат (бесплатный через Let's Encrypt)
sudo certbot --nginx -d trading.yourdomain.com
```

### 6.2. Настройка OpenClaw для Canvas

Добавить в `~/.openclaw/openclaw.json`:

```json
{
  "canvas": {
    "enabled": true,
    "wsPort": 3000,
    "authToken": "YOUR_CANVAS_AUTH_TOKEN",
    "features": {
      "pushNotifications": true,
      "tradeConfirmation": true,
      "portfolioDashboard": true,
      "voiceCommands": true
    }
  }
}
```

### 6.3. Установка Canvas App

1. Скачать **OpenClaw Canvas** из App Store (iOS) или Google Play (Android)
2. Открыть приложение → Settings → Add Gateway
3. Ввести:
   - **Gateway URL:** `https://trading.yourdomain.com`
   - **Auth Token:** (из openclaw.json → canvas.authToken)
4. Подключиться → Должен появиться dashboard

### 6.4. Настройка Push-уведомлений для Canvas

В Master Orchestrator агенте, при отправке торговых сигналов,
OpenClaw автоматически пушит уведомления на Canvas если он подключён.

Для кастомизации формата push-уведомлений:

```json
{
  "canvas": {
    "notifications": {
      "trade_signal": {
        "title": "Trading Signal: {ticker}",
        "body": "Score: {score}/100 | {recommendation}",
        "actions": ["BUY", "SKIP"],
        "priority": "high",
        "sound": "alert"
      },
      "position_closed": {
        "title": "{ticker} Closed",
        "body": "P&L: {pnl_percent}% (${pnl_amount})",
        "priority": "normal"
      },
      "self_learning": {
        "title": "Improvement Suggested",
        "body": "{description}",
        "actions": ["Review", "Dismiss"],
        "priority": "low"
      }
    }
  }
}
```

### 6.5. Canvas Dashboard Widgets

После подключения Canvas, доступны виджеты:

| Виджет | Данные | Обновление |
|---|---|---|
| Portfolio Value | Текущая стоимость портфеля | Реальное время |
| Open Positions | Список открытых позиций с PnL | Каждые 5 мин |
| Today's Signals | BUY/HOLD/SKIP сигналы дня | После скоринга |
| Win Rate | Процент выигрышных сделок (MTD) | Ежедневно |
| Self-Learning | Последние предложения улучшений | Еженедельно |
| Agent Status | Статус каждого агента | Реальное время |

---

## Фаза 7: Self-Learning System (Самообучение)

### Архитектура самообучения

```
[Закрытая сделка] → [Триггер: trade_closed]
                           ↓
              [Self-Learning Agent (Agent-7)]
                           ↓
              [Реконструкция цепочки данных]
              [Сравнение прогноз vs результат]
              [Поиск слабых звеньев]
              [Обнаружение паттернов (weekly)]
                           ↓
              [Генерация улучшенного кода (Skills)]
                           ↓
              [Уведомление пользователю]
              ┌────────────────────────────┐
              │ 📝 Предложено улучшение:    │
              │ Dynamic ATR Stop-Loss       │
              │                             │
              │ [Применить] [Отклонить]     │
              └────────────────────────────┘
                           ↓
              [Пользователь одобряет]
                           ↓
              [Код применяется к системе]
              [Логирование в БД]
```

### Жизненный цикл улучшения

1. **Обнаружение** — Agent-7 находит проблему
2. **Диагностика** — определяет конкретный скрипт/функцию
3. **Генерация** — создаёт Python-код решения
4. **Презентация** — отправляет пользователю через Telegram/Canvas
5. **Одобрение** — пользователь принимает или отклоняет
6. **Применение** — код интегрируется в систему
7. **Валидация** — на следующей неделе проверяется эффект

### Типы улучшений

| Тип | Пример | Автоматизация |
|---|---|---|
| **Параметры** | STOP_LOSS: 5% → 7% | .env изменение |
| **Скоринг** | Новый фактор оценки | Python функция |
| **Риск** | Динамический стоп на ATR | Python функция |
| **Фильтрация** | Секторный пенальти | Scoring modifier |
| **Тайминг** | Сдвиг входа на 10:30 | Cron изменение |

### Пример полного цикла самообучения

```
Неделя 1:
  - 5 сделок, 3 wins, 2 losses (WR=60%)
  - Оба лосса: stop-loss на высоко-волатильных акциях
  - Agent-7 анализ: "Stop-loss слишком тесный для ATR > 5"

  📊 Предложение #1:
  Заменить фиксированный STOP_LOSS=-5%
  на dynamic_stop = max(-5%, -(1.5 * ATR))
  Ожидаемый эффект: снижение false stop-outs на ~30%

  → Пользователь: "apply improvement 1"
  → Код применён

Неделя 2:
  - 6 сделок, 5 wins, 1 loss (WR=83%)
  - Ни один stop-loss не сработал ложно
  - Agent-7: "Улучшение #1 показало +23% к WR"
  - Новое предложение: добавить momentum confirmation к volume scoring

  → Цикл повторяется...
```

---

## Чеклист финального запуска

### Перед запуском (один раз)

- [ ] VPS настроен (firewall, пользователь, пакеты)
- [ ] Docker + Docker Compose установлены
- [ ] Node.js 22+ установлен
- [ ] OpenClaw установлен и работает
- [ ] PostgreSQL запущен через Docker Compose
- [ ] .env файл заполнен реальными значениями
- [ ] Telegram бот создан (@BotFather) и токен в .env
- [ ] IBKR Gateway установлен и настроен (paper trading)
- [ ] Python venv создан, зависимости установлены
- [ ] База данных инициализирована (init.sql + db_utils.py)
- [ ] SEC RSS Monitor запущен
- [ ] OpenClaw cron jobs настроены
- [ ] Тестовый pipeline прошёл успешно

### Ежедневная проверка (автоматизирована)

- [ ] OpenClaw Gateway online
- [ ] PostgreSQL доступен
- [ ] IBKR Gateway подключён
- [ ] Cron jobs выполняются по расписанию
- [ ] Telegram уведомления приходят

### Фаза 2 → Фаза 3 переход (ручной)

- [ ] WR > 65% за 2 недели paper trading
- [ ] Переключить IBKR_PORT с 7497 на 7496 (live)
- [ ] Уменьшить RISK_PER_TRADE до 0.01 (1%) на первую неделю
- [ ] Подключить Canvas (если нужно)
- [ ] Включить Self-Learning автоанализ

---

## Troubleshooting

### OpenClaw не запускается
```bash
openclaw gateway logs          # Посмотреть логи
openclaw config validate       # Проверить конфигурацию
node --version                 # Node >= 22?
```

### IBKR не подключается
```bash
# Проверить что IB Gateway запущен
ps aux | grep ibgateway

# Проверить порт
ss -tlnp | grep 7497

# Проверить подключение
python3 -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1', 7497, 99); print('OK'); ib.disconnect()"
```

### PostgreSQL ошибки
```bash
docker compose logs postgres
docker compose exec postgres psql -U trading_bot -d trading_bot -c "\dt"
```

### SEC API ошибки
```bash
# SEC требует корректный User-Agent
curl -H "User-Agent: trading-bot your@email.com" \
  "https://efts.sec.gov/LATEST/search-index?q=AAPL&forms=8-K"
```

### Pipeline не запускается по расписанию
```bash
openclaw cron list             # Все ли crons активны?
openclaw cron logs             # Логи последних запусков
# Проверить timezone — все crons в UTC!
date -u                        # Текущее UTC время
```
