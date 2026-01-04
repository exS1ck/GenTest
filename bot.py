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
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 10000))

# Создаём Flask приложение
app = Flask(__name__)

# Создаём приложение Telegram
application = Application.builder().token(TOKEN).build()

# Глобальные переменные
main_loop = None
task_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        'Привет! Отправь мне txt файл с данными 23andMe, '
        'и я обработаю его через PLINK и AdmixTools.'
    )

async def run_plink(input_path: str, output_prefix: str) -> bool:
    """Запуск PLINK"""
    result = subprocess.run(
        ['plink', '--23file', input_path, '--make-bed', '--out', output_prefix],
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        logger.error(f'PLINK error: {result.stderr}')
        return False
    
    return True

async def run_convertf(bed_prefix: str, eigen_prefix: str, par_file: str) -> bool:
    """Запуск convertf из AdmixTools"""
    # Создаём файл convertf.par
    par_content = f"""genotypename:    {bed_prefix}.bed
snpname:         {bed_prefix}.bim
indivname:       {bed_prefix}.fam
outputformat:    EIGENSTRAT
genotypeoutname: {eigen_prefix}.geno
snpoutname:      {eigen_prefix}.snp
indivoutname:    {eigen_prefix}.ind
"""
    
    with open(par_file, 'w') as f:
        f.write(par_content)
    
    # Запускаем convertf
    result = subprocess.run(
        ['/AdmixTools/src/convertf', '-p', par_file],
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        logger.error(f'convertf error: {result.stderr}')
        return False
    
    return True

async def process_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка файла через весь пайплайн"""
    input_path = None
    output_prefix = None
    eigen_prefix = None
    par_file = None
    
    try:
        await update.message.reply_text('⚙️ Начинаю обработку...')
        
        # Получаем файл
        file = await update.message.document.get_file()
        
        # Создаём временную директорию
        os.makedirs('/tmp/plink_data', exist_ok=True)
        
        # Определяем пути
        msg_id = update.message.message_id
        input_path = f'/tmp/plink_data/input_{msg_id}.txt'
        output_prefix = f'/tmp/plink_data/output_{msg_id}'
        eigen_prefix = f'/tmp/plink_data/dataeigen_{msg_id}'
        par_file = f'/tmp/plink_data/convertf_{msg_id}.par'
        
        # Скачиваем файл
        await file.download_to_drive(input_path)
        logger.info(f'Файл сохранён: {input_path}')
        
        # Шаг 1: PLINK
        await update.message.reply_text('⚙️ Запускаю PLINK...')
        
        if not await run_plink(input_path, output_prefix):
            await update.message.reply_text('❌ Ошибка при выполнении PLINK')
            return
        
        # Проверяем создание файлов
        if not os.path.exists(f'{output_prefix}.bim'):
            await update.message.reply_text('❌ PLINK не создал выходные файлы')
            return
        
        # Шаг 2: AdmixTools convertf
        await update.message.reply_text('✅ PLINK завершён, запускаю AdmixTools...')
        
        if not await run_convertf(output_prefix, eigen_prefix, par_file):
            await update.message.reply_text('❌ Ошибка при выполнении AdmixTools')
            return
        
        # Проверяем создание SNP файла
        snp_file = f'{eigen_prefix}.snp'
        if not os.path.exists(snp_file):
            await update.message.reply_text('❌ AdmixTools не создал файл .snp')
            return
        
        # Читаем первые 10 строк
        with open(snp_file, 'r') as f:
            lines = []
            for i in range(10):
                line = f.readline()
                if not line:
                    break
                lines.append(line)
        
        if not lines:
            await update.message.reply_text('❌ Файл dataeigen.snp пустой')
            return
        
        # Отправляем результат
        response = "✅ Обработка завершена!\n\nПервые 10 строк файла dataeigen.snp:\n\n```\n" + "".join(lines) + "```"
        await update.message.reply_text(response, parse_mode='Markdown')
        
        logger.info(f'Обработка завершена для пользователя {update.message.from_user.id}')
        
    except subprocess.TimeoutExpired:
        await update.message.reply_text('❌ Превышено время ожидания (5 минут)')
    except Exception as e:
        logger.error(f'Ошибка обработки: {str(e)}', exc_info=True)
        await update.message.reply_text(f'❌ Произошла ошибка: {str(e)}')
    finally:
        # Очистка всех временных файлов
        try:
            files_to_remove = []
            
            if input_path:
                files_to_remove.append(input_path)
            
            if output_prefix:
                for ext in ['.bed', '.bim', '.fam', '.log', '.nosex']:
                    files_to_remove.append(f'{output_prefix}{ext}')
            
            if eigen_prefix:
                for ext in ['.geno', '.snp', '.ind']:
                    files_to_remove.append(f'{eigen_prefix}{ext}')
            
            if par_file:
                files_to_remove.append(par_file)
            
            for file_path in files_to_remove:
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            logger.info('Временные файлы удалены')
        except Exception as e:
            logger.error(f'Ошибка удаления файлов: {str(e)}')

async def process_queue():
    """Фоновая обработка очереди задач"""
    while True:
        update, context = await task_queue.get()
        try:
            async with processing_lock:
                await process_file(update, context)
        except Exception as e:
            logger.error(f'Ошибка в process_queue: {str(e)}', exc_info=True)
        finally:
            task_queue.task_done()

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик получения документа"""
    
    # Проверяем, что это txt файл
    file_name = update.message.document.file_name
    if not file_name.endswith('.txt'):
        await update.message.reply_text('Пожалуйста, отправьте txt файл.')
        return
    
    # Добавляем в очередь
    queue_position = task_queue.qsize() + 1
    
    if queue_position > 1:
        await update.message.reply_text(
            f'📥 Файл получен и добавлен в очередь.\n'
            f'Ваша позиция: {queue_position}'
        )
    else:
        await update.message.reply_text('📥 Файл получен.')
    
    await task_queue.put((update, context))

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
    
    # Запускаем обработчик очереди в фоне
    asyncio.create_task(process_queue())
    logger.info('Обработчик очереди запущен')
    
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