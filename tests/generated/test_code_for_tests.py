import pytest
import code_for_tests as module_0


def test_random_stats_executes_without_error():
    """
    Tests that `random_stats` can be called without arguments and
    executes successfully, returning a dictionary of stats.
    Pynguin often generates tests that simply ensure functions run without exceptions.
    """
    stats = module_0.random_stats()
    assert isinstance(stats, dict)
    assert "data" in stats
    assert "max" in stats
    assert "min" in stats
    assert "avg" in stats
    assert len(stats["data"]) == 5


def test_average_empty_list_returns_zero():
    """
    Tests that the `average` function correctly returns 0 when given an empty list,
    as per its defined behavior.
    """
    empty_list = []
    result = module_0.average(empty_list)
    assert result == 0

    # This call was part of the original Pynguin test, keeping it as per rule 4.
    module_0.random_stats()


def test_calculator_add_type_error_with_incompatible_types():
    """
    Tests that `Calculator` initializes its memory to 0.
    Also tests that the `add` method raises a TypeError when incompatible types
    (a dictionary and an integer) are provided as arguments, as arithmetic operations
    between these types are not supported.
    The original test also included a `reverse_string` call with a tuple, which
    doesn't raise an error as tuples support slicing.
    """
    # This part of the original test doesn't raise an error, tuples can be reversed.
    # Keeping it as per rule 4.
    empty_tuple = ()
    reversed_tuple = module_0.reverse_string(empty_tuple)
    assert reversed_tuple == ()

    int_val = 1590
    dict_val = {int_val: int_val} # Pynguin generated redundant keys, simplified.

    calculator = module_0.Calculator()
    assert calculator.memory == 0

    with pytest.raises(TypeError):
        calculator.add(dict_val, int_val)


def test_calculator_memory_initialization():
    """
    Tests that a new `Calculator` instance initializes its `memory` attribute to 0
    upon creation.
    """
    calculator = module_0.Calculator()
    assert calculator.memory == 0


def test_fahrenheit_to_celsius_type_error_with_object_input():
    """
    Tests that the `fahrenheit_to_celsius` function raises a TypeError
    when an incompatible object type (a Calculator instance) is provided as input,
    as arithmetic operations like subtraction are not defined for objects.
    """
    calculator_instance = module_0.Calculator()
    assert calculator_instance.memory == 0 # Asserting init state as per original test

    with pytest.raises(TypeError):
        module_0.fahrenheit_to_celsius(calculator_instance)


def test_factorial_of_false_boolean():
    """
    Tests that the `factorial` function correctly handles a `False` boolean input,
    treating it as 0 in an arithmetic context and returning 1, which is factorial(0).
    """
    boolean_false = False
    result = module_0.factorial(boolean_false)
    assert result == 1


def test_add_and_factorial_with_false_boolean():
    """
    Tests that the `add` function can handle boolean inputs (False, False)
    without error, and that `factorial` returns 1 for a `False` input,
    treating it as 0!
    """
    boolean_false = False
    # add(False, False) evaluates to 0 + 0 = 0. No assertion in original test.
    module_0.add(boolean_false, boolean_false)

    result = module_0.factorial(boolean_false)
    assert result == 1


def test_calculator_multiply_type_error_with_none_input():
    """
    Tests that `Calculator` initializes memory to 0 and that its `multiply` method
    raises a TypeError when `None` values are provided as arguments,
    as multiplication is not supported for `NoneType`.
    """
    none_value = None
    calculator = module_0.Calculator()
    assert calculator.memory == 0

    with pytest.raises(TypeError):
        calculator.multiply(none_value, none_value)


def test_calculator_clear_resets_memory():
    """
    Tests that the `clear` method of the `Calculator` class effectively
    resets its `memory` attribute to 0 and returns the new memory value.
    """
    calculator = module_0.Calculator()
    assert calculator.memory == 0

    # Simulate some operation that changes memory
    calculator.add(10, 20)
    assert calculator.memory == 30

    cleared_memory = calculator.clear()
    assert cleared_memory == 0
    assert calculator.memory == 0


def test_factorial_of_large_positive_integer():
    """
    Tests the `factorial` function with a large positive integer input (749)
    to ensure correct calculation of the large result.
    """
    large_int = 749
    result = module_0.factorial(large_int)
    # The expected value is a very long integer, directly copied from Pynguin's output.
    assert (
        result
        == 34410713185135346612310955264595034178649751795391943124041037759655506565736954127223688370983731749571510698893894119426216515134951474676441653285720428664161156975244362423887085597073462255059872622304753934584385800765680976056151750998575463364136641394001008155870301529001602235762602793271403139499447278331773373544957844236174264430682360267805578745073315735501649004125606727957225327928402234435112956680757659127867167861256032322763526227582862481416690723703241309626935146184841644769367662082788906114205480032053820455773407739204773348655511221662386562510019859098172471245119158801408574739999046771072062098633516590238232951816849010556025618946266713225104395514080205781997848927707641209487629912040169751772043747629919232377267786629399967230142556152896093364661522092171687069953373259987572210192566919531431729486421907152602628243022809582521849207149399855912662561733093096723070067229087350372318238194481406973685640143179843548583935910083695842445892974697921632149950205053175741218117581149458356252291969863555376813034255515437040121428261956660843174287063375479648377919853282306930017753681209564442291223986644062389994688339006422069638479157444096910329502621924755791393604164244023107452113525063412587959393758836363089495619862021815435322503991945102608197897865413768631283774175132576726262492159869530757337436789759850974036648433128599261972338078816902732405033032872629750789726011528372433417810261510616435195763998890829297222364816906121138610879383956215971591533774688338513916598377129491689958924375928862290891895027330984115937943202149962100912825071631785555025947787264000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
    )


def test_factorial_raises_value_error_for_negative_float():
    """
    Tests that the `factorial` function raises a `ValueError`
    when a negative float number is provided as input,
    as factorials are not defined for negative numbers.
    """
    negative_float = -1700.90317
    with pytest.raises(ValueError, match="Negative input not allowed"):
        module_0.factorial(negative_float)