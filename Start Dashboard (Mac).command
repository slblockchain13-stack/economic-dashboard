#!/bin/bash
# Double-click to start the Economic Machine Monitor on this Mac.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed and was not found."
  echo "Install it from https://www.python.org/downloads/ and double-click this file again."
  read -r -p "Press Return to close."
  exit 1
fi
python3 run_local.py
echo
read -r -p "The dashboard has stopped. Press Return to close this window."
