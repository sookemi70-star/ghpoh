import os
import asyncio
import html
import aiosqlite
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, FSInputFile
)

# ================= КОНФИГУРАЦИЯ И ЗАЩИТА ТОКЕНА =================
class Settings(BaseSettings):
    bot_token: SecretStr
    owner_id: int
    db_name: str = "shop.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

try:
    config = Settings()
except ValidationError as e:
    raise SystemExit(
        "❌ Ошибка конфигурации! Убедитесь, что создан файл .env и в нем указаны BOT_TOKEN и OWNER_ID.\n"
        f"Детали ошибки: {e}"
    )

BOT_TOKEN = config.bot_token.get_secret_value()
OWNER_ID = config.owner_id
DB_NAME = config.db_name

# Пути к изображениям
MAIN_IMAGE_PATH = "main_menu.jpg"
RULES_IMAGE_PATH = "rules.jpg"
PROFILE_IMAGE_PATH = "profile.jpg"
BALANCE_IMAGE_PATH = "balance.jpg"
ORDERS_IMAGE_PATH = "orders.jpg"
PRODUCTS_IMAGE_PATH = "products.jpg"

CACHED_PHOTO_IDS = {}

CATEGORIES = {
    "ai": "🤖 ИИ-Подписки",
    "other": "📦 Прочие товары"
}

DEFAULT_TEXTS = {
    "start_text": (
        "👋 <b>Добро пожаловать в GM store, {name}!</b>\n\n"
        "В нашем магазине вы можете приобрести цифровые услуги и ключи с моментальной автоматической выдачей.\n\n"
        "Выберите интересующий раздел:"
    ),
    "profile_text": (
        "👤 <b>Ваш профиль</b>\n\n"
        "• <b>Имя:</b> {name}\n"
        "• <b>ID:</b> <code>{id}</code>\n"
        "• <b>Текущий баланс:</b> {balance} ₽\n"
        "• <b>Куплено товаров:</b> {orders_count} шт."
    ),
    "balance_text": (
        "💰 <b>Управление балансом</b>\n\n"
        "Ваш текущий баланс: <b>{balance} ₽</b>\n\n"
        "Вы можете пополнить баланс и оплачивать любые товары в один клик без ввода реквизитов."
    ),
    "deposit_prompt": (
        "💳 <b>Пополнение баланса</b>\n\n"
        "Отправьте в чат сумму в рублях (например: <code>500</code>):"
    ),
    "deposit_success": (
        "✅ Баланс успешно пополнен на <b>{amount} ₽</b>!\n\n"
        "Текущий баланс: <b>{balance} ₽</b>"
    ),
    "catalog_text": (
        "🛍 <b>Каталог товаров</b>\n\n"
        "Выберите интересующую категорию:"
    ),
    "orders_history": (
        "📦 <b>История ваших покупок:</b>\n\n"
        "Нажмите на нужный заказ, чтобы посмотреть выданные данные:"
    ),
    "order_checkout": (
        "🧾 <b>Оформление заказа #{id}</b>\n\n"
        "Товар: <b>{title}</b>\n"
        "Стоимость: <b>{price} ₽</b>\n"
        "Ваш баланс: <b>{balance} ₽</b>\n\n"
        "Выберите способ оплаты:"
    ),
    "order_success": (
        "🎉 <b>Заказ #{id} успешно оплачен!</b>\n\n"
        "Ваш цифровой товар / ключ:\n<code>{content}</code>\n\n"
        "<i>(Данные всегда доступны в разделе «📦 Мои заказы»)</i>"
    ),
    "docs_caption": (
        "📜 <b>Документы магазина GM store</b>\n\n"
        "Ознакомьтесь с официальными правилами сервиса, регламентом покупки цифровых товаров и политикой обработки данных."
    )
}

