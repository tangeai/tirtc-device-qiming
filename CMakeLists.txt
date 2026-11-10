cmake_minimum_required(VERSION 3.16)

# Dependencies are pinned. The optional update probe in Component Manager 2.4.9
# misreads LVGL 8 optional Kconfig symbols on a normal Windows reconfigure.
# Keep dependency resolution enabled; skip only that probe for this project.
if(NOT DEFINED ENV{IDF_COMPONENT_CHECK_NEW_VERSION})
    set(ENV{IDF_COMPONENT_CHECK_NEW_VERSION} "0")
endif()

set(PROJECT_VER "0.1.0-dev")
# The imported Waveshare BSP is retained only as source provenance.
set(EXCLUDE_COMPONENTS esp32_p4_wifi6_touch_lcd_35)
# This Kconfig is loaded through starter_voice's rsource. Track it explicitly
# so incremental Ninja builds regenerate sdkconfig.h when its options change.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.xiaotai")
# Wi-Fi Remote 0.14 includes Kconfig by this major.minor environment value.
# Derive it from the selected IDF even on Ninja/CMake-triggered reconfigure;
# a missing value silently drops C6/SDIO symbols before Hosted compilation.
include($ENV{IDF_PATH}/tools/cmake/version.cmake)
if(NOT IDF_VERSION_MAJOR EQUAL 5 OR NOT IDF_VERSION_MINOR EQUAL 5 OR
   NOT IDF_VERSION_PATCH EQUAL 5)
    message(FATAL_ERROR "This P4 component set requires ESP-IDF 5.5.5")
endif()
set(ENV{ESP_IDF_VERSION} "${IDF_VERSION_MAJOR}.${IDF_VERSION_MINOR}")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# IDF serializes local overrides as absolute paths. Keep that generated lock in
# build/, while the reviewed dependency versions and hashes stay portable in Git.
include(${CMAKE_CURRENT_LIST_DIR}/tools/dependency_lock.cmake)
xiaotai_prepare_dependency_lock("${CMAKE_CURRENT_LIST_DIR}" "${CMAKE_BINARY_DIR}")
idf_build_set_property(DEPENDENCIES_LOCK "${CMAKE_BINARY_DIR}/dependencies.lock")
project(xiaotai_wt99p461_s1)

# Component Manager supplies the pinned 3.0.7 archive. Retain the reviewed
# RPC extension/RX stack patch; the Waveshare SDIO DMA patch is not used by SPI.
find_package(Git REQUIRED)
set(_hosted_dir "${CMAKE_CURRENT_LIST_DIR}/managed_components/espressif__esp_hosted")
# Treat component paths as patch roots, not paths in an enclosing checkout.
# Otherwise git apply can skip every file and still return success.
set(_hosted_git_apply "${CMAKE_COMMAND}" -E env
    --unset=GIT_DIR --unset=GIT_WORK_TREE --unset=GIT_INDEX_FILE
    "GIT_CEILING_DIRECTORIES=${CMAKE_CURRENT_LIST_DIR}/managed_components"
    "${GIT_EXECUTABLE}" apply)
set(_hosted_patches
    "${CMAKE_CURRENT_LIST_DIR}/tools/patches/esp-hosted-3.0.7-app-desc.patch"
    "${CMAKE_CURRENT_LIST_DIR}/tools/patches/esp-hosted-3.0.7-spi-diagnostics.patch")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_hosted_patches})
if(NOT EXISTS "${_hosted_dir}/host/features/eh_host_feat_system/src/eh_host_sys.c")
    message(FATAL_ERROR "ESP-Hosted 3.0.7 component is missing")
endif()
foreach(_hosted_patch IN LISTS _hosted_patches)
    execute_process(COMMAND ${_hosted_git_apply} --reverse --check --ignore-space-change "${_hosted_patch}"
        WORKING_DIRECTORY "${_hosted_dir}" RESULT_VARIABLE _hosted_patch_applied
        OUTPUT_QUIET ERROR_QUIET)
    if(NOT _hosted_patch_applied EQUAL 0)
        execute_process(COMMAND ${_hosted_git_apply} --check --ignore-space-change "${_hosted_patch}"
            WORKING_DIRECTORY "${_hosted_dir}" RESULT_VARIABLE _hosted_patch_clean
            OUTPUT_QUIET ERROR_VARIABLE _hosted_patch_error)
        if(NOT _hosted_patch_clean EQUAL 0)
            message(FATAL_ERROR "ESP-Hosted patch ${_hosted_patch} does not match pinned 3.0.7: ${_hosted_patch_error}")
        endif()
        execute_process(COMMAND ${_hosted_git_apply} --ignore-space-change "${_hosted_patch}"
            WORKING_DIRECTORY "${_hosted_dir}" RESULT_VARIABLE _hosted_patch_result)
        if(NOT _hosted_patch_result EQUAL 0)
            message(FATAL_ERROR "Could not apply ESP-Hosted patch ${_hosted_patch}")
        endif()
    endif()
