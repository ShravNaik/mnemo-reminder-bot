import os
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
from datetime import datetime, date
import sqlite3

load_dotenv()

app = Flask(__name__)

DB_PATH = "mnemo.db"

# Twilio credentials from .env
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Initialize scheduler
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
scheduler = BackgroundScheduler()
scheduler.start()

# Initialize SQLite Database
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user TEXT,
                        task TEXT,
                        due_date TEXT,
                        status TEXT DEFAULT 'pending',
                        recurrence TEXT
                    )''')
    conn.commit()
    conn.close()

def add_task(user, task, due_date=None, recurrence=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO tasks (user, task, due_date, status, recurrence) VALUES (?, ?, ?, ?, ?)", (user, task, due_date, "🟡 Pending", recurrence))
    conn.commit()
    conn.close()

def get_tasks(user):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT task, due_date, status FROM tasks WHERE user=?", (user,))
    rows = c.fetchall()
    conn.close()
    return rows

def delete_task(user, task):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE user=? AND task=?", (user, task))
    conn.commit()
    conn.close()

def delete_all_tasks(user):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE user=?", (user,))
    conn.commit()
    conn.close()

def mark_task_done(user, task):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET status='🟢 Done' WHERE user=? AND task=?", (user, task))
    conn.commit()
    conn.close()

def edit_task(user, old_task, new_task, new_due_date=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET task=?, due_date=? WHERE user=? AND task=?", (new_task, new_due_date, user, old_task))
    conn.commit()
    conn.close()

def send_reminder(user, task):
    from_number = TWILIO_WHATSAPP_NUMBER
    to_number = user

    if not from_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"

    client.messages.create(
        from_=from_number,
        to=to_number,
        body=f"⏱️ Reminder: {task}"
    )

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From")
    resp = MessagingResponse()
    msg = resp.message()

    user_tasks = get_tasks(sender)
    if not user_tasks and incoming_msg in ["hi", "start"]:
        msg.body(
            "👋 Welcome to Mnemo!\n"
            "I’m your WhatsApp reminder assistant.\n\n"
            "Here’s what I can do:\n"
            "- add <task> at <time/date> [daily/weekly]\n"
            "- view / view pending / view done\n"
            "- delete <task number or name>\n"
            "- delete all / confirm delete all\n"
            "- done <task number>\n"
            "- edit <task number> <new text>\n"
            "- help (list all commands)\n\n"
            "Try: add Buy milk at 21:00"
        )
        return str(resp)

    if incoming_msg == "bye":
        msg.body("👋 See you later! I'll keep your remainders safe!")
        return str(resp)

    # Delete all command
    if incoming_msg == "delete all":
        user_tasks = get_tasks(sender)
        if user_tasks:
            formatted = "\n".join([f"{t[0]} (due: {t[1]})" if t[1] else f"{i+1}. {t[0]}"
                                                                        for i, t in enumerate(user_tasks)])
            msg.body("‼️You are about to delete all tasks!\nYour Tasks:\n" + formatted + "\n\n Reply with 'confirm delete all' to delete all tasks.")
        else:
            msg.body("❌ No Tasks Found.")

    elif incoming_msg == "confirm delete all":
        delete_all_tasks(sender)
        msg.body("✅ Successfully deleted all tasks.")

    # Add command
    elif incoming_msg.startswith("add"):
        parts = incoming_msg.replace("add", "").strip().split(" at ")
        task = parts[0].strip()
        recurrence = None
        due_date_str = None

        if len(parts) > 1:
            if " daily" in parts[1]:
                due_date_str = parts[1].replace(" daily", "").strip()
                recurrence = "daily"
            elif " weekly" in parts[1]:
                due_date_str = parts[1].replace(" weekly", "").strip()
                recurrence = "weekly"
            else:
                due_date_str = parts[1].strip()

        add_task(sender, task, due_date_str, recurrence)
        body_text = f"✅ Task added: {task}."

        if due_date_str:
            try:
                if len(due_date_str) == 5:
                    today = date.today()
                    due_date = datetime.strptime(due_date_str, "%H:%M").replace(
                        day=today.day, month=today.month, year=today.year
                    )
                else:
                    due_date = datetime.strptime(due_date_str, "%d-%m-%Y %H:%M")

                if recurrence == "daily":
                    scheduler.add_job(send_reminder, "interval", days=1, start_date=due_date, args=[sender, task])
                    body_text += f"\n⏰ Daily reminder set at {due_date_str}"
                elif recurrence == "weekly":
                    scheduler.add_job(send_reminder, "interval", weeks=1, start_date=due_date, args=[sender, task])
                    body_text += f"\n⏰ Weekly reminder set at {due_date_str}"
                else:
                    scheduler.add_job(send_reminder, "date", run_date=due_date, args=[sender, task])
                    body_text += f"\n⏱️ Reminder set for {due_date.strftime('%d-%m-%Y %H:%M')}"
            except ValueError:
                body_text = "⚠️ Invalid time/date format. Use HH:MM or DD-MM-YYYY HH:MM"

        msg.body(body_text)

    # View command
    elif incoming_msg == "view":
        user_tasks = get_tasks(sender)
        if user_tasks:
            formatted = "\n".join([f"{i+1}. {t[0]} (due: {t[1]}) - {t[2]}" if t[1] else f"{i+1}. {t[0]} - {t[2]}"
                                   for i, t in enumerate(user_tasks)])
            msg.body("📃 Your Tasks: \n"+ formatted)
        else:
            msg.body("❌ No Tasks Found.")

    # Delete command
    elif incoming_msg.startswith("delete"):
        arg = incoming_msg.replace("delete", "").strip()
        if arg.isdigit():
            index = int(arg) - 1
            user_tasks = get_tasks(sender)
            if 0 <= index < len(user_tasks):
                task_to_delete = user_tasks[index][0]
                delete_task(sender, task_to_delete)
                msg.body(f"🗑️ Task deleted: {task_to_delete}")
            else:
                msg.body("❓ Invalid task number/ List is empty.")
        else:
            task = arg
            delete_task(sender, task)
            msg.body(f"🗑️ Task deleted: {task}")

    # Done command
    elif incoming_msg.startswith("done"):
        arg = incoming_msg.replace("done", "").strip()
        if arg.isdigit():
            index = int(arg) - 1
            user_tasks = get_tasks(sender)
            if 0 <= index < len(user_tasks):
                task_to_mark = user_tasks[index][0]
                mark_task_done(sender, task_to_mark)
                msg.body(f"✅ Yoo-Hoo! Task marked as done: {task_to_mark}")
            else:
                msg.body("❓ Invalid task number.")
        else:
            task = arg
            mark_task_done(sender, task)
            msg.body(f"✅ Task marked ad done: {task}")

    # View pending command
    elif incoming_msg == "view pending":
        user_tasks = get_tasks(sender)
        pending = [t for t in user_tasks if t[2] == "🟡 Pending"]
        if pending:
            formatted = "\n".join(f"{i+1}. {t[0]} (due: {t[1]}) - {t[2]}" for i, t in enumerate(pending))
            msg.body("📋 Pending tasks:\n"+ formatted)
        else:
            msg.body("✅ No pending tasks!")

    # View done command
    elif incoming_msg == "view done":
        user_tasks = get_tasks(sender)
        done = [t for t in user_tasks if t[2] == "🟢 Done"]
        if done:
            formatted = "\n".join(f"{i+1}. {t[0]} (due: {t[1]}) - {t[2]}" for i, t in enumerate(done))
            msg.body("🎉 Completed tasks:\n"+ formatted)
        else:
            msg.body("❌ No completed tasks yet.")

    # Edit command
    elif incoming_msg.startswith("edit"):
        arg = incoming_msg.replace("edit", "").strip()
        parts = arg.split(" ", 1)
        if parts[0].isdigit():
            index = int(parts[0]) - 1
            user_tasks = get_tasks(sender)
            if 0 <= index < len(user_tasks):
                old_task = user_tasks[index][0]

                if " at " in parts[1]:
                    new_task_text, new_due_date = parts[1].split(" at ", 1)
                    new_task_text = new_task_text.strip()
                    new_due_date = new_due_date.strip()
                else:
                    new_task_text = parts[1].strip()
                    new_due_date = user_tasks[index][1]

                edit_task(sender, old_task, new_task_text, new_due_date)
                msg.body(f"✅ Task updated:\nFrom: {old_task}\nTo: {new_task_text} (due: {new_due_date})")
            else:
                msg.body("❌ Invalid task number")
        else:
            msg.body("⚠️ Use: edit <task number> <new text> [at <DD-MM-YYYY HH:MM> or HH:MM]")

    # Help command
    elif incoming_msg == "help":
        msg.body(
            "🤖 Mnemo Bot Commands:\n"
            "- *add* <task> at <HH:MM or DD-MM-YYYY HH:MM> [daily/weekly]\n"
            "       ➝ Example: add Gym at 07:00 daily\n\n"
            "- *view*\n"
            "   ➝ Shows all tasks\n\n"
            "- *view pending*\n"
            "   ➝ Shows only unfinished tasks\n\n"
            "- *view done*\n"
            "   ➝ Shows completed tasks\n\n"
            "- *delete* <task number or task name>\n"
            "   ➝ Example: delete 2\n\n"
            "- *delete all*\n"
            "   ➝ Shows all tasks and asks for confirmation\n\n"
            "- *confirm delete all*\n"
            "   ➝ Deletes all tasks after confirmation\n\n"
            "- *done* <task number>\n"
            "   ➝ Marks a task as done\n\n"
            "- *edit* <task number> <new text> [at <time/date>]\n"
            "   ➝ Example: edit 1 Finish math homework at 19:00\n\n"
            "- *help*\n"
            "   ➝ Shows this list"
        )

    # Invalid command
    else:
        msg.body("Invalid Command. Please type 'help' to get the list of available commands.")

    return str(resp)

if __name__ == "__main__":
    init_db()
    app.run(port=5000)