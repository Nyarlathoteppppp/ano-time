class RecordingSignal:
    """Minimal Qt-like signal recorder for contract tests."""

    def __init__(self):
        self.events = []

    def emit(self, *args):
        self.events.append(args)
