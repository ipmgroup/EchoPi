#!/bin/bash
# Сбор всех логов для отчета о проблеме

OUTPUT_DIR="echopi_diagnostics_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "Сбор диагностической информации EchoPi..."
echo "Папка: $OUTPUT_DIR"
echo ""

# 1. System info
echo "1. Сбор системной информации..."
uname -a > "$OUTPUT_DIR/system_info.txt"
cat /proc/cpuinfo > "$OUTPUT_DIR/cpuinfo.txt"
cat /proc/meminfo > "$OUTPUT_DIR/meminfo.txt"
vcgencmd get_throttled >> "$OUTPUT_DIR/system_info.txt"
vcgencmd measure_temp >> "$OUTPUT_DIR/system_info.txt"
vcgencmd measure_volts >> "$OUTPUT_DIR/system_info.txt"

# 2. Kernel logs
echo "2. Сбор kernel логов..."
sudo dmesg > "$OUTPUT_DIR/dmesg_full.log"
sudo dmesg | grep -i echopi > "$OUTPUT_DIR/dmesg_echopi.log"
sudo dmesg | grep -i voicehat > "$OUTPUT_DIR/dmesg_voicehat.log"
sudo dmesg | grep -i "undervoltage\|throttl" > "$OUTPUT_DIR/dmesg_power.log"
sudo dmesg | grep -i "error\|oops\|panic" > "$OUTPUT_DIR/dmesg_errors.log"

# 3. Journal logs
echo "3. Сбор journal логов..."
sudo journalctl -k -b > "$OUTPUT_DIR/journal_kernel.log" 2>/dev/null || echo "No journal"
sudo journalctl -b --no-pager > "$OUTPUT_DIR/journal_full.log" 2>/dev/null || echo "No journal"

# 4. Audio info
echo "4. Сбор информации об аудио..."
aplay -l > "$OUTPUT_DIR/audio_playback.txt" 2>&1
arecord -l > "$OUTPUT_DIR/audio_record.txt" 2>&1
cat /proc/asound/cards > "$OUTPUT_DIR/audio_cards.txt" 2>&1

# 5. Loaded modules
echo "5. Сбор информации о модулях..."
lsmod > "$OUTPUT_DIR/lsmod.txt"
lsmod | grep -E "snd|audio" > "$OUTPUT_DIR/audio_modules.txt"

# 6. Config files
echo "6. Копирование конфигов..."
cp /boot/firmware/config.txt "$OUTPUT_DIR/boot_config.txt" 2>/dev/null || echo "No config.txt"
[ -f ~/.config/echopi/init.json ] && cp ~/.config/echopi/init.json "$OUTPUT_DIR/echopi_config.json"

# 7. EchoPi version
echo "7. Версия EchoPi..."
if [ -f "pyproject.toml" ]; then
    grep "version" pyproject.toml > "$OUTPUT_DIR/echopi_version.txt"
fi

# 8. Python packages
echo "8. Установленные пакеты Python..."
pip list > "$OUTPUT_DIR/pip_packages.txt" 2>&1

# 9. Health check
echo "9. Проверка здоровья системы..."
./check_system_health.sh > "$OUTPUT_DIR/health_check.txt" 2>&1

# 10. Create summary
echo "10. Создание сводки..."
cat > "$OUTPUT_DIR/README.txt" << EOF
EchoPi Diagnostic Report
========================

Дата: $(date)
Система: $(uname -a)

КРИТИЧЕСКИЕ ПРОБЛЕМЫ:
--------------------
$(sudo dmesg | grep -i "undervoltage" | tail -3)

$(sudo dmesg | grep "echopi.*exit" | tail -3)

KERNEL PANIC:
------------
$(sudo dmesg | grep -i "oops\|panic" | tail -5)

Файлы в этой папке:
------------------
- dmesg_*.log - kernel логи (разные фильтры)
- journal_*.log - systemd журналы
- audio_*.txt - информация об аудио устройствах
- health_check.txt - результат проверки системы
- system_info.txt - информация о системе
- boot_config.txt - конфигурация загрузки

Рекомендации:
------------
1. СРОЧНО: Замените блок питания на 27W (5V/5A) для RPi5
2. Прочитайте CRITICAL_ISSUES.md в корне проекта
3. Обновите систему: sudo apt update && sudo apt full-upgrade
4. Перезагрузите и проверьте снова

Для отправки bug report:
-----------------------
Запакуйте эту папку:
  tar -czf echopi_diagnostics.tar.gz $OUTPUT_DIR/

EOF

echo ""
echo "✓ Диагностика завершена!"
echo ""
echo "Результаты сохранены в: $OUTPUT_DIR/"
echo ""
echo "Краткая сводка:"
echo "----------------------------------------"
cat "$OUTPUT_DIR/README.txt"
