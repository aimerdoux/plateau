"""Module 2 of the D-037 target."""

from d037_target.mod3 import MOD3_ITEM_LIMIT, MOD3_BATCH_LIMIT


def base2(x):
    return x + 2


def twice2(x):
    return 2 * base2(x)


def link_7():
    return MOD3_ITEM_LIMIT


def link_13():
    return MOD3_BATCH_LIMIT
