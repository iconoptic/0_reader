import books
import latex


def test_plain_prose_untouched():
    text = "The quick brown fox jumps. Price: $5 and $10 total."
    assert latex.convert(text) == text


def test_greek_letters():
    assert latex.convert(r"\alpha + \beta = \Gamma") == "α + β = Γ"


def test_superscript_digits_and_braced():
    assert latex._convert_commands("x^2") == "x²"
    assert latex._convert_commands("x^{23}") == "x²³"
    assert latex._convert_commands("e^{i\\pi}") == "eⁱπ"


def test_subscript():
    assert latex._convert_commands("x_i") == "xᵢ"
    assert latex._convert_commands("a_{n+1}") == "aₙ₊₁"


def test_bare_scripts_converted_when_document_has_other_latex():
    # A bare "x^2" with no $ of its own still gets converted once the
    # document proves it actually contains LaTeX (here, the \alpha).
    text = r"Note $\alpha$ appears once, and later x^2 shows up too."
    result = latex.convert(text)
    assert "α" in result
    assert "x²" in result


def test_bare_caret_and_underscore_left_alone_without_latex_signal():
    # No $ or backslash anywhere in the document -> treated as plain prose,
    # so code-like snake_case/caret text isn't mangled.
    text = "my_variable is x^2 style naming, no real latex here"
    assert latex.convert(text) == text


def test_frac_simple_and_vulgar():
    assert latex.convert(r"\frac{1}{2}") == "½"
    assert latex.convert(r"\frac{a}{b}") == "a⁄b"
    assert latex.convert(r"\dfrac{x+1}{y}") == "(x+1)⁄y"


def test_sqrt():
    assert latex.convert(r"\sqrt{2}") == "√2"
    assert latex.convert(r"\sqrt{x+1}") == "√(x+1)"
    assert latex.convert(r"\sqrt[3]{8}") == "³√8"


def test_common_symbols():
    assert latex.convert(r"a \times b \leq c") == "a × b ≤ c"
    assert latex.convert(r"x \to \infty") == "x → ∞"
    assert latex.convert(r"\sum_{i=1}^{n} i") == (
        "∑" + "ᵢ₌₁" + "ⁿ i")


def test_inline_dollar_math_stripped_when_looks_like_math():
    assert latex.convert(r"the value $\alpha$ is small") == (
        "the value α is small")
    assert latex.convert("let $x$ be an integer") == "let x be an integer"


def test_inline_dollar_currency_left_alone():
    assert latex.convert("It costs $5 and $10 for two.") == (
        "It costs $5 and $10 for two.")


def test_display_math_and_parens():
    assert latex.convert(r"\[\alpha^2\]") == "α²"
    assert latex.convert(r"\(\alpha^2\)") == "α²"
    assert latex.convert(r"$$\alpha^2$$") == "α²"


def test_left_right_stripped():
    assert latex.convert(r"\left( x + 1 \right)") == "( x + 1 )"


def test_mathbb_blackboard():
    assert latex.convert(r"\mathbb{R}") == "ℝ"
    assert latex.convert(r"\mathbb{Q}") == "ℚ"


def test_text_and_textbf_unwrap():
    assert latex.convert(r"\text{if } x > 0") == "if x > 0"
    assert latex.convert(r"\textbf{important}") == "important"


def test_accents():
    assert latex.convert(r"\hat{x}") == "x̂"
    assert latex.convert(r"\vec{v}") == "v⃗"


def test_metadata_commands_dropped():
    assert latex.convert(r"see equation \ref{eq:1} above") == (
        "see equation above")
    assert latex.convert(r"as shown \cite{smith2020}.") == "as shown ."


def test_escaped_specials_and_literal_braces():
    assert latex.convert(r"50\% of \$100") == "50% of $100"
    assert latex.convert(r"the set \{1, 2, 3\}") == "the set {1, 2, 3}"


def test_unknown_command_falls_back_to_bare_name():
    assert latex.convert(r"\somecommand") == "somecommand"


def test_double_backslash_line_break_becomes_space():
    assert latex.convert(r"a \\ b") == "a b"


def test_no_backslash_or_dollar_is_a_fast_no_op():
    text = "Nothing special here."
    assert latex.convert(text) is text


def test_book_load_converts_latex_in_txt(tmp_path):
    p = tmp_path / "math.txt"
    p.write_text(r"Let $\alpha$ be small and $x^2 + y^2 = r^2$.",
                 encoding="utf-8")
    book = books.Book.load(str(p))
    assert book.words[1] == "α"
    assert "x²" in book.words
