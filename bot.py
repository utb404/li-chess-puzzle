"""
Основной модуль Telegram-бота для отправки шахматных задач.
"""
import os
import json
import logging
import asyncio
from typing import Optional, Set, Dict
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
import schedule
import threading

from lichess_api import LichessAPI

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные
lichess_api = LichessAPI()
# Храним текущую задачу для каждого чата отдельно
current_puzzles: Dict[int, dict] = {}
bot_application: Optional[Application] = None

# Файл для хранения подписок
SUBSCRIPTIONS_FILE = Path("subscriptions.json")


def load_subscriptions() -> Set[int]:
    """Загружает список подписанных чатов из файла."""
    if SUBSCRIPTIONS_FILE.exists():
        try:
            with open(SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('chats', []))
        except Exception as e:
            logger.error("Ошибка при загрузке подписок: %s", e)
            return set()
    return set()


def save_subscriptions(subscriptions: Set[int]) -> None:
    """Сохраняет список подписанных чатов в файл."""
    try:
        with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'chats': list(subscriptions)}, f, indent=2)
    except Exception as e:
        logger.error("Ошибка при сохранении подписок: %s", e)


# Загружаем подписки при старте
subscribed_chats: Set[int] = load_subscriptions()


async def send_puzzle(chat_id: int, context: Optional[ContextTypes.DEFAULT_TYPE] = None, random_puzzle: bool = False) -> bool:
    """
    Отправляет задачу дня или случайную задачу в указанный чат.
    
    Args:
        chat_id: ID чата для отправки
        context: Контекст бота (опционально)
        random_puzzle: Если True, отправляет случайную задачу, иначе задачу дня
        
    Returns:
        True если успешно, False в противном случае.
    """
    global current_puzzles
    
    try:
        # Получаем задачу дня или случайную задачу
        if random_puzzle:
            puzzle_data = lichess_api.get_random_puzzle()
            if not puzzle_data:
                logger.error("Не удалось получить случайную задачу")
                return False
        else:
            puzzle_data = lichess_api.get_daily_puzzle()
            if not puzzle_data:
                logger.error("Не удалось получить задачу дня")
                return False
        
        # Сохраняем задачу для этого чата
        current_puzzles[chat_id] = puzzle_data
        
        # Получаем FEN позицию
        fen = lichess_api.get_fen_from_puzzle(puzzle_data)
        
        # Формируем описание с решением под спойлером (передаем FEN для определения хода)
        description = lichess_api.format_puzzle_description(puzzle_data, fen, include_solution=True)
        
        # Получаем изображение доски (с координатами)
        board_image = lichess_api.download_board_image(fen)
        
        # Логируем для отладки
        if not board_image:
            logger.warning("Не удалось сгенерировать изображение доски для FEN: %s", fen)
        
        # Отправляем сообщение
        bot_to_use = context.bot if context else (bot_application.bot if bot_application else None)
        
        if not bot_to_use:
            logger.error("Не удалось получить объект бота для отправки")
            return False
        
        if board_image:
            try:
                board_image.seek(0)
                # Проверяем, что изображение действительно загружено
                image_data = board_image.read()
                if len(image_data) > 0:
                    board_image.seek(0)
                    # Используем InputFile для правильной отправки
                    from telegram import InputFile
                    photo_file = InputFile(board_image, filename='board.png')
                    
                    # Пробуем отправить все в caption с тегом <tg-spoiler>
                    # Если спойлеры не поддерживаются в caption, отправляем решение отдельно
                    try:
                        # Отправляем изображение с полным описанием включая спойлер
                        sent_message = await bot_to_use.send_photo(
                            chat_id=chat_id,
                            photo=photo_file,
                            caption=description,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        # Если не получилось (возможно, спойлеры не поддерживаются в caption)
                        logger.warning("Не удалось отправить с решением в caption: %s", e)
                        # Разделяем описание и решение
                        description_parts = description.split('<tg-spoiler>')
                        if len(description_parts) > 1:
                            caption_text = description_parts[0].rstrip()
                            solution_text = description_parts[1].replace('</tg-spoiler>', '')
                        else:
                            caption_text = description
                            solution_text = None
                        
                        # Отправляем изображение с описанием
                        sent_message = await bot_to_use.send_photo(
                            chat_id=chat_id,
                            photo=photo_file,
                            caption=caption_text,
                            parse_mode=ParseMode.HTML
                        )
                        
                        # Отправляем решение сразу после (без задержки, чтобы выглядело как одно сообщение)
                        if solution_text:
                            try:
                                # Используем MarkdownV2 для спойлера
                                escaped_solution = solution_text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]').replace('(', '\\(').replace(')', '\\)').replace('~', '\\~').replace('`', '\\`').replace('>', '\\>').replace('#', '\\#').replace('+', '\\+').replace('-', '\\-').replace('=', '\\=').replace('|', '\\|').replace('{', '\\{').replace('}', '\\}').replace('.', '\\.').replace('!', '\\!')
                                spoiler_msg = f"💡 <b>Решение:</b>\n\n||{escaped_solution}||"
                                await bot_to_use.send_message(
                                    chat_id=chat_id,
                                    text=spoiler_msg,
                                    parse_mode=ParseMode.MARKDOWN_V2
                                )
                            except Exception as e2:
                                logger.warning("Не удалось отправить решение со спойлером: %s", e2)
                                await bot_to_use.send_message(
                                    chat_id=chat_id,
                                    text=f"💡 <b>Решение:</b>\n\n{solution_text}",
                                    parse_mode=ParseMode.HTML
                                )
                else:
                    raise ValueError("Изображение пустое")
            except Exception as e:
                logger.error("Ошибка при отправке изображения: %s", e)
                import traceback
                traceback.print_exc()
                # Fallback: отправляем только текст
                await bot_to_use.send_message(
                    chat_id=chat_id,
                    text=description,
                    parse_mode=ParseMode.HTML
                )
        else:
            # Если изображение не сгенерировалось, отправляем только текст
            logger.warning("Не удалось сгенерировать изображение, отправляем только текст")
            await bot_to_use.send_message(
                chat_id=chat_id,
                text=description,
                parse_mode=ParseMode.HTML
            )
        
        logger.info("Задача дня успешно отправлена в чат %s", chat_id)
        return True
        
    except Exception as e:
        logger.error("Ошибка при отправке задачи: %s", e)
        return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    chat_id = update.effective_chat.id
    is_subscribed = chat_id in subscribed_chats
    
    message = (
        "Привет! Я бот для шахматных задач с lichess.org.\n\n"
        "Доступные команды:\n"
        "/puzzle - Получить задачу дня\n"
        "/solution - Показать решение текущей задачи\n"
        "/subscribe - Подписаться на ежедневные задачи\n"
        "/unsubscribe - Отписаться от ежедневных задач\n"
    )
    
    if is_subscribed:
        message += "\n✅ Вы подписаны на ежедневные задачи"
    else:
        message += "\n❌ Вы не подписаны на ежедневные задачи"
    
    await update.message.reply_text(message)


