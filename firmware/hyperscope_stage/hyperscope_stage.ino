/*
 * hyperscope XY stage controller.
 *
 * Two NEMA 17 steppers on TMC2209 drivers turn the microscope's stage knobs,
 * commanded over USB serial or jogged with an analog joystick. Wiring, pin map
 * and the serial protocol are in docs/hardware.md.
 */

#include <Arduino.h>
#include <FastAccelStepper.h>
#include <TMCStepper.h>

#include "config.h"

struct Axis {
  const char* name;
  uint8_t stepPin;
  uint8_t dirPin;
  uint8_t ledPin;
  uint8_t joyPin;
  bool joyInvert;
  TMC2209Stepper driver;
  FastAccelStepper* stepper = nullptr;
  bool present = false;
  int joyCentre = JOY_ADC_MAX / 2;
};

constexpr size_t AXIS_COUNT = 2;
Axis axes[AXIS_COUNT] = {
    {"X", PIN_X_STEP, PIN_X_DIR, PIN_X_LED, PIN_JOY_X, JOY_INVERT_X, TMC2209Stepper(&Serial2, TMC_R_SENSE, TMC_ADDR_X)},
    {"Y", PIN_Y_STEP, PIN_Y_DIR, PIN_Y_LED, PIN_JOY_Y, JOY_INVERT_Y, TMC2209Stepper(&Serial2, TMC_R_SENSE, TMC_ADDR_Y)},
};

FastAccelStepperEngine engine;
bool driversEnabled = false;
bool joystickEnabled = true;
bool jogFine = false;
uint32_t speedHz = DEFAULT_SPEED_HZ;
uint32_t accel = DEFAULT_ACCEL;
String lineBuffer;

// A parsed "X<n> Y<n>" argument list, indexed like `axes`.
struct AxisTargets {
  bool has[AXIS_COUNT] = {};
  long value[AXIS_COUNT] = {};
};

Axis* findAxis(const String& name) {
  for (Axis& axis : axes) {
    if (name.equalsIgnoreCase(axis.name)) return &axis;
  }
  return nullptr;
}

// --- Drivers -------------------------------------------------------------------

void setDriversEnabled(bool on) {
  digitalWrite(PIN_EN, on ? LOW : HIGH);
  driversEnabled = on;
}

void configureDriver(Axis& axis) {
  TMC2209Stepper& driver = axis.driver;
  driver.begin();
  driver.pdn_disable(true);       // the UART owns the driver, not the PDN pin
  driver.I_scale_analog(false);   // current from the register, not the Vref pot
  driver.mstep_reg_select(true);  // microsteps from the register, MS pins are the address
  driver.toff(5);
  driver.blank_time(24);
  driver.rms_current(MOTOR_RMS_CURRENT_MA, MOTOR_HOLD_FRACTION);
  driver.microsteps(MICROSTEPS);
  driver.en_spreadCycle(false);  // StealthChop: silent, and a knob needs little torque
  driver.pwm_autoscale(true);
  driver.pwm_autograd(true);
  driver.pwm_freq(STEALTHCHOP_PWM_FREQ);
  driver.iholddelay(10);
  driver.TPOWERDOWN(20);

  axis.present = driver.test_connection() == 0;
  if (!axis.present) {
    Serial.printf("# %s driver not responding, that axis is unavailable\n", axis.name);
    return;
  }
  Serial.printf("# %s driver ok, version 0x%02X, %u mA, %u microsteps\n", axis.name, driver.version(),
                driver.rms_current(), driver.microsteps());
}

// A supply brownout resets a driver to its MS-pin microstepping and pot current
// without telling anyone, so re-check the register and restore it.
void restoreResetDrivers() {
  static uint32_t lastCheck = 0;
  uint32_t now = millis();
  if (now - lastCheck < DRIVER_CHECK_INTERVAL_MS) return;
  lastCheck = now;
  for (Axis& axis : axes) {
    if (!axis.present || axis.driver.microsteps() == MICROSTEPS) continue;
    Serial.printf("# %s driver lost its settings (supply brownout?), restoring\n", axis.name);
    configureDriver(axis);
  }
}