endforeach()

# LVGL 8.4 misreads the cover-check payload and inherits a transparent image
# widget's background result even when its native RGB pixels are opaque.
set(_lvgl_dir "${CMAKE_CURRENT_LIST_DIR}/managed_components/lvgl__lvgl")
set(_lvgl_patch "${CMAKE_CURRENT_LIST_DIR}/tools/patches/lvgl-8.4.0-image-cover.patch")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_lvgl_patch}")
execute_process(COMMAND ${_hosted_git_apply} --reverse --check --ignore-space-change "${_lvgl_patch}"
    WORKING_DIRECTORY "${_lvgl_dir}" RESULT_VARIABLE _lvgl_patch_applied
    OUTPUT_QUIET ERROR_QUIET)
if(NOT _lvgl_patch_applied EQUAL 0)
    execute_process(COMMAND ${_hosted_git_apply} --check --ignore-space-change "${_lvgl_patch}"
        WORKING_DIRECTORY "${_lvgl_dir}" RESULT_VARIABLE _lvgl_patch_clean
        OUTPUT_QUIET ERROR_VARIABLE _lvgl_patch_error)
    if(NOT _lvgl_patch_clean EQUAL 0)
        message(FATAL_ERROR "LVGL image-cover patch does not match pinned 8.4.0: ${_lvgl_patch_error}")
    endif()
    execute_process(COMMAND ${_hosted_git_apply} --ignore-space-change "${_lvgl_patch}"
        WORKING_DIRECTORY "${_lvgl_dir}" RESULT_VARIABLE _lvgl_patch_result)
    if(NOT _lvgl_patch_result EQUAL 0)
        message(FATAL_ERROR "Could not apply LVGL image-cover patch")
    endif()
endif()

# This branch produces firmware for v3.x silicon only. Never reuse a cached
# rev1 sdkconfig or flash its output to a rev1 board.
if(CONFIG_ESP32P4_SELECTS_REV_LESS_V3 OR
   NOT CONFIG_ESP32P4_REV_MIN_FULL EQUAL 301 OR
   NOT CONFIG_ESP32P4_REV_MAX_FULL EQUAL 399 OR
   NOT CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ EQUAL 400 OR
   CONFIG_HAL_WDT_USE_ROM_IMPL)
    message(FATAL_ERROR
        "P4 rev3.2 validation requires rev3.1-3.99, 400 MHz and non-ROM WDT. "
        "Current sdkconfig: min=${CONFIG_ESP32P4_REV_MIN_FULL}, "
        "max=${CONFIG_ESP32P4_REV_MAX_FULL}, "
        "cpu=${CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ}, "
        "rom_wdt=${CONFIG_HAL_WDT_USE_ROM_IMPL}. "
        "A previous branch's ignored sdkconfig/build cache cannot be reused; "
        "preserve it separately and regenerate this branch's configuration.")
endif()

include(${CMAKE_CURRENT_LIST_DIR}/tools/check_board_config.cmake)

add_custom_command(TARGET ${CMAKE_PROJECT_NAME}.elf POST_BUILD
 COMMAND ${CMAKE_COMMAND}
         -DCROSS_NM=${CMAKE_NM}
         -DELF=$<TARGET_FILE:${CMAKE_PROJECT_NAME}.elf>
         -DMAP=${CMAKE_BINARY_DIR}/${CMAKE_PROJECT_NAME}.map
         -DCONFIG=${CMAKE_BINARY_DIR}/config/sdkconfig.json
         -P ${CMAKE_CURRENT_LIST_DIR}/tools/check_firmware.cmake
 VERBATIM)
set_property(TARGET ${CMAKE_PROJECT_NAME}.elf APPEND PROPERTY LINK_DEPENDS
    "${CMAKE_CURRENT_LIST_DIR}/tools/check_firmware.cmake")
