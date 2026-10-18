"""Unit conversions that work offline: length, weight, volume, area, speed, time and temperature.

"Convert 5 miles to kilometres" used to need Wolfram Alpha and its key. These are the everyday units, with exact factors,
so the answer comes at once and without an account. The words are the ones people say, plurals and abbreviations included.
"""
import re

# kind, singular, plural, how many of the kind's base unit it is, other ways of saying it
_UNITS = [
    ("length", "millimetre", "millimetres", 0.001, ("mm", "millimeter", "millimeters")),
    ("length", "centimetre", "centimetres", 0.01, ("cm", "centimeter", "centimeters")),
    ("length", "metre", "metres", 1.0, ("m", "meter", "meters")),
    ("length", "kilometre", "kilometres", 1000.0, ("km", "kms", "kilometer", "kilometers")),
    ("length", "inch", "inches", 0.0254, ("inchs",)),
    ("length", "foot", "feet", 0.3048, ("ft",)),
    ("length", "yard", "yards", 0.9144, ("yd", "yds")),
    ("length", "mile", "miles", 1609.344, ("mi",)),
    ("length", "nautical mile", "nautical miles", 1852.0, ("nmi",)),
    ("mass", "milligram", "milligrams", 1e-6, ("mg",)),
    ("mass", "gram", "grams", 0.001, ("g", "gm", "gms")),
    ("mass", "kilogram", "kilograms", 1.0, ("kg", "kgs", "kilo", "kilos")),
    ("mass", "tonne", "tonnes", 1000.0, ("metric ton", "metric tons")),
    ("mass", "ounce", "ounces", 0.028349523125, ("oz",)),
    ("mass", "pound", "pounds", 0.45359237, ("lb", "lbs")),
    ("mass", "stone", "stone", 6.35029318, ("stones",)),
    ("volume", "millilitre", "millilitres", 0.001, ("ml", "milliliter", "milliliters")),
    ("volume", "litre", "litres", 1.0, ("l", "liter", "liters")),
    ("volume", "gallon", "gallons", 3.785411784, ("gal", "us gallon", "us gallons")),
    ("volume", "pint", "pints", 0.473176473, ()),
    ("volume", "quart", "quarts", 0.946352946, ()),
    ("volume", "cup", "cups", 0.2365882365, ()),
    ("volume", "tablespoon", "tablespoons", 0.01478676478125, ("tbsp",)),
    ("volume", "teaspoon", "teaspoons", 0.00492892159375, ("tsp",)),
    ("volume", "fluid ounce", "fluid ounces", 0.0295735295625, ("fl oz",)),
    ("area", "square metre", "square metres", 1.0, ("square meter", "square meters", "sq m", "m2")),
    ("area", "square kilometre", "square kilometres", 1e6, ("square kilometer", "square kilometers", "sq km", "km2")),
    ("area", "square foot", "square feet", 0.09290304, ("sq ft", "ft2")),
    ("area", "square mile", "square miles", 2589988.110336, ("sq mi",)),
    ("area", "acre", "acres", 4046.8564224, ()),
    ("area", "hectare", "hectares", 10000.0, ()),
    ("speed", "metre per second", "metres per second", 1.0, ("meter per second", "meters per second", "m/s", "mps")),
    ("speed", "kilometre per hour", "kilometres per hour", 1 / 3.6,
     ("kilometer per hour", "kilometers per hour", "kph", "kmh", "km/h", "kilometres an hour", "kilometers an hour")),
    ("speed", "mile per hour", "miles per hour", 0.44704, ("mph", "miles an hour")),
    ("speed", "knot", "knots", 1852 / 3600, ("kn",)),
    ("time", "second", "seconds", 1.0, ("sec", "secs")),
    ("time", "minute", "minutes", 60.0, ("min", "mins")),
    ("time", "hour", "hours", 3600.0, ("hr", "hrs")),
    ("time", "day", "days", 86400.0, ()),
    ("time", "week", "weeks", 604800.0, ()),
    ("time", "year", "years", 31557600.0, ()),
]
_TEMPERATURES = [("celsius", ("centigrade", "degrees celsius", "degree celsius", "degrees centigrade")),
                 ("fahrenheit", ("degrees fahrenheit", "degree fahrenheit")),
                 ("kelvin", ("kelvins",))]

NAMES = {}                                               # every way of saying a unit -> (kind, size, singular, plural)
for _kind, _one, _many, _size, _others in _UNITS:
    for _word in (_one, _many, *_others):
        NAMES[_word] = (_kind, _size, _one, _many)
for _name, _others in _TEMPERATURES:
    for _word in (_name, *_others):
        NAMES[_word] = ("temperature", None, _name, _name)


def pattern():
    """A regular expression (no groups) that matches any unit word, the longest first so "miles per hour" beats "miles"."""
    return "(?:" + "|".join(re.escape(word) for word in sorted(NAMES, key=len, reverse=True)) + ")"


def _to_celsius(value, name):
    return value if name == "celsius" else (value - 32) * 5 / 9 if name == "fahrenheit" else value - 273.15


def _from_celsius(value, name):
    return value if name == "celsius" else value * 9 / 5 + 32 if name == "fahrenheit" else value + 273.15


def convert(value, source, target):
    """``value`` of the unit called ``source`` as a number of ``target`` units. A ValueError says why it can't be done."""
    start, end = NAMES.get(source.lower().strip()), NAMES.get(target.lower().strip())
    if start is None or end is None:
        raise ValueError(f"I don't know the unit {source if start is None else target}.")
    if start[0] != end[0]:
        raise ValueError(f"{start[3].capitalize()} and {end[3]} measure different things, sir.")
    if start[0] == "temperature":
        return _from_celsius(_to_celsius(value, start[2]), end[2])
    return value * start[1] / end[1]


def format_number(x):
    if abs(x) >= 100:
        text = f"{x:,.2f}"
    elif abs(x) >= 1:
        text = f"{x:,.4f}"
    else:
        text = f"{x:.6f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def sentence(value, source, target):
    """"5 miles is 8.0467 kilometres." Raises ValueError like convert()."""
    result = convert(value, source, target)
    start, end = NAMES[source.lower().strip()], NAMES[target.lower().strip()]
    one = lambda x: round(x, 6) == 1                         # (2.54 cm is 0.9999999999999999 inch, which is "1 inch")
    return f"{format_number(value)} {start[2] if one(value) else start[3]} is {format_number(result)} {end[2] if one(result) else end[3]}."
