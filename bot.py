import os
import asyncio
import csv
import re
from datetime import datetime, timedelta
from typing import Dict, Any

from telethon import TelegramClient, events, Button, __version__ as telethon_version
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsRecent
from telethon.tl.types import User, Channel, Chat
from telethon.errors import FloodWaitError, SessionPasswordNeededError

import config

print(f"Telethon version: {telethon_version}")
try:
    print(f"Script path: {os.path.abspath(__file__)}")
except NameError:
    print("Script path: Unable to determine (running in an interactive environment)")

BOT_TOKEN = getattr(config, "BOT_TOKEN", None)
ADMIN_IDS = getattr(config, "ADMIN_IDS", [])
MAX_REPORTS = getattr(config, "MAX_REPORTS", 50)

if hasattr(config, "ACCOUNT_DETAILS"):
    ACCOUNT_DETAILS = config.ACCOUNT_DETAILS
else:
    single = {}
    if hasattr(config, "PHONE"):
        single['phone'] = getattr(config, "PHONE")
    if hasattr(config, "API_ID"):
        single['api_id'] = getattr(config, "API_ID")
    if hasattr(config, "API_HASH"):
        single['api_hash'] = getattr(config, "API_HASH")
    if hasattr(config, "SESSION"):
        single['session'] = getattr(config, "SESSION")
    if single:
        single.setdefault('proxy', None)
        ACCOUNT_DETAILS = [single]
    else:
        ACCOUNT_DETAILS = []

BOT_API_ID = getattr(config, "BOT_API_ID", ACCOUNT_DETAILS[0]['api_id'] if ACCOUNT_DETAILS else None)
BOT_API_HASH = getattr(config, "BOT_API_HASH", ACCOUNT_DETAILS[0]['api_hash'] if ACCOUNT_DETAILS else None)

username_to_id: Dict[str, int] = {}
SUDO_APPROVED_USERS: Dict[int, datetime] = {}
user_states: Dict[int, Dict[str, Any]] = {}
reporting_clients = []

SIM_LOG_FILE = "simulated_actions.csv"

def parse_message_link(link: str):
    pattern = r"https://t\.me/(?:c/)?([^/]+)/(\d+)"
    match = re.match(pattern, link)
    if not match:
        return None, None
    chat_identifier, message_id = match.groups()
    return chat_identifier, int(message_id)

def parse_duration(duration_str: str) -> int:
    parts = duration_str.lower().split()
    if len(parts) != 2:
        raise ValueError("Invalid duration format")
    amount_str, unit = parts
    amount = int(amount_str)
    multipliers = {
        "second": 1, "seconds": 1,
        "minute": 60, "minutes": 60,
        "hour": 3600, "hours": 3600,
        "day": 86400, "days": 86400,
        "week": 604800, "weeks": 604800,
        "month": 2592000, "months": 2592000
    }
    if unit not in multipliers:
        raise ValueError("Invalid time unit")
    return amount * multipliers[unit]

def log_simulated_action(action: str, target: str, performed_by: str, details: str = ""):
    header_needed = not os.path.isfile(SIM_LOG_FILE)
    with open(SIM_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header_needed:
            writer.writerow(["Timestamp", "Action", "Target", "Performed By", "Details"])
        writer.writerow([datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), action, target, performed_by, details])

async def check_sudo_expirations():
    while True:
        now = datetime.utcnow()
        expired = [uid for uid, exp in SUDO_APPROVED_USERS.items() if now >= exp]
        for uid in expired:
            SUDO_APPROVED_USERS.pop(uid, None)
            try:
                await bot.send_message(uid, "Your sudo approval has expired.")
            except Exception:
                pass
        await asyncio.sleep(60)

async def scan_users(event, client: TelegramClient):
    try:
        chat = await event.get_chat()
        if not hasattr(chat, "id"):
            await event.respond("This command can only be used in a group or channel.")
            return
        participants = await client(GetParticipantsRequest(
            channel=chat.id,
            filter=ChannelParticipantsRecent(),
            offset=0,
            limit=200,
            hash=0
        ))
        count = 0
        for u in participants.users:
            if getattr(u, "username", None):
                username_to_id[u.username.lower()] = u.id
                count += 1
        await event.respond(f"Scanned and mapped {count} usernames from this chat.")
    except Exception as e:
        await event.respond(f"Error scanning users: {e}")

