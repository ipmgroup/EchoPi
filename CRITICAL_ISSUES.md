# 🚨 КРИТИЧЕСКАЯ ПРОБЛЕМА: KERNEL PANIC в Audio Драйвере

## Обнаружена серьезная проблема на уровне ядра

Дата анализа: 2 January 2026

---

## 💥 ОСНОВНАЯ ПРОБЛЕМА: KERNEL PANIC в audio драйвере (КРИТИЧНО!)

### Проблема
```
Jan 02 12:49:43 kernel: Unable to handle kernel paging request at virtual address deaddeaddeaddead
Jan 02 12:49:43 kernel: Internal error: Oops: 0000000096000004 [#1] PREEMPT SMP
Jan 02 12:49:43 kernel: pc : dma_pool_alloc+0x48/0x248
Jan 02 12:49:43 kernel: note: echopi[1475] exited with irqs disabled
Jan 02 12:49:43 kernel: note: echopi[1475] exited with preempt_count 2
```

### Анализ
- Kernel crash на уровне DMA (прямой доступ к памяти)
- Адрес `deaddeaddeaddead` = освобождённая память (use-after-free bug)
- Связано с audio драйвером `snd_soc_googlevoicehat_codec`
- echopi завершился с отключенными прерываниями (аварийно)

### Причина
**Use-after-free bug в audio драйвере:**
1. Ошибка управления памятью в DMA pool
2. Быстрые открытия/закрытия audio streams
3. Неправильная последовательность освобождения ресурсов
4. Bug в драйвере Google Voice HAT codec или sounddevice/PortAudio

### 🔧 РЕШЕНИЕ (ПРИОРИТЕТ #1)

#### ✅ Вариант A: Использовать новый модуль audio_safe.py (РЕКОМЕНДУЕТСЯ)

**Создан:** `src/echopi/io/audio_safe.py` - модуль с persistent audio stream.

**ПОЧЕМУ ЭТО РАБОТАЕТ:**
- Один stream используется для множества измерений
- Нет постоянного создания/уничтожения DMA буферов
- Добавлены задержки для стабилизации драйвера
- Правильная последовательность закрытия ресурсов

**КАК ПРИМЕНИТЬ:**

1. **Для CLI команд (одно измерение):**

В файлах `echopi/utils/distance.py` и `echopi/utils/latency.py`:

```python
# Заменить импорт:
# from echopi.io.audio import play_and_record

# На:
from echopi.io.audio_safe import play_and_record_safe

# И изменить вызов:
recorded = play_and_record_safe(
    signal, 
    cfg, 
    extra_record_seconds=...,
    use_global=False  # Для CLI каждый раз новый stream
)
```

2. **Для GUI (множество измерений) - КРИТИЧНО:**

В файле `echopi/gui/sonar.py`:

```python
# В начале файла добавить:
from echopi.io.audio_safe import PersistentAudioStream, close_global_stream

# В классе SonarGUI.__init__ создать stream:
self.audio_stream = PersistentAudioStream(self.cfg)

# В _measurement_loop использовать:
recorded = self.audio_stream.play_and_record(
    signal, 
    extra_record_seconds=...
)

# В методе run() в finally блоке:
def run(self):
    try:
        self.app.exec()
    finally:
        # Закрыть audio stream
        if hasattr(self, 'audio_stream'):
            self.audio_stream.close()
        # ... остальная очистка
```

#### ⚠️ Вариант B: Добавить задержки в текущий код (ВРЕМЕННОЕ РЕШЕНИЕ)

#### ⚠️ Вариант B: Добавить задержки в текущий код (ВРЕМЕННОЕ РЕШЕНИЕ)

Если не хотите использовать новый модуль, добавьте задержки в `echopi/io/audio.py`:

```python
import time

def play_and_record(play_signal: np.ndarray, cfg: AudioDeviceConfig, 
                    extra_record_seconds: float = 0.1) -> np.ndarray:
    # ЗАДЕРЖКА ПЕРЕД: дать драйверу время
    time.sleep(0.15)
    
    total_frames = len(play_signal) + int(extra_record_seconds * cfg.sample_rate)
    recorded = np.zeros(total_frames, dtype=np.float32)

    with audio_stream(cfg) as stream:
        # ... существующий код ...
    
    # ЗАДЕРЖКА ПОСЛЕ: дать драйверу время закрыться
    time.sleep(0.15)
    
    return recorded
```

**Минусы:**
- Медленнее (задержки на каждое измерение)
- Не решает проблему полностью
- Все равно создает/уничтожает streams

#### Вариант C: Обновить систему

