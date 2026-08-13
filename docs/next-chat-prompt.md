# Промпт для продолжения SMS Gateway в новом чате

Скопируй этот текст в новый чат:

```text
Ты продолжаешь разработку проекта sms-gateway.

## Окружение

Работай только через MCP SSH profile `smsgw01`:

- hostname: `smsgw01`
- VMID: `104`
- IP: `192.168.0.15`
- пользователь для SSH: `devagent`
- проект: `/workspace/sms-gateway`

Не используй другие машины, SSH-профили, Proxmox API, локальный компьютер пользователя или сетевое сканирование.

В начале проверь:

```sh
hostname
whoami
pwd
cd /workspace/sms-gateway
git status --short --branch
```

## Git и публикация

GitHub repository уже создан:

```text
git@github.com:Egorchik322/sms-gate.git
```

Пока не выполнять:

- `git commit`;
- `git push`;
- force push;
- публикацию Docker image;
- изменение remote без отдельного разрешения.

Пользователь отдельно скажет, когда подготовить commit и push. Не добавляй строку `Co-Authored-By` в commit message.

Перед любым будущим commit проверяй, что в staging нет:

- `.env`;
- SQLite database, WAL/SHM;
- runtime spool;
- токенов, private keys, Authorization headers и proxy credentials.

## Секреты

Настоящий `.env` находится на VM в:

```text
/workspace/sms-gateway/.env
```

Не читай и не выводи содержимое `.env`. Допустимы только проверки наличия переменных без значений.

Не проси пользователя отправлять токены, PAT, private keys или содержимое `.env` в чат.

## Текущая архитектура

```text
Huawei E3272 -> gammu-smsd -> Gammu FILES spool -> Python gateway -> SQLite
                                                       |-> Telegram через HTTP/HTTPS proxy
                                                       |-> VK напрямую через https://api.vk.com
```

- `gammu-smsd` является единственным владельцем выбранного AT-порта.
- Host `gammu-smsd.service` должен быть отключён, чтобы не конкурировать с контейнером.
- В Compose host `/dev/ttyUSB0` передаётся в контейнер как `/dev/huawei-e3272-sms` через `MODEM_HOST_DEVICE` и `MODEM_DEVICE`.
- Не передавай весь `/dev/bus/usb`.
- Не используй `privileged`, `NET_ADMIN`, host network или Docker socket.
- Не открывай второй AT-порт для healthcheck.

## Сетевые правила

Telegram:

- только через `HTTP_PROXY_URL` и `HTTPS_PROXY_URL`;
- прямой fallback запрещён;
- endpoint фиксирован в коде `https://api.telegram.org`;
- long polling;
- inline buttons через `callback_query`.

VK:

- только исходящие уведомления;
- прямой HTTPS без proxy разрешён осознанно;
- endpoint фиксирован: `https://api.vk.com/method/messages.send`;
- параметры отправляются `application/x-www-form-urlencoded`;
- JSON API error при HTTP 200 не считать успешной доставкой;
- токен только из окружения;
- endpoint нельзя переопределить через `.env`.

Реальные Telegram/VK API не запускать в тестах и не вызывать без явного указания пользователя.

## Уже реализовано

Основные файлы:

- `app/store.py` — SQLite, WAL, foreign keys, busy timeout, messages, deliveries, bot_updates, modem_status, outage_state;
- `app/ingress.py` — Gammu FILES ingestion, multipart, Unicode, идемпотентность;
- `app/delivery.py` — независимые очереди и retry;
- `app/http_transports.py` — Telegram proxy transport и прямой VK transport;
- `app/control.py` — Telegram whitelist, callback allowlist `smsgw:v1:<action>`, inline keyboard, status rendering;
- `app/polling.py` — long polling, callback_query, answerCallbackQuery, editMessageText и fallback;
- `app/gammu_status.py` — read-only parser `gammu-smsd-monitor`;
- `app/cpms.py` — read-only `AT+CPMS?` через SIGUSR1/SIGUSR2 паузу Gammu; автоматическое удаление SMS запрещено;
- `app/main.py` — runtime ingestion, workers, polling и monitor snapshot;
- `migrations/001_initial.sql` — SQLite schema;
- `compose.yml`, `Dockerfile`, `scripts/entrypoint.sh`, `scripts/healthcheck.sh` — контейнеризация.

