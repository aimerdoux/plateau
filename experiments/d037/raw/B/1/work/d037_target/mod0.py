"""Module 0 of the D-037 target."""


MOD0_RETRY_LIMIT = 10


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


MOD0_QUEUE_LIMIT = 30


def h7_alpha():
    return "h7_alpha"


def h7_beta():
    return "h7_beta"


def h7_gamma():
    return "h7_gamma"


def link_11():
    from d037_target.mod1 import tally_handler
    return tally_handler()


MOD0_BURST_LIMIT = 50


def h13_alpha():
    return "h13_alpha"


def h13_beta():
    return "h13_beta"


def h13_gamma():
    return "h13_gamma"
