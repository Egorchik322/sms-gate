# Эксплуатация

## Команды

Выполняется вручную оператором:

```sh
docker compose ps
docker compose logs --tail=100 sms-gateway
docker compose restart sms-gateway
docker compose stop sms-gateway
```

Логи не должны содержать body SMS, OTP, токены, proxy credentials или Authorization headers. Для диагностики используйте message ID, channel и class ошибки.

## Health и очереди

Healthcheck контейнера проверяет только живой PID Python gateway и доступность SQLite. `gammu-smsd` намеренно не является условием Docker health: при недоступном модеме Telegram control-plane должен продолжать работу.

Прикладной статус хранит отдельные признаки `device_available` и `smsd_running`. Для PID Gammu проверяется не только наличие файла, но и существование процесса; stale PID-файл после падения не считается рабочим SMSD.

Минимальный образ не содержит CLI `sqlite3`. Для агрегированной диагностики используйте Python внутри контейнера:

```sh
docker exec sms-gateway-sms-gateway-1 python3 - <<'PY'
import sqlite3
connection = sqlite3.connect('/data/gateway.sqlite3')
print(connection.execute(
    "select channel,status,count(*) from deliveries group by channel,status"
).fetchall())
PY
```

Не выводите `messages.text` при обычной диагностике.

## Radio и актуальность

`gammu-smsd-monitor` отдаёт `signal` уже в процентах от 0 до 100. Поэтому в Telegram значение показывается так:

```text
Сигнал: 48/100
```

Дополнительно radio snapshot показывает сырой ответ модема:

```text
Сырой CSQ: 18/31
```

Для `AT+CSQ` значение `0–31` является уровнем, а `99` означает неизвестное значение. Это не нужно путать с процентом Gammu: `18/31` и `48/100` используют разные шкалы.

Gateway read-only запрашивает через контролируемую паузу SMSD:

```text
AT+CSQ
AT+COPS?
AT+CREG?
AT+CEREG?
AT+CGREG?
```

Команды не меняют регистрацию, не запускают поиск всех сетей и не выполняют reset. Оператор и network status сохраняются только после успешного snapshot.

В Telegram поле `Актуальность` показывает время последнего успешного snapshot и его возраст:

- `Gammu` — monitor signal/counters;
- `Радио` — CSQ/COPS/CREG snapshot;
- `Память SIM` — CPMS snapshot;
- `База` — последняя запись прикладного статуса.

Если snapshot старше допустимого интервала, рядом будет `устарело`. Старое значение не скрывается, но явно помечается как несвежее.

## Контроль SIM SMS storage

Gateway периодически выполняет read-only `AT+CPMS?` с интервалом `MODEM_STATUS_CHECK_INTERVAL_SECONDS` (по умолчанию 300 секунд; один общий сеанс radio+SIM через SIGUSR1/SIGUSR2).

Второй постоянный AT-клиент не используется. Перед запросом gateway отправляет фактическому `gammu-smsd` сигнал `SIGUSR1`, выполняет только `AT+CPMS?`, затем отправляет `SIGUSR2`. Запрос не читает текст SMS и не выполняет удаление.

В Telegram отображаются `used/capacity`, свободные слоты, процент и уровень:

- менее 80%: норма;
- 80–94%: предупреждение;
- 95–99%: критично;
- 100%: переполнена.

Автоматическая очистка SIM-памяти запрещена.

## Hotplug модема

После unplug/replug не нужно вручную выбирать новый `ttyUSB` или использовать `/dev/serial/by-id`. `scripts/modem-compose-supervisor.sh` повторно вызывает read-only resolver и пересоздаёт только сервис `sms-gateway`, когда найден подходящий интерфейс или меняется USB identity.

Для автозапуска после reboot используется host-side systemd unit:

```sh
sudo systemctl status sms-gateway-modem-supervisor.service
sudo journalctl -u sms-gateway-modem-supervisor.service -n 100 --no-pager
```

Unit устанавливается из `deploy/systemd/sms-gateway-modem-supervisor.service` оператором вручную. Он запускается после Docker, автоматически перезапускается systemd и не требует Docker socket внутри Compose-контейнера.

Если systemd unit ещё не установлен, supervisor можно запустить вручную для диагностики:

```sh
cd /workspace/sms-gateway
MODEM_USB_PATH=pci-0000:02:1b.0-usb-0:1 \
MODEM_VENDOR_ID=12d1 MODEM_PRODUCT_IDS=1506 MODEM_INTERFACE_NUM=00 \
./scripts/modem-compose-supervisor.sh
```

## Сетевая политика

Telegram требует `HTTP_PROXY_URL` и `HTTPS_PROXY_URL`; без них доставки переходят в configuration error. VK использует прямой HTTPS к фиксированному `https://api.vk.com/method/messages.send` и намеренно не использует proxy. Endpoint VK не переопределяется через окружение.

## Backup и очистка

Выполняется вручную. Остановите контейнер перед консистентным backup SQLite и сохраните `data/gateway.sqlite3` вместе с WAL/SHM и Gammu spool. Старую историю удаляйте только отдельной согласованной операцией; не удаляйте записи со статусами `pending` и `retry`.

Не выполняйте автоматический USB reset, AT reset или повторную регистрацию. Feature flag `MODEM_REREGISTRATION_ENABLED` выключен по умолчанию.
