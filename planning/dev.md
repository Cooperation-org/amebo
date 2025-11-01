psql -U postgres -c "CREATE DATABASE slack_helper;" 2>&1 || psql -d postgres -c "CREATE DATABASE slack_helper;" 2>&1

psql -d slack_helper -f planning/final-schema.sql

psql -d slack_helper -c "\dt" && echo "---VIEWS---" && psql -d slack_helper -c "\dv"