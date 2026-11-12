#!/bin/sh
set -e
cd "$(dirname "$0")/.."
python3 -m py_compile explain.py
python3 tests/test_explain.py
