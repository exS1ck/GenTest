import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Основное меню с кнопками
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📊 Статистика"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("📚 Каталог"), KeyboardButton("🔔 Уведомления")],
        [KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот с заглушками.\n\nВыбери действие:",
        reply_markup=get_main_keyboard()
    )

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    responses = {
        "📊 Статистика": "📊 Раздел статистики в разработке...",
        "⚙️ Настройки": "⚙️ Раздел настроек в разработке...",
        "📚 Каталог": "📚 Каталог в разработке...",
        "🔔 Уведомления": "🔔 Уведомления в разработке...",
        "ℹ️ Помощь": "ℹ️ Справка:\n\nВсе разделы находятся в разработке.\nИспользуйте /start для возврата в главное меню."
    }
    
    response = responses.get(text, "Неизвестная команда. Используйте /start")
    await update.message.reply_text(response, reply_markup=get_main_keyboard())

def main():
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("BOT_TOKEN не установлен в переменных окружения")
    
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()