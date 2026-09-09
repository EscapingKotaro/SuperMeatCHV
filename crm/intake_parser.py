"""Импорт текстовых заявок. Неизвестные поля сохраняются в исходном тексте."""
import re


def parse_application(raw):
    result = {}
    notes = []
    question = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.casefold().replace("ё", "е")
        if key == "вопрос":
            question = value.casefold().replace("ё", "е")
            continue
        if key == "ответ":
            key = question
        if not value:
            continue
        if "телефон" in key or key in {"phone", "tel", "номер"}:
            digits = re.sub(r"\D", "", value)
            result["phone"] = ("+7" + digits[1:] if len(digits) == 11 and digits[0] in "78" else value)[:30]
        elif "возраст" in key and ("имя" in key or "фио" in key):
            match = re.search(r"(?:возраст\s*)?(\d{1,2})(?:[,.](\d{1,2}))?\s*(?:лет|года?|г\.?)(?!\w)", value, re.I)
            if match:
                result["age_text"] = (match[1] + ("," + match[2] if match[2] else ""))
                name = (value[:match.start()] + value[match.end():]).strip(" ,;.-")
                name = re.sub(r"^(?:имя|ребенок|ребёнок)\s*[:—-]?\s*", "", name, flags=re.I)
                if name:
                    result["full_name"] = name[:220]
            elif re.search(r"[а-яa-z]", value, re.I):
                result["full_name"] = value[:220]
        elif key in {"имя", "фио", "name", "имя ребенка", "фио ребенка"} or "как зовут" in key:
            result["full_name"] = value[:220]
        elif "возраст" in key or "сколько лет" in key:
            result["age_text"] = value[:30]
        elif key in {"источник", "source", "utm_source"}:
            result["source"] = value[:100]
        else:
            notes.append(f"{key}: {value}")
    # Retain attribution, callback preferences and unrecognized answers losslessly.
    result["comment"] = "\n".join(notes + ["Исходная заявка:", raw])
    return result
