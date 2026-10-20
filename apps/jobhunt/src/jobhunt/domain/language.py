"""Language detection for job postings: an ISO 639-1 code or "unknown".

A small heuristic with no library (plan 01, task 5):
- Japanese, Chinese and Korean are recognised by their scripts.
- Vietnamese, English, German, Dutch, French and Spanish are recognised by common words.
  Vietnamese is not recognised by its letters alone, so English text naming a place such as
  "Đà Nẵng" stays English.
- Anything else, or too little text to tell (e.g. a bare English job title), is "unknown".
"""

import re
import unicodedata

UNKNOWN = "unknown"

MIN_SCRIPT_CHARS = 2  # CJK characters needed before a script decides the language
MIN_SCRIPT_SHARE = 0.2  # ...and their share of all letters (job posts mix in English terms)
MIN_WORD_HITS = 2  # common words needed before word counts decide the language
MIN_HIT_SHARE = 0.1  # ...as a share of all words
MIN_MARGIN = 1.5  # best language needs this many times the runner-up's hits

_WORD = re.compile(r"[^\W\d_]+")

# Common words per language: function words plus general job-posting vocabulary, never role or
# skill names. Words shared between languages (e.g. "in", "is", "we" in English and Dutch) are
# kept in one list only, so they don't blur the margin.
_COMMON_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the and of to for with on are be you your we our will as at by or from this that have "
        "has is in an it they their who what about into across using including help join "
        "experience team work working years skills requirements responsibilities benefits role "
        "job salary strong ability knowledge hiring looking".split()
    ),
    "vi": frozenset(
        "và của các có cho với trong được là những một không này khi để về từ theo tại hoặc như "
        "người chúng tôi bạn đang sẽ đã rất nhiều hơn phải cùng làm việc công ty nhân viên kinh "
        "nghiệm năm lương kỹ sư phát triển hệ thống yêu cầu mô tả quyền lợi chế độ đội ngũ dự "
        "án khách hàng sản phẩm thời gian tốt trên ít nhất hiểu biết khả năng tiếng môi trường "
        "chuyên nghiệp đãi ngộ thưởng bảo hiểm sức khỏe ứng tuyển vị trí cấp mới tham gia hỗ "
        "trợ quản lý vận hành tìm kiếm".split()
    ),
    "de": frozenset(
        "der die das und ist mit für von zu den dem des ein eine einen einer im auf sie wir du "
        "ihr ihre unsere unser unserer bei als oder nicht auch sich werden sind bist hast zum "
        "zur über sowie sehr gute erfahrung kenntnisse aufgaben stelle wir bieten suchen".split()
    ),
    "nl": frozenset(
        "het een en van op met voor je jij jouw wij ons onze zijn aan bij als niet ook naar dat "
        "deze wat wordt worden bent heb hebt tot uit ervaring kennis werk functie vacature "
        "zoeken bieden".split()
    ),
    "fr": frozenset(
        "le la les des du et un une est dans pour avec sur au aux vous nous votre vos notre nos "
        "qui que par plus pas ce cette ses son sont être expérience poste équipe compétences "
        "connaissances profil missions entreprise recherchons rejoindre".split()
    ),
    "es": frozenset(
        "el los las del y una es con para por se su sus al lo como más nuestro nuestra "
        "nuestros nuestras tu tus experiencia equipo trabajo empresa conocimientos requisitos "
        "puesto años buscamos ofrecemos".split()
    ),
}

# "de", "en" and "la" are common in Dutch, French and Spanish alike; counted for each.
for _lang in ("nl", "fr", "es"):
    _COMMON_WORDS[_lang] |= {"de", "en"}
for _lang in ("fr", "es"):
    _COMMON_WORDS[_lang] |= {"la"}


def detect_language(text: str) -> str:
    """Return the ISO 639-1 code of the text's language, or "unknown"."""
    text = unicodedata.normalize("NFC", text)
    return _by_script(text) or _by_common_words(text) or UNKNOWN


def _by_script(text: str) -> str | None:
    kana = hangul = han = other_letters = 0
    for char in text:
        code = ord(char)
        if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9D:
            kana += 1
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            hangul += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            han += 1
        elif char.isalpha():
            other_letters += 1
    letters = kana + hangul + han + other_letters

    def dominant(count: int) -> bool:
        return count >= MIN_SCRIPT_CHARS and count >= MIN_SCRIPT_SHARE * letters

    if dominant(hangul):
        return "ko"
    if kana >= MIN_SCRIPT_CHARS and dominant(kana + han):
        return "ja"
    if dominant(han):
        return "zh"
    return None


def _by_common_words(text: str) -> str | None:
    words = _WORD.findall(text.lower())
    if not words:
        return None
    ranked = sorted(
        ((sum(word in vocab for word in words), lang) for lang, vocab in _COMMON_WORDS.items()),
        reverse=True,
    )
    (best, lang), (runner_up, _) = ranked[0], ranked[1]
    clear = best >= MIN_WORD_HITS and best >= MIN_HIT_SHARE * len(words)
    return lang if clear and best >= MIN_MARGIN * runner_up else None