// --- Motion --------------------------------------------------------------------

void applyMotionLimits() {
  for (Axis& axis : axes) {
    axis.stepper->setSpeedInHz(speedHz);
    axis.stepper->setAcceleration(accel);
    axis.stepper->applySpeedAcceleration();
  }
}

void decelerateToStop() {
  for (Axis& axis : axes) axis.stepper->stopMove();
}

void stopImmediately() {
  for (Axis& axis : axes) axis.stepper->forceStopAndNewPosition(axis.stepper->getCurrentPosition());
}

bool anyRunning() {
  for (Axis& axis : axes) {
    if (axis.stepper->isRunning()) return true;
  }
  return false;
}

void updateMotorLeds() {
  for (Axis& axis : axes) digitalWrite(axis.ledPin, axis.stepper->isRunning() ? HIGH : LOW);
}

void waitForMotion() {
  while (anyRunning()) {
    updateMotorLeds();
    delay(1);
  }
  updateMotorLeds();
}

// Reads microsteps and current back from each driver: they fall back to the
// MS-pin and Vref defaults if the driver browns out and loses its registers.
void printStatus() {
  Serial.printf("pos X%ld Y%ld moving:%d en:%d joy:%d fine:%d speed:%lu accel:%lu",
                (long)axes[0].stepper->getCurrentPosition(), (long)axes[1].stepper->getCurrentPosition(),
                anyRunning(), driversEnabled, joystickEnabled, jogFine, (unsigned long)speedHz,
                (unsigned long)accel);
  for (Axis& axis : axes) {
    if (axis.present) Serial.printf(" drv%s:%u/%umA", axis.name, axis.driver.microsteps(), axis.driver.rms_current());
  }
  Serial.println();
}

// --- Joystick ------------------------------------------------------------------

void calibrateJoystickCentre() {
  long sum[AXIS_COUNT] = {};
  for (int i = 0; i < JOY_CALIBRATION_SAMPLES; i++) {
    for (size_t a = 0; a < AXIS_COUNT; a++) sum[a] += analogRead(axes[a].joyPin);
    delay(2);
  }
  for (size_t a = 0; a < AXIS_COUNT; a++) axes[a].joyCentre = sum[a] / JOY_CALIBRATION_SAMPLES;
  Serial.printf("# joystick centre measured at x:%d y:%d\n", axes[0].joyCentre, axes[1].joyCentre);
}

uint32_t jogMaxHz() { return jogFine ? JOG_SPEED_FINE_HZ : JOG_SPEED_COARSE_HZ; }

// Signed jog speed in Hz, or zero inside the deadzone. Each side is scaled
// against its own travel, so an off-centre rest point does not slow one way.
int32_t joystickAxisSpeed(const Axis& axis, int raw) {
  int delta = raw - axis.joyCentre;
  if (abs(delta) < JOY_DEADZONE) return 0;

  int span = (delta > 0 ? JOY_ADC_MAX - axis.joyCentre : axis.joyCentre) - JOY_DEADZONE;
  float fraction = constrain((float)(abs(delta) - JOY_DEADZONE) / (float)max(span, 1), 0.0f, 1.0f);
  float shaped = fraction;
  for (int i = 1; i < JOY_CURVE_EXPONENT; i++) shaped *= fraction;

  int32_t hz = (int32_t)(shaped * (float)jogMaxHz());
  return (delta > 0) == axis.joyInvert ? -hz : hz;
}

