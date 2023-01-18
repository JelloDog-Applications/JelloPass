from time import sleep
import requests
from cryptography.fernet import Fernet

# Generate a new key
key = Fernet.generate_key()
cipher = Fernet(key)

Featurelink = ('https://tinyurl.com/y3hex46c')
Buglink = ('https://tinyurl.com/yy4o4rgc')
version = ('v1.0.0')


def check_updates():
    # Check the version of the script on the remote repository
    version_url = "https://raw.githubusercontent.com/Sharkrider120/password_manager/main/version.txt"
    remote_version = requests.get(version_url).text.strip()
    if remote_version != version:
        update = input(
            f"A new version {remote_version} is available. Do you want to update? (y/n): ")
        if update == 'y':
            # Download the new version of the script
            update_url = "https://raw.githubusercontent.com/Sharkrider120/password_manager/main/password%20manager.py"
            updated_script = requests.get(update_url).text
            with open("password_manager.py", "w") as f:
                f.write(updated_script)
            print("Update successful, please restart the script.")
            exit()


while True:
    check_updates()
    session = input(
        "Do you want to add a password type add or type open to open a password or type help :\n")

    if session == "help":
        help_com = input("type About, Bug, or Feature:\n")

        if help_com == ("Feature"):
            print("Click this link to suggest a new feature" + Featurelink)

        if help_com == ("Bug"):
            print("Please go to this link to report a bug " + Buglink)

        if help_com == ("About"):
            print("PASSWORD MANAGER By Cody Wagner v" + version)

    if session == "open":
        pass_open = input("What is the name of the password?:\n")

        # Read the encrypted password from the file
        with open(pass_open, "rb") as f:
            encrypted_password = f.read()

        # Decrypt the password
        password = cipher.decrypt(encrypted_password).decode()
        print(password)
        sleep(10)

    if session == "add":
        new_name = input("What is the name of your password?:\n")
        password = input("Please enter the password:\n")

        # Encrypt the password
        encrypted_password = cipher.encrypt(password.encode())

        # Write the encrypted password to a file
        with open(new_name, "wb") as f:
            f.write(encrypted_password)
