"""
Encryption Utilities for Sensitive Data
Uses Fernet (symmetric encryption) for encrypting credentials at rest
"""

import os
import base64
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import logging

logger = logging.getLogger(__name__)


class EncryptionManager:
    """
    Manages encryption/decryption of sensitive data like Slack tokens

    Uses Fernet symmetric encryption with a key derived from ENCRYPTION_KEY env var
    """

    def __init__(self):
        """Initialize encryption manager with key from environment"""
        encryption_key = os.getenv("ENCRYPTION_KEY")

        if not encryption_key:
            logger.warning(
                "⚠️  ENCRYPTION_KEY not set in environment! "
                "Using default key for development. "
                "NEVER use in production!"
            )
            # Default key for development only
            encryption_key = "dev-encryption-key-change-in-production"

        # Derive a valid Fernet key from the encryption key
        self.fernet = self._create_fernet(encryption_key)

    def _create_fernet(self, password: str) -> Fernet:
        """
        Create Fernet instance from password string

        Args:
            password: Encryption key/password from environment

        Returns:
            Fernet instance for encryption/decryption
        """
        # Use PBKDF2HMAC to derive a valid 32-byte key from the password
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'slack-helper-salt',  # Static salt (OK for symmetric encryption)
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string

        Args:
            plaintext: String to encrypt (e.g., Slack bot token)

        Returns:
            Encrypted string (base64 encoded)

        Example:
            >>> manager = EncryptionManager()
            >>> encrypted = manager.encrypt("xoxb-123456-abcdef")
            >>> print(encrypted)
            'gAAAAABl...'
        """
        if not plaintext:
            return ""

        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode())
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"❌ Encryption error: {e}", exc_info=True)
            raise ValueError(f"Failed to encrypt data: {e}")

    def decrypt(self, encrypted_text: str) -> str:
        """
        Decrypt an encrypted string

        Args:
            encrypted_text: Encrypted string (base64 encoded)

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (wrong key, corrupted data)

        Example:
            >>> manager = EncryptionManager()
            >>> decrypted = manager.decrypt("gAAAAABl...")
            >>> print(decrypted)
            'xoxb-123456-abcdef'
        """
        if not encrypted_text:
            return ""

        try:
            decrypted_bytes = self.fernet.decrypt(encrypted_text.encode())
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"❌ Decryption error: {e}", exc_info=True)
            raise ValueError(f"Failed to decrypt data: {e}")

    def encrypt_dict(self, data: dict, fields: list) -> dict:
        """
        Encrypt specific fields in a dictionary

        Args:
            data: Dictionary containing sensitive fields
            fields: List of field names to encrypt

        Returns:
            New dictionary with specified fields encrypted

        Example:
            >>> manager = EncryptionManager()
            >>> data = {
            ...     "workspace_id": "W123",
            ...     "bot_token": "xoxb-secret",
            ...     "app_token": "xapp-secret"
            ... }
            >>> encrypted = manager.encrypt_dict(data, ["bot_token", "app_token"])
            >>> print(encrypted["bot_token"])
            'gAAAAABl...'
        """
        result = data.copy()
        for field in fields:
            if field in result and result[field]:
                result[field] = self.encrypt(result[field])
        return result

    def decrypt_dict(self, data: dict, fields: list) -> dict:
        """
        Decrypt specific fields in a dictionary

        Args:
            data: Dictionary containing encrypted fields
            fields: List of field names to decrypt

        Returns:
            New dictionary with specified fields decrypted

        Example:
            >>> manager = EncryptionManager()
            >>> encrypted_data = {"bot_token": "gAAAAABl..."}
            >>> decrypted = manager.decrypt_dict(encrypted_data, ["bot_token"])
            >>> print(decrypted["bot_token"])
            'xoxb-secret'
        """
        result = data.copy()
        for field in fields:
            if field in result and result[field]:
                result[field] = self.decrypt(result[field])
        return result


# Global instance for convenience
_encryption_manager: Optional[EncryptionManager] = None


def get_encryption_manager() -> EncryptionManager:
    """
    Get singleton encryption manager instance

    Returns:
        Global EncryptionManager instance
    """
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


# Convenience functions
def encrypt_string(plaintext: str) -> str:
    """Encrypt a string using global encryption manager"""
    return get_encryption_manager().encrypt(plaintext)


def decrypt_string(encrypted_text: str) -> str:
    """Decrypt a string using global encryption manager"""
    return get_encryption_manager().decrypt(encrypted_text)


def encrypt_credentials(
    bot_token: str,
    app_token: Optional[str] = None,
    signing_secret: Optional[str] = None
) -> dict:
    """
    Encrypt Slack credentials

    Args:
        bot_token: Slack bot token (required)
        app_token: Slack app token (optional)
        signing_secret: Slack signing secret (optional)

    Returns:
        Dict with encrypted credentials

    Example:
        >>> encrypted = encrypt_credentials(
        ...     bot_token="xoxb-123",
        ...     app_token="xapp-456"
        ... )
        >>> print(encrypted)
        {
            'bot_token_encrypted': 'gAAAAABl...',
            'app_token_encrypted': 'gAAAAABl...',
            'signing_secret_encrypted': None
        }
    """
    manager = get_encryption_manager()

    return {
        'bot_token_encrypted': manager.encrypt(bot_token) if bot_token else None,
        'app_token_encrypted': manager.encrypt(app_token) if app_token else None,
        'signing_secret_encrypted': manager.encrypt(signing_secret) if signing_secret else None
    }


def decrypt_credentials(encrypted_data: dict) -> dict:
    """
    Decrypt Slack credentials

    Args:
        encrypted_data: Dict with encrypted credential fields

    Returns:
        Dict with decrypted credentials

    Example:
        >>> encrypted = {
        ...     'bot_token_encrypted': 'gAAAAABl...',
        ...     'app_token_encrypted': 'gAAAAABl...'
        ... }
        >>> decrypted = decrypt_credentials(encrypted)
        >>> print(decrypted)
        {
            'bot_token': 'xoxb-123',
            'app_token': 'xapp-456',
            'signing_secret': None
        }
    """
    manager = get_encryption_manager()

    return {
        'bot_token': manager.decrypt(encrypted_data.get('bot_token_encrypted', ''))
                     if encrypted_data.get('bot_token_encrypted') else None,
        'app_token': manager.decrypt(encrypted_data.get('app_token_encrypted', ''))
                     if encrypted_data.get('app_token_encrypted') else None,
        'signing_secret': manager.decrypt(encrypted_data.get('signing_secret_encrypted', ''))
                          if encrypted_data.get('signing_secret_encrypted') else None
    }


def test_encryption():
    """
    Test encryption/decryption functionality
    Useful for verifying encryption setup
    """
    print("🔐 Testing encryption utilities...")

    manager = EncryptionManager()

    # Test 1: Simple string encryption
    test_string = "xoxb-617883639172-test-token-secret"
    encrypted = manager.encrypt(test_string)
    decrypted = manager.decrypt(encrypted)

    assert decrypted == test_string, "String encryption failed"
    print(f"✅ String encryption: {test_string[:20]}... → {encrypted[:30]}...")

    # Test 2: Credential encryption
    credentials = {
        'bot_token': 'xoxb-123456-secret',
        'app_token': 'xapp-789012-secret',
        'signing_secret': 'abc123def456'
    }

    encrypted_creds = encrypt_credentials(**credentials)
    decrypted_creds = decrypt_credentials(encrypted_creds)

    assert decrypted_creds['bot_token'] == credentials['bot_token'], "Credential encryption failed"
    print(f"✅ Credential encryption: bot_token → {encrypted_creds['bot_token_encrypted'][:30]}...")

    # Test 3: Empty string handling
    assert manager.encrypt("") == ""
    assert manager.decrypt("") == ""
    print("✅ Empty string handling: OK")

    print("✅ All encryption tests passed!")


if __name__ == "__main__":
    # Run tests when executed directly
    test_encryption()
