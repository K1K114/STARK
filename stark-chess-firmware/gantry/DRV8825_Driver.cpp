#include "DRV8825_Driver.h"

#include <Arduino.h>

#define DEFAULT_PULSE_WIDTH_US 500U
#define MIN_PULSE_WIDTH_US 2U

static bool valid_driver(const DRV8825Driver *driver) {
    return driver != nullptr;
}

bool DRV8825_Init(
    DRV8825Driver *driver,
    int step_pin,
    int dir_pin,
    int en_pin,
    bool dir_inverted,
    bool en_active_low
) {
    if (!valid_driver(driver)) {
        return false;
    }

    driver->step_pin = step_pin;
    driver->dir_pin = dir_pin;
    driver->en_pin = en_pin;
    driver->dir_inverted = dir_inverted;
    driver->en_active_low = en_active_low;
    driver->pulse_width_us = DEFAULT_PULSE_WIDTH_US;
    driver->is_enabled = false;

    pinMode(driver->step_pin, OUTPUT);
    pinMode(driver->dir_pin, OUTPUT);
    pinMode(driver->en_pin, OUTPUT);

    digitalWrite(driver->step_pin, LOW);
    digitalWrite(driver->dir_pin, LOW);
    DRV8825_Disable(driver);

    return true;
}

void DRV8825_Enable(DRV8825Driver *driver) {
    if (!valid_driver(driver)) {
        return;
    }

    digitalWrite(driver->en_pin, driver->en_active_low ? LOW : HIGH);
    driver->is_enabled = true;
}

void DRV8825_Disable(DRV8825Driver *driver) {
    if (!valid_driver(driver)) {
        return;
    }

    digitalWrite(driver->en_pin, driver->en_active_low ? HIGH : LOW);
    driver->is_enabled = false;
}

void DRV8825_SetDirection(DRV8825Driver *driver, bool clockwise) {
    if (!valid_driver(driver)) {
        return;
    }

    bool dir = driver->dir_inverted ? !clockwise : clockwise;
    digitalWrite(driver->dir_pin, dir ? HIGH : LOW);
}

void DRV8825_SetPulseWidthUs(DRV8825Driver *driver, uint32_t pulse_width_us) {
    if (!valid_driver(driver)) {
        return;
    }

    driver->pulse_width_us = (pulse_width_us < MIN_PULSE_WIDTH_US) ? MIN_PULSE_WIDTH_US : pulse_width_us;
}

void DRV8825_SetStepLevel(DRV8825Driver *driver, bool level_high) {
    if (!valid_driver(driver)) {
        return;
    }

    digitalWrite(driver->step_pin, level_high ? HIGH : LOW);
}

void DRV8825_Pulse(DRV8825Driver *driver) {
    if (!valid_driver(driver)) {
        return;
    }

    DRV8825_SetStepLevel(driver, true);
    delayMicroseconds(driver->pulse_width_us);
    DRV8825_SetStepLevel(driver, false);
    delayMicroseconds(driver->pulse_width_us);
}
