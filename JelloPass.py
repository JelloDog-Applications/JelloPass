from time import sleep
import requests
from cryptography.fernet import Fernet
import os
import pyperclip
import win32clipboard
import configparser

# Create an encrypted folder for the passwords
encrypted_folder = "encrypted"
if not os.path.exists(encrypted_folder):
    os.mkdir(encrypted_folder)

# Generate a new key or load an existing one
key_filename = "jellopass.key"
try:
    with open(key_filename, "rb") as key_file:
        key = key_file.read()
except FileNotFoundError:
    key = Fernet.generate_key()
    with open(key_filename, "wb") as key_file:
        key_file.write(key)

cipher = Fernet(key)

Featurelink = 'https://tinyurl.com/y3hex46c'
Buglink = 'https://tinyurl.com/yy4o4rgc'

config = configparser.ConfigParser()
config.read("config.ini")
branch = config.get("General", "branch")

version_file = "version.txt"
version_url = f"https://raw.githubusercontent.com/jelloDog-applications/jellopass/{branch}/{version_file}"
local_version = ""

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

passwords_file = os.path.join(encrypted_folder, "passwords.txt")

update_shown = False


def check_updates():
    global update_shown

    if not local_version:
        return

    remote_version = requests.get(version_url).text.strip()

    if remote_version != local_version and not update_shown:
        update = input(f"A new version {remote_version} is available. Do you want to update? (y/n): ")
        if update == 'y':
            update_path = f"https://raw.githubusercontent.com/jelloDog-applications/jellopass/{branch}/JelloPass.py"
            updated_script = requests.get(update_path).text
            with open("JelloPass.py", "w") as f:
                f.write(updated_script)
            print("Update successful, please restart the script.")
            exit()
        else:
            update_shown = True


def save_password(name, password):
    with open(passwords_file, "a") as f:
        encrypted_password = cipher.encrypt(password.encode())
        f.write(f"{name}:{encrypted_password.decode()}\n")


def get_password(name):
    with open(passwords_file, "r") as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line.startswith(f"{name}:"):
                encrypted_password = line.split(":", 1)[1]
                password = cipher.decrypt(encrypted_password.encode()).decode()
                return password
        return None


def list_passwords():
    with open(passwords_file, "r") as f:
        lines = f.readlines()
        if lines:
            print("Available passwords:")
            for line in lines:
                name = line.split(":", 1)[0]
                print(name)
        else:
            print("No passwords found.")


while True:
    check_updates()
    session = input("Do you want to add a password (type 'add') or open a password (type 'open') or type 'help' or 'exit' to close the program:\n")

    if session == "help":
        help_com = input("type 'About', 'Bug', or 'Feature':\n")

        if help_com == "Feature":
            print("Click this link to suggest a new feature: " + Featurelink)

        if help_com == "Bug":
            print("Please go to this link to report a bug: " + Buglink)

        if help_com == "About":
            print("JelloPass Was Made By JelloDog-Applications " + local_version)

    if session == "close" or session == "exit":
        print("Thank you for using JelloPass")
        sleep(0.5)
        break

    if session == "open":
        list_passwords()
        pass_open = input("Enter the name of the password you want to open:\n")

        # Validate the password file name
        if not pass_open.isalnum():
            print("Error: Password file name can only contain alphanumeric characters.")
        else:
            password = get_password(pass_open)
            if password:
                print('Deleting in 10 seconds')
                pyperclip.copy(password)
                sleep(10)
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
                win32clipboard.OpenClipboard()
                win32clipboard.SetClipboardText("")
                win32clipboard.CloseClipboard()
            else:
                print(f"Password '{pass_open}' not found.")

    if session == "add":
        new_name = input("What is the name of your password?:\n")
        password = input("Please enter the password:\n")
        save_password(new_name, password)
        print("Password saved successfully.")
