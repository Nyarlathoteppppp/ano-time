"""Fast, dependency-free conversion of inline LaTeX for subtitle display."""

import re


_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ϵ", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "ϕ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ",
    "Omega": "Ω",
}

_SYMBOLS = {
    "sum": "Σ", "prod": "Π", "int": "∫", "partial": "∂",
    "infty": "∞", "times": "×", "cdot": "·", "pm": "±",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠",
    "approx": "≈", "equiv": "≡", "in": "∈", "notin": "∉",
    "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩",
    "to": "→", "rightarrow": "→", "leftarrow": "←",
    "forall": "∀", "exists": "∃", "nabla": "∇", "ell": "ℓ",
    "max": "max", "min": "min", "argmax": "argmax", "argmin": "argmin",
    "log": "log", "ln": "ln", "exp": "exp", "det": "det",
    "Var": "Var", "Cov": "Cov",
    "top": "ᵀ", "perp": "⊥", "sim": "∼", "propto": "∝",
    "mid": "|", "vert": "|", "Vert": "‖", "Pr": "P",
    "ldots": "…", "cdots": "⋯", "dots": "…",
    "trace": "tr", "tr": "tr", "rank": "rank",
    "arg": "arg",
}

_SUPERSCRIPT = str.maketrans(
    "0123456789+-=()abcdefghijklmnopqrstuvwxyz",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖqʳˢᵗᵘᵛʷˣʸᶻ",
)
_SUBSCRIPT = str.maketrans(
    "0123456789+-=()aehijklmnoprstuvx",
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
)


def _script(value, marker):
    if marker == "^" and value == "*":
        return "*"
    if marker == "^" and value in {"T", "top"}:
        return "ᵀ"
    if marker == "^" and value and all(
        character in "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵀ" for character in value
    ):
        return value
    table = _SUPERSCRIPT if marker == "^" else _SUBSCRIPT
    converted = value.translate(table)
    if len(converted) == len(value) and converted != value:
        return converted
    return f"{marker}({value})"


def _replace_balanced_command(text, command, replacement):
    pattern = re.compile(rf"\\{command}\s*\{{([^{{}}]*)\}}")
    while True:
        updated = pattern.sub(lambda match: replacement(match.group(1)), text)
        if updated == text:
            return text
        text = updated


