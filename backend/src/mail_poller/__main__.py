"""
Entrypoint for the mail poller process.

  python -m src.mail_poller            # loop
  python -m src.mail_poller --once     # single pass (cron / test)

Config from env (see config.py): MAIL_POLLER_IMAP_*, MAIL_POLLER_ALLOWLIST,
MAIL_POLLER_TRUSTED_DOMAINS, plus ODOO_URL/ODOO_DB/ODOO_USER/ODOO_API_KEY.
"""

import logging
import os
import sys

from dotenv import load_dotenv

from src.mail_poller.config import PollerConfig
from src.mail_poller.odoo_client import OdooClient
from src.mail_poller.poller import Poller
from src.mail_poller.runner import ImapRunner
from src.db.repositories.mail_poller_repo import MailPollerRepo


def build_runner() -> ImapRunner:
    load_dotenv()
    config = PollerConfig()
    if not config.ready():
        raise SystemExit(
            "Poller not configured. Need MAIL_POLLER_IMAP_USER/PASSWORD and at least "
            "one of MAIL_POLLER_ALLOWLIST / MAIL_POLLER_TRUSTED_DOMAINS."
        )
    repo = MailPollerRepo()
    poller = Poller(config, repo, OdooClient())
    return ImapRunner(config, poller, repo)


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    runner = build_runner()
    if "--once" in argv:
        counts = runner.run_once()
        print(counts)
    else:
        runner.run_forever(int(os.getenv("MAIL_POLLER_INTERVAL", "60")))


if __name__ == "__main__":
    main()
