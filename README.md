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

## 调试日志判读模板（建议按 request_id/session_id 追踪）

当出现“检测到语言但迟迟不返回”时，可按以下顺序检查日志：

1. **HTTP 文件识别（`/api/transcribe`）**
   - 关键日志：
     - `transcribe request_id=... step=upload_start/upload_done`
     - `transcribe request_id=... step=convert_start/convert_done`
     - `transcribe request_id=... step=decode_start/decode_done`
     - `transcribe request_id=... timing: ...`
   - 判读：
     - 卡在 `upload_*`：上传慢/文件过大。
     - 卡在 `convert_*`：ffmpeg 转码慢或格式异常。
     - 卡在 `decode_*`：模型推理慢（通常与模型大小、设备、beam_size 相关）。

2. **HTTP 流式识别（`/api/transcribe/stream`）**
   - 关键日志：
     - `transcribe_stream request_id=... step=upload_*`
     - `transcribe_stream request_id=... step=convert_*`
     - `transcribe_stream request_id=... step=decode_*`
   - 判读与上面一致；如果出现 `step=failed`，优先查看同 request_id 的异常堆栈。

3. **WebSocket 实时识别（`/api/ws/transcribe`）**
   - 关键日志：
     - `ws_transcribe step=session_started session_id=...`
     - `ws_transcribe step=chunk_received session_id=...`
     - `ws_transcribe step=partial_decoded session_id=...`
     - `ws_transcribe step=final_convert_* / final_decode_*`
   - 判读：
     - 有 `chunk_received` 但无 `partial_decoded`：可能 chunk 太小未触发 partial，或转码失败被跳过。
     - 有 `final_decode_start` 无 `final_decode_done`：最终解码阶段耗时过长或超时。

4. **超时/异常快速定位**
   - 关键日志：
     - `transcribe request_id=... last_step=... timeout_seconds=...`
     - `transcribe_stream request_id=... last_step=... timeout_seconds=...`
     - `step=failed last_step=...`
   - 判读：
     - `last_step=decode_start`：通常是模型推理耗时过长。
     - `last_step=convert_start`：通常是 ffmpeg 转码耗时或输入音频异常。
