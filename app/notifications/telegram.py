"""
Telegram-уведомления и команды.
Использует глобальный app для доступа к состоянию.
"""
import asyncio
from datetime import datetime
from typing import Optional, List

from aiogram import Bot, Dispatcher, types

from app.config import config
from app.utils.logger import logger


class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.dp = Dispatcher(self.bot)
        self.app = None
        self._register()

    def set_app(self, app):
        self.app = app

    # ========== КОМАНДЫ ==========

    def _register(self):
        @self.dp.message_handler(commands=["start"])
        async def cmd_start(m: types.Message):
            await m.reply(
                "🤖 Market Analysis Bot\n\n"
                "Анализирую ликвидные USDT-перпы Bybit в реальном времени.\n\n"
                "Команды:\n"
                "/status — состояние бота\n"
                "/top — топ-10 активных монет\n"
                "/coins — список отслеживаемых\n"
                "/signals — последние сигналы\n"
                "/mute — вкл/выкл уведомления\n"
                "/settings — текущие настройки\n"
            )

        @self.dp.message_handler(commands=["status"])
        async def cmd_status(m: types.Message):
            if not self.app:
                await m.reply("Бот инициализируется…")
                return
            s = (
                f"📊 Статус\n"
                f"🕐 {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"📈 Монет: {len(self.app.active_symbols)}\n"
                f"💾 БД: {'OK' if self.app.postgres._connected else 'FAIL'}\n"
                f"🗄 Хранилище: {'Redis' if config.use_redis else 'FileStore'}"
            )
            await m.reply(s)

        @self.dp.message_handler(commands=["top"])
        async def cmd_top(m: types.Message):
            if not self.app:
                await m.reply("Бот инициализируется…")
                return
            symbols = self.app.active_symbols[:10]
            if not symbols:
                await m.reply("Список символов пуст")
                return
            lines = ["🔥 TOP-10 по обороту:"]
            for i, s in enumerate(symbols, 1):
                score = await self.app.store.get_current_score(s) or 0
                lines.append(f"{i}. {s} — {score}")
            await m.reply("\n".join(lines))

        @self.dp.message_handler(commands=["coins"])
        async def cmd_coins(m: types.Message):
            if not self.app:
                await m.reply("Бот инициализируется…")
                return
            symbols = self.app.active_symbols
            if not symbols:
                await m.reply("Список пуст")
                return
            head = symbols[:30]
            body = "\n".join(f"• {s}" for s in head)
            tail = f"\n… и ещё {len(symbols) - 30}" if len(symbols) > 30 else ""
            await m.reply(f"🪙 Монеты ({len(symbols)}):\n{body}{tail}")

        @self.dp.message_handler(commands=["signals"])
        async def cmd_signals(m: types.Message):
            if not self.app:
                await m.reply("Бот инициализируется…")
                return
            rows = await self.app.postgres.get_recent_signals(limit=10)
            if not rows:
                await m.reply("Пока нет сигналов")
                return
            lines = ["📊 Последние сигналы:"]
            for r in rows:
                ts = r["created_at"].strftime("%m-%d %H:%M")
                lines.append(f"{ts} {r['symbol']} {r['direction']} — {r['score']}")
            await m.reply("\n".join(lines))

        @self.dp.message_handler(commands=["mute"])
        async def cmd_mute(m: types.Message):
            uid = m.from_user.id
            if uid not in self._muted:
                self._muted.add(uid)
                await m.reply("🔕 Уведомления выключены")
            else:
                self._muted.discard(uid)
                await m.reply("🔔 Уведомления включены")

        @self.dp.message_handler(commands=["settings"])
        async def cmd_settings(m: types.Message):
            s = (
                f"⚙️ Настройки\n"
                f"Порог сигнала: {config.SIGNAL_THRESHOLD}\n"
                f"Cooldown: {config.SIGNAL_COOLDOWN_SEC} сек\n"
                f"Монет: {config.TOP_SYMBOLS_COUNT}\n"
                f"Таймфреймы: {', '.join(config.TIMEFRAMES.keys())}\n"
                f"Глубина стакана: {config.ORDERBOOK_DEPTH}"
            )
            await m.reply(s)

    _muted: set = set()

    # ========== ОТПРАВКА ==========

    async def send(self, message: str, user_ids: Optional[List[int]] = None):
        if not user_ids:
            user_ids = [aid for aid in config.ADMIN_IDS if aid not in self._muted]
        for uid in user_ids:
            try:
                await self.bot.send_message(uid, message)
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"send to {uid}: {e}")

    async def start(self):
        logger.info("Telegram bot started")
        await self.dp.start_polling()

    async def stop(self):
        try:
            await self.bot.close()
        except Exception:
            pass
        logger.info("Telegram bot stopped")