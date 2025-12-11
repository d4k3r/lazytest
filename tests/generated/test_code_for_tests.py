import pytest
import code_for_tests as module_0


def test_calculator_initial_memory_is_zero():
    """
    Tests that a new Calculator instance initializes its memory to 0.
    """
    calculator = module_0.Calculator()
    assert calculator.memory == 0


def test_factorial_of_zero_or_false_is_one():
    """
    Tests the factorial function with 0 (represented by False), expecting 1.
    """
    input_false = False  # Represents 0 for factorial
    result = module_0.factorial(input_false)
    assert result == 1


def test_random_stats_runs_and_returns_valid_dict():
    """
    Tests that random_stats runs without error and returns a dictionary
    containing expected keys.
    """
    stats = module_0.random_stats()
    assert isinstance(stats, dict)
    assert "data" in stats
    assert "max" in stats
    assert "min" in stats
    assert "avg" in stats
    # Default size is 5, so data should not be empty
    assert len(stats["data"]) > 0


def test_add_none_inputs_raises_type_error():
    """
    Tests that the `add` function raises a TypeError when provided with None inputs,
    as `None + None` is not a valid operation for the current implementation.
    """
    none_value = None
    with pytest.raises(TypeError):
        module_0.add(none_value, none_value)


def test_reverse_string_with_set_input_raises_type_error():
    """
    Tests that `reverse_string` raises a TypeError when given a set,
    as slicing is not supported for set types.
    """
    string_item = ";R"
    set_input = {string_item}
    with pytest.raises(TypeError):
        module_0.reverse_string(set_input)


def test_fahrenheit_to_celsius_negative_and_factorial_of_one():
    """
    Tests `fahrenheit_to_celsius` with a negative temperature and
    `factorial` with True (representing 1).
    """
    temp_fahrenheit = -670
    celsius_result = module_0.fahrenheit_to_celsius(temp_fahrenheit)
    assert celsius_result == pytest.approx(-390.0, abs=0.01, rel=0.01)

    input_true = True  # Represents 1 for factorial
    factorial_result = module_0.factorial(input_true)
    assert factorial_result == 1


def test_calculator_clear_multiply_and_other_functions_interaction_with_error():
    """
    Tests a sequence of operations involving Calculator's clear and multiply methods,
    along with calls to random_stats and fahrenheit_to_celsius.
    It expects a TypeError when passing the dict from random_stats to fahrenheit_to_celsius.
    """
    boolean_false = False  # Represents 0 for multiplication
    stats_result = module_0.random_stats()

    calculator = module_0.Calculator()
    assert calculator.memory == 0

    cleared_memory = calculator.clear()
    assert cleared_memory == 0

    multiplication_result = calculator.multiply(boolean_false, boolean_false)
    assert multiplication_result == 0

    # The original test implicitly expects a TypeError here because random_stats returns a dict
    # which cannot be converted to a number for fahrenheit_to_celsius.
    with pytest.raises(TypeError):
        module_0.fahrenheit_to_celsius(stats_result)


def test_calculator_init_and_average_empty_set():
    """
    Tests Calculator initialization and the `average` function with an empty set,
    expecting 0 for the average.
    """
    calculator = module_0.Calculator()
    assert calculator.memory == 0

    empty_set = set()
    average_result = module_0.average(empty_set)
    assert average_result == 0


def test_calculator_add_with_invalid_inputs_raises_type_error():
    """
    Tests that the Calculator's `add` method raises a TypeError when provided
    with invalid inputs (Calculator instance and None), as these types
    cannot be added together by default.
    """
    calculator = module_0.Calculator()
    assert calculator.memory == 0
    none_value = None
    with pytest.raises(TypeError):
        calculator.add(calculator, none_value)


def test_fahrenheit_to_celsius_zero_and_factorial_negative_float_raises_value_error():
    """
    Tests `fahrenheit_to_celsius` with 0 (represented by False), then attempts to
    calculate factorial of the resulting negative float, expecting a ValueError
    as factorial requires a non-negative integer.
    """
    input_false = False  # Represents 0 for fahrenheit_to_celsius
    celsius_result = module_0.fahrenheit_to_celsius(input_false)
    assert celsius_result == pytest.approx(-17.77777777777778, abs=0.01, rel=0.01)

    calculator = module_0.Calculator()
    assert calculator.memory == 0

    # The result of celsius_result is a negative float. Factorial expects non-negative integer.
    with pytest.raises(ValueError):
        module_0.factorial(celsius_result)


def test_factorial_large_number():
    """
    Tests the factorial function with a large positive integer to ensure
    correct computation.
    """
    large_integer = 530
    expected_factorial = 282768894511806884040693317494735370870286197046072864302028207741271113386117033852466222933472122786772682350020152650999919970533061221386323313882305934011462307855449050928566133687410293036422487860399384068845790046863045540180941988541957188254532687202791519082367309728191470169980778292757553431674977335265243475713534382581749321602682911447453290670973238139709551042971492351749733968629134542927530351530221420809914260044514670968078715911827086155447913046577969655138455884483555451345444319574660430853057027923759585503690978031665726788905516741791667846792264313354848976875267653207821904313677295856782885996737741116688967815517699034366346591629436709793297124503266471303838021662061093985373694716142826449392228193812963934435539158055815890569433795049624000656583722673786751986848754823629381782087544325280817639928189638620892885273715838119765934710726750209229048051094966960032087070016524059514707803973153805323170695038503598172993829892791794751923820321139675566388826511777529812786513242305956477638747236419518416172799287014058118736773120000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
    result = module_0.factorial(large_integer)
    assert result == expected_factorial