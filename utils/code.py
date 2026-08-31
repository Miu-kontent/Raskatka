print("Скрипт запущен!", flush=True)
import eel
import os
import random
import re
import gspread
from time import sleep
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from transliterate import translit
import requests
import ctypes
import json
import sys
print("Библиотеки импортированы", flush=True)
# --- ИНИЦИАЛИЗАЦИЯ ---
try:
    r = requests.get("https://www.googleapis.com/discovery/v1/apis/sheets/v4/rest", timeout=10)
    print("✅ Google API доступен")
except:
    print("❌ Google API НЕ ДОСТУПЕН - попробуйте/смените/отключите VPN")

# Пути к файлам
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(UTILS_DIR)

JSON_KEY = os.path.join(UTILS_DIR, "raskatka-adressov-591861b40918.json")
GECKO_PATH = os.path.join(UTILS_DIR, "geckodriver.exe")
WEB_PATH = os.path.join(BASE_DIR, "web")

# JSON_KEY = f'{os.path.join(os.getcwd(), "utils", "raskatka-adressov-591861b40918.json")}'
# GECKO_PATH = f"{os.path.join(os.getcwd(), 'geckodriver.exe')}"
# WEB_PATH = f"{os.path.dirname(os.getcwd())}\\web"

# Подключение к Google Таблицам
try:
    with open(JSON_KEY, "r", encoding="utf-8-sig") as f:
        credentials_data = json.load(f)
    service_account = gspread.service_account_from_dict(credentials_data)
    sh = service_account.open("Раскатка адрессов")
    print("✅ Успешное подключение к Google Таблице Раскатка адрессов")
    worksheet_rolling = sh.worksheet("Rolling")
    print("✅ Успешное подключение к листу Rolling")
    worksheet_parser = sh.worksheet("Parser")
    print("✅ Успешное подключение к листу Parser")
except Exception as e:
    print(f"❌ Ошибка подключения: {e}")

# --- Перехват логов консоли и отправка в интерфейс ---
class EelLogger:
    def __init__(self):
        self.terminal = sys.stdout

    def write(self, message):
        if self.terminal:
            self.terminal.write(message)
        msg = message.strip()
        if msg:
            try:
                # Отправляем лог в JS функцию addLog
                eel.addLog(msg)()
            except Exception:
                pass

    def flush(self):
        if self.terminal:
            self.terminal.flush()

# Включаем перехват (теперь все print пойдут в UI)
sys.stdout = EelLogger()
# Перехватываем ошибки тоже
sys.stderr = EelLogger()

# Глобальная переменная браузера
brow = None

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def address_parser_form_func(res):
    """Нормализация адреса (сокращения и переносы)"""
    original_res = res
    
    alternative = {
        r'\b[Уу]лица\b': 'ул.',
        r'\b[Пп]роспект\b': 'пр.',
        r'\b[Пп]росп\.?\s?': 'пр.',
        r'\b[Пп]ереулок\b': 'пер.',
        r'\b[Шш]оссе\b': 'ш.',
        r'\b[Бб]ульвар\b': 'б-р',
        r'\b[Мм]икрорайон\b': 'мкр-н',
        r'\b[Пп]лощадь\b': 'пл.',
        r'\b[Кк]вартал\b': 'кв-л',
        r'\b[Пп]роезд\b': 'пр-д',
        r'\b[Нн]абережная\b': 'наб.',
        r'\b[Аа]ллея\b': 'ал.',
        r'\b[Тт]ерритория\b': 'тер.',
    }
    replacements = {
        r'\s?[Уу]л\.\s?': ' ул. ',
        r'\s?[Пп]р\.\s?': ' пр. ',
        r'\s?[Пп]ер\.\s?': ' пер ',
        r'\s?[Шш]\.\s?': ' ш ',
        r'\s?[Бб]-р\s?': ' б-р ',
        r'\s?[Мм]кр-н\s?': ' мкр-н ',
        r'\s?[Пп]л\.\s?': ' пл ',
        r'\s?[Кк]в-л\s?': ' кв-л ',
        r'\s?[Пп]р-д\s?': ' пр-д ',
        r'\s?[Нн]аб\.\s?': ' наб. ',
        r'\s?[Аа]л\.\s?': ' ал. ',
        r'\s?[Тт]ер\.\s?': ' тер. ',
    }
    
    applied_shortcuts = []

    for pattern, repl in alternative.items():
        res, count = re.subn(pattern, repl, res)
        if count > 0:
            clean_repl = repl.strip()
            if clean_repl not in applied_shortcuts:
                applied_shortcuts.append(clean_repl)
                
    for pattern, repl in replacements.items():
        if re.search(pattern, res):
            res = re.sub(pattern, repl, res)
            before, sep, after = res.partition(repl[1:])
            res = sep + before.strip() + after
            
    res = re.sub(r'\s+', ' ', res).strip()
    
    if len(applied_shortcuts) > 1:
        print(f"⚠️ Предупреждение: В адресе обнаружено несколько типов сокращений {applied_shortcuts}!")
        print(f"   Оригинал: '{original_res}'")
        print(f"   Результат: '{res}'")
        print("-" * 50)
        
    return res, len(applied_shortcuts)

