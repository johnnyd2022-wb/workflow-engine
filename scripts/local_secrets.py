import getpass
import os
import subprocess
import sys
from pathlib import Path

# Default values - can be overridden by environment variables
DEFAULT_ENTRY_NAME = "workflow-engine/workflow-engine-test-db"
DEFAULT_KDBX_PATH = "/mnt/c/Users/OEM/Documents/workflow-engine/Passwords.kdbx"


def get_keepass_entry(entry_name: str | None = None, kdbx_path: str | None = None, verbose: bool = False) -> dict:
    """
    Fetches a KeePassXC entry from KeePassXC database.

    Environment variables:
        KEEPASS_ENTRY_NAME: Entry path (defaults to DEFAULT_ENTRY_NAME)
        KEEPASS_KDBX_PATH: Database file path (defaults to DEFAULT_KDBX_PATH)
        KEEPASS_PASSWORD: Database password (if not set, will prompt interactively)

    Args:
        entry_name: KeePassXC entry path (defaults to KEEPASS_ENTRY_NAME env var or DEFAULT_ENTRY_NAME)
        kdbx_path: Path to KeePassXC database (defaults to KEEPASS_KDBX_PATH env var or DEFAULT_KDBX_PATH)
        verbose: If True, print detailed logging information

    Returns:
        Dictionary with entry fields (Username, Password, URL, Notes, etc.)
        Returns empty dict if entry not found or error occurs.
    """
    entry_name = entry_name or os.getenv("KEEPASS_ENTRY_NAME", DEFAULT_ENTRY_NAME)
    kdbx_path = kdbx_path or os.getenv("KEEPASS_KDBX_PATH", DEFAULT_KDBX_PATH)

    if verbose:
        print("🔍 Looking for KeePassXC entry:")
        print(f"   Entry name: {entry_name}")
        print(f"   Database path: {kdbx_path}")

    # Check if keepassxc-cli is available
    if verbose:
        print("🔍 Checking if keepassxc-cli is available...")
    try:
        version_result = subprocess.run(["keepassxc-cli", "--version"], capture_output=True, text=True, check=True)
        if verbose:
            print(f"✅ keepassxc-cli found: {version_result.stdout.strip()}")
    except FileNotFoundError:
        if verbose:
            print("❌ keepassxc-cli not found in PATH")
        return {}
    except subprocess.CalledProcessError as e:
        if verbose:
            print(f"❌ Error running keepassxc-cli --version: {e.stderr}")
        return {}

    # Check if database file exists
    kdbx_path_obj = Path(kdbx_path)
    if verbose:
        print(f"🔍 Checking if database file exists: {kdbx_path}")
        print(f"   Absolute path: {kdbx_path_obj.absolute()}")
        print(f"   Exists: {kdbx_path_obj.exists()}")
    if not kdbx_path_obj.exists():
        if verbose:
            print(f"❌ Database file not found at: {kdbx_path}")
        return {}

    # Try to fetch the entry
    # First, try without password (if database is unlocked in KeePassXC GUI)
    # Use -a Password to get the actual password (not PROTECTED placeholder)
    # Get all fields (Username, Password, URL, Notes, etc.)
    cmd = [
        "keepassxc-cli",
        "show",
        "-q",
        "-a",
        "Password",
        "-a",
        "Username",
        "-a",
        "URL",
        "-a",
        "Notes",
        kdbx_path,
        entry_name,
    ]
    if verbose:
        print(f"🔍 Running command: {' '.join(cmd)}")
        print("   (Trying without password - will prompt if database is locked)")

    try:
        # Try without password first (works if database is unlocked in GUI)
        # Use Popen with timeout to properly handle hanging processes
        process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            stdout, stderr = process.communicate(timeout=5)
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd, stdout, stderr)
            result = type("obj", (object,), {"stdout": stdout, "stderr": stderr})()
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise subprocess.TimeoutExpired(cmd, 5)
        output = result.stdout.strip()
        if verbose:
            print("✅ Command succeeded (database was unlocked)")
            print(f"   stdout: {output[:200] if len(output) > 200 else output}")

        # When using -a flags, keepassxc-cli returns values in order on separate lines
        # Order: Password, Username, URL, Notes
        secret_dict = {}
        lines = output.splitlines()
        attribute_order = ["Password", "Username", "URL", "Notes"]

        for i, line in enumerate(lines):
            if i < len(attribute_order):
                key = attribute_order[i]
                secret_dict[key] = line.strip()

        if verbose:
            print(f"✅ Parsed {len(secret_dict)} fields from entry")
        return secret_dict
    except subprocess.TimeoutExpired:
        # Command is waiting for password input - kill any hanging process
        if verbose:
            print("⏳ Command is waiting for password input...")
        return _try_with_password(cmd, kdbx_path, entry_name, verbose)
    except subprocess.CalledProcessError as e:
        # Check if it's a password-related error
        if "password" in e.stderr.lower() or "locked" in e.stderr.lower() or e.returncode == 1:
            if verbose:
                print("🔒 Database appears to be locked, trying with password...")
            return _try_with_password(cmd, kdbx_path, entry_name, verbose)
        if verbose:
            print(f"❌ Command failed with return code {e.returncode}")
            print(f"   stdout: {e.stdout}")
            print(f"   stderr: {e.stderr}")
        return {}
    except Exception as e:
        if verbose:
            print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        return {}


