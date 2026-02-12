import pytest
from your_module import add, factorial, reverse_string, average, Calculator, random_stats, fahrenheit_to_celsius

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
    assert add(100, -50) == 50

def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120
    assert factorial(3) == 6

def test_factorial_negative_input():
    with pytest.raises(ValueError, match="Negative input not allowed"):
        factorial(-1)
    with pytest.raises(ValueError, match="Negative input not allowed"):
        factorial(-5)

def test_reverse_string():
    assert reverse_string("hello") == "olleh"
    assert reverse_string("") == ""
    assert reverse_string("a") == "a"
    assert reverse_string("Python") == "nohtyP"
    assert reverse_string("  space ") == " ecaps  "

def test_average():
    assert average([1, 2, 3, 4, 5]) == 3.0
    assert average([10, 20, 30]) == 20.0
    assert average([]) == 0
    assert average([7]) == 7.0
    assert average([1.5, 2.5, 3.0]) == pytest.approx(2.333, rel=1e-3)
    assert average([-1, 0, 1]) == 0.0

class TestCalculator:
    def test_calculator_init(self):
        calc = Calculator()
        assert calc.memory == 0

    def test_calculator_add(self):
        calc = Calculator()
        assert calc.add(5, 7) == 12
        assert calc.memory == 12
        assert calc.add(-1, 1) == 0
        assert calc.memory == 0

    def test_calculator_multiply(self):
        calc = Calculator()
        assert calc.multiply(3, 7) == 21
        assert calc.memory == 21
        assert calc.multiply(10, 0) == 0
        assert calc.memory == 0
        assert calc.multiply(-2, 4) == -8
        assert calc.memory == -8

    def test_calculator_clear(self):
        calc = Calculator()
        calc.add(10, 5)
        assert calc.memory == 15
        assert calc.clear() == 0
        assert calc.memory == 0

def test_random_stats():
    stats = random_stats(size=10)
    assert isinstance(stats, dict)
    assert "data" in stats
    assert "max" in stats
    assert "min" in stats
    assert "avg" in stats

    assert isinstance(stats["data"], list)
    assert len(stats["data"]) == 10
    for num in stats["data"]:
        assert 1 <= num <= 100

    assert stats["max"] == max(stats["data"])
    assert stats["min"] == min(stats["data"])
    assert stats["avg"] == pytest.approx(sum(stats["data"]) / len(stats["data"]))

def test_random_stats_custom_size():
    stats = random_stats(size=3)
    assert len(stats["data"]) == 3
    stats = random_stats(size=1)
    assert len(stats["data"]) == 1

def test_fahrenheit_to_celsius():
    assert fahrenheit_to_celsius(32) == 0
    assert fahrenheit_to_celsius(212) == 100
    assert fahrenheit_to_celsius(-4) == pytest.approx(-20.0)
    assert fahrenheit_to_celsius(104) == pytest.approx(40.0)
    assert fahrenheit_to_celsius(98.6) == pytest.approx(37.0)
