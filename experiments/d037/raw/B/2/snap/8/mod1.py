"""Module 1 of the D-037 target."""

from d037_target.ping_util import ping


def base1(x):
    return x + 1


def twice1(x):
    return 2 * base1(x)


def mod1_seven_handler():
    return 7


def h2_alpha():
    return "h2_alpha"


def h2_beta():
    return "h2_beta"


def h2_gamma():
    return "h2_gamma"


def link_6():
    return ping()


def mod1_eight_handler():
    return 7


def h8_alpha():
    return "h8_alpha"


def h8_beta():
    return "h8_beta"


def h8_gamma():
    return "h8_gamma"
