# Тестирование

## Автоматические тесты

В корне проекта:

```sh
PYTHONPATH=. python3 -m pytest -p no:cacheprovider -q
python3 -m py_compile app/*.py tests/*.py
sh -n scripts/entrypoint.sh scripts/healthcheck.sh
```

Тесты используют временные каталоги и SQLite. Покрыты ingestion, Unicode, multipart, идемпотентность, одинаковые sender/text, две независимые очереди, retry и `Retry-After`, whitelist/update_id Telegram, outage/recovery, обязательный proxy для Telegram, прямой фиксированный VK endpoint и отсутствие SMS body/секретов в логах.

## Telegram inline-кнопки

Callback-тесты используют fake fetcher и fake poster, без сети:

- `allowed_updates` содержит `message` и `callback_query`;
- callback data проверяется по allowlist `smsgw:v1:<action>`;
- разрешённый callback вызывает `answerCallbackQuery` и `editMessageText`;
- edit HTTP 400 допускает безопасный fallback на `sendMessage`;
- transient edit error не создаёт потенциальный дубль;
- duplicate `update_id` подтверждается, но action не выполняется повторно;
- запрещённые user/chat, неизвестные и malformed callback только подтверждаются;
- callback без `message.chat` не может обойти whitelist;
- `/start` отправляет меню с inline keyboard;
- кнопка повторной регистрации не появляется при выключенном feature flag.

Реальные Telegram API, VK API и модем во время этих тестов не используются.

## Development injection

Только в development mode:

```sh
GATEWAY_DEVELOPMENT_MODE=true python3 scripts/inject_test_sms.py --text 'fictional test SMS'
PYTHONPATH=. python3 -m app.main --once
```

Скрипт создаёт файл в FILES spool и не обращается к модему или внешнему API.

## Ручные проверки оператором

Выполняется вручную оператором: проверить латиницу, кириллицу, китайский текст, multipart Unicode, недоступный Telegram proxy, прямой VK HTTPS, `/start` и нажатие каждой inline-кнопки, restart контейнера и unplug/replug USB. Не включайте реальные токены в тестовые fixtures и не публикуйте body SMS в логах.
