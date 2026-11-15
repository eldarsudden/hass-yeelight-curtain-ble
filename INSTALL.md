# Установка Yeelight Curtain BLE

Нужны Home Assistant 2026.11.0 или новее, настроенный Bluetooth-адаптер
или ESPHome Bluetooth Proxy с активными соединениями и гирлянда YLYDD-0053.
Версия экспериментальная; работа через HA и ESPHome proxy ещё требует проверки.

## Через HACS

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
Не сбрасывайте гирлянду ради установки: первичная настройка после сброса
пока не поддерживается.

Настройка ESPHome, управление и ограничения описаны в
[README репозитория](https://github.com/eldarsudden/hass-yeelight-curtain-ble#readme).
