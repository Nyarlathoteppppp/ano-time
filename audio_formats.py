"""Audio format compatibility rules shared by config and settings storage."""


APPLE_SPEECH_SAMPLE_RATES = (8000, 16000)


def normalize_sample_rate(sample_rate, asr_backend):
    """Return a SpeechAnalyzer-compatible rate without changing other ASRs."""
    requested = max(1, int(sample_rate))
    if str(asr_backend or "").casefold() != "apple":
        return requested
    return min(
        APPLE_SPEECH_SAMPLE_RATES,
        key=lambda supported: (abs(supported - requested), -supported),
    )
