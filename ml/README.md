# ml/

Models, training, and inference.

**Stack:** _TBD_ — PyTorch, scikit-learn, ONNX Runtime, or an API call to a hosted
model. **Prefer a pretrained model or an API over training something.** Judges cannot
see training effort; they can see a demo that doesn't work.

## Contract

Consumes windows of `Telemetry`, produces `Detection`
(see [`../contracts/schemas/detection.schema.json`](../contracts/schemas/detection.schema.json)).

Fill in `explanation` on every detection. A model that says *why* reads as far more
sophisticated than one that emits a number, and it gives you something to narrate
on stage.

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
