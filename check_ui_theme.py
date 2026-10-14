"""Проверка темы Dark Pro (styles.py и использование цветов в main.py).

Запуск из корня проекта:  python check_ui_theme.py
PySide6 для этой проверки не нужен. Файлы проекта не меняются.

Зачем: если в тексте стилей (QSS) будет синтаксическая ошибка, Qt молча
отбросит ВЕСЬ глобальный стиль, и приложение станет непонятно выглядеть.
Эта проверка ловит такие ошибки, остатки светлой темы и слабый контраст
ещё до запуска окна.
"""

import re
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
UI_DIR = PROJECT_ROOT / "src" / "konspekt" / "ui"

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from konspekt.ui import styles  # noqa: E402

failures = 0

# Свойства QSS, которые мы используем (опечатка в названии не пройдёт).
KNOWN_PROPERTIES = {
    "background", "background-color", "border", "border-top", "border-right",
    "border-bottom", "border-left", "border-radius", "color", "font-size",
    "font-weight", "margin", "padding", "min-height", "min-width", "height",
    "width", "text-align", "selection-background-color", "selection-color",
    "outline",
}
KNOWN_STATES = {
    "hover", "pressed", "focus", "disabled", "checked", "on", "selected",
    "vertical", "horizontal",
}
KNOWN_SUBCONTROLS = {
    "handle", "add-line", "sub-line", "add-page", "sub-page", "chunk",
    "item", "separator",
}
# Типы виджетов, которые есть в приложении и обязаны иметь правила.
REQUIRED_TYPES = [
    "QLabel", "QDialog", "QToolTip", "QPushButton", "QLineEdit", "QTextEdit",
    "QComboBox", "QProgressBar", "QMenu", "QScrollBar",
]
# Цвета прежней светлой темы: в новой теме их быть не должно.
OLD_LIGHT_COLORS = {
    "#F4F6FA", "#E5E7EB", "#EEF0F4", "#1F2937", "#6B7280", "#4F6BED",
    "#3F59D6", "#364DC0", "#AAB6F5", "#B91C1C", "#1E2433", "#C9D1E0",
    "#7C879E", "#283049", "#323C5A", "#CBD2DC", "#AEB7C4", "#D1D5DB",
}


def check(condition: bool, description: str) -> None:
    """Печатает OK или FAIL для одной проверки."""
    global failures
    if condition:
        print(f"  OK    {description}")
    else:
        failures += 1
        print(f"  FAIL  {description}")


