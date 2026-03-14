"""Repository for trusted device operations"""

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.db.models.trusted_device import TrustedDevice


class TrustedDeviceRepository:
    """Repository for managing trusted devices"""

    def __init__(self, db: Session):
        self.db = db

    def generate_device_token(self) -> str:
        """Generate a secure random token for device identification"""
        return secrets.token_urlsafe(32)

    def hash_device_token(self, token: str) -> str:
        """Hash device token for secure storage (following Google/AWS/Azure patterns)"""
        return hashlib.sha256(token.encode()).hexdigest()

    def generate_device_fingerprint(self, fingerprint_data: dict, ip_address: str = None) -> str:
        """Generate device fingerprint from browser characteristics + IP address

        CRITICAL: Combines User-Agent + IP + hashed device ID for robust fingerprinting
        Following Google/AWS/Azure patterns by using browser + OS + hardware characteristics
        plus IP address for additional security layer.

        Args:
            fingerprint_data: Dictionary containing browser characteristics
            ip_address: Optional IP address to include in fingerprint

        Returns:
            SHA-256 hash of the combined fingerprint data
        """
        if not fingerprint_data:
            # Fallback: use empty string if no data provided
            fingerprint_data = {}

        # CRITICAL: Combine all fingerprint properties into a deterministic string
        # Order matters for consistency
        # Include IP address for additional security (even though IPs can change)
        fingerprint_string = ":".join(
            [
                str(fingerprint_data.get("userAgent", "")),  # User-Agent (browser + OS)
                str(ip_address or ""),  # IP address (additional security layer)
                str(fingerprint_data.get("language", "")),
                str(fingerprint_data.get("platform", "")),
                str(fingerprint_data.get("screenResolution", "")),
                str(fingerprint_data.get("timezone", "")),
                str(fingerprint_data.get("colorDepth", "")),
                str(fingerprint_data.get("hardwareConcurrency", "")),
                str(fingerprint_data.get("maxTouchPoints", "")),
                str(fingerprint_data.get("deviceMemory", "")),
            ]
        )
        return hashlib.sha256(fingerprint_string.encode()).hexdigest()

    def create_trusted_device(
        self, user_id: UUID, device_token: str, device_fingerprint: str, expires_at: datetime
    ) -> TrustedDevice:
        """Create a new trusted device record"""
        trusted_device = TrustedDevice(
            user_id=user_id,
            device_token=device_token,
            device_fingerprint=device_fingerprint,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
            last_used_at=datetime.now(timezone.utc),
        )
        self.db.add(trusted_device)
        return trusted_device

    def get_trusted_device_by_token(self, device_token: str) -> TrustedDevice | None:
        """Get a trusted device by its token (hashed)"""
        hashed_token = self.hash_device_token(device_token)
        return self.db.query(TrustedDevice).filter(TrustedDevice.device_token == hashed_token).first()

    def get_trusted_device_by_token_hash(self, hashed_token: str) -> TrustedDevice | None:
        """Get a trusted device by its hashed token"""
        return self.db.query(TrustedDevice).filter(TrustedDevice.device_token == hashed_token).first()

    def get_trusted_device_by_fingerprint(self, user_id: UUID, device_fingerprint: str) -> TrustedDevice | None:
        """Get a trusted device by user ID and fingerprint"""
        return (
            self.db.query(TrustedDevice)
            .filter(
                and_(
                    TrustedDevice.user_id == user_id,
                    TrustedDevice.device_fingerprint == device_fingerprint,
                    TrustedDevice.expires_at > datetime.now(timezone.utc),  # Only return non-expired devices
                )
            )
            .first()
        )

    def update_last_used(self, trusted_device: TrustedDevice) -> None:
        """Update the last_used_at timestamp for a trusted device"""
        trusted_device.last_used_at = datetime.now(timezone.utc)

    def delete_expired_devices(self) -> int:
        """Delete all expired trusted devices and return count of deleted devices"""
        deleted_count = (
            self.db.query(TrustedDevice).filter(TrustedDevice.expires_at < datetime.now(timezone.utc)).delete()
        )
        return deleted_count

    def delete_user_devices(self, user_id: UUID) -> int:
        """Delete all trusted devices for a user (e.g., on logout or password change)"""
        deleted_count = self.db.query(TrustedDevice).filter(TrustedDevice.user_id == user_id).delete()
        return deleted_count

    def delete_device(self, device_token: str) -> bool:
        """Delete a specific trusted device by token (hashed)"""
        hashed_token = self.hash_device_token(device_token)
        deleted_count = self.db.query(TrustedDevice).filter(TrustedDevice.device_token == hashed_token).delete()
        return deleted_count > 0