TEXT_TITLES = {
    "start_text": "💬 Приветствие (/start)",
    "profile_text": "👤 Экран профиля",
    "balance_text": "💰 Экран баланса",
    "deposit_prompt": "💳 Запрос суммы пополнения",
    "deposit_success": "✅ Успех пополнения",
    "catalog_text": "🛍 Экран каталога",
    "orders_history": "📦 Экран истории заказов",
    "order_checkout": "🧾 Карточка заказа",
    "order_success": "🎉 Успешная выдача товара",
    "docs_caption": "📜 Описание в меню документов"
}

user_menu_messages = {}

# ================= БАЗА ДАННЫХ =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                comment TEXT
            )
        """)
        await db.execute("INSERT OR IGNORE INTO admins (user_id, comment) VALUES (?, ?)", (OWNER_ID, "Главный владелец"))

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        for k, v in DEFAULT_TEXTS.items():
            await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                price REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS items_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_sold INTEGER DEFAULT 0,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                delivered_content TEXT DEFAULT NULL
            )
        """)
        await db.commit()

async def get_text_setting(key: str) -> str:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            if row:
                return row[0]
            return DEFAULT_TEXTS.get(key, "")

async def set_text_setting(key: str, value: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None

async def add_admin_db(user_id: int, comment: str = "Администратор"):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id, comment) VALUES (?, ?)", (user_id, comment))
        await db.commit()

async def remove_admin_db(user_id: int):
    if user_id == OWNER_ID:
        return False
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()
        return True

async def get_all_admins():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, comment FROM admins") as cur:
            return await cur.fetchall()

async def get_or_create_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            user = await cur.fetchone()
            if not user:
                await db.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, 0.0)", (user_id, username))
                await db.commit()
                return 0.0
            return user[1]

async def add_user_balance(user_id: int, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def get_products_by_category(category: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT p.id, p.title, p.price, COUNT(s.id) 
            FROM products p 
            LEFT JOIN items_stock s ON p.id = s.product_id AND s.is_sold = 0
            WHERE p.category = ?
            GROUP BY p.id
        """, (category,)) as cur:
            return await cur.fetchall()

async def get_all_products():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT p.id, p.category, p.title, p.price, COUNT(s.id) 
            FROM products p 
            LEFT JOIN items_stock s ON p.id = s.product_id AND s.is_sold = 0
            GROUP BY p.id
        """) as cur:
            return await cur.fetchall()

async def add_product(category: str, title: str, price: float):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("INSERT INTO products (category, title, price) VALUES (?, ?, ?)", (category, title, price))
        await db.commit()
        return cur.lastrowid

async def add_items_to_stock(product_id: int, items: list[str]):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executemany(
            "INSERT INTO items_stock (product_id, content) VALUES (?, ?)",
            [(product_id, item.strip()) for item in items if item.strip()]
        )
        await db.commit()

async def create_order(user_id: int, product_id: int, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, product_id, amount) VALUES (?, ?, ?)",
            (user_id, product_id, amount)
        )
        await db.commit()
        return cur.lastrowid

async def fulfill_order(order_id: int, deduct_from_balance: bool = False):
    """Атомарная выдача товара с блокировкой БД для исключения Race Condition."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute("SELECT user_id, product_id, amount, status FROM orders WHERE id = ?", (order_id,)) as cur:
                order = await cur.fetchone()
                if not order or order[3] == "paid":
                    await db.rollback()
                    return None, None

            user_id, product_id, amount, _ = order

            if deduct_from_balance:
                async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
                    user_res = await cur.fetchone()
                    balance = user_res[0] if user_res else 0.0
                    if balance < amount:
                        await db.rollback()
                        return "no_balance", None
                await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))

            async with db.execute(
                "SELECT id, content FROM items_stock WHERE product_id = ? AND is_sold = 0 LIMIT 1",
                (product_id,)
            ) as cur:
                item = await cur.fetchone()

            if not item:
                await db.execute("UPDATE orders SET status = 'out_of_stock' WHERE id = ?", (order_id,))
                await db.commit()
                return user_id, None

            item_id, item_content = item
            await db.execute("UPDATE items_stock SET is_sold = 1 WHERE id = ?", (item_id,))
            await db.execute(
                "UPDATE orders SET status = 'paid', delivered_content = ? WHERE id = ?", 
                (item_content, order_id)
            )
            await db.commit()
            return user_id, item_content
        except Exception:
            await db.rollback()
            raise

async def get_user_orders(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT o.id, p.title, o.amount, o.delivered_content 
            FROM orders o 
            JOIN products p ON o.product_id = p.id 
            WHERE o.user_id = ? AND o.status = 'paid'
            ORDER BY o.id DESC LIMIT 20
        """, (user_id,)) as cur:
            return await cur.fetchall()

