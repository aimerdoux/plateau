"""Module 2 of the D-037 target."""


def base2(x):
    return x + 2


def twice2(x):
    return 2 * base2(x)


def link_7():
    from d037_target.mod3 import MOD3_BATCH_LIMIT
    return MOD3_BATCH_LIMIT


def link_13():
    from d037_target.mod3 import MOD3_RATE_LIMIT
    return MOD3_RATE_LIMIT