def url_changed(driver, previous_url):
    old_match = re.search(r'(?:ll|m)=([\d\.]+)%2C([\d\.]+)', previous_url)
    match_state = re.search(r'(?:ll|m)=([\d\.]+)%2C([\d\.]+)', driver.current_url)
    new_match = match_state if match_state is not None else old_match
    return f"{old_match.group(1)},{old_match.group(2)}" != f"{new_match.group(1)},{new_match.group(2)}"

def safe_action(action_func, max_retries=3, delay=0.5):
    for attempt in range(1, max_retries + 1):
        try:
            return action_func()
        except Exception as e:
            if attempt == max_retries:
                print(f"❌ Действие окончательно не удалось после {max_retries} попыток.")
                raise e
            sleep(delay)

find_input = lambda: WebDriverWait(brow, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.input__control")))

def safe_type_and_verify(focus_query, retries=5):
    safe_action(lambda: find_input().clear())
    safe_action(lambda: find_input().send_keys(focus_query))
    sleep(0.05)

    for _ in range(retries):
        stringfound = safe_action(lambda: brow.execute_script("return document.querySelector('input.input__control').value"))

        if stringfound == focus_query:
            return True

        if stringfound and focus_query.startswith(stringfound):
            missing = focus_query[len(stringfound):]
            safe_action(lambda: find_input().send_keys(missing))
        else:
            safe_action(lambda: find_input().clear())
            safe_action(lambda: find_input().send_keys(focus_query))
            
        sleep(0.05)

    final_check = safe_action(lambda: brow.execute_script("return document.querySelector('input.input__control').value"))
    return final_check == focus_query

# --- EEL ФУНКЦИИ ---

@eel.expose
def process_search_iteration(city, region, search_type, custom_text):
    """Открывает Яндекс Карты для конкретной итерации поиска"""
    global brow
    
    try:
        _ = brow.window_handles 
    except Exception:
        eel.updateStatus("Открытие браузера")
        service = Service(executable_path=GECKO_PATH)
        brow = webdriver.Firefox(service=service)
        eel.updateStatus("Открытие яндекс карт")
        brow.get("https://yandex.ru/maps/?ll=0.000000%2C0.000000&z=10")

    try:
        previous_url = brow.current_url

        focus_query = f"{city} {region}"
        safe_action(lambda: brow.execute_script("document.querySelector('input.input__control').click()"))

        eel.updateStatus(f"Поиск {focus_query}")
        if not safe_type_and_verify(focus_query):
            print(f"⚠️ Не удалось корректно ввести поисковый запрос для: {focus_query}")
            eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
        safe_action(lambda: find_input().send_keys(Keys.RETURN))

        if search_type != "standard":
            target_query = f"{custom_text} в {city} {region}".strip()

            WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))

            safe_action(lambda: find_input().send_keys(Keys.CONTROL + "a"))
            safe_action(lambda: find_input().send_keys(Keys.BACKSPACE))

            eel.updateStatus(f"Поиск {custom_text}")

            if not safe_type_and_verify(target_query):
                print(f"⚠️ Не удалось корректно ввести поисковый запрос для: {target_query}")
                eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
            safe_action(lambda: find_input().send_keys(Keys.RETURN))
        eel.updateStatus(f"Выберите здание в {city}")
    except Exception as e:
        print(f"❌ Ошибка при выполнении поиска: {e}")
        eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)

