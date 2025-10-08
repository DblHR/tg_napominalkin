import os
import logging
import sqlite3
import re
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

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

# Глобальная переменная для хранения задачи напоминаний
reminder_task = None

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

# Система напоминаний без JobQueue
async def send_reminders(application):
    while True:
        try:
            tasks = get_tasks_for_reminder()
            
            for task in tasks:
                task_id, user_id, task_text = task
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=f"🔔 **Напоминание:**\n{task_text}\n\n/complete - отметить выполненной"
                    )
                    logger.info(f"Напоминание отправлено пользователю {user_id}")
                except Exception as e:
                    logger.error(f"Не удалось отправить напоминание: {e}")
            
            # Ждем 60 секунд до следующей проверки
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Ошибка в системе напоминаний: {e}")
            await asyncio.sleep(60)

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"пиривета {user.first_name}! 👋\n\n"
        "Я бот Дыни для напоминалок\n\n"
        "Команды:\n"
        "/addtask - Добавить задачу\n"
        "/mytasks - Мои задачи\n"
        "/complete - Отметить выполненной\n"
        "/help - Помощь"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(help_text)

async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔔 Один раз", callback_data="reminder_once")],
        [InlineKeyboardButton("🔄 Повторять", callback_data="reminder_custom")],
        [InlineKeyboardButton("🕐 Время", callback_data="reminder_time")],
        [InlineKeyboardButton("🚫 Без напоминаний", callback_data="reminder_none")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери тип напоминания:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "reminder_once":
        context.user_data['reminder_type'] = "once"
        await query.edit_message_text("🔔 Напомнить один раз\nНапиши имя задачи:")
    
    elif data == "reminder_custom":
        context.user_data['reminder_type'] = "custom"
        await query.edit_message_text("Введи интервал в минутах:")
    
    elif data == "reminder_time":
        context.user_data['reminder_type'] = "specific_time"
        await query.edit_message_text("Введи время (ЧЧ:ММ):")
    
    elif data == "reminder_none":
        context.user_data['reminder_type'] = "none"
        await query.edit_message_text("🚫 Без напоминаний\nНапиши имя задачи:")

async def handle_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('reminder_type') == 'custom':
        try:
            interval = int(update.message.text)
            if interval > 0:
                context.user_data['reminder_interval'] = interval
                await update.message.reply_text(f"✅ Напоминания каждые {interval} мин\nНапиши имя задачи:")
            else:
                await update.message.reply_text("Введи положительное число:")
        except ValueError:
            await update.message.reply_text("Введи число (минуты):")
    
    elif context.user_data.get('reminder_type') == 'specific_time':
        time_pattern = r'^(\d{1,2}):(\d{2})$'
        time_match = re.match(time_pattern, update.message.text)
        
        if time_match:
            hours, minutes = int(time_match.group(1)), int(time_match.group(2))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                context.user_data['reminder_time'] = f"{hours:02d}:{minutes:02d}"
                await update.message.reply_text(f"✅ Напоминание в {hours:02d}:{minutes:02d}\nНапиши имя задачи:")
            else:
                await update.message.reply_text("Неверное время! Попробуй еще раз:")
        else:
            await update.message.reply_text("Используй формат ЧЧ:ММ:")

async def handle_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'reminder_type' not in context.user_data:
        await update.message.reply_text("Сначала выбери тип напоминания: /addtask")
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
    await update.message.reply_text(f"✅ Задача добавлена!\n{task_text}\n{reminder_info}")

async def my_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        await update.message.reply_text("📝 Нет активных задач!")
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
    
    await update.message.reply_text(tasks_text)

async def complete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        await update.message.reply_text("Нет задач для отметки!")
        return
    
    keyboard = []
    for task in tasks:
        task_id, task_text, _, _, _, _ = task
        keyboard.append([InlineKeyboardButton(task_text, callback_data=f"complete_{task_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери задачу:", reply_markup=reply_markup)

async def complete_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("complete_"):
        task_id = int(query.data.split("_")[1])
        mark_task_completed(task_id)
        await query.edit_message_text("✅ Задача выполнена!")

async def main():
    # Инициализация базы данных
    init_db()
    
    try:
        # Создание приложения без JobQueue
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("addtask", add_task_command))
        application.add_handler(CommandHandler("mytasks", my_tasks_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("complete", complete_task_command))
        
        # Обработчики кнопок
        application.add_handler(CallbackQueryHandler(button_handler, pattern="^reminder_"))
        application.add_handler(CallbackQueryHandler(complete_button_handler, pattern="^complete_"))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+$') & ~filters.COMMAND, handle_interval_input))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_text))
        
        # Запускаем систему напоминаний в отдельной задаче
        asyncio.create_task(send_reminders(application))
        logger.info("✅ Система напоминаний запущена!")
        
        # Запуск бота
        logger.info("🤖 Бот запускается на Railway...")
        await application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
