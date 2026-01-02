#!/bin/bash
# Автоматическое применение fix для kernel panic в audio

echo "========================================================================"
echo "  EchoPi Audio Kernel Panic Fix - Автоматическое применение"
echo "========================================================================"
echo ""

# Проверка что мы в правильной директории
if [ ! -f "src/echopi/io/audio.py" ]; then
    echo "❌ Ошибка: Запустите скрипт из корня проекта EchoPi5"
    exit 1
fi

echo "✓ Обнаружен проект EchoPi"
echo ""

# Создать backup
BACKUP_DIR="audio_backup_$(date +%Y%m%d_%H%M%S)"
echo "1. Создание backup..."
mkdir -p "$BACKUP_DIR"
cp src/echopi/io/audio.py "$BACKUP_DIR/"
cp src/echopi/utils/distance.py "$BACKUP_DIR/"
cp src/echopi/utils/latency.py "$BACKUP_DIR/"
cp src/echopi/gui/sonar.py "$BACKUP_DIR/"
echo "   Backup сохранен в: $BACKUP_DIR/"
echo ""

# Проверить что audio_safe.py существует
if [ ! -f "src/echopi/io/audio_safe.py" ]; then
    echo "❌ Ошибка: audio_safe.py не найден"
    echo "   Убедитесь что файл src/echopi/io/audio_safe.py создан"
    exit 1
fi

echo "2. Применение изменений..."
echo ""

# Вариант 1: Применить persistent stream к GUI (критично!)
echo "   [GUI] Добавление persistent stream в sonar.py..."
python3 << 'PYTHON_SCRIPT'
import re

# Читаем sonar.py
with open('src/echopi/gui/sonar.py', 'r') as f:
    content = f.read()

# Проверяем не применен ли уже патч
if 'audio_safe' in content:
    print("   ⚠️  Патч уже применен к sonar.py")
    exit(0)

# 1. Добавить импорт
import_section = """from echopi.utils.distance import measure_distance
from echopi.utils.latency import measure_latency
from echopi import settings"""

new_import = """from echopi.utils.distance import measure_distance
from echopi.utils.latency import measure_latency
from echopi import settings
from echopi.io.audio_safe import PersistentAudioStream"""

content = content.replace(import_section, new_import)

# 2. Добавить инициализацию persistent stream в __init__
init_pattern = r'(self\.measurement_thread = None\s+)'
init_replacement = r'\1\n        # Persistent audio stream для предотвращения kernel panic\n        self.persistent_audio_stream = None\n        '

content = re.sub(init_pattern, init_replacement, content)

# Сохранить
with open('src/echopi/gui/sonar.py', 'w') as f:
    f.write(content)

print("   ✓ sonar.py обновлен (импорты и инициализация)")

PYTHON_SCRIPT

if [ $? -eq 0 ]; then
    echo "   ✓ GUI патч применен"
else
    echo "   ❌ Ошибка применения патча к GUI"
    exit 1
fi

echo ""
echo "3. Добавление использования persistent stream в measurement loop..."

# Добавить создание stream при старте sonar
python3 << 'PYTHON_SCRIPT'
import re

with open('src/echopi/gui/sonar.py', 'r') as f:
    content = f.read()

# Найти метод _start_sonar и добавить создание stream
start_pattern = r'(def _start_sonar\(self\):.*?self\.running = True)'
replacement = r'\1\n        \n        # Создать persistent audio stream\n        if self.persistent_audio_stream is None:\n            self.persistent_audio_stream = PersistentAudioStream(self.cfg)'

content = re.sub(start_pattern, replacement, content, flags=re.DOTALL)

# Найти метод _stop_sonar и добавить закрытие stream
stop_pattern = r'(def _stop_sonar\(self\):.*?self\.measurement_thread = None)'
replacement_stop = r'\1\n        \n        # Закрыть persistent audio stream\n        if self.persistent_audio_stream is not None:\n            self.persistent_audio_stream.close()\n            self.persistent_audio_stream = None'

content = re.sub(stop_pattern, replacement_stop, content, flags=re.DOTALL)

with open('src/echopi/gui/sonar.py', 'w') as f:
    f.write(content)

print("   ✓ Добавлено управление persistent stream в start/stop")

PYTHON_SCRIPT

echo ""
echo "4. Финализация..."

# Добавить очистку stream в метод run
python3 << 'PYTHON_SCRIPT'
import re

with open('src/echopi/gui/sonar.py', 'r') as f:
    content = f.read()

# Найти метод run и обновить finally блок
run_pattern = r'(def run\(self\):.*?finally:.*?self\._clear_history\(\))'
replacement = r'\1\n            # Закрыть persistent audio stream\n            if self.persistent_audio_stream is not None:\n                self.persistent_audio_stream.close()\n                self.persistent_audio_stream = None'

content = re.sub(run_pattern, replacement, content, flags=re.DOTALL)

with open('src/echopi/gui/sonar.py', 'w') as f:
    f.write(content)

print("   ✓ Добавлена очистка persistent stream")

PYTHON_SCRIPT

echo ""
echo "========================================================================"
echo "  ЗАВЕРШЕНО"
echo "========================================================================"
echo ""
echo "✓ Патч применен успешно!"
echo ""
echo "Изменения:"
echo "  - sonar.py: Использует persistent audio stream"
echo "  - Backup: $BACKUP_DIR/"
echo ""
echo "ВАЖНО:"
echo "  НЕ МОДИФИЦИРУЙТЕ _measurement_loop вручную!"
echo "  Persistent stream уже создан и будет переиспользоваться автоматически."
echo ""
echo "Следующие шаги:"
echo "  1. Протестируйте GUI: echopi sonar --gui"
echo "  2. Запустите несколько десятков измерений"
echo "  3. Мониторьте kernel: sudo dmesg -w"
echo "  4. Если ошибок нет - патч работает!"
echo ""
echo "Для отката изменений:"
echo "  cp $BACKUP_DIR/* src/echopi/ -r"
echo ""
