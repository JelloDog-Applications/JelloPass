from time import sleep
import base64
import requests
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import getpass
import pyperclip
import configparser
import subprocess
from termcolor import colored
import re
import sys
from urllib.parse import urlparse

# Master password: key file format "JP1" + 16-byte salt + Fernet-encrypted data key
MASTER_KEY_MAGIC = b"JP1"
SALT_LEN = 16
KDF_ITERATIONS = 600_000  # OWASP-recommended for PBKDF2-SHA256
SYNC_TIMEOUT_SECONDS = 15
SYNC_TOKEN_MAGIC = "enc:"

filename_pattern = re.compile(r'^[\w-]+$')

appfolder = (os.getenv('APPDATA')) + "/JelloDog-Applications"

if not os.path.exists(appfolder):
    os.makedirs(appfolder)

# Create an encrypted folder for the passwords
encrypted_folder = appfolder + "/encrypted"
if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)

# Master password: derive a Fernet key from password + salt
def _derive_fernet_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    raw = kdf.derive(password)
    return base64.urlsafe_b64encode(raw)


def _load_or_create_key(password_prompt=None, choice_prompt=None):
    """Load or create the vault key. Use password_prompt(msg) and choice_prompt(msg) for GUI; defaults to getpass/input."""
    if password_prompt is None:
        password_prompt = getpass.getpass
    if choice_prompt is None:
        def _input_choice(msg):
            return input(msg).strip().lower()
        choice_prompt = _input_choice

    key_filename_local = appfolder + "/jellopass.key"
    if not os.path.exists(key_filename_local):
        # New install: generate key and optionally protect with master password
        key = Fernet.generate_key()
        choice = choice_prompt("Set a master password to protect your vault? (y/n): ")
        if choice == "y":
            while True:
                mp = password_prompt("Master password: ")
                mp2 = password_prompt("Confirm master password: ")
                if mp is None or mp2 is None:
                    break  # User cancelled; save without master password
                if mp != mp2:
                    print("Passwords don't match. Try again.")
                    continue
                if len(mp) < 6:
                    print("Master password must be at least 6 characters.")
                    continue
                break
            if mp is None or mp2 is None:
                choice = "n"  # Fall back to no master password
        if choice == "y":
            salt = os.urandom(SALT_LEN)
            derived = _derive_fernet_key(mp.encode("utf-8"), salt)
            wrapper = Fernet(derived)
            encrypted_key = wrapper.encrypt(key)
            with open(key_filename_local, "wb") as f:
                f.write(MASTER_KEY_MAGIC + salt + encrypted_key)
            print("Master password set. You'll need it each time you start JelloPass.")
        else:
            with open(key_filename_local, "wb") as f:
                f.write(key)
        try:
            os.chmod(key_filename_local, 0o600)
        except OSError:
            pass
        return key

    with open(key_filename_local, "rb") as f:
        data = f.read()
    try:
        os.chmod(key_filename_local, 0o600)
    except OSError:
        pass

    if len(data) >= len(MASTER_KEY_MAGIC) and data[: len(MASTER_KEY_MAGIC)] == MASTER_KEY_MAGIC:
        # Protected by master password
        salt = data[len(MASTER_KEY_MAGIC) : len(MASTER_KEY_MAGIC) + SALT_LEN]
        encrypted_key = data[len(MASTER_KEY_MAGIC) + SALT_LEN :]
        while True:
            mp = password_prompt("Master password: ")
            if mp is None:
                sys.exit(0)  # User cancelled (e.g. closed dialog)
            try:
                derived = _derive_fernet_key(mp.encode("utf-8"), salt)
                wrapper = Fernet(derived)
                key = wrapper.decrypt(encrypted_key)
                break
            except InvalidToken:
                print("Wrong master password. Try again.")
        return key
    else:
        # Legacy: raw Fernet key
        return data


key_filename = appfolder + "/jellopass.key"
key = None
cipher = None


def init_vault(password_prompt=None, choice_prompt=None):
    """Load key and set up cipher. Call with GUI prompts when running GUI."""
    global key, cipher
    key = _load_or_create_key(password_prompt=password_prompt, choice_prompt=choice_prompt)
    cipher = Fernet(key)
    _migrate_sync_token_to_encrypted()

# Define URLs for feature and bug reporting
Featurelink = 'https://tinyurl.com/y3hex46c'
Buglink = 'https://tinyurl.com/yy4o4rgc'

# Create or read the configuration file
config_file = appfolder + "/config.ini"
config = configparser.ConfigParser()
if not os.path.exists(config_file):
    config.add_section("General")
    config.set("General", "branch", "Stable")
    config.add_section("Sync")
    config.set("Sync", "server_url", "")
    config.set("Sync", "username", "")
    config.set("Sync", "token", "")
    config.set("Sync", "vault_version", "0")
    with open(config_file, "w") as f:
        config.write(f)

config.read(config_file)
if not config.has_section("General"):
    config.add_section("General")
if not config.has_option("General", "branch"):
    config.set("General", "branch", "Stable")
if not config.has_section("Sync"):
    config.add_section("Sync")
if not config.has_option("Sync", "server_url"):
    config.set("Sync", "server_url", "")
if not config.has_option("Sync", "username"):
    config.set("Sync", "username", "")
if not config.has_option("Sync", "token"):
    config.set("Sync", "token", "")
if not config.has_option("Sync", "vault_version"):
    config.set("Sync", "vault_version", "0")
branch = config.get("General", "branch")

# Define the version file and check for local version
version_file = "version.txt"
version_url = f"https://raw.githubusercontent.com/jelloDog-applications/jellopass/{branch}/{version_file}"
local_version = ""

# Use the absolute path to the version file
version_file_path = os.path.join(os.path.dirname(__file__), version_file)

# Check for local version
if os.path.exists(version_file_path):
    with open(version_file_path, "r") as f:
        local_version = f.read().strip()