async def get_single_order(order_id: int, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT o.id, p.title, o.amount, o.delivered_content 
            FROM orders o 
            JOIN products p ON o.product_id = p.id 
            WHERE o.id = ? AND o.user_id = ? AND o.status = 'paid'
        """, (order_id, user_id)) as cur:
            return await cur.fetchone()

# ================= ИНИЦИАЛИЗАЦИЯ И ХЕЛПЕРЫ =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AdminState(StatesGroup):
    add_product_title = State()
    add_product_price = State()
    stock_content = State()
    new_admin_id = State()
    edit_text_value = State()

class DepositState(StatesGroup):
    amount = State()

def render_template(template: str, variables: dict) -> str:
    """Безопасная подстановка переменных без сбоев форматирования."""
    rendered = template
    for key, val in variables.items():
        rendered = rendered.replace(f"{{{key}}}", str(val))
    return rendered

async def send_clean_menu(chat_id: int, user_id: int, text: str, reply_markup: InlineKeyboardMarkup):
    old_msg_id = user_menu_messages.get(user_id)
    if old_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
        except Exception:
            pass
    new_msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)
    user_menu_messages[user_id] = new_msg.message_id
    return new_msg

async def send_clean_photo(chat_id: int, user_id: int, image_path: str, caption: str, reply_markup: InlineKeyboardMarkup):
    old_msg_id = user_menu_messages.get(user_id)
    if old_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
        except Exception:
            pass

    cached_id = CACHED_PHOTO_IDS.get(image_path)

    if cached_id:
        new_msg = await bot.send_photo(
            chat_id=chat_id, 
            photo=cached_id, 
            caption=caption, 
            parse_mode="HTML", 
            reply_markup=reply_markup
        )
    elif os.path.exists(image_path):
        photo = FSInputFile(image_path)
        new_msg = await bot.send_photo(
            chat_id=chat_id, 
            photo=photo, 
            caption=caption, 
            parse_mode="HTML", 
            reply_markup=reply_markup
        )
        if new_msg.photo:
            CACHED_PHOTO_IDS[image_path] = new_msg.photo[-1].file_id
    else:
        new_msg = await bot.send_message(
            chat_id=chat_id, 
            text=caption, 
            parse_mode="HTML", 
            reply_markup=reply_markup
        )
    
    user_menu_messages[user_id] = new_msg.message_id
    return new_msg

async def get_main_menu_keyboard(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="🛍 Товары", callback_data="catalog_cats")],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="💰 Баланс", callback_data="balance")
        ],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="📄 Политика / Соглашения", callback_data="open_docs")]
    ]
    if await is_admin(user_id):
        buttons.append([InlineKeyboardButton(text="⚙️ Панель администратора", callback_data="adm_panel_open")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard(is_owner: bool):
    buttons = [
        [InlineKeyboardButton(text="➕ Создать товар", callback_data="adm_add_cat")],
        [InlineKeyboardButton(text="📦 Загрузить ключи", callback_data="adm_load_stock")],
        [InlineKeyboardButton(text="📊 Остатки склада", callback_data="adm_stock_list")],
        [InlineKeyboardButton(text="✏️ Настройки текстов", callback_data="adm_texts")]
    ]
    if is_owner:
        buttons.append([InlineKeyboardButton(text="👥 Администраторы", callback_data="adm_team")])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ =================
@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await get_or_create_user(msg.from_user.id, msg.from_user.username)
    try:
        await msg.delete()
    except Exception:
        pass

    raw_text = await get_text_setting("start_text")
    safe_name = html.escape(msg.from_user.first_name or "Пользователь")
    text = render_template(raw_text, {"name": safe_name})
    kb = await get_main_menu_keyboard(msg.from_user.id)
    await send_clean_photo(msg.chat.id, msg.from_user.id, MAIN_IMAGE_PATH, text, kb)

@dp.callback_query(F.data == "start_menu")
async def back_to_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    raw_text = await get_text_setting("start_text")
    safe_name = html.escape(call.from_user.first_name or "Пользователь")
    text = render_template(raw_text, {"name": safe_name})
    kb = await get_main_menu_keyboard(call.from_user.id)
    await send_clean_photo(call.message.chat.id, call.from_user.id, MAIN_IMAGE_PATH, text, kb)

@dp.callback_query(F.data == "open_docs")
async def show_docs_menu(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url="https://telegra.ph/Polzovatelskoe-soglashenie-10-15-93")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url="https://telegra.ph/Politika-konfidencialnosti-10-15-140")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
    ])
    caption = await get_text_setting("docs_caption")
    await send_clean_photo(call.message.chat.id, call.from_user.id, RULES_IMAGE_PATH, caption, kb)

@dp.callback_query(F.data == "profile")
async def show_profile(call: CallbackQuery):
    balance = await get_or_create_user(call.from_user.id, call.from_user.username)
    orders = await get_user_orders(call.from_user.id)
    
    raw_text = await get_text_setting("profile_text")
    text = render_template(raw_text, {
        "name": html.escape(call.from_user.first_name or "Пользователь"),
        "id": call.from_user.id,
        "balance": f"{balance:.2f}",
        "orders_count": len(orders)
    })

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
    ])
    await send_clean_photo(call.message.chat.id, call.from_user.id, PROFILE_IMAGE_PATH, text, kb)

@dp.callback_query(F.data == "balance")
async def show_balance(call: CallbackQuery):
    balance = await get_or_create_user(call.from_user.id, call.from_user.username)
    raw_text = await get_text_setting("balance_text")
    text = render_template(raw_text, {"balance": f"{balance:.2f}"})

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
    ])
    await send_clean_photo(call.message.chat.id, call.from_user.id, BALANCE_IMAGE_PATH, text, kb)

@dp.callback_query(F.data == "deposit")
async def start_deposit(call: CallbackQuery, state: FSMContext):
    text = await get_text_setting("deposit_prompt")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data="balance")]
    ])
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)
    await state.set_state(DepositState.amount)

@dp.message(DepositState.amount)
async def process_deposit_sum(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    try:
        amount = float(msg.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        return

    await state.clear()
    await add_user_balance(msg.from_user.id, amount)
    balance = await get_or_create_user(msg.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 К товарам", callback_data="catalog_cats")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
    ])
    raw_text = await get_text_setting("deposit_success")
    text = render_template(raw_text, {
        "amount": f"{amount:.2f}",
        "balance": f"{balance:.2f}"
    })

    await send_clean_menu(msg.chat.id, msg.from_user.id, text, kb)

@dp.callback_query(F.data == "my_orders")
async def show_orders(call: CallbackQuery):
    orders = await get_user_orders(call.from_user.id)
    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 В каталог", callback_data="catalog_cats")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
        ])
        await send_clean_photo(call.message.chat.id, call.from_user.id, ORDERS_IMAGE_PATH, "📦 У вас пока нет оформленных покупок.", kb)
        return

    buttons = []
    for o_id, title, amount, _ in orders:
        buttons.append([InlineKeyboardButton(text=f"🛒 #{o_id} — {title} ({amount}₽)", callback_data=f"view_order:{o_id}")])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")])

    text = await get_text_setting("orders_history")
    await send_clean_photo(call.message.chat.id, call.from_user.id, ORDERS_IMAGE_PATH, text, InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("view_order:"))
async def view_order_detail(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])
    order = await get_single_order(order_id, call.from_user.id)

    if not order:
        await call.answer("Заказ не найден!", show_alert=True)
        return

    _, title, amount, delivered_content = order
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад к заказам", callback_data="my_orders")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
    ])

    safe_content = html.escape(delivered_content or "")
    text = (
        f"📦 <b>Информация о заказе #{order_id}</b>\n\n"
        f"• <b>Товар:</b> {html.escape(title)}\n"
        f"• <b>Стоимость:</b> {amount} ₽\n\n"
        f"🔑 <b>Выданные данные:</b>\n"
        f"<code>{safe_content}</code>\n\n"
        f"<i>(Нажмите на текст в рамке выше, чтобы скопировать его)</i>"
    )
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)

@dp.callback_query(F.data == "catalog_cats")
async def show_categories(call: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="🤖 ИИ-Подписки", callback_data="cat:ai")],
        [InlineKeyboardButton(text="📦 Прочие товары", callback_data="cat:other")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
    ]
    text = await get_text_setting("catalog_text")
    await send_clean_photo(call.message.chat.id, call.from_user.id, PRODUCTS_IMAGE_PATH, text, InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("cat:"))
async def show_category_products(call: CallbackQuery):
    cat_key = call.data.split(":")[1]
    cat_title = CATEGORIES.get(cat_key, "Товары")
    products = await get_products_by_category(cat_key)

    if not products:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к категориям", callback_data="catalog_cats")]
        ])
        await send_clean_menu(call.message.chat.id, call.from_user.id, f"В категории <b>{cat_title}</b> пока нет доступных товаров.", kb)
        return

    buttons = []
    for p_id, title, price, count in products:
        status = f"({count} шт.)" if count > 0 else "(Нет в наличии)"
        buttons.append([InlineKeyboardButton(text=f"🟢 {title} — {price}₽ {status}", callback_data=f"buy:{p_id}")])
    buttons.append([InlineKeyboardButton(text="« К категориям", callback_data="catalog_cats")])

    await send_clean_menu(call.message.chat.id, call.from_user.id, f"Категория: <b>{cat_title}</b>\nВыберите товар:", InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("buy:"))
async def process_buy(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT p.category, p.title, p.price, COUNT(s.id) 
            FROM products p 
            LEFT JOIN items_stock s ON p.id = s.product_id AND s.is_sold = 0
            WHERE p.id = ? GROUP BY p.id
        """, (product_id,)) as cur:
            item = await cur.fetchone()

    if not item or item[3] <= 0:
        await call.answer("Товара нет в наличии!", show_alert=True)
        return

    category, title, price, count = item
    order_id = await create_order(call.from_user.id, product_id, price)
    balance = await get_or_create_user(call.from_user.id)

    buttons = [
        [InlineKeyboardButton(text=f"💰 Оплатить с баланса ({balance:.2f} ₽)", callback_data=f"pay_bal:{order_id}")]
    ]

    if await is_admin(call.from_user.id):
        buttons.append([InlineKeyboardButton(text="🧪 Тестовая оплата (Админ)", callback_data=f"test_pay:{order_id}")])

    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"cat:{category}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    raw_text = await get_text_setting("order_checkout")
    text = render_template(raw_text, {
        "id": order_id,
        "title": html.escape(title),
        "price": price,
        "balance": f"{balance:.2f}"
    })
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)

