import eel
import os
import sys
import json
import time
import shutil
import zipfile
import io
import random
import re
import gspread
import requests
import ctypes
import subprocess
from time import sleep
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from transliterate import translit

# Пути к файлам
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(UTILS_DIR)

JSON_KEY = os.path.join(UTILS_DIR, "raskatka-adressov-591861b40918.json")
GECKO_PATH = os.path.join(UTILS_DIR, "geckodriver.exe")
WEB_PATH = os.path.join(BASE_DIR, "web")
VERSION_FILE = os.path.join(BASE_DIR, "version.json")
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/Miu-kontent/Raskatka/main/version.json"
GITHUB_ZIP_URL = "https://api.github.com/repos/Miu-kontent/Raskatka/zipball/main"

# Глобальные переменные для БД и браузера
brow = None
sh = None
worksheet_rolling = None
worksheet_parser = None

# --- ВЕРСИЯ И ОБНОВЛЕНИЕ ---

def parse_version(version_str):
    """Парсит строку версии 'X.Y.Z' в кортеж целых чисел"""
    try:
        parts = str(version_str).strip().split('.')
        return tuple(int(p) for p in parts[:3])
    except Exception:
        return (0, 0, 0)

def get_local_version():
    """Читает локальную версию из version.json"""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ver = data.get("version", "0.0.0")
        return ver.strip()
    except Exception:
        return "0.0.0"

