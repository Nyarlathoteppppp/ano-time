# FunASR Integration Guide

## Overview

FunASR has been added as an alternative ASR backend to the Real-Time Translator project. FunASR is Alibaba's fundamental end-to-end speech recognition toolkit with industrial-grade models.

## What is FunASR?

FunASR offers:
- 🎯 **High Accuracy**: Trained on 60,000+ hours of industrial data
- ⚡ **Low Latency**: Optimized for real-time transcription
- 🌍 **Multi-language Support**: Chinese (with dialects), English, Japanese, Korean, and more
- 🎤 **Advanced Features**: VAD, punctuation restoration, speaker diarization, emotion recognition
- 📦 **Multiple Models**: Paraformer, SenseVoice, Fun-ASR-Nano and more

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- `funasr`: The FunASR toolkit
- `modelscope`: Model hub for downloading FunASR models

### 2. Configure ASR Backend

Edit your `config.ini`:

```ini
[transcription]
backend = funasr
funasr_model = paraformer-zh
whisper_model = base
device = auto
compute_type = float16
source_language = auto
transcription_workers = 4
```

## Available FunASR Models

### Recommended Models

1. **paraformer-zh** (Default for Chinese)
   - Best for: Mandarin Chinese
   - Features: High accuracy, with timestamps
   - Size: 220M parameters
   - Training data: 60,000 hours

2. **paraformer-zh-streaming**
   - Best for: Real-time streaming Chinese ASR
   - Features: Low latency, streaming mode
   - Size: 220M parameters

3. **paraformer-en**
   - Best for: English speech recognition
   - Features: High accuracy for English
   - Size: 220M parameters
   - Training data: 50,000 hours

4. **SenseVoiceSmall** or **iic/SenseVoiceSmall**
   - Best for: Multi-language with emotion recognition
   - Features: ASR, Language ID, Sentiment, Emotion Detection
   - Languages: Chinese, Cantonese, English, Japanese, Korean
   - Size: 234M parameters

5. **Fun-ASR-Nano**
   - Best for: Multi-language, low-latency
   - Features: 31 languages, 7 Chinese dialects, 26 regional accents
   - Size: 800M parameters
   - Training data: Tens of millions of hours

## Configuration Options

### Backend Selection

Set the ASR backend in `config.ini`:

```ini
[transcription]
backend = whisper   # Options: whisper, mlx, funasr
```

- **whisper**: faster-whisper (CPU/CUDA)
- **mlx**: MLX Whisper (Apple Silicon GPU acceleration)
- **funasr**: FunASR (Alibaba models)

### Model Selection

For FunASR backend:

```ini
funasr_model = paraformer-zh
```

Common options:
- `paraformer-zh` - Mandarin Chinese
- `paraformer-zh-streaming` - Streaming Chinese
- `paraformer-en` - English
- `SenseVoiceSmall` - Multi-language with emotion
- `iic/SenseVoiceSmall` - Same as above (ModelScope format)
- `Fun-ASR-Nano` - Latest multi-language model

## Using the GUI Settings

1. Launch the dashboard:
   ```bash
   python dashboard.py
   ```

2. Click **Settings**

3. Configure:
   - **ASR Backend**: Select `funasr`
   - **FunASR Model**: Choose or type a model name
   - **Whisper Model**: (Only used when backend is whisper/mlx)

4. Click **Save & Restart**

## Performance Tips

### 1. Model Selection
- **Chinese speech**: Use `paraformer-zh`
- **English speech**: Use `paraformer-en`
- **Mixed languages**: Use `SenseVoiceSmall` or `Fun-ASR-Nano`
- **Streaming/Real-time**: Use models with `-streaming` suffix

### 2. Transcription Workers
- FunASR models are generally thread-safe
- Set `transcription_workers = 4` for parallel processing
- Adjust based on your CPU cores

### 3. Language Settings
```ini
source_language = auto
```
- Use `auto` for automatic language detection
- Or specify: `zh`, `en`, `ja`, `ko`, etc.

## Comparison: Whisper vs FunASR

| Feature | Whisper | FunASR |
|---------|---------|---------|
| **Languages** | 99+ languages | 31+ languages (specialized) |
| **Chinese Dialects** | Limited | 7 dialects, 26 accents |
| **Training Data** | General internet data | 60,000+ hours industrial data |
| **Latency** | Moderate | Low (optimized) |
| **Accuracy (Chinese)** | Good | Excellent |
| **Accuracy (English)** | Excellent | Very Good |
| **Extra Features** | Minimal | VAD, Punctuation, Emotion, Diarization |
| **Model Size** | 39M - 1550M | 220M - 800M |

## Troubleshooting

### Issue: Model download fails

FunASR models are downloaded from ModelScope on first use. If download fails:

1. Check internet connection
2. Try using a VPN if in restricted region
3. Manually specify model path:
   ```python
   funasr_model = /path/to/local/model
   ```

### Issue: Import error

```
ModuleNotFoundError: No module named 'funasr'
```

**Solution**: Install dependencies
```bash
pip install funasr modelscope
```

### Issue: Slow first inference

The first transcription may be slow due to:
1. Model downloading from ModelScope
2. Model loading and initialization
3. Warmup computation

This is normal. Subsequent inferences will be fast.

### Issue: Memory errors

FunASR models require significant memory. Solutions:
- Reduce `transcription_workers` to 1 or 2
- Use smaller models like `SenseVoiceSmall` instead of `Fun-ASR-Nano`
- Close other applications

## Advanced Usage

### Custom Model Path

You can use local models:

```ini
funasr_model = /path/to/your/custom/model
```

### Hotword Support

FunASR supports hotwords (prompt-based bias). The system automatically uses previous transcription as context.

### Batch Processing

FunASR processes in batches. Adjust batch size in `transcriber.py`:

```python
result = self.model.generate(
    input=audio_data,
    batch_size_s=300,  # Adjust this value
    hotword=prompt
)
```

## References

- **FunASR GitHub**: https://github.com/modelscope/FunASR
- **Model Zoo**: https://github.com/modelscope/FunASR#model-zoo
- **Documentation**: https://github.com/modelscope/FunASR/tree/main/docs
- **ModelScope Hub**: https://modelscope.cn/models

## Example Configurations

### For Chinese Podcasts
```ini
[transcription]
backend = funasr
funasr_model = paraformer-zh
source_language = zh
transcription_workers = 4
```

### For English Meetings
```ini
[transcription]
backend = funasr
funasr_model = paraformer-en
source_language = en
transcription_workers = 4
```

### For Multi-language Content
```ini
[transcription]
backend = funasr
funasr_model = SenseVoiceSmall
source_language = auto
transcription_workers = 2
```

### For Real-time Streaming
```ini
[transcription]
backend = funasr
funasr_model = paraformer-zh-streaming
source_language = zh
transcription_workers = 2

[audio]
streaming_mode = true
streaming_step_size = 0.2
update_interval = 0.5
```

## Support

For issues specific to:
- **This integration**: Open an issue in the project repo
- **FunASR toolkit**: Check https://github.com/modelscope/FunASR/issues
- **Model performance**: Refer to FunASR model zoo documentation
