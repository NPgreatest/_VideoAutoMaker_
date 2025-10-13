# videogen

A lightweight, modular Python pipeline that reads a JSON script and calls pluggable
generation **methods** to produce audio/video artifacts. The included methods are
stubs you can later replace with real implementations (e.g., Sora API, TTS, FFmpeg, etc.).

## Features
- Simple plugin/registry system for methods
- Per-line processing pipeline with project-scoped output folder
- Structured outputs and metadata
- Example methods: `Podcast` (produces a silent WAV as a placeholder), `Sora` and `ReactAnimation` (write video stubs + metadata)
- CLI: list methods, run a pipeline

## Quick Start
```bash
# (1) Run with the example JSON
python -m videogen.pipeline run examples/MH370_example.json --out outputs

# (2) List available methods
python -m videogen.pipeline list-methods
```

## JSON Schema (simplified)
```jsonc
{
  "project": "MH370_1",
  "script": [
    {
      "text": "Hello ...",
      "method": "Podcast",
      "prompt": "镜头正对老高..."
    },
    {
      "text": "MH370 从吉隆坡...",
      "method": "Sora",
      "prompt": "夜间机场跑道镜头..."
    },
    {
      "text": "机型是波音 777-200ER...",
      "method": "ReactAnimation",
      "prompt": "数据可视化动画..."
    }
  ]
}
```

## Add a New Method
Create a new file in `videogen/methods/`, subclass `BaseMethod`, and register it:

```python
from .base import BaseMethod, register_method

@register_method
class MyCoolMethod(BaseMethod):
    NAME = "MyCool"
    OUTPUT_KIND = "video"  # or "audio"

    def run(self, *, prompt: str, project: str, target_name: str, text: str, workdir) -> dict:
        # produce files in workdir / project
        ...
        return {"ok": True, "artifacts": [<paths>], "meta": {...}}
```

The pipeline discovers it automatically when the module is imported.
