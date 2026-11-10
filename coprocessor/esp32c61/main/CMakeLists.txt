idf_component_register(SRCS "main.c" "c61_diagnostics.c" INCLUDE_DIRS "."
 PRIV_REQUIRES nvs_flash esp_event espressif__esp_hosted esp_wifi app_update esp_timer)
if(CONFIG_ESP_HOSTED_CP_FEAT_NW_SPLIT)
    message(FATAL_ERROR "The C61 RX observation hook requires the standard Wi-Fi RX owner")
endif()
target_link_libraries(${COMPONENT_LIB} INTERFACE "-Wl,--wrap=esp_wifi_internal_reg_rxcb")
if(CONFIG_WT_C61_ALLOC_TRACE)
    target_sources(${COMPONENT_LIB} PRIVATE "c61_alloc_trace.c")
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-Wl,--wrap=malloc" "-Wl,--wrap=calloc"
        "-Wl,--wrap=realloc" "-Wl,--wrap=heap_caps_malloc"
        "-Wl,--wrap=esp_wifi_internal_free_rx_buffer")
endif()
