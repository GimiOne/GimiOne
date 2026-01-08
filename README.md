## Telegram VPN Bot MVP (Xray + x-ui / 3x-ui)

MVP Telegram-бота для продажи VPN-доступа на базе Xray через HTTP API панели x-ui / 3x-ui.

### Что умеет

- **Telegram-бот (aiogram 3)**: `/start`, меню, покупка подписки (30 дней), “моя подписка”, выдача ключа
- **Один inbound → много клиентов**
- **VLESS Reality**: генерация URI + QR-код
- **SQLite**: пользователи, платежи, подписки
- **payment_mock**: заглушка оплаты со статусами и идемпотентной обработкой (по `payment_id`)
- **Авто-отключение**: фоновая задача удаляет клиента в x-ui после истечения подписки

### Структура

```
bot/
  main.py
  handlers/
  keyboards/
services/
  xui_client.py
  payments.py
db/
  models.py
config.py
```

### Быстрый старт

1) Установите зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Создайте `.env`:

```bash
cp .env.example .env
```

3) Запустите бота:

```bash
python3 -m bot.main
```

### Переменные окружения

См. `.env.example`. Ключевые:

- **`BOT_TOKEN`**: токен Telegram-бота
- **`ADMIN_TG_IDS`**: TG ID админов (через запятую). Для них бот автоматически создаёт подписку без оплаты
- **`XUI_BASE_URL`**: URL панели (должен быть доступен только локально, например `http://127.0.0.1:54321`)
- **`XUI_USERNAME` / `XUI_PASSWORD`**: учётка панели (не хранить в коде)
- **`XUI_INBOUND_ID`**: ID inbound (если не задан — бот попробует найти по `XUI_INBOUND_REMARK`, иначе возьмёт первый VLESS inbound)
- **`VPN_PUBLIC_HOST`**: домен/IP, который будет в VLESS-ссылке (для клиента)

### Пример inbound (VLESS Reality)

Ниже ориентир (настройки зависят от версии x-ui/3x-ui). Важные поля для генерации ссылки:

- `protocol`: `vless`
- `port`: публичный порт
- `streamSettings.security`: `reality`
- `streamSettings.realitySettings.publicKey`
- `streamSettings.realitySettings.shortIds`
- `streamSettings.realitySettings.serverNames`

Пример того, что бот ожидает в `streamSettings` (как JSON-строка в x-ui):

```json
{
  "network": "tcp",
  "security": "reality",
  "realitySettings": {
    "show": false,
    "dest": "www.cloudflare.com:443",
    "xver": 0,
    "serverNames": ["www.cloudflare.com"],
    "privateKey": "<PRIVATE_KEY>",
    "publicKey": "<PUBLIC_KEY>",
    "shortIds": ["a1b2c3d4"]
  }
}
```

### Пример VLESS-ссылки

Формат, который выдаёт бот:

```
vless://<UUID>@vpn.example.com:<PORT>?type=tcp&security=reality&encryption=none&flow=xtls-rprx-vision&fp=chrome&sni=www.cloudflare.com&pbk=<PUBLIC_KEY>&sid=a1b2c3d4#tg12345-abcdef12
```

### Безопасность

- **Пароли/токены только в `.env`**
- **API x-ui/3x-ui должен быть доступен только с localhost** (закрыть firewall / bind на 127.0.0.1 / reverse-proxy с allowlist)
- Создайте отдельного пользователя панели с минимально нужными правами (если поддерживается вашей сборкой)