Telegram menu:

```text
[ Состояние ] [ Полная информация ]
[ Последние SMS ]
[ Доставка ] [ Обновить ]
```

Проверка callback/user/chat выполняется до action. `update_id` сохраняется до действия. Повторная регистрация отключена по умолчанию и не содержит AT-команд.

## Известное текущее состояние

AT-проверка ранее дала:

```text
AT+CPIN?  -> +CPIN: READY
AT+CREG?  -> +CREG: 0,5
AT+CSQ    -> +CSQ: 18,255
AT+COPS?  -> оператор t2 rus
```

SIM зарегистрирована в роуминге и SMS принимались. Telegram-доставка уже проверялась в рабочем окружении. VK transport исправлялся после ошибки API-конфигурации; при проверке новой версии используй новую тестовую SMS, не переотправляй старые `sent`-доставки автоматически.

`gammu-smsd-monitor` Gammu 1.42 возвращает signal в процентах 0–100 и счётчики. Оператор, технология, регистрация и raw CSQ получают отдельным read-only snapshot через контролируемую паузу Gammu.

Текущий ожидаемый статус после пересоздания:

```text
Состояние шлюза

Устройство: да
Gammu SMSD: да
Оператор: имя из radio snapshot или нет данных
Код сети: numeric code или нет данных
Сигнал: N/100; Сырой CSQ: N/31; оператор, технология, регистрация и актуальность snapshot
Последняя SMS: timestamp или нет данных
SMS принято: число
SMS отправлено: число
```

Батарею, ошибки Gammu и время последнего контакта в Telegram показывать не нужно.

## Следующие шаги

1. Проверить Git status и наличие только локальных изменений.
2. Запустить локальные проверки:

```sh
cd /workspace/sms-gateway
PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider
python3 -m py_compile app/*.py tests/*.py
sh -n scripts/entrypoint.sh scripts/healthcheck.sh scripts/resolve_modem_device.sh scripts/modem-compose-supervisor.sh
```

3. Пересобрать образ:

```sh
sudo docker compose config --quiet
sudo docker compose build
```

4. После явного согласия/команды пользователя пересоздать контейнер:

```sh
sudo docker compose up -d --build --force-recreate
sleep 30
sudo docker compose ps
```

5. Проверить безопасными агрегатами:

- контейнер `running`, `healthy`, restart count;
- процессы `gammu-smsd` и `python3 -m app.main`;
- device mapping `/dev/ttyUSB0 -> /dev/huawei-e3272-sms`;
- Gammu monitor CSV без вывода IMEI;
- `modem_status.signal_percent`, `sent_count`, `received_count`, `last_received_at`;
 - `modem_status.sim_storage_used/capacity/free/percent/checked_at`, radio fields и timestamps актуальности; компактный `Состояние` и расширенная `Полная информация`; общий интервал задаётся `MODEM_STATUS_CHECK_INTERVAL_SECONDS`;
- delivery statuses Telegram/VK;
- отсутствие SMS body, токенов и Authorization headers в логах.

6. В Telegram нажать `/start`, затем `Состояние`, `Последние SMS`, `Доставка`, `Обновить`. Проверять, что ответы содержат реальные SQLite-данные, а не только названия action.

7. Не выполнять реальные AT-команды, reset, USB reset или регистрацию автоматически. Для ручной AT-проверки остановку контейнера и команды выполняет оператор.

## Коммуникация

Отвечай на русском. В каждом отчёте указывай:

- изменённые файлы;
- команды проверок;
- что прошло/не прошло;
- что остаётся непроверенным;
- что требуется от пользователя.

Не объявляй проект полностью готовым, пока runtime, Telegram/VK deliveries, modem status и тесты не подтверждены фактическими проверками.
```
