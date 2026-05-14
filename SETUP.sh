#!/bin/zsh
set -euo pipefail

cd backend
python3.11 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

echo "Setup complete."
echo "Next steps:"
echo "1. Review backend/.env and fill in your local PostgreSQL credentials."
echo "2. Create the database with: createdb alphacore"
echo "3. Start the backend with: ./RUN.sh"
