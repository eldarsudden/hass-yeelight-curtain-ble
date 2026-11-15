# Установка Yeelight Curtain BLE

Нужны Home Assistant 2026.11.0 или новее, настроенный Bluetooth-адаптер
или ESPHome Bluetooth Proxy с активными соединениями и гирлянда YLYDD-0053.
Версия экспериментальная; работа через HA и ESPHome proxy ещё требует проверки.

## Через HACS

[![Добавить в HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eldarsudden&repository=hass-yeelight-curtain-ble&category=integration)

Кнопка открывает репозиторий в вашем HACS. Скачайте интеграцию и перезапустите
HA. Если HACS ещё не установлен, сначала установите его.
Добавить репозиторий можно и через меню:

1. Откройте **HACS → ⋮ → Custom repositories / Пользовательские репозитории**.
2. Добавьте `https://github.com/eldarsudden/hass-yeelight-curtain-ble`, тип **Integration**.
3. Скачайте **Yeelight Curtain BLE** и перезапустите HA.
4. Закройте Yeelight на телефоне и отключите другие BLE-клиенты.
5. В **Настройки → Устройства и службы** настройте обнаруженную гирлянду
   или выберите **Добавить интеграцию → Yeelight Curtain BLE**.

## Вручную

1. Скопируйте папку `custom_components/yeelight_curtain_ble` из архива
   или репозитория в каталог конфигурации HA. В HA OS должен получиться путь
   `/config/custom_components/yeelight_curtain_ble/manifest.json`.
   Для Container используйте каталог, смонтированный в `/config`.
2. Перезапустите Home Assistant.
3. Закройте Yeelight на телефоне и отключите другие BLE-клиенты.
4. В **Настройки → Устройства и службы** настройте обнаруженную гирлянду
   или выберите **Добавить интеграцию → Yeelight Curtain BLE**.

Выберите гирлянду и подтвердите проверку связи. При настройке интеграция
только читает состояние. YAML для самой интеграции не нужен.
Сбрасывать рабочую гирлянду ради установки не требуется. На нашем экземпляре
после заводского сброса локальное BLE-управление с Mac работало сразу,
без первоначальной привязки через приложение Yeelight.

После установки и перезапуска HA настройку можно открыть кнопкой:

[![Настроить интеграцию в Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=yeelight_curtain_ble)

Настройка ESPHome, управление и ограничения описаны в
[README репозитория](https://github.com/eldarsudden/hass-yeelight-curtain-ble#readme).
