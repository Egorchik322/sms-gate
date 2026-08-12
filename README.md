# SMS Gateway

Домашний SMS-шлюз для Huawei E3272 / MegaFon M100-4. Шлюз принимает SMS через Gammu SMSD, сохраняет их в локальное durable-хранилище, записывает сообщения в SQLite и доставляет уведомления в Telegram и VK через независимые очереди.

## Архитектура

```text
Huawei E3272
    |
    v
Gammu SMSD + FILES spool
    |
    v
Python gateway
    |
    +--> SQLite messages/deliveries
    |
    +--> Telegram через HTTP/HTTPS proxy
    |
    +--> VK напрямую через https://api.vk.com
```

Основные свойства:

- один `gammu-smsd` является владельцем выбранного serial-порта;
- Gammu FILES backend сохраняет входящие SMS до обработки приложением;
- multipart и Unicode обрабатываются на границе Gammu;
- прикладная SQLite использует WAL, foreign keys и busy timeout;
- для каждой SMS создаются независимые delivery-записи Telegram и VK;
- модель доставки: at-least-once;
- ошибка Telegram не блокирует VK и наоборот;
- повторные Telegram `update_id` не выполняют команды повторно;
- управляющие Telegram-команды доступны только whitelist-пользователям и настроенному чату;
- автоматический reset модема и повторная регистрация отключены.

Подробности находятся в [`docs/architecture.md`](docs/architecture.md) и ADR [`docs/adr/0001-files-backend.md`](docs/adr/0001-files-backend.md).

## Сетевая политика

### Telegram

Telegram использует только proxy из окружения:

- `HTTP_PROXY_URL`;
- `HTTPS_PROXY_URL`.

Если proxy не настроен, Telegram получает configuration error. Прямой fallback запрещён.

### VK

VK используется только для исходящих уведомлений и работает напрямую по фиксированному endpoint:

```text
https://api.vk.com/method/messages.send
```

VK не использует proxy. Endpoint нельзя переопределить через `.env`.

## Требования

- Debian 12;
- Docker Engine и Docker Compose plugin;
- Gammu SMSD 1.42.x;
- Huawei E3272 / MegaFon M100-4 или совместимый AT-модем;
- доступный HTTP proxy для Telegram;
- USB passthrough модема в VM;
- стабильный device path, например `/dev/huawei-e3272-sms`.

Установка Docker/Gammu и ручные операции с USB описаны в [`docs/deployment.md`](docs/deployment.md).

## Конфигурация

Создайте локальный файл `.env` из шаблона:

```sh
cp .env.example .env
chmod 600 .env
```

Заполните значения на сервере:

```dotenv
MODEM_DEVICE=/dev/huawei-e3272-sms
MODEM_HOST_DEVICE=/dev/ttyUSB0

TELEGRAM_BOT_TOKEN=replace-with-real-token
TELEGRAM_CHAT_ID=replace-with-chat-id
TELEGRAM_ALLOWED_USER_IDS=replace-with-user-id

VK_TOKEN=replace-with-community-token
VK_PEER_ID=replace-with-numeric-peer-id

HTTP_PROXY_URL=http://proxy.example.invalid:3128
HTTPS_PROXY_URL=http://proxy.example.invalid:3128

DATABASE_PATH=/data/gateway.sqlite3
TZ=UTC
MODEM_REREGISTRATION_ENABLED=false
DIALOUT_GID=20
GATEWAY_DEVELOPMENT_MODE=false
```

`MODEM_HOST_DEVICE` используется Compose для передачи реального host-порта в контейнер. `MODEM_DEVICE` является путём, который видит Gammu внутри контейнера.

Не публикуйте `.env`, токены, приватные ключи, OTP или содержимое SMS. Файл `.env` исключён из Git.

## Получение Telegram chat ID

1. Откройте своего бота в Telegram.
2. Отправьте ему `/start`.
3. Выполните на VM запрос `getUpdates` через настроенный proxy.

Пример безопасного скрипта находится в эксплуатационных инструкциях. Полученный `chat_id` указывается в `TELEGRAM_CHAT_ID`, а ID разрешённых пользователей в `TELEGRAM_ALLOWED_USER_IDS`.

## Получение VK peer ID

Для личного диалога используется числовой ID пользователя VK.

Для групповой беседы используется значение:

```text
peer_id = 2000000000 + chat_id
```

В `.env` указывается только число, не URL профиля и не ID сообщества.

Community token должен иметь право отправлять сообщения, а пользователь обычно должен предварительно открыть диалог с сообществом.

## Подготовка модема

На host/VM оператор вручную выполняет:

