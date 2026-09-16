"""Module 5 of the D-037 target."""

from d037_target.mod0 import MOD0_ITEM_LIMIT


def base5(x):
    return x + 5


def twice5(x):
    return 2 * base5(x)


def link_4():
    return MOD0_ITEM_LIMIT
