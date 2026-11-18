/**
 * @file main.cpp
 * AgentDeck v2 Firmware Draft — Waveshare ESP32-S3-Touch-LCD-3.49
 *
 * Target Hardware:
 *   Waveshare ESP32-S3-Touch-LCD-3.49 (ESP32-S3R8 8MB OPI PSRAM + 16MB QIO Flash)
 *   Display: 3.49" 172x640 IPS, AXS15231B QSPI controller, landscape 640x172 UI
 *   Touch:   AXS15231B I2C capacitive touch (0x3B on GPIO17/18) [待实测]
 *   IO Exp:  TCA9554 (0x20 on GPIO47/48) — holds SYS_EN (EXIO6) + LCD_RST/BL_EN (V2) [待实测]
 *
 * Host Transport:
 *   Native USB CDC Serial (baudrate-independent line protocol, CRLF/LF terminated)
 *
 * Fail-Closed Guarantee (07-技术方案.md §6.3):
 *   Firmware NEVER decides or auto-approves locally; physical/touch inputs only report
 *   KEY events carrying `shown_nonce` back to the host hub.
 */

#include <Arduino.h>
#include <Wire.h>
#include <driver/spi_master.h>
#include <esp_heap_caps.h>
#include <lvgl.h>

#include "board_config.h"
#include "deck_protocol.h"