1. USB passthrough модема в VM.
2. Проверку USB ID:
   - до переключения: `12d1:14fe`;
   - после переключения: `12d1:1506`.
3. При необходимости `usb_modeswitch`.
4. Определение SMS/AT-порта `/dev/ttyUSB0` или `/dev/ttyUSB1`.
5. Создание udev symlink `/dev/huawei-e3272-sms`.
6. Отключение host-службы `gammu-smsd`, чтобы только контейнер владел AT-портом.

Проверка SIM и регистрации выполняется оператором вручную:

```text
AT+CPIN?
AT+CEREG?
AT+CREG?
AT+CSQ
AT+COPS?
```

Ожидаемые признаки:

- `+CPIN: READY`;
- `+CREG: 0,1` или `+CREG: 0,5`;
- `+CSQ` не равен `99,99`.

Не используйте второй serial-порт для healthcheck. Автоматические AT reset, USB reset и повторная регистрация в проекте не реализованы.

## Запуск

Проверить конфигурацию без вывода раскрытых переменных:

```sh
sudo docker compose config --quiet
```

Собрать образ:

```sh
sudo docker compose build
```

Запустить контейнер:

```sh
sudo docker compose up -d
sudo docker compose ps
```

Проверить health:

```sh
CONTAINER_ID=$(sudo docker compose ps -q sms-gateway)
sudo docker inspect \
  --format '{{.State.Health.Status}}' \
  "$CONTAINER_ID"
```

Ожидается:

```text
healthy
```

## Тесты

Unit-тесты не используют физический модем, реальные Telegram/VK API или рабочий proxy:

```sh
PYTHONPATH=. python3 -m pytest -p no:cacheprovider -q
python3 -m py_compile app/*.py tests/*.py
sh -n scripts/entrypoint.sh scripts/healthcheck.sh
```

В тестах покрыты:

- латиница, кириллица и китайский текст;
- multipart SMS;
- идемпотентная ingestion;
- одинаковые sender/text как разные SMS;
- независимые Telegram/VK queues;
- retry, exponential backoff и `Retry-After`;
- Telegram whitelist и повторные `update_id`;
- outage/recovery без спама;
- Telegram proxy policy;
- прямой VK endpoint и form-encoded API request;
- JSON-ошибки API при HTTP 200;
- отсутствие SMS body и секретов в логах.

## Development SMS injection

Безопасный тестовый инжектор работает только в development mode:

```sh
GATEWAY_DEVELOPMENT_MODE=true \
python3 scripts/inject_test_sms.py \
  --inbox data/gammu/inbox \
  --text 'fictional development SMS'
```

Инжектор не обращается к модему и внешним API.

## Диагностика

Безопасные логи:

```sh
sudo docker compose logs -f --tail=100 sms-gateway
```

Агрегаты очередей без вывода body SMS:

```sh
sudo docker compose exec sms-gateway \
  python3 -c '
import os
import sqlite3

path = os.environ.get("DATABASE_PATH", "/data/gateway.sqlite3")
with sqlite3.connect(path) as db:
    print(db.execute("select count(*) from messages").fetchone()[0])
    print(db.execute(
        "select channel,status,count(*) from deliveries "
        "group by channel,status order by channel,status"
    ).fetchall())
'
```

Не используйте обычную диагностику с `select text from messages`: body SMS может содержать OTP и персональные данные.

## Файлы проекта

- `app/` — Python gateway;
- `migrations/` — SQLite schema;
- `config/gammu-smsdrc.template` — Gammu FILES configuration;
- `scripts/entrypoint.sh` — запуск и остановка двух процессов;
- `scripts/healthcheck.sh` — проверка процессов и SQLite;
- `compose.yml` — контейнеризация;
- `tests/` — unit-тесты;
- `docs/` — архитектура и эксплуатационные инструкции;
- `data/` — persistent spool, архив и SQLite runtime data.

## Безопасность

Не добавляйте в Git:

- `.env`;
- Telegram/VK tokens;
- proxy credentials;
- private SSH keys;
- OTP и body SMS;
- SQLite database и runtime spool.

Не используйте:

```sh
git add -f .env
docker compose down -v
docker system prune
git push --force
```

Перед публикацией проверьте:

```sh
git check-ignore -v .env
git ls-files .env
```

`git ls-files .env` не должен выводить ничего.

## Документация

- [Архитектура](docs/architecture.md)
- [ADR выбора Gammu FILES backend](docs/adr/0001-files-backend.md)
- [Развёртывание](docs/deployment.md)
- [Тестирование](docs/testing.md)
- [Эксплуатация](docs/operations.md)