// Serial moves re-apply their own speed and acceleration, so the jog limits set
// here need no undoing.
void jogAxis(FastAccelStepper* stepper, int32_t hz) {
  stepper->setAcceleration(JOG_ACCEL);
  if (hz == 0) {
    stepper->applySpeedAcceleration();
    stepper->stopMove();
    return;
  }
  stepper->setSpeedInHz((uint32_t)abs(hz));
  hz > 0 ? stepper->runForward() : stepper->runBackward();
}

void pollJoystickButton(uint32_t now) {
  static bool lastLevel = true;
  static uint32_t changedAt = 0;
  bool level = digitalRead(PIN_JOY_SW);
  if (level == lastLevel || now - changedAt < JOY_BUTTON_DEBOUNCE_MS) return;
  changedAt = now;
  lastLevel = level;
  if (!level) {
    jogFine = !jogFine;
    Serial.printf("# jog %s\n", jogFine ? "fine" : "coarse");
  }
}

void pollJoystick() {
  static uint32_t lastPoll = 0;
  static bool jogging = false;  // so releasing the stick never stops a serial move

  uint32_t now = millis();
  if (now - lastPoll < JOY_POLL_INTERVAL_MS) return;
  lastPoll = now;

  pollJoystickButton(now);
  if (!joystickEnabled || !driversEnabled) return;

  int32_t hz[AXIS_COUNT];
  bool deflected = false;
  for (size_t a = 0; a < AXIS_COUNT; a++) {
    hz[a] = axes[a].present ? joystickAxisSpeed(axes[a], analogRead(axes[a].joyPin)) : 0;
    deflected |= hz[a] != 0;
  }

  if (deflected) {
    jogging = true;
  } else if (!jogging) {
    return;
  } else {
    jogging = false;
  }
  for (size_t a = 0; a < AXIS_COUNT; a++) jogAxis(axes[a].stepper, hz[a]);
}

// --- Commands ------------------------------------------------------------------
// Each handler prints its own "err ..." and returns false, or returns true and
// lets handleCommand print "ok".

// Parse "X123 Y-45", rejecting any other label.
bool parseAxes(const String& args, AxisTargets& targets) {
  int i = 0;
  while (i < (int)args.length()) {
    if (args[i] == ' ') {
      i++;
      continue;
    }
    int end = args.indexOf(' ', i + 1);
    if (end < 0) end = args.length();
    String value = args.substring(i + 1, end);
    Axis* axis = findAxis(String(args[i]));
    if (!axis || value.length() == 0) return false;

    size_t index = axis - axes;
    targets.value[index] = value.toInt();
    targets.has[index] = true;
    i = end;
  }
  for (bool has : targets.has) {
    if (has) return true;
  }
  return false;
}

bool readPositive(const String& args, const char* name, uint32_t& target) {
  long value = args.toInt();
  if (value <= 0) {
    Serial.printf("err %s must be > 0\n", name);
    return false;
  }
  target = value;
  return true;
}

bool readFlag(const String& args, const char* usage, bool& target) {
  if (args != "0" && args != "1") {
    Serial.printf("err usage: %s\n", usage);
    return false;
  }
  target = (args == "1");
  return true;
}

bool requireDriversEnabled() {
  if (driversEnabled) return true;
  Serial.println("err drivers disabled, send EN 1");
  return false;
}

bool requireAxis(const Axis& axis) {
  if (axis.present) return true;
  Serial.printf("err %s axis unavailable, its driver did not respond\n", axis.name);
  return false;
}

bool commandMove(const String& args, bool absolute) {
  AxisTargets targets;
  if (!parseAxes(args, targets)) {
    Serial.println("err usage: MOVE X<n> Y<n>");
    return false;
  }
  if (!requireDriversEnabled()) return false;
  for (size_t a = 0; a < AXIS_COUNT; a++) {
    if (targets.has[a] && !requireAxis(axes[a])) return false;
  }

  applyMotionLimits();
  for (size_t a = 0; a < AXIS_COUNT; a++) {
    if (!targets.has[a]) continue;
    absolute ? axes[a].stepper->moveTo(targets.value[a]) : axes[a].stepper->move(targets.value[a]);
  }
  return true;
}