def _convert_formula(formula):
    text = str(formula or "").strip()
    text = text.replace(r"\left", "").replace(r"\right", "")
    text = text.replace(r"\|", "‖")
    text = text.replace(r"^{\top}", "ᵀ").replace(r"^\top", "ᵀ")

    matrix_pattern = re.compile(
        r"\\begin\{(?:bmatrix|pmatrix|matrix)\}(.*?)"
        r"\\end\{(?:bmatrix|pmatrix|matrix)\}",
        re.DOTALL,
    )
    text = matrix_pattern.sub(
        lambda match: "[" + match.group(1).replace(r"\\", "; ").replace("&", ", ") + "]",
        text,
    )

    fraction = re.compile(r"\\(?:d?frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
    wrappers = ("mathbf", "boldsymbol", "mathrm", "mathit", "operatorname", "text")
    accents = (
        ("hat", "\u0302"), ("bar", "\u0304"), ("overline", "\u0304"),
        ("tilde", "\u0303"), ("vec", "\u20d7"), ("dot", "\u0307"),
    )
    for _ in range(5):
        previous = text
        for command in wrappers:
            text = _replace_balanced_command(text, command, _convert_formula)
        text = _replace_balanced_command(
            text, "mathbb", lambda value: {
                "R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ",
                "E": "E",
            }.get(_convert_formula(value), _convert_formula(value))
        )
        text = _replace_balanced_command(
            text, "mathcal", lambda value: {
                "N": "𝒩", "L": "ℒ",
            }.get(_convert_formula(value), _convert_formula(value))
        )
        text = fraction.sub(
            lambda match: f"({_convert_formula(match.group(1))})/({_convert_formula(match.group(2))})",
            text,
        )
        text = _replace_balanced_command(
            text, "sqrt", lambda value: f"√({_convert_formula(value)})"
        )
        for command, suffix in accents:
            text = _replace_balanced_command(
                text, command,
                lambda value, mark=suffix: _convert_formula(value) + mark,
            )
        if text == previous:
            break

    symbols = {**_GREEK, **_SYMBOLS}
    text = re.sub(
        r"\\([A-Za-z]+)",
        lambda match: symbols.get(match.group(1), match.group(0)),
        text,
    )
    text = re.sub(
        r"([_^])\{([^{}]+)\}",
        lambda match: _script(_convert_formula(match.group(2)), match.group(1)),
        text,
    )
    text = re.sub(
        r"([_^])([A-Za-z0-9+\-=()*])",
        lambda match: _script(match.group(2), match.group(1)),
        text,
    )
    text = re.sub(r"\\[,;:!]", " ", text)
    text = text.replace(r"\ ", " ").replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_math(value):
    value = str(value or "").strip()
    return bool(
        re.search(r"\\[A-Za-z]+|[_^=]|\\begin\{", value)
        or re.fullmatch(r"[A-Za-z](?:[A-Za-z0-9.]*)|[0-9]+(?:\.[0-9]+)?", value)
    )


def _convert_or_preserve(formula, opening="", closing=""):
    converted = _convert_formula(formula)
    if re.search(r"\\[A-Za-z]+", converted):
        return f"{opening}{formula}{closing}"
    return converted


def normalize_math_subtitles(text, final=True):
    """Convert complete inline LaTeX while keeping ordinary currency intact.

    During streaming, an unfinished mathematical ``$...`` tail is withheld so
    users never see half a command such as ``$\\hat{``. The final pass converts
    that tail if it contains recognizable mathematical syntax.
    """
    value = str(text or "")
    value = re.sub(
        r"\\\((.+?)\\\)",
        lambda match: _convert_or_preserve(match.group(1), r"\(", r"\)"),
        value,
        flags=re.DOTALL,
    )
    value = re.sub(
        r"\\\[(.+?)\\\]",
        lambda match: _convert_or_preserve(match.group(1), r"\[", r"\]"),
        value,
        flags=re.DOTALL,
    )

    parts = value.split("$")
    rendered = [parts[0]]
    index = 1
    while index + 1 < len(parts):
        content = parts[index]
        if _looks_like_math(content):
            rendered.append(_convert_or_preserve(content, "$", "$"))
        else:
            rendered.append(f"${content}$")
        rendered.append(parts[index + 1])
        index += 2

    if len(parts) % 2 == 0:
        unfinished = parts[-1]
        if final and _looks_like_math(unfinished):
            rendered.append(_convert_or_preserve(unfinished, "$"))
        elif final:
            rendered.append("$" + unfinished)
        # An unfinished mathematical stream tail is intentionally withheld.
        elif not _looks_like_math(unfinished):
            rendered.append("$" + unfinished)

    result = "".join(rendered)
    # Some providers omit delimiters despite the prompt. Convert only when a
    # known command remains; normal prose and currency never enter this path.
    if re.search(r"\\(?:hat|bar|overline|tilde|vec|dot|frac|dfrac|sqrt|mathbb|"
                 r"mathcal|mathbf|boldsymbol|mathrm|"
                 r"operatorname|alpha|beta|gamma|theta|lambda|mu|sigma|phi|"
                 r"omega|sum|prod|int|partial|infty)(?![A-Za-z])", result):
        result = _convert_or_preserve(result)
    return result.strip()


def safe_normalize_math_subtitles(text, final=True):
    """Fail open so display enhancement can never break translation delivery."""
    try:
        return normalize_math_subtitles(text, final=final)
    except Exception:
        return str(text or "").strip()
