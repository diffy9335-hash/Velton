"""VELTON Telegram launcher. Run separately from the API service."""
import os, asyncio
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

load_dotenv(Path(__file__).parent / '.env')
router = Router()

@router.message(CommandStart())
async def start(message: Message):
    url = os.environ.get('APP_URL','').strip()
    if not url.startswith('https://'):
        await message.answer('VELTON: адрес мини-приложения пока не настроен. Администратору нужно указать APP_URL с HTTPS.')
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Открыть VELTON', web_app=WebAppInfo(url=url))
    ]])
    await message.answer(
        'VELTON — твоя футбольная история.\n\n'
        'Выбирай карьеру футболиста, тренера, судьи, агента или управляй собственным клубом. '
        'У тебя 5 слотов сохранения, один общий профиль и достижения.\n\n'
        'Нажми кнопку, чтобы начать.', reply_markup=keyboard)

@router.message(Command('help'))
async def help_message(message: Message):
    await message.answer('Команда /start открывает мини-приложение VELTON. Прогресс привязан к твоему аккаунту Telegram.')

async def main():
    token = os.environ.get('BOT_TOKEN','').strip()
    if not token:
        raise RuntimeError('Add BOT_TOKEN to .env before starting bot')
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
