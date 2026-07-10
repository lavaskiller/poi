#!/usr/bin/env python3
"""Subprocess wrapper that runs a submitted Python `predict(case)` over a
stream of cases.

Protocol (kept identical for other languages so the harness is language
agnostic): read one JSON `case` object per stdin line, write one JSON result
object per stdout line, in the same order. A result is normalized to
`{"prediction": <str>, "reason": <str|null>, "error": <str|null>}`.

The submitted script is isolated in its own process; the harness enforces the
timeout. The `case` object never contains the ground-truth place name, so a
script cannot score itself by reading the answer.
"""
import sys, json, importlib.util


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
        try:
            res = _normalize(predict(case))
            res["error"] = None
        except Exception as e:  # a failing case must not kill the whole run
            res = {"prediction": "", "reason": None, "error": repr(e)}
        sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
