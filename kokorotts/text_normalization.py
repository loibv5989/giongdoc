import re
from decimal import Decimal, InvalidOperation


_LARGE_UNIT_NAMES = {
    "K": "thousand",
    "M": "million",
    "B": "billion",
    "T": "trillion",
}

# Uppercase suffixes are intentional. Lowercase forms are ambiguous with
# measurements such as 10m, while longer suffixes such as MB are identifiers.
_ENGLISH_LARGE_UNIT = re.compile(
    r"(?<![\w.])"
    r"(?P<currency>[$£])?"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<unit>[KMBT])"
    r"(?!\w)"
)

_MEASUREMENT_NAMES = {
    "km": ("kilometer", "kilometers"),
    "cm": ("centimeter", "centimeters"),
    "mm": ("millimeter", "millimeters"),
    "ft": ("foot", "feet"),
    "in": ("inch", "inches"),
    "m": ("meter", "meters"),
}
_ENGLISH_MEASUREMENT = re.compile(
    r"(?<![\w.])"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*"
    r"(?P<unit>km|cm|mm|ft|in|m)"
    r"(?!\w)"
)

_ERA_NAMES = {
    "BC": "before Christ",
    "BCE": "before common era",
    "AD": "anno Domini",
    "CE": "common era",
}
_YEAR = r"(?:\d{1,4})"
_ENGLISH_TRAILING_ERA = re.compile(
    rf"(?<!\w)(?P<year>{_YEAR})\s*(?P<era>BCE|BC|AD|CE)(?!\w)"
)
_ENGLISH_LEADING_ERA = re.compile(
    rf"(?<!\w)(?P<era>BCE|BC|AD|CE)\s*(?P<year>{_YEAR})(?!\w)"
)

_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}
_CARDINAL_ROMAN_CONTEXT = re.compile(
    r"\b(?P<label>World\s+War|Chapter|Part|Volume|Book|Act|Scene|Section|"
    r"Type|Class|Phase|Stage|Level|Version|Model|Mark)\s+"
    r"(?P<roman>[IVXLCDM]+)\b",
    re.IGNORECASE,
)
_REGNAL_ROMAN_CONTEXT = re.compile(
    r"\b(?P<name>[A-Z][a-z]+(?:[-'][A-Za-z]+)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Za-z]+)?){0,3})\s+"
    r"(?P<roman>[IVXLCDM]+)\b"
)
_ENGLISH_MARKDOWN_ASTERISK_EMPHASIS = re.compile(
    r"(?<![\w\\*])"
    r"(?P<marker>\*{1,3})"
    r"(?P<content>\S(?:[^\n*]*?\S)?)"
    r"(?P=marker)"
    r"(?![\w*])"
)


def expand_english_large_units(text: str) -> str:
    """Expand unambiguous compact English number suffixes before G2P."""

    def replace(match: re.Match[str]) -> str:
        currency = match.group("currency") or ""
        number = match.group("number")
        unit = _LARGE_UNIT_NAMES[match.group("unit")]
        return f"{currency}{number} {unit}"

    return _ENGLISH_LARGE_UNIT.sub(replace, text)


def expand_english_measurements(text: str) -> str:
    """Expand unambiguous numeric measurements before English G2P."""

    def replace(match: re.Match[str]) -> str:
        number = match.group("number")
        singular, plural = _MEASUREMENT_NAMES[match.group("unit")]
        try:
            is_singular = Decimal(number.replace(",", "")) == 1
        except InvalidOperation:
            is_singular = False
        return f"{number} {singular if is_singular else plural}"

    return _ENGLISH_MEASUREMENT.sub(replace, text)


def expand_english_eras(text: str) -> str:
    """Expand era abbreviations only when they are adjacent to a year."""

    def trailing(match: re.Match[str]) -> str:
        return f"{match.group('year')} {_ERA_NAMES[match.group('era')]}"

    def leading(match: re.Match[str]) -> str:
        return f"{_ERA_NAMES[match.group('era')]} {match.group('year')}"

    return _ENGLISH_LEADING_ERA.sub(
        leading, _ENGLISH_TRAILING_ERA.sub(trailing, text)
    )


def _roman_to_int(value: str) -> int | None:
    total = 0
    previous = 0
    for character in reversed(value):
        current = _ROMAN_VALUES[character]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    if not 0 < total < 4000 or _int_to_roman(total) != value:
        return None
    return total


def _int_to_roman(value: int) -> str:
    numerals = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    rendered = []
    remaining = value
    for amount, numeral in numerals:
        count, remaining = divmod(remaining, amount)
        rendered.append(numeral * count)
    return "".join(rendered)


def _ordinal_number(value: int) -> str:
    suffix = "th"
    if value % 100 not in {11, 12, 13}:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def expand_english_roman_numerals(text: str) -> str:
    """Expand Roman numerals in explicit labels and regnal-name contexts."""

    def cardinal(match: re.Match[str]) -> str:
        value = _roman_to_int(match.group("roman").upper())
        if value is None:
            return match.group(0)
        return f"{match.group('label')} {value}"

    def ordinal(match: re.Match[str]) -> str:
        value = _roman_to_int(match.group("roman"))
        if value is None:
            return match.group(0)
        return f"{match.group('name')} {_ordinal_number(value)}"

    return _REGNAL_ROMAN_CONTEXT.sub(
        ordinal, _CARDINAL_ROMAN_CONTEXT.sub(cardinal, text)
    )