// JOG X<hz> Y<hz>: run each named axis at a signed velocity until told
// otherwise; 0 decelerates that axis to a stop. Lets a host act as a switch.
bool commandJog(const String& args) {
  AxisTargets targets;
  if (!parseAxes(args, targets)) {
    Serial.println("err usage: JOG X<hz> Y<hz>");
    return false;
  }
  if (!requireDriversEnabled()) return false;
  for (size_t a = 0; a < AXIS_COUNT; a++) {
    if (targets.has[a] && !requireAxis(axes[a])) return false;
  }
  for (size_t a = 0; a < AXIS_COUNT; a++) {
    if (targets.has[a]) jogAxis(axes[a].stepper, targets.value[a]);
  }
  return true;
}

bool commandCurrent(const String& args) {
  long milliamps = args.toInt();
  if (milliamps < 100 || milliamps > 1500) {
    Serial.println("err current must be 100..1500 mA");
    return false;
  }
  for (Axis& axis : axes) {
    if (axis.present) axis.driver.rms_current(milliamps, MOTOR_HOLD_FRACTION);
  }
  return true;
}

bool commandEnable(const String& args) {
  bool on = false;
  if (!readFlag(args, "EN <0|1>", on)) return false;
  if (!on) stopImmediately();
  setDriversEnabled(on);
  return true;
}

bool commandJoystickReadout() {
  int raw[AXIS_COUNT];
  for (size_t a = 0; a < AXIS_COUNT; a++) raw[a] = analogRead(axes[a].joyPin);
  Serial.printf("joy x:%d y:%d sw:%d -> vx:%ld vy:%ld  (centre x:%d y:%d, deadzone %d)\n", raw[0], raw[1],
                digitalRead(PIN_JOY_SW), (long)joystickAxisSpeed(axes[0], raw[0]),
                (long)joystickAxisSpeed(axes[1], raw[1]), axes[0].joyCentre, axes[1].joyCentre, JOY_DEADZONE);
  return true;
}

// The driver's microstep counter wraps at 1024. Signed change since `before`.
int16_t mscntDelta(uint16_t before, uint16_t after) {
  int16_t delta = (int16_t)((after - before) & 0x3FF);
  return delta > 511 ? delta - 1024 : delta;
}

// Step a little each way and read the driver's own counter, which reports the
// direction it actually took rather than the one it was asked for.
bool commandDirectionTest(const String& args) {
  constexpr int32_t PROBE_STEPS = 20;  // short enough that the counter cannot wrap twice
  constexpr uint32_t SETTLE_MS = 30;

  Axis* axis = findAxis(args.length() ? args : "X");
  if (!axis) {
    Serial.println("err usage: DIRTEST [X|Y]");
    return false;
  }
  if (!requireDriversEnabled() || !requireAxis(*axis)) return false;
  applyMotionLimits();

  uint16_t before = axis->driver.MSCNT();
  axis->stepper->move(PROBE_STEPS);
  waitForMotion();
  delay(SETTLE_MS);
  uint16_t middle = axis->driver.MSCNT();
  axis->stepper->move(-PROBE_STEPS);
  waitForMotion();
  delay(SETTLE_MS);

  int16_t forward = mscntDelta(before, middle);
  int16_t backward = mscntDelta(middle, axis->driver.MSCNT());
  Serial.printf("dirtest %s forward:%+d backward:%+d\n", axis->name, forward, backward);
  if (forward == 0 || backward == 0) {
    Serial.println("# no movement reported, check STEP");
  } else if ((forward > 0) == (backward > 0)) {
    Serial.println("# direction is not reaching the driver");
  } else {
    Serial.println("# direction works");
  }
  return true;
}

