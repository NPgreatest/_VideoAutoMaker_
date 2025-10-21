# videogen

A comprehensive AI-powered video generation pipeline that transforms text scripts into multimedia content. The system intelligently decides between different generation methods (video, animation, subtitles) and produces synchronized audio/video outputs with professional quality.

## Features
- **Intelligent Method Selection**: LLM-powered decision engine automatically chooses the best generation method for each script line
- **Multi-Modal Generation**: Supports text-to-video, React animations, subtitle-only content, and audio synthesis
- **Character Voice Cloning**: Advanced TTS with character-specific voice profiles and emotional variations
- **Modular Architecture**: Pluggable method system with registry-based discovery
- **Project Management**: Structured project organization with metadata tracking
- **Real-time Processing**: Pipeline processes scripts line-by-line with progress tracking
- **Professional Output**: Generates synchronized audio, video, and subtitle files

## System Architecture

The videogen system consists of several key components:

### Core Components
- **Pipeline Engine** (`videogen/pipeline/`): Main orchestration system that processes JSON scripts
- **LLM Engine** (`videogen/llm_engine/`): Unified interface for language model interactions
- **Method Registry** (`videogen/methods/`): Pluggable generation methods with automatic discovery
- **Router/Decider** (`videogen/router/`): Intelligent method selection based on content analysis

### Generation Methods
- **`text_video_silicon`**: Text-to-video generation using SiliconFlow API
- **`react_render`**: Interactive React-based animations and data visualizations
- **`subtitle_only`**: Text-only content with subtitle generation
- **`audio_engine`**: Character voice synthesis with TTS and voice cloning

### Configuration
- **Character Profiles** (`config/character_profiles.json`): Voice and personality definitions
- **Audio Config** (`config/audio_config.yaml`): TTS model weights and reference audio
- **Project Structure**: Organized output with metadata tracking

## Quick Start

### 1. Generate a New Project
```bash
# Create a new project script
python project_json_generator.py
```

### 2. Run the Pipeline
```bash
# Process the project with different generation stages
python -m videogen.pipeline run project/mh370_demo/mh370_demo.json --out outputs

# Or run specific stages
python -m videogen.pipeline run project/mh370_demo/mh370_demo.json --decision --audio --media
```

### 3. List Available Methods
```bash
python -m videogen.pipeline list-methods
```

## Available Generation Methods

### Text-to-Video (`text_video_silicon`)
- **Purpose**: Generates video content from text descriptions
- **Use Case**: Scenic shots, action sequences, environmental footage
- **Output**: MP4 video files with metadata
- **API**: SiliconFlow text-to-video service

### React Animation (`react_render`)
- **Purpose**: Creates interactive data visualizations and animations
- **Use Case**: Charts, infographics, statistical displays, interactive elements
- **Output**: HTML/JSX components with React animations
- **Features**: Dynamic data binding, responsive design

### Subtitle Only (`subtitle_only`)
- **Purpose**: Text-focused content with subtitle generation
- **Use Case**: Narration, commentary, dialogue
- **Output**: SRT subtitle files with timing
- **Features**: Multi-language support, timing synchronization

### Audio Engine (`audio_engine`)
- **Purpose**: Character voice synthesis and audio generation
- **Use Case**: Voice-over, character dialogue, narration
- **Output**: WAV audio files with character-specific voices
- **Features**: Voice cloning, emotional variations, multi-character support

## JSON Schema

The system uses a structured JSON format for project definitions:

```jsonc
{
  "project": "mh370_demo",
  "script": [
    {
      "id": "L1",
      "text": "Hello 大家好，我是老高。咱们今天要聊的，是大家都希望我填的坑，马航MH370失踪事件。",
      "prompt": "A warmly lit home studio comes into focus...",
      "context": "",
      "decision": {
        "method": "text_video",
        "confidence": 1.0,
        "decided_by": "llm"
      },
      "generation": {
        "ok": true,
        "artifacts": ["project/mh370_demo/L1.mp4"],
        "meta": {
          "output_path": "project/mh370_demo/L1.mp4",
          "status": "Completed"
        }
      },
      "audioGeneration": {
        "ok": true,
        "artifacts": ["project/mh370_demo/audio/L1.wav"],
        "meta": {
          "total_duration": 9180
        }
      },
      "status": "done"
    }
  ]
}
```