async def resolve_user(event):
    if event.sender_id not in ADMIN_IDS:
        await event.respond("You are not authorized to use this command.")
        return
    args = event.message.message.split()
    if len(args) < 2:
        await event.respond("Usage: /resolve @username")
        return
    username = args[1].lstrip("@")
    response_lines = []
    for client, account in reporting_clients:
        try:
            result = await client(ResolveUsernameRequest(username))
            found_any = False
            for u in result.users:
                if getattr(u, "username", None) and u.username.lower() == username.lower():
                    response_lines.append(f"{account['phone']}: accessible (id={u.id})")
                    username_to_id[username.lower()] = u.id
                    found_any = True
                    break
            if not found_any:
                response_lines.append(f"{account['phone']}: not accessible or not found")
        except FloodWaitError as e:
            response_lines.append(f"{account['phone']}: flood wait {e.seconds}s")
        except Exception as e:
            response_lines.append(f"{account['phone']}: error - {e}")
    await event.respond("\n".join(response_lines))

async def simulate_report_handler(event):
    if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
        await event.respond("You are not authorized to use this command.")
        return
    args = event.message.message.split(maxsplit=1)
    if len(args) < 2:
        await event.respond("Usage: /simulate_report target_description")
        return
    target = args[1]
    performer = str(event.sender_id)
    log_simulated_action("simulate_report", target, performer, details="User-triggered simulation")
    await event.respond(f"Simulated report logged for: {target}")

bot = TelegramClient("bot_session", BOT_API_ID, BOT_API_HASH)