bool dispatchCommand(const String& command, const String& args) {
  if (command == "?") {
    printStatus();
    return true;
  }
  if (command == "MOVE") return commandMove(args, false);
  if (command == "GOTO") return commandMove(args, true);
  if (command == "JOG") return commandJog(args);
  if (command == "ZERO") {
    for (Axis& axis : axes) axis.stepper->setCurrentPosition(0);
    return true;
  }
  if (command == "STOP") {
    decelerateToStop();
    return true;
  }
  if (command == "HALT") {
    stopImmediately();
    return true;
  }
  if (command == "WAIT") {
    waitForMotion();
    return true;
  }
  if (command == "SPEED" || command == "ACCEL") {
    uint32_t& target = command == "SPEED" ? speedHz : accel;
    if (!readPositive(args, command == "SPEED" ? "speed" : "accel", target)) return false;
    applyMotionLimits();
    return true;
  }
  if (command == "EN") return commandEnable(args);
  if (command == "JOY") return readFlag(args, "JOY <0|1>", joystickEnabled);
  if (command == "CUR") return commandCurrent(args);
  if (command == "JOYRAW") return commandJoystickReadout();
  if (command == "JOYCAL") {
    calibrateJoystickCentre();
    return true;
  }
  if (command == "DIRTEST") return commandDirectionTest(args);

  Serial.printf("err unknown command '%s'\n", command.c_str());
  return false;
}

void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  int space = line.indexOf(' ');
  String command = (space < 0) ? line : line.substring(0, space);
  String args = (space < 0) ? "" : line.substring(space + 1);
  command.toUpperCase();
  args.trim();

  if (dispatchCommand(command, args)) Serial.println("ok");
}

void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      handleCommand(lineBuffer);
      lineBuffer = "";
    } else if (lineBuffer.length() < SERIAL_LINE_MAX) {
      lineBuffer += c;
    }
  }
}

// --- Setup and loop ------------------------------------------------------------

void configureIo() {
  pinMode(PIN_JOY_SW, INPUT_PULLUP);
  pinMode(PIN_EN, OUTPUT);
  for (Axis& axis : axes) {
    pinMode(axis.ledPin, OUTPUT);
    digitalWrite(axis.ledPin, LOW);
  }
  setDriversEnabled(false);  // motors free until the drivers are configured
  analogReadResolution(12);
}

void configureDrivers() {
  Serial2.begin(TMC_BAUD, SERIAL_8N1, PIN_TMC_RX, PIN_TMC_TX);
  delay(50);
  for (Axis& axis : axes) configureDriver(axis);
}

void configureSteppers() {
  engine.init();
  for (Axis& axis : axes) {
    axis.stepper = engine.stepperConnectToPin(axis.stepPin);
    if (!axis.stepper) {
      Serial.printf("err could not allocate the %s stepper, check its STEP pin\n", axis.name);
      while (true) delay(1000);
    }
    axis.stepper->setDirectionPin(axis.dirPin);
  }
  applyMotionLimits();
}

bool anyDriverPresent() {
  for (Axis& axis : axes) {
    if (axis.present) return true;
  }
  return false;
}

void setup() {
  Serial.begin(HOST_BAUD);
  delay(200);
  Serial.println("# hyperscope stage controller");

  configureIo();
  calibrateJoystickCentre();
  configureDrivers();
  configureSteppers();

  if (!anyDriverPresent()) {
    Serial.println("# no driver responded, check the 12 V supply and the UART wiring");
  } else if (ENABLE_DRIVERS_AT_BOOT) {
    delay(DRIVER_ENABLE_SETTLE_MS);
    setDriversEnabled(true);
    Serial.println("# drivers enabled, joystick active. Send ? for status.");
  } else {
    Serial.println("# ready, send EN 1 to energise the motors");
  }
  Serial.println("ok");
}

void loop() {
  pollSerial();
  pollJoystick();
  restoreResetDrivers();
  updateMotorLeds();
}
