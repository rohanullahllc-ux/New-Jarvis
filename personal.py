"""Small personal touches applied to everything Jarvis says.

His replies are written with "sir" in them ("Ok sir", "Opening your tasks folder, sir."). ADDRESS_AS in .env lets you choose another
word (ma'am, boss, chief, your first name...); address() swaps it in, in the one place everything he says passes through (speech.py),
so no reply has to be rewritten. With the default, "sir", the text is left exactly as it is.

A title in front of a name is not the word being replaced: "Sir Isaac Newton" stays "Sir Isaac Newton".
"""
import re

import config

_SIR = re.compile(r"\b([Ss]ir)\b(?!\s+[A-Z][a-z])")


def address(text, word=None):
    """``text`` with "sir" replaced by the word the user chose (ADDRESS_AS), keeping a capital letter where there was one."""
    chosen = (config.ADDRESS_AS if word is None else word).strip()
    if not chosen or chosen.lower() == "sir" or "sir" not in text.lower():
        return text

    def swap(match):
        return chosen[0].upper() + chosen[1:] if match.group(1)[0] == "S" else chosen
    return _SIR.sub(swap, text)
