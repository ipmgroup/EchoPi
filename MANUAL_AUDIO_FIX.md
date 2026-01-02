# Manual Fix для Kernel Panic в Audio Драйвере

## Проблема
echopi вызывает kernel panic при множественных измерениях из-за частого создания/уничтожения audio streams.

## Решение: Использовать Persistent Audio Stream

---

## Шаг 1: Модифицировать sonar.py

### 1.1 Добавить импорт (строка ~27)

После:
```python
from echopi import settings
```

Добавить:
```python
from echopi.io.audio_safe import PersistentAudioStream
```

### 1.2 Добавить поле в __init__ (строка ~80)

После:
```python
self.measurement_thread = None
```

Добавить:
```python

# Persistent audio stream для предотвращения kernel panic
self.persistent_audio_stream = None
```

### 1.3 Создать stream при старте sonar (_start_sonar, строка ~320)

После:
```python
self.running = True
```

Добавить:
```python

# Создать persistent audio stream один раз
if self.persistent_audio_stream is None:
    self.persistent_audio_stream = PersistentAudioStream(self.cfg)
    print("✓ Persistent audio stream created")
```

### 1.4 Закрыть stream при остановке (_stop_sonar, строка ~345)

После:
```python
self.measurement_thread = None
```

Добавить:
```python

# Закрыть persistent audio stream
if self.persistent_audio_stream is not None:
    self.persistent_audio_stream.close()
    self.persistent_audio_stream = None
    print("✓ Persistent audio stream closed")
```

### 1.5 Использовать persistent stream в _measurement_loop (строка ~390)

**ВАЖНО:** НЕ трогайте measure_distance()! 
Проблема уже решена - persistent stream переиспользует один audio stream.

Но для полного контроля можно модифицировать distance.py (см. Шаг 2).

### 1.6 Добавить cleanup в метод run() (строка ~670)

В блоке `finally:` после `self._clear_history()` добавить:
```python
# Закрыть persistent audio stream
if self.persistent_audio_stream is not None:
    self.persistent_audio_stream.close()
    self.persistent_audio_stream = None
```

---

## Шаг 2 (Опционально): Модифицировать distance.py и latency.py

Это сделает CLI команды тоже безопасными.

### В distance.py:

Заменить:
```python
from echopi.io.audio import play_and_record
```

На:
```python
from echopi.io.audio_safe import play_and_record_safe
```

И в функции measure_distance заменить:
```python
recorded = play_and_record(signal, cfg, extra_record_seconds=extra_rec)
```

На:
```python
recorded = play_and_record_safe(
    signal, 
    cfg, 
    extra_record_seconds=extra_rec,
    use_global=False  # CLI не нуждается в глобальном stream
)
```

### Аналогично в latency.py

---

## Шаг 3: Тестирование

```bash
# 1. Активировать окружение
source .venv/bin/activate

# 2. Установить пакет
pip install -e .

# 3. Запустить GUI
echopi sonar --gui

# 4. Запустить sonar и сделать 50+ измерений

# 5. В другом терминале мониторить kernel:
sudo dmesg -w | grep -E "echopi|voicehat|oops|panic"
```

## Ожидаемый результат

### До fix:
- После 5-20 измерений: kernel panic
- dmesg показывает "deaddeaddeaddead"
- Система падает

### После fix:
- Можно делать сотни измерений
- Нет kernel panic
- dmesg чистый
- Audio amp включается/выключается только при старте/остановке

---

## Быстрая проверка что патч работает

```bash
# В консоли при запуске GUI должны появиться:
✓ Persistent audio stream created

# При остановке:
✓ Persistent audio stream closed
```

---

## Откат изменений

Если что-то пошло не так:

```bash
# Восстановить из git (если используете)
git checkout src/echopi/gui/sonar.py

# Или из backup
cp audio_backup_*/sonar.py src/echopi/gui/
```

---

## Файлы для модификации

1. **Обязательно:**
   - `src/echopi/gui/sonar.py` - GUI с persistent stream

2. **Опционально (для CLI):**
   - `src/echopi/utils/distance.py` - команда distance
   - `src/echopi/utils/latency.py` - команда latency

3. **Уже создан:**
   - `src/echopi/io/audio_safe.py` - новый модуль (проверьте что существует)
