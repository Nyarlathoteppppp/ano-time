import unittest
from types import SimpleNamespace
from unittest.mock import patch

from math_subtitles import normalize_math_subtitles, safe_normalize_math_subtitles
from translator import Translator


class MathSubtitleTests(unittest.TestCase):
    def test_converts_common_estimator_formula(self):
        self.assertEqual(
            normalize_math_subtitles(
                r"方差图，即 $\hat{\alpha} = \frac{1}{n}\sum_{i=1}^{n}x_i$ 的直方图。"
            ),
            "方差图，即 α̂ = (1)/(n)Σᵢ₌₁ⁿxᵢ 的直方图。",
        )

    def test_converts_expectation_and_probability_symbols(self):
        self.assertEqual(
            normalize_math_subtitles(
                r"其中 $\mathbb{E}[X] \approx \mu$，且 $X \in \mathbb{R}$。"
            ),
            "其中 E[X] ≈ μ，且 X ∈ ℝ。",
        )

    def test_removes_delimiters_from_simple_math_tokens(self):
        self.assertEqual(
            normalize_math_subtitles(r"当 $A$ 可逆且 $n$ 大于 $1.96$ 时。"),
            "当 A 可逆且 n 大于 1.96 时。",
        )

    def test_converts_named_subscripts_and_norms(self):
        self.assertEqual(
            normalize_math_subtitles(
                r"最大值为 $\lambda_{\max}$，更新 $\theta_{t+1}$，范数 $\|\theta\|_2^2$。"
            ),
            "最大值为 λₘₐₓ，更新 θₜ₊₁，范数 ‖θ‖₂²。",
        )

    def test_linear_algebra_and_sml_formula_corpus(self):
        cases = {
            r"$\mathbf{x}^\top\mathbf{x}$": "xᵀx",
            r"$x^T A x$": "xᵀ A x",
            r"$A^{-1}b$": "A⁻¹b",
            r"$\det(A) \neq 0$": "det(A) ≠ 0",
            r"$\mathbf{x} \in \mathbb{R}^d$": "x ∈ ℝᵈ",
            r"$\|\theta\|_2^2$": "‖θ‖₂²",
            r"$\nabla_\theta \mathcal{L}(\theta)$": "∇_θ ℒ(θ)",
            r"$\operatorname{Var}(X)=\sigma^2$": "Var(X)=σ²",
            r"$\operatorname{Cov}(X,Y)$": "Cov(X,Y)",
            r"$X \sim \mathcal{N}(\mu,\sigma^2)$": "X ∼ 𝒩(μ,σ²)",
            r"$p(\theta \mid D) \propto p(D \mid \theta)p(\theta)$":
                "p(θ | D) ∝ p(D | θ)p(θ)",
            r"$\hat{\beta} \pm 1.96\,\operatorname{SE}(\hat{\beta})$":
                "β̂ ± 1.96 SE(β̂)",
            r"$\sum_{i=1}^{n}(y_i-\hat{y}_i)^2$": "Σᵢ₌₁ⁿ(yᵢ-ŷᵢ)²",
            r"$\arg\min_\theta \mathcal{L}(\theta)$": "argmin_θ ℒ(θ)",
            r"$\lambda_{\max}(\Sigma)$": "λₘₐₓ(Σ)",
            r"$\frac{1}{n}X^\top X$": "(1)/(n)Xᵀ X",
        }
        for latex, expected in cases.items():
            with self.subTest(latex=latex):
                self.assertEqual(normalize_math_subtitles(latex), expected)

    def test_preserves_currency(self):
        self.assertEqual(
            normalize_math_subtitles("费用从 $5 增加到 $10。"),
            "费用从 $5 增加到 $10。",
        )

    def test_withholds_unfinished_streaming_formula(self):
        self.assertEqual(
            normalize_math_subtitles(r"估计量为 $\hat{", final=False),
            "估计量为",
        )
        self.assertEqual(
            normalize_math_subtitles(r"估计量为 $\hat{\alpha}$", final=False),
            "估计量为 α̂",
        )

    def test_converts_known_command_without_delimiters(self):
        self.assertEqual(normalize_math_subtitles(r"参数 \beta_1"), "参数 β₁")

    def test_unknown_latex_is_preserved(self):
        self.assertEqual(
            normalize_math_subtitles(r"暂不支持 $\unknown{x}$。"),
            r"暂不支持 $\unknown{x}$。",
        )

    def test_safe_converter_never_breaks_translation(self):
        with patch(
            "math_subtitles.normalize_math_subtitles",
            side_effect=RuntimeError("bad formula"),
        ):
            self.assertEqual(
                safe_normalize_math_subtitles("正常译文"),
                "正常译文",
            )

    def test_streaming_translator_hides_incomplete_latex_and_deduplicates(self):
        class Stream(list):
            def close(self):
                pass

        stream = Stream([
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=r"估计量为 $\hat{"))],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=r"\alpha"))],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="}$。"))],
                usage=None,
            ),
        ])
        completions = SimpleNamespace(create=lambda **_options: stream)
        translator = Translator(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="generic-fast-model",
        )
        translator.client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        updates = []

        result = translator.translate(
            "The estimator is alpha hat.",
            use_context=False,
            remember_context=False,
            on_update=updates.append,
        )

        self.assertEqual(updates, ["估计量为", "估计量为 α̂。"])
        self.assertEqual(result, "估计量为 α̂。")


if __name__ == "__main__":
    unittest.main()
