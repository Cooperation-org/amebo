"""amebo-max entry point: `python -m src.max_answerer`.

Listens on 127.0.0.1 only. A POST carries {channel, ts, thread_ts}; the text is
read back from Slack (see src/services/max_answerer.py), so a forged POST can at
most make amebo answer a message that already addresses it.
"""
import asyncio
import logging
import os
import re

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

load_dotenv()

from src.services.max_answerer import MaxAnswerer  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("amebo-max")

app = FastAPI()
answerer = MaxAnswerer(
    bot_token=os.environ["SLACK_BOT_TOKEN"],
    workdir=os.environ["AMEBO_MAX_WORKDIR"],
    claude_bin=os.getenv("AMEBO_MAX_CLAUDE", "claude"),
    timeout_seconds=int(os.getenv("AMEBO_MAX_TIMEOUT_SECONDS", "600")),
    concurrency=int(os.getenv("AMEBO_MAX_CONCURRENCY", "1")),
    per_hour=int(os.getenv("AMEBO_MAX_PER_HOUR", "20")),
)
_SLACK_TS = re.compile(r"^\d+\.\d+$")
_SLACK_ID = re.compile(r"^[A-Z0-9]+$")


@app.post("/mention")
async def mention(request: Request):
    body = await request.json()
    channel, ts = body.get("channel", ""), body.get("ts", "")
    thread_ts = body.get("thread_ts") or ts
    if not (_SLACK_ID.match(channel) and _SLACK_TS.match(ts) and _SLACK_TS.match(thread_ts)):
        raise HTTPException(status_code=400, detail="channel, ts, thread_ts required")

    async def run():
        try:
            outcome = await answerer.handle(channel, ts, thread_ts)
        except Exception:
            logger.exception("amebo-max failed on %s/%s", channel, ts)
            return
        logger.info("amebo-max %s/%s: %s", channel, ts, outcome)

    asyncio.create_task(run())
    return JSONResponse(status_code=202, content={"accepted": True})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["AMEBO_MAX_PORT"]))
