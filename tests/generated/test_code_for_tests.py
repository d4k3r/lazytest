import pytest
import math
from datetime import datetime
import random

# Import the functions and classes from the user's code
# Assuming the code is in a module named "mymodule.py"
# If the code is in the same file, you can omit this import
# from mymodule import add, factorial, reverse_string, average, Calculator, random_stats, fahrenheit_to_celsius

# For demonstration, I'll define dummy references here
# Comment these if you import from your actual module
# from your_module import add, factorial, reverse_string, average, Calculator, random_stats, fahrenheit_to_celsius

# Since the actual functions are provided inline, we'll access them directly if in the same scope


# Tests for add
def test_add_integers():
    assert add(1, 2) == 3

def test_add_floats():
    assert math.isclose(add(1.5, 2.5), 4.0)

def test_add_negative():
    assert add(-1, -2) == -3

# Tests for factorial
@pytest.mark.parametrize("n, expected", [
    (0, 1),
    (1, 1),
    (5, 120),
    (3, 6),
])
def test_factorial_valid(n, expected):
    assert factorial(n) == expected

def test_factorial_negative():
    with pytest.raises(ValueError):
        factorial(-1)

# Tests for reverse_string
@pytest.mark.parametrize("input_str, expected", [
    ("abc", "cba"),
    ("", ""),
    ("a", "a"),
    ("racecar", "racecar"),
])
def test_reverse_string(input_str, expected):
    assert reverse_string(input_str) == expected

# Tests for average
def test_average_regular():
    data = [1, 2, 3, 4]
    assert average(data) == 2.5

def test_average_empty():
    assert average([]) == 0

def test_average_single_element():
    assert average([10]) == 10

# Tests for Calculator class
def test_calculator_add_and_multiply():
    calc = Calculator()
    assert calc.add(2, 3) == 5
    assert calc.memory == 5
    assert calc.multiply(4, 5) == 20
    assert calc.memory == 20

def test_calculator_clear():
    calc = Calculator()
    calc.add(1, 2)
    calc.clear()
    assert calc.memory == 0

# Tests for random_stats
def test_random_stats_default_size():
    stats = random_stats()
    data = stats["data"]
    assert len(data) == 5
    assert all(1 <= num <= 100 for num in data)
    assert stats["max"] == max(data)
    assert stats["min"] == min(data)
    # Check average calculation
    expected_avg = sum(data) / len(data)
    assert math.isclose(stats["avg"], expected_avg)

def test_random_stats_custom_size():
    size = 10
    stats = random_stats(size=size)
    data = stats["data"]
    assert len(data) == size

# Tests for fahrenheit_to_celsius
@pytest.mark.parametrize("fahrenheit, expected_celsius", [
    (32, 0),
    (212, 100),
    (68, 20),
    (0, -17.7778),
])
def test_fahrenheit_to_celsius(fahrenheit, expected_celsius):
    result = fahrenheit_to_celsius(fahrenheit)
    assert math.isclose(result, expected_celsius, rel_tol=1e-4)

# Note: The main() function prints output and isn't suitable for direct testing.
# However, you might mock the datetime if testing its output or just test the functions separately.

