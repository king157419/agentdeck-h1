#pragma once

/**
 * @file board_config.h
 * Hardware pinout and peripheral definitions for Waveshare ESP32-S3-Touch-LCD-3.49.
 *
 * Official Wiki:
 *   https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.49
 * Official GitHub (V2 / PCB silkscreen Rev1.1, shipped since 2026-06):
 *   https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.49-V2
 * Official GitHub (V1, discontinued):
 *   https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.49
 *
 * NOTE: Hardware interactions are marked [待实测] until verified on a physical board.
 */

#ifndef BOARD_HW_VERSION
#define BOARD_HW_VERSION 2
#endif

#ifndef ENABLE_TOUCH_KEYS
#define ENABLE_TOUCH_KEYS 1
#endif

/* Set to 1 if a panel batch lacks OTP gamma/timing and needs the full register table */
#ifndef AXS15231B_USE_VENDOR_INIT_TABLE
#define AXS15231B_USE_VENDOR_INIT_TABLE 0
#endif

/* Touch coordinate orientation in 640x172 landscape mode (matches Waveshare lvgl_port.c) [待实测] */
#ifndef TOUCH_INVERT_X
#define TOUCH_INVERT_X 1
#endif
#ifndef TOUCH_INVERT_Y
#define TOUCH_INVERT_Y 1
#endif

/* =========================================================================
 * Physical & Logical Display Geometry
 * ========================================================================= */
/* Native AXS15231B QSPI scan geometry is 172 (H) x 640 (V) portrait */
#define LCD_PHYS_W              172
#define LCD_PHYS_H              640

/* Logical UI geometry after 90-degree software transpose into PSRAM */
#define LCD_UI_W                640
#define LCD_UI_H                172

/* Bottom bar height and 6-slot strip height */
#define UI_BOTTOM_BAR_H         36
#define UI_SLOT_AREA_H          (LCD_UI_H - UI_BOTTOM_BAR_H) /* 136 px */

/* QSPI DMA transfer chunk: 64 portrait rows per transaction (172 * 64 * 2 = 22,016 B) */
#define LCD_DMA_LINES           64
#define LCD_DMA_CHUNK_BYTES     (LCD_PHYS_W * LCD_DMA_LINES * 2)
#define LCD_FRAMEBUF_PIXELS     (LCD_UI_W * LCD_UI_H)
#define LCD_FRAMEBUF_BYTES      (LCD_FRAMEBUF_PIXELS * 2)

/* =========================================================================
 * AXS15231B QSPI Display Bus Pins (Common to V1 & V2)
 * ========================================================================= */
#define PIN_LCD_CS              9
#define PIN_LCD_PCLK            10
#define PIN_LCD_D0              11
#define PIN_LCD_D1              12
#define PIN_LCD_D2              13
#define PIN_LCD_D3              14
#define LCD_QSPI_FREQ_HZ        (40 * 1000 * 1000) /* 40 MHz */
#define LCD_QSPI_SPI_MODE       3                  /* Waveshare official spi_mode = 3 */

/* =========================================================================
 * Version-Specific Control Pins (V1 vs V2 / Rev1.1)
 * V2 swapped LCD_TE/LCD_RESET and LCD_BL/EXIO_INT, moving LCD_RST & BL_EN to TCA9554.
 * ========================================================================= */
#if (BOARD_HW_VERSION == 2)
    #define PIN_LCD_TE          21
    #define PIN_LCD_RST         (-1)  /* Driven via TCA9554 EXIO5 */
    #define PIN_LCD_BL          42    /* LEDC PWM + TCA9554 EXIO1 (BL_EN) */
    #define PIN_EXIO_INT        8
#elif (BOARD_HW_VERSION == 1)
    #define PIN_LCD_TE          (-1)
    #define PIN_LCD_RST         21    /* Direct GPIO reset on V1 */
    #define PIN_LCD_BL          8     /* Direct GPIO PWM backlight on V1 */
    #define PIN_EXIO_INT        (-1)
#else
    #error "Unsupported BOARD_HW_VERSION (expected 1 or 2)"
#endif

/* =========================================================================
 * Dual I2C Buses
 * ========================================================================= */
/* Bus 0 (Wire): System I2C — TCA9554 IO expander, PCF85063 RTC (0x51), QMI8658 IMU (0x6B) */
#define PIN_SYS_I2C_SDA         47
#define PIN_SYS_I2C_SCL         48
#define SYS_I2C_FREQ_HZ         400000

/* Bus 1 (Wire1): Dedicated Capacitive Touch I2C — AXS15231B touch controller */
#define PIN_TOUCH_I2C_SDA       17
#define PIN_TOUCH_I2C_SCL       18
#define TOUCH_I2C_FREQ_HZ       300000
#define I2C_ADDR_AXS_TOUCH      0x3B

/* =========================================================================
 * TCA9554 / TCA9554A I2C IO Expander (Address 0x20, fallback 0x38)
 * ========================================================================= */
#define I2C_ADDR_TCA9554        0x20
#define I2C_ADDR_TCA9554A       0x38

#define TCA9554_REG_INPUT       0x00
#define TCA9554_REG_OUTPUT      0x01
#define TCA9554_REG_POLARITY    0x02
#define TCA9554_REG_CONFIG      0x03  /* 1 = input, 0 = output */

#define EXIO_BIT_TOUCH_INT      (1U << 0) /* Input */
#define EXIO_BIT_BL_EN          (1U << 1) /* Output: Backlight enable (V2) */
#define EXIO_BIT_IMU_INT1       (1U << 2) /* Input */
#define EXIO_BIT_IMU_INT2       (1U << 3) /* Input */
#define EXIO_BIT_RTC_INT        (1U << 4) /* Input */
#define EXIO_BIT_LCD_RST        (1U << 5) /* Output: Active-low LCD reset (V2) */
#define EXIO_BIT_SYS_EN         (1U << 6) /* Output: MUST stay HIGH to hold battery power latch! */
#define EXIO_BIT_NS_MODE        (1U << 7) /* Output: Audio PA mode */

/* =========================================================================
 * Onboard Physical Buttons & Battery ADC
 * ========================================================================= */
#define PIN_BTN_BOOT            0     /* Active LOW: mapped to KEY APPROVE */
#define PIN_BTN_PWR             16    /* Active LOW: short press mapped to KEY DENY */
#define PIN_BAT_ADC             4
