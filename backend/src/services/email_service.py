"""
Email service for sending invitations and notifications
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
        
    def send_invitation_email(self, to_email: str, temp_password: str, org_name: str = "Slack Helper") -> bool:
        """Send invitation email with temporary password"""
        if not self.smtp_username or not self.smtp_password:
            logger.warning("SMTP credentials not configured, skipping email send")
            return False
            
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"You've been invited to join {org_name}"
            
            # Email body
            body = f"""
Hello!

You've been invited to join {org_name} on Slack Helper.

Your temporary login credentials:
Email: {to_email}
Password: {temp_password}

Please log in and change your password: http://localhost:3000/login

Best regards,
The Slack Helper Team
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
            server.quit()
            
            logger.info(f"Invitation email sent to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False


# Global instance
email_service = EmailService()