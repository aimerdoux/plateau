from d037_target import mod0, mod1, mod2, mod3, mod4, mod5


def test_mod0():
    assert mod0.twice0(1) == 2 * (1 + 0)


def test_mod1():
    assert mod1.twice1(1) == 2 * (1 + 1)


def test_mod2():
    assert mod2.twice2(1) == 2 * (1 + 2)


def test_mod3():
    assert mod3.twice3(1) == 2 * (1 + 3)


def test_mod4():
    assert mod4.twice4(1) == 2 * (1 + 4)


def test_mod5():
    assert mod5.twice5(1) == 2 * (1 + 5)


