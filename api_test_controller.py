"""Non-blocking API benchmark orchestration for the control center."""

from ui.qt import QThread, Signal

from config import config
from course_profiles import do_not_translate_paths, glossary_paths, profile_domain


class ApiSpeedTestWorker(QThread):
    sample_ready = Signal(int, float, float, str, str)
    completed = Signal(int, float, float, int, bool)

    def __init__(self, spec):
        super().__init__()
        self.spec = dict(spec)

    def run(self):
        from api_benchmark import run_translation_benchmark
        from translator import Translator
        from translation_workflows.single_streaming import (
            SingleModelStreamingAdapter,
        )

        try:
            options = dict(self.spec)
            options.pop("label", None)
            streaming_mode = options.pop("streaming_mode", None)
            translator = Translator(**options)
            if streaming_mode is not None:
                translator = SingleModelStreamingAdapter(
                    translator, streaming_mode
                )

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
                summary.attempted,
                summary.stopped_early,
            )
        except Exception as exc:
            self.sample_ready.emit(
                1, 0.0, 0.0, "", f"{type(exc).__name__}: {exc}"
            )
            self.completed.emit(0, 0.0, 0.0, 1, True)


class ApiTestController:
    def __init__(self, view):
        self.view = view
        self.worker = None
        self._last_workflow = None

    def refresh_targets(self):
        view = self.view
        workflow = view.translation_workflow.currentData() or "single_model"
        previous = (
            view.api_test_provider.currentData()
            if workflow == self._last_workflow
            else None
        )
        bridge = view.bridge_provider.currentData() or "off"
        targets = []
        if workflow == "smart_hybrid":
            final_pool = view.smart_hybrid_final_provider.currentData()
            if final_pool == "groq_cerebras":
                targets.extend((
                    ("Groq GPT-OSS 20B（主翻译）", "groq"),
                    ("Cerebras GPT-OSS 120B（主翻译兜底）", "cerebras"),
                ))
            else:
                if bridge == "groq":
                    targets.append(("Groq GPT-OSS 20B（桥接）", "groq"))
                    targets.append(("Cerebras GPT-OSS 120B（桥接兜底）", "cerebras"))
                targets.append(("Gemini 3.5 Flash-Lite Paid（主翻译）", "gemini"))
            targets.append(("Cloudflare GLM-4.7-Flash（最终兜底）", "glm"))
        elif workflow == "single_model":
            targets.append((
                f"Current Final Model（当前最终模型） · {view.provider.currentText()}",
                "single",
            ))
            if bridge == "groq":
                targets.append(("Optional Bridge（可选桥接） · Groq", "groq"))
                targets.append((
                    "Optional Bridge Fallback（桥接兜底） · Cerebras",
                    "cerebras",
                ))

        view.api_test_provider.blockSignals(True)
        view.api_test_provider.clear()
        for label, value in targets:
            view.api_test_provider.addItem(label, value)
        index = view.api_test_provider.findData(previous)
        view.api_test_provider.setCurrentIndex(index if index >= 0 else 0)
        view.api_test_provider.blockSignals(False)
        self._last_workflow = workflow
        enabled = bool(targets) and self.worker is None
        view.api_test_provider.setEnabled(enabled)
        view.api_test_btn.setEnabled(enabled)

    def _spec(self):
        view = self.view
        target = view.api_test_provider.currentData()
        course_topic = view.current_course_topic.text().strip()
        profile_id = (
            view.course_profile.currentData()
            if hasattr(view, "course_profile")
            else getattr(config, "course_profile_id", "")
        )
        domain_prompt = (
            f"Current lecture topic: {course_topic}." if course_topic else
            profile_domain(view.translation_domain.text(), profile_id)
        )
        common = {
            "target_lang": str(
                view.target_lang.currentData() or view.target_lang.currentText()
            ),
            "domain_prompt": domain_prompt,
            "deadline_seconds": 3.0,
            "glossary_path": glossary_paths(config.glossary_path, profile_id),
            "do_not_translate_path": do_not_translate_paths(profile_id),
        }
        specs = {
            "groq": {
                "label": "Groq GPT-OSS 20B",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": view.groq_api_key.text().strip(),
                "model": "openai/gpt-oss-20b",
            },
            "cerebras": {
                "label": "Cerebras GPT-OSS 120B",
                "base_url": "https://api.cerebras.ai/v1",
                "api_key": view.cerebras_api_key.text().strip(),
                "model": "gpt-oss-120b",
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
                "streaming_mode": str(
                    view.single_streaming_mode.currentData() or "auto"
                ),
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

    def _completed(
        self,
        successes,
        average_first_ms,
        average_total_ms,
        attempted=5,
        stopped_early=False,
    ):
        suffix = " · 已提前停止" if stopped_early else ""
        self.view.api_test_results.append(
            "\n—— 汇总 ——\n"
            f"成功 {successes}/{attempted} · 平均首字 {average_first_ms:.0f} ms · "
            f"平均单次总耗时 {average_total_ms:.0f} ms{suffix}"
        )

    def _finished(self):
        self.worker = None
        self.refresh_targets()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3500)
