#!/bin/bash
# Скрипт для запуска GUI на локальном дисплее Raspberry Pi

echo "Запуск X-сервера на :0..."

# Проверяем, запущен ли уже X-сервер
if [ ! -S /tmp/.X11-unix/X0 ]; then
    # Запускаем X-сервер в фоне
    sudo xinit /usr/bin/openbox-session -- :0 vt1 &
    XINIT_PID=$!
    
    # Ждем запуска X-сервера
    echo "Ожидание запуска X-сервера..."
    for i in {1..10}; do
        if [ -S /tmp/.X11-unix/X0 ]; then
            echo "X-сервер запущен!"
            break
        fi
        sleep 1
    done
    
    if [ ! -S /tmp/.X11-unix/X0 ]; then
        echo "Ошибка: X-сервер не запустился"
        exit 1
    fi
    
    # Даем права доступа
    sleep 2
    xhost +local: 2>/dev/null
fi

# Запускаем приложение на локальном дисплее
echo "Запуск EchoPi GUI..."
DISPLAY=:0 /home/pi/src/EchoPi5/.venv/bin/python -m echopi.cli scope

# Cleanup при выходе
if [ -n "$XINIT_PID" ]; then
    echo "Остановка X-сервера..."
    sudo kill $XINIT_PID 2>/dev/null
fi
