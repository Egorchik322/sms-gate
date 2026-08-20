# SMS Gateway

Домашний SMS-шлюз для Huawei E3272 / MegaFon M100-4. Шлюз принимает SMS через Gammu SMSD, сохраняет их в durable FILES spool и SQLite, а затем доставляет уведомления в Telegram и VK через независимые очереди.

## Состояние проекта

Проект разворачивается на VM `smsgw01` в каталоге `/workspace/sms-gateway`.

Текущая рабочая схема проверена на Gammu 1.42 и Huawei E3272:

```text
Huawei E3272
    |
    v
Gammu SMSD 1.42
    |  единственный владелец serial-порта
    +--> FILES spool
    |
    +--> shared memory status
             |
             v
Python gateway + C-helper
    |
    +--> SQLite messages/deliveries/modem_status
    +--> Telegram через HTTP/HTTPS proxy
    +--> VK через прямой HTTPS
```

Проверенные свойства:

- контейнер `running` и `healthy`;
- systemd supervisor `enabled` и `active`;
- Docker restart policy `unless-stopped`;
- device mapping переживает перенумерацию `ttyUSB*`;
- `gammu-smsd` остаётся единственным владельцем модема;
- C-helper читает shared memory SMSD и не открывает `/dev/ttyUSB*`;
- proxy-разрыв Telegram не завершает gateway;
- stale/zombie PID не считается здоровым процессом;
- локальные тесты: `60 passed`.

Последний опубликованный локальный commit перед экспериментами C-helper:

```text
21c852b Improve modem lifecycle and shared status monitoring
```

Экспериментальная C-helper версия находится поверх него в локальной ветке. GitHub push выполняется отдельно после проверки credentials.

## Gammu shared status

C-helper `helpers/gammu-smsd-status.c` использует официальный API:

```text
SMSD_ReadConfig()
SMSD_GetStatus()
SMSD_FreeConfig()
```

Он читает shared memory уже работающего `gammu-smsd` и получает:

```text
signal_percent
signal_dbm
bit_error_percent
network_name
network_code
network_state
GPRS state
packet state
LAC/CID
packet LAC/CID
sent/received/failed counters
```

Пример фактического статуса для текущей SIM:

```text
Оператор: beeline
Код сети: 250 99
Сигнал: 63/100
Сигнал dBm: -71
Регистрация: roaming
GPRS: attached
```

Это не второй AT-клиент: C-helper не открывает serial device и не конкурирует с SMSD.

`python3-gammu` остаётся fallback для shared-memory status. `gammu-smsd-monitor` используется как дополнительный fallback, если C-helper или Python binding недоступны.

## Telegram

`/start` открывает inline-меню:

```text
[ Состояние ] [ Полная информация ]
[ Последние SMS ]
[ Доставка ] [ Обновить ]
```

`Состояние` показывает компактный live-статус:

```text
Устройство: да
Gammu SMSD: да
Сигнал: N/100
Последняя SMS: timestamp
SMS принято: N
SMS отправлено: N
Обновлено: timestamp и возраст
```

`Полная информация` дополнительно показывает данные C-helper:

```text
Оператор
Код сети
Регистрация
Сигнал в процентах
Сигнал dBm
BER
LAC/CID
GPRS state
Packet state
Packet LAC/CID
Актуальность snapshot-а
```

Callback-данные имеют формат `smsgw:v1:<action>`. Все callback и текстовые команды проходят whitelist-проверку пользователя и чата. Повторные `update_id` не выполняются повторно.

## USB и resolver

Не используйте постоянную привязку к `/dev/ttyUSB0`, `/dev/ttyUSB1` или `/dev/serial/by-id`.

У текущего Huawei E3272 нет уникального аппаратного USB serial number. Поэтому resolver `scripts/resolve_modem_device.sh` ищет AT-интерфейс по стабильным атрибутам:

```text
VID: 12d1
PID: 1506
USB interface: 00
Driver: option
```

`MODEM_USB_PATH` необязателен. Если он задан, это предпочтительный физический путь; при отсутствии совпадения resolver использует fallback по VID/PID/interface/driver.

При одном модеме resolver возвращает единственный подходящий `/dev/ttyUSB*`. Если найдено несколько одинаковых AT-интерфейсов, он завершается с ошибкой вместо случайного выбора.

Внутри контейнера Gammu всегда получает стабильный путь:

```text
/dev/huawei-e3272-sms
```

Проектное udev-правило находится в:

```text
deploy/udev/99-huawei-e3272-sms.rules
```