# If local version is not found, fetch it from the remote repository
if not local_version:
    print("Local version file not found. Retrieving the latest version from the remote repository.")
    remote_version = requests.get(version_url).text.strip()
    if remote_version:
        local_version = remote_version
        with open(version_file, "w") as f:
            f.write(local_version)

# Define the passwords file path
passwords_file = os.path.join(encrypted_folder, "passwords.JelloPass")

update_shown = False

import urllib.request


def _save_config():
    with open(config_file, "w") as f:
        config.write(f)


def _sync_get_settings():
    token_stored = config.get("Sync", "token").strip()
    return {
        "server_url": config.get("Sync", "server_url").strip().rstrip("/"),
        "username": config.get("Sync", "username").strip(),
        "token": _decrypt_sync_token(token_stored),
        "vault_version": config.getint("Sync", "vault_version", fallback=0),
    }


def _sync_set_settings(server_url=None, username=None, token=None, vault_version=None):
    if server_url is not None:
        config.set("Sync", "server_url", server_url.strip().rstrip("/"))
    if username is not None:
        config.set("Sync", "username", username.strip())
    if token is not None:
        config.set("Sync", "token", _encrypt_sync_token(token.strip()))
    if vault_version is not None:
        config.set("Sync", "vault_version", str(int(vault_version)))
    _save_config()


def _sync_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _encrypt_sync_token(token):
    if not token:
        return ""
    if cipher is None:
        return token
    return SYNC_TOKEN_MAGIC + cipher.encrypt(token.encode("utf-8")).decode("utf-8")


def _decrypt_sync_token(token_value):
    if not token_value:
        return ""
    if not token_value.startswith(SYNC_TOKEN_MAGIC):
        return token_value
    if cipher is None:
        return ""
    encrypted = token_value[len(SYNC_TOKEN_MAGIC):]
    try:
        return cipher.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def _migrate_sync_token_to_encrypted():
    if cipher is None or not config.has_section("Sync"):
        return
    token_value = config.get("Sync", "token", fallback="").strip()
    if not token_value or token_value.startswith(SYNC_TOKEN_MAGIC):
        return
    config.set("Sync", "token", _encrypt_sync_token(token_value))
    _save_config()


def _validate_sync_server_url(raw_url):
    value = (raw_url or "").strip().rstrip("/")
    if not value:
        return None, "Server URL is required."
    try:
        parsed = urlparse(value)
    except Exception:
        return None, "Invalid server URL."
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, "Server URL must start with http:// or https://"
    host = (parsed.hostname or "").lower()
    is_local = host in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not is_local:
        return None, "Use https:// for non-local sync servers."
    return value, None


def _read_bytes_if_exists(path):
    if not os.path.exists(path):
        return b""
    with open(path, "rb") as f:
        return f.read()


def _write_bytes_secure(path, data):
    with open(path, "wb") as f:
        f.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _append_bytes_secure(path, data):
    # Create with restrictive permissions when possible, and append ciphertext bytes only.
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _is_master_password_enabled():
    if not os.path.exists(key_filename):
        return False
    with open(key_filename, "rb") as f:
        head = f.read(len(MASTER_KEY_MAGIC))
    return head == MASTER_KEY_MAGIC


