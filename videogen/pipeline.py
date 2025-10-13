import argparse, json, sys, re, time
from pathlib import Path
from typing import Any, Dict, List
from .registry import get_method, list_methods
from .types import ScriptItem, InputSpec, RunResult

# Import methods package so decorators run and register classes.
from . import registry  # noqa: F401
from .methods import *  # noqa: F401,F403

def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\-_.]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-") or "item"

def _load_input(path: Path) -> InputSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")
    project = data.get("project")
    script = data.get("script")
    if not project or not isinstance(project, str):
        raise ValueError("'project' must be a non-empty string")
    if not isinstance(script, list):
        raise ValueError("'script' must be an array of items")

    items: List[ScriptItem] = []
    for i, raw in enumerate(script):
        if not isinstance(raw, dict):
            raise ValueError(f"script[{i}] must be an object")
        text = raw.get("text", "")
        method = raw.get("method", "")
        prompt = raw.get("prompt", "")
        filename = raw.get("filename")
        if not isinstance(text, str) or not isinstance(method, str) or not isinstance(prompt, str):
            raise ValueError(f"script[{i}] must include string fields: text, method, prompt")
        if filename is not None and not isinstance(filename, str):
            raise ValueError(f"script[{i}].filename must be string if present")
        items.append(ScriptItem(text=text, method=method, prompt=prompt, filename=filename))
    return InputSpec(project=project, script=items)

def run_pipeline(input_path: Path, out_dir: Path) -> List[RunResult]:
    spec = _load_input(input_path)
    project_dir = out_dir / spec.project
    project_dir.mkdir(parents=True, exist_ok=True)

    results: List[RunResult] = []
    for idx, item in enumerate(spec.script, start=1):
        method_cls = get_method(item.method)
        if not method_cls:
            results.append(RunResult(
                ok=False, index=idx, item=item, method=item.method,
                artifacts=[], meta={}, error=f"Unknown method '{item.method}'"
            ))
            continue

        # determine a target base name
        base = item.filename or f"{idx:03d}_{_slugify(item.method)}"
        workdir = project_dir / f"{idx:03d}_{_slugify(item.method)}"
        workdir.mkdir(parents=True, exist_ok=True)

        method = method_cls()
        try:
            outcome = method.run(
                prompt=item.prompt,
                project=spec.project,
                target_name=base,
                text=item.text,
                workdir=workdir
            )
            artifacts = list(map(str, outcome.get("artifacts", [])))
            meta = outcome.get("meta", {})
            ok = bool(outcome.get("ok", False))
            err = outcome.get("error", None)
        except Exception as e:
            ok, artifacts, meta, err = False, [], {}, f\"{type(e).__name__}: {e}\"

        results.append(RunResult(
            ok=ok, index=idx, item=item, method=item.method,
            artifacts=artifacts, meta=meta, error=err
        ))

    # write a project-level manifest
    manifest = {
        "project": spec.project,
        "created_at": time.time(),
        "results": [
            {
                "index": r.index,
                "method": r.method,
                "ok": r.ok,
                "artifacts": r.artifacts,
                "error": r.error,
                "meta": r.meta
            } for r in results
        ]
    }
    (project_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return results

def main(argv=None):
    parser = argparse.ArgumentParser(description="videogen pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run pipeline on an input JSON")
    p_run.add_argument("input", type=str, help="Path to input JSON")
    p_run.add_argument("--out", type=str, default="outputs", help="Output directory (default: outputs)")

    p_list = sub.add_parser("list-methods", help="List available method names")

    args = parser.parse_args(argv)

    if args.cmd == "list-methods":
        for name in list_methods():
            print(name)
        return 0

    if args.cmd == "run":
        input_path = Path(args.input)
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = run_pipeline(input_path, out_dir)
        # Pretty print a short summary
        for r in results:
            status = "OK " if r.ok else "ERR"
            print(f"[{status}] #{r.index:02d} {r.method:15s} -> {', '.join(r.artifacts) or '-'}")
        print(f"\nManifest written to: {out_dir / _load_input(input_path).project / 'manifest.json'}")
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