# Справочник регионов для областных центров, где Яндекс скрывает регион
REGIONAL_CAPITALS = {
    "москва": "Москва",
    "санкт-петербург": "Санкт-Петербург",
    "севастополь": "Севастополь",
    "волгоград": "Волгоградская область",
    "брянск": "Брянская область",
    "воронеж": "Воронежская область",
    "екатеринбург": "Свердловская область",
    "нижний новгород": "Нижегородская область",
    "новосибирск": "Новосибирская область",
    "ростов-на-дону": "Ростовская область",
    "самара": "Самарская область",
    "казань": "Республика Татарстан",
    "уфа": "Республика Башкортостан",
    "краснодар": "Краснодарский край",
    "красноярск": "Красноярский край",
    "владивосток": "Приморский край",
    "пермь": "Пермский край",
    "челябинск": "Челябинская область",
    "омск": "Омская область",
    "саратов": "Саратовская область",
    "тюмень": "Тюменская область",
    "барнаул": "Алтайский край",
    "иркутск": "Иркутская область",
    "ярославль": "Ярославская область",
    "владимир": "Владимирская область",
    "тула": "Тульская область",
    "хабаровск": "Хабаровский край",
    "ижевск": "Удмуртская Республика",
    "ульяновск": "Ульяновская область",
    "оренбург": "Оренбургская область",
    "кемерово": "Кемеровская область",
    "рязань": "Рязанская область",
    "астрахань": "Астраханская область",
    "пенза": "Пензенская область",
    "липецк": "Липецкая область",
    "киров": "Кировская область",
    "кирово-чепецк": "Кировская область",
    "чебоксары": "Чувашская Республика",
    "калининград": "Калининградская область",
    "курск": "Курская область",
    "ставрополь": "Ставропольский край",
    "тверь": "Тверская область",
    "иваново": "Ивановская область",
    "белгород": "Белгородская область",
    "калуга": "Калужская область",
    "архангельск": "Архангельская область",
    "чита": "Забайкальский край",
    "смоленск": "Смоленская область",
    "курган": "Курганская область",
    "вологда": "Вологодская область",
    "орел": "Орловская область",
    "орёл": "Орловская область",
    "владикавказ": "Республика Северная Осетия — Алания",
    "мурманск": "Мурманская область",
    "саранск": "Республика Мордовия",
    "тамбов": "Тамбовская область",
    "петрозаводск": "Республика Карелия",
    "кострома": "Костромская область",
    "йошкар-ола": "Республика Марий Эл",
    "сыктывкар": "Республика Коми",
    "нальчик": "Кабардино-Балкарская Республика",
    "благовещенск": "Амурская область",
    "якутск": "Республика Саха (Якутия)",
    "великий новгород": "Новгородская область",
    "псков": "Псковская область",
    "южно-сахалинск": "Сахалинская область",
    "абакан": "Республика Хакасия",
    "кызыл": "Республика Тыва",
    "майкоп": "Республика Адыгея",
    "черкесск": "Карачаево-Черкесская Республика",
    "теберда": "Карачаево-Черкесская Республика",
    "карачаевск": "Карачаево-Черкесская Республика",
    "магадан": "Магаданская область",
    "ханты-мансийск": "Ханты-Мансийский автономный округ — Югра",
    "салехард": "Ямало-Ненецкий автономный округ",
    "анадырь": "Чукотский автономный округ",
    "биробиджан": "Еврейская автономная область",
    "симферополь": "Республика Крым"
}

# Корпус исключений для поиска города
CITY_EXCEPTIONS = ("жилой район", "микрорайон", "промышленная зона", "снт", "административный округ", "исторический район", "район")

