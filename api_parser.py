# api_parser.py
import mysql.connector
import requests
import time
import schedule
import logging
from datetime import datetime
import json
from typing import List, Dict, Optional

# Используем те же настройки что и в боте
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'almas575',
    'database': 'casting_db',
    'port': 3306
}

# Настройки API (ЗАМЕНИ НА РЕАЛЬНЫЕ ДАННЫЕ)
API_CONFIG = {
    'url': 'http://localhost:8080/castings',  # Замени на реальный URL API
    'headers': {
        'Content-Type': 'application/json'
    },
    'params': {
        'status': 'active',
        'limit': 100
    }
}

# Настройки логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('api_parser.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class RoleAPIParser:
    def __init__(self):
        self.api_url = API_CONFIG['url']
        self.api_headers = API_CONFIG.get('headers', {})
        self.api_params = API_CONFIG.get('params', {})

    def get_db_connection(self):
        """Подключение к MySQL"""
        try:
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            return conn
        except mysql.connector.Error as e:
            logger.error(f"Ошибка подключения к MySQL: {e}")
            return None

    def make_api_request(self) -> Optional[List[Dict]]:
        """
        Выполняет запрос к API и возвращает данные
        """
        try:
            logger.info(f"Выполняем запрос к API: {self.api_url}")

            response = requests.get(
                self.api_url,
                headers=self.api_headers,
                params=self.api_params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    f"Успешно получено {len(data) if isinstance(data, list) else 'неизвестное количество'} записей")
                return data
            else:
                logger.error(f"Ошибка API: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return None

    def transform_role_data(self, api_data: Dict) -> Dict:
        """
        Преобразует данные из API в формат нашей базы данных
        """
        try:
            # Базовое преобразование полей согласно вашему формату
            transformed = {
                'role_id': str(api_data.get('roleId', '')),
                'title': api_data.get('title', '')[:500],
                'dates': api_data.get('eventDate', ''),
                'description': api_data.get('description', ''),
                'gender': self._normalize_gender(api_data.get('gender', 'any')),
                'age_min': self._safe_int(api_data.get('age_min')),
                'age_max': self._safe_int(api_data.get('age_max')),
                'height_min': self._safe_int(api_data.get('height_min')),
                'height_max': self._safe_int(api_data.get('height_max')),
                'fee': self._safe_decimal(api_data.get('fee')),
                'city': api_data.get('city', 'Москва')[:100],  # По умолчанию Москва
                'contact_info': api_data.get('contactInfo', ''),
                'requirements': api_data.get('requirements', ''),
                'category': api_data.get('category', ''),
                'source': 'api',
                'is_active': True
            }

            # Логируем преобразование для отладки
            logger.debug(f"Преобразована роль: {transformed['title'][:50]}...")

            return transformed

        except Exception as e:
            logger.error(f"Ошибка при преобразовании данных: {e} - Данные: {api_data}")
            return {}

    def _normalize_gender(self, gender: str) -> str:
        """Нормализует значение пола"""
        if not gender:
            return 'any'

        gender = str(gender).lower().strip()
        if gender in ['male', 'мужской', 'м', 'm', 'man']:
            return 'male'
        elif gender in ['female', 'женский', 'ж', 'f', 'woman']:
            return 'female'
        else:
            return 'any'

    def _safe_int(self, value) -> Optional[int]:
        """Безопасное преобразование в int"""
        try:
            if value is None or value == '':
                return None
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def _safe_decimal(self, value) -> Optional[float]:
        """Безопасное преобразование в decimal"""
        try:
            if value is None or value == '':
                return None
            return float(value)
        except (ValueError, TypeError):
            return None

    def save_role_to_db(self, role_data: Dict) -> bool:
        """
        Сохраняет или обновляет роль в базе данных
        """
        if not role_data or not role_data.get('role_id'):
            logger.warning("Попытка сохранить пустые данные или без role_id")
            return False

        conn = self.get_db_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()

            # Проверяем существующую роль по role_id
            cursor.execute(
                "SELECT id FROM roles WHERE role_id = %s",
                (role_data['role_id'],)
            )
            existing_role = cursor.fetchone()

            if existing_role:
                # Обновляем существующую роль
                query = """
                UPDATE roles SET 
                    title = %s, dates = %s, description = %s, gender = %s,
                    age_min = %s, age_max = %s, height_min = %s, height_max = %s,
                    fee = %s, city = %s, contact_info = %s, requirements = %s,
                    updated_at = CURRENT_TIMESTAMP, source = %s, is_active = %s
                WHERE role_id = %s
                """
                params = (
                    role_data['title'], role_data['dates'], role_data['description'],
                    role_data['gender'], role_data['age_min'], role_data['age_max'],
                    role_data['height_min'], role_data['height_max'], role_data['fee'],
                    role_data['city'], role_data['contact_info'], role_data['requirements'],
                    role_data['source'], role_data['is_active'], role_data['role_id']
                )

                cursor.execute(query, params)
                action = "обновлена"

            else:
                # Вставляем новую роль
                query = """
                INSERT INTO roles (
                    role_id, title, dates, description, gender, age_min, age_max,
                    height_min, height_max, fee, city, contact_info, requirements,
                    source, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    role_data['role_id'], role_data['title'], role_data['dates'],
                    role_data['description'], role_data['gender'], role_data['age_min'],
                    role_data['age_max'], role_data['height_min'], role_data['height_max'],
                    role_data['fee'], role_data['city'], role_data['contact_info'],
                    role_data['requirements'], role_data['source'], role_data['is_active']
                )

                cursor.execute(query, params)
                action = "добавлена"

            conn.commit()
            logger.info(f"{action.capitalize()} роль: {role_data['title'][:50]}...")
            return True

        except mysql.connector.Error as e:
            logger.error(f"Ошибка при сохранении в БД: {e} - Данные: {role_data}")
            conn.rollback()
            return False
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def process_category(self, category_name: str, role_data: Dict) -> bool:
        """
        Обрабатывает категорию роли
        """
        if not category_name:
            return True

        conn = self.get_db_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()

            # Добавляем категорию если её нет
            cursor.execute(
                "INSERT IGNORE INTO categories (name) VALUES (%s)",
                (category_name,)
            )

            # Связываем роль с категорией
            cursor.execute(
                """INSERT IGNORE INTO role_categories (role_id, category_id)
                SELECT r.id, c.id 
                FROM roles r, categories c 
                WHERE r.role_id = %s AND c.name = %s""",
                (role_data['role_id'], category_name)
            )

            conn.commit()
            logger.debug(f"Обработана категория '{category_name}' для роли {role_data['role_id']}")
            return True

        except mysql.connector.Error as e:
            logger.error(f"Ошибка при обработке категории: {e}")
            return False
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    def run_parsing(self):
        """
        Основной метод парсинга
        """
        logger.info("🎬 === Начало парсинга API ===")
        start_time = time.time()

        # Получаем данные из API
        api_data = self.make_api_request()
        if not api_data:
            logger.error("❌ Не удалось получить данные из API")
            return

        if not isinstance(api_data, list):
            logger.error(f"❌ Ожидался список данных, получен: {type(api_data)}")
            return

        processed = 0
        errors = 0

        # Обрабатываем каждую роль
        for role in api_data:
            try:
                # Преобразуем данные
                transformed_data = self.transform_role_data(role)
                if not transformed_data:
                    errors += 1
                    continue

                # Сохраняем в БД
                if self.save_role_to_db(transformed_data):
                    # Обрабатываем категорию
                    category = role.get('category')
                    if category:
                        self.process_category(category, transformed_data)

                    processed += 1
                else:
                    errors += 1

            except Exception as e:
                logger.error(f"❌ Ошибка при обработке роли: {e} - Данные: {role}")
                errors += 1

        # Логируем результаты
        elapsed_time = time.time() - start_time
        logger.info(f"📊 === Парсинг завершен ===")
        logger.info(f"✅ Успешно обработано: {processed}")
        logger.info(f"❌ Ошибок: {errors}")
        logger.info(f"⏱️ Затраченное время: {elapsed_time:.2f} секунд")

        return processed, errors


def run_scheduled_parsing():
    """Функция для запуска по расписанию"""
    parser = RoleAPIParser()
    return parser.run_parsing()


def main():
    """Основная функция"""
    parser = RoleAPIParser()

    # Запускаем сразу один раз
    logger.info("🚀 Запуск парсера...")
    processed, errors = parser.run_parsing()

    if processed == 0 and errors == 0:
        logger.warning("⚠️  Не получено данных для обработки. Проверьте настройки API.")
        return

    # Настраиваем расписание (раз в час)
    schedule.every(1).hours.do(run_scheduled_parsing)

    logger.info("⏰ Планировщик запущен. Парсинг будет выполняться каждый час.")

    # Бесконечный цикл для расписания
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)  # Проверяем каждую минуту
        except KeyboardInterrupt:
            logger.info("🛑 Парсер остановлен пользователем")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка в основном цикле: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()