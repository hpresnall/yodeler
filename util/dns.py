import re

# valid hostname & alias based on valid DNS
_valid = "^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\\-]*[a-zA-Z0-9])\\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\\-]*[A-Za-z0-9])$"


def invalid_hostname(alias: str) -> bool:
    return not re.match(_valid, alias)
