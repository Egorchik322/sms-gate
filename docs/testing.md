# Тестирование

## Автоматические тесты

В корне проекта:

```sh
PYTHONPATH=. python3 -m pytest -q
python3 -m py_compile app/*.py tests/*.py
sh -n scripts/entrypoint.sh scripts/healthcheck.sh
```

Тесты используют временные каталоги и SQLite. Покрыты ingestion, Unicode, multipart, идемпотентность, одинаковые sender/text, две независимые очереди, retry и `Retry-After`, whitelist/update_id Telegram, outage/recovery, обязательный proxy для Telegram, прямой фиксированный VK endpoint и отсутствие SMS body/секретов в логах.

## Development injection

Только в development mode:

```sh
GATEWAY_DEVELOPMENT_MODE=true python3 scripts/inject_test_sms.py --text 'fictional test SMS'
PYTHONPATH=. python3 -m app.main --once
```

Скрипт создаёт файл в FILES spool и не обращается к модему или внешнему API.

## Ручные проверки оператором

Выполняется вручную оператором: проверить латиницу, кириллицу, китайский текст, multipart Unicode, недоступный Telegram proxy, прямой VK HTTPS, restart контейнера и unplug/replug USB. Не включайте реальные токены в тестовые fixtures и не публикуйте body SMS в логах.
