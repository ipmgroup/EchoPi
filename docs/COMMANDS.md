# EchoPi - Краткая справка команд

## Установка и настройка

```bash
# Создание виртуального окружения
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Установка X11 для GUI
sudo apt install -y xserver-xorg xinit openbox

# Запуск X-сервера
sudo xinit /usr/bin/openbox-session -- :0 vt1 &
```

## Проверка системы

```bash
# Список аудио устройств
echopi devices

# Проверка доступности устройств
echopi check-device --rec-device 0 --play-device 0 --sr 48000

# Тестовый тон (1 кГц, 2 секунды)
echopi tone --freq 1000 --seconds 2 --play-device 0 --sr 48000

# Запись с микрофона (3 секунды)
echopi record test.wav --seconds 3 --rec-device 0 --sr 48000

# Воспроизведение файла
echopi play test.wav --play-device 0 --sr 48000
```

## Калибровка

```bash
# Измерение системной задержки (5 раз для усреднения)
for i in {1..5}; do
  echo "=== Тест $i ==="
  echopi latency --rec-device 0 --play-device 0 --sr 48000
done

# Типичное значение для 48 кГц: ~1.21 мс (58 samples)
```

## Измерение дистанции

```bash
# Базовое измерение (воздух)
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121

# С пользовательскими параметрами чирпа
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121 \
  --start 2000 \
  --end 20000 \
  --duration 0.05 \
  --amp 0.8 \
  --medium air

# Для воды
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121 \
  --medium water
```

## GUI приложения

### Осциллограф (waveform + spectrum)

```bash
# Оконный режим
DISPLAY=:0 echopi scope --rec-device 0 --sr 48000

# Полноэкранный режим
DISPLAY=:0 echopi scope --rec-device 0 --sr 48000 --fullscreen

# Демо режим (без микрофона)
DISPLAY=:0 echopi scope --demo

# Мониторинг уровня сигнала (консоль)
echopi monitor --rec-device 0 --sr 48000
```

### Интерактивный сонар

```bash
# Оконный режим
DISPLAY=:0 echopi sonar \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000

# Полноэкранный режим
DISPLAY=:0 echopi sonar \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --fullscreen
```

Функции интерактивного сонара:
- ✅ Запуск/остановка измерений кнопкой START/STOP
- ✅ Изменение параметров чирпа в реальном времени
- ✅ Выбор среды (воздух/вода)
- ✅ Настройка системной задержки
- ✅ Регулировка частоты обновления (0.1-10 Hz)
- ✅ Графики истории дистанции и времени полета
- ✅ Отображение результатов (м, см, мс)
- ✅ Качество сигнала (peak correlation)
- ✅ Счетчик измерений
- ✅ Очистка истории

## Генерация сигналов

```bash
# Генерация чирпа в файл
echopi generate-chirp chirp.wav \
  --sr 48000 \
  --start 2000 \
  --end 20000 \
  --duration 0.05 \
  --amp 0.8 \
  --fade 0.05
```

## Типичные значения параметров

### Для воздуха (ближние измерения 0.5-5 м)
- Sample Rate: 48000 Hz
- Start Freq: 2000 Hz
- End Freq: 20000 Hz
- Duration: 0.03-0.05 s
- Amplitude: 0.8
- System Latency: 0.00121 s (калибровать!)

### Для воды (средние дистанции)
- Sample Rate: 48000 Hz
- Start Freq: 5000 Hz
- End Freq: 40000 Hz (если поддерживается)
- Duration: 0.1-0.2 s
- Amplitude: 0.9
- Medium: water

## Производительность

CPU использование на Raspberry Pi 5 @ 48 кГц:

| Режим | CPU | Память |
|-------|-----|--------|
| distance (однократно) | - | - |
| monitor | ~2% | ~1% |
| scope (window) | ~9% | ~2% |
| scope (fullscreen) | ~16% | ~2% |
| sonar (idle) | ~3-4% | ~2.4% |
| sonar (active) | ~5-6% | ~2.4% |

## Устранение проблем

### X11 не запущен
```bash
# Проверка
ps aux | grep X | grep -v grep

# Запуск
sudo xinit /usr/bin/openbox-session -- :0 vt1 &
```

### Аудио устройство не найдено
```bash
# ALSA
aplay -l
arecord -l

# Python/sounddevice
python3 -c "import sounddevice as sd; print(sd.query_devices())"

# EchoPi
echopi devices
```

### Неточные измерения дистанции
1. Откалибруйте системную задержку: `echopi latency`
2. Проверьте температуру (влияет на скорость звука)
3. Минимизируйте фоновый шум
4. Улучшите звукоизоляцию излучатель↔микрофон

### Высокая нагрузка CPU
1. Уменьшите sample rate (если возможно)
2. Используйте оконный режим вместо fullscreen
3. В sonar: уменьшите update rate

## Документация

- [README.md](../README.md) - Полная документация проекта
- [INSTALL.md](../INSTALL.md) - Инструкция по установке
- [SONAR_GUI.md](SONAR_GUI.md) - Подробное описание GUI сонара

## Быстрый старт

```bash
# 1. Проверка устройств
echopi devices

# 2. Калибровка задержки
echopi latency --rec-device 0 --play-device 0 --sr 48000

# 3. Измерение дистанции
echopi distance --rec-device 0 --play-device 0 --sr 48000 --sys-latency 0.00121

# 4. Запуск интерактивного сонара
DISPLAY=:0 echopi sonar --rec-device 0 --play-device 0 --sr 48000
```
