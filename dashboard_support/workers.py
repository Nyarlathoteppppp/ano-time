from ui.qt import QThread, Signal


class ModelListWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

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
    result = Signal(bool, str, float)

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


class SmartHintTestWorker(QThread):
    """Test Smart Hint independently of an active translation session."""

    completed = Signal(bool, str)

    SAMPLE_FINALIZED_ENGLISH = (
        "We compare the bias and variance of a regularized estimator.",
        "The regularization parameter controls the complexity of the model.",
        "Cross-validation estimates the expected generalization error.",
        "We use the mean squared error to evaluate the prediction.",
    )

    def __init__(self, api_key, base_url, model):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self):
        client = None
        try:
            from smart_hint import SmartHintClient

            client = SmartHintClient(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
            )
            hint = client.summarize(self.SAMPLE_FINALIZED_ENGLISH)
            keywords = "、".join(hint.keywords) or "无"
            self.completed.emit(
                True,
                f"连接成功：{hint.topic or '已返回主题'}\n关键词：{keywords}",
            )
        except Exception as exc:
            self.completed.emit(False, f"测试失败：{type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                client.close()


class StartupWorker(QThread):
    ready = Signal(int, object)

    def __init__(self, generation, session_settings=None):
        super().__init__()
        self.generation = generation
        self.session_settings = session_settings

    def run(self):
        try:
            from main import Pipeline

            pipeline = Pipeline(
                session_settings=self.session_settings,
                asr_session_generation=self.generation,
            )
            self.ready.emit(self.generation, pipeline)
        except Exception as exc:
            print(f"Startup Error: {exc}")
            import traceback

            traceback.print_exc()
            self.ready.emit(self.generation, None)
