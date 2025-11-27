python scripts/backfill_chromadb.py --workspace W_DEFAULT --all --days 90

python scripts/start_slack_commands_simple.py

python -m src.run_server

ngrok http 8000