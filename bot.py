import os
import logging
import sqlite3
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Настройки - токен ТОЛЬКО из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в переменных окружения!")

DB_NAME = "tasks.db"
PORT = int(os.environ.get('PORT', 8443))

# Остальной код без изменений...

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
            # Проверяем конкретное время
            if current_time == specific_time:
                # Проверяем, не отправляли ли уже сегодня
                if last_reminder != current_date:
                    tasks_to_remind.append((task_id, user_id, task_text))
                    cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                                 (current_date, task_id))
        
        elif reminder_type == 'custom':
            # Периодические напоминания
            if last_reminder:
                try:
                    last_reminder_time = datetime.strptime(last_reminder, '%Y-%m-%d %H:%M:%S')
                    time_diff = (now - last_reminder_time).total_seconds() / 60
                    
                    if time_diff >= interval:
                        tasks_to_remind.append((task_id, user_id, task_text))
                        cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                                     (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
                except ValueError:
                    # Если формат даты неправильный, сбрасываем
                    tasks_to_remind.append((task_id, user_id, task_text))
                    cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                                 (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
            else:
                # Первое напоминание - ждём полный интервал
                cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                             (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
        
        elif reminder_type == 'once':
            # Напоминание один раз
            if not last_reminder:
                tasks_to_remind.append((task_id, user_id, task_text))
                cursor.execute('UPDATE tasks SET last_reminder_date = ? WHERE id = ?', 
                             (now.strftime('%Y-%m-%d %H:%M:%S'), task_id))
    
    conn.commit()
    conn.close()
    return tasks_to_remind

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"пиривета {user.first_name}! 👋\n\n"
        "Я бот Дыни для напоминалок\n\n"
        "📋 **Тут можно:**\n"
        "/addtask - Добавить новую задачу\n"
        "/mytasks - Показать мои задачи\n"
        "/complete - Отметить задачу выполненной\n"
        "/help - Помощь\n\n"
        "⏰ **Форматы напоминаний:**\n"
        "• Число (5, 60, 120) - периодические напоминания в минутах\n"
        "• Время (10:00, 14:30) - напоминание в конкретное время (по мск)"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📋 **Доступные команды:**

/addtask - Добавить новую задачу
/mytasks - Показать текущие задачи
/complete - Отметить задачу выполненной
/help - Показать эту справку

⏰ **Типы напоминаний:**

🔔 **Один раз** - напомнить один раз и больше не повторять

🔄 **Повторять с интервалом**:
• Введи число - интервал в минутах
• Пример: 60 - каждый час, 1440 - раз в день

🕐 **Конкретное время**:
• Введи время в формате ЧЧ:ММ
• Пример: 10:00, 14:30, 09:15
• Напоминание приходит каждый день в указанное время по мск

🚫 **Без напоминаний** - задача без уведомлений

**Как пользоваться:**
1. Добавь задачу командой /addtask
2. Выбери тип напоминания
3. Введи интервал или время (если нужно)
4. Напиши имя задачи
5. Получай напоминания!
    """
    await update.message.reply_text(help_text)

async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔔 Один раз", callback_data="reminder_once")],
        [InlineKeyboardButton("🔄 Повторять с интервалом", callback_data="reminder_custom")],
        [InlineKeyboardButton("🕐 Конкретное время", callback_data="reminder_time")],
        [InlineKeyboardButton("🚫 Без напоминаний", callback_data="reminder_none")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выбери тип напоминания для новой задачи:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "reminder_once":
        context.user_data['reminder_type'] = "once"
        await query.edit_message_text(
            "Режим: 🔔 Напомнить один раз\n\n"
            "Теперь напиши имя задачи:"
        )
    
    elif data == "reminder_custom":
        context.user_data['reminder_type'] = "custom"
        await query.edit_message_text(
            "Введи интервал напоминаний в МИНУТАХ:\n\n"
            "Примеры:\n"
            "• 60 - напоминать каждый час\n"
            "• 180 - каждые 3 часа\n" 
            "• 1440 - раз в день\n"
            "• 30 - каждые 30 минут"
        )
    
    elif data == "reminder_time":
        context.user_data['reminder_type'] = "specific_time"
        await query.edit_message_text(
            "Введи время напоминания в формате ЧЧ:ММ:\n\n"
            "Примеры:\n"
            "• 10:00 - в 10 утра\n"
            "• 14:30 - в 2:30 дня\n"
            "• 09:15 - в 9:15 утра\n"
            "• 18:45 - в 6:45 вечера"
        )
    
    elif data == "reminder_none":
        context.user_data['reminder_type'] = "none"
        await query.edit_message_text(
            "Режим: 🚫 Без напоминаний\n\n"
            "Теперь напиши имя задачи:"
        )

async def handle_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('reminder_type') == 'custom':
        user_input = update.message.text
        
        try:
            interval = int(user_input)
            if interval <= 0:
                await update.message.reply_text("Интервал должен быть положительным числом. Попробуй еще раз:")
                return
            
            context.user_data['reminder_interval'] = interval
            
            # Преобразуем в читаемый формат
            if interval < 60:
                interval_text = f"каждые {interval} минут"
            elif interval == 60:
                interval_text = "каждый час"
            elif interval % 60 == 0:
                hours = interval // 60
                interval_text = f"каждые {hours} часов"
            else:
                hours = interval // 60
                minutes = interval % 60
                interval_text = f"каждые {hours}ч {minutes}м"
            
            await update.message.reply_text(
                f"✅ Напоминания будут приходить: {interval_text}\n\n"
                "Теперь напиши имя задачи:"
            )
            
        except ValueError:
            await update.message.reply_text("Пожалуйста, введи число (только цифры). Попробуй еще раз:")

    elif context.user_data.get('reminder_type') == 'specific_time':
        user_input = update.message.text
        
        # Проверяем формат времени (10:00, 14:30 и т.д.)
        time_pattern = r'^(\d{1,2}):(\d{2})$'
        time_match = re.match(time_pattern, user_input)
        
        if time_match:
            hours, minutes = int(time_match.group(1)), int(time_match.group(2))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                context.user_data['reminder_time'] = f"{hours:02d}:{minutes:02d}"
                
                await update.message.reply_text(
                    f"✅ Напоминание будет приходить каждый день в {hours:02d}:{minutes:02d}\n\n"
                    "Теперь напиши имя задачи:"
                )
            else:
                await update.message.reply_text("Неверное время! Часы (0-23), минуты (0-59). Попробуй еще раз:")
        else:
            await update.message.reply_text(
                "Неверный формат времени! Используй формат ЧЧ:ММ\n"
                "Примеры: 10:00, 14:30, 09:15\n"
                "Попробуй еще раз:"
            )

async def handle_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'reminder_type' not in context.user_data:
        await update.message.reply_text("Сначала выбери тип напоминания командой /addtask")
        return
    
    task_text = update.message.text
    user_id = update.effective_user.id
    reminder_type = context.user_data['reminder_type']
    reminder_interval = context.user_data.get('reminder_interval', 0)
    reminder_time = context.user_data.get('reminder_time', "")
    
    add_task(user_id, task_text, reminder_type, reminder_interval, reminder_time)
    
    # Формируем сообщение о добавлении
    if reminder_type == "once":
        reminder_info = "🔔 Напомнить один раз"
    elif reminder_type == "custom":
        if reminder_interval < 60:
            reminder_info = f"🔄 Каждые {reminder_interval} минут"
        elif reminder_interval == 60:
            reminder_info = "🔄 Каждый час"
        else:
            hours = reminder_interval // 60
            reminder_info = f"🔄 Каждые {hours} часов"
    elif reminder_type == "specific_time":
        reminder_info = f"🕐 Каждый день в {reminder_time}"
    else:
        reminder_info = "🚫 Без напоминаний"
    
    # Очищаем временные данные
    context.user_data.clear()
    
    await update.message.reply_text(
        f"✅ Задача добавлена!\n\n"
        f"📝 Задача: {task_text}\n"
        f"⏰ Режим: {reminder_info}"
    )

async def my_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        await update.message.reply_text("📝 У тебя пока нет активных задач!")
        return
    
    tasks_text = "📋 **Твои задачи:**\n\n"
    for i, task in enumerate(tasks, 1):
        task_id, task_text, reminder_type, interval, specific_time, completed = task
        
        if reminder_type == "once":
            reminder_info = "🔔 Один раз"
        elif reminder_type == "custom":
            if interval < 60:
                reminder_info = f"🔄 Каждые {interval} мин"
            elif interval == 60:
                reminder_info = "🔄 Каждый час"
            else:
                hours = interval // 60
                reminder_info = f"🔄 Каждые {hours} ч"
        elif reminder_type == "specific_time":
            reminder_info = f"🕐 Каждый день в {specific_time}"
        else:
            reminder_info = "🚫 Без напоминаний"
        
        tasks_text += f"{i}. {task_text}\n   {reminder_info}\n\n"
    
    tasks_text += "Используй /complete чтобы отметить задачу выполненной"
    await update.message.reply_text(tasks_text)

async def complete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    
    if not tasks:
        await update.message.reply_text("У тебя нет активных задач для отметки!")
        return
    
    keyboard = []
    for task in tasks:
        task_id, task_text, _, _, _, _ = task
        keyboard.append([InlineKeyboardButton(task_text, callback_data=f"complete_{task_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери задачу для отметки выполненной:", reply_markup=reply_markup)

async def complete_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("complete_"):
        task_id = int(query.data.split("_")[1])
        mark_task_completed(task_id)
        await query.edit_message_text("✅ Задача отмечена выполненной!")

# Система напоминаний
async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks_for_reminder()
    
    for task in tasks:
        task_id, user_id, task_text = task
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔔 **Напоминание:**\n{task_text}\n\n"
                     f"Используй /complete чтобы отметить выполненной"
            )
            logger.info(f"Напоминание отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить напоминание: {e}")

def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Получаем job_queue
    job_queue = application.job_queue
    
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
    
    # Настройка напоминаний (проверка каждую минуту)
    if job_queue:
        # Первая проверка через 60 секунд, потом каждые 60 секунд
        job_queue.run_repeating(send_reminders, interval=60, first=60)
        logger.info("✅ Система напоминаний запущена! Первая проверка через 60 секунд.")
    else:
        logger.info("⚠️ Job queue не доступен")
    
    # Запуск бота
    logger.info("🤖 Бот запускается на Railway...")
    
    # Для Railway используем webhook вместо polling
    webhook_url = os.environ.get('RAILWAY_STATIC_URL')
    if webhook_url:
        # В продакшене используем webhook
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{webhook_url}/{BOT_TOKEN}"
        )
    else:
        # В разработке используем polling
        application.run_polling()

if __name__ == "__main__":
    main()