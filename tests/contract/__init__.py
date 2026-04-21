"""Stage 2.9 canonical contract tier (per SUBPROJECT_TESTING_STANDARD §2).

Two layers (mirroring announcement follow-up #3):
- Layer 1: production canonical mapper assertions (subsystem_id /
  produced_at / canonical field renames; unconditional).
- Layer 2: real round-trip through ``contracts.Ex*.model_validate``
  (gated on [contracts-schemas] extra via importorskip).

Iron rule #4: this tier MUST contain real tests, not just
``__init__.py`` (avoid pytest exit code 5 "no tests collected").
"""
