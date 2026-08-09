"""Non-blocking API benchmark orchestration for the control center."""

from PyQt6.QtCore import QThread, pyqtSignal

from config import config


class ApiSpeedTestWorker(QThread):
    sample_ready = pyqtSignal(int, float, float, str, str)
    completed = pyqtSignal(int, float, float)

    def __init__(self, spec):
        super().__init__()
        self.spec = dict(spec)

    def run(self):
        from api_benchmark import run_translation_benchmark
        from translator import Translator

        try:
            options = dict(self.spec)
            options.pop("label", None)
            translator = Translator(**options)

            def publish(sample):
                self.sample_ready.emit(
                    sample.index,
                    sample.first_token_ms,
                    sample.total_ms,
                    sample.translation,
                    sample.error,
                )

            summary = run_translation_benchmark(
                translator,
                progress=publish,
                should_stop=self.isInterruptionRequested,
                deadline_seconds=3.0,
            )
            self.completed.emit(
                len(summary.successes),
                summary.average_first_token_ms,
                summary.average_total_ms,
            )
        except Exception as exc:
            self.sample_ready.emit(
                1, 0.0, 0.0, "", f"{type(exc).__name__}: {exc}"
            )
            self.completed.emit(0, 0.0, 0.0)


class ApiTestController:
    def __init__(self, view):
        self.view = view
        self.worker = None

    def refresh_targets(self):
        view = self.view
        previous = view.api_test_provider.currentData()
        workflow = view.translation_workflow.currentData() or "smart_hybrid"
        bridge = view.bridge_provider.currentData() or "off"
        targets = []
        if workflow == "smart_hybrid":
            if bridge == "groq":
                targets.append(("Groq GPT-OSS 20B（桥接）", "groq"))
            targets.extend((
                ("Gemini 3.5 Flash-Lite", "gemini"),
                ("Cloudflare GLM-4.7-Flash", "glm"),
                ("Qwen-MT Flash（最终兜底）", "qwen"),
            ))
        elif workflow == "single_model":
            targets.append((f"{view.provider.currentText()}（最终模型）", "single"))
            if bridge == "groq":
                targets.append(("Groq GPT-OSS 20B（桥接）", "groq"))

        view.api_test_provider.blockSignals(True)
        view.api_test_provider.clear()
        for label, value in targets:
            view.api_test_provider.addItem(label, value)
        index = view.api_test_provider.findData(previous)
        view.api_test_provider.setCurrentIndex(index if index >= 0 else 0)
        view.api_test_provider.blockSignals(False)
        enabled = bool(targets) and self.worker is None
        view.api_test_provider.setEnabled(enabled)
        view.api_test_btn.setEnabled(enabled)

    def _spec(self):
        view = self.view
        target = view.api_test_provider.currentData()
        common = {
            "target_lang": str(
                view.target_lang.currentData() or view.target_lang.currentText()
            ),
            "domain_prompt": view.translation_domain.text(),
            "deadline_seconds": 3.0,
            "glossary_path": config.glossary_path,
        }
        specs = {
            "groq": {
                "label": "Groq GPT-OSS 20B",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": view.groq_api_key.text().strip(),
                "model": "openai/gpt-oss-20b",
            },
            "gemini": {
                "label": "Gemini 3.5 Flash-Lite",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key": view.gemini_api_key.text().strip(),
                "model": "gemini-3.5-flash-lite",
            },
            "qwen": {
                "label": "Qwen-MT Flash",
                "base_url": view.qwen_fallback_url.text().strip(),
                "api_key": view.qwen_fallback_key.text().strip(),
                "model": "qwen-mt-flash",
            },
            "single": {
                "label": view.provider.currentText(),
                "base_url": view.base_url.text().strip(),
                "api_key": view.api_key.text().strip(),
                "model": view.model.currentText().strip(),
            },
        }
        if target == "glm":
            account = view.cloudflare_account_id.text().strip()
            specs["glm"] = {
                "label": "Cloudflare GLM-4.7-Flash",
                "base_url": (
                    "https://api.cloudflare.com/client/v4/accounts/"
                    f"{account}/ai/v1" if account else ""
                ),
                "api_key": view.cloudflare_api_token.text().strip(),
                "model": "@cf/zai-org/glm-4.7-flash",
            }
        selected = specs.get(target)
        return {**common, **selected} if selected else None

    def start(self):
        if self.worker is not None:
            return
        spec = self._spec()
        if not spec or not spec["base_url"] or not spec["api_key"] or not spec["model"]:
            self.view.api_test_results.setPlainText(
                "缺少 API Key、Base URL、Account ID 或 Model；请先补全当前测速服务。"
            )
            return
        self.view.api_test_results.setPlainText(
            f"{spec['label']} · 正在发送 5 条固定测试任务…\n"
            "每条任务最长等待 3 秒。"
        )
        self.view.api_test_btn.setEnabled(False)
        self.view.api_test_provider.setEnabled(False)
        worker = ApiSpeedTestWorker(spec)
        self.worker = worker
        worker.sample_ready.connect(self._sample_ready)
        worker.completed.connect(self._completed)
        worker.finished.connect(self._finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _sample_ready(self, index, first_ms, total_ms, translation, error):
        if error:
            line = f"{index}/5 失败 · {total_ms:.0f} ms · {error}"
        else:
            compact = " ".join(translation.split())
            line = (
                f"{index}/5 首字 {first_ms:.0f} ms · 总计 {total_ms:.0f} ms"
                f"\n    {compact}"
            )
        self.view.api_test_results.append(line)

    def _completed(self, successes, average_first_ms, average_total_ms):
        self.view.api_test_results.append(
            "\n—— 汇总 ——\n"
            f"成功 {successes}/5 · 平均首字 {average_first_ms:.0f} ms · "
            f"平均总耗时 {average_total_ms:.0f} ms"
        )

    def _finished(self):
        self.worker = None
        self.refresh_targets()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3500)
