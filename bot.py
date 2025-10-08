import os
import logging
import sqlite3
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# Настройки - токен ТОЛЬКО из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в переменных окружения!")

DB_NAME = "tasks.db"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# База данных
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_text TEXT,
            reminder_type TEXT,
            reminder_interval INTEGER,
            reminder_time TEXT,
            is_completed BOOLEAN DEFAULT FALSE,
            last_reminder_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def add_task(user_id, task_text, reminder_type, reminder_interval=0, reminder_time=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (user_id, task_text, reminder_type, reminder_interval, reminder_time)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, task_text, reminder_type, reminder_interval, reminder_time))
    conn.commit()
    conn.close()
    logger.info(f"Задача добавлена для пользователя {user_id}")

def get_user_tasks(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, task_text, reminder_type, reminder_interval, reminder_time, is_completed 
        FROM tasks 
        WHERE user_id = ? AND is_completed = FALSE
    ''', (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def mark_task_completed(task_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET is_completed = TRUE WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()
    logger.info(f"Задача {task_id} отмечена выполненной")

def get_tasks_for_reminder():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    current_time = now.strftime('%H:%M')
    current_date = now.strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT id, user_id, task_text, reminder_type, reminder_interval, reminder_time, last_reminder_date 
        FROM tasks 
        WHERE is_completed = FALSE
    ''')
    tasks = cursor.fetchall()
    
    tasks_to_remind = []
    for task in tasks:
        task_id, user_id, task_text, reminder_type, interval, specific_time, last_reminder = task
        
        if reminder_type == 'specific_time':
            if current_time == specific_time and last_reminder != current_date:
                tasks_to_remind.append((task_id, user_id, task_text))
                cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                             (current_date, task_id))
        
        elif reminder_type == 'custom' and interval > 0:
            if last_reminder:
                try:
                    last_reminder_time = datetime.strptime(last_reminder, '%Y-%m-%d %H:%M:%S')
                    time_diff = (now - last_reminder_time).total_seconds() / 60
                    if time_diff >= interval:
                        tasks_to_remind.append((task_id, user_id, task_text))
                        cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                                     (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
                except ValueError:
                    pass
            else:
                cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                             (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
        
        elif reminder_type == 'once' and not last_reminder:
            tasks_to_remind.append((task_id, user_id, task_text))
            cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                         (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
    
    conn.commit()
    conn.close()
    return tasks_to_remind

# Команды бота
def start(update, context):
    user = update.effective_user
    update.message.reply_text(
        f"пиривета {user.first_name}! 👋\n\n"
        "Я бот Дыни для напоминалок\n\n"
        "Команды:\n"
        "/addtask - Добавить задачу\n"
        "/mytasks - Мои задачи\n"
        "/complete - Отметить выполненной\n"
        "/help - Помощь"
    )

def help_command(update, context):
    help_text = """
Команды:
/addtask - Добавить задачу
/mytasks - Показать задачи  
/complete - Отметить выполненной
/help - Помощь

Типы напоминаний:
🔔 Один раз
🔄 Повторять (введи минуты)
🕐 Конкретное время (ЧЧ:ММ)
🚫 Без напоминаний
    """
    update.message.reply_text(help_text)

def add_task_command(update, context):
    keyboard = [
        [InlineKeyboardButton("🔔 Один раз", callback_data="reminder_once")],
        [InlineKeyboardButton("🔄 Повторять", callback_data="reminder_custom")],
        [InlineKeyboardButton("🕐 Время", callback_data="reminder_time")],
        [InlineKeyboardButton("🚫 Без напоминаний", callback_data="reminder_none")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выбери тип напоминания:", reply_markup=reply_markup)

def button_handler(update, context):
    query = update.callback_query
    query.answer()
    
    data = query.data
    
    if data == "reminder_once":
        context.user_data['reminder_type'] = "once"
        query.edit_message_text("🔔 Напомнить один раз\nНапиши имя задачи:")
    
    elif data == "reminder_custom":
        context.user_data['reminder_type'] = "custom"
        query.edit_message_text("Введи интервал в минутах:")
    
    elif data == "reminder_time":
        context.user_data['reminder_type'] = "specific_time"
        query.edit_message_text("Введи время (ЧЧ:ММ):")
    
    elif data == "reminder_none":
        context.user_data['reminder_type'] = "none"
        query.edit_message_text("🚫 Без напоминаний\nНапиши имя задачи:")

def handle_interval_input(update, context):
    if context.user_data.get('reminder_type') == 'custom':
        try:
            interval = int(update.message.text)
            if interval > 0:
                context.user_data['reminder_interval'] = interval
                update.message.reply_text(f"✅ Напоминания каждые {interval} мин\nНапиши имя задачи:")
            else:
                update.message.reply_text("Введи положительное число:")
        except ValueError:
            update.message.reply_text("Введи число (минуты):")
    
    elif context.user_data.get('reminder_type') == 'specific_time':
        time_pattern = r'^(\d{1,2}):(\d{2})$'
        time_match = re.match(time_pattern, update.message.text)
        
        if time_match:
            hours, minutes = int(time_match.group(1)), int(time_match.group(2))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                context.user_data['reminder_time'] = f"{hours:02d}:{minutes:02d}"
                update.message.reply_text(f"✅ Напоминание в {hours:02d}:{minutes:02d}\nНапиши имя задачи:")
            else:
                update.message.reply_text("Неверное время! Попробуй еще раз:")
        else:
            update.message.reply_text("Используй формат ЧЧ:ММ:")

def handle_task_text(update, context):
    if 'reminder_type' not in context.user_data:
        update.message.reply_text("Сначала выбери тип напоминания: /addtask")
        return
    
    task_text = update.message.text
    user_id = update.effective_user.id
    reminder_type = context.user_data['reminder_type']
    reminder_interval = context.user_data.get('reminder_interval', 0)
    reminder_time = context.user_data.get('reminder_time', "")
    
    add_task(user_id, task_text, reminder_type, reminder_interval, reminder_time)
    
    # Формируем сообщение о добавлении
    if reminder_type == "once":
        reminder_info = "🔔 Один раз"
    elif reminder_type == "custom":
        reminder_info = f"🔄 Каждые {reminder_interval} мин"
    elif reminder_type == "specific_time":
        reminder_info = f"🕐 В {reminder_time}"
    else:
        reminder_info = "🚫 Без напоминаний"
    
    context.user_data.clear()
    update.message.reply_text(f"✅ Задача добавлена!\n{task_text}\n{reminder_info}")

def my_tasks_command(update, context):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        update.message.reply_text("📝 Нет активных задач!")
        return
    
    tasks_text = "📋 Твои задачи:\n\n"
    for i, task in enumerate(tasks, 1):
        task_id, task_text, reminder_type, interval, specific_time, completed = task
        
        if reminder_type == "once":
            reminder_info = "🔔 Один раз"
        elif reminder_type == "custom":
            reminder_info = f"🔄 Каждые {interval} мин"
        elif reminder_type == "specific_time":
            reminder_info = f"🕐 В {specific_time}"
        else:
            reminder_info = "🚫 Без напоминаний"
        
        tasks_text += f"{i}. {task_text}\n   {reminder_info}\n\n"
    
    update.message.reply_text(tasks_text)

def complete_task_command(update, context):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        update.message.reply_text("Нет задач для отметки!")
        return
    
    keyboard = []
    for task in tasks:
        task_id, task_text, _, _, _, _ = task
        keyboard.append([InlineKeyboardButton(task_text, callback_data=f"complete_{task_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выбери задачу:", reply_markup=reply_markup)

def complete_button_handler(update, context):
    query = update.callback_query
    query.answer()
    
    if query.data.startswith("complete_"):
        task_id = int(query.data.split("_")[1])
        mark_task_completed(task_id)
        query.edit_message_text("✅ Задача выполнена!")

def send_reminders(context):
    tasks = get_tasks_for_reminder()
    
    for task in tasks:
        task_id, user_id, task_text = task
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"🔔 Напоминание:\n{task_text}\n\n/complete - отметить выполненной"
            )
            logger.info(f"Напоминание отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")

def error_handler(update, context):
    logger.error(f"Ошибка: {context.error}")

def main():
    init_db()
    
    # Простой и рабочий синтаксис для версии 13.15
    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    job_queue = updater.job_queue
    
    # Обработчики
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("addtask", add_task_command))
    dispatcher.add_handler(CommandHandler("mytasks", my_tasks_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("complete", complete_task_command))
    
    dispatcher.add_handler(CallbackQueryHandler(button_handler, pattern="^reminder_"))
    dispatcher.add_handler(CallbackQueryHandler(complete_button_handler, pattern="^complete_"))
    
    dispatcher.add_handler(MessageHandler(Filters.text & Filters.regex(r'^\d+$') & ~Filters.command, handle_interval_input))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_task_text))
    
    dispatcher.add_error_handler(error_handler)
    
    # Напоминания
    if job_queue:
        job_queue.run_repeating(send_reminders, interval=60, first=60)
        logger.info("Система напоминаний запущена")
    
    logger.info("Бот запущен на Railway")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
