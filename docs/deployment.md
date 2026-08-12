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

Выполняется вручную оператором:

1. Проверить USB ID до и после `usb_modeswitch` для MegaFon M100-4/Huawei E3272.
2. Создать host udev symlink `/dev/huawei-e3272-sms` для подтверждённого serial-порта.
3. Убедиться, что оператор процесса имеет доступ к группе serial device.
4. Не открывать второй AT-порт для healthcheck.

## Конфигурация

Скопируйте `.env.example` в `.env` вручную оператором и заполните только реальные значения на VM. Настройте `MODEM_DEVICE`, proxy URL для Telegram, Telegram параметры, VK параметры и numeric `DIALOUT_GID`. VK использует прямой HTTPS и не использует proxy. Настоящий `.env` не хранится в репозитории.

## Запуск

Выполняется вручную оператором после проверки device path и proxy Telegram:

```sh
docker compose config
docker compose build
docker compose up -d
```

Compose использует один serial device, persistent `./data`, non-root gateway, `restart: unless-stopped`, local log rotation и healthcheck обоих PID-процессов плюс SQLite.
