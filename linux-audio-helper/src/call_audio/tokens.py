"""Optional local token counter, loaded before starting a capture session."""
from collections.abc import Callable

TOKENIZERS = ("cl100k_base", "o200k_base")


def load_token_counter(name: str | None) -> Callable[[str], int] | None:
    if name is None:
        return None
    if name not in TOKENIZERS:
        raise ValueError("Choose a supported tokenizer: " + ", ".join(TOKENIZERS))
    try:
        import tiktoken
    except ImportError:
        raise RuntimeError("Optional token counting needs: uv sync --locked --extra tokens") from None
    try:
        # First load may download the encoding vocabulary; do this at startup,
        # never inside a final-event callback or an active capture session.
        encoding = tiktoken.get_encoding(name)
        encoding.encode_ordinary("warm up")
    except Exception:
        raise RuntimeError("Could not load the tokenizer; prepare its vocabulary before starting the service.") from None

    def count(text: str) -> int:
        # Audio text is untrusted content, not a special-token control stream.
        return len(encoding.encode_ordinary(text))

    return count
