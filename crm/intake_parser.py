"""Импорт текстовых заявок из сайта и рекламных форм без потери исходных данных."""
import re
from datetime import datetime
from django.utils import timezone


def _key(value):
    """Нормализует ключ: нижний регистр, замена ё на е, удаление лишних пробелов и знаков препинания."""
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip(" ?.!\t")


def _phone(value):
    """Приводит телефон к формату +7XXXXXXXXXX."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return value[:30]


def _age(value):
    """Извлекает возраст (например, '6', '5,5') из строки."""
    match = re.search(r"(\d{1,2})(?:[,.](\d{1,2}))?", value)
    if not match:
        return value[:30]
    return match[1] + ("," + match[2] if match[2] else "")


def _date(value):
    """Парсит только дату."""
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _datetime(value):
    """Парсит дату и время, корректно удаляя указания часовых поясов вроде (МСК)."""
    cleaned = re.sub(r"\s*\((?:мск|msk|utc\s*\+?3)\)\s*$", "", value, flags=re.I).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        except ValueError:
            continue
    return None


def _name_and_age(value):
    """
    Извлекает возраст и имя из комбинированной строки (например, "Арсений 6 лет").
    Игнорирует ответы вроде "предпочел не отвечать".
    """
    match = re.search(
        r"(?:возраст\s*)?(\d{1,2})(?:[,.](\d{1,2}))?\s*(?:лет|года?|г\.?)(?!\w)",
        value,
        re.I,
    )
    
    # Проверка на отказ от ответа
    if re.search(r"предпочел\s+не\s+отвечать|не\s+указано|нет\s+ответа", value, re.I):
        return None, None

    if not match:
        # Если возраста нет, но есть текст, возвращаем его как имя (если это не мусор)
        return None, value.strip() if re.search(r"[а-яa-z]", value, re.I) else None

    age = match[1] + ("," + match[2] if match[2] else "")
    
    # Вырезаем возраст из строки, чтобы получить чистое имя
    name = (value[:match.start()] + value[match.end():]).strip(" ,;.-")
    name = re.sub(r"^(?:имя|фио|ребенок|ребёнок)\s*[:—-]?\s*", "", name, flags=re.I).strip()
    
    # Дополнительная проверка имени на "мусор"
    if re.search(r"предпочел\s+не\s+отвечать|не\s+указано", name, re.I):
        name = None
        
    return age, name or None


def parse_application(raw):
    raw = (raw or "").strip()
    result = {}
    notes = []
    
    question = ""
    question_label = ""

    form_name = ""
    callback = ""
    ad_url = ""
    campaign = ""
    ad_group = ""
    ad_name = ""

    for source_line in raw.splitlines():
        line = source_line.strip()
        if not line or ":" not in line:
            continue

        label, value = (part.strip() for part in line.split(":", 1))
        key = _key(label)

        # Логика обработки пар Вопрос-Ответ
        if key == "вопрос":
            question = _key(value)
            question_label = value
            continue

        display_label = label
        if key == "ответ":
            key = question
            display_label = question_label or "Ответ"

        if not value:
            continue

        # 1. Телефон
        if "телефон" in key or key in {"phone", "tel", "номер", "мобильный"}:
            result["phone"] = _phone(value)
        
        # 2. Имя и возраст в одной строке (например, "Арсений 6 лет" в ответе на вопрос)
        elif "возраст" in key and ("имя" in key or "фио" in key or "ребенк" in key):
            age, name = _name_and_age(value)
            if age:
                result["age_text"] = age
            if name:
                existing_name = result.get("full_name")
                # Если имя родителя уже есть, добавляем имя ребенка для полноты картины
                if existing_name and name.lower() not in existing_name.lower():
                    result["full_name"] = f"{existing_name} (ребёнок: {name})"[:220]
                else:
                    result["full_name"] = name[:220]
        
        # 3. Только имя
        elif key in {"имя", "фио", "name", "имя ребенка", "фио ребенка"} or "как зовут" in key:
            if not re.search(r"предпочел\s+не\s+отвечать", value, re.I):
                result["full_name"] = value[:220]
        
        # 4. Только возраст (добавлен key == "age" для английских форм)
        elif "возраст" in key or "сколько лет" in key or key == "age":
            if not re.search(r"предпочел\s+не\s+отвечать", value, re.I):
                result["age_text"] = _age(value)
        
        # 5. Дата рождения
        elif key in {"дата рождения", "день рождения", "birth date", "birth_date"}:
            parsed = _date(value)
            if parsed:
                result["birth_date"] = parsed
            else:
                notes.append(f"{display_label}: {value}")
        
        # 6. Дата и время пробного (если указана полная дата)
        elif "пробн" in key and ("дата" in key or "время" in key):
            parsed = _datetime(value)
            if parsed:
                result["trial_at"] = parsed
            else:
                notes.append(f"{display_label}: {value}") # Например, "Понедельник 10:00" уйдет сюда
        
        # 7. Источник и UTM
        elif key in {"источник", "source", "utm_source"}:
            result["source"] = value[:100]
        
        # 8. Дата отправки заявки
        elif key in {"дата отправки", "дата заявки", "отправлено", "submitted at", "submitted_at"}:
            parsed = _datetime(value)
            if parsed:
                result["submitted_at"] = parsed
            else:
                notes.append(f"{display_label}: {value}")
        
        # 9. Перезвон
        elif ("время" in key and "звон" in key) or "перезвон" in key:
            callback = value
        
        # 10. Рекламные метаданные
        elif "переход с рекламного объявления" in key or key in {"рекламная ссылка", "ссылка на рекламу", "ad_url"}:
            ad_url = value
        elif key in {"кампания", "campaign", "utm_campaign"}:
            campaign = value
        elif key in {"группа", "группа объявлений", "ad group", "ad_group"} or "группа объяв" in key:
            ad_group = value
        elif key in {"объявление", "advert", "ad"}:
            ad_name = value
        elif key.startswith("новая заявка по форме") or key == "форма":
            form_name = value
        
        # 11. Всё остальное (например, gender: Мальчик)
        else:
            notes.append(f"{display_label}: {value}")

    # Умное определение источника, если он не был явно указан в полях
    if not result.get("source"):
        if ad_url and re.search(r"(?:^|[/.])(?:ads\.)?vk\.ru(?:[/:]|$)", ad_url, re.I):
            result["source"] = "VK Реклама"
        elif form_name:
            result["source"] = f"Форма: {form_name}"[:100]
        else:
            result["source"] = "Реклама" # Fallback (дублирует логику во view для надежности)

    # Сборка комментария
    metadata = [
        ("Форма", form_name),
        ("Удобное время для звонка", callback),
        ("Переход с рекламного объявления", ad_url),
        ("Кампания", campaign),
        ("Группа объявлений", ad_group),
        ("Объявление", ad_name),
    ]
    
    # Добавляем в notes только непустые метаданные
    notes.extend(f"{label}: {value}" for label, value in metadata if value)

    comment_parts = notes[:]
    if raw:
        comment_parts.extend(["", "=== Исходная заявка ===", raw])
    
 #   result["comment"] = "\n".join(comment_parts).strip()
    return result