def _try_with_password(cmd: list, kdbx_path: str, entry_name: str, verbose: bool) -> dict:
    """Try to fetch entry with password input"""
    # Check for password in environment variable first
    password = os.getenv("KEEPASS_PASSWORD")

    if password:
        if verbose:
            print("🔐 Using password from KEEPASS_PASSWORD environment variable")
    else:
        # Prompt for password interactively if not in env var
        if verbose:
            print("🔐 Prompting for KeePassXC database password...")
            print("   (Tip: Set KEEPASS_PASSWORD env var in your bashrc to avoid prompts)")
        try:
            password = getpass.getpass("Enter KeePassXC database password: ")
        except (KeyboardInterrupt, EOFError):
            if verbose:
                print("❌ Password input cancelled")
            return {}

    if not password:
        if verbose:
            print("❌ No password provided")
        return {}

    # keepassxc-cli reads password from stdin when database is locked
    # We'll pass it via stdin (no --password flag needed)
    if verbose:
        print("🔐 Attempting to unlock database with password...")

    # Try with password via stdin using Popen for better control
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, stdout, stderr)
        result = type("obj", (object,), {"stdout": stdout, "stderr": stderr})()
        output = result.stdout.strip()
        if verbose:
            print("✅ Command succeeded with password")
            print(f"   stdout: {output[:200] if len(output) > 200 else output}")

        # When using -a flags, keepassxc-cli returns values in order on separate lines
        # Order: Password, Username, URL, Notes
        secret_dict = {}
        lines = output.splitlines()
        attribute_order = ["Password", "Username", "URL", "Notes"]

        for i, line in enumerate(lines):
            if i < len(attribute_order):
                key = attribute_order[i]
                secret_dict[key] = line.strip()

        if verbose:
            print(f"✅ Parsed {len(secret_dict)} fields from entry")
        return secret_dict
    except subprocess.CalledProcessError as e:
        if verbose:
            print(f"❌ Command failed with return code {e.returncode}")
            if e.stderr:
                print(f"   stderr: {e.stderr}")
            if "password" in e.stderr.lower() or "incorrect" in e.stderr.lower():
                print("   💡 Password may be incorrect")
        return {}
    except subprocess.TimeoutExpired:
        if verbose:
            print("❌ Command timed out (database may be locked or password incorrect)")
        return {}
    except Exception as e:
        if verbose:
            print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        return {}


if __name__ == "__main__":
    import sys

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    creds = get_keepass_entry(verbose=verbose)
    if creds:
        print("\n✅ Successfully fetched KeePassXC entry:")
        for key, value in creds.items():
            if key == "Password":
                print(f"  {key}: {'*' * len(value)}")
            else:
                print(f"  {key}: {value}")
    else:
        print("\n❌ Failed to fetch KeePassXC entry (database may be locked or entry not found)")
        print("💡 Run with --verbose or -v for detailed logging")