namespace {

using agentdeck::DeviceModel;
using agentdeck::RiskTier;
using agentdeck::SlotInfo;
using agentdeck::SlotState;

/* =========================================================================
 * Global Hardware & UI State
 * ========================================================================= */
DeviceModel g_model;

spi_device_handle_t g_lcd_spi = nullptr;
bool g_tca_present = false;
uint8_t g_tca_addr = I2C_ADDR_TCA9554;
uint8_t g_tca_out_shadow = 0xFF;
uint8_t g_tca_dir_shadow = 0xFF;
bool g_touch_bus_ready = false;

/* PSRAM & DMA Framebuffers */
static lv_disp_draw_buf_t g_draw_buf;
static lv_disp_drv_t g_disp_drv;
static lv_color_t* g_lv_buf1 = nullptr;   // 640x172 RGB565 in PSRAM (220,160 B)
static lv_color_t* g_lv_buf2 = nullptr;   // Optional 2nd buffer in PSRAM
static uint16_t* g_rot_buf = nullptr;     // 172x640 rotated portrait frame in PSRAM
static uint8_t* g_dma_buf = nullptr;      // Internal SRAM DMA bounce chunk (22,016 B)

/* Serial Line Receiver */
static char g_rx_buf[agentdeck::kSerialLineMax + 1];
static size_t g_rx_len = 0;
static bool g_rx_overflow = false;

/* Animation & Periodic Timers */
static bool g_gate_flash_on = true;
static uint32_t g_last_blink_ms = 0;
static uint32_t g_last_duration_tick_ms = 0;
static bool g_last_offline_state = false;

/* LVGL Widget Handles */
struct SlotWidgets {
    lv_obj_t* card;
    lv_obj_t* idx_lbl;
    lv_obj_t* dur_lbl;
    lv_obj_t* badge;
    lv_obj_t* state_lbl;
    lv_obj_t* name_lbl;
};

static SlotWidgets g_slot_ui[agentdeck::kNumSlots];
static lv_obj_t* g_bottom_bar = nullptr;
static lv_obj_t* g_tier_pill = nullptr;
static lv_obj_t* g_tier_lbl = nullptr;
static lv_obj_t* g_summary_lbl = nullptr;

/* =========================================================================
 * TCA9554 I2C IO Expander Driver (System Bus: GPIO47 SDA, GPIO48 SCL)
 * ========================================================================= */
bool tca9554_write_reg(uint8_t reg, uint8_t val) {
    if (!g_tca_present) return false;
    Wire.beginTransmission(g_tca_addr);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

bool tca9554_probe(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

void tca9554_set_pin_level(uint8_t mask, bool high) {
    if (!g_tca_present) return;
    if (high) {
        g_tca_out_shadow |= mask;
    } else {
        g_tca_out_shadow &= static_cast<uint8_t>(~mask);
    }
    tca9554_write_reg(TCA9554_REG_OUTPUT, g_tca_out_shadow);
}

void system_i2c_and_exio_init() {
    Wire.begin(PIN_SYS_I2C_SDA, PIN_SYS_I2C_SCL, SYS_I2C_FREQ_HZ);
    delay(5);

    if (tca9554_probe(I2C_ADDR_TCA9554)) {
        g_tca_present = true;
        g_tca_addr = I2C_ADDR_TCA9554;
    } else if (tca9554_probe(I2C_ADDR_TCA9554A)) {
        g_tca_present = true;
        g_tca_addr = I2C_ADDR_TCA9554A;
    }

    if (!g_tca_present) {
        return;
    }

    /*
     * CRITICAL BATTERY POWER-LATCH FIX [待实测]:
     * Pre-load OUTPUT register with EXIO6 (SYS_EN) = 1 and EXIO5 (LCD_RST) = 1
     * BEFORE clearing bits in the CONFIG (direction) register. Never write 0xFF
     * reset to CONFIG after SYS_EN is latched, otherwise battery power cuts off.
     */
    g_tca_out_shadow = EXIO_BIT_SYS_EN | EXIO_BIT_LCD_RST;
    tca9554_write_reg(TCA9554_REG_OUTPUT, g_tca_out_shadow);

    // 0 = output (BL_EN, LCD_RST, SYS_EN), 1 = input (TOUCH_INT, IMU_INT, RTC_INT)
    const uint8_t output_pins = EXIO_BIT_BL_EN | EXIO_BIT_LCD_RST | EXIO_BIT_SYS_EN;
    g_tca_dir_shadow = static_cast<uint8_t>(~output_pins);
    tca9554_write_reg(TCA9554_REG_CONFIG, g_tca_dir_shadow);
}

/* =========================================================================
 * Backlight Control (LEDC PWM + V2 EXIO1 BL_EN)
 * ========================================================================= */
static constexpr uint8_t kBlLedcChannel = 0;
static constexpr uint32_t kBlLedcFreqHz = 25000;
static constexpr uint8_t kBlLedcResBits = 8;

void backlight_init_off() {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, LOW);
#if (BOARD_HW_VERSION == 2)
    tca9554_set_pin_level(EXIO_BIT_BL_EN, false);
#endif

#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
    ledcAttach(PIN_LCD_BL, kBlLedcFreqHz, kBlLedcResBits);
    ledcWrite(PIN_LCD_BL, 0);
#else
    ledcSetup(kBlLedcChannel, kBlLedcFreqHz, kBlLedcResBits);
    ledcAttachPin(PIN_LCD_BL, kBlLedcChannel);
    ledcWrite(kBlLedcChannel, 0);
#endif
}

void backlight_set(uint8_t duty) {
#if (BOARD_HW_VERSION == 2)
    tca9554_set_pin_level(EXIO_BIT_BL_EN, duty > 0);
#endif
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
    ledcWrite(PIN_LCD_BL, duty);
#else
    ledcWrite(kBlLedcChannel, duty);
#endif
}

/* =========================================================================
 * AXS15231B QSPI Display Driver (172x640 native -> 640x172 software rotated)
 * Matches Waveshare official esp_lcd_axs15231b.c & lvgl_port.c
 * ========================================================================= */
static constexpr uint8_t kAxsOpcodeWriteCmd   = 0x02;
static constexpr uint8_t kAxsOpcodeWriteColor = 0x32;

struct AxsInitCmd {
    uint8_t cmd;
    const uint8_t* data;
    uint8_t len;
    uint16_t delay_ms;
};

#if AXS15231B_USE_VENDOR_INIT_TABLE
/* Full vendor register init sequence from Waveshare esp_lcd_axs15231b.c (fallback if non-OTP panel) */
static const uint8_t kRegBB_Unlock[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x5A, 0xA5};
static const uint8_t kRegA0[] = {0x00, 0x10, 0x00, 0x02, 0x00, 0x00, 0x64, 0x3F, 0x20, 0x05, 0x3F, 0x3F, 0x00, 0x00, 0x00, 0x00, 0x00};
static const uint8_t kRegA2[] = {0x30, 0x04, 0x0A, 0x3C, 0xEC, 0x54, 0xC4, 0x30, 0xAC, 0x28, 0x7F, 0x7F, 0x7F, 0x20, 0xF8, 0x10, 0x02, 0xFF, 0xFF, 0xF0, 0x90, 0x01, 0x32, 0xA0, 0x91, 0xC0, 0x20, 0x7F, 0xFF, 0x00, 0x54};
static const uint8_t kRegD0[] = {0x30, 0xAC, 0x21, 0x24, 0x08, 0x09, 0x10, 0x01, 0xAA, 0x14, 0xC2, 0x00, 0x22, 0x22, 0xAA, 0x03, 0x10, 0x12, 0x40, 0x14, 0x1E, 0x51, 0x15, 0x00, 0x40, 0x10, 0x00, 0x03, 0x3D, 0x12};
static const uint8_t kRegA3[] = {0xA0, 0x06, 0xAA, 0x08, 0x08, 0x02, 0x0A, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x55, 0x55};
static const uint8_t kRegC1[] = {0x33, 0x04, 0x02, 0x02, 0x71, 0x05, 0x24, 0x55, 0x02, 0x00, 0x41, 0x00, 0x53, 0xFF, 0xFF, 0xFF, 0x4F, 0x52, 0x00, 0x4F, 0x52, 0x00, 0x45, 0x3B, 0x0B, 0x02, 0x0D, 0x00, 0xFF, 0x40};
static const uint8_t kRegC3[] = {0x00, 0x00, 0x00, 0x50, 0x03, 0x00, 0x00, 0x00, 0x01, 0x80, 0x01};
static const uint8_t kRegC4[] = {0x00, 0x24, 0x33, 0x90, 0x50, 0xEA, 0x64, 0x32, 0xC8, 0x64, 0xC8, 0x32, 0x90, 0x90, 0x11, 0x06, 0xDC, 0xFA, 0x04, 0x03, 0x80, 0xFE, 0x10, 0x10, 0x00, 0x0A, 0x0A, 0x44, 0x50};
static const uint8_t kRegC5[] = {0x18, 0x00, 0x00, 0x03, 0xFE, 0x78, 0x33, 0x20, 0x30, 0x10, 0x88, 0xDE, 0x0D, 0x08, 0x0F, 0x0F, 0x01, 0x78, 0x33, 0x20, 0x10, 0x10, 0x80};
static const uint8_t kRegC6[] = {0x05, 0x0A, 0x05, 0x0A, 0x00, 0xE0, 0x2E, 0x0B, 0x12, 0x22, 0x12, 0x22, 0x01, 0x00, 0x00, 0x3F, 0x6A, 0x18, 0xC8, 0x22};
static const uint8_t kRegC7[] = {0x50, 0x32, 0x28, 0x00, 0xA2, 0x80, 0x8F, 0x00, 0x80, 0xFF, 0x07, 0x11, 0x9F, 0x6F, 0xFF, 0x26, 0x0C, 0x0D, 0x0E, 0x0F};
static const uint8_t kRegC9[] = {0x33, 0x44, 0x44, 0x01};
static const uint8_t kRegCF[] = {0x34, 0x1E, 0x88, 0x58, 0x13, 0x18, 0x56, 0x18, 0x1E, 0x68, 0xF7, 0x00, 0x65, 0x0C, 0x22, 0xC4, 0x0C, 0x77, 0x22, 0x44, 0xAA, 0x55, 0x04, 0x04, 0x12, 0xA0, 0x08};
static const uint8_t kRegD5[] = {0x3E, 0x3E, 0x88, 0x00, 0x44, 0x04, 0x78, 0x33, 0x20, 0x78, 0x33, 0x20, 0x04, 0x28, 0xD3, 0x47, 0x03, 0x03, 0x03, 0x03, 0x86, 0x00, 0x00, 0x00, 0x30, 0x52, 0x3F, 0x40, 0x40, 0x96};
static const uint8_t kRegD6[] = {0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE, 0x95, 0x00, 0x01, 0x83, 0x75, 0x36, 0x20, 0x75, 0x36, 0x20, 0x3F, 0x03, 0x03, 0x03, 0x10, 0x10, 0x00, 0x04, 0x51, 0x20, 0x01, 0x00};
static const uint8_t kRegD7[] = {0x0A, 0x08, 0x0E, 0x0C, 0x1E, 0x18, 0x19, 0x1F, 0x00, 0x1F, 0x1A, 0x1F, 0x3E, 0x3E, 0x04, 0x00, 0x1F, 0x1F, 0x1F};
static const uint8_t kRegD8[] = {0x0B, 0x09, 0x0F, 0x0D, 0x1E, 0x18, 0x19, 0x1F, 0x01, 0x1F, 0x1A, 0x1F};
static const uint8_t kRegD9[] = {0x00, 0x0D, 0x0F, 0x09, 0x0B, 0x1F, 0x18, 0x19, 0x1F, 0x01, 0x1E, 0x1A, 0x1F};
static const uint8_t kRegDD[] = {0x0C, 0x0E, 0x08, 0x0A, 0x1F, 0x18, 0x19, 0x1F, 0x00, 0x1E, 0x1A, 0x1F};
static const uint8_t kRegDF[] = {0x44, 0x73, 0x4B, 0x69, 0x00, 0x0A, 0x02, 0x90};
static const uint8_t kRegE0[] = {0x19, 0x20, 0x0A, 0x13, 0x0E, 0x09, 0x12, 0x28, 0xD4, 0x24, 0x0C, 0x35, 0x13, 0x31, 0x36, 0x2F, 0x03};
static const uint8_t kRegE1[] = {0x38, 0x20, 0x09, 0x12, 0x0E, 0x08, 0x12, 0x28, 0xC5, 0x24, 0x0C, 0x34, 0x12, 0x31, 0x36, 0x2F, 0x27};
static const uint8_t kRegE2[] = {0x19, 0x20, 0x0A, 0x11, 0x09, 0x06, 0x11, 0x25, 0xD4, 0x22, 0x0B, 0x33, 0x12, 0x2D, 0x32, 0x2F, 0x03};
static const uint8_t kRegE3[] = {0x38, 0x20, 0x0A, 0x11, 0x09, 0x06, 0x11, 0x25, 0xC4, 0x21, 0x0A, 0x32, 0x11, 0x2C, 0x32, 0x2F, 0x27};
static const uint8_t kRegE4[] = {0x19, 0x20, 0x0D, 0x14, 0x0D, 0x08, 0x12, 0x2A, 0xD4, 0x26, 0x0E, 0x35, 0x13, 0x34, 0x39, 0x2F, 0x03};
static const uint8_t kRegE5[] = {0x38, 0x20, 0x0D, 0x13, 0x0D, 0x07, 0x12, 0x29, 0xC4, 0x25, 0x0D, 0x35, 0x12, 0x33, 0x39, 0x2F, 0x27};
static const uint8_t kRegBB_Lock[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

static const AxsInitCmd kAxsInitSeq[] = {
    {0xBB, kRegBB_Unlock, sizeof(kRegBB_Unlock), 0},
    {0xA0, kRegA0, sizeof(kRegA0), 0},
    {0xA2, kRegA2, sizeof(kRegA2), 0},
    {0xD0, kRegD0, sizeof(kRegD0), 0},
    {0xA3, kRegA3, sizeof(kRegA3), 0},
    {0xC1, kRegC1, sizeof(kRegC1), 0},
    {0xC3, kRegC3, sizeof(kRegC3), 0},
    {0xC4, kRegC4, sizeof(kRegC4), 0},
    {0xC5, kRegC5, sizeof(kRegC5), 0},
    {0xC6, kRegC6, sizeof(kRegC6), 0},
    {0xC7, kRegC7, sizeof(kRegC7), 0},
    {0xC9, kRegC9, sizeof(kRegC9), 0},
    {0xCF, kRegCF, sizeof(kRegCF), 0},
    {0xD5, kRegD5, sizeof(kRegD5), 0},
    {0xD6, kRegD6, sizeof(kRegD6), 0},
    {0xD7, kRegD7, sizeof(kRegD7), 0},
    {0xD8, kRegD8, sizeof(kRegD8), 0},
    {0xD9, kRegD9, sizeof(kRegD9), 0},
    {0xDD, kRegDD, sizeof(kRegDD), 0},
    {0xDF, kRegDF, sizeof(kRegDF), 0},
    {0xE0, kRegE0, sizeof(kRegE0), 0},
    {0xE1, kRegE1, sizeof(kRegE1), 0},
    {0xE2, kRegE2, sizeof(kRegE2), 0},
    {0xE3, kRegE3, sizeof(kRegE3), 0},
    {0xE4, kRegE4, sizeof(kRegE4), 0},
    {0xE5, kRegE5, sizeof(kRegE5), 0},
    {0xBB, kRegBB_Lock, sizeof(kRegBB_Lock), 0},
    {0x13, nullptr, 0, 0},
    {0x11, nullptr, 0, 150},
    {0x29, nullptr, 0, 100},
};
#else
/* Default OTP init sequence used in Waveshare 09_LVGL_V8_Test/lvgl_port.c */
static const AxsInitCmd kAxsInitSeq[] = {
    {0x11, nullptr, 0, 120}, /* SLPOUT */
    {0x29, nullptr, 0, 100}, /* DISPON */
};
#endif

void axs_write_cmd(uint8_t lcd_cmd, const uint8_t* param, size_t param_len) {
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.flags = 0;  // 1-line command + 1-line 24-bit addr + 1-line param
    t.cmd = kAxsOpcodeWriteCmd;
    t.addr = static_cast<uint32_t>(lcd_cmd) << 8;
    t.length = param_len * 8;
    t.tx_buffer = (param_len > 0) ? param : nullptr;
    ESP_ERROR_CHECK(spi_device_polling_transmit(g_lcd_spi, &t));
}

void axs_write_pixels_qio(uint8_t ram_cmd, const void* dma_pixels, size_t byte_len) {
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.flags = SPI_TRANS_MODE_QIO;  // 1-line cmd (0x32) + 1-line addr + 4-line QIO pixels
    t.cmd = kAxsOpcodeWriteColor;
    t.addr = static_cast<uint32_t>(ram_cmd) << 8;
    t.length = byte_len * 8;
    t.tx_buffer = dma_pixels;
    ESP_ERROR_CHECK(spi_device_polling_transmit(g_lcd_spi, &t));
}

void axs_hardware_reset() {
#if (BOARD_HW_VERSION == 2)
    if (g_tca_present) {
        tca9554_set_pin_level(EXIO_BIT_LCD_RST, true);
        delay(30);
        tca9554_set_pin_level(EXIO_BIT_LCD_RST, false);
        delay(250);
        tca9554_set_pin_level(EXIO_BIT_LCD_RST, true);
        delay(50);
    } else {
        axs_write_cmd(0x01 /* SWRESET */, nullptr, 0);
        delay(150);
    }
#else
    pinMode(PIN_LCD_RST, OUTPUT);
    digitalWrite(PIN_LCD_RST, HIGH);
    delay(30);
    digitalWrite(PIN_LCD_RST, LOW);
    delay(200);
    digitalWrite(PIN_LCD_RST, HIGH);
    delay(50);
#endif
}

void axs_display_init() {
    spi_bus_config_t buscfg;
    memset(&buscfg, 0, sizeof(buscfg));
    buscfg.data0_io_num = PIN_LCD_D0;
    buscfg.data1_io_num = PIN_LCD_D1;
    buscfg.sclk_io_num = PIN_LCD_PCLK;
    buscfg.data2_io_num = PIN_LCD_D2;
    buscfg.data3_io_num = PIN_LCD_D3;
    buscfg.data4_io_num = -1;
    buscfg.data5_io_num = -1;
    buscfg.data6_io_num = -1;
    buscfg.data7_io_num = -1;
    buscfg.max_transfer_sz = LCD_DMA_CHUNK_BYTES + 64;
    buscfg.flags = SPICOMMON_BUSFLAG_MASTER | SPICOMMON_BUSFLAG_QUAD;
    ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO));

    spi_device_interface_config_t devcfg;
    memset(&devcfg, 0, sizeof(devcfg));
    devcfg.command_bits = 8;
    devcfg.address_bits = 24;
    devcfg.dummy_bits = 0;
    devcfg.mode = LCD_QSPI_SPI_MODE;
    devcfg.clock_speed_hz = LCD_QSPI_FREQ_HZ;
    devcfg.spics_io_num = PIN_LCD_CS;
    devcfg.flags = SPI_DEVICE_HALFDUPLEX;
    devcfg.queue_size = 4;
    ESP_ERROR_CHECK(spi_bus_add_device(SPI3_HOST, &devcfg, &g_lcd_spi));

    axs_hardware_reset();

    // Base AXS15231B setup matching esp_lcd_axs15231b.c panel_axs15231b_init()
    axs_write_cmd(0x11 /* SLPOUT */, nullptr, 0);
    delay(100);
    const uint8_t madctl_rgb = 0x00;  // Native portrait RGB; landscape is software-transposed
    axs_write_cmd(0x36 /* MADCTL */, &madctl_rgb, 1);
    const uint8_t colmod_rgb565 = 0x55;  // 16-bit RGB565
    axs_write_cmd(0x3A /* COLMOD */, &colmod_rgb565, 1);

    for (size_t i = 0; i < sizeof(kAxsInitSeq) / sizeof(kAxsInitSeq[0]); ++i) {
        axs_write_cmd(kAxsInitSeq[i].cmd, kAxsInitSeq[i].data, kAxsInitSeq[i].len);
        if (kAxsInitSeq[i].delay_ms > 0) {
            delay(kAxsInitSeq[i].delay_ms);
        }
    }
}

/*
 * LVGL Flush Callback:
 * AXS15231B QSPI ignores partial RASET updates and does not support hardware MV=1 90-deg
 * rotation cleanly. Following Waveshare's official lvgl_port.c:
 *   1. LVGL renders full_refresh=1 into a 640x172 buffer in PSRAM.
 *   2. We transpose 640x172 -> 172x640 into g_rot_buf (PSRAM).
 *   3. Stream 10 DMA chunks via CASET (0x2A) + RAMWR (0x2C) / RAMWRC (0x3C) in 4-line QIO.
 */
void lvgl_flush_cb(lv_disp_drv_t* drv, const lv_area_t* /*area*/, lv_color_t* color_map) {
    const uint16_t* src = reinterpret_cast<const uint16_t*>(color_map);
    uint32_t dst_idx = 0;
    for (uint16_t py = 0; py < LCD_PHYS_H; ++py) {
        for (uint16_t px = 0; px < LCD_PHYS_W; ++px) {
            g_rot_buf[dst_idx++] = src[LCD_UI_W * (LCD_UI_H - 1 - px) + py];
        }
    }

    const uint8_t caset[4] = {
        0x00, 0x00,
        static_cast<uint8_t>((LCD_PHYS_W - 1) >> 8),
        static_cast<uint8_t>((LCD_PHYS_W - 1) & 0xFF),
    };

    const uint8_t* ptr = reinterpret_cast<const uint8_t*>(g_rot_buf);
    size_t remaining = LCD_FRAMEBUF_BYTES;
    bool first_chunk = true;

    while (remaining > 0) {
        const size_t chunk = (remaining > LCD_DMA_CHUNK_BYTES) ? LCD_DMA_CHUNK_BYTES : remaining;
        memcpy(g_dma_buf, ptr, chunk);
        axs_write_cmd(0x2A /* CASET */, caset, sizeof(caset));
        axs_write_pixels_qio(first_chunk ? 0x2C /* RAMWR */ : 0x3C /* RAMWRC */, g_dma_buf, chunk);
        first_chunk = false;
        ptr += chunk;
        remaining -= chunk;
    }

    lv_disp_flush_ready(drv);
}

/* =========================================================================
 * LVGL Landscape UI (640x172): 6 Equal Agent Zones + Bottom Approval/Hint Bar
 * ========================================================================= */
struct BadgePalette {
    uint32_t badge_bg;
    uint32_t badge_fg;
    uint32_t card_border;
};

BadgePalette palette_for_state(SlotState st, bool assigned, bool gate_flash_on, bool selected) {
    BadgePalette p = {0x1F2937, 0x6B7280, 0x1F2937};
    switch (st) {
        case SlotState::STATE_RUN:
            p = {0x22C55E, 0x052E16, 0x15803D};  // Green
            break;
        case SlotState::STATE_ASK:
            p = {0xF59E0B, 0x1C1917, 0xD97706};  // Amber
            break;
        case SlotState::STATE_DONE:
            p = {0x3B82F6, 0xFFFFFF, 0x2563EB};  // Blue
            break;
        case SlotState::STATE_ERR:
            p = {0xEF4444, 0xFFFFFF, 0xDC2626};  // Red
            break;
        case SlotState::STATE_GATE:
            if (gate_flash_on) {
                p = {0xEF4444, 0xFFFFFF, 0xF87171};  // Bright red flash ON
            } else {
                p = {0x3B0A0A, 0xFCA5A5, 0x7F1D1D};  // Dark crimson flash OFF
            }
            break;
        case SlotState::STATE_IDLE:
        default:
            if (assigned) {
                p = {0x4B5563, 0xE5E7EB, 0x374151};  // Assigned IDLE gray
            } else {
                p = {0x1E293B, 0x64748B, 0x1E293B};  // Empty slot dim gray
            }
            break;
    }
    if (selected) {
        p.card_border = 0x38BDF8;  // Highlight selected slot with cyan border
    }
    return p;
}

void format_elapsed(uint32_t elapsed_ms, char* buf, size_t len) {
    uint32_t sec = elapsed_ms / 1000;
    if (sec < 60) {
        snprintf(buf, len, "%lus", static_cast<unsigned long>(sec));
    } else if (sec < 3600) {
        snprintf(buf, len, "%lum", static_cast<unsigned long>(sec / 60));
    } else {
        snprintf(buf, len, "%luh", static_cast<unsigned long>(sec / 3600));
    }
}

void ui_build() {
    lv_obj_t* scr = lv_scr_act();
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x090D16), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);

    // 1. Six equal horizontal slot zones across 640 x 136
    for (int i = 0; i < agentdeck::kNumSlots; ++i) {
        const int zone_x0 = (i * LCD_UI_W) / agentdeck::kNumSlots;
        const int zone_x1 = ((i + 1) * LCD_UI_W) / agentdeck::kNumSlots;
        const int card_x = zone_x0 + 2;
        const int card_w = (zone_x1 - zone_x0) - 4;
        const int card_y = 2;
        const int card_h = UI_SLOT_AREA_H - 4;  // 132 px

        lv_obj_t* card = lv_obj_create(scr);
        lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_pos(card, card_x, card_y);
        lv_obj_set_size(card, card_w, card_h);
        lv_obj_set_style_bg_color(card, lv_color_hex(0x111827), 0);
        lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(card, 2, 0);
        lv_obj_set_style_border_color(card, lv_color_hex(0x1E293B), 0);
        lv_obj_set_style_radius(card, 6, 0);
        lv_obj_set_style_pad_all(card, 0, 0);

        // Slot number (#1..#6)
        lv_obj_t* idx_lbl = lv_label_create(card);
        char idx_txt[8];
        snprintf(idx_txt, sizeof(idx_txt), "#%d", i + 1);
        lv_label_set_text(idx_lbl, idx_txt);
        lv_obj_set_style_text_font(idx_lbl, &lv_font_montserrat_12, 0);
        lv_obj_set_style_text_color(idx_lbl, lv_color_hex(0x94A3B8), 0);
        lv_obj_align(idx_lbl, LV_ALIGN_TOP_LEFT, 6, 4);

        // Elapsed duration (top-right)
        lv_obj_t* dur_lbl = lv_label_create(card);
        lv_label_set_text(dur_lbl, "");
        lv_obj_set_style_text_font(dur_lbl, &lv_font_montserrat_12, 0);
        lv_obj_set_style_text_color(dur_lbl, lv_color_hex(0x64748B), 0);
        lv_obj_align(dur_lbl, LV_ALIGN_TOP_RIGHT, -6, 4);

        // Prominent Status Color Block
        lv_obj_t* badge = lv_obj_create(card);
        lv_obj_clear_flag(badge, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_size(badge, card_w - 12, 58);
        lv_obj_align(badge, LV_ALIGN_TOP_MID, 0, 24);
        lv_obj_set_style_radius(badge, 6, 0);
        lv_obj_set_style_border_width(badge, 0, 0);
        lv_obj_set_style_pad_all(badge, 0, 0);
        lv_obj_set_style_bg_opa(badge, LV_OPA_COVER, 0);

        lv_obj_t* state_lbl = lv_label_create(badge);
        lv_label_set_text(state_lbl, "IDLE");
        lv_obj_set_style_text_font(state_lbl, &lv_font_montserrat_16, 0);
        lv_obj_align(state_lbl, LV_ALIGN_CENTER, 0, 0);

        // Agent Name (<= 8 chars, bottom of card)
        lv_obj_t* name_lbl = lv_label_create(card);
        lv_label_set_text(name_lbl, "--");
        lv_label_set_long_mode(name_lbl, LV_LABEL_LONG_CLIP);
        lv_obj_set_width(name_lbl, card_w - 8);
        lv_obj_set_style_text_align(name_lbl, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_font(name_lbl, &lv_font_montserrat_14, 0);
        lv_obj_set_style_text_color(name_lbl, lv_color_hex(0xF8FAFC), 0);
        lv_obj_align(name_lbl, LV_ALIGN_BOTTOM_MID, 0, -10);

        g_slot_ui[i] = {card, idx_lbl, dur_lbl, badge, state_lbl, name_lbl};
    }

    // 2. Bottom Approval & Hint Bar (640 x 36 at y = 136..171)
    g_bottom_bar = lv_obj_create(scr);
    lv_obj_clear_flag(g_bottom_bar, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_pos(g_bottom_bar, 2, UI_SLOT_AREA_H + 1);
    lv_obj_set_size(g_bottom_bar, LCD_UI_W - 4, UI_BOTTOM_BAR_H - 3);
    lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x111827), 0);
    lv_obj_set_style_bg_opa(g_bottom_bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_bottom_bar, 1, 0);
    lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0x1F2937), 0);
    lv_obj_set_style_radius(g_bottom_bar, 5, 0);
    lv_obj_set_style_pad_all(g_bottom_bar, 0, 0);

    g_tier_pill = lv_obj_create(g_bottom_bar);
    lv_obj_clear_flag(g_tier_pill, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(g_tier_pill, 96, 23);
    lv_obj_align(g_tier_pill, LV_ALIGN_LEFT_MID, 5, 0);
    lv_obj_set_style_radius(g_tier_pill, 4, 0);
    lv_obj_set_style_border_width(g_tier_pill, 0, 0);
    lv_obj_set_style_pad_all(g_tier_pill, 0, 0);
    lv_obj_set_style_bg_opa(g_tier_pill, LV_OPA_COVER, 0);

    g_tier_lbl = lv_label_create(g_tier_pill);
    lv_label_set_text(g_tier_lbl, "READY");
    lv_obj_set_style_text_font(g_tier_lbl, &lv_font_montserrat_12, 0);
    lv_obj_align(g_tier_lbl, LV_ALIGN_CENTER, 0, 0);

    g_summary_lbl = lv_label_create(g_bottom_bar);
    lv_label_set_long_mode(g_summary_lbl, LV_LABEL_LONG_DOT);
    lv_obj_set_width(g_summary_lbl, LCD_UI_W - 118);
    lv_obj_set_style_text_font(g_summary_lbl, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0xCBD5E1), 0);
    lv_obj_align(g_summary_lbl, LV_ALIGN_LEFT_MID, 108, 0);
}

