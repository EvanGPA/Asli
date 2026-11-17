#!/usr/bin/env bash
# Downloads the Indian Nutrient Databank spreadsheet into data/raw/ (not committed:
# the repository has no licence file, so commercial use needs the authors' permission).
set -euo pipefail
mkdir -p data/raw
curl -fsSL -o data/raw/INDB.xlsx \
  https://raw.githubusercontent.com/lindsayjaacks/Indian-Nutrient-Databank-INDB-/main/INDB.xlsx
echo "Saved data/raw/INDB.xlsx"
