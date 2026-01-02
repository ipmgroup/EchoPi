#!/bin/bash
# System health check for EchoPi on Raspberry Pi 5

echo "========================================================================"
echo "  EchoPi System Health Check"
echo "========================================================================"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Check power supply
echo "1. Power Supply Status"
echo "----------------------------------------"
THROTTLED=$(vcgencmd get_throttled)
echo "Throttle status: $THROTTLED"

if [[ "$THROTTLED" == "throttled=0x0" ]]; then
    echo -e "${GREEN}✓ Power supply OK${NC}"
else
    echo -e "${RED}✗ UNDERVOLTAGE DETECTED!${NC}"
    echo -e "${RED}  ACTION REQUIRED: Replace power supply with official RPi5 27W adapter${NC}"
fi

VOLTS=$(vcgencmd measure_volts)
echo "Voltage: $VOLTS"
echo ""

# 2. Check temperature
echo "2. Temperature"
echo "----------------------------------------"
TEMP=$(vcgencmd measure_temp)
echo "$TEMP"

TEMP_VALUE=$(echo $TEMP | grep -oP '\d+\.\d+')
if (( $(echo "$TEMP_VALUE < 70" | bc -l) )); then
    echo -e "${GREEN}✓ Temperature OK${NC}"
else
    echo -e "${YELLOW}⚠ Temperature high - consider cooling${NC}"
fi
echo ""

# 3. Check kernel version
echo "3. Kernel Version"
echo "----------------------------------------"
uname -r
echo ""

# 4. Check audio devices
echo "4. Audio Devices"
echo "----------------------------------------"
echo "Playback devices:"
aplay -l 2>/dev/null | grep -E "card|device" || echo "No playback devices found"
echo ""
echo "Recording devices:"
arecord -l 2>/dev/null | grep -E "card|device" || echo "No recording devices found"
echo ""

# 5. Check for recent kernel errors
echo "5. Recent Kernel Errors"
echo "----------------------------------------"
ERRORS=$(sudo dmesg | grep -i -E "error|oops|panic|segfault" | tail -5)
if [ -z "$ERRORS" ]; then
    echo -e "${GREEN}✓ No recent kernel errors${NC}"
else
    echo -e "${YELLOW}Recent errors found:${NC}"
    echo "$ERRORS"
fi
echo ""

# 6. Check for audio amp issues
echo "6. Audio Amplifier Status"
echo "----------------------------------------"
AMP_ISSUES=$(sudo dmesg | grep "voicehat-codec" | tail -10)
if [ -z "$AMP_ISSUES" ]; then
    echo -e "${GREEN}✓ No audio amp messages${NC}"
else
    echo -e "${YELLOW}Recent audio amp activity:${NC}"
    echo "$AMP_ISSUES" | tail -5
fi
echo ""

# 7. Check memory
echo "7. Memory Status"
echo "----------------------------------------"
free -h
echo ""

# 8. Check disk space
echo "8. Disk Space"
echo "----------------------------------------"
df -h / | tail -1
echo ""

# 9. Check for echopi crashes
echo "9. EchoPi Crash History"
echo "----------------------------------------"
CRASHES=$(sudo dmesg | grep "echopi.*exit")
if [ -z "$CRASHES" ]; then
    echo -e "${GREEN}✓ No echopi crashes found${NC}"
else
    echo -e "${RED}✗ EchoPi crashes detected:${NC}"
    echo "$CRASHES"
fi
echo ""

# 10. Summary
echo "========================================================================"
echo "  SUMMARY"
echo "========================================================================"
echo ""

ISSUES=0

# Check critical issues
if [[ "$THROTTLED" != "throttled=0x0" ]]; then
    echo -e "${RED}🚨 CRITICAL: Undervoltage detected - REPLACE POWER SUPPLY${NC}"
    ((ISSUES++))
fi

if [ ! -z "$CRASHES" ]; then
    echo -e "${RED}🚨 CRITICAL: EchoPi has crashed - see CRITICAL_ISSUES.md${NC}"
    ((ISSUES++))
fi

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed${NC}"
    echo ""
    echo "System is healthy. You can proceed with echopi testing."
else
    echo ""
    echo -e "${RED}Found $ISSUES critical issue(s)${NC}"
    echo ""
    echo "NEXT STEPS:"
    echo "1. Read CRITICAL_ISSUES.md for detailed information"
    echo "2. Fix power supply issues FIRST"
    echo "3. Update system: sudo apt update && sudo apt full-upgrade"
    echo "4. Reboot and run this check again"
fi

echo ""
echo "========================================================================"
