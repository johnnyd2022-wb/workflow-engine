"""Request schemas for account creation, sign-in and profile management."""

from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from app.api.middleware.session_security import MAX_SESSION_TIMEOUT_MINUTES, MIN_SESSION_TIMEOUT_MINUTES
from app.utils.request_validation import CleanName, CleanText, JsonInput

EmailText = Annotated[CleanName, StringConstraints(max_length=255)]
Name = Annotated[CleanName, StringConstraints(max_length=255)]
OptionalName = Annotated[CleanText, StringConstraints(max_length=255)]
PhoneText = Annotated[str, StringConstraints(max_length=64)]
Password = Annotated[str, StringConstraints(min_length=1)]
Totp = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]
INVITE_TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"
InviteToken = Annotated[str, StringConstraints(pattern=INVITE_TOKEN_PATTERN)]

FingerprintText = Annotated[str, StringConstraints(max_length=512)]
FingerprintInt = Annotated[int, Field(ge=0, le=16_384)]


class DeviceFingerprint(JsonInput):
    user_agent: FingerprintText = Field(default="", alias="userAgent")
    language: FingerprintText = ""
    platform: FingerprintText = ""
    screen_resolution: FingerprintText = Field(default="", alias="screenResolution")
    timezone: FingerprintText = ""
    color_depth: FingerprintInt = Field(default=0, alias="colorDepth")
    hardware_concurrency: FingerprintInt = Field(default=0, alias="hardwareConcurrency")
    max_touch_points: FingerprintInt = Field(default=0, alias="maxTouchPoints")
    device_memory: Annotated[int | float, Field(ge=0, le=16_384)] = Field(default=0, alias="deviceMemory")


class LoginInput(JsonInput):
    # Keep the established behavior of ignoring unused flags, including org_id and password_reset.
    model_config = ConfigDict(extra="ignore")

    email: EmailText
    password: Password
    device_fingerprint: DeviceFingerprint = Field(default_factory=DeviceFingerprint)


class SignupInput(JsonInput):
    org_name: Name
    email: EmailText
    password: Password
    password_confirm: Password
    phone_number: PhoneText | None = None


class AcceptInviteInput(JsonInput):
    token: InviteToken
    password: Password
    password_confirm: Password
    first_name: OptionalName | None = None
    last_name: OptionalName | None = None


class VerifyTwoFactorInput(JsonInput):
    token: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(?:[0-9]{6}|[A-Za-z0-9]{8})$")]
    remember_device: bool = False
    device_fingerprint: DeviceFingerprint = Field(default_factory=DeviceFingerprint)


class EnableTwoFactorInput(JsonInput):
    token1: Totp
    token2: Totp


class SessionTimeoutInput(JsonInput):
    session_timeout_minutes: Annotated[int, Field(ge=MIN_SESSION_TIMEOUT_MINUTES, le=MAX_SESSION_TIMEOUT_MINUTES)]


class PasswordPolicyInput(JsonInput):
    password: Annotated[str, StringConstraints(max_length=1024)]


class ChangePasswordInput(JsonInput):
    current_password: Password
    new_password: Password
    new_password_confirm: Password


class UserSettingsInput(JsonInput):
    email: EmailText | None = None
    first_name: OptionalName | None = None
    last_name: OptionalName | None = None
    phone_number: PhoneText | None = None
