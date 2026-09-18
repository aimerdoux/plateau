"""Module 3 of the D-037 target."""


MOD3_BATCH_LIMIT = 20


def base3(x):
    return x + 3


def twice3(x):
    return 2 * base3(x)


def h4_alpha():
    return "h4_alpha"


def h4_beta():
    return "h4_beta"


def h4_gamma():
    return "h4_gamma"


def link_8():
    from d037_target.mod4 import lucky_handler
    return lucky_handler()
