#include "TMC2209_Driver.h"

#include <Arduino.h>
#include <TMCStepper.h>

#define DEFAULT_PULSE_WIDTH_US 500U
#define MIN_PULSE_WIDTH_US 2U

static bool valid_driver(const TMC2209Driver *driver) {
    return driver != nullptr;
}

bool TMC2209_Init(
    TMC2209Driver *driver,
    HardwareSerial *uart,
    int uart_rx_pin,
    int uart_tx_pin,
    uint8_t uart_address,
    int step_pin,
    int dir_pin,
    int en_pin,
    bool dir_inverted,
    bool en_active_low,
    uint32_t steps_per_rev,
    float r_sense,
    uint16_t run_current_ma,
    uint16_t microsteps
) {
    if (!valid_driver(driver) || uart == nullptr) {
        return false;
    }

    driver->step_pin = step_pin;
    driver->dir_pin = dir_pin;
    driver->en_pin = en_pin;
    driver->uart_rx_pin = uart_rx_pin;
    driver->uart_tx_pin = uart_tx_pin;
    driver->uart_address = uart_address;
    driver->dir_inverted = dir_inverted;
    driver->en_active_low = en_active_low;
    driver->pulse_width_us = DEFAULT_PULSE_WIDTH_US;
    driver->steps_per_rev = (steps_per_rev == 0U) ? 200U : steps_per_rev;
    driver->is_enabled = false;
    driver->r_sense = (r_sense <= 0.0f) ? 0.11f : r_sense;
    driver->run_current_ma = (run_current_ma == 0U) ? 800U : run_current_ma;
    driver->microsteps = (microsteps == 0U) ? 16U : microsteps;
    driver->uart = uart;
    driver->tmc = nullptr;

    pinMode(driver->step_pin, OUTPUT);
    pinMode(driver->dir_pin, OUTPUT);
    pinMode(driver->en_pin, OUTPUT);

    digitalWrite(driver->step_pin, LOW);
    digitalWrite(driver->dir_pin, LOW);
    TMC2209_Disable(driver);

    return true;
}

bool TMC2209_Begin(TMC2209Driver *driver, uint32_t uart_baud) {
    if (!valid_driver(driver) || driver->uart == nullptr) {
        return false;
    }

    if (driver->tmc != nullptr) {
        delete driver->tmc;
        driver->tmc = nullptr;
    }

    driver->uart->begin(uart_baud, SERIAL_8N1, driver->uart_rx_pin, driver->uart_tx_pin);

    driver->tmc = new TMC2209Stepper(driver->uart, driver->r_sense, driver->uart_address);
    if (driver->tmc == nullptr) {
        return false;
    }

    driver->tmc->begin();
    driver->tmc->toff(5);
    driver->tmc->rms_current(driver->run_current_ma);
    driver->tmc->microsteps(driver->microsteps);
    driver->tmc->pwm_autoscale(true);
    driver->tmc->en_spreadCycle(false);

    return true;
}

void TMC2209_Enable(TMC2209Driver *driver) {
    if (!valid_driver(driver)) {
        return;
    }

    digitalWrite(driver->en_pin, driver->en_active_low ? LOW : HIGH);
    driver->is_enabled = true;
}

void TMC2209_Disable(TMC2209Driver *driver) {
    if (!valid_driver(driver)) {
        return;
    }

    digitalWrite(driver->en_pin, driver->en_active_low ? HIGH : LOW);
    driver->is_enabled = false;
}

void TMC2209_SetDirection(TMC2209Driver *driver, bool clockwise) {
    if (!valid_driver(driver)) {
        return;
    }

    bool dir = driver->dir_inverted ? !clockwise : clockwise;
    digitalWrite(driver->dir_pin, dir ? HIGH : LOW);
}

void TMC2209_SetPulseWidthUs(TMC2209Driver *driver, uint32_t pulse_width_us) {
    if (!valid_driver(driver)) {
        return;
    }

    driver->pulse_width_us = (pulse_width_us < MIN_PULSE_WIDTH_US) ? MIN_PULSE_WIDTH_US : pulse_width_us;
}

void TMC2209_SetStepLevel(TMC2209Driver *driver, bool level_high) {
    if (!valid_driver(driver)) {
        return;
    }

    digitalWrite(driver->step_pin, level_high ? HIGH : LOW);
}

void TMC2209_Pulse(TMC2209Driver *driver) {
    if (!valid_driver(driver)) {
        return;
    }

    TMC2209_SetStepLevel(driver, true);
    delayMicroseconds(driver->pulse_width_us);
    TMC2209_SetStepLevel(driver, false);
    delayMicroseconds(driver->pulse_width_us);
}

uint8_t TMC2209_TestConnection(TMC2209Driver *driver) {
    if (!valid_driver(driver) || driver->tmc == nullptr) {
        return 255U;
    }

    return driver->tmc->test_connection();
}