@dp.callback_query(F.data.startswith("pay_bal:"))
async def process_balance_payment(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])
    res, content = await fulfill_order(order_id, deduct_from_balance=True)

    if res == "no_balance":
        await call.answer("Недостаточно средств на балансе!", show_alert=True)
        return

    if content:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
        ])
        raw_text = await get_text_setting("order_success")
        text = render_template(raw_text, {
            "id": order_id,
            "content": html.escape(content)
        })
        await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)
    else:
        await call.answer("Товар закончился или уже выдан.", show_alert=True)

@dp.callback_query(F.data.startswith("test_pay:"))
async def process_test_payment(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("У вас нет прав для тестовой оплаты!", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    user_id, content = await fulfill_order(order_id, deduct_from_balance=False)

    if content:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start_menu")]
        ])
        raw_text = await get_text_setting("order_success")
        text = render_template(raw_text, {
            "id": order_id,
            "content": html.escape(content)
        })
        await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)
    else:
        await call.answer("Товар закончился или уже выдан.", show_alert=True)

# ================= АДМИН-ПАНЕЛЬ =================
@dp.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        return
    await state.clear()
    try:
        await msg.delete()
    except Exception:
        pass

    is_owner = (msg.from_user.id == OWNER_ID)
    await send_clean_menu(msg.chat.id, msg.from_user.id, "⚙️ <b>Панель управления магазином:</b>", get_admin_keyboard(is_owner))

