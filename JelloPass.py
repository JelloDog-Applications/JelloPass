from time import sleep
import requests
from cryptography.fernet import Fernet
import os
import pyperclip
import configparser
from termcolor import colored

appfolder = (os.getenv('APPDATA')) + "/JelloDog-Applications"

if not os.path.exists(appfolder):
    os.makedirs(appfolder)

# Create an encrypted folder for the passwords
encrypted_folder = appfolder + "/encrypted"
if not os.path.exists(encrypted_folder):
    os.mkdir(encrypted_folder)

# Generate a new key or load an existing one
key_filename = appfolder + "/jellopass.key"
try:
    with open(key_filename, "rb") as key_file:
        key = key_file.read()
except FileNotFoundError:
    key = Fernet.generate_key()
    with open(key_filename, "wb") as key_file:
        key_file.write(key)

cipher = Fernet(key)

# Define URLs for feature and bug reporting
Featurelink = 'https://tinyurl.com/y3hex46c'
Buglink = 'https://tinyurl.com/yy4o4rgc'

# Create or read the configuration file
config_file = appfolder + "/config.ini"
config = configparser.ConfigParser()
if not os.path.exists(config_file):
    config.add_section("General")
    config.set("General", "branch", "Stable")
    with open(config_file, "w") as f:
        config.write(f)

config.read(config_file)
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

# Function to check for updates
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

            version_text = requests.get(version_url).text.strip()
            with open(version_file, "w") as f:
                f.write(version_text)

            print("Update successful, please restart the script.")
            exit()
        else:
            update_shown = True

# Function to save a password
def save_password(name, password):
    with open(passwords_file, "a") as f:
        encrypted_password = cipher.encrypt(password.encode())
        f.write(f"{name}:{encrypted_password.decode()}\n")

# Function to retrieve a password
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

# Function to list all saved passwords
def list_passwords():
    with open(passwords_file, "r") as f:
        lines = f.readlines()
        if lines:
            print("Available passwords:")
            for line in lines:
                name = line.split(":", 1)[0]
                print("- " + name)
        else:
            print("No passwords found.")

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

# Main loop
while True:
    check_updates()
    session = input("Do you want to add a password (add), open a password (open), change branch (branch), help, or exit? ")

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
                print('Deleting in 10 seconds')
                pyperclip.copy(password)
                sleep(10)
            else:
                print(f"Password '{pass_open}' not found.")

    elif session == "add":
        new_name = input("What is the name of your password? ")
        password = input("Please enter the password: ")
        save_password(new_name, password)
        print("Password saved successfully.")

    elif session == "branch":
        change_branch()

    else:
        print("Invalid command. Please try again.")
