import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode

# Используем абсолютные импорты
from app.config import config
from app.utils.logger import logger

class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.dp = Dispatcher(self.bot)
        self.user_sessions: Dict[int, Dict] = {}
        self.running = False
        self.app = None
        
        # Register handlers
        self._register_handlers()
    
    def set_app(self, app):
        """Set app reference"""
        self.app = app
    
    def _register_handlers(self):
        """Register telegram command handlers"""
        
        @self.dp.message_handler(commands=['start'])
        async def start_command(message: types.Message):
            await self._handle_start(message)
        
        @self.dp.message_handler(commands=['status'])
        async def status_command(message: types.Message):
            await self._handle_status(message)
        
        @self.dp.message_handler(commands=['top'])
        async def top_command(message: types.Message):
            await self._handle_top(message)
        
        @self.dp.message_handler(commands=['coins'])
        async def coins_command(message: types.Message):
            await self._handle_coins(message)
        
        @self.dp.message_handler(commands=['settings'])
        async def settings_command(message: types.Message):
            await self._handle_settings(message)
        
        @self.dp.message_handler(commands=['signals'])
        async def signals_command(message: types.Message):
            await self._handle_signals(message)
        
        @self.dp.message_handler(commands=['mute'])
        async def mute_command(message: types.Message):
            await self._handle_mute(message)
    
    async def _handle_start(self, message: types.Message):
        """Handle /start command"""
        welcome = """
🤖 Market Analysis Bot

Я анализирую рыночную активность и отправляю сигналы о потенциально важных ситуациях.

📊 Анализирую:
• Ликвидность в стакане
• Дисбаланс Bid/Ask
• Агрессивные покупки/продажи
• Поглощение
• Open Interest
• Funding Rate
• Объемы
• Технические уровни

Commands:
/status - текущий статус бота
/top - топ активных сигналов
/coins - список отслеживаемых монет
/settings - настройки
/signals - история сигналов
/mute - отключить уведомления

💡 Все сигналы носят информационный характер.
Не являются рекомендацией к действию.
        """
        await message.reply(welcome)
    
    async def _handle_status(self, message: types.Message):
        """Handle /status command"""
        status = f"""
📊 Статус бота

🟢 Активен: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📈 Отслеживаемые монеты: {len(self.app.active_symbols) if self.app and hasattr(self.app, 'active_symbols') else 0}
🔴 Активных сигналов: {len(self.app.signal_engine.active_signals) if self.app and hasattr(self.app, 'signal_engine') else 0}
        """
        await message.reply(status)
    
    async def _handle_top(self, message: types.Message):
        """Handle /top command"""
        if self.app and hasattr(self.app, 'redis'):
            signals = await self.app.redis.get_active_signals()
            if not signals:
                await message.reply("Нет активных сигналов")
                return
            
            lines = ["🔥 TOP MARKET ACTIVITY", "━━━━━━━━━━━━━━━━"]
            for i, (symbol, data) in enumerate(signals.items(), 1):
                if i > 10:
                    break
                lines.append(f"{i}. {symbol} — {data.get('score', 0)}")
            
            await message.reply("\n".join(lines))
        else:
            await message.reply("Бот еще не инициализирован")
    
    async def _handle_coins(self, message: types.Message):
        """Handle /coins command"""
        if self.app and hasattr(self.app, 'active_symbols'):
            symbols = self.app.active_symbols[:20]
            lines = ["🪙 Отслеживаемые монеты:", "━━━━━━━━━━━━━━━━"]
            
            for i, symbol in enumerate(symbols, 1):
                lines.append(f"{i}. {symbol}")
            
            if len(self.app.active_symbols) > 20:
                lines.append(f"\n... и еще {len(self.app.active_symbols) - 20} монет")
            
            await message.reply("\n".join(lines))
        else:
            await message.reply("Нет активных монет")
    
    async def _handle_settings(self, message: types.Message):
        """Handle /settings command"""
        settings = f"""
⚙️ Настройки

Порог сигнала: {config.SIGNAL_THRESHOLD}/100
Cooldown: {config.SIGNAL_COOLDOWN // 60} мин
Монет: {config.TOP_SYMBOLS_COUNT}
Таймфреймы: {', '.join(config.TIMEFRAMES.keys())}

Для изменения параметров обратитесь к администратору.
        """
        await message.reply(settings)
    
    async def _handle_signals(self, message: types.Message):
        """Handle /signals command"""
        if self.app and hasattr(self.app, 'postgres'):
            signals = await self.app.postgres.get_recent_signals(limit=10)
            
            if not signals:
                await message.reply("Нет истории сигналов")
                return
            
            lines = ["📊 Последние сигналы:", "━━━━━━━━━━━━━━━━"]
            for signal in signals:
                lines.append(f"{signal['symbol']} {signal['direction']}")
                lines.append(f"Score: {signal['score']}/100")
                lines.append(f"Time: {signal['created_at'].strftime('%H:%M')}")
                lines.append("")
            
            await message.reply("\n".join(lines))
        else:
            await message.reply("Нет истории сигналов")
    
    async def _handle_mute(self, message: types.Message):
        """Handle /mute command"""
        user_id = message.from_user.id
        
        if user_id in self.user_sessions:
            current = self.user_sessions[user_id].get('muted', False)
            self.user_sessions[user_id]['muted'] = not current
            status = "включены" if not current else "отключены"
        else:
            self.user_sessions[user_id] = {'muted': True}
            status = "отключены"
        
        await message.reply(f"🔕 Уведомления {status}")
    
    async def send_notification(self, message: str, user_ids: List[int] = None):
        """Send notification to users"""
        try:
            if not user_ids:
                user_ids = [admin for admin in config.ADMIN_IDS if not self._is_muted(admin)]
            
            for user_id in user_ids:
                try:
                    await self.bot.send_message(
                        user_id,
                        message,
                        parse_mode="HTML"  # Вместо ParseMode.HTML
                    )
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"Error sending to {user_id}: {e}")
        
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    def _is_muted(self, user_id: int) -> bool:
        """Check if user is muted"""
        return self.user_sessions.get(user_id, {}).get('muted', False)
    
    async def start(self):
        """Start telegram bot"""
        self.running = True
        logger.info("Telegram notifier started")
        await self.dp.start_polling()
    
    async def stop(self):
        """Stop telegram bot"""
        self.running = False
        await self.bot.close()
        logger.info("Telegram notifier stopped")