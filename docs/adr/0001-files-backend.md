# ADR-0001: Gammu FILES backend

## Решение

Использовать штатный `gammu-smsd` FILES backend как durable ingress spool, а прикладные сообщения и delivery queues хранить в отдельной SQLite.

## Основание

В Debian 12 доступен штатный `gammu-smsd` 1.42.0-8 с `/usr/share/man/man7/gammu-smsd-files.7.gz`. Документация описывает входящие файлы `IN<date>_<time>_<serial>_<sender>_<sequence>.<ext>` и каталоги `inboxpath`, `outboxpath`, `sentsmspath`, `errorsmspath`.

SQL backend Gammu через SQLite не выбран: совместное владение одной SQLite между daemon и gateway создаёт лишнюю связанность, тогда как FILES backend предоставляет естественную durable границу и не требует нестабильной сборки.

## Последствия

- Gammu надёжно сохраняет SMS до обработки gateway.
- Gateway должен быть идемпотентным по source identifier.
- Multipart объединяется на уровне метаданных FILES backend, без самописного PDU-парсера.
- Архив spool и прикладная SQLite должны входить в backup.
- At-least-once доставка сохраняет возможность дубля после неопределённого timeout.