@dp.callback_query(F.data == "adm_panel_open")
async def adm_panel_callback(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id): return
    await state.clear()
    is_owner = (call.from_user.id == OWNER_ID)
    await send_clean_menu(call.message.chat.id, call.from_user.id, "⚙️ <b>Панель управления магазином:</b>", get_admin_keyboard(is_owner))

@dp.callback_query(F.data == "adm_back")
async def adm_back_btn(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id): return
    await state.clear()
    is_owner = (call.from_user.id == OWNER_ID)
    await send_clean_menu(call.message.chat.id, call.from_user.id, "⚙️ <b>Панель управления магазином:</b>", get_admin_keyboard(is_owner))

@dp.callback_query(F.data == "adm_texts")
async def adm_texts_menu(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return
    
    buttons = []
    for k, title in TEXT_TITLES.items():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"adm_edtxt:{k}")])
    
    buttons.append([InlineKeyboardButton(text="🔄 Сбросить ВСЕ тексты по умолчанию", callback_data="adm_edtxt_reset")])
    buttons.append([InlineKeyboardButton(text="« Назад в админку", callback_data="adm_back")])

    await send_clean_menu(
        call.message.chat.id, call.from_user.id,
        "✏️ <b>Управление текстами магазина:</b>\n\nВыберите раздел, который хотите отредактировать:",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("adm_edtxt:"))
