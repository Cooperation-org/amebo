"""
IMAP runner: fetch unseen mail, hand each to the pipeline, mark processed.

run_once() does a single pass (used by tests and the loop). The DB seen-set is
the real idempotency backstop; IMAP \\Seen just avoids re-fetching.
"""

import email
import imaplib
import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)


class ImapRunner:
    def __init__(self, config, poller, repo):
        self.config = config
        self.poller = poller
        self.repo = repo

    def run_once(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        M = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        try:
            M.login(self.config.imap_user, self.config.imap_password)
            M.select("INBOX")
            typ, data = M.search(None, "UNSEEN")
            for num in (data[0].split() if data and data[0] else []):
                typ, msgdata = M.fetch(num, "(RFC822)")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                msg = email.message_from_bytes(msgdata[0][1])
                try:
                    status = self.poller.process(msg)
                except Exception:
                    logger.exception("process failed for a message")
                    status = "error"
                counts[status] = counts.get(status, 0) + 1
                M.store(num, "+FLAGS", "\\Seen")
        finally:
            try:
                M.logout()
            except Exception:
                pass
        try:
            self.repo.purge_seen(self.config.seen_ttl_days)
        except Exception:
            logger.exception("seen purge failed")
        if counts:
            logger.info("poll pass: %s", counts)
        return counts

    def run_forever(self, interval_seconds: int = 60):
        logger.info("mail poller loop started (interval=%ss)", interval_seconds)
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("poll pass failed")
            time.sleep(interval_seconds)
