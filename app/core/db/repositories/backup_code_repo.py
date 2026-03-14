"""Repository for 2FA backup code operations"""

import secrets
import string
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.two_factor_backup_code import TwoFactorBackupCode
from app.core.security.backup_code_encryption import BackupCodeEncryption


class BackupCodeRepository:
    """Repository for backup code operations"""

    def __init__(self, db: Session, encryption: BackupCodeEncryption | None = None):
        """Initialize repository

        Args:
            db: Database session
            encryption: Encryption service instance (creates default if not provided)
        """
        self.db = db
        self.encryption = encryption or BackupCodeEncryption()

    @staticmethod
    def generate_backup_code(length: int = 8) -> str:
        """Generate a random backup code

        Args:
            length: Length of the code (default 8)

        Returns:
            Random alphanumeric code
        """
        # Use letters (both cases) and digits
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def generate_and_store_codes(self, user_id: UUID, count: int = 10, commit: bool = False) -> list[str]:
        """Generate backup codes and store them encrypted in the database

        Args:
            user_id: User ID to generate codes for
            count: Number of codes to generate (default 10)
            commit: Whether to commit the transaction (default False, let caller control)

        Returns:
            List of plaintext backup codes (for one-time display to user)

        Note:
            CRITICAL: By default, this method does NOT commit the transaction.
            The caller must commit to ensure atomicity with other operations.
            Set commit=True only if this is the only operation in the transaction.
        """
        plaintext_codes = []
        backup_codes = []

        for _ in range(count):
            # Generate plaintext code
            code = self.generate_backup_code()
            plaintext_codes.append(code)

            # Encrypt and store
            encrypted_code = self.encryption.encrypt(code)
            backup_code = TwoFactorBackupCode(
                user_id=user_id,
                encrypted_code=encrypted_code,
                consumed=False,
            )
            backup_codes.append(backup_code)

        # Bulk insert all codes
        self.db.add_all(backup_codes)

        # CRITICAL: Only commit if explicitly requested
        # This allows the caller to wrap this in a larger transaction
        if commit:
            self.db.commit()

        return plaintext_codes

    def verify_and_consume_code(self, user_id: UUID, code: str) -> bool:
        """Verify a backup code and mark it as consumed if valid

        Args:
            user_id: User ID
            code: Plaintext backup code to verify

        Returns:
            True if code is valid and was consumed, False otherwise
        """
        if not code:
            return False

        # Normalize the input code (trim whitespace, but preserve case since codes are case-sensitive)
        code = code.strip()

        # Validate format: exactly 8 alphanumeric ASCII characters
        if len(code) != 8 or not code.isalnum():
            return False

        # CRITICAL: Use SELECT FOR UPDATE to lock rows and prevent race conditions
        # This ensures only one request can consume a code at a time
        backup_codes = (
            self.db.query(TwoFactorBackupCode)
            .filter(TwoFactorBackupCode.user_id == user_id)
            .filter(TwoFactorBackupCode.consumed.is_(False))
            .with_for_update()  # Lock rows to prevent concurrent consumption
            .all()
        )

        # Try to match the code against each encrypted code
        matched = False
        for backup_code in backup_codes:
            try:
                decrypted_code = self.encryption.decrypt(backup_code.encrypted_code)
                # Use constant-time comparison to prevent timing attacks
                if secrets.compare_digest(decrypted_code.strip(), code):
                    # Code matches - mark as consumed
                    backup_code.consumed = True
                    matched = True
                    break  # Found match, no need to check others
            except Exception as e:
                # Decryption failed or code doesn't match - continue to next
                # Log the exception for debugging (but don't expose sensitive info)
                import logging

                logger = logging.getLogger(__name__)
                logger.debug(f"Backup code verification failed: {type(e).__name__}")
                continue

        # Commit only if we found a match (atomic operation)
        if matched:
            self.db.commit()
            return True
        else:
            # No match found - rollback to release locks
            self.db.rollback()
            return False

    def delete_all_codes_for_user(self, user_id: UUID, commit: bool = False) -> int:
        """Delete all backup codes for a user (used when disabling 2FA)

        Args:
            user_id: User ID
            commit: Whether to commit the transaction (default False, let caller control)

        Returns:
            Number of codes deleted

        Note:
            CRITICAL: By default, this method does NOT commit the transaction.
            The caller must commit to ensure atomicity with other operations.
            Set commit=True only if this is the only operation in the transaction.
        """
        deleted_count = self.db.query(TwoFactorBackupCode).filter(TwoFactorBackupCode.user_id == user_id).delete()

        # CRITICAL: Only commit if explicitly requested
        # This allows the caller to wrap this in a larger transaction
        if commit:
            self.db.commit()

        return deleted_count

    def get_unconsumed_count(self, user_id: UUID) -> int:
        """Get count of unconsumed backup codes for a user

        Args:
            user_id: User ID

        Returns:
            Number of unconsumed codes
        """
        return (
            self.db.query(TwoFactorBackupCode)
            .filter(TwoFactorBackupCode.user_id == user_id)
            .filter(TwoFactorBackupCode.consumed.is_(False))
            .count()
        )

    def get_all_codes_for_user(self, user_id: UUID) -> list[TwoFactorBackupCode]:
        """Get all backup codes for a user (for admin retrieval)

        Args:
            user_id: User ID

        Returns:
            List of backup code records
        """
        return self.db.query(TwoFactorBackupCode).filter(TwoFactorBackupCode.user_id == user_id).all()
