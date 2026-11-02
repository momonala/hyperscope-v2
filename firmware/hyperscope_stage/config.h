// Hardware configuration for the hyperscope XY stage controller.
// ESP32-WROOM-32 DevKit driving BIGTREETECH TMC2209 modules in UART mode.
// Mirrors docs/hardware.md.
#pragma once

// MVPower NEMA 17 rated 1.5 A peak (~1060 mA RMS). The fanless BTT TMC2209
// modules are comfortable to ~1.2 A RMS.
constexpr uint16_t MOTOR_RMS_CURRENT_X_MA = 800;
constexpr uint16_t MOTOR_RMS_CURRENT_Y_MA = 800;

// +X is right, +Y is up.
constexpr bool DIR_INVERT_X = true;
constexpr bool DIR_INVERT_Y = false;

constexpr float MOTOR_HOLD_FRACTION = 0.25f;  // standstill current as a fraction of run current
// StealthChop PWM frequency code: 0 = 23 kHz, 1 = 35 kHz, 2 = 47 kHz, 3 = 59 kHz.
constexpr uint8_t STEALTHCHOP_PWM_FREQ = 2;
constexpr uint16_t MICROSTEPS = 16;  // 3200 microsteps per knob revolution
constexpr float TMC_R_SENSE = 0.11f;

// Carrier PCB rev C pin map (hardware/pcb/generate.py is the source of truth).
// Axis names follow the stage, not the PCB silkscreen: the board's "Y" socket drives
// X (left/right) and its "X" socket drives Y (up/down). GPIO 5 is a strapping pin,
// sampled only at reset.
constexpr uint8_t PIN_X_STEP = 19;
constexpr uint8_t PIN_X_DIR = 21;
constexpr uint8_t PIN_Y_STEP = 5;
constexpr uint8_t PIN_Y_DIR = 18;
constexpr uint8_t PIN_EN = 4;  // shared by both drivers, active low

// Each driver's DIAG pin, through 1 kOhm and a select jumper. Not read: stalls are
// polled over the UART.
constexpr uint8_t PIN_X_DIAG = 22;
constexpr uint8_t PIN_Y_DIAG = 13;

// Blue "motor active" LEDs beside each motor terminal (PCB rev C), through 100 Ohm.
constexpr uint8_t PIN_X_LED = 23;
constexpr uint8_t PIN_Y_LED = 32;

constexpr uint8_t PIN_TMC_RX = 17;
constexpr uint8_t PIN_TMC_TX = 16;   // through 1 kOhm onto the shared PDN_UART line
constexpr uint8_t TMC_ADDR_X = 0b10;  // board "Y" socket: MS1 jumpered to GND, MS2 to VIO
constexpr uint8_t TMC_ADDR_Y = 0b11;  // board "X" socket: MS1 and MS2 jumpered to VIO
constexpr uint32_t TMC_BAUD = 115200;

// Joystick, powered from 3V3 and never 5 V because these are ADC inputs.
// PIN_JOY_X is whichever input drives the X motor, which need not be the pin the
// module labels VRX once it is mounted.
constexpr uint8_t PIN_JOY_X = 35;
constexpr uint8_t PIN_JOY_Y = 34;
constexpr uint8_t PIN_JOY_SW = 33;  // to GND when pressed, internal pull-up
constexpr int JOY_ADC_MAX = 4095;
constexpr int JOY_DEADZONE = 120;
constexpr int JOY_CURVE_EXPONENT = 3;        // higher spends more of the throw at low speed
constexpr int JOY_CALIBRATION_SAMPLES = 64;  // these sticks do not rest at mid-scale
constexpr bool JOY_INVERT_X = false;
constexpr bool JOY_INVERT_Y = false;

constexpr bool ENABLE_DRIVERS_AT_BOOT = false;
constexpr bool JOYSTICK_ENABLED_AT_BOOT = false;  // an unconnected stick reads noise and jogs the stage
constexpr bool LIMITS_ENABLED_AT_BOOT = false;
// Energising the motors within a few ms of writing the driver registers resets
// both chips to their pin defaults.
constexpr uint32_t DRIVER_ENABLE_SETTLE_MS = 100;
constexpr uint32_t DRIVER_CHECK_INTERVAL_MS = 1000;

// Motion, in microsteps/s and microsteps/s^2.
constexpr uint32_t DEFAULT_SPEED_HZ = 2700;
constexpr uint32_t DEFAULT_ACCEL = 8000;
constexpr uint32_t JOG_SPEED_COARSE_HZ = 4000;
constexpr uint32_t JOG_SPEED_FINE_HZ = 400;
constexpr uint32_t JOG_ACCEL = 8000;

// Soft limits in microsteps either side of zero, until MIN/MAX override them.
constexpr long SOFT_LIMIT_DEFAULT = 3200;

// StallGuard homing.
constexpr uint8_t STALL_THRESHOLD_DEFAULT = 20;
constexpr uint32_t STALL_IGNORE_MS = 300;  // the acceleration ramp reads as load
constexpr uint32_t STALL_POLL_MS = 5;
constexpr long HOME_MAX_STEPS_X = 12800;
constexpr long HOME_MAX_STEPS_Y = 12800;
constexpr long HOME_BACKOFF_STEPS = 800;
constexpr uint32_t SGTEST_DURATION_MS = 1500;

constexpr uint32_t HOST_BAUD = 115200;
constexpr uint16_t SERIAL_LINE_MAX = 120;

constexpr uint32_t JOY_POLL_INTERVAL_MS = 20;
constexpr uint32_t JOY_BUTTON_DEBOUNCE_MS = 200;
