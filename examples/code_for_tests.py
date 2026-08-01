import math
import random
from datetime import datetime


def add(a, b):
    """Return the sum of two numbers."""
    return a + b


def factorial(n):
    """Compute factorial recursively."""
    if n < 0:
        raise ValueError("Negative input not allowed")
    return 1 if n in (0, 1) else n * factorial(n - 1)


def reverse_string(s):
    """Reverse a given string."""
    return s[::-1]


def average(numbers):
    """Return the average of a list of numbers."""
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)


class Calculator:
    """A simple calculator class."""

    def __init__(self):
        self.memory = 0

    def add(self, a, b):
        result = a + b
        self.memory = result
        return result

    def multiply(self, a, b):
        result = a * b
        self.memory = result
        return result

    def clear(self):
        self.memory = 0
        return self.memory


def random_stats(size=5):
    """Generate random numbers and return some basic stats."""
    data = [random.randint(1, 100) for _ in range(size)]
    return {
        "data": data,
        "max": max(data),
        "min": min(data),
        "avg": average(data)
    }


def main():
    print("=== Sample Python Script ===")
    print(f"Run time: {datetime.now()}")

    print("\n--- Basic Function Tests ---")
    print("Add(5, 7):", add(5, 7))
    print("Factorial(5):", factorial(5))
    print("Reverse('testing'):", reverse_string("testing"))
    print("Average([1,2,3,4,5]):", average([1, 2, 3, 4, 5]))

    print("\n--- Class Tests ---")
    calc = Calculator()
    print("Add using Calculator:", calc.add(10, 5))
    print("Multiply using Calculator:", calc.multiply(3, 7))
    print("Memory cleared:", calc.clear())

    print("\n--- Random Stats ---")
    stats = random_stats()
    for k, v in stats.items():
        print(f"{k}: {v}")

    print("\nAll tests completed successfully!")


if __name__ == "__main__":
    main()