## Configuration

### Environment Variables
Create a `.env` file in the project root:
```bash
# LLM Configuration
LLM_API_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=your_siliconflow_api_key
LLM_DEFAULT_MODEL=deepseek-llm

# Project Configuration
PROJECT_NAME=mh370_demo
```

### Character Profiles
Edit `config/character_profiles.json` to define character voices:
```json
{
  "老高": "一位40多岁的亚洲男性科学家，黑发微卷，略显凌乱，戴着金属边框眼镜...",
  "史强": "一位50岁左右的魁梧中国警官，皮肤粗糙，脸型宽大..."
}
```

### Audio Configuration
Configure TTS models in `config/audio_config.yaml`:
```yaml
characters:
  laogao:
    gpt_weights: GPT_weights_v2/laogao.ckpt
    sovits_weights: SoVITS_weights_v2/laogao.pth
    language: "zh"
    emotions:
      default:
        ref_audio_path: "reference/laogao.wav"
        prompt_text: "就是跟他这个成长的外部环境有关系..."
```

## Pipeline Stages

The system processes projects in several stages:

1. **Decision Stage** (`--decision`): LLM analyzes each script line and selects the appropriate generation method
2. **Audio Generation** (`--audio`): Generates character-specific voice audio using TTS
3. **Media Generation** (`--media`): Creates video content, animations, or subtitles based on decisions
4. **Final Assembly**: Combines all outputs into synchronized multimedia content

## Project Structure

```
project/
├── mh370_demo/
│   ├── mh370_demo.json          # Project definition
│   ├── audio/                    # Generated audio files
│   │   ├── L1.wav
│   │   └── L1_001.wav
│   ├── subtitles/               # Subtitle files
│   │   └── L1.srt
│   ├── L1.mp4                   # Generated video files
│   └── L1.meta.json            # Metadata for each segment
```

## Adding Custom Methods

Create a new method by subclassing `BaseMethod`:

```python
from videogen.methods.base import BaseMethod
from videogen.methods.registry import register_method

@register_method
class MyCustomMethod(BaseMethod):
    NAME = "MyCustom"
    OUTPUT_KIND = "video"  # or "audio", "other"

    def run(self, *, prompt: str, project: str, target_name: str, text: str, workdir, duration_ms=None, block=None) -> dict:
        # Your custom generation logic here
        output_path = workdir / "project" / project / f"{target_name}.mp4"
        
        # Generate your content...
        
        return {
            "ok": True,
            "artifacts": [str(output_path)],
            "meta": {
                "output_path": str(output_path),
                "duration": duration_ms
            }
        }

    def generate_prompt(self, text: str) -> str:
        # Generate prompts for your method
        return f"Create a video based on: {text}"
```

The pipeline automatically discovers registered methods when the module is imported.

## Dependencies

### Core Requirements
- Python 3.8+
- `dacite` - Data class conversion
- `python-dotenv` - Environment variable management
- `pathlib` - Path handling
- `dataclasses` - Data structure definitions

### External Services
- **SiliconFlow API** - Text-to-video generation
- **TTS Models** - Voice synthesis (GPT-SoVITS, etc.)
- **LLM API** - Method decision making and prompt generation

### Optional Dependencies
- `ffmpeg` - Video processing and concatenation
- `react` - For React animation rendering
- Various TTS model weights and reference audio files

## Example Projects

The `project/` directory contains several example projects:
- **`mh370_demo/`** - Complete MH370 documentary with multiple generation methods
- **`mh370_end/`** - Extended content with additional scenes
- **`mh370_mid/`** - Intermediate processing stages

Each project demonstrates different aspects of the pipeline:
- Mixed content types (video, animation, subtitles)
- Character voice synthesis
- Multi-language support
- Professional video assembly
