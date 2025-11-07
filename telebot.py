# bot.py
import mysql.connector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import logging
from config import MYSQL_CONFIG, BOT_TOKEN

# Настройки логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище временных данных пользователей
user_data = {}


# Подключение к MySQL
def get_db_connection():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f"Ошибка подключения к MySQL: {e}")
        return None


# Поиск подходящих ролей
def find_matching_roles(age, gender, height):
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor(dictionary=True)

        query = """
        SELECT * FROM roles 
        WHERE (gender = %s OR gender = 'any')
        AND %s BETWEEN age_min AND age_max
        AND (%s BETWEEN height_min AND height_max OR height_min IS NULL)
        AND is_active = TRUE
        ORDER BY fee DESC
        """

        cursor.execute(query, (gender, age, height))
        roles = cursor.fetchall()
        return roles

    except mysql.connector.Error as e:
        logger.error(f"Ошибка MySQL: {e}")
        return []
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


# Сохраняем актера в базу
def save_actor_to_db(telegram_id, first_name, last_name, username, age, gender, height):
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        query = """
        INSERT INTO actors (telegram_id, first_name, last_name, username, age, gender, height)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        age = VALUES(age), gender = VALUES(gender), height = VALUES(height)
        """

        cursor.execute(query, (telegram_id, first_name, last_name, username, age, gender, height))
        conn.commit()
        return True

    except mysql.connector.Error as e:
        logger.error(f"Ошибка сохранения актера: {e}")
        return False
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()


