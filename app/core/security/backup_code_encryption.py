"""Encryption utilities for 2FA backup codes

Uses Fernet (symmetric encryption) for secure storage of backup codes.
Fernet provides authenticated encryption with AES 128 in CBC mode.
"""

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class BackupCodeEncryption:
    """Encryption service for 2FA backup codes"""

    def __init__(self, encryption_key: str | None = None):
        """Initialize encryption with a key

        Args:
            encryption_key: Base64-encoded Fernet key, or None to derive from environment/config
        """
        if encryption_key:
            self.fernet = Fernet(encryption_key.encode())
        else:
            # Derive key from environment variable or generate a default (for development only)
            key_material = os.getenv("BACKUP_CODE_ENCRYPTION_KEY", "")
            if key_material:
                # If a key is provided, use it directly (should be base64-encoded Fernet key)
                try:
                    self.fernet = Fernet(key_material.encode())
                except Exception:
                    # If not a valid Fernet key, derive one from the material
                    self.fernet = self._derive_fernet_key(key_material)
            else:
                # Development fallback: derive from a default (NOT for production!)
                # In production, BACKUP_CODE_ENCRYPTION_KEY must be set
                default_key_material = "workflow-engine-backup-codes-default-key-change-in-production"
                self.fernet = self._derive_fernet_key(default_key_material)

    @staticmethod
    def _derive_fernet_key(password: str, salt: bytes | None = None) -> Fernet:
        """Derive a Fernet key from a password using PBKDF2

        Args:
            password: Password string to derive key from
            salt: Optional salt (defaults to a fixed salt for consistency)

        Returns:
            Fernet instance with derived key
        """
        if salt is None:
            # Use a fixed salt for consistency (in production, consider storing salt separately)
            salt = b"workflow-engine-backup-code-salt"

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,  # High iteration count for security
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    @staticmethod
    def generate_fernet_key() -> str:
        """Generate a new Fernet key for production use

        Returns:
            Base64-encoded Fernet key (safe to store in environment variable)
        """
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a backup code

        Args:
            plaintext: Plaintext backup code to encrypt

        Returns:
            Encrypted backup code (base64-encoded)
        """
        encrypted = self.fernet.encrypt(plaintext.encode())
        return encrypted.decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a backup code

        Args:
            ciphertext: Encrypted backup code (base64-encoded)

        Returns:
            Decrypted backup code

        Raises:
            Exception: If decryption fails (invalid key, tampered data, etc.)
        """
        decrypted = self.fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
