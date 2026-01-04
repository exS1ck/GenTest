import os
import subprocess
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
from threading import Thread

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем переменные окружения
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # Например: https://your-app.onrender.com
PORT = int(os.getenv('PORT', 10000))

# Создаём Flask приложение
app = Flask(__name__)

# Создаём приложение Telegram
application = Application.builder().token(TOKEN).build()

# Глобальная переменная для event loop
main_loop = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        'Привет! Отправь мне txt файл с данными 23andMe, '
        'и я обработаю его через PLINK.'
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик получения документа"""
    
    # Проверяем, что это txt файл
    file_name = update.message.document.file_name
    if not file_name.endswith('.txt'):
        await update.message.reply_text('Пожалуйста, отправьте txt файл.')
        return
    
    await update.message.reply_text('📥 Файл получен, начинаю обработку...')
    
    try:
        # Получаем файл
        file = await update.message.document.get_file()
        
        # Создаём временную директорию если её нет
        os.makedirs('/tmp/plink_data', exist_ok=True)
        
        # Сохраняем файл
        input_path = f'/tmp/plink_data/input_{update.message.message_id}.txt'
        output_prefix = f'/tmp/plink_data/output_{update.message.message_id}'
        
        await file.download_to_drive(input_path)
        logger.info(f'Файл сохранён: {input_path}')
        
        await update.message.reply_text('⚙️ Запускаю PLINK...')
        
        # Запускаем PLINK
        result = subprocess.run(
            ['./plink', '--23file', input_path, '--make-bed', '--out', output_prefix],
            capture_output=True,
            text=True,
            timeout=300  # 5 минут таймаут
        )
        
        logger.info(f'PLINK stdout: {result.stdout}')
        logger.info(f'PLINK stderr: {result.stderr}')
        
        if result.returncode != 0:
            await update.message.reply_text(f'❌ Ошибка PLINK:\n{result.stderr[:500]}')
            return
        
        # Читаем первые 10 строк из .bim файла
        bim_file = f'{output_prefix}.bim'
        
        if not os.path.exists(bim_file):
            await update.message.reply_text('❌ Файл .bim не был создан')
            return
        
        with open(bim_file, 'r') as f:
            lines = []
            for i in range(10):
                line = f.readline()
                if not line:
                    break
                lines.append(line)
        
        if not lines:
            await update.message.reply_text('❌ Файл .bim пустой')
            return
        
        response = "✅ Обработка завершена!\n\nПервые 10 строк из .bim файла:\n\n```\n" + "".join(lines) + "```"
        await update.message.reply_text(response, parse_mode='Markdown')
        
        logger.info(f'Результат отправлен пользователю {update.message.from_user.id}')
        
    except subprocess.TimeoutExpired:
        await update.message.reply_text('❌ Превышено время ожидания (5 минут)')
    except Exception as e:
        logger.error(f'Ошибка обработки: {str(e)}', exc_info=True)
        await update.message.reply_text(f'❌ Произошла ошибка: {str(e)}')
    finally:
        # Очищаем временные файлы
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
            for ext in ['.bed', '.bim', '.fam', '.log', '.nosex']:
                file_path = f'{output_prefix}{ext}'
                if os.path.exists(file_path):
                    os.remove(file_path)
            logger.info('Временные файлы удалены')
        except Exception as e:
            logger.error(f'Ошибка удаления файлов: {str(e)}')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f'Update {update} caused error {context.error}')

# Регистрируем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
application.add_error_handler(error_handler)

@app.route('/')
def index():
    """Главная страница для проверки работы"""
    return 'Bot is running!'

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    """Обработчик вебхука от Telegram"""
    try:
        json_data = request.get_json()
        update = Update.de_json(json_data, application.bot)
        
        # Отправляем update в основной event loop
        asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            main_loop
        )
        
        return 'OK'
    except Exception as e:
        logger.error(f'Ошибка обработки webhook: {str(e)}', exc_info=True)
        return 'Error', 500

def run_flask():
    """Запуск Flask в отдельном потоке"""
    app.run(host='0.0.0.0', port=PORT)

async def main():
    """Основная функция запуска бота"""
    global main_loop
    main_loop = asyncio.get_event_loop()
    
    # Инициализируем приложение
    await application.initialize()
    
    # Устанавливаем webhook
    webhook_url = f'{WEBHOOK_URL}/{TOKEN}'
    await application.bot.set_webhook(url=webhook_url)
    logger.info(f'Webhook установлен: {webhook_url}')
    
    # Запускаем приложение
    await application.start()
    
    # Запускаем Flask в отдельном потоке
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f'Flask запущен на порту {PORT}')
    
    # Держим приложение запущенным
    import signal
    
    stop_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        stop_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await stop_event.wait()
    
    # Остановка приложения
    await application.stop()
    await application.shutdown()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError('TELEGRAM_BOT_TOKEN не установлен')
    if not WEBHOOK_URL:
        raise ValueError('WEBHOOK_URL не установлен')
    
    asyncio.run(main())