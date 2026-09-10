import asyncio
from datetime import datetime
from typing import List, Optional, Set

from aiogram import Bot, Dispatcher, types

from app.config import config
from app.utils.logger import logger


class TelegramNotifier:
    SUBSCRIBERS_KEY = "telegram_subscribers"

    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.dp = Dispatcher(self.bot)
        self.app = None

        self._subscribers: Set[int] = set()
        self._muted: Set[int] = set()
        self._loaded = False

        self._register()

    def set_app(self, app):
        self.app = app

    # ========== ХРАНИЛИЩЕ ПОДПИСЧИКОВ ==========

    async def _load_subscribers(self):
        if self._loaded or not self.app:
            return
        try:
            data = await self.app.store._get(self.SUBSCRIBERS_KEY)
            if isinstance(data, list):
                self._subscribers = set(int(x) for x in data)
        except Exception as e:
            logger.debug(f"load_subscribers: {e}")
        self._loaded = True

    async def _save_subscribers(self):
        if not self.app:
            return
        try:
            await self.app.store._set(
                self.SUBSCRIBERS_KEY, sorted(self._subscribers), ttl=None
            )
        except Exception as e:
            logger.debug(f"save_subscribers: {e}")

    # ========== КОМАНДЫ ==========

    def _register(self):
        @self.dp.message_handler(commands=["start"])
        async def cmd_start(m: types.Message):
            uid = m.from_user.id
            await self._load_subscribers()
            self._subscribers.add(uid)
            await self._save_subscribers()
            await m.reply(
                "🤖 Market Analysis Bot\n\n"
                "✅ Ты подписан на сигналы.\n\n"
                "Команды:\n"
                "/status — состояние\n"
                "/top — топ-10 монет\n"
                "/coins — список монет\n"
                "/signals — последние сигналы\n"
                "/mute — вкл/выкл уведомления\n"
                "/stop — отписаться от сигналов\n"
                "/settings — настройки\n"
            )

        @self.dp.message_handler(commands=["stop"])
        async def cmd_stop(m: types.Message):
            uid = m.from_user.id
            await self._load_subscribers()
            self._subscribers.discard(uid)
            await self._save_subscribers()
            await m.reply("🔕 Ты отписан от сигналов. Вернуться — /start")

        @self.dp.message_handler(commands=["status"])
        async def cmd_status(m: types.Message):
            if not self.app:
                await m.reply("Бот инициализируется…")
                return
            db_ok = "OK" if self.app.postgres._connected else "FAIL"
            store = "Redis" if config.use_redis else "FileStore"
            s = (
                f"📊 Статус\n"
                f"🕐 {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"📈 Монет: {len(self.app.active_symbols)}\n"
                f"💾 БД: {db_ok}\n"
                f"🗄 Хранилище: {store}\n"
                f"👥 Подписчиков: {len(self._subscribers)}"
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
            if uid in self._muted:
                self._muted.discard(uid)
                await m.reply("🔔 Уведомления включены")
            else:
                self._muted.add(uid)
                await m.reply("🔕 Уведомления выключены (подписка остаётся)")

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

    # ========== ОТПРАВКА ==========

    async def send(self, message: str, user_ids: Optional[List[int]] = None):
        await self._load_subscribers()

        if user_ids is None:
            recipients = set(self._subscribers)
            recipients.update(config.ADMIN_IDS)
            recipients -= self._muted
        else:
            recipients = set(user_ids) - self._muted

        for uid in recipients:
            try:
                await self.bot.send_message(uid, message)
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"send to {uid}: {e}")

    async def start(self):
        await self._load_subscribers()
        logger.info(f"Telegram bot started, subscribers: {len(self._subscribers)}")
        await self.dp.start_polling()

    async def stop(self):
        try:
            await self.bot.close()
        except Exception:
            pass
        logger.info("Telegram bot stopped")