#pragma once

/*
 * Product media tuning.
 *
 * Keep values that are adjusted during camera, transport, and call tuning in
 * this file. Kconfig is reserved for build composition and hardware feature
 * switches; generated sdkconfig files must not become the source of truth for
 * runtime media policy.
 */

/* Normal RTC/IPC uplink profile. SC2336 exposes 1024x600 natively. */
#define APP_MEDIA_CAMERA_CAPTURE_WIDTH                  1024U
#define APP_MEDIA_CAMERA_CAPTURE_HEIGHT                 600U
#define APP_MEDIA_RTC_VIDEO_WIDTH                       1024U
#define APP_MEDIA_RTC_VIDEO_HEIGHT                      600U
#define APP_MEDIA_RTC_H264_BITRATE_BPS                  4000000U
#define APP_MEDIA_RTC_H264_FPS                          20U
#define APP_MEDIA_RTC_H264_MIN_QP                       30U
#define APP_MEDIA_RTC_H264_MAX_QP                       45U

/*
 * Stable full-duplex device-call profile.
 *
 * The encoder bitrate is a rate-control target, not a hard ceiling. Use the
 * 384x256 landscape surface to keep the P4 software decoder inside the frame
 * budget under full-frame motion. The Qiming renderer scales once through PPA
 * to its 640x480 DSI viewport while preserving aspect ratio. Keep the validated
 * per-frame bit budget while reserving CPU time for UI and transport. Let rate
 * control
 * use the full legal H.264 QP range when full-frame motion would otherwise
 * exceed the peer's software-decode budget. Weak-network adaptation remains
 * opt-in and starts from this normal profile.
 */
#define APP_MEDIA_CALL_VIDEO_WIDTH                      384U
#define APP_MEDIA_CALL_VIDEO_HEIGHT                     256U
#define APP_MEDIA_CALL_VIDEO_FPS                        12U
#define APP_MEDIA_CALL_VIDEO_BITRATE_BPS                256000U
#define APP_MEDIA_CALL_VIDEO_MIN_QP                     34U
#define APP_MEDIA_CALL_VIDEO_MAX_QP                     51U

/* WeChat negotiates a fixed supported edge length. Keep its uplink at the
 * native landscape surface instead of inheriting the P4-to-P4 decoder guard. */
#define APP_MEDIA_WECHAT_VIDEO_WIDTH                    480U
#define APP_MEDIA_WECHAT_VIDEO_HEIGHT                   320U
#define APP_MEDIA_WECHAT_VIDEO_FPS                      15U
#define APP_MEDIA_WECHAT_VIDEO_BITRATE_BPS              480000U
#define APP_MEDIA_WECHAT_VIDEO_MIN_QP                   30U
#define APP_MEDIA_WECHAT_VIDEO_MAX_QP                   46U
/* H264 encoder and transport protection. */
/*
 * IPC keeps a two-second recovery interval. Full-duplex calls use four
 * seconds to reduce IDR work without making recovery depend entirely on a PLI
 * traversing the same congested TGTRP path. This bounds reference-chain loss
 * while stream start, subscription and peer requests can still force an IDR.
 */
#define APP_MEDIA_H264_GOP_DURATION_MS                  2000U
#define APP_MEDIA_CALL_H264_GOP_DURATION_MS              4000U
#define APP_MEDIA_H264_OUTPUT_BUFFER_BYTES              (1024U * 1024U)
#define APP_MEDIA_H264_MAX_DELTA_PAYLOAD_BYTES          (256U * 1024U)
#define APP_MEDIA_H264_STARTUP_GUARD_MS                 2500U
#define APP_MEDIA_H264_STARTUP_MAX_DELTA_PAYLOAD_BYTES  (128U * 1024U)
#define APP_MEDIA_H264_KEY_FRAME_REQUEST_MIN_INTERVAL_MS 2000U
#define APP_MEDIA_TRANSPORT_BACKPRESSURE_HOLD_MS        80U

/* Local pressure fallback. Disabled builds do not execute this policy. */
#define APP_MEDIA_AUTO_DEGRADE_SAMPLES                  2U
#define APP_MEDIA_AUTO_RECOVER_SAMPLES                  6U
#define APP_MEDIA_AUTO_COOLDOWN_MS                      10000U
#define APP_MEDIA_AUTO_PRESSURE_BUFFER_PCT              8U
#define APP_MEDIA_AUTO_SEVERE_BUFFER_PCT                20U
#define APP_MEDIA_AUTO_HEALTHY_BUFFER_PCT               2U
#define APP_MEDIA_AUTO_PRESSURE_QUEUE_DEPTH             2U
#define APP_MEDIA_AUTO_SEVERE_QUEUE_DEPTH               4U
/*
 * A healthy link always starts at 100%. Sustained pressure steps through
 * progressively smaller encoder budgets without rebuilding the negotiated
 * resolution. Severe pressure advances two levels so a 96 KB/s path reaches
 * a survivable media budget before MQTT keepalive is starved. Recovery still
 * moves one level at a time after the longer healthy-sample gate above.
 */
#define APP_MEDIA_AUTO_LEVEL1_BITRATE_PERCENT           60U
#define APP_MEDIA_AUTO_LEVEL2_BITRATE_PERCENT           35U
#define APP_MEDIA_AUTO_LEVEL3_BITRATE_PERCENT           10U
#define APP_MEDIA_AUTO_LEVEL1_FPS_PERCENT               75U
#define APP_MEDIA_AUTO_LEVEL2_FPS_PERCENT               50U
#define APP_MEDIA_AUTO_LEVEL3_FPS_PERCENT               25U
#define APP_MEDIA_AUTO_SEVERE_LEVEL_STEP                 2U

