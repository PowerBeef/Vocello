#!/usr/bin/env bash
# Host posture preflight for timing- and memory-sensitive lanes on the 8 GB host.
#
# A benchmark, language, memory or UI benchmark run started on a loaded or
# memory-pressured machine produces numbers that the gate summarizer later
# rejects as inconclusive (load above twice the core count, thermal throttling).
# Refusing to start applies the same rule before the model loads, so the
# operator does not spend a 20-minute run to learn that the host was busy.
#
#   require_quiet_host <lane>
#
# Refuses (exit 1) when the 1-minute load average exceeds twice the core count
# or the kernel reports memory pressure above normal
# (`kern.memorystatus_vm_pressure_level` > 1: 2 = warning, 4 = critical), and
# prints the numbers either way. `QVOICE_ALLOW_BUSY_HOST=1` records the numbers
# and continues, for an explicitly exploratory run the publisher will classify
# from the run's own load sample. No dependency on the caller's note/warn/die.

require_quiet_host() {
    local lane="${1:-}"
    if [ -z "$lane" ]; then
        echo "error: require_quiet_host needs a lane identifier" >&2
        return 2
    fi
    local load cores level limit load_hundredths
    load="$(sysctl -n vm.loadavg 2>/dev/null | tr -d '{}' | awk '{print $1}')"
    cores="$(sysctl -n hw.ncpu 2>/dev/null)"
    level="$(sysctl -n kern.memorystatus_vm_pressure_level 2>/dev/null || echo 1)"
    case "$cores" in ''|*[!0-9]*) cores=1 ;; esac
    case "$level" in ''|*[!0-9]*) level=1 ;; esac
    load_hundredths="$(awk -v value="${load:-0}" 'BEGIN { printf "%d", value * 100 }')"
    limit=$(( cores * 2 ))
    local busy=0
    if [ "$load_hundredths" -gt $(( limit * 100 )) ] || [ "$level" -gt 1 ]; then
        busy=1
    fi
    if [ "$busy" -eq 1 ]; then
        if [ "${QVOICE_ALLOW_BUSY_HOST:-0}" = "1" ]; then
            echo "==> [host] $lane: continuing on a busy host by request (load1m=${load:-?} limit=$limit cores=$cores memoryPressureLevel=$level)" >&2
            return 0
        fi
        echo "error: $lane needs a quiet host: load1m=${load:-?} (limit $limit for $cores cores), memoryPressureLevel=$level (limit 1)." >&2
        echo "error: wait for the load to settle or close other work; QVOICE_ALLOW_BUSY_HOST=1 runs anyway and the run's own load sample decides its classification." >&2
        return 1
    fi
    echo "==> [host] $lane: load1m=${load:-?} cores=$cores memoryPressureLevel=$level" >&2
    return 0
}