async def puzzle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /puzzle."""
    chat_id = update.effective_chat.id
    await send_puzzle(chat_id, context, random_puzzle=False)


async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /random."""
    chat_id = update.effective_chat.id
    await send_puzzle(chat_id, context, random_puzzle=True)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /subscribe."""
    global subscribed_chats
    
    chat_id = update.effective_chat.id
    
    if chat_id in subscribed_chats:
        await update.message.reply_text(
            "Вы уже подписаны на ежедневные задачи! ✅"
        )
    else:
        subscribed_chats.add(chat_id)
        save_subscriptions(subscribed_chats)
        await update.message.reply_text(
            "Вы успешно подписались на ежедневные задачи! ✅\n"
            "Теперь вы будете получать задачу дня каждый день по расписанию."
        )
        logger.info("Новая подписка: чат %s", chat_id)


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /unsubscribe."""
    global subscribed_chats
    
    chat_id = update.effective_chat.id
    
    if chat_id not in subscribed_chats:
        await update.message.reply_text(
            "Вы не подписаны на ежедневные задачи."
        )
    else:
        subscribed_chats.discard(chat_id)
        save_subscriptions(subscribed_chats)
        await update.message.reply_text(
            "Вы отписались от ежедневных задач. ❌\n"
            "Вы по-прежнему можете получать задачи командой /puzzle"
        )
        logger.info("Отписка: чат %s", chat_id)


