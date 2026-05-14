#!/bin/bash
echo "================================================"
echo "ALPHACORE TEST SUITE"
echo "================================================"
cd "$(dirname "$0")/.."

echo ""
echo "Running unit tests..."
pytest tests/unit/ -v --tb=short

echo ""
echo "Running API tests..."
pytest tests/api/ -v --tb=short

echo ""
echo "Running integration tests..."
pytest tests/integration/ -v --tb=short

echo ""
echo "Running property tests..."
pytest tests/property/ -v --tb=short

echo ""
echo "Running chaos tests..."
pytest tests/chaos/ -v --tb=short

echo ""
echo "Running regression tests..."
pytest tests/regression/ -v --tb=short

echo ""
echo "Running stress tests..."
pytest tests/stress/ -v --tb=short

echo ""
echo "================================================"
echo "FULL SUITE COMPLETE"
pytest tests/ --co -q | tail -5
echo "================================================"
