"""
Credential Service - Manage encrypted Slack workspace credentials
Handles reading, writing, and migrating credentials with encryption
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from src.db.connection import DatabaseConnection
from src.utils.encryption import get_encryption_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CredentialService:
    """
    Service for managing encrypted Slack workspace credentials

    Features:
    - Store credentials with encryption
    - Retrieve and decrypt credentials
    - Migrate plaintext to encrypted
    - Verify credential validity
    """

    def __init__(self):
        self.encryption_manager = get_encryption_manager()

    def store_credentials(
        self,
        workspace_id: str,
        bot_token: str,
        app_token: Optional[str] = None,
        signing_secret: Optional[str] = None,
        bot_user_id: Optional[str] = None
    ) -> bool:
        """
        Store or update encrypted credentials for a workspace

        Args:
            workspace_id: Workspace ID
            bot_token: Slack bot token (xoxb-...)
            app_token: Slack app token (xapp-...) - optional
            signing_secret: Slack signing secret - optional
            bot_user_id: Bot user ID - optional

        Returns:
            True if successful, False otherwise
        """
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            # Encrypt credentials
            bot_token_enc = self.encryption_manager.encrypt(bot_token) if bot_token else None
            app_token_enc = self.encryption_manager.encrypt(app_token) if app_token else None
            signing_secret_enc = self.encryption_manager.encrypt(signing_secret) if signing_secret else None

            # Update or insert
            cur.execute("""
                INSERT INTO installations (
                    workspace_id,
                    bot_token,
                    app_token,
                    signing_secret,
                    bot_token_encrypted,
                    app_token_encrypted,
                    signing_secret_encrypted,
                    bot_user_id,
                    credentials_encrypted,
                    encryption_version,
                    installed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, 1, NOW())
                ON CONFLICT (workspace_id) DO UPDATE SET
                    bot_token = EXCLUDED.bot_token,
                    app_token = EXCLUDED.app_token,
                    signing_secret = EXCLUDED.signing_secret,
                    bot_token_encrypted = EXCLUDED.bot_token_encrypted,
                    app_token_encrypted = EXCLUDED.app_token_encrypted,
                    signing_secret_encrypted = EXCLUDED.signing_secret_encrypted,
                    bot_user_id = EXCLUDED.bot_user_id,
                    credentials_encrypted = TRUE,
                    encryption_version = 1
            """, (
                workspace_id,
                bot_token,  # Keep plaintext for backward compatibility during migration
                app_token,
                signing_secret,
                bot_token_enc,
                app_token_enc,
                signing_secret_enc,
                bot_user_id
            ))

            conn.commit()

            logger.info(f"✅ Stored encrypted credentials for workspace {workspace_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error storing credentials for {workspace_id}: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()

    def get_credentials(self, workspace_id: str) -> Optional[Dict[str, str]]:
        """
        Retrieve and decrypt credentials for a workspace

        Args:
            workspace_id: Workspace ID

        Returns:
            Dict with decrypted credentials or None if not found

        Example:
            >>> service = CredentialService()
            >>> creds = service.get_credentials("W_DEFAULT")
            >>> print(creds)
            {
                'bot_token': 'xoxb-...',
                'app_token': 'xapp-...',
                'signing_secret': '...',
                'bot_user_id': 'U123...'
            }
        """
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT
                    credentials_encrypted,
                    bot_token,
                    app_token,
                    signing_secret,
                    bot_token_encrypted,
                    app_token_encrypted,
                    signing_secret_encrypted,
                    bot_user_id,
                    is_valid
                FROM installations
                WHERE workspace_id = %s AND is_active = TRUE
            """, (workspace_id,))

            row = cur.fetchone()
            if not row:
                logger.warning(f"No credentials found for workspace {workspace_id}")
                return None

            (credentials_encrypted, bot_token, app_token, signing_secret,
             bot_token_enc, app_token_enc, signing_secret_enc, bot_user_id, is_valid) = row

            # Use encrypted credentials if available
            if credentials_encrypted and bot_token_enc:
                return {
                    'bot_token': self.encryption_manager.decrypt(bot_token_enc),
                    'app_token': self.encryption_manager.decrypt(app_token_enc) if app_token_enc else None,
                    'signing_secret': self.encryption_manager.decrypt(signing_secret_enc) if signing_secret_enc else None,
                    'bot_user_id': bot_user_id,
                    'is_valid': is_valid
                }
            else:
                # Fallback to plaintext (for backward compatibility)
                logger.warning(f"⚠️  Using plaintext credentials for {workspace_id} - consider migrating")
                return {
                    'bot_token': bot_token,
                    'app_token': app_token,
                    'signing_secret': signing_secret,
                    'bot_user_id': bot_user_id,
                    'is_valid': is_valid
                }

        except Exception as e:
            logger.error(f"❌ Error retrieving credentials for {workspace_id}: {e}", exc_info=True)
            return None
        finally:
            cur.close()
            conn.close()

    def verify_credentials(self, workspace_id: str) -> bool:
        """
        Verify credentials are valid by testing with Slack API

        Args:
            workspace_id: Workspace ID

        Returns:
            True if credentials are valid, False otherwise
        """
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError

        credentials = self.get_credentials(workspace_id)
        if not credentials or not credentials.get('bot_token'):
            return False

        try:
            client = WebClient(token=credentials['bot_token'])
            response = client.auth_test()

            # Update verification status
            self._update_verification_status(workspace_id, is_valid=True)

            logger.info(f"✅ Credentials verified for workspace {workspace_id}")
            return True

        except SlackApiError as e:
            logger.error(f"❌ Invalid credentials for {workspace_id}: {e.response['error']}")
            self._update_verification_status(workspace_id, is_valid=False)
            return False

    def _update_verification_status(self, workspace_id: str, is_valid: bool):
        """Update credential verification status in database"""
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                UPDATE installations
                SET
                    is_valid = %s,
                    last_verified_at = NOW()
                WHERE workspace_id = %s
            """, (is_valid, workspace_id))

            conn.commit()

        except Exception as e:
            logger.error(f"Error updating verification status: {e}")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    def migrate_plaintext_to_encrypted(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Migrate plaintext credentials to encrypted

        Args:
            workspace_id: Specific workspace to migrate, or None for all

        Returns:
            Dict with migration results
        """
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            # Find workspaces with plaintext credentials
            if workspace_id:
                cur.execute("""
                    SELECT workspace_id, bot_token, app_token, signing_secret
                    FROM installations
                    WHERE workspace_id = %s
                      AND credentials_encrypted = FALSE
                      AND bot_token IS NOT NULL
                """, (workspace_id,))
            else:
                cur.execute("""
                    SELECT workspace_id, bot_token, app_token, signing_secret
                    FROM installations
                    WHERE credentials_encrypted = FALSE
                      AND bot_token IS NOT NULL
                """)

            workspaces = cur.fetchall()

            if not workspaces:
                logger.info("No workspaces to migrate")
                return {'migrated': 0, 'failed': 0}

            migrated = 0
            failed = 0

            for workspace_id, bot_token, app_token, signing_secret in workspaces:
                try:
                    # Encrypt credentials
                    bot_token_enc = self.encryption_manager.encrypt(bot_token) if bot_token else None
                    app_token_enc = self.encryption_manager.encrypt(app_token) if app_token else None
                    signing_secret_enc = self.encryption_manager.encrypt(signing_secret) if signing_secret else None

                    # Update database
                    cur.execute("""
                        UPDATE installations
                        SET
                            bot_token_encrypted = %s,
                            app_token_encrypted = %s,
                            signing_secret_encrypted = %s,
                            credentials_encrypted = TRUE,
                            encryption_version = 1
                        WHERE workspace_id = %s
                    """, (bot_token_enc, app_token_enc, signing_secret_enc, workspace_id))

                    conn.commit()
                    migrated += 1
                    logger.info(f"✅ Migrated credentials for {workspace_id}")

                except Exception as e:
                    logger.error(f"❌ Failed to migrate {workspace_id}: {e}")
                    conn.rollback()
                    failed += 1

            logger.info(f"Migration complete: {migrated} succeeded, {failed} failed")

            return {
                'migrated': migrated,
                'failed': failed,
                'total': len(workspaces)
            }

        finally:
            cur.close()
            conn.close()


# Example usage
if __name__ == "__main__":
    import os

    service = CredentialService()

    # Test 1: Store encrypted credentials
    print("Test 1: Storing encrypted credentials...")
    success = service.store_credentials(
        workspace_id="TEST_WORKSPACE",
        bot_token="xoxb-test-token-123",
        app_token="xapp-test-token-456",
        signing_secret="test-secret-789",
        bot_user_id="U_TEST123"
    )
    print(f"✅ Store: {success}")

    # Test 2: Retrieve credentials
    print("\nTest 2: Retrieving credentials...")
    creds = service.get_credentials("TEST_WORKSPACE")
    if creds:
        print(f"✅ Retrieved: bot_token={creds['bot_token'][:20]}...")
        print(f"   Decryption successful: {creds['bot_token'] == 'xoxb-test-token-123'}")
    else:
        print("❌ Failed to retrieve")

    # Test 3: Verify credentials (will fail with test tokens)
    print("\nTest 3: Verifying credentials...")
    # This will fail with fake tokens, which is expected
    # valid = service.verify_credentials("TEST_WORKSPACE")
    # print(f"Valid: {valid}")

    print("\n✅ All tests completed")