# Клавиатура для выбора пола
def gender_keyboard():
    keyboard = [
        [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Женский", callback_data="gender_female")]
    ]
    return InlineKeyboardMarkup(keyboard)


# Клавиатура для навигации по ролям
def roles_keyboard(role_index, total_roles):
    keyboard = []

    # Кнопки навигации
    nav_buttons = []
    if role_index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"role_{role_index - 1}"))

    nav_buttons.append(InlineKeyboardButton(f"{role_index + 1}/{total_roles}", callback_data="show_index"))

    if role_index < total_roles - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"role_{role_index + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # Кнопки действий
    action_buttons = [
        InlineKeyboardButton("✅ Подходит", callback_data=f"suitable_{role_index}"),
        InlineKeyboardButton("❌ Не подходит", callback_data=f"notsuitable_{role_index}")
    ]
    keyboard.append(action_buttons)

    # Кнопка нового поиска
    keyboard.append([InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")])

    return InlineKeyboardMarkup(keyboard)


# Форматирование информации о роли
def format_role_info(role, role_index, total_roles):
    gender_display = {
        'male': 'Мужской',
        'female': 'Женский',
        'any': 'Любой'
    }.get(role['gender'], 'Любой')

    height_info = f"{role['height_min']}-{role['height_max']} см" if role['height_min'] else "не указан"
    fee_info = f"{role['fee']:,} руб./смена" if role['fee'] else "не указан"

    return f"""
🎬 **{role['title']}**
🏙️ **Город:** {role['city']}
📅 **Даты:** {role['dates']}
📝 **Описание:** {role['description']}

👤 **Требования:**
• Возраст: {role['age_min']}-{role['age_max']} лет
• Рост: {height_info}
• Пол: {gender_display}

💰 **Гонорар:** {fee_info}

📋 {role_index + 1} из {total_roles} ролей
"""


# Команда /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user

    # Сбрасываем данные пользователя и устанавливаем состояние "ожидаем возраст"
    user_data[user_id] = {
        'age': None,
        'gender': None,
        'height': None,
        'matching_roles': [],
        'current_role_index': 0,
        'state': 'waiting_age'  # Добавляем состояние
    }

    await update.message.reply_text(
        "🎭 *Find Your Role Bot*\n"
        "Я помогу найти подходящие актерские роли!\n\n"
        "Для начала укажите ваш *возраст*:",
        parse_mode='Markdown'
    )


# Обработчик ВСЕХ текстовых сообщений
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Если пользователь не начал диалог
    if user_id not in user_data:
        await update.message.reply_text("Начните поиск ролей с помощью команды /start")
        return

    current_state = user_data[user_id].get('state')

    # Обработка возраста
    if current_state == 'waiting_age':
        try:
            age = int(text)
            if age < 1 or age > 100:
                await update.message.reply_text("Пожалуйста, введите реальный возраст (1-100):")
                return

            user_data[user_id]['age'] = age
            user_data[user_id]['state'] = 'waiting_gender'

            await update.message.reply_text(
                f"✅ Возраст {age} лет сохранен.\n\n"
                "Теперь выберите ваш *пол*:",
                reply_markup=gender_keyboard(),
                parse_mode='Markdown'
            )

        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите возраст числом:")

    # Обработка роста
    elif current_state == 'waiting_height':
        try:
            height = int(text)
            if height < 100 or height > 250:
                await update.message.reply_text("Пожалуйста, введите реальный рост (100-250 см):")
                return

            user_data[user_id]['height'] = height
            user_data[user_id]['state'] = 'searching'

            user = update.effective_user

            # Сохраняем актера в базу
            save_actor_to_db(
                telegram_id=user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                age=user_data[user_id]['age'],
                gender=user_data[user_id]['gender'],
                height=height
            )

            # Показываем сообщение о поиске
            search_msg = await update.message.reply_text("🔍 Ищу подходящие роли...")

            # Ищем подходящие роли
            age = user_data[user_id]['age']
            gender = user_data[user_id]['gender']

            matching_roles = find_matching_roles(age, gender, height)
            user_data[user_id]['matching_roles'] = matching_roles
            user_data[user_id]['current_role_index'] = 0

            # Удаляем сообщение о поиске
            await search_msg.delete()

            if not matching_roles:
                await update.message.reply_text(
                    "😔 По вашим параметрам не найдено подходящих ролей.\n\n"
                    "*Ваши параметры:*\n"
                    f"• Возраст: {age} лет\n"
                    f"• Пол: {'Мужской' if gender == 'male' else 'Женский'}\n"
                    f"• Рост: {height} см\n\n"
                    "Попробуйте изменить критерии поиска с помощью /start",
                    parse_mode='Markdown'
                )
                return

            # Показываем первую роль
            await show_role(update, context, user_id, 0)

        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите рост числом:")

    else:
        await update.message.reply_text("Используйте кнопки для навигации или /start для нового поиска")


# Обработка выбора пола
async def handle_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    gender = query.data.replace('gender_', '')

    if user_id not in user_data:
        await query.edit_message_text("Сессия устарела. Начните с /start")
        return

    user_data[user_id]['gender'] = gender
    user_data[user_id]['state'] = 'waiting_height'

    await query.edit_message_text(
        f"✅ Пол: {'Мужской' if gender == 'male' else 'Женский'}\n\n"
        "Теперь укажите ваш *рост* (в см):",
        parse_mode='Markdown'
    )


# Показ роли
async def show_role(update, context, user_id, role_index):
    if user_id not in user_data or not user_data[user_id]['matching_roles']:
        if isinstance(update, Update) and update.message:
            await update.message.reply_text("Данные не найдены. Начните с /start")
        else:
            await update.edit_message_text("Данные не найдены. Начните с /start")
        return

    roles = user_data[user_id]['matching_roles']
    role = roles[role_index]

    role_text = format_role_info(role, role_index, len(roles))
    keyboard = roles_keyboard(role_index, len(roles))

    if isinstance(update, Update) and update.message:
        await update.message.reply_text(role_text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        await update.edit_message_text(role_text, reply_markup=keyboard, parse_mode='Markdown')


# Обработка навигации по ролям
async def handle_role_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in user_data:
        await query.edit_message_text("Сессия устарела. Начните новый поиск с /start")
        return

    data = query.data

    if data.startswith('role_'):
        role_index = int(data.replace('role_', ''))
        user_data[user_id]['current_role_index'] = role_index
        await show_role(query, context, user_id, role_index)

    elif data.startswith('suitable_'):
        role_index = int(data.replace('suitable_', ''))
        role = user_data[user_id]['matching_roles'][role_index]

        contact_info = role.get('contact_info', 'Контактная информация не указана')

        await query.edit_message_text(
            f"✅ *Вы отметили роль как подходящую!*\n\n"
            f"**{role['title']}**\n\n"
            f"📞 *Для отклика:* {contact_info}\n"
            f"📋 *Номер роли:* #{role['id']}\n\n"
            f"*Не забудьте указать при контакте:*\n"
            f"• Номер роли #{role['id']}\n"
            f"• Что вы откликаетесь через Find Your Role Bot",
            parse_mode='Markdown'
        )

    elif data.startswith('notsuitable_'):
        role_index = int(data.replace('notsuitable_', ''))
        user_data[user_id]['current_role_index'] = role_index

        # Показываем следующую роль или сообщение
        roles = user_data[user_id]['matching_roles']
        if role_index < len(roles) - 1:
            await show_role(query, context, user_id, role_index + 1)
        else:
            await query.edit_message_text(
                "🤔 Вы просмотрели все подходящие роли.\n\n"
                "Попробуйте новый поиск с другими параметрами!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")
                ]])
            )

    elif data == "new_search":
        await start_command_from_callback(query, context)

    elif data == "show_index":
        await query.answer(
            f"Роль {user_data[user_id]['current_role_index'] + 1} из {len(user_data[user_id]['matching_roles'])}")


# Обработка команды start из callback
async def start_command_from_callback(query, context):
    user_id = query.from_user.id
    user_data[user_id] = {
        'age': None,
        'gender': None,
        'height': None,
        'matching_roles': [],
        'current_role_index': 0,
        'state': 'waiting_age'
    }

    await query.edit_message_text(
        "🎭 *Find Your Role Bot*\n\n"
        "Для начала укажите ваш *возраст*:",
        parse_mode='Markdown'
    )


# Основная функция
def main():
    # Проверяем подключение к базе
    conn = get_db_connection()
    if not conn:
        print("❌ Не удалось подключиться к MySQL. Проверьте настройки в config.py")
        return

    print("✅ Подключение к MySQL успешно!")
    conn.close()

    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start_command))

    # Один обработчик для всех текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Обработчики callback'ов
    application.add_handler(CallbackQueryHandler(handle_gender, pattern="^gender_"))
    application.add_handler(
        CallbackQueryHandler(handle_role_navigation, pattern="^(role_|suitable_|notsuitable_|new_search|show_index)"))

    # Запуск бота
    print("🤖 Бот запущен...")
    print("📝 Теперь бот будет правильно обрабатывать ввод возраста!")
    application.run_polling()


if __name__ == "__main__":
    main()