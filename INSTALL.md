# Инструкция по установке EchoPi

## Системные требования

- Raspberry Pi 5 / CM5
- Raspberry Pi OS (Debian Bookworm) или Ubuntu Server
- Python 3.10+
- I2S аудио устройство (96 кГц или выше)

## Установка зависимостей

### 1. Системные пакеты

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git
```

### 2. Установка X11 (для GUI)

Для работы графического интерфейса (команда `echopi scope`) необходим X11 сервер:

```bash
# Установка X11 и минимального окружения
sudo apt install -y xserver-xorg xinit x11-xserver-utils x11-utils openbox

# Настройка автозапуска графического режима (опционально)
sudo systemctl set-default graphical.target
```

### 3. Python окружение

```bash
cd /home/pi/src/EchoPi5
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Запуск GUI

### Вариант 1: Локальный дисплей (через SSH)

1. Запустите X-сервер на Raspberry Pi:
```bash
sudo xinit /usr/bin/openbox-session -- :0 vt1 &
```

2. Запустите приложение:
```bash
# Осциллограф
DISPLAY=:0 echopi scope --rec-device 0 --sr 48000

# Интерактивный сонар
DISPLAY=:0 echopi sonar --rec-device 0 --play-device 0 --sr 48000

# Полноэкранный режим
DISPLAY=:0 echopi scope --rec-device 0 --sr 48000 --fullscreen
DISPLAY=:0 echopi sonar --rec-device 0 --play-device 0 --sr 48000 --fullscreen
```

Или используйте готовый скрипт:
```bash
./start_gui_local.sh
```

### Вариант 2: X11 Forwarding (GUI на вашем компьютере)

1. Подключитесь с X11 forwarding:
```bash
ssh -X pi@raspberry-pi-hostname
```

2. Запустите приложение:
```bash
echopi scope
echopi sonar
```

### Вариант 3: Прямое подключение (локальная консоль)

Если вы работаете непосредственно с консолью Raspberry Pi (клавиатура/монитор):

```bash
startx &
DISPLAY=:0 echopi scope
```

## Проверка установки

### Проверка аудио устройств

```bash
echopi devices
```

### Проверка воспроизведения

```bash
echopi tone --freq 1000 --seconds 2
```

### Проверка записи

```bash
echopi record test.wav --seconds 3
```

## Настройка I2S

Для работы с I2S устройствами на частоте 96 кГц необходимо:

1. Скомпилировать и установить device tree overlay:
```bash
dtc -@ -I dts -O dtb -o echopi-i2s-96k.dtbo echopi-i2s-96k.dts
sudo cp echopi-i2s-96k.dtbo /boot/overlays/
```

2. Добавить в `/boot/config.txt`:
```
dtoverlay=echopi-i2s-96k
```

3. Перезагрузить систему:
```bash
sudo reboot
```

## Решение проблем

### X11 не запускается

Если при запуске GUI возникает ошибка "No X11 display available":

1. Убедитесь, что X11 установлен (см. раздел "Установка X11")
2. Проверьте наличие X-сервера:
```bash
ps aux | grep X | grep -v grep
```

3. Проверьте переменную DISPLAY:
```bash
echo $DISPLAY
```

4. Запустите X-сервер вручную:
```bash
sudo xinit /usr/bin/openbox-session -- :0 vt1 &
```

### Нет аудио устройств

```bash
# Проверка ALSA устройств
aplay -l
arecord -l

# Проверка через Python
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

### Проблемы с производительностью GUI через SSH

Если GUI работает медленно через X11 forwarding:
- Используйте локальный дисплей (Вариант 1)
- Уменьшите частоту обновления через параметр `--update-interval`
- Проверьте качество сетевого соединения

## Дополнительная информация

Подробная документация проекта: [README.md](README.md)