def check_remote_version():
    """Проверяет версию на GitHub с cache-busting. Возвращает строку версии или None"""
    try:
        cache_buster = f"?nocache={int(time.time())}"
        headers = {"Cache-Control": "no-cache"}
        resp = requests.get(GITHUB_VERSION_URL + cache_buster, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            ver = data.get("version")
            if ver:
                return ver.strip()
    except Exception:
        pass
    return None

@eel.expose
def update_app():
    """Скачивает и распаковывает обновление"""
    try:
        eel.addLog("🔄 Скачивание обновления...")
        headers = {"Cache-Control": "no-cache"}
        cache_buster = f"?nocache={int(time.time())}"

        resp = requests.get(GITHUB_ZIP_URL + cache_buster, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

        eel.addLog("📦 Распаковка обновления...")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            root_prefix = z.namelist()[0].split('/')[0] + '/'
            for member in z.namelist():
                if member == root_prefix:
                    continue
                norm_path = member.replace("\\", "/")
                if norm_path.startswith((".git/", ".venv")):
                    continue
                if "raskatka-adressov-591861b40918.json" in norm_path:
                    continue

                rel_path = member[len(root_prefix):]
                if not rel_path:
                    continue

                target_path = os.path.join(BASE_DIR, rel_path)
                if member.endswith('/'):
                    os.makedirs(target_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with z.open(member) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)

        eel.addLog("✅ Обновление успешно распаковано!")
        return {"success": True}
    except Exception as e:
        eel.addLog(f"❌ Ошибка обновления: {e}")
        return {"success": False, "message": str(e)}

@eel.expose
def restart_app():
    """Чистый перезапуск приложения"""
    subprocess.Popen([sys.executable] + sys.argv)
    sys.exit(0)

# --- ИНИЦИАЛИЗАЦИЯ И ПРОВЕРКИ ---

@eel.expose
def run_initial_checks():
    """Асинхронная проверка API и подключение к таблицам при старте UI"""
    global sh, worksheet_rolling, worksheet_parser

    # --- ШАГ 1: Проверка версии ---
    local_ver = get_local_version()
    remote_ver = check_remote_version()

    if remote_ver and parse_version(remote_ver) > parse_version(local_ver):
        eel.addLog(f"⚠️ Доступна новая версия: {remote_ver}")
        return {"success": False, "new_version": remote_ver, "local_version": local_ver}

    if remote_ver:
        eel.addLog(f"✅ Версия актуальна ({local_ver})")
    else:
        eel.addLog("⚠️ Не удалось проверить версию на GitHub (продолжение работы)")

    # --- ШАГ 2: Проверка Google API ---
    eel.addLog("🔌 Проверка Google API...")
    try:
        resp = requests.get("https://www.googleapis.com/discovery/v1/apis/sheets/v4/rest", timeout=10)
        if resp.status_code != 200:
            eel.addLog(f"❌ Google API вернул код {resp.status_code}")
            if resp.status_code in (502, 503, 504):
                eel.addLog("⚠️ Сервер Google временно недоступен. Рекомендуется проверить VPN и перезапустить приложение.")
            return {"success": False, "message": f"Google API ошибка {resp.status_code}"}
        eel.addLog("✅ Google API доступен")
    except Exception as e:
        eel.addLog(f"❌ Ошибка подключения к Google API: {e}")
        eel.addLog("⚠️ Рекомендуется проверить VPN и перезапустить приложение.")
        return {"success": False, "message": f"Ошибка API: {str(e)}"}

    # --- ШАГ 3: Подключение к таблице ---
    eel.addLog("📊 Подключение к Google Таблице 'Раскатка адрессов'...")
    try:
        with open(JSON_KEY, "r", encoding="utf-8-sig") as f:
            credentials_data = json.load(f)
        service_account = gspread.service_account_from_dict(credentials_data)
        sh = service_account.open("Раскатка адрессов")
        eel.addLog("✅ Подключено к таблице 'Раскатка адрессов'")
    except Exception as e:
        eel.addLog(f"❌ Ошибка подключения к таблице: {e}")
        eel.addLog("⚠️ Рекомендуется проверить VPN и перезапустить приложение.")
        return {"success": False, "message": f"Ошибка таблицы: {str(e)}"}

    # --- ШАГ 4: Подключение к листу Rolling ---
    eel.addLog("📄 Подключение к листу Rolling...")
    try:
        worksheet_rolling = sh.worksheet("Rolling")
        eel.addLog("✅ Подключено к листу Rolling")
    except Exception as e:
        eel.addLog(f"❌ Ошибка подключения к листу Rolling: {e}")
        return {"success": False, "message": f"Ошибка Rolling: {str(e)}"}

    # --- ШАГ 5: Подключение к листу Parser ---
    eel.addLog("📄 Подключение к листу Parser...")
    try:
        worksheet_parser = sh.worksheet("Parser")
        eel.addLog("✅ Подключено к листу Parser")
    except Exception as e:
        eel.addLog(f"❌ Ошибка подключения к листу Parser: {e}")
        return {"success": False, "message": f"Ошибка Parser: {str(e)}"}

    eel.addLog(f"Инициализация завершена. Все системы готовы к работе!")
    return {"success": True, "message": "Все системы готовы к работе!"}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def address_parser_form_func(res):
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

# Справочник регионов
REGIONAL_CAPITALS = {
    "москва": "Москва", "санкт-петербург": "Санкт-Петербург", "севастополь": "Севастополь",
    "волгоград": "Волгоградская область", "брянск": "Брянская область", "воронеж": "Воронежская область",
    "екатеринбург": "Свердловская область", "нижний новгород": "Нижегородская область",
    "новосибирск": "Новосибирская область", "ростов-на-дону": "Ростовская область",
    "самара": "Самарская область", "казань": "Республика Татарстан", "уфа": "Республика Башкортостан",
    "краснодар": "Краснодарский край", "красноярск": "Красноярский край", "владивосток": "Приморский край",
    "пермь": "Пермский край", "челябинск": "Челябинская область", "омск": "Омская область",
    "саратов": "Саратовская область", "тюмень": "Тюменская область", "барнаул": "Алтайский край",
    "иркутск": "Иркутская область", "ярославль": "Ярославская область", "владимир": "Владимирская область",
    "тула": "Тульская область", "хабаровск": "Хабаровский край", "ижевск": "Удмуртская Республика",
    "ульяновск": "Ульяновская область", "оренбург": "Оренбургская область", "кемерово": "Кемеровская область",
    "рязань": "Рязанская область", "астрахань": "Астраханская область", "пенза": "Пензенская область",
    "липецк": "Липецкая область", "киров": "Кировская область", "кирово-чепецк": "Кировская область",
    "чебоксары": "Чувашская Республика", "калининград": "Калининградская область", "курск": "Курская область",
    "ставрополь": "Ставропольский край", "тверь": "Тверская область", "иваново": "Ивановская область",
    "белгород": "Белгородская область", "калуга": "Калужская область", "архангельск": "Архангельская область",
    "чита": "Забайкальский край", "смоленск": "Смоленская область", "курган": "Курганская область",
    "вологда": "Вологодская область", "орел": "Орловская область", "орёл": "Орловская область",
    "владикавказ": "Республика Северная Осетия — Алания", "мурманск": "Мурманская область",
    "саранск": "Республика Мордовия", "тамбов": "Тамбовская область", "петрозаводск": "Республика Карелия",
    "кострома": "Костромская область", "йошкар-ола": "Республика Марий Эл", "сыктывкар": "Республика Коми",
    "нальчик": "Кабардино-Балкарская Республика", "благовещенск": "Амурская область",
    "якутск": "Республика Саха (Якутия)", "великий новгород": "Новгородская область", "псков": "Псковская область",
    "южно-сахалинск": "Сахалинская область", "абакан": "Республика Хакасия", "кызыл": "Республика Тыва",
    "майкоп": "Республика Адыгея", "черкесск": "Карачаево-Черкесская Республика",
    "теберда": "Карачаево-Черкесская Республика", "карачаевск": "Карачаево-Черкесская Республика",
    "магадан": "Магаданская область", "ханты-мансийск": "Ханты-Мансийский автономный округ — Югра",
    "салехард": "Ямало-Ненецкий автономный округ", "анадырь": "Чукотский автономный округ",
    "биробиджан": "Еврейская автономная область", "симферополь": "Республика Крым"
}

CITY_EXCEPTIONS = ("жилой район", "микрорайон", "промышленная зона", "снт", "административный округ", "исторический район", "район")

# --- EEL ФУНКЦИИ ---

@eel.expose
def process_search_iteration(city, region, search_type, custom_text):
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
            eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
        safe_action(lambda: find_input().send_keys(Keys.RETURN))

        if search_type != "standard":
            target_query = f"{custom_text} в {city} {region}".strip()
            WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            safe_action(lambda: find_input().send_keys(Keys.CONTROL + "a"))
            safe_action(lambda: find_input().send_keys(Keys.BACKSPACE))
            eel.updateStatus(f"Поиск {custom_text}")
            if not safe_type_and_verify(target_query):
                eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
            safe_action(lambda: find_input().send_keys(Keys.RETURN))
        eel.updateStatus(f"Выберите здание в {city}")
    except Exception as e:
        eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)

@eel.expose
def capture_map_data():
    try:
        address_element = brow.find_element(By.CLASS_NAME, "toponym-card-title-view__description")
        full_address_raw  = address_element.text
        parts = [p.strip() for p in full_address_raw.split(',') if p.strip()]

        street_part, shortcut_count = address_parser_form_func(parts[0])
        has_address_warning = (shortcut_count > 1)

        city_warning = False
        type_warning = False
        city_part_index = 2

        if shortcut_count == 0:
            city_part_index = 0
            city_warning = True
            type_warning = True
            address_normalized = parts[1] if len(parts) > 1 else ""
        else:
            if len(parts) > 2 and any(re.search(exc, parts[2].lower()) for exc in CITY_EXCEPTIONS):
                city_part_index = 3
            address_normalized = f"{street_part}, {parts[1]}" if len(parts) > 1 else street_part

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

        try:
            coords_el = brow.find_element(By.CLASS_NAME, "toponym-card-title-view__coords-badge")
            coords = coords_el.text.strip()
        except Exception as e:
            print(f"⚠️ Не удалось получить координаты из блока: {e}")
            coords = ""

        return {
            "city": city, "city_warning": city_warning, "translit_city": translit_city,
            "typeNP": typeNP, "type_warning": type_warning, "region": region,
            "address": address_normalized, "address_warning": has_address_warning,
            "full_address": full_address_raw, "coords": coords, "index": index, "comm": "",
        }
    except Exception as e:
        eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
        return None

@eel.expose
def save_captured_data(data):
    try:
        eel.updateStatus("Проверка данных")
        if not data['address'] or not data['city']:
            eel.showTempStatusWithTimer(f"❌ Ошибка: Город и Адрес обязательны", 3)
            return "error"

        existing_rows = []
        if worksheet_rolling: existing_rows += worksheet_rolling.get_all_values()
        if worksheet_parser: existing_rows += worksheet_parser.get_all_values()

        for row in existing_rows:
            if len(row) >= 5:
                if (row[4].strip() == data['address'].strip()):
                    eel.showTempStatusWithTimer(f"❌ Дубликат: {data['address'].strip()}", 3)
                    return "Дубликат: Такие данные уже есть в таблице"

        if data['comm'] == "":
            data['comm'] = "---"

        eel.updateStatus("Сохранение данных")

        new_row = [
            data['city'], data['translit_city'], data['typeNP'], data['region'],
            data['address'], data['full_address'], data['coords'], data['index'], data['comm']
        ]

        if worksheet_parser: worksheet_parser.append_row(new_row)
        eel.showTempStatusWithTimer("✅ Данные сохранены !", 3)
        return "success"
    except Exception as e:
        eel.showTempStatusWithTimer(f"❌ Непредвиденная ошибка", 3)
        return "error"

@eel.expose
def sbor_start_func(addresses, cities, regions):
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
            try: WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            except: sleep(1)

        if reg_city and city:
            safe_type_and_verify(reg_city)
            previous_url = brow.current_url
            safe_action(lambda: find_input().send_keys(Keys.ENTER))
            try: WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            except: sleep(1)

        if full_query and addr:
            safe_type_and_verify(full_query)
            previous_url = brow.current_url
            safe_action(lambda: find_input().send_keys(Keys.ENTER))
            try: WebDriverWait(brow, 10).until(lambda d: url_changed(d, previous_url))
            except: sleep(1.5)

        index_val, coords_val, translit_val, error_msg = "", "", "", ""

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
            index_val, coords_val, translit_val, region_val = "Ошибка", "Ошибка", "Ошибка", "Ошибка"
            error_msg = f"{i+1}: Ошибка".strip()

        eel.update_sbor_output(translit_val, coords_val, region_val, index_val, error_msg)

    eel.enableSborButton()()
    eel.showTempStatusWithTimer("✅ Сбор дополнений завершен", 3)

@eel.expose
def raskatka_start_func(cities, regions, comm, base):
    eel.updateStatus("Загрузка данных из таблиц")
    base_rows = []
    if re.search("rolling", base) and worksheet_rolling:
        base_rows += worksheet_rolling.get_all_values()
    if re.search("parser", base) and worksheet_parser:
        base_rows += worksheet_parser.get_all_values()

    out_addresses, out_translits, out_regions, out_coords, out_indexes, out_errors = [], [], [], [], [], []

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
            if row[0].strip().lower() != city_one.lower(): continue
            if reg_one and row[3].strip().lower() != reg_one.lower(): continue
            if comm_one and row[8].strip().lower() != comm_one.lower(): continue
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
            if reg_one: error_details += f", {reg_one}"
            if comm_one: error_details += f" ({comm_one})"
            out_errors.append(error_details)

    eel.updateRaskatkaResults(out_addresses, out_translits, out_regions, out_coords, out_indexes, out_errors)
    eel.enableRaskatkaButton()()
    eel.showTempStatusWithTimer("✅ Подбор данных завершен", 3)

if __name__ == "__main__":
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 0)

    eel.init(WEB_PATH)

    eel.start("index.html", size=(1000, 1200), port=7000)