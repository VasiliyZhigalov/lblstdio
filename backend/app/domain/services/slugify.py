from __future__ import annotations

import re

_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def latin_slug(value: str, *, fallback: str = "model") -> str:
    """Transliterate to a lowercase ASCII slug suitable for model names."""
    chars: list[str] = []
    for char in value.strip().lower():
        if char in _CYRILLIC_TO_LATIN:
            chars.append(_CYRILLIC_TO_LATIN[char])
        elif "a" <= char <= "z" or "0" <= char <= "9":
            chars.append(char)
        elif char in {" ", "-", "_", ".", "/"}:
            chars.append("_")
        else:
            chars.append("_")
    slug = re.sub(r"_+", "_", "".join(chars)).strip("_")
    return slug or fallback


def trained_model_name(project_name: str, version_number: int) -> str:
    return f"{latin_slug(project_name)}_v{version_number}"
