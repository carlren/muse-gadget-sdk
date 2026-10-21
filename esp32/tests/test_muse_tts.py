# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
"""Run the production speech request/state machine against a fake HTTP client."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Speech(unittest.TestCase):
    def test_json_poll_retry_cancel_and_bounds(self):
        source = (ROOT / 'components/muse/muse_chat_session.cpp').read_text()
        cloud = source[source.index('/* ---- Cloud speech'):source.index('static void start_tts(void)')]
        code = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include "cJSON.h"
#define CONFIG_MUSE_TTS 1
#define CONFIG_MUSE_TTS_URL "https://openrouter.ai/api/v1/audio/speech"
#define CONFIG_MUSE_TTS_TOKEN "test-key"
#define CONFIG_MUSE_TTS_MODEL "x-ai/grok-voice-tts-1.0"
#define CONFIG_MUSE_TTS_VOICE "eve"
#define TEXT_MAX 1024
#define MP3_BUF 2097152
#define ESP_LOGI(...) ((void)0)
using esp_err_t = int;
constexpr int ESP_OK=0, ESP_ERR_HTTP_EAGAIN=1, HTTP_METHOD_POST=2, HTTP_EVENT_ON_DATA=3, HTTP_EVENT_ON_HEADER=4;
struct Http;
using esp_http_client_handle_t = Http*;
struct esp_http_client_event_t {
    int event_id; Http *client; int data_len; void *data;
    const char *header_key=nullptr, *header_value=nullptr;
};
struct esp_http_client_config_t {
    const char *url; int method; void (*crt_bundle_attach)();
    esp_err_t (*event_handler)(esp_http_client_event_t*); bool is_async; int timeout_ms;
};
struct Http { esp_http_client_config_t cfg; };
static int status=200, result=ESP_OK, opens, closes, failures;
static bool complete=true;
static size_t incoming=10;
static int64_t clock_us;
static void esp_crt_bundle_attach() {}
static Http *esp_http_client_init(esp_http_client_config_t *cfg) { opens++; return new Http{*cfg}; }
static int esp_http_client_get_status_code(Http*) { return status; }
static void esp_http_client_set_header(Http*,const char*,const char*) {}
static void esp_http_client_set_post_field(Http*,const char*,size_t) {}
static esp_err_t esp_http_client_set_timeout_ms(Http *h,int n) { h->cfg.timeout_ms=n; return ESP_OK; }
static bool esp_http_client_is_complete_data_received(Http*) { return complete; }
static void esp_http_client_cleanup(Http *h) { closes++; delete h; }
static esp_err_t esp_http_client_perform(Http *h) {
    static char data[MP3_BUF+1];
    esp_http_client_event_t header{HTTP_EVENT_ON_HEADER,h,0,nullptr,"content-type","audio/mpeg"};
    h->cfg.event_handler(&header);
    if (incoming) {
        esp_http_client_event_t ev{HTTP_EVENT_ON_DATA,h,(int)incoming,data};
        h->cfg.event_handler(&ev);
    }
    return result;
}
struct msg_t { char id[80]; size_t len; };
static struct {
    uint8_t mp3[MP3_BUF]; size_t mp3_len; bool mp3_ended; int tts_msg; msg_t msgs[1];
} s_turn;
static int64_t now_us() { return clock_us; }
static const char *esp_err_to_name(int) { return "test"; }
enum { M_MP3 };
static void mark(int) {}
static void stop_tts();
static void turn_fail(const char*) { failures++; stop_tts(); }
''' + cloud + r'''
static void begin() {
    stop_tts(); s_turn.mp3_len=0; s_turn.mp3_ended=false;
    s_tts_body=build_tts_body("Hello"); assert(s_tts_body);
    s_tts_attempt=1; assert(open_tts());
    assert(s_tts_http->cfg.is_async && s_tts_http->cfg.timeout_ms==100);
}
int main() {
    // Quotes, control characters, Unicode, and a maximum-length input remain valid JSON.
    for (auto text : {std::string("Say \"hello\"\\\n\t **world** _ok_ #tag `code` | \xf0\x9f\x98\x80"),
                     std::string(1000,'a'), std::string("caf\xc3\xa9"), std::string("bad\xe2\x82")}) {
        char *body=build_tts_body(text.c_str()); assert(body);
        cJSON *json=cJSON_Parse(body); assert(json);
        assert(!strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(json,"voice")),"eve"));
        assert(!cJSON_GetObjectItem(json,"provider"));
        const char *input=cJSON_GetStringValue(cJSON_GetObjectItem(json,"input")); assert(input);
        if (text.size()==1000) assert(strlen(input)==1000);
        assert(!strchr(input,'*') && !strchr(input,'_'));
        cJSON_Delete(json); free(body);
    }
    begin(); incoming=0; result=ESP_ERR_HTTP_EAGAIN;
    poll_tts(); assert(s_tts_http && !s_turn.mp3_ended && !failures);
    assert(s_tts_http->cfg.timeout_ms==5000); // tolerate gaps after streaming headers arrive
    incoming=10; result=ESP_OK;
    poll_tts(); assert(!s_tts_http && s_turn.mp3_ended && s_turn.mp3_len==10);
    // Retrying cannot replay partial audio: decode waits until a complete response.
    begin(); status=503; poll_tts(); assert(s_tts_http && s_tts_attempt==2 && !s_turn.mp3_len);
    status=200; poll_tts(); assert(!s_tts_http && s_turn.mp3_ended);
    begin(); status=400; int before=opens;
    poll_tts(); assert(!s_tts_http && failures==1 && opens==before);
    begin(); status=-1; incoming=0; result=ESP_ERR_HTTP_EAGAIN;
    clock_us+=45000001; poll_tts(); assert(s_tts_http && s_tts_attempt==2);
    clock_us+=45000001; poll_tts(); assert(!s_tts_http && failures==2);
    begin(); status=200; result=ESP_OK; incoming=MP3_BUF+1;
    poll_tts(); assert(!s_tts_http && failures==3 && !s_turn.mp3_len);
    begin(); incoming=10; complete=false;
    poll_tts(); assert(s_tts_http && s_tts_attempt==2 && !s_turn.mp3_ended);
    poll_tts(); assert(!s_tts_http && failures==4 && !s_turn.mp3_ended);
    begin(); stop_tts(); assert(!s_tts_http && !s_tts_body && opens==closes);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / 'tts.cpp').write_text(code)
            cjson = ROOT / 'managed_components/espressif__cjson/cJSON'
            subprocess.run(['cc', '-c', str(cjson / 'cJSON.c'), '-I', str(cjson),
                            '-o', str(temp / 'json.o')], check=True, capture_output=True)
            built = subprocess.run(['c++', '-std=c++17', '-I', str(cjson),
                                    str(temp / 'tts.cpp'), str(temp / 'json.o'),
                                    '-o', str(temp / 'tts')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(temp / 'tts')], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