def sync_register():
    settings = _sync_get_settings()
    server_url_raw = input("Sync server URL (example: http://127.0.0.1:8091): ")
    server_url, url_error = _validate_sync_server_url(server_url_raw)
    if url_error:
        print(url_error)
        return
    username = input("Sync username: ").strip()
    if not username:
        print("Username is required.")
        return
    password = getpass.getpass("Sync account password: ")
    confirm = getpass.getpass("Confirm sync account password: ")
    if password != confirm:
        print("Passwords do not match.")
        return
    if len(password) < 8:
        print("Sync account password must be at least 8 characters.")
        return
    try:
        response = requests.post(
            f"{server_url}/register",
            json={"username": username, "password": password},
            timeout=SYNC_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Sync register failed: {e}")
        return

    if response.status_code != 201:
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text
        print(f"Sync register failed: {msg}")
        return

    _sync_set_settings(server_url=server_url, username=username, token=settings["token"])
    print("Sync account created.")


def sync_login():
    settings = _sync_get_settings()
    server_url_raw = input(f"Sync server URL [{settings['server_url']}]: ").strip() or settings["server_url"]
    server_url, url_error = _validate_sync_server_url(server_url_raw)
    if url_error:
        print(url_error)
        return
    username = input(f"Sync username [{settings['username']}]: ").strip() or settings["username"]
    if not username:
        print("Username is required.")
        return
    password = getpass.getpass("Sync account password: ")
    try:
        response = requests.post(
            f"{server_url}/login",
            json={"username": username, "password": password},
            timeout=SYNC_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Sync login failed: {e}")
        return

    if response.status_code != 200:
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text
        print(f"Sync login failed: {msg}")
        return

    payload = response.json()
    token = payload.get("token", "").strip()
    vault_version = int(payload.get("vault_version", 0))
    if not token:
        print("Sync login failed: missing token.")
        return
    _sync_set_settings(server_url=server_url, username=username, token=token, vault_version=vault_version)
    print("Sync login successful.")


def sync_status():
    settings = _sync_get_settings()
    if not settings["server_url"] or not settings["username"]:
        print("Sync is not configured.")
        return
    print(f"Server: {settings['server_url']}")
    print(f"User: {settings['username']}")
    print(f"Token saved: {'yes' if settings['token'] else 'no'}")
    print(f"Local sync version: {settings['vault_version']}")


def sync_pull():
    settings = _sync_get_settings()
    if not settings["server_url"] or not settings["token"]:
        print("Run sync-login first.")
        return
    try:
        response = requests.get(
            f"{settings['server_url']}/vault",
            headers=_sync_headers(settings["token"]),
            timeout=SYNC_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Sync pull failed: {e}")
        return

    if response.status_code == 404:
        print("No remote vault found yet.")
        return
    if response.status_code != 200:
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text
        print(f"Sync pull failed: {msg}")
        return

    payload = response.json()
    vault_b64 = payload.get("vault_data_b64", "")
    key_b64 = payload.get("key_data_b64", "")
    remote_version = int(payload.get("vault_version", 0))
    if not key_b64:
        print("Sync pull failed: missing encrypted key payload.")
        return

    try:
        key_bytes = base64.b64decode(key_b64.encode("ascii"))
        vault_bytes = base64.b64decode(vault_b64.encode("ascii")) if vault_b64 else b""
    except Exception:
        print("Sync pull failed: invalid payload format.")
        return

    _write_bytes_secure(key_filename, key_bytes)
    _write_bytes_secure(passwords_file, vault_bytes)
    _sync_set_settings(vault_version=remote_version)

    try:
        init_vault()
    except Exception:
        print("Pulled vault data, but failed to unlock with current master password.")
        return
    print(f"Sync pull successful. Local vault updated to version {remote_version}.")


def sync_push():
    settings = _sync_get_settings()
    if not settings["server_url"] or not settings["token"]:
        print("Run sync-login first.")
        return
    if not _is_master_password_enabled():
        print("Enable master password first (lock). Sync only accepts encrypted key files.")
        return

    key_bytes = _read_bytes_if_exists(key_filename)
    vault_bytes = _read_bytes_if_exists(passwords_file)
    if not key_bytes:
        print("No key file found.")
        return

    payload = {
        "base_version": settings["vault_version"],
        "key_data_b64": base64.b64encode(key_bytes).decode("ascii"),
        "vault_data_b64": base64.b64encode(vault_bytes).decode("ascii"),
    }
    try:
        response = requests.put(
            f"{settings['server_url']}/vault",
            headers=_sync_headers(settings["token"]),
            json=payload,
            timeout=SYNC_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        print(f"Sync push failed: {e}")
        return

    if response.status_code == 409:
        try:
            server_version = int(response.json().get("vault_version", 0))
        except Exception:
            server_version = 0
        print(f"Sync conflict. Remote version is {server_version}. Run sync-pull, then sync-push again.")
        return
    if response.status_code != 200:
        try:
            msg = response.json().get("error", response.text)
        except Exception:
            msg = response.text
        print(f"Sync push failed: {msg}")
        return

    new_version = int(response.json().get("vault_version", settings["vault_version"]))
    _sync_set_settings(vault_version=new_version)
    print(f"Sync push successful. Remote vault is now version {new_version}.")

# Function to check for updates
def check_updates():
    global update_shown, local_version

    if not local_version:
        return

    remote_version = requests.get(version_url).text.strip()

    if remote_version != local_version and not update_shown:
        update = input(f"A new version ({remote_version}) is available. Do you want to update? (y/n): ")
        if update == 'y':
            update_path = "https://github.com/JelloDog-Applications/JelloPass/releases/latest/download/JelloPass.exe"
            urllib.request.urlretrieve(update_path, "JelloPass-Installer.exe")

            version_text = requests.get(version_url).text.strip()
            with open(version_file, "w") as f:
                f.write(version_text)

            print("Download complete. Please run the installer to update JelloPass.")
            sleep(2)
            sys.exit()
        else:
            update_shown = True

# Function to save a password (name and password both encrypted on disk)
def save_password(name, password):
    enc_name = cipher.encrypt(name.encode("utf-8"))
    enc_password = cipher.encrypt(password.encode("utf-8"))
    entry = enc_name + b":" + enc_password + b"\n"
    _append_bytes_secure(passwords_file, entry)  # lgtm [py/clear-text-storage-sensitive-data]

# Function to retrieve a password (supports old plaintext-name and new encrypted-name lines)
def get_password(name):
    if not os.path.exists(passwords_file):
        return None
    with open(passwords_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            try:
                dec_name = cipher.decrypt(parts[0].encode()).decode()
                dec_password = cipher.decrypt(parts[1].encode()).decode()
                if dec_name == name:
                    return dec_password
            except InvalidToken:
                # Old format: plaintext name, encrypted password
                if parts[0] == name:
                    return cipher.decrypt(parts[1].encode()).decode()
    return None


def get_entry_by_index(index):
    """Return (name, password) for the entry at the given line index (0-based), or None if out of range."""
    if not os.path.exists(passwords_file):
        return None
    with open(passwords_file, "r") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if index < 0 or index >= len(lines):
        return None
    line = lines[index]
    parts = line.split(":", 1)
    if len(parts) != 2:
        return None
    try:
        dec_name = cipher.decrypt(parts[0].encode()).decode()
        dec_password = cipher.decrypt(parts[1].encode()).decode()
        return (dec_name, dec_password)
    except InvalidToken:
        dec_password = cipher.decrypt(parts[1].encode()).decode()
        return (parts[0], dec_password)


def get_entries_list():
    """Return list of {name, index} for all entries (for Chrome extension / local server)."""
    entries = []
    if not os.path.exists(passwords_file):
        return entries
    with open(passwords_file, "r") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            try:
                name = cipher.decrypt(parts[0].encode()).decode()
            except InvalidToken:
                name = parts[0]
            entries.append({"name": name, "index": idx})
    return entries


# Function to list all saved passwords (decrypts names for display)
def list_passwords():
    if not os.path.exists(passwords_file):
        print("No passwords found.")
        return
    with open(passwords_file, "r") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines:
        print("No passwords found.")
        return
    print("Available passwords:")
    for line in lines:
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        try:
            name = cipher.decrypt(parts[0].encode()).decode()
        except InvalidToken:
            name = parts[0]  # Old format: plaintext name
        print("- " + name)

# Function to change the branch
def change_branch():
    global branch, local_version

    branch = input("Enter the branch name (Stable, Beta, Development): ").capitalize()

    if branch not in ["Stable", "Beta", "Development"]:
        print("Invalid branch name. Please choose from 'Stable', 'Beta', or 'Development'.")
        return

    version_url = f"https://raw.githubusercontent.com/jelloDog-applications/jellopass/{branch}/{version_file}"

    if os.path.exists(version_file):
        with open(version_file, "r") as f:
            local_version = f.read().strip()

    if not local_version:
        print("Local version file not found. Retrieving the latest version from the remote repository.")
        remote_version = requests.get(version_url).text.strip()
        if remote_version:
            local_version = remote_version
            with open(version_file, "w") as f:
                f.write(local_version)

    config.set("General", "branch", branch)
    with open(config_file, "w") as f:
        config.write(f)

    warning_message = colored("WARNING: Switching branches may result in loss of passwords.", "red")
    print(warning_message)
    confirmation = input("Are you sure you want to proceed? (y/n): ")
    if confirmation.lower() == "y":
        print(f"Switched to the '{branch}' branch.")
    else:
        print("Branch switch canceled.")


def set_master_password():
    """Protect the key file with a master password (for users currently using raw key)."""
    global key, cipher
    if not os.path.exists(key_filename):
        return
    with open(key_filename, "rb") as f:
        head = f.read(len(MASTER_KEY_MAGIC))
    if head == MASTER_KEY_MAGIC:
        print("Already using a master password.")
        return
    # Key in memory is the raw Fernet key
    while True:
        mp = getpass.getpass("New master password: ")
        mp2 = getpass.getpass("Confirm master password: ")
        if mp != mp2:
            print("Passwords don't match. Try again.")
            continue
        if len(mp) < 6:
            print("Master password must be at least 6 characters.")
            continue
        break
    salt = os.urandom(SALT_LEN)
    derived = _derive_fernet_key(mp.encode("utf-8"), salt)
    wrapper = Fernet(derived)
    encrypted_key = wrapper.encrypt(key)
    with open(key_filename, "wb") as f:
        f.write(MASTER_KEY_MAGIC + salt + encrypted_key)
    try:
        os.chmod(key_filename, 0o600)
    except OSError:
        pass
    print("Master password set. You'll need it next time you start JelloPass.")


def remove_master_password():
    """Remove master password and store key in plaintext again (less secure)."""
    global key, cipher
    if not os.path.exists(key_filename):
        return
    with open(key_filename, "rb") as f:
        data = f.read()
    if len(data) < len(MASTER_KEY_MAGIC) or data[: len(MASTER_KEY_MAGIC)] != MASTER_KEY_MAGIC:
        print("Not using a master password.")
        return
    salt = data[len(MASTER_KEY_MAGIC) : len(MASTER_KEY_MAGIC) + SALT_LEN]
    encrypted_key = data[len(MASTER_KEY_MAGIC) + SALT_LEN :]
    mp = getpass.getpass("Current master password: ")
    try:
        derived = _derive_fernet_key(mp.encode("utf-8"), salt)
        wrapper = Fernet(derived)
        key = wrapper.decrypt(encrypted_key)
    except InvalidToken:
        print("Wrong master password.")
        return
    with open(key_filename, "wb") as f:
        f.write(key)
    try:
        os.chmod(key_filename, 0o600)
    except OSError:
        pass
    cipher = Fernet(key)
    print("Master password removed. Key is now stored on disk (less secure).")


def run_cli():
    """Command-line interface main loop."""
    while True:
        check_updates()
        session = input(
            "Do you want to add a password (add), open a password (open), change branch (branch), "
            "set master password (lock), remove master password (unlock), "
            "sync-register, sync-login, sync-status, sync-push, sync-pull, help, or exit? "
        )

        if session == "help":
            help_com = input("Type 'About', 'Bug', or 'Feature': ")

            if help_com == "Feature":
                print("Click this link to suggest a new feature: " + Featurelink)

            if help_com == "Bug":
                print("Please go to this link to report a bug: " + Buglink)

            if help_com == "About":
                print("JelloPass Was Made By JelloDog-Applications " + local_version)

        elif session == "exit":
            print("Thank you for using JelloPass")
            sleep(0.5)
            break

        elif session == "open":
            list_passwords()
            pass_open = input("Enter the name of the password you want to open: ")

            # Validate the password file name
            if not pass_open.isalnum():
                print("Error: Password file name can only contain alphanumeric characters.")
            else:
                password = get_password(pass_open)
                if password:
                    print("Password copied. Clipboard will clear in 10 seconds.")
                    pyperclip.copy(password)
                    sleep(10)
                    pyperclip.copy("")  # Clear clipboard for security
                    print("Clipboard cleared.")
                else:
                    print(f"Password '{pass_open}' not found.")

        elif session == "add":
            new_name = input("What is the name of your password? ")
            if not new_name.isalnum():
                print("Error: Password file name can only contain alphanumeric characters.")
            else:
                password = getpass.getpass("Please enter the password: ")
                save_password(new_name, password)
                print("Password saved successfully.")

        elif session == "branch":
            change_branch()

        elif session == "lock":
            set_master_password()

        elif session == "unlock":
            remove_master_password()

        elif session == "sync-register":
            sync_register()

        elif session == "sync-login":
            sync_login()

        elif session == "sync-status":
            sync_status()

        elif session == "sync-push":
            sync_push()

        elif session == "sync-pull":
            sync_pull()

        else:
            print("Invalid command. Please try again.")


# --- Local server for Chrome extension (run when GUI is open) ---
JELLOPASS_SERVER_PORT = 47984


def _run_jellopass_server():
    """Run a minimal HTTP server on 127.0.0.1 so the Chrome extension can list/get passwords."""
    import json
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class JelloPassHandler(BaseHTTPRequestHandler):
        def _sanitize_header_value(self, value):
            """
            Remove characters that could be used for HTTP response splitting from a header value.
            """
            if not isinstance(value, str):
                value = str(value)
            # Strip CR and LF to prevent header injection / response splitting.
            return value.replace("\r", "").replace("\n", "")

        def _origin_allowed(self):
            origin = self.headers.get("Origin", "")
            if not origin:
                return False
            return origin.startswith("chrome-extension://")

        def log_message(self, format, *args):
            pass  # quiet

        def _send_json(self, obj, status=200):
            if not self._origin_allowed():
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "forbidden"}).encode("utf-8"))
                return
            origin = self.headers.get("Origin", "")
            safe_origin = self._sanitize_header_value(origin)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", safe_origin)
            self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode("utf-8"))

        def do_GET(self):
            try:
                if self.path == "/list" or self.path == "/list/":
                    entries = get_entries_list()
                    self._send_json({"entries": entries})
                    return
                if self.path.startswith("/get?"):
                    from urllib.parse import parse_qs, urlparse
                    qs = parse_qs(urlparse(self.path).query)
                    idx_list = qs.get("index", [])
                    if not idx_list:
                        self._send_json({"error": "missing index"}, 400)
                        return
                    try:
                        index = int(idx_list[0])
                    except ValueError:
                        self._send_json({"error": "invalid index"}, 400)
                        return
                    entry = get_entry_by_index(index)
                    if not entry:
                        self._send_json({"error": "not found"}, 404)
                        return
                    name, password = entry
                    self._send_json({"name": name, "password": password})
                    return
                self.send_response(404)
                self.end_headers()
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        def do_OPTIONS(self):
            if not self._origin_allowed():
                self.send_response(403)
                self.end_headers()
                return
            origin = self.headers.get("Origin", "")
            safe_origin = self._sanitize_header_value(origin)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", safe_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    try:
        server = HTTPServer(("127.0.0.1", JELLOPASS_SERVER_PORT), JelloPassHandler)
        server.serve_forever()
    except OSError:
        pass  # port in use or permission


# --- GUI (CustomTkinter: dark mode + rounded buttons) ---
import tkinter as tk
from tkinter import messagebox, simpledialog
import customtkinter as ctk
import webbrowser
import threading

# Dark theme and rounded style
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _gui_password_prompt(root, msg):
    """Show a modal dialog to enter a password; returns the string or None if cancelled."""
    result = [None]

    def on_ok():
        result[0] = entry.get().strip()
        dlg.destroy()

    def on_cancel():
        dlg.destroy()

    dlg = ctk.CTkToplevel(root)
    dlg.title("JelloPass")
    dlg.resizable(False, False)
    dlg.transient(root)
    dlg.grab_set()
    ctk.CTkLabel(dlg, text=msg, font=ctk.CTkFont(size=13)).pack(padx=20, pady=(20, 8))
    entry = ctk.CTkEntry(dlg, show="•", width=280, height=36, corner_radius=8, font=ctk.CTkFont(size=13))
    entry.pack(padx=20, pady=8)
    entry.focus_set()
    entry.bind("<Return>", lambda e: on_ok())
    btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
    btn_frame.pack(pady=(8, 20))
    ctk.CTkButton(btn_frame, text="OK", command=on_ok, width=90, height=32, corner_radius=8).pack(side=tk.LEFT, padx=6)
    ctk.CTkButton(btn_frame, text="Cancel", command=on_cancel, width=90, height=32, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(side=tk.LEFT, padx=6)
    dlg.geometry("+%d+%d" % (root.winfo_rootx() + 50, root.winfo_rooty() + 50))
    dlg.wait_window()
    return result[0]


def _gui_choice_prompt(root, msg):
    """Return 'y' or 'n' from a yes/no dialog."""
    result = [None]

    def on_yes():
        result[0] = "y"
        dlg.destroy()

    def on_no():
        result[0] = "n"
        dlg.destroy()

    dlg = ctk.CTkToplevel(root)
    dlg.title("JelloPass")
    dlg.resizable(False, False)
    dlg.transient(root)
    dlg.grab_set()
    ctk.CTkLabel(dlg, text=msg, font=ctk.CTkFont(size=13), wraplength=280).pack(padx=20, pady=(20, 16))
    btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
    btn_frame.pack(pady=(0, 20))
    ctk.CTkButton(btn_frame, text="Yes", command=on_yes, width=90, height=32, corner_radius=8).pack(side=tk.LEFT, padx=6)
    ctk.CTkButton(btn_frame, text="No", command=on_no, width=90, height=32, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(side=tk.LEFT, padx=6)
    dlg.geometry("+%d+%d" % (root.winfo_rootx() + 50, root.winfo_rooty() + 50))
    dlg.wait_window()
    return result[0] or "n"


def run_gui():
    """Launch the graphical interface (dark mode, rounded buttons)."""
    root = ctk.CTk()
    root.title("JelloPass")
    root.minsize(360, 400)
    root.geometry("440x480")

    def password_prompt(msg):
        return _gui_password_prompt(root, msg)

    def choice_prompt(msg):
        return _gui_choice_prompt(root, msg)

    try:
        init_vault(password_prompt=password_prompt, choice_prompt=choice_prompt)
    except (TypeError, InvalidToken):
        root.destroy()
        return

    # Start local server for Chrome extension (vault is unlocked)
    server_thread = threading.Thread(target=_run_jellopass_server, daemon=True)
    server_thread.start()

    # Main content
    main = ctk.CTkFrame(root, fg_color="transparent")
    main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

    ctk.CTkLabel(main, text="JelloPass", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 4))
    ctk.CTkLabel(main, text="Your passwords", font=ctk.CTkFont(size=13), text_color=("#6b6b6b", "#9ca3af")).pack(pady=(0, 12))

    def refresh_list():
        """Return list of (name, index) for each entry so duplicate names are tracked by row index."""
        entries = []
        if os.path.exists(passwords_file):
            with open(passwords_file, "r") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(":", 1)
                    if len(parts) != 2:
                        continue
                    try:
                        name = cipher.decrypt(parts[0].encode()).decode()
                    except InvalidToken:
                        name = parts[0]
                    entries.append((name, idx))
        return entries

    list_container = ctk.CTkFrame(main, corner_radius=12, fg_color=("#e0e0e0", "#2b2b2b"))
    list_container.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
    list_inner = ctk.CTkScrollableFrame(list_container, fg_color="transparent", corner_radius=8)
    list_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    selected_index = [None]  # row index so duplicate names get the correct password
    name_buttons = []

    def update_listbox():
        for w in name_buttons:
            w.destroy()
        name_buttons.clear()
        selected_index[0] = None
        for name, idx in refresh_list():
            btn = ctk.CTkButton(
                list_inner, text=name, height=40, corner_radius=8,
                fg_color="transparent", anchor="w",
                font=ctk.CTkFont(size=13),
                command=lambda i=idx: select_index(i)
            )
            btn.bind("<Double-Button-1>", lambda e, i=idx: show_entry_for_index(i))
            btn.pack(fill=tk.X, pady=2)
            name_buttons.append(btn)

    def select_index(idx):
        selected_index[0] = idx
        for i, btn in enumerate(name_buttons):
            btn.configure(fg_color=("#c9c9c9", "#3d3d3d") if i == idx else "transparent")

    def show_entry_for_index(idx):
        entry = get_entry_by_index(idx)
        if not entry:
            messagebox.showerror("JelloPass", "Password not found.", parent=root)
            return
        name, pwd = entry
        dlg = ctk.CTkToplevel(root)
        dlg.title("Password: " + name)
        dlg.resizable(False, False)
        dlg.transient(root)
        dlg.grab_set()
        ctk.CTkLabel(dlg, text=name, font=ctk.CTkFont(size=12, weight="bold")).pack(padx=20, pady=(20, 4))
        pwd_entry = ctk.CTkEntry(dlg, width=300, height=40, corner_radius=8, font=ctk.CTkFont(size=13))
        pwd_entry.insert(0, pwd)
        pwd_entry.pack(padx=20, pady=12)
        try:
            pwd_entry.configure(state="readonly")
        except tk.TclError:
            pwd_entry.configure(state="disabled")
        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=(4, 20))
        ctk.CTkButton(btn_frame, text="Copy", command=lambda: (pyperclip.copy(pwd), messagebox.showinfo("JelloPass", "Copied.", parent=dlg)), width=90, height=32, corner_radius=8).pack(side=tk.LEFT, padx=6)
        ctk.CTkButton(btn_frame, text="Close", command=dlg.destroy, width=90, height=32, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(side=tk.LEFT, padx=6)
        dlg.geometry("+%d+%d" % (root.winfo_rootx() + 30, root.winfo_rooty() + 80))

    update_listbox()

    def on_copy():
        if selected_index[0] is None:
            messagebox.showinfo("JelloPass", "Select a password first.", parent=root)
            return
        entry = get_entry_by_index(selected_index[0])
        if not entry:
            messagebox.showerror("JelloPass", "Password not found.", parent=root)
            return
        name, pwd = entry
        pyperclip.copy(pwd)
        messagebox.showinfo("JelloPass", "Password copied. Clipboard will clear in 10 seconds.", parent=root)
        def clear_later():
            sleep(10)
            pyperclip.copy("")
            try:
                root.event_generate("<<ClipboardCleared>>")
            except tk.TclError:
                pass
        threading.Thread(target=clear_later, daemon=True).start()

    def on_show():
        if selected_index[0] is None:
            messagebox.showinfo("JelloPass", "Select a password first.", parent=root)
            return
        show_entry_for_index(selected_index[0])

    def on_add():
        dlg = ctk.CTkToplevel(root)
        dlg.title("Add password")
        dlg.resizable(False, False)
        dlg.transient(root)
        dlg.grab_set()
        result = [None]

        def submit():
            name = name_entry.get().strip()
            if not name:
                return
            if not name.isalnum():
                messagebox.showerror("JelloPass", "Name can only contain letters and numbers.", parent=dlg)
                return
            pwd = _gui_password_prompt(root, "Enter the password to save:")
            if pwd is None:
                return
            save_password(name, pwd)
            update_listbox()
            result[0] = True
            messagebox.showinfo("JelloPass", "Password saved.", parent=root)
            dlg.destroy()

        ctk.CTkLabel(dlg, text="Name (letters/numbers only):", font=ctk.CTkFont(size=13)).pack(padx=20, pady=(20, 8))
        name_entry = ctk.CTkEntry(dlg, width=280, height=36, corner_radius=8, font=ctk.CTkFont(size=13))
        name_entry.pack(padx=20, pady=8)
        name_entry.focus_set()
        name_entry.bind("<Return>", lambda e: submit())
        ctk.CTkButton(dlg, text="Add", command=submit, width=120, height=36, corner_radius=8).pack(pady=(8, 20))
        dlg.geometry("+%d+%d" % (root.winfo_rootx() + 40, root.winfo_rooty() + 60))
        dlg.wait_window()

    def on_refresh():
        update_listbox()

    def _ask_text(prompt, initial_value=""):
        return simpledialog.askstring("JelloPass Sync", prompt, initialvalue=initial_value, parent=root)

    def on_sync_register():
        settings = _sync_get_settings()
        server_url_raw = _ask_text("Sync server URL:", settings["server_url"] or "http://127.0.0.1:8091")
        if server_url_raw is None:
            return
        server_url, url_error = _validate_sync_server_url(server_url_raw)
        if url_error:
            messagebox.showerror("JelloPass", url_error, parent=root)
            return
        username = _ask_text("Sync username:", settings["username"])
        if username is None:
            return
        username = username.strip()
        if not username:
            messagebox.showerror("JelloPass", "Username is required.", parent=root)
            return
        password = _gui_password_prompt(root, "Sync account password:")
        if password is None:
            return
        confirm = _gui_password_prompt(root, "Confirm sync account password:")
        if confirm is None:
            return
        if password != confirm:
            messagebox.showerror("JelloPass", "Passwords do not match.", parent=root)
            return
        if len(password) < 8:
            messagebox.showerror("JelloPass", "Sync account password must be at least 8 characters.", parent=root)
            return
        try:
            response = requests.post(
                f"{server_url}/register",
                json={"username": username, "password": password},
                timeout=SYNC_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            messagebox.showerror("JelloPass", f"Sync register failed: {e}", parent=root)
            return
        if response.status_code != 201:
            try:
                msg = response.json().get("error", response.text)
            except Exception:
                msg = response.text
            messagebox.showerror("JelloPass", f"Sync register failed: {msg}", parent=root)
            return
        _sync_set_settings(server_url=server_url, username=username)
        messagebox.showinfo("JelloPass", "Sync account created.", parent=root)

    def on_sync_login():
        settings = _sync_get_settings()
        server_url_raw = _ask_text("Sync server URL:", settings["server_url"] or "http://127.0.0.1:8091")
        if server_url_raw is None:
            return
        server_url, url_error = _validate_sync_server_url(server_url_raw)
        if url_error:
            messagebox.showerror("JelloPass", url_error, parent=root)
            return
        username = _ask_text("Sync username:", settings["username"])
        if username is None:
            return
        username = username.strip()
        if not username:
            messagebox.showerror("JelloPass", "Username is required.", parent=root)
            return
        password = _gui_password_prompt(root, "Sync account password:")
        if password is None:
            return
        try:
            response = requests.post(
                f"{server_url}/login",
                json={"username": username, "password": password},
                timeout=SYNC_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            messagebox.showerror("JelloPass", f"Sync login failed: {e}", parent=root)
            return
        if response.status_code != 200:
            try:
                msg = response.json().get("error", response.text)
            except Exception:
                msg = response.text
            messagebox.showerror("JelloPass", f"Sync login failed: {msg}", parent=root)
            return
        payload = response.json()
        token = payload.get("token", "").strip()
        vault_version = int(payload.get("vault_version", 0))
        if not token:
            messagebox.showerror("JelloPass", "Sync login failed: missing token.", parent=root)
            return
        _sync_set_settings(server_url=server_url, username=username, token=token, vault_version=vault_version)
        messagebox.showinfo("JelloPass", f"Sync login successful.\nVersion: {vault_version}", parent=root)

    def on_sync_status():
        settings = _sync_get_settings()
        if not settings["server_url"] or not settings["username"]:
            messagebox.showinfo("JelloPass", "Sync is not configured.", parent=root)
            return
        messagebox.showinfo(
            "JelloPass",
            f"Server: {settings['server_url']}\n"
            f"User: {settings['username']}\n"
            f"Token saved: {'yes' if settings['token'] else 'no'}\n"
            f"Local sync version: {settings['vault_version']}",
            parent=root,
        )

    def on_sync_push():
        settings = _sync_get_settings()
        if not settings["server_url"] or not settings["token"]:
            messagebox.showerror("JelloPass", "Run Sync Login first.", parent=root)
            return
        if not _is_master_password_enabled():
            messagebox.showerror("JelloPass", "Enable master password first (lock).", parent=root)
            return
        key_bytes = _read_bytes_if_exists(key_filename)
        vault_bytes = _read_bytes_if_exists(passwords_file)
        if not key_bytes:
            messagebox.showerror("JelloPass", "No key file found.", parent=root)
            return
        payload = {
            "base_version": settings["vault_version"],
            "key_data_b64": base64.b64encode(key_bytes).decode("ascii"),
            "vault_data_b64": base64.b64encode(vault_bytes).decode("ascii"),
        }
        try:
            response = requests.put(
                f"{settings['server_url']}/vault",
                headers=_sync_headers(settings["token"]),
                json=payload,
                timeout=SYNC_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            messagebox.showerror("JelloPass", f"Sync push failed: {e}", parent=root)
            return
        if response.status_code == 409:
            try:
                server_version = int(response.json().get("vault_version", 0))
            except Exception:
                server_version = 0
            messagebox.showwarning(
                "JelloPass",
                f"Sync conflict. Remote version is {server_version}.\nRun Sync Pull, then Sync Push again.",
                parent=root,
            )
            return
        if response.status_code != 200:
            try:
                msg = response.json().get("error", response.text)
            except Exception:
                msg = response.text
            messagebox.showerror("JelloPass", f"Sync push failed: {msg}", parent=root)
            return
        new_version = int(response.json().get("vault_version", settings["vault_version"]))
        _sync_set_settings(vault_version=new_version)
        messagebox.showinfo("JelloPass", f"Sync push successful.\nVersion: {new_version}", parent=root)

    def on_sync_pull():
        settings = _sync_get_settings()
        if not settings["server_url"] or not settings["token"]:
            messagebox.showerror("JelloPass", "Run Sync Login first.", parent=root)
            return
        try:
            response = requests.get(
                f"{settings['server_url']}/vault",
                headers=_sync_headers(settings["token"]),
                timeout=SYNC_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            messagebox.showerror("JelloPass", f"Sync pull failed: {e}", parent=root)
            return
        if response.status_code == 404:
            messagebox.showinfo("JelloPass", "No remote vault found yet.", parent=root)
            return
        if response.status_code != 200:
            try:
                msg = response.json().get("error", response.text)
            except Exception:
                msg = response.text
            messagebox.showerror("JelloPass", f"Sync pull failed: {msg}", parent=root)
            return
        payload = response.json()
        vault_b64 = payload.get("vault_data_b64", "")
        key_b64 = payload.get("key_data_b64", "")
        remote_version = int(payload.get("vault_version", 0))
        if not key_b64:
            messagebox.showerror("JelloPass", "Sync pull failed: missing encrypted key payload.", parent=root)
            return
        try:
            key_bytes = base64.b64decode(key_b64.encode("ascii"))
            vault_bytes = base64.b64decode(vault_b64.encode("ascii")) if vault_b64 else b""
        except Exception:
            messagebox.showerror("JelloPass", "Sync pull failed: invalid payload format.", parent=root)
            return
        _write_bytes_secure(key_filename, key_bytes)
        _write_bytes_secure(passwords_file, vault_bytes)
        _sync_set_settings(vault_version=remote_version)
        try:
            init_vault(password_prompt=password_prompt, choice_prompt=choice_prompt)
        except Exception:
            messagebox.showerror(
                "JelloPass",
                "Pulled vault data, but failed to unlock with the provided master password.",
                parent=root,
            )
            return
        update_listbox()
        messagebox.showinfo("JelloPass", f"Sync pull successful.\nVersion: {remote_version}", parent=root)

    def on_open_sync_window():
        sync_win = ctk.CTkToplevel(root)
        sync_win.title("Sync")
        sync_win.geometry("360x300")
        sync_win.resizable(False, False)
        sync_win.transient(root)

        ctk.CTkLabel(sync_win, text="Sync", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(18, 6))
        ctk.CTkLabel(
            sync_win,
            text="Account and vault sync actions",
            font=ctk.CTkFont(size=12),
            text_color=("#6b6b6b", "#9ca3af"),
        ).pack(pady=(0, 14))

        grid = ctk.CTkFrame(sync_win, fg_color="transparent")
        grid.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        ctk.CTkButton(grid, text="Register", command=on_sync_register, height=36, corner_radius=8).pack(fill=tk.X, pady=4)
        ctk.CTkButton(grid, text="Login", command=on_sync_login, height=36, corner_radius=8).pack(fill=tk.X, pady=4)
        ctk.CTkButton(grid, text="Status", command=on_sync_status, height=36, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(fill=tk.X, pady=4)
        ctk.CTkButton(grid, text="Pull", command=on_sync_pull, height=36, corner_radius=8).pack(fill=tk.X, pady=4)
        ctk.CTkButton(grid, text="Push", command=on_sync_push, height=36, corner_radius=8).pack(fill=tk.X, pady=4)
        ctk.CTkButton(grid, text="Close", command=sync_win.destroy, height=34, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(fill=tk.X, pady=(10, 4))

        sync_win.geometry("+%d+%d" % (root.winfo_rootx() + 60, root.winfo_rooty() + 40))

    def on_open_cli():
        try:
            creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--cli"],
                creationflags=creation_flags,
            )
            messagebox.showinfo("JelloPass", "CLI opened in a new window.", parent=root)
        except Exception as e:
            messagebox.showerror("JelloPass", f"Failed to open CLI: {e}", parent=root)

    btn_row = ctk.CTkFrame(main, fg_color="transparent")
    btn_row.pack(fill=tk.X, pady=8)
    ctk.CTkButton(btn_row, text="Copy password", command=on_copy, width=120, height=36, corner_radius=8).pack(side=tk.LEFT, padx=(0, 8))
    ctk.CTkButton(btn_row, text="Show password", command=on_show, width=120, height=36, corner_radius=8).pack(side=tk.LEFT, padx=8)
    ctk.CTkButton(btn_row, text="Add password", command=on_add, width=120, height=36, corner_radius=8).pack(side=tk.LEFT, padx=8)
    ctk.CTkButton(btn_row, text="Refresh", command=on_refresh, width=90, height=36, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(side=tk.LEFT, padx=8)

    def on_help():
        help_win = ctk.CTkToplevel(root)
        help_win.title("Help")
        help_win.geometry("340x240")
        help_win.transient(root)
        ctk.CTkLabel(help_win, text="JelloPass by JelloDog-Applications", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 4))
        ctk.CTkLabel(help_win, text=local_version, font=ctk.CTkFont(size=12), text_color=("#6b6b6b", "#9ca3af")).pack(pady=(0, 16))
        ctk.CTkButton(help_win, text="Suggest a feature", command=lambda: webbrowser.open(Featurelink), width=200, height=32, corner_radius=8).pack(pady=6)
        ctk.CTkButton(help_win, text="Report a bug", command=lambda: webbrowser.open(Buglink), width=200, height=32, corner_radius=8).pack(pady=6)
        ctk.CTkButton(help_win, text="Close", command=help_win.destroy, width=120, height=32, corner_radius=8, fg_color=("#8a8a8a", "#4a4a4a")).pack(pady=16)

    footer = ctk.CTkFrame(main, fg_color="transparent")
    footer.pack(fill=tk.X, pady=4)
    ctk.CTkButton(footer, text="Sync", command=on_open_sync_window, width=90, height=32, corner_radius=8).pack(side=tk.LEFT, padx=(0, 8))
    ctk.CTkButton(footer, text="Open CLI", command=on_open_cli, width=100, height=32, corner_radius=8).pack(side=tk.LEFT, padx=8)
    ctk.CTkButton(footer, text="Help", command=on_help, width=90, height=32, corner_radius=8, fg_color="transparent").pack(side=tk.LEFT, padx=8)
    root.bind("<<ClipboardCleared>>", lambda e: None)
    root.mainloop()


if __name__ == "__main__":
    if "--cli" in sys.argv or "-c" in sys.argv:
        init_vault()
        run_cli()
    else:
        run_gui()