/* TGMP bitrate controller hysteresis. */
#define APP_MEDIA_TGMP_EVENT_MIN_INTERVAL_US            500000ULL
#define APP_MEDIA_TGMP_EVENT_FAST_STEP_BPS              64000U
/* Keep the normal device-call profile at 256 kbit/s. These bounds are dormant
 * while CONFIG_APP_RTC_SDK_VIDEO_ADAPT_ENABLE is disabled. They only define an
 * explicit TGMP experiment and must not silently change the normal product
 * profile. */
#define APP_MEDIA_TGMP_COMPACT_MIN_BITRATE_BPS           (96U * 1000U)
#define APP_MEDIA_TGMP_LARGE_MIN_BITRATE_BPS            (750U * 1000U)
#define APP_MEDIA_TGMP_MIN_RATIO_DIVISOR                4U
#define APP_MEDIA_TGMP_START_RANGE_PERCENT              80U
#define APP_MEDIA_TGMP_MIN_STEP_BPS                     (16U * 1000U)
#define APP_MEDIA_TGMP_MIN_STEP_PERCENT                 10U
#define APP_MEDIA_TGMP_PROTECTION_INTERVAL_MS           1000U
#define APP_MEDIA_TGMP_EMERGENCY_DROP_PERCENT           25U
#define APP_MEDIA_TGMP_RECOVERY_HOLD_MS                 5000U
#define APP_MEDIA_TGMP_RECOVERY_INTERVAL_MS             3000U
#define APP_MEDIA_TGMP_RECOVERY_STEP_PERCENT            15U
#define APP_MEDIA_TGMP_RECOVERY_MIN_STEP_BPS            (64U * 1000U)

/* Focused diagnostics. Keep the initial trace count at zero for normal use. */
#define APP_MEDIA_CAMERA_FRAME_TRACE_INITIAL_COUNT      0U
#define APP_MEDIA_CAMERA_FRAME_TRACE_INTERVAL_MS        10000U

#if APP_MEDIA_CALL_VIDEO_MIN_QP > APP_MEDIA_CALL_VIDEO_MAX_QP
#error "Call video minimum QP must not exceed maximum QP"
#endif

#if APP_MEDIA_CALL_VIDEO_FPS == 0U || APP_MEDIA_CALL_VIDEO_FPS > 15U
#error "Stable call profile must stay within 1-15 fps"
#endif

#if APP_MEDIA_WECHAT_VIDEO_FPS == 0U || APP_MEDIA_WECHAT_VIDEO_FPS > 15U
#error "WeChat video profile must stay within 1-15 fps"
#endif

#if APP_MEDIA_RTC_H264_MIN_QP > APP_MEDIA_RTC_H264_MAX_QP
#error "RTC video minimum QP must not exceed maximum QP"
#endif

#if (APP_MEDIA_CALL_VIDEO_WIDTH % 16U) != 0U || \
    (APP_MEDIA_CALL_VIDEO_HEIGHT % 16U) != 0U
#error "Call video dimensions must be aligned to 16 pixels"
#endif

#if (APP_MEDIA_WECHAT_VIDEO_WIDTH % 16U) != 0U || \
    (APP_MEDIA_WECHAT_VIDEO_HEIGHT % 16U) != 0U
#error "WeChat video dimensions must be aligned to 16 pixels"
#endif

#if APP_MEDIA_TGMP_COMPACT_MIN_BITRATE_BPS > APP_MEDIA_CALL_VIDEO_BITRATE_BPS
#error "TGMP compact floor must not exceed the normal call bitrate"
#endif

#if APP_MEDIA_TGMP_START_RANGE_PERCENT == 0U || \
    APP_MEDIA_TGMP_START_RANGE_PERCENT >= 100U
#error "TGMP start range percentage must stay strictly between 0 and 100"
#endif

#if APP_MEDIA_AUTO_LEVEL1_BITRATE_PERCENT >= 100U || \
    APP_MEDIA_AUTO_LEVEL2_BITRATE_PERCENT >= APP_MEDIA_AUTO_LEVEL1_BITRATE_PERCENT || \
    APP_MEDIA_AUTO_LEVEL3_BITRATE_PERCENT >= APP_MEDIA_AUTO_LEVEL2_BITRATE_PERCENT
#error "Automatic weak-network bitrate levels must decrease monotonically"
#endif

#if APP_MEDIA_AUTO_LEVEL1_FPS_PERCENT >= 100U || \
    APP_MEDIA_AUTO_LEVEL2_FPS_PERCENT >= APP_MEDIA_AUTO_LEVEL1_FPS_PERCENT || \
    APP_MEDIA_AUTO_LEVEL3_FPS_PERCENT >= APP_MEDIA_AUTO_LEVEL2_FPS_PERCENT
#error "Automatic weak-network frame-rate levels must decrease monotonically"
#endif

#if APP_MEDIA_AUTO_SEVERE_LEVEL_STEP == 0U || \
    APP_MEDIA_AUTO_SEVERE_LEVEL_STEP > 3U
#error "Automatic weak-network severe step must stay within 1-3 levels"
#endif