async def main():
    for acc in ACCOUNT_DETAILS:
        phone = acc.get("phone")
        api_id = acc.get("api_id")
        api_hash = acc.get("api_hash")
        session = acc.get("session", f"session_{phone}")
        proxy = acc.get("proxy")
        proxy_settings = None
        if proxy:
            proxy_settings = {
                "proxy_type": "http",
                "addr": proxy.get("ip"),
                "port": proxy.get("port"),
                "username": proxy.get("username"),
                "password": proxy.get("password"),
                "rdns": True
            }
        client = TelegramClient(session, api_id, api_hash, proxy=proxy_settings)
        try:
            await client.start(phone=phone)
            me = await client.get_me()
            reporting_clients.append((client, acc))
            print(f"Started client for {acc.get('phone')} (me: {getattr(me, 'phone', 'unknown')})")
        except Exception as e:
            print(f"Failed to start client for {phone}: {e}")

    if BOT_TOKEN is None:
        print("BOT_TOKEN missing in config.py; bot commands disabled. Exiting.")
        return

    await bot.start(bot_token=BOT_TOKEN)
    print("Bot started")

    asyncio.create_task(check_sudo_expirations())

    @bot.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            await event.respond("You are not authorized to use this bot.")
            return
        buttons = [
            [Button.inline("Scan Users", data="scan")],
            [Button.inline("Resolve Username", data="resolve")],
            [Button.inline("List Accounts", data="list_accounts")],
            [Button.inline("Add Account", data="add_account")],
            [Button.inline("Delete Account", data="delete_account")],
            [Button.inline("Simulate Report (safe)", data="simulate_report")],
        ]
        await event.respond("Admin helper bot - choose an action:", buttons=buttons)

    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode() if isinstance(event.data, (bytes, bytearray)) else str(event.data)
        uid = event.sender_id
        if uid not in ADMIN_IDS and uid not in SUDO_APPROVED_USERS:
            await event.answer("Not authorized.")
            return

        if data == "scan":
            await event.respond("Please run /scan in the group you want to scan (this button just reminds you).")
        elif data == "resolve":
            await event.respond("Use /resolve @username to check accessibility across configured accounts.")
        elif data == "list_accounts":
            if not ACCOUNT_DETAILS:
                await event.respond("No accounts configured.")
            else:
                resp = "Configured accounts:\n"
                for a in ACCOUNT_DETAILS:
                    proxy = a.get("proxy")
                    ps = "no proxy" if not proxy else f"{proxy.get('ip')}:{proxy.get('port')}"
                    resp += f"- {a.get('phone')} (session: {a.get('session')}) [{ps}]\n"
                await event.respond(resp)
        elif data == "add_account":
            user_states[uid] = {"step": "add_phone"}
            await event.respond("Starting add-account flow. Please send the phone number (e.g., +1234567890).")
        elif data == "delete_account":
            user_states[uid] = {"step": "delete_phone"}
            await event.respond("Send the phone number to delete (e.g., +1234567890).")
        elif data == "simulate_report":
            await event.respond("Use /simulate_report <target_description> to create a harmless log entry.")

        await event.answer()

    @bot.on(events.NewMessage(pattern="/scan"))
    async def scan_handler(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond("You are not authorized.")
            return
        if not reporting_clients:
            await event.respond("No reporting clients are configured to perform scanning. Please add at least one account.")
            return
        await scan_users(event, reporting_clients[0][0])

    @bot.on(events.NewMessage(pattern=r"^/resolve\b"))
    async def resolve_handler(event):
        await resolve_user(event)

    @bot.on(events.NewMessage(pattern=r"^/simulate_report\b"))
    async def simulate_report_cmd(event):
        await simulate_report_handler(event)

    @bot.on(events.NewMessage(pattern=r"^/report_count\b"))
    async def report_count_cmd(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond("Not authorized.")
            return
        counts = {}
        if not os.path.isfile(SIM_LOG_FILE):
            await event.respond("No simulated actions logged yet.")
            return
        try:
            with open(SIM_LOG_FILE, "r", encoding="utf-8") as f:
                rdr = csv.reader(f)
                headers = next(rdr, None)
                for row in rdr:
                    if len(row) >= 4:
                        performed_by = row[3]
                        counts[performed_by] = counts.get(performed_by, 0) + 1
            resp = "Simulated action counts:\n"
            for who, c in counts.items():
                resp += f"{who}: {c}\n"
            await event.respond(resp)
        except Exception as e:
            await event.respond(f"Error reading log: {e}")

    @bot.on(events.NewMessage(pattern=r"^/sudo\b"))
    async def sudo_cmd(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond("Not authorized.")
            return
        parts = event.message.message.split()
        if len(parts) < 3:
            await event.respond("Usage: /sudo <user_id_or_@username> <duration> (e.g., /sudo 123456789 1 week)")
            return
        target = parts[1]
        duration_str = " ".join(parts[2:4]) if len(parts) >= 4 else parts[2]
        target_id = None
        if target.startswith("@"):
            uname = target.lstrip("@")
            if reporting_clients:
                try:
                    res = await reporting_clients[0][0](ResolveUsernameRequest(uname))
                    for u in res.users:
                        if getattr(u, "username", None) and u.username.lower() == uname.lower():
                            target_id = u.id
                            break
                except Exception as e:
                    await event.respond(f"Error resolving username: {e}")
                    return
            else:
                await event.respond("No accounts available to resolve username; please provide a user ID.")
                return
        else:
            try:
                target_id = int(target)
            except ValueError:
                await event.respond("Invalid target. Provide a user ID or @username.")
                return
        try:
            seconds = parse_duration(duration_str)
        except Exception as e:
            await event.respond(f"Invalid duration: {e}")
            return
        expiry = datetime.utcnow() + timedelta(seconds=seconds)
        SUDO_APPROVED_USERS[target_id] = expiry
        await event.respond(f"Approved {target_id} until {expiry.isoformat()} UTC.")

    @bot.on(events.NewMessage(pattern=r"^/unsudo\b"))
    async def unsudo_cmd(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond("Not authorized.")
            return
        parts = event.message.message.split()
        if len(parts) < 2:
            await event.respond("Usage: /unsudo <user_id_or_@username>")
            return
        target = parts[1]
        target_id = None
        if target.startswith("@"):
            uname = target.lstrip("@")
            if reporting_clients:
                try:
                    res = await reporting_clients[0][0](ResolveUsernameRequest(uname))
                    for u in res.users:
                        if getattr(u, "username", None) and u.username.lower() == uname.lower():
                            target_id = u.id
                            break
                except Exception as e:
                    await event.respond(f"Error resolving username: {e}")
                    return
            else:
                await event.respond("No accounts available to resolve username; please provide a user ID.")
                return
        else:
            try:
                target_id = int(target)
            except ValueError:
                await event.respond("Invalid target. Provide a user ID or @username.")
                return
        if target_id in SUDO_APPROVED_USERS:
            SUDO_APPROVED_USERS.pop(target_id, None)
            await event.respond(f"Removed sudo approval for {target_id}.")
        else:
            await event.respond("That user is not approved.")

    @bot.on(events.NewMessage(pattern=r"^/add\b"))
    async def add_begin(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond("Not authorized.")
            return
        user_states[event.sender_id] = {"step": "add_phone"}
        await event.respond("Enter phone (e.g., +1234567890):")

    @bot.on(events.NewMessage)
    async def generic_flow(event):
        uid = event.sender_id
        if uid not in user_states:
            return
        state = user_states[uid]
        step = state.get("step")
        if step == "add_phone":
            phone = event.message.message.strip()
            if not phone.startswith("+"):
                await event.respond("Phone must start with '+'. Try again or /cancel")
                return
            state["new_account"] = {"phone": phone}
            state["step"] = "add_api_id"
            user_states[uid] = state
            await event.respond("Enter API ID (number):")
        elif step == "add_api_id":
            try:
                api_id = int(event.message.message.strip())
                state["new_account"]["api_id"] = api_id
                state["step"] = "add_api_hash"
                user_states[uid] = state
                await event.respond("Enter API hash:")
            except ValueError:
                await event.respond("API ID must be a number. Try again.")
        elif step == "add_api_hash":
            api_hash = event.message.message.strip()
            state["new_account"]["api_hash"] = api_hash
            state["step"] = "add_session"
            user_states[uid] = state
            await event.respond("Enter session name (e.g., session_2):")
        elif step == "add_session":
            session = event.message.message.strip()
            state["new_account"]["session"] = session
            new_acc = state["new_account"]
            new_acc.setdefault("proxy", None)
            ACCOUNT_DETAILS.append(new_acc)
            client = TelegramClient(new_acc["session"], new_acc["api_id"], new_acc["api_hash"])
            try:
                await client.connect()
                sent_code = await client.send_code_request(new_acc["phone"])
                state["phone_code_hash"] = sent_code.phone_code_hash
                state["step"] = "add_verification_code"
                user_states[uid] = state
                await event.respond(f"Code sent to {new_acc['phone']}. Enter the code:")
            except Exception as e:
                ACCOUNT_DETAILS.remove(new_acc)
                user_states.pop(uid, None)
                await event.respond(f"Failed to send code: {e}")
        elif step == "add_verification_code":
            code = event.message.message.strip()
            new_acc = state["new_account"]
            phone_code_hash = state.get("phone_code_hash")
            client = TelegramClient(new_acc["session"], new_acc["api_id"], new_acc["api_hash"])
            try:
                await client.connect()
                await client.sign_in(phone=new_acc["phone"], code=code, phone_code_hash=phone_code_hash)
                me = await client.get_me()
                reporting_clients.append((client, new_acc))
                user_states.pop(uid, None)
                await event.respond(f"Successfully added account {new_acc['phone']}.")
            except SessionPasswordNeededError:
                await event.respond("Two-step verification enabled for account; cannot complete add via bot.")
                await client.disconnect()
                ACCOUNT_DETAILS.remove(new_acc)
                user_states.pop(uid, None)
            except Exception as e:
                await event.respond(f"Failed to sign in: {e}")
                await client.disconnect()
                ACCOUNT_DETAILS.remove(new_acc)
                user_states.pop(uid, None)
        elif step == "delete_phone":
            phone = event.message.message.strip()
            acc_to_remove = None
            for a in ACCOUNT_DETAILS:
                if a.get("phone") == phone:
                    acc_to_remove = a
                    break
            if not acc_to_remove:
                await event.respond("Account not found.")
                user_states.pop(uid, None)
                return
            ACCOUNT_DETAILS.remove(acc_to_remove)
            for client, acc in list(reporting_clients):
                if acc.get("phone") == phone:
                    await client.disconnect()
                    reporting_clients.remove((client, acc))
            session_name = acc_to_remove.get("session")
            session_file = f"{session_name}.session"
            try:
                if os.path.exists(session_file):
                    os.remove(session_file)
                await event.respond(f"Removed account {phone}.")
            except Exception:
                await event.respond(f"Removed account {phone}, but failed to remove session file.")
            user_states.pop(uid, None)

    @bot.on(events.NewMessage(pattern=r"^/list\b"))
    async def list_cmd(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond("Not authorized.")
            return
        if not ACCOUNT_DETAILS:
            await event.respond("No accounts registered.")
            return
        resp = "Registered accounts:\n"
        for a in ACCOUNT_DETAILS:
            proxy = a.get("proxy")
            ps = "no proxy" if not proxy else f"{proxy.get('ip')}:{proxy.get('port')}"
            resp += f"- {a.get('phone')} (session: {a.get('session')}) [{ps}]\n"
        await event.respond(resp)

    @bot.on(events.NewMessage(pattern=r"^/function\b"))
    async def function_cmd(event):
        uid = event.sender_id
        if uid not in ADMIN_IDS and uid not in SUDO_APPROVED_USERS:
            await event.respond("Not authorized.")
            return
        cmds = [
            "/start - show main menu",
            "/scan - scan users in the group where you run this (admin)",
            "/resolve @username - check accessibility of username across accounts (admin)",
            "/list - list configured accounts (admin)",
            "/add - add an account interactively (admin)",
            "/delete - delete an account interactively (admin)",
            "/simulate_report - harmless log-only simulation of a report",
            "/report_count - show counts from simulated log (admin)",
            "/sudo - grant sudo approval (admin)",
            "/unsudo - remove sudo approval (admin)",
        ]
        await event.respond("Available commands:\n" + "\n".join(cmds))

    @bot.on(events.NewMessage(pattern=r"^/cancel\b"))
    async def cancel_cmd(event):
        if event.sender_id in user_states:
            user_states.pop(event.sender_id, None)
            await event.respond("Operation cancelled.")
        else:
            await event.respond("No active operation.")

    print("Bot event handlers registered. Running...")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down...")
    finally:
        for client, _ in reporting_clients:
            try:
                await client.disconnect()
            except Exception:
                pass
        await bot.disconnect()

if __name__ == "__main__":
    asyncio.run(main())