async def adm_edit_text_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id): return
    key = call.data.split(":")[1]
    current_val = await get_text_setting(key)

    await state.update_data(editing_key=key)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_texts")]])
    
    hints = {
        "start_text": "💡 Переменная: <code>{name}</code> (имя пользователя)",
        "profile_text": "💡 Переменные: <code>{name}</code>, <code>{id}</code>, <code>{balance}</code>, <code>{orders_count}</code>",
        "balance_text": "💡 Переменная: <code>{balance}</code>",
        "deposit_prompt": "💡 Текст запроса ввода суммы",
        "deposit_success": "💡 Переменные: <code>{amount}</code>, <code>{balance}</code>",
        "catalog_text": "💡 Текст витрины категорий",
        "orders_history": "💡 Текст шапки истории заказов",
        "order_checkout": "💡 Переменные: <code>{id}</code>, <code>{title}</code>, <code>{price}</code>, <code>{balance}</code>",
        "order_success": "💡 Переменные: <code>{id}</code>, <code>{content}</code> (выданный ключ)",
        "docs_caption": "💡 Описание под картинкой правил"
    }
    hint = hints.get(key, "")

    text = (
        f"📝 <b>Редактирование:</b> {TEXT_TITLES.get(key, key)}\n\n"
        f"<b>Текущий текст:</b>\n"
        f"<pre>{html.escape(current_val)}</pre>\n\n"
        f"{hint}\n\n"
        "Отправьте в чат новое сообщение с текстом (поддерживается HTML-разметка):"
    )
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)
    await state.set_state(AdminState.edit_text_value)