def luminance(color: str) -> float:
    color = color.lstrip("#")
    channels = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    a, b = luminance(first), luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def parse_rules(css: str):
    """Разбирает QSS на правила. Возвращает (правила, остаток вне правил)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    pattern = re.compile(r"([^{}]+)\{([^{}]*)\}")
    rules = [(m.group(1).strip(), m.group(2)) for m in pattern.finditer(css)]
    leftover = pattern.sub("", css).strip()
    return rules, leftover


def declarations(body: str):
    """Список (свойство, значение) и признак, что каждая строка закончена точкой с запятой."""
    result = []
    well_formed = body.strip().endswith(";") or not body.strip()
    for part in body.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            well_formed = False
            continue
        name, value = part.split(":", 1)
        result.append((name.strip(), value.strip()))
    return result, well_formed


def main() -> None:
    colors = styles.COLORS
    stylesheet = styles.build_stylesheet()
    template = styles._QSS_TEMPLATE
    rules, leftover = parse_rules(stylesheet)

    print("1. Палитра")
    bad_colors = [n for n, v in colors.items() if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) is None]
    check(not bad_colors, f"все цвета записаны как #RRGGBB (ошибки: {bad_colors})")
    expected = {
        "BACKGROUND": "#111318", "SURFACE": "#181A22", "CARD": "#1F222C",
        "BORDER": "#303442", "INPUT_BORDER": "#4A5066", "TEXT": "#F3F4F6",
        "MUTED": "#A1A1AA", "ACCENT": "#7C3AED", "ACCENT_HOVER": "#8B5CF6",
        "ACCENT_PRESSED": "#6D28D9", "ACCENT_TEXT": "#A78BFA",
        "SUCCESS": "#34D399", "WARNING": "#FBBF24", "DANGER": "#F87171",
    }
    wrong = {n: colors.get(n) for n, v in expected.items() if colors.get(n) != v}
    check(not wrong, f"основные цвета совпадают с утверждённой палитрой Dark Pro ({wrong})")

    print("2. Сборка стилей")
    check("@" not in stylesheet, "после подстановки не осталось неразобранных @ИМЯ@")
    used = set(re.findall(r"@([A-Z_]+)@", template))
    check(used <= set(colors), f"все цвета из стилей есть в палитре (нет: {sorted(used - set(colors))})")
    check(stylesheet.count("{") == stylesheet.count("}"), "скобки { } сбалансированы")
    check(leftover == "", f"вне правил нет лишнего текста ({leftover[:40]!r})")
    check(len(rules) >= 50, f"правил достаточно: {len(rules)}")

    print("3. Синтаксис правил (ошибка тут обнулила бы весь стиль)")
    problems = []
    for selector, body in rules:
        parts = [s.strip() for s in selector.split(",")]
        if any(not s for s in parts):
            problems.append(f"пустой селектор в «{selector}»")
        decls, well_formed = declarations(body)
        if not well_formed:
            problems.append(f"{selector}: объявление без «;» или без «:»")
        if not decls:
            problems.append(f"{selector}: правило без объявлений")
        for name, value in decls:
            if name not in KNOWN_PROPERTIES:
                problems.append(f"{selector}: неизвестное свойство «{name}»")
            if not value:
                problems.append(f"{selector}: пустое значение у «{name}»")
            if ":" in value or "\n" in value:
                problems.append(f"{selector}: в значении «{name}» есть «:» или перенос строки (пропущена «;»?)")
        for colons, word in re.findall(r"(::?)([a-z][a-z-]*)", selector):
            known = KNOWN_SUBCONTROLS if colons == "::" else KNOWN_STATES
            if word not in known:
                problems.append(f"{selector}: неизвестное «{colons}{word}»")
    check(not problems, "все правила корректны" if not problems else "ошибки: " + "; ".join(problems[:5]))

    print("4. Покрытие виджетов")
    selectors_text = " ".join(selector for selector, _ in rules)
    for widget_type in REQUIRED_TYPES:
        check(re.search(rf"\b{widget_type}\b", selectors_text) is not None, f"есть правила для {widget_type}")
    names = set()
    for path in sorted(UI_DIR.rglob("*.py")):
        names.update(re.findall(r"""setObjectName\(\s*["']([A-Za-z][A-Za-z0-9_]*)["']\s*\)""", path.read_text(encoding="utf-8")))
    missing = sorted(n for n in names if re.search(rf"#{n}\b", stylesheet) is None)
    check(bool(names), f"в коде найдены имена объектов для стилей: {len(names)}")
    check(not missing, f"у каждого имени объекта из кода есть правило (нет: {missing})")
    for state in ("hover", "pressed", "focus", "disabled"):
        check(f"QPushButton:{state}" in stylesheet, f"у обычной кнопки есть состояние :{state}")
        check(f"QPushButton#PrimaryButton:{state}" in stylesheet, f"у основной кнопки есть состояние :{state}")
    check("QLineEdit:focus" in stylesheet and "QComboBox:focus" in stylesheet, "у полей ввода и списков есть :focus")
    check("QLineEdit:disabled" in stylesheet and "QComboBox:disabled" in stylesheet, "у полей ввода и списков есть :disabled")

    print("5. Тёмная тема без остатков светлой")
    leftovers = sorted(c for c in OLD_LIGHT_COLORS if c.lower() in stylesheet.lower())
    check(not leftovers, f"цветов прежней светлой темы в стилях нет ({leftovers})")
    light_backgrounds = []
    for selector, body in rules:
        for name, value in declarations(body)[0]:
            if name in ("background", "background-color") and re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                if luminance(value) > 0.25:
                    light_backgrounds.append(f"{selector}: {value}")
    check(not light_backgrounds, f"ни один фон не светлый ({light_backgrounds})")
    for name in ("BACKGROUND", "SURFACE", "CARD", "INPUT_BG", "BUTTON", "SIDEBAR"):
        check(luminance(colors[name]) < 0.05, f"{name} тёмный")

    print("6. Контраст")
    text_pairs = [
        ("TEXT", "BACKGROUND"), ("TEXT", "SURFACE"), ("TEXT", "CARD"),
        ("TEXT", "INPUT_BG"), ("TEXT", "BUTTON"), ("TEXT", "BUTTON_HOVER"),
        ("MUTED", "BACKGROUND"), ("MUTED", "SURFACE"), ("MUTED", "CARD"),
        ("ACCENT_TEXT", "BACKGROUND"), ("ACCENT_TEXT", "SURFACE"), ("ACCENT_TEXT", "CARD"),
        ("SUCCESS", "CARD"), ("WARNING", "CARD"), ("DANGER", "CARD"),
        ("SIDEBAR_TEXT", "SIDEBAR"), ("SIDEBAR_MUTED", "SIDEBAR"),
        ("TEXT", "SIDEBAR_HOVER"), ("SIDEBAR_ACTIVE_TEXT", "SIDEBAR_ACTIVE"),
        ("MUTED", "ACCENT_DISABLED"),
    ]
    for first, second in text_pairs:
        ratio = contrast(colors[first], colors[second])
        check(ratio >= 4.5, f"{first} на {second}: {ratio:.1f} (нужно не меньше 4.5)")
    for name in ("ACCENT", "ACCENT_PRESSED"):
        ratio = contrast("#FFFFFF", colors[name])
        check(ratio >= 4.5, f"белый текст на {name}: {ratio:.1f} (нужно не меньше 4.5)")
    ratio = contrast("#FFFFFF", colors["ACCENT_HOVER"])
    check(ratio >= 4.0, f"белый текст на ACCENT_HOVER: {ratio:.2f} (допустимо не меньше 4.0: состояние при наведении)")
    ratio = contrast(colors["INPUT_BORDER"], colors["INPUT_BG"])
    check(ratio >= 2.0, f"рамка поля ввода к его фону: {ratio:.1f} (нужно не меньше 2.0)")
    ratio = contrast(colors["INPUT_BORDER"], colors["CARD"])
    check(ratio >= 1.9, f"рамка поля ввода к карточке: {ratio:.1f} (нужно не меньше 1.9)")
    ratio = contrast(colors["BORDER"], colors["CARD"])
    check(ratio >= 1.2, f"граница карточки заметна: {ratio:.2f} (нужно не меньше 1.2)")
    ratio = contrast(colors["SCROLL_HANDLE_HOVER"], colors["BACKGROUND"])
    check(ratio >= 2.9, f"ползунок прокрутки при наведении: {ratio:.1f} (нужно не меньше 2.9)")

    print("7. Использование палитры в main.py")
    main_text = (UI_DIR / "main.py").read_text(encoding="utf-8")
    referenced = set(re.findall(r"""ColorRole\.\w+:\s*["']([A-Z_]+)["']""", main_text))
    referenced |= set(re.findall(r"""colors\[["']([A-Z_]+)["']\]""", main_text))
    check(bool(referenced), f"main.py берёт цвета палитры из COLORS: {len(referenced)}")
    check(referenced <= set(colors), f"все цвета из main.py есть в COLORS (нет: {sorted(referenced - set(colors))})")
    check("Qt.ColorScheme.Light" not in main_text, "светлая схема больше не включается принудительно")
    check("Qt.ColorScheme.Dark" in main_text, "включается тёмная схема Qt")
    check("app.setStyleSheet(build_stylesheet())" in main_text, "глобальный стиль по-прежнему применяется")
    check("storage.init_db()" in main_text and "_install_exception_hook()" in main_text and "_setup_logging()" in main_text,
          "журнал, обработчик ошибок и init_db на месте")

    print()
    if failures:
        print(f"ИТОГ: проверок не пройдено: {failures}")
        sys.exit(1)
    print("ИТОГ: все проверки пройдены.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Непредвиденная ошибка внутри проверки: показываем её и считаем проверку проваленной.
        traceback.print_exc()
        print()
        print("ИТОГ: проверка прервана из-за непредвиденной ошибки (см. выше).")
        sys.exit(1)