void ui_sync(uint32_t now_ms) {
    // 1. Update 6 Slot Cards
    for (int i = 0; i < agentdeck::kNumSlots; ++i) {
        const SlotInfo& info = g_model.slots[i];
        SlotWidgets& w = g_slot_ui[i];
        const bool selected = (g_model.selected_slot == static_cast<uint8_t>(i + 1));
        const BadgePalette pal = palette_for_state(info.state, info.assigned, g_gate_flash_on, selected);

        lv_obj_set_style_border_color(w.card, lv_color_hex(pal.card_border), 0);
        lv_obj_set_style_text_color(
            w.idx_lbl,
            lv_color_hex(selected ? 0x38BDF8 : 0x94A3B8),
            0
        );

        lv_obj_set_style_bg_color(w.badge, lv_color_hex(pal.badge_bg), 0);
        lv_obj_set_style_text_color(w.state_lbl, lv_color_hex(pal.badge_fg), 0);
        lv_label_set_text(w.state_lbl, agentdeck::state_name(info.state));

        lv_label_set_text(w.name_lbl, info.name);
        lv_obj_set_style_text_color(
            w.name_lbl,
            lv_color_hex(info.assigned ? 0xF8FAFC : 0x64748B),
            0
        );

        if (info.assigned && info.state != SlotState::STATE_IDLE) {
            char dur_txt[12];
            format_elapsed(now_ms - info.since_ms, dur_txt, sizeof(dur_txt));
            lv_label_set_text(w.dur_lbl, dur_txt);
        } else {
            lv_label_set_text(w.dur_lbl, "");
        }
    }

    // 2. Update Bottom Prompt / Approval Bar
    char pill_txt[20];
    char line_txt[192];

    if (g_model.approval.active) {
        const uint8_t s = g_model.approval.slot;
        switch (g_model.approval.tier) {
            case RiskTier::TIER_CRITICAL: {
                lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x7F1D1D), 0);
                lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0xF87171), 0);
                lv_obj_set_style_bg_color(g_tier_pill, lv_color_hex(0xDC2626), 0);
                lv_obj_set_style_text_color(g_tier_lbl, lv_color_hex(0xFFFFFF), 0);
                if (s >= 1 && s <= agentdeck::kNumSlots) {
                    snprintf(pill_txt, sizeof(pill_txt), "CRIT #%u", s);
                } else {
                    snprintf(pill_txt, sizeof(pill_txt), "CRITICAL");
                }
                lv_label_set_text(g_tier_lbl, pill_txt);

                lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0xFFFFFF), 0);
                if (g_model.approval.summary[0] != '\0') {
                    snprintf(line_txt, sizeof(line_txt), "LOCKED: use terminal | %s", g_model.approval.summary);
                } else {
                    snprintf(line_txt, sizeof(line_txt), "LOCKED: use terminal");
                }
                lv_label_set_text(g_summary_lbl, line_txt);
                break;
            }
            case RiskTier::TIER_HIGH: {
                lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x450A0A), 0);
                lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0xEF4444), 0);
                lv_obj_set_style_bg_color(g_tier_pill, lv_color_hex(0xDC2626), 0);
                lv_obj_set_style_text_color(g_tier_lbl, lv_color_hex(0xFFFFFF), 0);
                if (s >= 1 && s <= agentdeck::kNumSlots) {
                    snprintf(pill_txt, sizeof(pill_txt), "HIGH #%u", s);
                } else {
                    snprintf(pill_txt, sizeof(pill_txt), "HIGH");
                }
                lv_label_set_text(g_tier_lbl, pill_txt);

                lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0xFEE2E2), 0);
                if (g_model.hint_active && g_model.hint[0] != '\0') {
                    snprintf(line_txt, sizeof(line_txt), "%s | %s", g_model.hint, g_model.approval.summary);
                } else {
                    snprintf(line_txt, sizeof(line_txt), "%s", g_model.approval.summary);
                }
                lv_label_set_text(g_summary_lbl, line_txt);
                break;
            }
            case RiskTier::TIER_LOW:
            default: {
                lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x1E293B), 0);
                lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0xF59E0B), 0);
                lv_obj_set_style_bg_color(g_tier_pill, lv_color_hex(0xD97706), 0);
                lv_obj_set_style_text_color(g_tier_lbl, lv_color_hex(0xFFFFFF), 0);
                if (s >= 1 && s <= agentdeck::kNumSlots) {
                    snprintf(pill_txt, sizeof(pill_txt), "LOW #%u", s);
                } else {
                    snprintf(pill_txt, sizeof(pill_txt), "LOW");
                }
                lv_label_set_text(g_tier_lbl, pill_txt);

                lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0xF8FAFC), 0);
                if (g_model.hint_active && g_model.hint[0] != '\0') {
                    snprintf(line_txt, sizeof(line_txt), "%s | %s", g_model.hint, g_model.approval.summary);
                } else {
                    snprintf(line_txt, sizeof(line_txt), "%s", g_model.approval.summary);
                }
                lv_label_set_text(g_summary_lbl, line_txt);
                break;
            }
        }
    } else if (g_model.hint_active && g_model.hint[0] != '\0') {
        lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x0F172A), 0);
        lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0x38BDF8), 0);
        lv_obj_set_style_bg_color(g_tier_pill, lv_color_hex(0x0284C7), 0);
        lv_obj_set_style_text_color(g_tier_lbl, lv_color_hex(0xFFFFFF), 0);
        lv_label_set_text(g_tier_lbl, "HINT");
        lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0xE0F2FE), 0);
        lv_label_set_text(g_summary_lbl, g_model.hint);
    } else if (g_model.is_hub_offline(now_ms)) {
        lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x450A0A), 0);
        lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0xEF4444), 0);
        lv_obj_set_style_bg_color(g_tier_pill, lv_color_hex(0xDC2626), 0);
        lv_obj_set_style_text_color(g_tier_lbl, lv_color_hex(0xFFFFFF), 0);
        lv_label_set_text(g_tier_lbl, "OFFLINE");
        lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0xFCA5A5), 0);
        lv_label_set_text(g_summary_lbl, "Hub heartbeat lost (>3s) - check desktop hub");
    } else {
        lv_obj_set_style_bg_color(g_bottom_bar, lv_color_hex(0x111827), 0);
        lv_obj_set_style_border_color(g_bottom_bar, lv_color_hex(0x1F2937), 0);
        lv_obj_set_style_bg_color(g_tier_pill, lv_color_hex(0x334155), 0);
        lv_obj_set_style_text_color(g_tier_lbl, lv_color_hex(0xCBD5E1), 0);
        lv_label_set_text(g_tier_lbl, "READY");
        lv_obj_set_style_text_color(g_summary_lbl, lv_color_hex(0x94A3B8), 0);
        lv_label_set_text(g_summary_lbl, "AgentDeck v2 | USB CDC Ready | Tap slot 1-6");
    }

    g_model.ui_dirty = false;
}