@eel.expose
def capture_map_data():
    """Извлекает данные с текущей открытой карточки объекта в Яндекс Картах"""
    try:
        address_element = brow.find_element(By.CLASS_NAME, "toponym-card-title-view__description")
        full_address_raw  = address_element.text

        parts = [p.strip() for p in full_address_raw.split(',') if p.strip()]

        # --- ШАГ 1: Сначала проверяем улицу на наличие сокращений ---
        street_part, shortcut_count = address_parser_form_func(parts[0])
        has_address_warning = (shortcut_count > 1) # Предупреждение, если сокращений больше одного

        city_warning = False
        type_warning = False
        city_part_index = 2

        # --- ШАГ 2: Определение индекса города ---
        if shortcut_count == 0:
            city_part_index = 0
            city_warning = True
            type_warning = True
            address_normalized = parts[1] if len(parts) > 1 else "" 
        else:
            if len(parts) > 2 and any(re.search(exc, parts[2].lower()) for exc in CITY_EXCEPTIONS):
                city_part_index = 3
            address_normalized = f"{street_part}, {parts[1]}" if len(parts) > 1 else street_part

        # --- ШАГ 3: Извлекаем город и тип НП из нужного индекса ---
        city_part = parts[city_part_index]
        type_match = re.search(r'^(пос[её]лок городского типа|рабочий пос[её]лок|город|пос[её]лок|деревня|село|станица|хутор|аул)\b\s*', city_part, re.IGNORECASE)
        if type_match:
            typeNP = type_match.group(1).strip().lower()
            city = city_part[type_match.end():].strip()
        else:
            typeNP = "город"
            city = city_part

        if re.match(r'^\d{6}$', parts[-1]):
            index = parts[-1]
            region = parts[-2]
        else:
            index = ""
            region = parts[-1]

        # --- ШАГ 4: Пытаемся найти регион ---
        region_clean = region.strip()
        if not any(marker in region_clean.lower() for marker in ["область", "край", "республика", "автономный округ"]):
            if "городской округ" in region_clean.lower():
                city = re.sub(r'(?i)городской округ', '', region_clean).strip()
            else:
                city = region_clean
            typeNP = "город"
            if city.lower() in REGIONAL_CAPITALS:
                region = REGIONAL_CAPITALS[city.lower()]

        translit_city = translit(str(city), 'ru', reversed=True).lower()
        translit_city = translit_city.replace(" ", "").replace("-", "").replace("'", "").replace("’", "")

        # --- ШАГ 5: ПОЛУЧЕНИЕ КООРДИНАТ ИЗ БЛОКА КАРТОЧКИ ---
        try:
            coords_el = brow.find_element(By.CLASS_NAME, "toponym-card-title-view__coords-badge")
            coords = coords_el.text.strip()
        except Exception as e:
            print(f"⚠️ Не удалось получить координаты из блока: {e}")
            coords = ""

        return {
            "city": city,
            "city_warning": city_warning,
            "translit_city": translit_city,
            "typeNP": typeNP,
            "type_warning": type_warning,
            "region": region,
            "address": address_normalized,
            "address_warning": has_address_warning,
            "full_address": full_address_raw,
            "coords": coords,
            "index": index,
            "comm": "",
        }
    except Exception as e:
        print(f"⚠️ Не удалось захватить данные: {type(e).__name__}: {e}")
        eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
        return None

@eel.expose
def save_captured_data(data):
    """Проверяет дубликаты и записывает новую строку в Google Таблицу """
    try:
        eel.updateStatus("Проверка данных")
        if not data['address'] or not data['city']:
            eel.showTempStatusWithTimer(f"❌ Ошибка: Город и Адрес обязательны", 3)
            return "error"

        existing_rows = []
        existing_rows += worksheet_rolling.get_all_values()
        existing_rows += worksheet_parser.get_all_values()

        for row in existing_rows:
            if len(row) >= 5:
                if (row[4].strip() == data['address'].strip()):
                    eel.showTempStatusWithTimer(f"❌ Дубликат: {data['address'].strip()}", 3)
                    return "Дубликат: Такие данные уже есть в таблице"

        if data['comm'] == "":
            data['comm'] = "---"

        eel.updateStatus("Сохранение данных")

        new_row = [
            data['city'],
            data['translit_city'],
            data['typeNP'],
            data['region'],
            data['address'],
            data['full_address'],
            data['coords'],
            data['index'],
            data['comm']
        ]

        worksheet_parser.append_row(new_row)
        eel.showTempStatusWithTimer("✅ Данные сохранены !", 3)
        return "success"
    except Exception as e:
        print(f"❌ Ошибка при сохранении данных: {e}")
        eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
        return "error"

