# 缅甸语&粤语 ASR 服务

## 模型路由

- `language=my`：显式切到 MMS-1B 识别
- `language=auto`：继续走 Whisper 自动识别
- `language=yue`：继续走 Whisper 粤语识别

为兼容现有前端和流式接口，缅语走 MMS 时仍返回相同 JSON 结构：`text`、`segments`、`detected_language`、`language_probability`。如果 MMS 不提供时间戳，服务会返回一个覆盖整段音频的单段 `segment`。

## 识别慢时的常见原因与优化开关

服务默认在 CPU 场景启用速度优先（`medium` + `beam=1`），如需更高精度可调整模型与解码参数。可以通过以下环境变量做速度/精度权衡：

- `WHISPER_MODEL_SIZE`：模型大小，建议按速度优先从 `large-v3` 调整为 `medium` / `small`。
- `WHISPER_DEVICE`：`auto` / `cuda` / `cpu`。有 NVIDIA GPU 时建议固定为 `cuda`。
- `WHISPER_COMPUTE_TYPE_CUDA`：建议 `float16`。
- `WHISPER_COMPUTE_TYPE_CPU`：建议 `int8`。
- `WHISPER_BEAM_SIZE`：解码束宽。追求速度建议 `1`~`2`（`docker-compose.yml` 默认已设为 `1`）。
- `WHISPER_VAD_FILTER`：默认 `true`。若输入语音已经很干净、且更想压缩处理时间，可手动设为 `false`。
- `WHISPER_LANGUAGE_DETECT_SECONDS`：`auto` 路径用于语言检测的前置预览音频时长，默认 `3.0` 秒。越短越快，但误判风险会上升。
- `MMS_MODEL_ID`：缅语 MMS 模型 ID，默认 `facebook/mms-1b-all`。
- `MMS_DEVICE`：`auto` / `cuda` / `mps` / `cpu`。仅作用于缅语 MMS 路径；在 Apple Silicon 上，`auto` 会优先选择 `mps`。
- `MMS_TORCH_DTYPE`：MMS 推理 dtype，默认 `float32`。
- `MMS_VAD_FILTER`：默认 `true`。会在 MMS 前置裁掉前后静音，降低缅语重转写时的无效计算。
- `PRELOAD_MODEL_ON_STARTUP`：设为 `true` 可减少首请求冷启动延迟（服务默认开启）。
- `WS_CHUNK_MS`：WebSocket 音频 chunk 时长（毫秒），默认 `20`。
- `WS_PARTIAL_MIN_BYTES`：WebSocket 增量识别最小字节增量；默认按 chunk 自动推导（16k/mono/16-bit/20ms 下为 `640`）。
- `WS_PARTIAL_MIN_INTERVAL_MS`：WebSocket 增量识别最小触发间隔；默认与 `WS_CHUNK_MS` 一致（默认 `20` 毫秒）。

### 低延迟实时架构（几十毫秒级）

如果你要按下面目标跑实时流：

- ASR：Paraformer（主）+ MMS（补充缅语）
- 前端：WebRTC / App 实时流
- VAD：Silero
- 推理：`20ms chunk`、`batch=1`、Metal / NPU

本项目当前已具备流式骨架（WebSocket + 增量转写 + VAD），并默认切到**20ms 粒度阈值**来触发 partial 解码节奏（`WS_CHUNK_MS=20`）：

- 默认 `WS_PARTIAL_MIN_BYTES` 会按 16k / mono / 16-bit / 20ms 自动推导为 `640` 字节；
- 默认 `WS_PARTIAL_MIN_INTERVAL_MS=20`；
- 如需适配 App 侧 PCM 格式，可改：
  - `WS_AUDIO_SAMPLE_RATE`
  - `WS_AUDIO_CHANNELS`
  - `WS_AUDIO_BYTES_PER_SAMPLE`

> 说明：当前代码里的主模型仍是 Whisper 路径；MMS 已用于缅语补充路由。若你要把 Paraformer 作为主路径，可在现有 `TranscriberRouter` 上替换主分支。

### WebSocket 真流式（降低首包响应时间）

`/api/ws/transcribe` 现在支持 **PCM 直通流式模式**：

- 当 `start` 消息里 `mime_type` 为 `audio/pcm` 或 `audio/L16` 时，服务不再对每次 partial 依赖 ffmpeg 容器转码；
- 服务会直接把实时 PCM chunk 组装为短窗口 WAV 后立刻增量解码，明显降低“第一次有文本返回”的时间；
- 容器音频（如 `audio/webm`）仍保持兼容，继续走原有转码路径。

另外已增加 **Opus 实时解码链路**：

- 客户端若上传 `audio/webm;codecs=opus` / `audio/ogg;codecs=opus`，服务端会先持续解码为 PCM；
- partial/final ASR 直接消费解码后的 PCM 缓冲区，不再每次 partial 都做“容器文件落盘 + 再转码”。

## 一键本地启动（Makefile）

已新增 `Makefile`，可直接一键启动本地开发环境：

```bash
# 1) 安装全部依赖（Python + Web）
make install

# 2) 一键启动后端 + 前端（开发模式）
make dev
```

常用命令：

- `make dev-backend`：仅启动后端（uvicorn）
- `make dev-web`：仅启动前端（Vite）
- `make docker-up`：Docker Compose 一键启动
- `make test`：运行测试

另外，Whisper 和 MMS 模型实例都会在进程内单例缓存，不会在每次识别请求时重复初始化；慢通常来自首轮冷启动、ffmpeg 转码或过于高频的 WebSocket 增量全量重识别。首次使用缅语时还会发生 Hugging Face 模型下载，镜像和冷启动都会比原来更重。

当前 `language=auto` 的策略是先用 Whisper 对前几秒音频做语言检测；如果检测到缅语，再放弃首轮文本，切到 MMS 做完整转写。这样比直接让 Whisper 先完整转一遍再改路由要快得多。

MMS 初始化完成后，日志会输出一条 `mms runtime initialized ...`，明确当前实际使用的 `device` 和 `torch_dtype`，便于确认在 Mac mini M4 上是否已经跑到 `mps`。

> 当前默认配置已针对 CPU 场景做速度优先：`WHISPER_MODEL_SIZE=medium`、`WHISPER_BEAM_SIZE=1`。如需更高精度可手动改回更大模型，但延迟会明显增加。

另外服务会在 `/api/transcribe` 打印阶段耗时日志（upload/convert/decode/total）。当开启 VAD 时，还会额外输出一条 `decode step=vad_done`，包含：

- `elapsed_ms`：本次 VAD 处理耗时
- `input_duration_ms`：原始音频时长
- `speech_duration_ms`：VAD 保留下来的语音时长
- `removed_silence_ms`：被裁掉的静音时长

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