/* =========================================================================
 * Touch 6-Zone Mapper & Onboard Buttons -> Serial KEY Events [待实测]
 * ========================================================================= */
void send_key_event(const char* kind, int slot_or_zero, bool is_down, uint32_t now_ms) {
    char line[128];
    agentdeck::format_key_event(g_model, kind, slot_or_zero, is_down, now_ms, line, sizeof(line));
    Serial.println(line);
}

#if ENABLE_TOUCH_KEYS
static int g_pressed_touch_slot = 0;
static uint32_t g_last_touch_poll_ms = 0;

void touch_bus_init() {
    // Initialize Touch I2C (Wire1) AFTER AXS15231B LCD reset completes
    Wire1.begin(PIN_TOUCH_I2C_SDA, PIN_TOUCH_I2C_SCL, TOUCH_I2C_FREQ_HZ);
    Wire1.setTimeOut(15);
    g_touch_bus_ready = true;
}

/*
 * Poll AXS15231B capacitive touch controller at 0x3B using Waveshare's 11-byte command:
 *   cmd = {0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00}
 * TODO [待实测]: Confirm X/Y axis inversion (TOUCH_INVERT_X / TOUCH_INVERT_Y) on physical board
 *               to ensure left-to-right slots 1..6 match the landscape display orientation.
 */
