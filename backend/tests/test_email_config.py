from types import SimpleNamespace

from app.services.email_config import normalize_smtp_password, resolve_smtp_config


def test_grouped_gmail_app_password_is_compacted() -> None:
    assert normalize_smtp_password(
        "abcd efgh ijkl mnop",
        host="smtp.gmail.com",
    ) == "abcdefghijklmnop"


def test_non_gmail_password_keeps_internal_spaces() -> None:
    assert normalize_smtp_password(
        "  secret with spaces  ",
        host="mail.example.com",
    ) == "secret with spaces"


def test_resolve_smtp_config_accepts_grouped_gmail_password(monkeypatch) -> None:
    from app.services import email_config

    monkeypatch.setattr(email_config.settings, "smtp_host", None)
    monkeypatch.setattr(email_config.settings, "smtp_port", None)
    monkeypatch.setattr(email_config.settings, "smtp_user", None)
    monkeypatch.setattr(email_config.settings, "smtp_password", None)

    config = resolve_smtp_config(
        SimpleNamespace(
            smtp_host="smtp.gmail.com",
            smtp_port=465,
            email_expediteur="sender@example.com",
            smtp_password="abcd efgh ijkl mnop",
        )
    )

    assert config is not None
    assert config.password == "abcdefghijklmnop"
