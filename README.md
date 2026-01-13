# PW Log Bot

PW Log Bot helps track faction history in Perfect World by parsing local game logs and providing a web interface to view and manage the data.

## Features

- **Log Parsing**: Automatically parses `FactionHistoryData` from the game client.
- **Web Interface**: View clan history, player lists, and statistics via a local web dashboard.
- **Search & Filter**: Filter logs by date, player, or clan.
- **Data Management**: Edit player nicknames and classes directly from the UI.
- **System Tray Integration**: runs quietly in the background with a system tray icon.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd pw_log_bot
    ```

2.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration:**
    - Create a `.env` file (if needed, though mostly using local configs).
    - Ensure `watcher.ini` points to your Perfect World `FactionHistoryData` folder. The bot will try to create/read this on first run.

## Usage

Run the bot:
```bash
python bot.py
```

- The application will start a web server at `http://localhost:8000` (or configured port).
- Access the dashboard in your browser.
- Use the system tray icon to exit.

## Technologies

- **Python 3.10+**
- **FastAPI** (Web Framework)
- **Aiogram** (Telegram integration - optional/legacy)
- **Aiosqlite** (Database)
- **Jinja2** (Templates)
