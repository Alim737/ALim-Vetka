"""
Telegram-бот для управления заявками и мероприятиями студенческого совета.
Использует библиотеку pyTelegramBotAPI (telebot), SQLite для хранения данных.
"""

import sqlite3
import os
from typing import Dict, Optional, Tuple, List, Any

from dotenv import load_dotenv
from telebot import TeleBot, types

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

bot = TeleBot(TOKEN)

# Список доступных комитетов
COMMITTEES = ['Творческий', 'Спортивный', 'СМИ', 'Технический',
              'Киберспортивный', 'Социальный']

# Словарь для хранения временных состояний пользователей
# Ключ: chat_id, значение: dict с данными текущего шага
user_states: Dict[int, dict] = {}


class Database:
    """Класс для работы с базой данных SQLite."""

    def __init__(self, db_path: str = 'bot.db') -> None:
        """Инициализация БД и создание таблиц при необходимости."""
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        """Создание необходимых таблиц, если они не существуют."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE,
                    full_name TEXT,
                    role TEXT DEFAULT 'participant'
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    committee TEXT,
                    description TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

            cursor.execute(''br
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    date TEXT,
                    description TEXT
                )
            ''')

    def _get_connection(self) -> sqlite3.Connection:
        """Возвращает соединение с БД с включённым режимом проверки внешних ключей."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def register_user(self, telegram_id: int, full_name: str) -> None:
        """Регистрирует нового пользователя с ролью 'participant'."""
        with self._get_connection() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO users (telegram_id, full_name, role) '
                'VALUES (?, ?, ?)',
                (telegram_id, full_name, 'participant')
            )

    def get_user(self, telegram_id: int) -> Optional[Tuple]:
        """Возвращает данные пользователя по telegram_id или None."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                'SELECT * FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            return cursor.fetchone()

    def create_application(self, user_id: int, committee: str, description: str) -> None:
        """Создаёт новую заявку."""
        with self._get_connection() as conn:
            conn.execute(
                'INSERT INTO applications (user_id, committee, description) '
                'VALUES (?, ?, ?)',
                (user_id, committee, description)
            )

    def add_event(self, title: str, date: str, description: str) -> None:
        """Добавляет новое мероприятие."""
        with self._get_connection() as conn:
            conn.execute(
                'INSERT INTO events (title, date, description) VALUES (?, ?, ?)',
                (title, date, description)
            )

    def get_all_events(self) -> List[Tuple]:
        """Возвращает все мероприятия, отсортированные по дате."""
        with self._get_connection() as conn:
            cursor = conn.execute('SELECT * FROM events ORDER BY date')
            return cursor.fetchall()

    def delete_last_application(self, user_id: int) -> bool:
        """Удаляет последнюю заявку пользователя. Возвращает True, если была удалена."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM applications
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
            ''', (user_id,))
            result = cursor.fetchone()
            if result:
                cursor.execute('DELETE FROM applications WHERE id = ?', (result[0],))
                conn.commit()
                return True
            return False


# Инициализация БД
db = Database()


def remove_keyboard(chat_id: int, message_text: str) -> None:
    """Удаляет пользовательскую клавиатуру и отправляет сообщение."""
    markup = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, message_text, reply_markup=markup)


def role_required(required_role: str):
    """Декоратор для проверки роли пользователя перед выполнением команды."""
    def decorator(func):
        def wrapper(message):
            user = db.get_user(message.from_user.id)
            if not user or user[3] != required_role:
                bot.send_message(
                    message.chat.id,
                    "⚠️ У вас недостаточно прав для выполнения этой команды."
                )
                return
            return func(message)
        return wrapper
    return decorator


@bot.message_handler(commands=['start'])
def start(message: types.Message) -> None:
    """Обработчик команды /start: регистрация нового пользователя."""
    user = db.get_user(message.from_user.id)
    if user:
        bot.send_message(
            message.chat.id,
            f"✅ Добро пожаловать, {user[2]}!\nВаша роль: {user[3]}"
        )
    else:
        msg = bot.send_message(
            message.chat.id,
            "👤 Введите ваше ФИО для регистрации:"
        )
        bot.register_next_step_handler(msg, process_registration)


def process_registration(message: types.Message) -> None:
    """Обработка ввода ФИО и сохранение пользователя."""
    full_name = message.text.strip()
    if not full_name:
        bot.send_message(message.chat.id, "❌ ФИО не может быть пустым. Попробуйте /start заново.")
        return
    db.register_user(message.from_user.id, full_name)
    bot.send_message(
        message.chat.id,
        f"✅ Вы успешно зарегистрированы как участник, {full_name}!"
    )


@bot.message_handler(commands=['apply'])
def apply(message: types.Message) -> None:
    """Начало подачи заявки: отображает список комитетов."""
    user = db.get_user(message.from_user.id)
    if not user or user[3] != 'participant':
        bot.send_message(message.chat.id, "⚠️ Только участники могут подавать заявки.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for committee in COMMITTEES:
        markup.add(types.KeyboardButton(committee))
    markup.add(types.KeyboardButton("🔙 Назад"))

    msg = bot.send_message(
        message.chat.id,
        "Выберите комитет:",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, ask_description, user[0])


def ask_description(message: types.Message, user_id: int) -> None:
    """Запрос описания инициативы после выбора комитета."""
    if message.text == "🔙 Назад":
        remove_keyboard(message.chat.id, "❌ Действие отменено.")
        user_states.pop(message.chat.id, None)
        return

    committee = message.text
    if committee not in COMMITTEES:
        bot.send_message(message.chat.id, "❌ Неверный комитет. Попробуйте снова /apply.")
        return

    # Сохраняем выбранный комитет и ID пользователя
    user_states[message.chat.id] = {'committee': committee, 'user_id': user_id}
    remove_keyboard(message.chat.id, "📝 Введите описание инициативы:")

    msg = bot.send_message(message.chat.id, "Опишите вашу инициативу:")
    bot.register_next_step_handler(msg, save_application)


def save_application(message: types.Message) -> None:
    """Сохраняет заявку в БД после получения описания."""
    state = user_states.pop(message.chat.id, None)
    if not state:
        bot.send_message(message.chat.id, "⚠️ Сессия истекла. Начните заново с /apply.")
        return

    description = message.text.strip()
    if not description:
        bot.send_message(
            message.chat.id,
            "❌ Описание не может быть пустым. Попробуйте снова /apply."
        )
        return

    db.create_application(state['user_id'], state['committee'], description)
    bot.send_message(message.chat.id, "✅ Заявка отправлена!")


@bot.message_handler(commands=['cancelapp'])
def cancel_last_application(message: types.Message) -> None:
    """Удаляет последнюю заявку текущего пользователя."""
    user = db.get_user(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "⚠️ Вы не зарегистрированы. Используйте /start.")
        return

    if db.delete_last_application(user[0]):
        bot.send_message(message.chat.id, "✅ Ваша последняя заявка удалена.")
    else:
        bot.send_message(message.chat.id, "📭 У вас нет активных заявок.")


@bot.message_handler(commands=['events'])
def list_events(message: types.Message) -> None:
    """Выводит список всех мероприятий."""
    events = db.get_all_events()
    if not events:
        bot.send_message(message.chat.id, "📭 Мероприятий пока нет.")
        return

    for event_id, title, date, description in events:
        bot.send_message(
            message.chat.id,
            f"📌 <b>{title}</b>\n📅 {date}\n📝 {description}",
            parse_mode='HTML'
        )


@bot.message_handler(commands=['addevent'])
@role_required('admin')
def add_event_command(message: types.Message) -> None:
    """Начинает процесс добавления мероприятия (только для админов)."""
    msg = bot.send_message(message.chat.id, "📝 Введите название мероприятия:")
    bot.register_next_step_handler(msg, get_event_title)


def get_event_title(message: types.Message) -> None:
    """Сохраняет название мероприятия и запрашивает дату."""
    user_states[message.chat.id] = {'event_title': message.text.strip()}
    msg = bot.send_message(message.chat.id, "📅 Введите дату мероприятия (например, 20.10.2025):")
    bot.register_next_step_handler(msg, get_event_date)


def get_event_date(message: types.Message) -> None:
    """Сохраняет дату и запрашивает описание."""
    state = user_states.get(message.chat.id, {})
    state['event_date'] = message.text.strip()
    user_states[message.chat.id] = state
    msg = bot.send_message(message.chat.id, "📝 Введите описание мероприятия:")
    bot.register_next_step_handler(msg, save_event)


def save_event(message: types.Message) -> None:
    """Сохраняет мероприятие в БД."""
    state = user_states.pop(message.chat.id, {})
    title = state.get('event_title')
    date = state.get('event_date')
    description = message.text.strip()

    if not title or not date or not description:
        bot.send_message(message.chat.id, "⚠️ Ошибка: не все данные были введены.")
        return

    db.add_event(title, date, description)
    bot.send_message(message.chat.id, "✅ Мероприятие добавлено.")


@bot.message_handler(commands=['help'])
def help_command(message: types.Message) -> None:
    """Выводит список доступных команд."""
    help_text = (
        "📖 <b>Доступные команды:</b>\n\n"
        "👋 /start — Начало работы и регистрация\n"
        "📋 /apply — Подать заявку в один из комитетов\n"
        "🔙 Назад — Отменить подачу заявки на любом этапе\n"
        "🗑 /cancelapp — Удалить последнюю отправленную заявку\n"
        "📆 /events — Посмотреть план мероприятий\n"
        "➕ /addevent — (только для админов) Добавить мероприятие\n"
        "ℹ️ /help — Показать это сообщение\n"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='HTML')


if __name__ == '__main__':
    print("Бот запущен...")
    bot.polling(non_stop=True)
