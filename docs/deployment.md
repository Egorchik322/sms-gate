# Развёртывание

Все команды, меняющие VM, Docker, USB passthrough, host udev или системные службы, выполняются вручную оператором.

## Подготовка Debian 12

Выполняется вручную оператором:

```sh
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker <оператор>
```

Создайте VM и передайте USB-модем операторскими средствами гипервизора. Не используйте эти команды из контейнера.

## USB и стабильный device path

`/dev/serial/by-id` не используется как источник истины для Huawei E3272: у текущего устройства нет аппаратного USB serial number, поэтому ссылка может быть общей для `HUAWEI Mobile` и меняться при USB composition.

Resolver `scripts/resolve_modem_device.sh` выбирает текущий `/dev/ttyUSB*` по read-only udev-атрибутам:

- физический USB-путь `MODEM_USB_PATH`;
- `MODEM_VENDOR_ID`;
- один или несколько `MODEM_PRODUCT_IDS`, разделённых запятыми;
- номер интерфейса `MODEM_INTERFACE_NUM`;
- драйвер `option`.

На текущей VM подтверждено:

```text
MODEM_USB_PATH=pci-0000:02:1b.0-usb-0:1
MODEM_VENDOR_ID=12d1
MODEM_PRODUCT_IDS=1506
MODEM_INTERFACE_NUM=00
```

Проверка resolver безопасна и не открывает AT-порт:

```sh
MODEM_USB_PATH=pci-0000:02:1b.0-usb-0:1 \
MODEM_VENDOR_ID=12d1 MODEM_PRODUCT_IDS=1506 MODEM_INTERFACE_NUM=00 \
./scripts/resolve_modem_device.sh
```

Создание udev symlink `/dev/huawei-e3272-sms` можно оставить для ручной диагностики, но Compose должен получать реальный host device, найденный resolverом. Не открывайте второй AT-порт для healthcheck.

## Контроль SIM SMS storage

Gateway периодически выполняет read-only `AT+CPMS?` с интервалом `MODEM_STATUS_CHECK_INTERVAL_SECONDS` (по умолчанию 300 секунд; один общий сеанс radio+SIM через SIGUSR1/SIGUSR2).

Второй постоянный AT-клиент не используется. Перед запросом gateway отправляет фактическому `gammu-smsd` сигнал `SIGUSR1`; Gammu закрывает соединение с модемом, затем gateway выполняет только `AT+CPMS?`, закрывает serial-порт и отправляет `SIGUSR2` для возобновления SMSD.

Запрос:

- не читает текст SMS;
- не выполняет `AT+CMGL`, `AT+CMGR` или `AT+CMGD`;
- не удаляет сообщения автоматически;
- при ошибке возвращает Gammu в работу через `finally`;
- сохраняет последнее успешное значение в SQLite.

В Telegram отображаются:

```text
Память SIM (SM): 50/50
Свободно SIM: 0
Заполнение SIM: 100% (переполнена)
```

Пороговые уровни:

- менее 80%: `норма`;
- 80–94%: `предупреждение`;
- 95–99%: `критично`;
- 100%: `переполнена`.

Автоматическая очистка SIM-памяти запрещена. Старые SMS удаляются оператором вручную после проверки, что они больше не нужны.

## Hotplug supervisor

`scripts/modem-compose-supervisor.sh` управляет host device mapping и запускает `docker compose up -d --force-recreate`, когда появляется подходящий интерфейс или меняется USB identity. Он работает на host/VM, а не внутри Compose-контейнера: передача Docker socket в контейнер не требуется и не используется.

Для постоянной работы после reboot используйте systemd unit из `deploy/systemd/sms-gateway-modem-supervisor.service`.

Установка unit меняет `/etc/systemd/system` и выполняется оператором с `sudo`:

```sh
sudo install -m 0644 \
  deploy/systemd/sms-gateway-modem-supervisor.service \
  /etc/systemd/system/sms-gateway-modem-supervisor.service
sudo systemctl daemon-reload
sudo systemctl enable --now sms-gateway-modem-supervisor.service
sudo systemctl status sms-gateway-modem-supervisor.service
```

Проверка логов:

```sh
sudo journalctl -u sms-gateway-modem-supervisor.service -n 100 --no-pager
```

Unit запускается после `docker.service`, перезапускается systemd при завершении и передаёт только hardware metadata: USB path, VID/PID и interface number. Секреты приложения в unit не хранятся.

Если systemd unit ещё не установлен, supervisor можно запустить вручную для диагностики:

```sh
cd /workspace/sms-gateway
MODEM_USB_PATH=pci-0000:02:1b.0-usb-0:1 \
MODEM_VENDOR_ID=12d1 MODEM_PRODUCT_IDS=1506 MODEM_INTERFACE_NUM=00 \
./scripts/modem-compose-supervisor.sh
```

## Конфигурация

Скопируйте `.env.example` в `.env` вручную оператором и заполните только реальные значения на VM. Настройте `MODEM_DEVICE`, `MODEM_HOST_DEVICE`, параметры resolver, `MODEM_STATUS_CHECK_INTERVAL_SECONDS`, proxy URL для Telegram, Telegram параметры, VK параметры и numeric `DIALOUT_GID`. VK использует прямой HTTPS и не использует proxy. Настоящий `.env` не хранится в репозитории.

Рекомендуемые значения для текущего модема:

```dotenv
MODEM_DEVICE=/dev/huawei-e3272-sms
MODEM_USB_PATH=pci-0000:02:1b.0-usb-0:1
MODEM_VENDOR_ID=12d1
MODEM_PRODUCT_IDS=1506
MODEM_INTERFACE_NUM=00
MODEM_STATUS_CHECK_INTERVAL_SECONDS=300
```

`MODEM_HOST_DEVICE` задаётся supervisorом из результата resolver. Если Compose запускается вручную без supervisor, его можно временно задать равным найденному `/dev/ttyUSB*`.

## Запуск

Выполняется вручную оператором после проверки device path и proxy Telegram:

```sh
docker compose --env-file .env config --quiet
docker compose --env-file .env build
docker compose --env-file .env up -d --force-recreate
```

Compose использует один serial device, persistent `./data`, non-root gateway, `restart: unless-stopped`, local log rotation и healthcheck gateway плюс SQLite. Потеря Gammu не делает контейнер unhealthy: Python gateway продолжает Telegram polling, а entrypoint повторно запускает `gammu-smsd` с задержкой.
