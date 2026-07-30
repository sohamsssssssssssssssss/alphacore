#!/bin/bash
# AlphaCore N=10 Benchmark Runner
# Runs each mode N=10 times as separate process invocations.
# Usage: ./run_n10.sh <mode>
#   mode: lean_throughput | lean_latency | full_throughput | full_latency

set -uo pipefail

# Resolve paths relative to script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BENCH_DIR="${PROJECT_ROOT}/frontend/build"

N=10
MODE="${1:-}"

if [[ -z "${MODE}" ]]; then
    echo "Usage: $0 <mode>"
    echo "  mode: lean_throughput | lean_latency | full_throughput | full_latency"
    exit 1
fi

if [[ "${MODE}" == full_* ]]; then
    BENCH="${BENCH_DIR}/add_bench_full"
else
    BENCH="${BENCH_DIR}/add_bench"
fi

echo "======================================================================"
echo "AlphaCore N=${N} Benchmark: ${MODE}"
echo "Binary: ${BENCH}"
date '+%Y-%m-%d %H:%M:%S'
echo "======================================================================"

NS_VALUES=()
MOPS_VALUES=()
AVG_VALUES=()
P50_VALUES=()
P99_VALUES=()

for i in $(seq 1 ${N}); do
    # Disable errexit for this line — benchmark return code is checked manually
    set +e
    result=$("${BENCH}" "${MODE}" 2>/dev/null)
    rc=$?
    set -e
    if [[ ${rc} -ne 0 ]]; then
        echo "  Run ${i}: FAILED (exit=${rc})"
        continue
    fi
    if [[ "${MODE}" == *throughput ]]; then
        # Format: RESULT throughput lean 53.63 18.65  (or "full" instead of "lean")
        ns=$(echo "${result}" | awk '{print $4}')
        mops=$(echo "${result}" | awk '{print $5}')
        NS_VALUES+=("${ns}")
        MOPS_VALUES+=("${mops}")
        printf "  Run %2d: %8.2f ns/op  %8.2f M ops/s\n" "${i}" "${ns}" "${mops}"
    else
        # Format: RESULT latency lean avg=51.93 p50=36.67 p99=182.92 min=29.58 max=214.16
        avg=$(echo "${result}" | sed 's/.*avg=//' | awk '{print $1}')
        p50=$(echo "${result}" | sed 's/.*p50=//' | awk '{print $1}')
        p99=$(echo "${result}" | sed 's/.*p99=//' | awk '{print $1}')
        mong=$(echo "${result}" | sed 's/.*min=//' | awk '{print $1}')
        mx=$(echo "${result}" | sed 's/.*max=//' | awk '{print $1}')
        AVG_VALUES+=("${avg}")
        P50_VALUES+=("${p50}")
        P99_VALUES+=("${p99}")
        printf "  Run %2d: avg=%7.2f  p50=%7.2f  p99=%7.2f  min=%7.2f  max=%7.2f\n" \
               "${i}" "${avg}" "${p50}" "${p99}" "${mong}" "${mx}"
    fi
done

# Stats — compute mean, stddev, min, max for an array of values
# Usage: stats "name" -> prints "mean stddev min max"
stats() {
    local n=$#
    if [[ ${n} -eq 0 ]]; then
        echo "0 0 0 0"
        return
    fi
    local total=0
    local min=$1
    local max=$1
    for v in "$@"; do
        total=$(echo "${total} + ${v}" | bc -l)
        lt=$(echo "${v} < ${min}" | bc -l)
        gt=$(echo "${v} > ${max}" | bc -l)
        if [ "${lt}" = "1" ]; then min=${v}; fi
        if [ "${gt}" = "1" ]; then max=${v}; fi
    done
    local mean=$(echo "scale=4; ${total} / ${n}" | bc -l)

    local sum_sq=0
    for v in "$@"; do
        local diff=$(echo "${v} - ${mean}" | bc -l)
        local sq=$(echo "${diff} * ${diff}" | bc -l)
        sum_sq=$(echo "${sum_sq} + ${sq}" | bc -l)
    done

    local stddev="N/A"
    if [ "${n}" -gt 1 ]; then
        local variance=$(echo "scale=4; ${sum_sq} / (${n} - 1)" | bc -l)
        stddev=$(echo "scale=4; sqrt(${variance})" | bc -l)
    fi
    echo "${mean} ${stddev} ${min} ${max}"
}

echo ""
echo "----------------------------------------------------------------------"
echo "N=${N} Summary (separate process invocations)"
echo "----------------------------------------------------------------------"

if [[ "${MODE}" == *throughput ]]; then
    ns_stats=$(stats "${NS_VALUES[@]}")
    read ns_mean ns_std ns_min ns_max <<< "${ns_stats}"
    echo "  Latency (ns/op):   mean=${ns_mean}  stddev=${ns_std}  min=${ns_min}  max=${ns_max}"
    if [ "${ns_std}" != "N/A" ] && [ "${ns_std}" != "0" ]; then
        ns_cv=$(echo "scale=2; ${ns_std} * 100 / ${ns_mean}" | bc -l)
        echo "  CV (ns):          ${ns_cv}%"
    fi

    mops_stats=$(stats "${MOPS_VALUES[@]}")
    read mops_mean mops_std mops_min mops_max <<< "${mops_stats}"
    echo "  Throughput (M/s): mean=${mops_mean}  stddev=${mops_std}  min=${mops_min}  max=${mops_max}"
    if [ "${mops_std}" != "N/A" ] && [ "${mops_std}" != "0" ]; then
        mops_cv=$(echo "scale=2; ${mops_std} * 100 / ${mops_mean}" | bc -l)
        echo "  CV (M/s):         ${mops_cv}%"
    fi
else
    avg_stats=$(stats "${AVG_VALUES[@]}")
    p50_stats=$(stats "${P50_VALUES[@]}")
    p99_stats=$(stats "${P99_VALUES[@]}")

    read avg_mean avg_std avg_min avg_max <<< "${avg_stats}"
    read p50_mean p50_std p50_min p50_max <<< "${p50_stats}"
    read p99_mean p99_std p99_min p99_max <<< "${p99_stats}"

    echo "  Avg (ns):   mean=${avg_mean}  stddev=${avg_std}  min=${avg_min}  max=${avg_max}"
    echo "  P50 (ns):   mean=${p50_mean}  stddev=${p50_std}  min=${p50_min}  max=${p50_max}"
    echo "  P99 (ns):   mean=${p99_mean}  stddev=${p99_std}  min=${p99_min}  max=${p99_max}"
    if [ "${avg_std}" != "N/A" ] && [ "${avg_std}" != "0" ]; then
        cv=$(echo "scale=2; ${avg_std} * 100 / ${avg_mean}" | bc -l)
        echo "  CV (Avg):   ${cv}%"
    fi
fi
echo "----------------------------------------------------------------------"
