#!/usr/bin/env python3
"""Subprocess wrapper that runs a submitted Python `predict(case)` over a
stream of cases.

Protocol (kept identical for other languages so the harness is language
agnostic): read one JSON `case` object per stdin line, write one JSON result
object per stdout line, in the same order. A result is normalized to
`{"prediction": <str>, "reason": <str|null>, "error": <str|null>,
  "latency_ms": <float|null>}`.

The submitted script is isolated in its own process; the harness enforces the
timeout. The `case` object never contains the ground-truth place name, so a
script cannot score itself by reading the answer.

`latency_ms` is host-side wall time for one predict() call on this machine.
It is not a mobile-device measurement.
"""
import json
import importlib.util
import sys
import time


def _load_predict(path):
    spec = importlib.util.spec_from_file_location("submitted_predict", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "predict", None)
    if not callable(fn):
        raise SystemExit("submitted script defines no callable predict(case)")
    return fn


def _normalize(out):
    if isinstance(out, dict):
        return {"prediction": str(out.get("prediction") or "").strip(),
                "reason": out.get("reason")}
    if out is None:
        return {"prediction": "", "reason": None}
    return {"prediction": str(out).strip(), "reason": None}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: _predict_runner.py <script.py>")
    predict = _load_predict(sys.argv[1])
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        t0 = time.perf_counter()
        try:
            res = _normalize(predict(case))
            res["error"] = None
        except Exception as e:  # a failing case must not kill the whole run
            res = {"prediction": "", "reason": None, "error": repr(e)}
        res["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
