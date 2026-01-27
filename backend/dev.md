python scripts/backfill_chromadb.py --workspace W_DEFAULT --all --days 90

python scripts/start_slack_commands_simple.py

python -m src.run_server

ngrok http 8000

to delete last schedule
source venv/bin/activate && python -c "
from src.db.connection import DatabaseConnection
conn = DatabaseConnection.get_connection()
cur = conn.cursor()
cur.execute('DELETE FROM backfill_schedules WHERE workspace_id = %s', ('TJ5RZJT52',))
conn.commit()
cur.close()
conn.close()
print('Schedule deleted - restart server to trigger initial backfill')
"

python -c "
from src.db.connection import DatabaseConnection
conn = DatabaseConnection.get_connection()
cur = conn.cursor()
cur.execute('DELETE FROM backfill_schedules WHERE workspace_id = %s', ('TJ5RZJT52',))
conn.commit()
cur.close()
conn.close()
print('Schedule deleted - restart server to trigger initial backfill')
"