@dp.message(AdminState.edit_text_value)
async def adm_edit_text_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("editing_key")
    try:
        await msg.delete()
    except Exception:
        pass

    new_text = msg.html_text or msg.text or ""
    await set_text_setting(key, new_text)
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ К списку текстов", callback_data="adm_texts")],
        [InlineKeyboardButton(text="« В админку", callback_data="adm_back")]
    ])
    text = f"✅ Текст для <b>«{TEXT_TITLES.get(key, key)}»</b> успешно сохранён!"
    await send_clean_menu(msg.chat.id, msg.from_user.id, text, kb)

@dp.callback_query(F.data == "adm_edtxt_reset")
async def adm_reset_texts(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return
    for k, v in DEFAULT_TEXTS.items():
        await set_text_setting(k, v)
    await call.answer("Все тексты сброшены к стандартным!", show_alert=True)
    await adm_texts_menu(call)

@dp.callback_query(F.data == "adm_add_cat")
async def adm_choose_cat_for_add(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return
    buttons = [
        [InlineKeyboardButton(text="🤖 ИИ-Подписки", callback_data="adm_setcat:ai")],
        [InlineKeyboardButton(text="📦 Прочие товары", callback_data="adm_setcat:other")],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm_back")]
    ]
    await send_clean_menu(call.message.chat.id, call.from_user.id, "Выберите категорию для нового товара:", InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("adm_setcat:"))
async def adm_start_add_title(call: CallbackQuery, state: FSMContext):
    cat_key = call.data.split(":")[1]
    await state.update_data(category=cat_key)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_back")]])
    text = f"Категория: <b>{CATEGORIES[cat_key]}</b>\n\nВведите название товара (например: <code>ChatGPT Plus 1 месяц</code>):"
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)
    await state.set_state(AdminState.add_product_title)

@dp.message(AdminState.add_product_title)
async def adm_set_title(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    if not msg.text:
        return

    await state.update_data(title=msg.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_back")]])
    text = f"Товар: <b>{html.escape(msg.text.strip())}</b>\n\nТеперь введите цену в рублях (например: <code>199</code>):"
    await send_clean_menu(msg.chat.id, msg.from_user.id, text, kb)
    await state.set_state(AdminState.add_product_price)

@dp.message(AdminState.add_product_price)
async def adm_set_price(msg: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await msg.delete()
    except Exception:
        pass

    try:
        price = float(msg.text.replace(",", "."))
        if price < 0:
            raise ValueError
    except (ValueError, AttributeError):
        return

    pid = await add_product(data["category"], data["title"], price)
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать ещё", callback_data="adm_add_cat")],
        [InlineKeyboardButton(text="📦 Загрузить ключи", callback_data="adm_load_stock")],
        [InlineKeyboardButton(text="« В админку", callback_data="adm_back")]
    ])
    text = (
        f"✅ Товар успешно создан!\n\n"
        f"• ID: <code>{pid}</code>\n"
        f"• Категория: <b>{CATEGORIES[data['category']]}</b>\n"
        f"• Название: <b>{html.escape(data['title'])}</b>\n"
        f"• Цена: <b>{price} ₽</b>"
    )
    await send_clean_menu(msg.chat.id, msg.from_user.id, text, kb)

@dp.callback_query(F.data == "adm_load_stock")
async def adm_stock_menu(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return
    products = await get_all_products()
    if not products:
        await call.answer("Сначала создайте хотя бы один товар!", show_alert=True)
        return

    buttons = []
    for p_id, cat, title, _, _ in products:
        buttons.append([InlineKeyboardButton(text=f"[{CATEGORIES.get(cat, '')[:4]}] {title}", callback_data=f"adm_fill:{p_id}")])
    buttons.append([InlineKeyboardButton(text="« В админку", callback_data="adm_back")])
    await send_clean_menu(call.message.chat.id, call.from_user.id, "Выберите товар для пополнения ключами:", InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("adm_fill:"))
async def adm_start_fill(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.split(":")[1])
    await state.update_data(product_id=pid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_load_stock")]])
    await send_clean_menu(call.message.chat.id, call.from_user.id, "Отправьте ключи/данные списком (каждая единица товара с новой строки):", kb)
    await state.set_state(AdminState.stock_content)

@dp.message(AdminState.stock_content)
async def adm_save_keys(msg: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await msg.delete()
    except Exception:
        pass

    if not msg.text:
        return

    lines = [line.strip() for line in msg.text.split("\n") if line.strip()]
    await add_items_to_stock(data["product_id"], lines)
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Остатки склада", callback_data="adm_stock_list")],
        [InlineKeyboardButton(text="« В админку", callback_data="adm_back")]
    ])
    text = f"✅ Успешно загружено <b>{len(lines)}</b> шт. позиций на склад!"
    await send_clean_menu(msg.chat.id, msg.from_user.id, text, kb)

@dp.callback_query(F.data == "adm_stock_list")
async def adm_stock_view(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return
    products = await get_all_products()
    if not products:
        await call.answer("Товаров нет", show_alert=True)
        return

    text = "📊 <b>Текущие остатки на складе:</b>\n\n"
    for cat_key, cat_name in CATEGORIES.items():
        text += f"<b>{cat_name}:</b>\n"
        cat_prods = [p for p in products if p[1] == cat_key]
        if not cat_prods:
            text += "  <i>(пусто)</i>\n"
        for p_id, _, title, price, count in cat_prods:
            text += f"• <code>ID {p_id}</code> <b>{html.escape(title)}</b> — {price} ₽ | В наличии: <b>{count} шт.</b>\n"
        text += "\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад в админку", callback_data="adm_back")]
    ])
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)

