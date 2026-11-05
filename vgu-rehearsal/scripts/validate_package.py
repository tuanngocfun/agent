#!/usr/bin/env python3
"""Validate the portable teaching package, without private authoring evidence.

This deliberately delegates to check_portable.py. It inspects every recursive
notebook and the shipped decks, then runs the 18 reference and nine completed
Tier 1–2 example tests by default. It does not reproduce the private original
14-notebook/17-requirement provenance audit or certify learner understanding.
Use --skip-tests only to request saved-artifact inspection explicitly.
"""
from check_portable import main

if __name__ == '__main__':
    raise SystemExit(main())
