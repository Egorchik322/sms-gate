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

Healthcheck контейнера проверяет PID `gammu-smsd`, PID gateway и доступность SQLite. Доступность modem path и размеры Telegram/VK очередей хранятся в прикладном health-слое. Для безопасной диагностики используйте SQL только с агрегатами:

```sh
sqlite3 data/gateway.sqlite3 "select channel,status,count(*) from deliveries group by channel,status;"
```

Не выводите `messages.text` при обычной диагностике.

## Сетевая политика

Telegram требует `HTTP_PROXY_URL` и `HTTPS_PROXY_URL`; без них доставки переходят в configuration error. VK использует прямой HTTPS к фиксированному `https://api.vk.com/method/messages.send` и намеренно не использует proxy. Endpoint VK не переопределяется через окружение.

## Backup и очистка

Выполняется вручную оператором. Остановите контейнер перед консистентным backup SQLite и сохраните `data/gateway.sqlite3` вместе с WAL/SHM и Gammu spool. Старую историю удаляйте только отдельной согласованной операцией; не удаляйте записи со статусами `pending` и `retry`.

Не выполняйте автоматический USB reset, AT reset или повторную регистрацию. Feature flag `MODEM_REREGISTRATION_ENABLED` выключен по умолчанию.
