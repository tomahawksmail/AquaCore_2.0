#!/usr/bin/env bash
# Read-only AquaCore Orange Pi runtime verification.
# Does not trigger GPIO, pump calibration, water alarm or database writes.
set -u
issues=0
warnings=0
ok() { printf 'PASS  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; warnings=$((warnings+1)); }
fail() { printf 'FAIL  %s\n' "$*"; issues=$((issues+1)); }

echo 'AquaCore 1.0 live installation check (READ-ONLY)'
echo 'No physical relay or sensor test is performed.'
echo

if [[ ! -e /opt/aquacore/app.py ]]; then
    fail '/opt/aquacore/app.py is missing'
else
    ok '/opt/aquacore source checkout exists'
    runuser -u aquacore -- git -C /opt/aquacore log -1 \
        --format='Deployed commit: %h (%cs)' 2>/dev/null || warn 'Cannot read deployed commit as aquacore'
fi

for service in aquacore.service aquacore-scheduler.service aquacore-relays.service \
               aquacore-tds.service aquacore-system.service aquacore-telegram.service \
               aquacore-water-alarm.service; do
    state=$(systemctl is-active "$service" 2>/dev/null || true)
    if [[ "$state" == active ]]; then
        ok "$service active"
    else
        warn "$service $state (may be intentionally disabled)"
    fi
done

if [[ ! -e /etc/aquacore/web.env ]]; then
    fail 'Shared service environment is missing'
else
    ok 'Shared service environment exists (secrets not printed)'
fi

if command -v mariadb >/dev/null 2>&1 && mariadb _AquaCore_ -N -e 'SELECT 1' >/dev/null 2>&1; then
    ok 'MariaDB connection works'
    # Require the schema expected by both pumps, sensor factors and cooler.
    for spec in 'options fertilizer_weekdays' 'options fertilizer_dose_ml' \
                'options cooler_on_c' 'options cooler_off_c' \
                'fertilizer_pump2 fertilizer_weekdays' 'fertilizer_pump2 fertilizer_dose_ml' \
                'status fertilizer_pump_status' 'status fertilizer_pump2_status' \
                'sensor_calibration ph_factor' 'sensor_calibration tds_factor' \
                'data tds' 'psutil RAM_total'; do
        read -r tbl col <<< "$spec"
        sql="SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='_AquaCore_' AND table_name='$tbl' AND column_name='$col'"
        count=$(mariadb _AquaCore_ -N -e "$sql" 2>/dev/null || echo ERROR)
        if [[ "$count" == 1 ]]; then
            ok "Column $tbl.$col"
        else
            fail "Missing/inaccessible $tbl.$col"
        fi
    done
    echo
    echo 'Latest water-quality record (stored values, not live ADC feedback):'
    mariadb _AquaCore_ -e \
        'SELECT Id,Datetime,temp,ph,tds FROM data ORDER BY Datetime DESC,Id DESC LIMIT 1' \
        2>/dev/null || warn 'Cannot inspect water-quality sample'
    echo
    echo 'Latest valid system sample (zero-RAM rows excluded):'
    mariadb _AquaCore_ -e \
        'SELECT Id,Datetime,scpufreq_cur,RAM_total,RAM_available,cpu_thermal_cur FROM psutil WHERE RAM_total>0 ORDER BY Id DESC LIMIT 1' \
        2>/dev/null || warn 'Cannot inspect system sample'
    echo
else
    fail 'MariaDB not accessible as current OS account; run with sudo'
fi

if command -v gpioinfo >/dev/null 2>&1; then
    echo 'GPIO ownership only; these commands do NOT read actual voltage:'
    gpioinfo -c gpiochip1 258 232 230 231 256 228 2>/dev/null || \
        warn 'Cannot inspect all GPIO lines'
else
    warn 'gpioinfo not installed'
fi

echo
echo "Result: $issues failures, $warnings warnings"
echo 'Passing this software check does NOT certify mains safety, GPIO wiring, pump flow, fan response, water-sensor detection, or Telegram push delivery.'
if [[ "$issues" -gt 0 ]]; then exit 1; fi
