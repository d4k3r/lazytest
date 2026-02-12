import pytest
from your_module import add, factorial, reverse_string, average, Calculator, random_stats, fahrenheit_to_celsius

def test_add():
    assert add(1, 2) == 3
    assert add(-1, 1) == 0
    assert add(0, 0) == 0

def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120
    with pytest.raises(ValueError):
        factorial(-1)

def test_reverse_string():
    assert reverse_string("hello") == "olleh"
    assert reverse_string("") == ""
    assert reverse_string("12345") == "54321"

def test_average():
    assert average([1, 2, 3, 4, 5]) == 3
    assert average([]) == 0
    assert average([10, 20, 30]) == 20

def test_calculator():
    calc = Calculator()
    assert calc.add(2, 3) == 5
    assert calc.memory == 5
    assert calc.multiply(2, 3) == 6
    assert calc.memory == 6
    assert calc.clear() == 0
    assert calc.memory == 0

def test_random_stats():
    stats = random_stats(10)
    assert len(stats['data']) == 10
    assert 'max' in stats
    assert 'min' in stats
    assert 'avg' in stats

def test_fahrenheit_to_celsius():
    assert fahrenheit_to_celsius(32) == 0
    assert fahrenheit_to_celsius(212) == 100
    assert fahrenheit_to_celsius(98.6) == pytest.approx(37, rel=1e-2)