@eel.expose
def sbor_start_func(addresses, cities, regions):
    """Пакетный сбор данных (Транслит, Координаты, Индекс)"""
    global brow

    max_len = max(len(addresses), len(cities), len(regions))
    addresses += [""] * (max_len - len(addresses))
    cities += [""] * (max_len - len(cities))
    regions += [""] * (max_len - len(regions))

    for i in range(max_len):
        try:
            _ = brow.window_handles
        except Exception:
            eel.updateStatus("Открытие браузера")
            service = Service(executable_path=GECKO_PATH)
            brow = webdriver.Firefox(service=service)
            eel.updateStatus("Открытие яндекс карт")
            brow.get("https://yandex.ru/maps/?ll=0.000000%2C0.000000&z=10")

        addr = addresses[i].strip()
        city = cities[i].strip()
        reg = regions[i].strip()
        reg_city = f"{reg} {city}".strip()
        full_query = f"{reg_city} {addr}".strip()

        if not addr and not city and not reg:
            eel.update_sbor_output("", "", "", "","")
            continue

        eel.updateStatus(f"Сбор [{i+1}/{max_len}]: {full_query}")

        if reg:
            safe_type_and_verify(reg)
            previous_url = brow.current_url
            safe_action(lambda: find_input().send_keys(Keys.ENTER))
            try:
                WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            except Exception:
                sleep(1)
        
        if reg_city and city:
            safe_type_and_verify(reg_city)
            previous_url = brow.current_url
            safe_action(lambda: find_input().send_keys(Keys.ENTER))
            try:
                WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            except Exception:
                sleep(1)

        if full_query and addr:
            safe_type_and_verify(full_query)
            previous_url = brow.current_url
            safe_action(lambda: find_input().send_keys(Keys.ENTER))
            try:
                WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            except Exception:
                sleep(1.5)

        index_val = ""
        coords_val = ""
        translit_val = ""
        error_msg = ""

        try:
            address_element = WebDriverWait(brow, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "toponym-card-title-view__description"))
            )
            parts = [p.strip() for p in address_element.text.split(',') if p.strip()]

            if re.match(r'^\d{6}$', parts[-1]):
                index_val = parts[-1]
                region_val = parts[-2]
            else:
                index_val = "Ошибка"
                region_val = parts[-1]
                error_msg = f"{i+1}: Индекс"

            coords_element = brow.find_element(By.CLASS_NAME, "toponym-card-title-view__coords-badge")
            coords_val = coords_element.text

            target_city = city
            if not target_city and parts:
                street_part, shortcut_count = address_parser_form_func(parts[0])
                city_part_index = 2

                if shortcut_count == 0:
                    city_part_index = 0
                else:
                    if len(parts) > 2 and any(re.search(exc, parts[2].lower()) for exc in CITY_EXCEPTIONS):
                        city_part_index = 3

                if city_part_index < len(parts):
                    city_part = parts[city_part_index]
                else:
                    city_part = parts[-1]

                type_match = re.search(r'^(пос[её]лок городского типа|рабочий пос[её]лок|город|пос[её]лок|деревня|село|станица|хутор|аул)\b\s*', city_part, re.IGNORECASE)
                if type_match:
                    target_city = city_part[type_match.end():].strip()
                else:
                    target_city = city_part

            region_clean = region_val.strip()
            if not any(marker in region_clean.lower() for marker in ["область", "край", "республика", "автономный округ"]) and target_city.lower() in REGIONAL_CAPITALS:
                region_val = REGIONAL_CAPITALS[city.lower()]

            if target_city:
                t_city = translit(str(target_city), 'ru', reversed=True).lower()
                translit_val = t_city.replace(" ", "").replace("-", "").replace("'", "").replace("’", "")

        except Exception as e:
            print(f"Ошибка извлечения для '{full_query}': {e}")
            index_val = "Ошибка"
            coords_val = "Ошибка"
            translit_val = "Ошибка"
            region_val = "Ошибка"
            error_msg = f"{i+1}: Ошибка".strip() 

        eel.update_sbor_output(translit_val, coords_val, region_val, index_val, error_msg)

    eel.enableSborButton()()
    eel.showTempStatusWithTimer("✅ Сбор дополнений завершен", 3)

