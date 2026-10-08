"""Đúng 36 mã mà nhân upstream chấp nhận — phông đi kèm chỉ dựng được chữ Latin. Không nới."""

LANGUAGES: list[tuple[str, str]] = [
    ("vi", "Tiếng Việt"), ("en", "Tiếng Anh"), ("fr", "Tiếng Pháp"),
    ("de", "Tiếng Đức"), ("es", "Tiếng Tây Ban Nha"), ("pt", "Tiếng Bồ Đào Nha"),
    ("it", "Tiếng Ý"), ("nl", "Tiếng Hà Lan"), ("pl", "Tiếng Ba Lan"),
    ("id", "Tiếng Indonesia"), ("ms", "Tiếng Mã Lai"), ("tl", "Tiếng Philippines"),
    ("tr", "Tiếng Thổ Nhĩ Kỳ"), ("sv", "Tiếng Thuỵ Điển"), ("no", "Tiếng Na Uy"),
    ("da", "Tiếng Đan Mạch"), ("fi", "Tiếng Phần Lan"), ("cs", "Tiếng Séc"),
    ("sk", "Tiếng Slovak"), ("sl", "Tiếng Slovenia"), ("hr", "Tiếng Croatia"),
    ("hu", "Tiếng Hungary"), ("ro", "Tiếng Romania"), ("lt", "Tiếng Litva"),
    ("lv", "Tiếng Latvia"), ("et", "Tiếng Estonia"), ("is", "Tiếng Iceland"),
    ("ga", "Tiếng Ireland"), ("cy", "Tiếng Wales"), ("ca", "Tiếng Catalan"),
    ("gl", "Tiếng Galicia"), ("eu", "Tiếng Basque"), ("af", "Tiếng Afrikaans"),
    ("sq", "Tiếng Albania"), ("mt", "Tiếng Malta"), ("sw", "Tiếng Swahili"),
]
VALID_LANGUAGES = {code for code, _ in LANGUAGES}

ENGLISH_NAMES: dict[str, str] = {
    "vi": "Vietnamese", "en": "English", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese",
    "it": "Italian", "nl": "Dutch", "pl": "Polish", "id": "Indonesian", "ms": "Malay", "tl": "Filipino",
    "tr": "Turkish", "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish", "cs": "Czech",
    "sk": "Slovak", "sl": "Slovenian", "hr": "Croatian", "hu": "Hungarian", "ro": "Romanian", "lt": "Lithuanian",
    "lv": "Latvian", "et": "Estonian", "is": "Icelandic", "ga": "Irish", "cy": "Welsh", "ca": "Catalan",
    "gl": "Galician", "eu": "Basque", "af": "Afrikaans", "sq": "Albanian", "mt": "Maltese", "sw": "Swahili",
}
assert set(ENGLISH_NAMES) == VALID_LANGUAGES
