import pytest

from app.security.privacy import is_sensitive_text


@pytest.mark.parametrize(
    "text",
    [
        "My password must stay private.",
        "আমার পাসওয়ার্ড গোপন রাখো।",
        "मेरा बैंक खाता निजी है।",
        "என் சம்பளம் தனிப்பட்டது.",
        "నా ఆధార్ వివరాలు వ్యక్తిగతం.",
        "എന്റെ പാസ്‌വേഡ് രഹസ്യമാണ്.",
    ],
)
def test_sensitive_terms_are_detected_in_all_supported_languages(text):
    assert is_sensitive_text(text)


def test_unicode_format_marks_and_fullwidth_forms_are_normalized():
    assert is_sensitive_text("আমার পাস\u200dওয়ার্ড গোপন")
    assert is_sensitive_text("My ＰＡＳＳＷＯＲＤ is private")


def test_phone_number_is_detected_with_bengali_digits():
    assert is_sensitive_text("আমাকে ফোন করুন ৯৮৭৬৫৪৩২১০")


@pytest.mark.parametrize(
    "text",
    [
        "api_key=abcdefghijklmnopqrstuvwx",
        "GOOGLE_API_KEY=abcdefghijklmnopqrstuvwx",
        "access_token=abcdefghijklmnopqrstuvwxyz",
        "client_secret=abcdefghijklmnopqrstuvwxyz",
        "Authorization: Bearer eyJhbGciOiJub25lIn0.dGVzdC5zZWNyZXQudmFsdWU",
        "API key: ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "AIza" + "A" * 35,
        "sk-proj-" + "A" * 32,
        "ghp_" + "A" * 36,
        "AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz",
        "GITHUB_TOKEN=abcdefghijklmnopqrstuvwxyz",
        "Authorization: Basic YWJjZGVmZ2hpamtsbW5vcA==",
        "AKIA" + "A" * 16,
        "DATABASE_URL=postgres://shu:Q7pL2nV8@db.example.test/app",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_common_credential_config_forms_and_token_formats_are_sensitive(text):
    assert is_sensitive_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "Tell me a short story.",
        "আজ বাংলা কবিতা লিখে শোনাও।",
        "मुझे एक कहानी सुनाओ।",
        "எனக்கு ஒரு கதை சொல்லுங்கள்.",
        "నాకు ఒక కథ చెప్పండి.",
        "എനിക്ക് ഒരു കഥ പറയൂ.",
    ],
)
def test_ordinary_text_is_not_marked_sensitive(text):
    assert not is_sensitive_text(text)


@pytest.mark.parametrize("value", [None, 0, False, [], {}])
def test_non_text_values_are_not_sensitive(value):
    assert not is_sensitive_text(value)
