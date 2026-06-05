"""
Email poller: files emails sent/BCC'd to one inbox into the right place.

MVP: `+crm` tagged mail -> match To:/Cc to an Odoo contact -> log onto its chatter.
Runs as its own process (not inside the web app). Design + threat model:
docs/email-poller-architecture.md.

Step 0 (sender authentication) is the security gate: only mail from an allowlisted
team identity that passes DKIM is processed. Everything else is dead-lettered.
"""
