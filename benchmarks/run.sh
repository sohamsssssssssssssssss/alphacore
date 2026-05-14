#!/bin/bash
echo "Starting AlphaCore Benchmark Suite..."
echo "Target: 500 concurrent users"
echo "Backend: http://localhost:8000"
echo ""
cd "$(dirname "$0")/.."
python3 benchmarks/run_benchmark.py
echo ""
echo "Results saved to benchmarks/results.md"
