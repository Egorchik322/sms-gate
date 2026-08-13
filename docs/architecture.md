# Архитектура

## Поток SMS

`Huawei E3272 -> gammu-smsd -> FILES spool -> gateway -> SQLite -> независимые delivery queues`.

`gammu-smsd` является единственным постоянным владельцем одного AT-порта. Входящие SMS сначала сохраняются Gammu в durable FILES spool. Python gateway периодически группирует multipart-файлы, записывает сообщение и две delivery-записи в одной SQLite-транзакции, затем переносит обработанные файлы в архив.

Gateway не выполняет сетевые запросы в ingress-пути. Ошибка внешнего канала не удаляет принятую SMS и не блокирует вторую очередь.

## Хранение

Используется отдельная прикладная SQLite с `foreign_keys`, `busy_timeout` и WAL. `messages.source_identifier` уникален и строится по устойчивому имени Gammu-файла/группы multipart. Уникальность по `(sender, text)` намеренно не используется: два одинаковых текста являются разными SMS.

Для каждой новой SMS атомарно создаются записи `telegram` и `vk`. Доставка имеет модель at-least-once. При неоднозначном timeout внешнее API может принять запрос, а локальная очередь повторит его после рестарта.

## Telegram control plane

Telegram является control plane и единственным каналом, который требует proxy: он использует `HTTP_PROXY_URL` и `HTTPS_PROXY_URL`, а без них получает configuration error.

Текстовые команды и inline-кнопки используют одну policy:

- `TELEGRAM_ALLOWED_USER_IDS` и `TELEGRAM_CHAT_ID` проверяются до действия;
- `update_id` сохраняется в `bot_updates` до действия;
- повторный update не выполняет action повторно;
- callback data ограничена allowlist-ом `smsgw:v1:<action>`;
- callback без доступного `message.chat` отклоняется;
- `answerCallbackQuery` вызывается для разрешённых, запрещённых, неизвестных и повторных callback;
- принятое действие обновляет исходное сообщение через `editMessageText` и сохраняет inline keyboard;
- fallback на `sendMessage` выполняется только для определённой ошибки редактирования, чтобы transient timeout не создавал дубль;
- `Повторить регистрацию` скрыта и отклоняется при `MODEM_REREGISTRATION_ENABLED=false`; AT-команды не реализованы.

## Каналы

VK предусмотрен только как исходящий канал без polling и команд. VK использует прямой HTTPS к фиксированному официальному endpoint `https://api.vk.com/method/messages.send` и намеренно не использует proxy. Это отдельное осознанное исключение из общей proxy-политики.

Ни один transport не принимает endpoint из окружения. Токены читаются только из окружения. Токены, Authorization headers и body SMS не пишутся в логи.

## Состояние и outage

Health основывается на доступности device path, PID-файлах процессов, SQLite и размерах очередей. Второй AT-порт для мониторинга не открывается. Устойчивое отсутствие статуса длительностью 5 минут создаёт одно outage-событие с двумя delivery-записями; повторные проверки его не дублируют. После восстановления создаётся одно recovery-событие с двумя delivery-записями.

## Ограничения MVP

Внешние API не вызываются unit-тестами. Модем, USB passthrough, udev symlink и proxy подключаются только ручными операциями оператора.