void poll_touch_slots(uint32_t now_ms) {
    if (!g_touch_bus_ready || (now_ms - g_last_touch_poll_ms) < 20) {
        return;
    }
    g_last_touch_poll_ms = now_ms;

    static const uint8_t kTouchReadCmd[11] = {
        0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00
    };
    Wire1.beginTransmission(I2C_ADDR_AXS_TOUCH);
    Wire1.write(kTouchReadCmd, sizeof(kTouchReadCmd));
    if (Wire1.endTransmission() != 0) {
        return;
    }

    uint8_t buf[8] = {0};
    if (Wire1.requestFrom(static_cast<uint8_t>(I2C_ADDR_AXS_TOUCH), static_cast<uint8_t>(sizeof(buf))) != sizeof(buf)) {
        return;
    }
    for (size_t i = 0; i < sizeof(buf); ++i) {
        buf[i] = static_cast<uint8_t>(Wire1.read());
    }

    const uint8_t point_cnt = buf[1];
    int current_slot = 0;

    if (point_cnt > 0 && point_cnt < 5) {
        uint16_t raw_x = static_cast<uint16_t>(((buf[2] & 0x0F) << 8) | buf[3]);
        uint16_t raw_y = static_cast<uint16_t>(((buf[4] & 0x0F) << 8) | buf[5]);
        if (raw_x > LCD_UI_W) raw_x = LCD_UI_W;
        if (raw_y > LCD_UI_H) raw_y = LCD_UI_H;

        uint16_t lx = TOUCH_INVERT_X ? (LCD_UI_W - raw_x) : raw_x;
        uint16_t ly = TOUCH_INVERT_Y ? (LCD_UI_H - raw_y) : raw_y;
        if (lx >= LCD_UI_W) lx = LCD_UI_W - 1;
        if (ly >= LCD_UI_H) ly = LCD_UI_H - 1;

        current_slot = agentdeck::touch_point_to_slot(lx, ly, LCD_UI_W, UI_SLOT_AREA_H);
    }

    if (current_slot != g_pressed_touch_slot) {
        if (g_pressed_touch_slot >= 1 && g_pressed_touch_slot <= agentdeck::kNumSlots) {
            send_key_event("SLOT", g_pressed_touch_slot, false, now_ms);
        }
        g_pressed_touch_slot = current_slot;
        if (current_slot >= 1 && current_slot <= agentdeck::kNumSlots) {
            g_model.selected_slot = static_cast<uint8_t>(current_slot);
            g_model.ui_dirty = true;
            send_key_event("SLOT", current_slot, true, now_ms);
        }
    }
}
#endif  // ENABLE_TOUCH_KEYS