```bash
# Обновите ядро и драйверы
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

---

## 2. 🔊 Проблема с Audio Amplifier (вторичная)

### Проблема
```
voicehat-codec voicehat-codec: Enabling audio amp...
voicehat-codec voicehat-codec: Disabling audio amp...
[...повторяется ~40 раз за 13 секунд...]
```

### Анализ
Усилитель включается/выключается слишком часто из-за:
- Постоянного создания/закрытия audio streams
- Проблемы управления питанием в драйвере

### Решение
Использование persistent stream (Вариант A выше) решает эту проблему автоматически.

---

## 📊 Техническая информация

### Kernel Crash Details
```
Crash Address: deaddeaddeaddead (freed memory marker)
Function: dma_pool_alloc+0x48/0x248
Error Type: Use-after-free в DMA pool
Process: echopi (PID 1475)
State: exited with irqs disabled + preempt_count 2
Hardware: Raspberry Pi 5 Model B Rev 1.0
Kernel: 6.12.47+rpt-rpi-2712 #1 Debian
Driver: snd_soc_googlevoicehat_codec
```

### Последовательность событий
1. GUI запускает множество измерений (2 Hz update rate)
2. Каждое измерение вызывает `play_and_record()`
3. Каждый вызов создает новый `audio_stream`
4. Драйвер создает DMA буферы
5. Stream закрывается, но драйвер не успевает освободить память
6. Следующий stream пытается использовать уже освобожденную память
7. **KERNEL PANIC** - обращение к `deaddeaddeaddead`

---

## 🎯 ПЛАН ДЕЙСТВИЙ (ПО ПРИОРИТЕТУ)

### НЕМЕДЛЕННО (fixes kernel panic):

1. **Применить Вариант A - persistent stream**
   - Скопировать `audio_safe.py` (уже создан)
   - Модифицировать `sonar.py` для использования persistent stream
   - Модифицировать `distance.py` и `latency.py` (опционально)
```
Jan 02 12:49:37 kernel: voicehat-codec voicehat-codec: Enabling audio amp...
Jan 02 12:49:37 kernel: voicehat-codec voicehat-codec: Disabling audio amp...
[...повторяется ~40 раз за 13 секунд...]
```

### Анализ
Усилитель включается/выключается слишком часто - это:
- Нагружает драйвер
- Вызывает проблемы DMA
- Может быть связано с undervoltage

### 🔧 РЕШЕНИЕ
Модифицируйте код чтобы минимизировать операции audio I/O:

```python
# Вместо множества коротких измерений делайте батчи
# Используйте один stream для нескольких измерений
```

---

## 4. 📊 Модули ядра загруженные при крахе

```
snd_soc_googlevoicehat_codec - Google Voice HAT codec (ПРОБЛЕМНЫЙ)
snd_soc_core - ALSA SoC core
snd_pcm - ALSA PCM
videobuf2_* - Video4Linux2 (не связано)
```

---

## 🎯 ПРИОРИТЕТНЫЙ ПЛАН ДЕЙСТВИЙ

### ШАГИ (по порядку):

1. **СРОЧНО: Замените блок питания**
   - Raspberry Pi 5 требует 5V/5A (27W)
   - Проверьте: `vcgencmd get_throttled`

2. **Обновите систему**
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```

3. **Добавьте задержки в audio код**
   - Перед play/record: sleep(0.1)
   - После play/record: sleep(0.1)

4. **Уменьшите частоту измерений в GUI**
   - Update Rate: 0.5 Hz (вместо 2 Hz)
   - Дайте драйверу время восстановиться

5. **Мониторьте систему**
   ```bash
   # Проверка питания
   watch -n 1 vcgencmd get_throttled
   
   # Мониторинг kernel логов
   sudo dmesg -w | grep -E "voicehat|undervoltage|oops"
   ```

6. **Если проблема сохраняется**
   - Попробуйте другую audio карту (USB audio interface)
   - Отключите Google Voice HAT и используйте стандартный audio

---

## 📋 Диагностические команды

```bash
# Проверка питания
vcgencmd get_throttled
vcgencmd measure_volts

# Проверка audio устройств
aplay -l
arecord -l

# Мониторинг kernel
sudo dmesg -w

# Проверка температуры
vcgencmd measure_temp

# Проверка частоты процессора
vcgencmd measure_clock arm
```

---

## 🔍 Технические детали краха

```
Crash Address: deaddeaddeaddead (freed memory marker)
Function: dma_pool_alloc+0x48/0x248
Error Type: Use-after-free в DMA pool
Process: echopi (PID 1475)
State: exited with irqs disabled + preempt_count 2
Hardware: Raspberry Pi 5 Model B Rev 1.0
Kernel: 6.12.47+rpt-rpi-2712 #1 Debian
```

---

## ⚠️ ВНИМАНИЕ

**НЕ используйте систему с undervoltage!**

Это может привести к:
- Повреждению SD карты
- Потере данных
- Выходу из строя оборудования
- Нестабильной работе

**Сначала исправьте питание, потом тестируйте echopi!**

---

## 📞 Дальнейшие действия

После исправления питания:

1. Запустите диагностику:
   ```bash
   python test_distance_check.py
   ```

2. Если kernel panic повторяется - рассмотрите:
   - Использование USB audio interface вместо Google Voice HAT
   - Обращение к разработчикам Voice HAT driver
   - Переход на другую версию ядра

3. Соберите полный лог для bug report:
   ```bash
   sudo dmesg > echopi_crash_dmesg.log
   sudo journalctl -k -b > echopi_crash_journal.log
   ```