async def solution_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /solution."""
    global current_puzzles
    
    chat_id = update.effective_chat.id
    current_puzzle = current_puzzles.get(chat_id)
    
    if not current_puzzle:
        await update.message.reply_text(
            "Сначала получите задачу командой /puzzle"
        )
        return
    
    try:
        solution_text = lichess_api.format_solution(current_puzzle)
        
        # Отправляем решение под спойлером
        # В Telegram спойлеры создаются через ||текст|| в MarkdownV2
        # Но нужно экранировать специальные символы
        try:
            # Экранируем специальные символы для MarkdownV2
            escaped_text = solution_text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]').replace('(', '\\(').replace(')', '\\)').replace('~', '\\~').replace('`', '\\`').replace('>', '\\>').replace('#', '\\#').replace('+', '\\+').replace('-', '\\-').replace('=', '\\=').replace('|', '\\|').replace('{', '\\{').replace('}', '\\}').replace('.', '\\.').replace('!', '\\!')
            spoiler_text = f"||{escaped_text}||"
            
            await update.message.reply_text(
                spoiler_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.warning("Не удалось отправить со спойлером, отправляем без: %s", e)
            # Fallback: отправляем без спойлера
            await update.message.reply_text(
                solution_text,
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error("Ошибка при отправке решения: %s", e)
        await update.message.reply_text(
            "Произошла ошибка при получении решения."
        )


def run_scheduler():
    """Запускает планировщик для автоматической отправки задач."""
    schedule_time = os.getenv('SCHEDULE_TIME', '09:00')
    
    def job():
        """Задача для планировщика."""
        global subscribed_chats
        
        # Перезагружаем подписки на случай изменений
        subscribed_chats = load_subscriptions()
        
        if not subscribed_chats:
            logger.info("Нет подписанных чатов для отправки")
            return
        
        logger.info("Запуск запланированной отправки задачи в %s для %d чатов", 
                    schedule_time, len(subscribed_chats))
        
        try:
            # Создаем новый event loop для асинхронной задачи
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Отправляем задачу во все подписанные чаты
            async def send_to_all():
                tasks = [send_puzzle(chat_id) for chat_id in subscribed_chats]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                success_count = sum(1 for r in results if r is True)
                logger.info("Отправлено успешно: %d из %d", success_count, len(subscribed_chats))
            
            loop.run_until_complete(send_to_all())
            loop.close()
        except Exception as e:
            logger.error("Ошибка при выполнении запланированной задачи: %s", e)
    
    # Настраиваем расписание
    schedule.every().day.at(schedule_time).do(job)
    logger.info("Расписание установлено: ежедневно в %s", schedule_time)
    
    # Запускаем планировщик в отдельном потоке
    while True:
        schedule.run_pending()
        threading.Event().wait(60)  # Проверяем каждую минуту


def main() -> None:
    """Основная функция запуска бота."""
    global bot_application
    
    # Получаем токен бота
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
        return
    
    # Создаем приложение бота
    bot_application = Application.builder().token(token).build()
    
    # Регистрируем обработчики команд
    bot_application.add_handler(CommandHandler("start", start_command))
    bot_application.add_handler(CommandHandler("puzzle", puzzle_command))
    bot_application.add_handler(CommandHandler("random", random_command))
    bot_application.add_handler(CommandHandler("solution", solution_command))
    bot_application.add_handler(CommandHandler("subscribe", subscribe_command))
    bot_application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    
    # Запускаем планировщик в отдельном потоке
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Запускаем бота
    logger.info("Бот запущен")
    bot_application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

