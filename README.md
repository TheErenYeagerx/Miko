<p align="center">
  <img src="https://i.ibb.co/392BpmQ0/tmpas8jv23x.jpg" width="400" alt="Miko Safe Admin Bot">
</p>




# Miko Safe Admin Telethon Bot

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg?style=flat)](#)
[![Release](https://img.shields.io/badge/release-v0.1.0-blue.svg?style=flat)](#)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg?logo=python&style=flat)](https://www.python.org/)
[![Telethon](https://img.shields.io/badge/telethon-%3E%3D1.0-orange.svg?style=flat)](https://docs.telethon.dev/)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat)](#)


---

## Overview
**Miko Safe Admin Telethon Bot** is a safe and ethical administrative helper bot built with Telethon. It allows account management, username resolution, temporary sudo approvals, and simulation logs — all without performing any abusive or bulk actions.  

This bot is designed for administrators to manage their own accounts or groups safely and responsibly.

---

## Quickstart

1. Create and edit `config.py` with your `BOT_TOKEN`, `ADMIN_IDS`, and account credentials.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt

3. Run the bot:
   ```bash
   python bot.py
   ```
4. Talk to the bot from a Telegram account listed in `ADMIN_IDS` and send `/start`.

Configuration (config.py)
-------------------------
- BOT_TOKEN: Bot token string (required).
- BOT_API_ID / BOT_API_HASH: Optional API credentials for the bot client; if omitted, the bot attempts to reuse the first account in ACCOUNT_DETAILS.
- ADMIN_IDS: List of integer user IDs (administrators).
- MAX_REPORTS: Integer used for UI bounds (no abusive functionality).
- ACCOUNT_DETAILS: list of accounts — each with `phone`, `api_id`, `api_hash`, `session`, and optional `proxy`.

Commands
--------
Admin-only commands:
- /start — Show main menu.
- /scan — Scan recent participants in the group and map usernames → IDs.
- /resolve @username — Check accessibility across configured accounts.
- /add — Interactive flow to add a new account (verification code required).
- /delete — Interactive flow to remove an account and its session file.
- /list — List configured accounts and proxy status.
- /report_count — Show counts from the simulated CSV log.
- /sudo <user_or_@username> <duration> — Grant temporary sudo approval (e.g., `1 week`).
- /unsudo <user_or_@username> — Remove sudo approval.
- /function — List available commands.

Admin and sudo users:
- /simulate_report <description> — Create a harmless CSV log entry to simulate an action for testing.

Misc:
- /cancel — Cancel any active interactive flow.

Simulated actions log
---------------------
All simulated actions are logged in `simulated_actions.csv` with:
- Timestamp (UTC)
- Action
- Target
- Performed By (user id)
- Details

Security & ethics
-----------------
This project intentionally avoids automatic reporting and bulk actions that could harm others. Use the bot only for legitimate administration of accounts you own or administer. Misuse may violate Telegram's terms of service and local laws.


## Contact & Support
If you need help configuring the bot, you can:  

- Open an issue on this repository: [Create a new issue](https://github.com/TheErenYeagerx/Miko/issues/new)  
- Contact the maintainer directly on Telegram: [Eren Yeager](https://t.me/TheErenYeager)
----