struct DebouncedPinButton {
    int pin;
    const char* key_name;
    bool pressed;
    bool raw_last;
    uint32_t last_change_ms;
};

static DebouncedPinButton g_hw_buttons[] = {
    {PIN_BTN_BOOT, "APPROVE", false, false, 0},
    {PIN_BTN_PWR,  "DENY",    false, false, 0},
};

void buttons_init() {
    for (auto& b : g_hw_buttons) {
        pinMode(b.pin, INPUT_PULLUP);
    }
}

void poll_hw_buttons(uint32_t now_ms) {
    for (auto& b : g_hw_buttons) {
        const bool raw_pressed = (digitalRead(b.pin) == LOW);
        if (raw_pressed != b.raw_last) {
            b.raw_last = raw_pressed;
            b.last_change_ms = now_ms;
        }
        if ((now_ms - b.last_change_ms) >= 25 && raw_pressed != b.pressed) {
            b.pressed = raw_pressed;
            send_key_event(b.key_name, 0, b.pressed, now_ms);
        }
    }
}

/* =========================================================================
 * Non-Blocking USB CDC Serial Line Receiver
 * ========================================================================= */
void poll_serial(uint32_t now_ms) {
    while (Serial.available() > 0) {
        const int ch = Serial.read();
        if (ch < 0) break;

        if (ch == '\n' || ch == '\r') {
            if (g_rx_overflow) {
                if (ch == '\n') {
                    g_rx_overflow = false;
                    g_rx_len = 0;
                    Serial.println("ERR LINE_TOO_LONG");
                }
                continue;
            }
            if (g_rx_len == 0) {
                continue;  // Ignore empty CR/LF pairs
            }
            g_rx_buf[g_rx_len] = '\0';
            g_rx_len = 0;

            char reply[256];
            if (agentdeck::process_command_line(g_model, g_rx_buf, now_ms, reply, sizeof(reply))) {
                Serial.println(reply);
            }
        } else {
            if (g_rx_overflow) {
                continue;
            }
            if (g_rx_len < agentdeck::kSerialLineMax) {
                g_rx_buf[g_rx_len++] = static_cast<char>(ch);
            } else {
                g_rx_overflow = true;
            }
        }
    }
}

