"""nsx26: redact a page image properly, then measure how much a solid box still gives away.

A flattened box destroys the pixels under it but not its own width. In a known
font, the width admits only some words; a word model ranks those by the visible
words on either side. `unredact` therefore produces ranked *guesses* with scores,
never a recovery, and `unredact evaluate` measures how often the first guess is
right on held-out text, with and without the defences `redact` offers.
"""
__version__ = "0.1.0"
CODENAME = "Black Mirror"
