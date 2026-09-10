#!/bin/bash

cd ~/AI/SmartGarage || exit

source ~/AI/OpenInterpreter/venv/bin/activate

export OPENROUTER_API_KEY="$(grep '^OPENROUTER_API_KEY=' .env | cut -d '=' -f2-)"

interpreter \
    --model openrouter/openai/gpt-4.1-mini \
    --api_key "$OPENROUTER_API_KEY" \
    --custom_instructions "$(cat oi_instructions.md)" \
    -y