def strip_english_markdown_emphasis(text: str) -> str:
    """Remove bounded asterisk emphasis without consuming literal operators."""

    return _ENGLISH_MARKDOWN_ASTERISK_EMPHASIS.sub(
        lambda match: match.group("content"), text
    )


def normalize_english_text(
    text: str, *, normalize_markdown_emphasis: bool = True
) -> str:
    """Apply product-owned English normalization before Misaki G2P."""

    if normalize_markdown_emphasis:
        text = strip_english_markdown_emphasis(text)
    text = expand_english_large_units(text)
    text = expand_english_measurements(text)
    text = expand_english_eras(text)
    return expand_english_roman_numerals(text)


# Match Vietnamese labels case-insensitively, but require uppercase numerals:
# lowercase words such as "phần vi mô" are not Roman numbers.
_VIETNAMESE_ROMAN_CONTEXT = re.compile(
    r"\b(?P<label>(?i:Phần|Chương))(?P<space>\s+)(?P<roman>[IVXLCDM]+)\b(?![@/])"
)


def expand_vietnamese_roman_numerals(text: str) -> str:
    """Expand canonical Roman numbers in Vietnamese part/chapter references."""
    def replace(match: re.Match[str]) -> str:
        value = _roman_to_int(match.group("roman"))
        if value is None:
            return match.group(0)
        return f"{match.group('label')}{match.group('space')}{value}"

    return _VIETNAMESE_ROMAN_CONTEXT.sub(replace, text)


_VIETNAMESE_DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")
_VIETNAMESE_NUMBER = re.compile(
    r"(?P<protected>(?:https?://|www\.)[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
    r"|(?<![\w.])(?P<sign>[-−+])?(?P<number>[0-9]+(?:[.,][0-9]+)*)(?![\w]|[.,][0-9])"
)


def _vietnamese_triplet(value: int, full_hundreds: bool = False) -> str:
    hundreds, remainder = divmod(value, 100)
    tens, units = divmod(remainder, 10)
    words = []
    if hundreds or full_hundreds:
        words.extend((_VIETNAMESE_DIGITS[hundreds], "trăm"))
    if tens >= 2:
        words.extend((_VIETNAMESE_DIGITS[tens], "mươi"))
    elif tens == 1:
        words.append("mười")
    elif units and (hundreds or full_hundreds):
        words.append("linh")
    if units:
        words.append("mốt" if units == 1 and tens >= 2 else "lăm" if units == 5 and tens else _VIETNAMESE_DIGITS[units])
    return " ".join(words)


def _vietnamese_integer(digits: str) -> str:
    # Leading zeroes and long digit sequences are identifiers, not quantities.
    if (len(digits) > 1 and digits.startswith("0")) or len(digits) > 18:
        return " ".join(_VIETNAMESE_DIGITS[int(digit)] for digit in digits)
    value = int(digits)
    if value == 0:
        return _VIETNAMESE_DIGITS[0]
    groups = []
    while value:
        value, group = divmod(value, 1000)
        groups.append(group)
    words = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            continue
        words.append(_vietnamese_triplet(group, index < len(groups) - 1 and group < 100))
        unit = ("", "nghìn", "triệu")[index % 3]
        scale = " ".join(part for part in (unit, *("tỷ" for _ in range(index // 3))) if part)
        if scale:
            words.append(scale)
    return " ".join(words)


def _vietnamese_number(value: str) -> str | None:
    # Vietnamese grouping/decimal marks are primary; accept unambiguous imported forms.
    integer = value
    fraction = None
    if re.fullmatch(r"[1-9][0-9]{0,2}(?:\.[0-9]{3})+(?:,[0-9]+)?", value):
        integer, _, fraction = value.partition(",")
        integer = integer.replace(".", "")
    elif re.fullmatch(r"[1-9][0-9]{0,2}(?:,[0-9]{3})+\.[0-9]+", value):
        integer, fraction = value.split(".")
        integer = integer.replace(",", "")
    elif re.fullmatch(r"[1-9][0-9]{0,2}(?:,[0-9]{3}){2,}", value):
        integer = value.replace(",", "")
    elif value.count(",") + value.count(".") == 1:
        integer, fraction = re.split(r"[.,]", value)
    elif not value.isdigit():
        return None
    spoken = _vietnamese_integer(integer)
    if fraction:
        spoken += " phẩy " + " ".join(_VIETNAMESE_DIGITS[int(digit)] for digit in fraction)
    return spoken


def normalize_vietnamese_text(text: str) -> str:
    """Speak numeric values as Vietnamese words before tone-sensitive ViG2P."""
    def replace(match: re.Match[str]) -> str:
        if match.group("protected"):
            return match.group(0)
        spoken = _vietnamese_number(match.group("number"))
        if spoken is None:
            return match.group(0)
        sign = match.group("sign")
        return ("âm " if sign in {"-", "−"} else "cộng " if sign == "+" else "") + spoken

    return _VIETNAMESE_NUMBER.sub(replace, expand_vietnamese_roman_numerals(text))
