#pragma once

#include <stddef.h>

#include "esp_err.h"

esp_err_t hosted_coprocessor_ota_diag_start(const char *url);
esp_err_t hosted_coprocessor_ota_diag_recover_partition(size_t image_size);
