#include "c61_rx_probe.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "esp_app_desc.h"
#include "esp_heap_caps.h"
#include "esp_hosted_peer_data.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "stats.h"
#include "c61_sequence_window.h"

#define PROBE_RPC_ID 0xc610d001U
#define PROBE_CAPACITY 65536U

typedef struct {
    uint32_t packets, unique, duplicate, reordered, overflow, highest;
    uint32_t max_gap_us, consumed;
} probe_stats_t;

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static probe_stats_t s_stats;
static c61_sequence_window_t s_seen;
static int64_t s_last_us;
static int64_t s_sink_deadline_us;
static portMUX_TYPE s_heap_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_alloc_failed, s_alloc_size, s_alloc_caps;
static const char *s_alloc_function;
static int s_tx_error;
static uint32_t s_tx_wait, s_tx_recovered, s_tx_unrecovered, s_tx_max_wait_us;

void c61_tx_probe_backpressure(int result, uint32_t wait_us)
{
    portENTER_CRITICAL(&s_lock);
    s_tx_wait++;
    if (result == ESP_OK) {
        s_tx_recovered++;
    } else {
        s_tx_unrecovered++;
    }
    if (wait_us > s_tx_max_wait_us) {
        s_tx_max_wait_us = wait_us;
    }
    portEXIT_CRITICAL(&s_lock);
}

void c61_tx_probe_result(int result)
{
    if (result != 0) {
        portENTER_CRITICAL(&s_lock);
        s_tx_error = result;
        portEXIT_CRITICAL(&s_lock);
    }
}

static void allocation_failed(size_t size, uint32_t caps, const char *function)
{
    /* No allocation, heap queries or logging on the failing allocator's stack. */
    portENTER_CRITICAL(&s_heap_lock);
    s_alloc_failed++;
    s_alloc_size = size;
    s_alloc_caps = caps;
    s_alloc_function = function;
    portEXIT_CRITICAL(&s_heap_lock);
}

static uint16_t be16(const uint8_t *p)
{
    return ((uint16_t)p[0] << 8) | p[1];
}

static uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | p[3];
}

bool c61_rx_probe_observe(const void *buffer, uint16_t length)
{
    const uint8_t *p = buffer;
    if (!p || length < 54U || be16(p + 12) != 0x0800U ||
        (p[14] >> 4) != 4 || p[23] != 17 || (be16(p + 20) & 0x3fffU)) {
        return false;
    }
    const unsigned ihl = (p[14] & 15U) * 4U;
    if (ihl < 20U || length < 14U + ihl + 20U) {
        return false;
    }
    const uint8_t *udp = p + 14U + ihl;
    if (be16(udp + 2) != 5005U || be16(udp + 4) < 20U ||
        be32(udp + 8) != 0x43363144U) {
        return false;
    }
    const uint32_t sequence = be32(udp + 12);
    const int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    s_stats.packets++;
    if (sequence >= PROBE_CAPACITY) {
        s_stats.overflow++;
    } else {
        bool reordered = false;
        const c61_sequence_result_t result =
            c61_sequence_window_record(&s_seen, sequence, &reordered);
        if (result == C61_SEQUENCE_TOO_OLD) {
            s_stats.overflow++;
        } else if (result == C61_SEQUENCE_DUPLICATE) {
            s_stats.duplicate++;
        } else {
            if (reordered) {
                s_stats.reordered++;
            }
            if (!s_stats.unique || sequence > s_stats.highest) {
                s_stats.highest = sequence;
            }
            s_stats.unique++;
        }
    }
    if (s_last_us && now - s_last_us > s_stats.max_gap_us) {
        s_stats.max_gap_us = (uint32_t)(now - s_last_us);
    }
    s_last_us = now;
    const bool consume = now < s_sink_deadline_us;
    if (consume) {
        s_stats.consumed++;
    }
    portEXIT_CRITICAL(&s_lock);
    return consume;
}

