# 缅甸语&粤语 ASR 服务

## 识别慢时的常见原因与优化开关

服务默认优先识别质量（`large-v3`），在 CPU 或低端 GPU 上会偏慢。可以通过以下环境变量做速度优化：

- `WHISPER_MODEL_SIZE`：模型大小，建议按速度优先从 `large-v3` 调整为 `medium` / `small`。
- `WHISPER_DEVICE`：`auto` / `cuda` / `cpu`。有 NVIDIA GPU 时建议固定为 `cuda`。
- `WHISPER_COMPUTE_TYPE_CUDA`：建议 `float16`。
- `WHISPER_COMPUTE_TYPE_CPU`：建议 `int8`。
- `WHISPER_BEAM_SIZE`：解码束宽。追求速度建议 `1`~`2`（`docker-compose.yml` 默认已设为 `2`）。
- `WHISPER_VAD_FILTER`：默认 `true`。若输入语音较干净且追求速度，可设为 `false`。
- `PRELOAD_MODEL_ON_STARTUP`：设为 `true` 可减少首请求冷启动延迟（服务默认开启）。
- `WS_PARTIAL_MIN_BYTES`：WebSocket 增量识别最小字节增量，默认 `131072`，避免每个小 chunk 都触发全量重识别。
- `WS_PARTIAL_MIN_INTERVAL_MS`：WebSocket 增量识别最小触发间隔，默认 `1200` 毫秒，降低高频转码与解码开销。

另外，模型实例在进程内是单例缓存，不会在每次识别请求时重复初始化；慢通常来自首轮冷启动、ffmpeg 转码或过于高频的 WebSocket 增量全量重识别。

另外服务会在 `/api/transcribe` 打印阶段耗时日志（upload/convert/decode/total），便于判断瓶颈在上传、ffmpeg 转码还是模型推理。
