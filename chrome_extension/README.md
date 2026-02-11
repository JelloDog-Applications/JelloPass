# JelloPass Chrome Extension

Use your JelloPass passwords in Chrome. The extension talks to the JelloPass app on your computer.

## Setup

1. **Run JelloPass with the GUI** (must be open for the extension to work):
   ```bash
   python main.py --gui
   ```
   Unlock your vault (master password if you use one).

2. **Install the extension in Chrome**
   - Open `chrome://extensions/`
   - Turn on **Developer mode** (top right)
   - Click **Load unpacked**
   - Select the `chrome_extension` folder inside your JelloPass project

3. **Use it**
   - Click the JelloPass icon in the toolbar
   - You’ll see your saved entries
   - **Copy** – copies the password to the clipboard
   - **Fill** – fills the password (and username if it’s the entry name) on the current page’s login form

## Security

- The extension only talks to `http://127.0.0.1:47984` on your machine.
- Passwords are sent from the JelloPass app (already unlocked) to the extension only when you click Copy or Fill.
- Keep the JelloPass app closed when you’re not using it so the local server isn’t running.
