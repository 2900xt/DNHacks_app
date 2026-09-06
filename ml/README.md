# ml/

Models, training, and inference.

**Stack:** _TBD_ — PyTorch, scikit-learn, ONNX Runtime, or an API call to a hosted
model. **Prefer a pretrained model or an API over training something.** Judges cannot
see training effort; they can see a demo that doesn't work.

## Contract

This lane does not run a model. It builds the graph artifacts in `web/data/` from
openFDA and the official lists, and it owns the transparent risk rules
(`cascade_rules.py`, decision 0003) rather than a learned scorer.

The AEGIS pathfinder (`aegis.py`) is the one piece the console consumes as a
scored artifact: `make aegis` (or `python3 ml/aegis.py --write`) scores every
active DMF holder of every `precursor:` node and writes `web/data/reroute.json`,
keyed by graph node ids. The console re-ranks survivors itself as nodes are
switched off, so nothing on stage calls Python or the network. Re-run it after
`nodes.curated.json` changes; it warns about any holder with no company node.

Storage evaluation lives in `services/api/depot.py`, against
[`../contracts/schemas/depot.schema.json`](../contracts/schemas/depot.schema.json).

Every verdict names the rule that fired it. A rule that says *why* reads as far more
sophisticated than a number, and it gives you something to narrate on stage.

## Rules of thumb for 26 hours

- Ship a **stub predictor first** (rules, or random with realistic timing) so the UI
  and service can be built against real-shaped data within the first two hours.
  Swap in the real model behind the same interface later.
- Cache aggressively. Nothing in the demo should wait on a cold model load.
- Keep artifacts out of git (`.gitignore` already excludes `*.pt`, `*.onnx`, etc.).
  Note where they actually live here.

## Notes

_Model:_
_Artifact location:_
_Inference latency:_
