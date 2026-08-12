from PyQt6.QtCore import QThread, pyqtSignal


class ModelListWorker(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, api_key, base_url):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        try:
            import httpx
            from openai import OpenAI

            timeout = httpx.Timeout(5.0)
            with httpx.Client(timeout=timeout, verify=True) as http_client:
                client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    http_client=http_client,
                    max_retries=0,
                )
                response = client.models.list()
                model_ids = [model.id for model in response.data]
            self.loaded.emit(model_ids)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class SystemAudioTestWorker(QThread):
    result = pyqtSignal(bool, str, float)

    def __init__(self, sample_rate):
        super().__init__()
        self.sample_rate = sample_rate

    def run(self):
        capture = None
        peak = 0.0
        success = False
        message = ""
        try:
            import numpy as np
            from system_audio_capture import SystemAudioCapture

            capture = SystemAudioCapture(
                sample_rate=self.sample_rate,
                streaming_step_size=0.2,
            )
            generator = capture.generator()
            for _ in range(10):
                chunk = next(generator)
                if len(chunk):
                    peak = max(peak, float(np.max(np.abs(chunk))))
            success = True
            message = "System audio permission is available."
        except Exception as exc:
            message = (
                "System Audio could not start. Open permission settings, allow the "
                f"translator/Python helper, then restart. Detail: {exc}"
            )
        finally:
            if capture:
                capture.stop()
        self.result.emit(success, message, peak)


class StartupWorker(QThread):
    ready = pyqtSignal(int, object)

    def __init__(self, generation, session_settings=None):
        super().__init__()
        self.generation = generation
        self.session_settings = session_settings

    def run(self):
        try:
            from main import Pipeline

            pipeline = Pipeline(session_settings=self.session_settings)
            self.ready.emit(self.generation, pipeline)
        except Exception as exc:
            print(f"Startup Error: {exc}")
            import traceback

            traceback.print_exc()
            self.ready.emit(self.generation, None)
