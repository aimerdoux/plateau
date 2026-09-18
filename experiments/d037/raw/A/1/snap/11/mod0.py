"""Module 0 of the D-037 target."""

MOD0_ITEM_LIMIT = 100
MOD0_RETRY_LIMIT = 100


def base0(x):
    return x + 0


def twice0(x):
    return 2 * base0(x)


def h1_alpha():
    return "h1_alpha"


def h1_beta():
    return "h1_beta"


def h1_gamma():
    return "h1_gamma"


def link_5():
    from d037_target.mod1 import seven_handler
    return seven_handler()


def h7_alpha():
    return "h7_alpha"


def h7_beta():
    return "h7_beta"


def h7_gamma():
    return "h7_gamma"


def link_11():
    from d037_target.mod1 import lucky_seven_handler
    return lucky_seven_handler()
