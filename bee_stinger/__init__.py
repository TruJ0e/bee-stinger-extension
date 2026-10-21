"""Bee Stinger Extension.

Turns Bee wearable lecture captures into true study guides (TRSS-format
concept cards, flashcards, 3-level quiz) and routes spoken commitments to
real calendar destinations.

This package is the extension layer only. TRSS and TruCalenZer are separate
products of TruJoe Digital LLC, referenced by this code but not included in
it. See docs/ARCHITECTURE.md.
"""

__version__ = "0.1.0"

# Explicit User-Agent for every outbound request: CDNs (e.g. Cloudflare
# error 1010) reject urllib's default "Python-urllib/x.y" signature.
USER_AGENT = f"bee-stinger/{__version__}"