Оно не фиксирует `ID_PATH`, поэтому перенос модема в другой физический USB-порт не ломает alias.

## Автозапуск

Host supervisor запускается systemd unit:

```text
deploy/systemd/sms-gateway-modem-supervisor.service
```

Unit:

- запускается после `docker.service`;
- имеет `Restart=always`;
- включён через `systemctl enable`;
- повторно вызывает resolver;
- передаёт найденный host tty в Compose;
- пересоздаёт сервис при изменении USB identity;
- не требует Docker socket внутри контейнера.

Проверка:

```sh
sudo systemctl status sms-gateway-modem-supervisor.service --no-pager
sudo journalctl -u sms-gateway-modem-supervisor.service -n 100 --no-pager
```

Ожидается:

```text
Active: active (running)
Loaded: enabled
```

## Конфигурация

Создайте `.env` из шаблона:

```sh
cp .env.example .env
chmod 600 .env
```

Ключевые параметры:

```dotenv
MODEM_DEVICE=/dev/huawei-e3272-sms
MODEM_USB_PATH=
MODEM_VENDOR_ID=12d1
MODEM_PRODUCT_IDS=1506
MODEM_INTERFACE_NUM=00
MODEM_STATUS_AT_ENABLED=false
MODEM_STATUS_CHECK_INTERVAL_SECONDS=300
```

`MODEM_STATUS_AT_ENABLED=false` оставляет опасный serial AT snapshot выключенным. Для текущего модема подробные radio/SIM данные получаются через Gammu shared memory и C-helper, поэтому второй AT-клиент не нужен.

Остальные обязательные параметры:

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_ALLOWED_USER_IDS=...
HTTP_PROXY_URL=http://proxy.example.invalid:3128
HTTPS_PROXY_URL=http://proxy.example.invalid:3128
VK_TOKEN=...
VK_PEER_ID=...
DIALOUT_GID=20
```

`.env`, токены, ключи, SQLite и spool не хранятся в Git.

## Запуск и восстановление

Обычный запуск выполняется через supervisor:

```sh
sudo systemctl start sms-gateway-modem-supervisor.service
```

Supervisor сам запускает Compose с актуальным host device.

Compose имеет:

```yaml
restart: unless-stopped
```

Поэтому контейнер автоматически перезапускается после падения и после старта Docker. Python gateway также переживает временный разрыв Telegram proxy, а healthcheck отклоняет stale/zombie PID.

## Ручная AT-диагностика

AT-команды можно выполнять только после остановки supervisor и контейнера:

```sh
sudo systemctl stop sms-gateway-modem-supervisor.service
sudo docker compose stop sms-gateway
sudo fuser -v /dev/huawei-e3272-sms
```

Используйте стабильный alias `/dev/huawei-e3272-sms`, а не номер `ttyUSB*`.

Не запускайте второй AT-клиент параллельно с `gammu-smsd`. Не выполняйте автоматически:

```text
AT+COPS=?
AT+COPS=...
AT+CFUN=1,1
AT+CMGL=...
AT+CMGR=...
AT+CMGD=...
```

После диагностики:

```sh
sudo systemctl start sms-gateway-modem-supervisor.service
```

## Сетевые политики

Telegram работает только через настроенный proxy:

```text
HTTP_PROXY_URL
HTTPS_PROXY_URL
```

Прямой fallback Telegram запрещён.

VK работает напрямую с фиксированным endpoint:

```text
https://api.vk.com/method/messages.send
```

Endpoint VK нельзя переопределить через `.env`.

## Проверки

Локальные тесты:

```sh
PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider
python3 -m py_compile app/*.py tests/*.py
sh -n scripts/entrypoint.sh scripts/healthcheck.sh scripts/resolve_modem_device.sh scripts/modem-compose-supervisor.sh
systemd-analyze verify deploy/systemd/sms-gateway-modem-supervisor.service
```

Проверка контейнера:

```sh
sudo docker inspect -f \
'status={{.State.Status}} health={{.State.Health.Status}} restarts={{.RestartCount}}' \
sms-gateway-sms-gateway-1
```

Ожидается:

```text
status=running health=healthy restarts=0
```

Не выводите `messages.text` в обычной диагностике: SMS могут содержать OTP и персональные данные.

## Продолжение работы

Для следующего чата используйте [`docs/next-chat-prompt.md`](docs/next-chat-prompt.md). В нём описаны ограничения VM, текущая архитектура, правила работы с секретами и незавершённые экспериментальные изменения.