@eel.expose
def raskatka_start_func(cities, regions, comm, base):
    """Сбор с базы (Адресс, Транслит, Регион, Координаты, Индекс)"""
    eel.updateStatus("Загрузка данных из таблиц")
    base_rows = []
    if re.search("rolling", base):
        base_rows += worksheet_rolling.get_all_values()
    if re.search("parser", base):
        base_rows += worksheet_parser.get_all_values()

    out_addresses = []
    out_translits = []
    out_regions = []
    out_coords = []
    out_indexes = []
    out_errors = []

    empty_row = [""] * 9
    
    max_len = max(len(comm), len(cities), len(regions))
    cities += [""] * (max_len - len(cities))
    regions += [""] * (max_len - len(regions))
    comm += [""] * (max_len - len(comm))

    eel.updateStatus("Процесс поиска")

    for i in range(max_len):
        city_one = cities[i].strip()
        reg_one = regions[i].strip()
        comm_one = comm[i].strip()

        if not city_one:
            out_addresses.append("")
            out_translits.append("")
            out_regions.append("")
            out_coords.append("")
            out_indexes.append("")
            out_errors.append(f"{i+1}: город не указан")
            continue

        good_rows = []

        for row in base_rows:
            if row[0].strip().lower() != city_one.lower():
                continue
            if reg_one and row[3].strip().lower() != reg_one.lower():
                continue
            if comm_one and row[8].strip().lower() != comm_one.lower():
                continue
            good_rows.append(row)
        
        if good_rows:
            chosen = random.choice(good_rows)
            out_addresses.append(chosen[4])
            out_translits.append(chosen[1])
            out_regions.append(chosen[3])
            out_coords.append(chosen[6])
            out_indexes.append(chosen[7])
            out_errors.append("")
        else:
            out_addresses.append("")
            out_translits.append("")
            out_regions.append("")
            out_coords.append("")
            out_indexes.append("")
            error_details = f"{i+1}: {city_one}"
            if reg_one:
                error_details += f", {reg_one}"
            if comm_one:
                error_details += f" ({comm_one})"
            out_errors.append(error_details)

    eel.updateRaskatkaResults(
        out_addresses,
        out_translits,
        out_regions,
        out_coords,
        out_indexes,
        out_errors
    )

    eel.enableRaskatkaButton()()
    eel.showTempStatusWithTimer("✅ Подбор данных завершен", 3)

# --- ЗАПУСК ---

if __name__ == "__main__":
    # Скрываем черное окно системной консоли (CMD)
    # Используем 0 (SW_HIDE) вместо 6, чтобы полностью скрыть консоль
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 0) 

    # Инициализация Eel
    eel.init(WEB_PATH)
    
    # Чтобы UI успел загрузиться перед тем как мы начнем отправлять логи запуска API,
    # мы запускаем интерфейс в неблокирующем режиме с помощью block=False
    print("🚀 Приложение запускается...", flush=True)
    
    # Запускаем Eel, отдаем контроль потоку
    eel.start("index.html", size=(1000, 1200), port=7000, block=False)
    
    # Даем интерфейсу полсекунды на прогрузку DOM
    sleep(0.5) 
    
    print("Выполнение проверок API и баз данных...", flush=True)
    
    # Выводим сообщение о готовности и включаем кнопку в UI
    print("✅ Все системы готовы к работе!", flush=True)
    try:
        eel.enableAppEntry()()
    except:
        pass
    
    # Оставляем процесс висеть бесконечно (замена block=True)
    while True:
        eel.sleep(1.0)
    