bool any_slot_in_gate() {
    for (int i = 0; i < agentdeck::kNumSlots; ++i) {
        if (g_model.slots[i].state == SlotState::STATE_GATE) {
            return true;
        }
    }
    return false;
}

bool any_slot_showing_duration() {
    for (int i = 0; i < agentdeck::kNumSlots; ++i) {
        if (g_model.slots[i].assigned && g_model.slots[i].state != SlotState::STATE_IDLE) {
            return true;
        }
    }
    return false;
}

}  // namespace

/* =========================================================================
 * Arduino Entry Points
 * ========================================================================= */
void setup() {
    // USB CDC ignores baudrate on ESP32-S3 native USB; 115200 kept for API convention
    Serial.begin(115200);

    backlight_init_off();
    system_i2c_and_exio_init();
    buttons_init();

    // Allocate full-screen LVGL + transpose buffers in 8 MB OPI PSRAM, DMA chunk in internal SRAM
    g_lv_buf1 = static_cast<lv_color_t*>(heap_caps_malloc(LCD_FRAMEBUF_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    g_lv_buf2 = static_cast<lv_color_t*>(heap_caps_malloc(LCD_FRAMEBUF_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    g_rot_buf = static_cast<uint16_t*>(heap_caps_malloc(LCD_FRAMEBUF_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    g_dma_buf = static_cast<uint8_t*>(heap_caps_malloc(LCD_DMA_CHUNK_BYTES, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));

    if (!g_lv_buf1 || !g_rot_buf || !g_dma_buf) {
        // Halt safely with diagnostic message on USB CDC if OPI PSRAM is misconfigured
        while (true) {
            Serial.println("ERR BOOT_MEM PSRAM/DMA alloc failed (check qio_opi in platformio.ini)");
            delay(1000);
        }
    }

    axs_display_init();

#if ENABLE_TOUCH_KEYS
    touch_bus_init();
#endif

    lv_init();
    lv_disp_draw_buf_init(&g_draw_buf, g_lv_buf1, g_lv_buf2, LCD_FRAMEBUF_PIXELS);

    lv_disp_drv_init(&g_disp_drv);
    g_disp_drv.hor_res = LCD_UI_W;
    g_disp_drv.ver_res = LCD_UI_H;
    g_disp_drv.flush_cb = lvgl_flush_cb;
    g_disp_drv.draw_buf = &g_draw_buf;
    g_disp_drv.full_refresh = 1;  // Required for AXS15231B QSPI 0x2C/0x3C streaming
    lv_disp_drv_register(&g_disp_drv);

    const uint32_t now_ms = millis();
    g_model.reset(now_ms);
    ui_build();
    ui_sync(now_ms);
    lv_timer_handler();  // Push initial dark frame before turning on backlight

    backlight_set(g_model.brightness);
}

void loop() {
    const uint32_t now_ms = millis();

    poll_serial(now_ms);

#if ENABLE_TOUCH_KEYS
    poll_touch_slots(now_ms);
#endif
    poll_hw_buttons(now_ms);

    if (g_model.brightness_dirty) {
        g_model.brightness_dirty = false;
        backlight_set(g_model.brightness);
    }

    // Local 2 Hz (250 ms half-period) red flash for GATE slots
    if ((now_ms - g_last_blink_ms) >= 250) {
        g_last_blink_ms = now_ms;
        g_gate_flash_on = !g_gate_flash_on;
        if (any_slot_in_gate()) {
            g_model.ui_dirty = true;
        }
    }

    // Refresh elapsed duration labels once per second
    if ((now_ms - g_last_duration_tick_ms) >= 1000) {
        g_last_duration_tick_ms = now_ms;
        if (any_slot_showing_duration()) {
            g_model.ui_dirty = true;
        }
    }

    // Detect Hub heartbeat timeout transition (> 3000 ms)
    const bool offline_now = g_model.is_hub_offline(now_ms);
    if (offline_now != g_last_offline_state) {
        g_last_offline_state = offline_now;
        g_model.ui_dirty = true;
    }

    if (g_model.ui_dirty) {
        ui_sync(now_ms);
    }

    lv_timer_handler();
    delay(2);
}
