# Эксплуатация

## Команды

```sh
docker compose ps
docker compose logs --tail=100 sms-gateway
docker compose restart sms-gateway
docker compose stop sms-gateway
```

## Достоверный Telegram status

В меню Telegram показываются только данные, которые стабильно получает `gammu-smsd-monitor` при работающем SMSD:

- доступность device;
- состояние Gammu SMSD;
- свежий signal в шкале `0–100`;
- счётчики принятых/отправленных SMS;
- время последней SMS;
- время обновления статуса.

`Состояние` показывает компактный оперативный статус. `Полная информация` дополнительно объясняет ограничения диагностики.

Статус signal и счётчики читаются через shared memory Gammu SMSD без открытия serial-порта. На Huawei E3272 с Gammu 1.42 автоматический AT-опрос остаётся отключён (`MODEM_STATUS_AT_ENABLED=false`): `gammu-smsd` удерживает `/dev/ttyUSB0` эксклюзивно даже после `SIGUSR1`, поэтому второй AT-клиент получает `EBUSY`. Старые operator, technology, registration, raw CSQ и SIM storage snapshots не показываются в Telegram как текущие.

Оператор, технология, raw `CSQ` и `AT+CPMS?` не входят в shared-memory status Gammu 1.42; для них нужна ручная AT-диагностика после полной остановки Gammu и контейнера. Не запускайте второй AT-клиент параллельно с SMSD.

Минимальный образ не содержит CLI `sqlite3`; агрегаты SQLite проверяйте Python внутри контейнера:

```sh
docker exec sms-gateway-sms-gateway-1 python3 -c \
"import sqlite3; c=sqlite3.connect('/data/gateway.sqlite3'); print(c.execute(\"select signal_percent,signal_checked_at from modem_status where singleton=1\").fetchone())"
```

## Hotplug модема

После unplug/replug host-side systemd supervisor повторно вызывает resolver и пересоздаёт сервис при изменении USB identity. Docker socket внутрь контейнера не пробрасывается.

```sh
sudo systemctl status sms-gateway-modem-supervisor.service
sudo journalctl -u sms-gateway-modem-supervisor.service -n 100 --no-pager
```

## Health и очереди

Healthcheck проверяет живой Python gateway и SQLite. `gammu-smsd` не является условием Docker health: Telegram control-plane должен продолжать работу при временной недоступности модема.

Логи не должны содержать SMS body, OTP, токены, proxy credentials или Authorization headers.

## Сетевая политика

Telegram использует `HTTP_PROXY_URL` и `HTTPS_PROXY_URL`. VK использует прямой HTTPS к фиксированному endpoint и не использует proxy.

## Backup и очистка

Остановите контейнер перед консистентным backup SQLite и сохраните `gateway.sqlite3` вместе с WAL/SHM и Gammu spool. Не удаляйте pending/retry deliveries.

Не выполняйте автоматический USB reset, AT reset, повторную регистрацию или автоматическое удаление SMS.
