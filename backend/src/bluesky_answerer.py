"""amebo-bluesky entry point: `python -m src.bluesky_answerer`.

Polls Bluesky for mentions of the amebo account and answers the owners'
mentions with Claude Code on the Max login (src/services/bluesky_answerer.py).
No port: it only makes outbound calls.
"""
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.services.bluesky_answerer import Bluesky, BlueskyAnswerer  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("amebo-bluesky")


async def main():
    answerer = BlueskyAnswerer(
        client=Bluesky(os.getenv("AMEBO_BLUESKY_SERVICE", "https://bsky.social"),
                       os.environ["AMEBO_BLUESKY_HANDLE"],
                       os.environ["AMEBO_BLUESKY_APP_PASSWORD"]),
        owners=[o.strip() for o in os.environ["AMEBO_BLUESKY_OWNERS"].split(",") if o.strip()],
        state_file=Path(os.environ["AMEBO_BLUESKY_STATE"]),
        workdir=os.environ["AMEBO_MAX_WORKDIR"],
        claude_bin=os.getenv("AMEBO_MAX_CLAUDE", "claude"),
        timeout_seconds=int(os.getenv("AMEBO_MAX_TIMEOUT_SECONDS", "600")),
        per_hour=int(os.getenv("AMEBO_BLUESKY_PER_HOUR", "10")),
        sleep_window=os.getenv("AMEBO_MAX_SLEEP", "00:00-06:00"),
        tz=os.getenv("AMEBO_MAX_TZ", "America/Phoenix"),
        quiet_hours=float(os.getenv("AMEBO_MAX_QUIET_HOURS", "6")),
    )
    await answerer.start()
    every = int(os.getenv("AMEBO_BLUESKY_POLL_SECONDS", "30"))
    logger.info("amebo-bluesky: polling as %s every %ss", answerer.bsky.handle, every)
    while True:
        try:
            for line in await answerer.poll():
                logger.info("amebo-bluesky %s", line)
        except Exception:
            logger.exception("amebo-bluesky: poll failed")
        await asyncio.sleep(every)


if __name__ == "__main__":
    asyncio.run(main())
