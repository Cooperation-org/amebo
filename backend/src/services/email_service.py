"""
Email service for sending invitations, password resets, and notifications
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import os

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.from_email = os.getenv('FROM_EMAIL', self.smtp_username)
        self.app_url = os.getenv('APP_URL', 'http://localhost:3000').rstrip('/')
        self.app_name = os.getenv('APP_NAME', 'Amebo')

    def _base_html(self, content: str) -> str:
        """Wrap email content in a styled HTML template"""
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <tr><td style="background-color:#6366f1;padding:28px 40px;text-align:center;">
          <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">{self.app_name}</h1>
        </td></tr>
        <tr><td style="padding:36px 40px;">
          {content}
        </td></tr>
        <tr><td style="background-color:#f9fafb;padding:20px 40px;text-align:center;border-top:1px solid #e5e7eb;">
          <p style="margin:0;color:#9ca3af;font-size:13px;">&copy; {self.app_name} &mdash; AI-powered knowledge from your conversations</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    def _send_email(self, to_email: str, subject: str, html_body: str, text_body: str) -> bool:
        """Send an email via SMTP with HTML and plain-text fallback"""
        if not self.smtp_username or not self.smtp_password:
            logger.warning("SMTP credentials not configured, skipping email send")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject

            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
            server.quit()

            logger.info(f"Email sent to {to_email}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_invitation_email(self, to_email: str, temp_password: str, org_name: str = None) -> bool:
        """Send invitation email with temporary password"""
        org_name = org_name or self.app_name
        login_url = f"{self.app_url}/login"

        subject = f"You've been invited to join {org_name}"

        text_body = f"""You've been invited to join {org_name} on {self.app_name}!

Your login credentials:
  Email: {to_email}
  Password: {temp_password}

Log in here: {login_url}

Please change your password after logging in.

- The {self.app_name} Team
"""

        html_content = f"""
          <h2 style="margin:0 0 8px;color:#111827;font-size:20px;">You're invited!</h2>
          <p style="color:#4b5563;font-size:15px;line-height:1.6;">
            You've been invited to join <strong>{org_name}</strong> on {self.app_name}.
            Use the credentials below to log in.
          </p>
          <table cellpadding="0" cellspacing="0" style="margin:24px 0;width:100%;background-color:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">
            <tr><td style="padding:16px 20px;">
              <p style="margin:0 0 6px;color:#6b7280;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">Email</p>
              <p style="margin:0 0 14px;color:#111827;font-size:15px;font-weight:600;">{to_email}</p>
              <p style="margin:0 0 6px;color:#6b7280;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">Temporary Password</p>
              <p style="margin:0;color:#111827;font-size:15px;font-weight:600;font-family:monospace;">{temp_password}</p>
            </td></tr>
          </table>
          <table cellpadding="0" cellspacing="0" style="margin:24px auto;"><tr><td align="center" style="background-color:#6366f1;border-radius:6px;">
            <a href="{login_url}" style="display:inline-block;padding:12px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">Log In to {self.app_name}</a>
          </td></tr></table>
          <p style="color:#9ca3af;font-size:13px;line-height:1.5;margin:24px 0 0;">
            Please change your password after your first login.
          </p>"""

        html_body = self._base_html(html_content)
        return self._send_email(to_email, subject, html_body, text_body)

    def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        """Send password reset email with reset link"""
        reset_url = f"{self.app_url}/reset-password?token={reset_token}"

        subject = f"Reset your {self.app_name} password"

        text_body = f"""We received a request to reset your {self.app_name} password.

Reset your password here: {reset_url}

This link expires in 1 hour.

If you didn't request this, you can safely ignore this email.

- The {self.app_name} Team
"""

        html_content = f"""
          <h2 style="margin:0 0 8px;color:#111827;font-size:20px;">Reset your password</h2>
          <p style="color:#4b5563;font-size:15px;line-height:1.6;">
            We received a request to reset the password for your {self.app_name} account.
            Click the button below to set a new password.
          </p>
          <table cellpadding="0" cellspacing="0" style="margin:28px auto;"><tr><td align="center" style="background-color:#6366f1;border-radius:6px;">
            <a href="{reset_url}" style="display:inline-block;padding:12px 32px;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;">Reset Password</a>
          </td></tr></table>
          <p style="color:#9ca3af;font-size:13px;line-height:1.5;">
            This link will expire in 1 hour. If you didn't request a password reset, you can safely ignore this email.
          </p>"""

        html_body = self._base_html(html_content)
        return self._send_email(to_email, subject, html_body, text_body)


# Global instance
email_service = EmailService()
