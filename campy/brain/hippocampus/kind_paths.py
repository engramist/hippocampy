"""SPARQL property paths over the B508 kind vocabulary, as plain strings.

A leaf module (no imports) so the graph gateway and `kinds` can both use the
paths without importing each other (`kinds` -> `concept_links` -> gateway).
"""

NS = "https://campy.dev/ns#"

_B, _I, _L = f"<{NS}BROADER>", f"<{NS}INSTANCE_OF>", f"<{NS}IS_A>"
RELATION_PATH_UP = f"({_L}|{_I}|{_B})"            # one step from a thing to its kind / broader kind
RELATION_PATH_NARROWER_CLOSURE = f"({_B}|{_L})+"  # x ... transitively narrower than a kind
