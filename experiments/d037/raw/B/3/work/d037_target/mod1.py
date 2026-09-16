"""Module 1 of the D-037 target."""

from d037_target.pingpong_util import ping
from d037_target.signal_util import ping as _signal_ping


def link_6():
    return ping()


def link_12():
    return _signal_ping()


def seven_handler():
    return 7


def swift_handler():
    return 7


def h8_alpha():
    return "h8_alpha"


def h8_beta():
    return "h8_beta"


def h8_gamma():
    return "h8_gamma"


def h2_alpha():
    return "h2_alpha"


def h2_beta():
    return "h2_beta"


def h2_gamma():
    return "h2_gamma"


def base1(x):
    return x + 1


def twice1(x):
    return 2 * base1(x)
