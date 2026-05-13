import configparser
import os
import sys
from pathlib import Path
from typing import Any


class Config:
    """Configuration loader for environment-specific settings"""

    def __init__(self):
        self.config = configparser.ConfigParser()
        self.environment = os.getenv("ENVIRONMENT", "local")
        self._keepass_creds: dict | None = None
        self.load_config()
        self._load_keepass_creds()

    def load_config(self):
        """Load configuration based on environment"""
        # Get the app directory (where this module is located)
        # This works regardless of the current working directory
        app_dir = Path(__file__).parent.parent
        config_file = app_dir / "config" / f"{self.environment}.ini"

        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file {config_file} not found")

        self.config.read(config_file)
        print(f"✅ Loaded configuration for environment: {self.environment} from {config_file}")

    def _load_keepass_creds(self):
        """Attempt to load database credentials from KeePassXC"""
        # Only try KeePassXC for local environment
        if self.environment != "local":
            return

        try:
            # Import the keepass function from scripts
            scripts_dir = Path(__file__).parent.parent.parent / "scripts"
            if (scripts_dir / "local_secrets.py").exists():
                sys.path.insert(0, str(scripts_dir))
                from local_secrets import get_keepass_entry

                # Enable verbose logging if KEEPASS_VERBOSE env var is set
                verbose = os.getenv("KEEPASS_VERBOSE", "").lower() in ("1", "true", "yes")
                creds = get_keepass_entry(verbose=verbose)
                if creds and "Password" in creds:
                    password = creds["Password"]
                    # Only use KeePassXC if we got a valid password (not empty or "PROTECTED")
                    if password and password != "PROTECTED" and password.strip():
                        self._keepass_creds = creds
                        print("✅ Loaded database credentials from KeePassXC")
                    else:
                        if verbose:
                            print(f"⚠️  KeePassXC password is '{password}', using config file credentials")
                        else:
                            print("ℹ️  KeePassXC not available or database locked, using config file credentials")
                else:
                    if verbose:
                        print(f"⚠️  KeePassXC returned: {creds}, using config file credentials")
                    else:
                        print("ℹ️  KeePassXC not available or database locked, using config file credentials")
        except Exception as e:
            # Log error if verbose, otherwise silently fail and use config file
            if os.getenv("KEEPASS_VERBOSE", "").lower() in ("1", "true", "yes"):
                print(f"⚠️  KeePassXC error: {e}, using config file credentials")
            else:
                print("ℹ️  KeePassXC not available or database locked, using config file credentials")

    def get(self, section: str, key: str, fallback: Any = None) -> str:
        """Get a configuration value"""
        return self.config.get(section, key, fallback=fallback)

    def getboolean(self, section: str, key: str, fallback: bool = False) -> bool:
        """Get a boolean configuration value"""
        return self.config.getboolean(section, key, fallback=fallback)

    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        """Get an integer configuration value"""
        return self.config.getint(section, key, fallback=fallback)

    @property
    def environment(self) -> str:
        return self._environment

    @environment.setter
    def environment(self, value: str):
        self._environment = value

    @property
    def debug(self) -> bool:
        return self.getboolean("app", "debug", False)

    @property
    def is_production(self) -> bool:
        """True when running with production config (used to omit sensitive API error details)."""
        return (self.environment or "").strip().lower() == "production"

    @property
    def host(self) -> str:
        return self.get("app", "host", "localhost")

    @property
    def port(self) -> int:
        return self.getint("app", "port", 5000)

    @property
    def db_host(self) -> str:
        return self.get("database", "host", "localhost")

    @property
    def db_port(self) -> int:
        return self.getint("database", "port", 5432)

    @property
    def db_name(self) -> str:
        return self.get("database", "name", "workflow-engine-test-db")

    @property
    def db_user(self) -> str:
        # For test environment, check for environment variable first
        if self.environment == "test":
            use_env_var = self.getboolean("database", "use_env_var", False)
            if use_env_var:
                env_user = os.getenv("POSTGRES_USER")
                if env_user:
                    return env_user
        # Try KeePassXC first (for local environment), fallback to config file
        if self._keepass_creds and "Username" in self._keepass_creds:
            return self._keepass_creds["Username"]
        return self.get("database", "user", "postgres")

    @property
    def db_password(self) -> str:
        # For test environment, check for environment variable first
        if self.environment == "test":
            use_env_var = self.getboolean("database", "use_env_var", False)
            if use_env_var:
                # Check both POSTGRES_PASSWORD and POSTGRES_PASSWORD_TEST for compatibility
                env_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("POSTGRES_PASSWORD_TEST")
                if env_password:
                    # Strip quotes if present (handles cases where export used quotes)
                    env_password = env_password.strip("\"'")
                    if env_password:
                        return env_password
        # Try KeePassXC first (for local environment), fallback to config file
        if self._keepass_creds and "Password" in self._keepass_creds:
            return self._keepass_creds["Password"]
        return self.get("database", "password", "")

    @property
    def xero_client_id(self) -> str:
        return os.getenv("XERO_CLIENT_ID") or self.get("xero", "client_id", "")

    @property
    def xero_client_secret(self) -> str:
        return os.getenv("XERO_CLIENT_SECRET") or self.get("xero", "client_secret", "")

    @property
    def xero_redirect_uri(self) -> str:
        return os.getenv("XERO_REDIRECT_URI") or self.get("xero", "redirect_uri", "")

    @property
    def sender_email(self) -> str:
        return self.get("email", "sender_email", "")

    @property
    def receiver_email(self) -> str:
        return self.get("email", "receiver_email", "")

    @property
    def invoice_button_enabled(self) -> bool:
        return self.getboolean("features", "invoice_button_enabled", False)

    @property
    def schedule_enabled(self) -> bool:
        return self.getboolean("features", "schedule_enabled", True)

    @property
    def docker_enabled(self) -> bool:
        return self.getboolean("docker", "enabled", False)

    @property
    def docker_container_name(self) -> str:
        return self.get("docker", "container_name", "whistlebird_db")

    @property
    def docker_image_name(self) -> str:
        return self.get("docker", "image_name", "postgres")

    @property
    def docker_host_port(self) -> int:
        return self.getint("docker", "host_port", 5432)

    @property
    def docker_container_port(self) -> int:
        return self.getint("docker", "container_port", 5432)

    @property
    def crm_enabled(self) -> bool:
        return self.getboolean("features", "crm_enabled", True)

    @property
    def workflow_engine_enabled(self) -> bool:
        return self.getboolean("features", "workflow_engine_enabled", True)

    @property
    def db_readonly_user(self) -> str:
        """Read-only database user (for reporting/read-only connections)"""
        # Try KeePassXC first (look for ReadonlyUsername or Notes field), fallback to config
        if self._keepass_creds:
            # Check if there's a readonly username in Notes or a separate field
            if "ReadonlyUsername" in self._keepass_creds:
                return self._keepass_creds["ReadonlyUsername"]
            # Could also parse Notes field if it contains readonly credentials
        return self.get("database", "readonly_user", self.db_user)

    @property
    def evidence_storage_root(self) -> str:
        """Root directory for evidence file storage (default: app-relative evidence_storage)."""
        return self.get("evidence", "storage_root", "")

    @property
    def evidence_max_file_size_mb(self) -> int:
        """Max evidence file size in MB (default 10)."""
        return self.getint("evidence", "max_file_size_mb", 10)

    @property
    def evidence_allowed_mime_types(self) -> list[str]:
        """Allowed MIME types for evidence (default: jpeg, png, pdf)."""
        raw = self.get("evidence", "allowed_mime_types", "image/jpeg,image/png,application/pdf")
        return [x.strip() for x in raw.split(",") if x.strip()]

    @property
    def process_docs_storage_root(self) -> str:
        """Root directory for process step documentation (SOP) file storage."""
        return self.get("process_docs", "storage_root", "")

    @property
    def process_docs_max_file_size_mb(self) -> int:
        """Max process doc file size in MB (default 20)."""
        return self.getint("process_docs", "max_file_size_mb", 20)

    @property
    def process_docs_allowed_mime_types(self) -> list[str]:
        """Allowed MIME types for process docs (PDF, Word, markdown, plain text; no images)."""
        raw = self.get(
            "process_docs",
            "allowed_mime_types",
            "application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,text/plain",
        )
        return [x.strip() for x in raw.split(",") if x.strip()]

    @property
    def db_readonly_password(self) -> str:
        """Read-only database password (for reporting/read-only connections)"""
        # Try KeePassXC first (look for ReadonlyPassword or Notes field), fallback to config
        if self._keepass_creds:
            if "ReadonlyPassword" in self._keepass_creds:
                return self._keepass_creds["ReadonlyPassword"]
        return self.get("database", "readonly_password", self.db_password)


# Global config instance
config = Config()
