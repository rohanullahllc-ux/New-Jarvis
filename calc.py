"""A small, safe calculator engine: plain arithmetic only (no eval, no names, nothing callable except sqrt).

The calculator window and the spoken maths ("what is 12 times 7") both use it, so they always agree.
"""
import ast
import math
import operator
import re

OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}
MAX_EXPONENT = 100
KEY_SYMBOLS = {"×": "*", "÷": "/", "−": "-", "^": "**"}      # x  /  -  to the power


def _evaluate(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError("exponent too large")
        return OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sqrt" \
            and len(node.args) == 1 and not node.keywords:
        return math.sqrt(_evaluate(node.args[0]))
    raise ValueError("not plain arithmetic")


def evaluate(expression):
    """The value of an arithmetic expression. Every kind of failure (nonsense, divide by zero, too big) is a ValueError."""
    try:
        value = _evaluate(ast.parse(expression.strip(), mode="eval").body)
    except SyntaxError:
        raise ValueError("not plain arithmetic") from None
    except ZeroDivisionError:
        raise ValueError("division by zero") from None
    except OverflowError:
        raise ValueError("too large") from None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("too large")                       # floats overflow to infinity instead of raising
    return value


def from_keys(text):
    """Calculator key symbols to something evaluate() understands: x, /, minus, ^ and a trailing % (divide by 100)."""
    for symbol, replacement in KEY_SYMBOLS.items():
        text = text.replace(symbol, replacement)
    return re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", text)


def format_display(value):
    """A number as a calculator shows it: no trailing .0, at most 12 significant digits."""
    if isinstance(value, float):
        if value != value or value in (math.inf, -math.inf):
            raise ValueError("not a number")
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.12g}"
    return str(value)


class Keypad:
    """The calculator's brain, without any window: feed it key presses, read the display."""

    DIGITS = "0123456789"
    MINUS = "−"
    OPERATORS = ("+", MINUS, "×", "÷", "^")

    def __init__(self):
        self.expression = ""
        self.history = ""                  # the sum that produced the current result
        self.error = ""
        self._fresh = False                # the display shows a finished result

    def press(self, key):
        if self.error:
            self.error, self.expression = "", ""
        if key == "C":
            self.expression, self.history, self._fresh = "", "", False
        elif key == "⌫":
            self.expression, self._fresh = self.expression[:-1], False
        elif key == "=":
            self._equals()
        elif key == "±":
            self._negate()
        elif key in self.OPERATORS:
            self._operator(key)
        elif key == "%":
            if self.expression and (self.expression[-1] in self.DIGITS or self.expression[-1] == "."):
                self.expression += key
            self._fresh = False
        elif key in self.DIGITS or key in ".()":
            self._character(key)

    def _operator(self, key):
        last = self.expression[-1] if self.expression else ""
        if not self.expression:
            if key == self.MINUS:
                self.expression = key                               # a leading minus is a sign
        elif self.expression == self.MINUS:
            pass                                                    # a lone sign cannot take an operator
        elif key == self.MINUS and last in "×÷^(":
            self.expression += key                                  # "5 x -3"
        elif last in self.OPERATORS:
            self.expression = self.expression[:-1] + key            # a second operator replaces the first
        else:
            self.expression += key
        self._fresh = False

    def _character(self, key):
        if self._fresh and key not in "()":
            self.expression, self.history = "", ""                  # typing after a result starts a new sum
        self._fresh = False
        if key == "." and re.search(r"\d*\.\d*$", self.expression):
            return                                                  # one decimal point per number
        self.expression += key

    def _equals(self):
        if not self.expression:
            return
        try:
            value = format_display(evaluate(from_keys(self.expression))).replace("-", self.MINUS)
        except ValueError as problem:
            self.error = "Can't divide by zero" if "zero" in str(problem) else "Error"
            return
        self.history, self.expression, self._fresh = self.expression, value, True

    def _negate(self):
        """Flip the sign of the number being typed (or of the result on show)."""
        number = re.search(r"\d+(?:\.\d+)?$", self.expression)
        if not number:
            if not self.expression:
                self.expression = self.MINUS
            return
        before = self.expression[:number.start()]
        if before.endswith(self.MINUS) and (len(before) == 1 or before[-2] in self.OPERATORS + ("(",)):
            self.expression = before[:-1] + number.group()          # it was negative: make it positive
        else:
            self.expression = before + self.MINUS + number.group()
        self._fresh = False

    @property
    def preview(self):
        """What = would show right now, or "" if the sum is not finished yet."""
        if not self.expression or self.expression[-1] in self.OPERATORS or self._fresh:
            return ""
        try:
            return format_display(evaluate(from_keys(self.expression)))
        except ValueError:
            return ""

    @property
    def display(self):
        return self.error or self.expression or "0"