static void probe_request(uint32_t id, const uint8_t *data, size_t length, void *ctx)
{
    (void)id;
    (void)ctx;
    char command[20];
    char reply[240];
    esp_err_t ret = ESP_OK;
    if (!data || !length || length >= sizeof(command)) {
        return;
    }
    memcpy(command, data, length);
    command[length] = '\0';
    if (!strcmp(command, "RESET")) {
        portENTER_CRITICAL(&s_lock);
        memset(&s_stats, 0, sizeof(s_stats));
        c61_sequence_window_reset(&s_seen);
        s_last_us = 0;
        portEXIT_CRITICAL(&s_lock);
    } else if (!strcmp(command, "SINK=1") || !strcmp(command, "SINK=0")) {
        portENTER_CRITICAL(&s_lock);
        /* Automatic expiry limits an abandoned test to two minutes. */
        s_sink_deadline_us = command[5] == '1' ? esp_timer_get_time() + 120000000LL : 0;
        portEXIT_CRITICAL(&s_lock);
    } else if (!strcmp(command, "PROMISC=0") || !strcmp(command, "PROMISC=1")) {
        ret = esp_wifi_set_promiscuous(command[8] == '1');
    } else if (!strcmp(command, "PHY=N20") || !strcmp(command, "PHY=AX20")) {
        uint8_t protocol = WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N;
        if (command[4] == 'A') {
            protocol |= WIFI_PROTOCOL_11AX;
        }
        ret = esp_wifi_set_protocol(WIFI_IF_STA, protocol);
        if (ret == ESP_OK) {
            ret = esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
        }
        /* Host Wi-Fi owner handles the disconnect event and reconnects. */
        if (ret == ESP_OK) {
            ret = esp_wifi_disconnect();
        }
    } else if (!strcmp(command, "INFO")) {
        const esp_app_desc_t *desc = esp_app_get_description();
        char sha[65];
        for (unsigned i = 0; i < 32; ++i) {
            snprintf(sha + i * 2, 3, "%02x", desc->app_elf_sha256[i]);
        }
        uint8_t protocol = 0;
        wifi_ps_type_t ps = WIFI_PS_NONE;
        bool promisc = false;
        const esp_err_t protocol_ret = esp_wifi_get_protocol(WIFI_IF_STA, &protocol);
        const esp_err_t ps_ret = esp_wifi_get_ps(&ps);
        const esp_err_t promisc_ret = esp_wifi_get_promiscuous(&promisc);
        snprintf(reply, sizeof(reply), "+C61I:probe=1,idf=%s,elf=%s,proto=0x%02x/ret%d,ps=%d/ret%d,prom=%d/ret%d,heap=%u",
                 desc->idf_ver, sha, protocol, protocol_ret, ps, ps_ret, promisc, promisc_ret,
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
        goto send;
    } else if (!strcmp(command, "HEAP")) {
        uint32_t failed, size, caps;
        const char *function;
        portENTER_CRITICAL(&s_heap_lock);
        failed = s_alloc_failed;
        size = s_alloc_size;
        caps = s_alloc_caps;
        function = s_alloc_function;
        portEXIT_CRITICAL(&s_heap_lock);
        snprintf(reply, sizeof(reply), "+C61HEAP:free=%u,largest=%u,min=%u,fail=%"PRIu32",size=%"PRIu32",caps=0x%"PRIx32",fn=%s",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
                 failed, size, caps, function ? function : "-");
        goto send;
    } else if (!strcmp(command, "TXSTATS")) {
#if ESP_PKT_STATS
        /* Existing lifetime counters, sampled after the UDP load has drained. */
        portENTER_CRITICAL(&s_lock);
        const int tx_error = s_tx_error;
        const uint32_t wait = s_tx_wait, recovered = s_tx_recovered;
        const uint32_t unrecovered = s_tx_unrecovered, max_wait = s_tx_max_wait_us;
        portEXIT_CRITICAL(&s_lock);
        snprintf(reply, sizeof(reply), "+C61TX:in=%"PRIu32",ok=%"PRIu32",fail=%"PRIu32",fc_on=%"PRIu32",fc_off=%"PRIu32",ret=%d,wait=%"PRIu32",recover=%"PRIu32",unrecovered=%"PRIu32",max_us=%"PRIu32,
                 pkt_stats.hs_bus_sta_in, pkt_stats.hs_bus_sta_out,
                 pkt_stats.hs_bus_sta_fail, pkt_stats.sta_flowctrl_on,
                 pkt_stats.sta_flowctrl_off, tx_error, wait, recovered, unrecovered, max_wait);
        goto send;
#else
        ret = ESP_ERR_NOT_SUPPORTED;
#endif
    } else if (!strcmp(command, "STATS")) {
        probe_stats_t stats;
        const int64_t now = esp_timer_get_time();
        portENTER_CRITICAL(&s_lock);
        stats = s_stats;
        const bool sink = now < s_sink_deadline_us;
        portEXIT_CRITICAL(&s_lock);
        snprintf(reply, sizeof(reply), "+C61RX:sink=%d,packets=%"PRIu32",unique=%"PRIu32",dup=%"PRIu32",reorder=%"PRIu32",overflow=%"PRIu32",highest=%"PRIu32",maxgap_us=%"PRIu32",consumed=%"PRIu32,
                 sink, stats.packets, stats.unique, stats.duplicate, stats.reordered,
                 stats.overflow, stats.highest, stats.max_gap_us, stats.consumed);
        goto send;
    } else {
        ret = ESP_ERR_INVALID_ARG;
    }
    snprintf(reply, sizeof(reply), "+C61:cmd=%s,ret=%d", command, ret);
send:
    ret = esp_hosted_send_custom_data(PROBE_RPC_ID, (const uint8_t *)reply, strlen(reply));
    if (ret != ESP_OK) {
        printf("C61 probe response failed: %d\n", ret);
    }
}

esp_err_t c61_rx_probe_init(void)
{
    esp_err_t ret = heap_caps_register_failed_alloc_callback(allocation_failed);
    if (ret != ESP_OK) {
        return ret;
    }
    return esp_hosted_register_custom_callback(PROBE_RPC_ID, probe_request, NULL);
}
