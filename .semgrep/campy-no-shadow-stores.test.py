# Test fixtures for campy-no-shadow-stores Semgrep rules.
# Semgrep annotation comments (ok / ruleid) appear inline below each case.

# ok: campy-shadow-store-dict
LOCAL_LOOKUP = {}  # name doesn't match pattern — should not flag


# ruleid: campy-shadow-store-dict
_store = {}

# ruleid: campy-shadow-store-dict
_cache = {}

# ruleid: campy-shadow-store-dict
_cache: dict = {}

# ruleid: campy-shadow-store-dict
_store = dict()

# ruleid: campy-shadow-store-list
_registry = []

# ruleid: campy-shadow-store-list
_state = []

# ruleid: campy-shadow-store-list
_registry: list = []

# ruleid: campy-shadow-store-list
_state = list()


# ruleid: campy-shadow-store-dict
session_cache = {}

# ruleid: campy-shadow-store-dict
agent_state = {}

# ruleid: campy-shadow-store-list
node_registry = []

# ok: campy-shadow-store-dict
statement = {}  # "state" is not an underscore-delimited component

# ok: campy-shadow-store-dict
database = {}  # "db" is not present as an underscore-delimited component


def function_with_local():
    # ok: campy-shadow-store-dict
    local_cache = {}  # inside a function — should not flag
    # ok: campy-shadow-store-list
    local_store = []  # inside a function — should not flag
    return local_cache, local_store


class MyClass:
    # ok: campy-shadow-store-dict
    class_cache = {}  # inside a class — should not flag
