cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Wi-Fi Remote uses this export to load its IDF-specific Kconfig symbols.
if(NOT "$ENV{ESP_IDF_VERSION}" STREQUAL "${IDF_VERSION_MAJOR}.${IDF_VERSION_MINOR}")
    message(FATAL_ERROR
        "Activate the selected ESP-IDF environment with export.ps1/export.sh before configuring. "
        "ESP_IDF_VERSION must match ${IDF_VERSION_MAJOR}.${IDF_VERSION_MINOR}; "
        "otherwise Wi-Fi Remote cannot load the C61 configuration.")
endif()

set(PROJECT_VER "1.0.1")
project(tirtc_esp32p4_wt9932p4c61_tiny_device_app)

if(NOT CONFIG_IDF_TARGET_ESP32P4 OR
   NOT CONFIG_SLAVE_IDF_TARGET_ESP32C61 OR
   NOT CONFIG_ESP_HOSTED_CP_TARGET_ESP32C61 OR
   NOT CONFIG_ESP_HOSTED_SDIO_HOST_INTERFACE)
    message(FATAL_ERROR
        "WT9932P4C61-TINY requires an ESP32-P4 host and ESP32-C61 over SDIO. "
        "Check sdkconfig against this board's sdkconfig.defaults before building.")
endif()
