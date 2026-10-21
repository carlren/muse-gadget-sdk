# Spoken Muse replies with OpenRouter

Optional firmware support speaks completed voice-chat replies through the
gadget speaker using OpenRouter. The default model is
`x-ai/grok-voice-tts-1.0`, voice `eve`. No local TTS server is required.
The feature is disabled by default and requires a non-compact voice profile
with sufficient PSRAM.

## Configuration

Enable these settings in the ignored build directory's `sdkconfig`:

```ini
CONFIG_MUSE_TTS=y
CONFIG_MUSE_TTS_URL="https://openrouter.ai/api/v1/audio/speech"
CONFIG_MUSE_TTS_MODEL="x-ai/grok-voice-tts-1.0"
CONFIG_MUSE_TTS_VOICE="eve"
# Set CONFIG_MUSE_TTS_TOKEN privately in this same file.
CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE=y
CONFIG_MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH="openrouter_roots.pem"
```

Retain the SDK token and board profile required by the normal firmware
build. Do not commit generated configuration, binaries, flash backups,
recordings, or runtime logs: they can contain credentials or conversation
data. API keys are embedded in the resulting firmware image. ESP-IDF can
also echo configured credentials during configuration; redact build output
before sharing it.

With ESP-IDF 6.0.1 activated, build and flash the appropriate board profile
as described in the ESP32 README. For the Waveshare 1.75C profile, from
`esp32/`:

```sh
idf.py -B build-muse-waveshare-s3-175c build
idf.py -B build-muse-waveshare-s3-175c -p /dev/ttyACM0 flash
```

The bundled public GTS Root R4 and GlobalSign Root CA certificates supplement
the default trust bundle for OpenRouter's certificate chain. TLS certificate
verification remains enabled.

## Behavior and limits

- The speaker switch still controls spoken replies. When muted, the stock
  caption pacing remains active. Typed USB chat remains unspoken.
- cJSON constructs the request, including correct escaping of quotes,
  backslashes, and control characters. Basic markdown and emoji are removed;
  complete UTF-8 sequences are preserved within the stock 1,023-byte text
  limit.
- The existing session task polls asynchronously for response headers,
  allowing chat commands and connection pings during the initial provider
  wait. Once audio headers arrive, body reads allow five-second gaps between
  generated segments. ESP-IDF 6.0.1 otherwise reports a short body-read timeout
  as incomplete data. Reading the body can occupy the task for several
  seconds.
- Each attempt has a 45-second polling deadline. An in-progress HTTP body
  read can extend beyond that deadline. Transient network, server, and
  rate-limit failures are retried once; permanent HTTP 400 errors are not.
- The full HTTP 200 `audio/mpeg` response is validated before decoding.
  Retrying cannot replay a partially spoken sentence. The 2 MiB MP3 buffer
  accommodates 120 seconds at the observed 128 kbps bitrate. Overflow,
  incomplete responses, and invalid content types fail explicitly.
- A failed request shows `SPEECH UNAVAILABLE` instead of silently pacing an
  apparently successful spoken reply.

Provider synthesis time and Muse's upstream transcription/agent processing
both affect the delay before speech. This firmware change does not shorten
the upstream reply stage.

## Verification

Run the host checks from `esp32/` after a normal firmware build has populated
the managed components:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

`tests/test_muse_tts.py` compiles the production request builder and HTTP
state machine against a fake client. It exercises JSON escaping, long
inputs, UTF-8 boundaries, polling, streaming body timeouts, retries,
cancellation, incomplete transfers, and overflow.

The implementation was built for the Waveshare 1.75C and AIPI profiles and
tested through five consecutive microphone-to-speaker turns, including an
approximately 1,000-character reply with 57 seconds of complete playback.

For hardware acceptance, wait for each reply to finish before sending the
next voice note. Verify HTTP 200, non-empty MP3 data, `speaking message ...
via TTS`, and complete audible playback for every reply. Include a long
response and check its ending. A decoder self-test alone does not establish
end-to-end speech success. Keep device identifiers, reply content, and
credentials out of published evidence.