@dp.callback_query(F.data == "adm_team")
async def adm_team_menu(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Только главный владелец может управлять админами!", show_alert=True)
        return

    admins = await get_all_admins()
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить администратора", callback_data="adm_team_add")]
    ]
    for uid, comment in admins:
        if uid == OWNER_ID:
            continue
        buttons.append([InlineKeyboardButton(text=f"❌ Снять ID {uid}", callback_data=f"adm_team_del:{uid}")])
    buttons.append([InlineKeyboardButton(text="« Назад в админку", callback_data="adm_back")])

    text = "👥 <b>Команда администраторов:</b>\n\n"
    for uid, comment in admins:
        badge = "👑 (Владелец)" if uid == OWNER_ID else "🛡 (Админ)"
        text += f"• <code>{uid}</code> — {html.escape(comment)} {badge}\n"
    text += "\n<i>Нажмите на кнопку с ID ниже, чтобы разжаловать администратора.</i>"

    await send_clean_menu(call.message.chat.id, call.from_user.id, text, InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "adm_team_add")
async def adm_team_add_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="adm_team")]])
    text = (
        "Введите <b>Telegram ID</b> пользователя, которого хотите назначить администратором:\n\n"
        "<i>(Узнать свой ID пользователь может в разделе «👤 Профиль»)</i>"
    )
    await send_clean_menu(call.message.chat.id, call.from_user.id, text, kb)
    await state.set_state(AdminState.new_admin_id)

@dp.message(AdminState.new_admin_id)
async def adm_team_add_save(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    try:
        new_uid = int(msg.text.strip())
    except (ValueError, AttributeError):
        return

    await add_admin_db(new_uid, comment="Назначен владельцем")
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 К списку админов", callback_data="adm_team")],
        [InlineKeyboardButton(text="« В админку", callback_data="adm_back")]
    ])
    text = f"✅ Пользователь с ID <code>{new_uid}</code> успешно добавлен в администраторы!\nТеперь ему доступна команда <code>/admin</code> и тестовая оплата."
    await send_clean_menu(msg.chat.id, msg.from_user.id, text, kb)

@dp.callback_query(F.data.startswith("adm_team_del:"))
async def adm_team_delete(call: CallbackQuery):
    if call.from_user.id != OWNER_ID: return
    target_id = int(call.data.split(":")[1])
    await remove_admin_db(target_id)
    await call.answer(f"Пользователь {target_id} снят с должности админа!", show_alert=True)
    await adm_team_menu(call)

# ================= СТАРТ =================
async def main():
    await init_db()
    print("=== Бот GM store успешно запущен! ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())