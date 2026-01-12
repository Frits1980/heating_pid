"""PID controller for zone temperature management.

Implements a PID controller with:
- Anti-windup via integral clamping
- Derivative on process variable (not error) to avoid setpoint kick
- Multiplicative outdoor compensation (Ke factor)
- Configurable gains per zone

The controller outputs a demand value (0-100%) representing how much
heating is required for a zone.
"""

from __future__ import annotations

import logging
import time
from typing import Final

_LOGGER = logging.getLogger(__name__)

# Output limits
MIN_OUTPUT: Final = 0.0
MAX_OUTPUT: Final = 100.0


class PIDController:
    """PID controller with anti-windup and outdoor compensation.

    The controller calculates demand based on the temperature error
    (setpoint - current temperature) using the formula:

        output = Kp * error + Ki * integral + Kd * derivative

    With multiplicative outdoor compensation:

        output = output * (1 + Ke * outdoor_factor)

    Where outdoor_factor increases as outdoor temperature drops below
    a reference point (typically 15°C).

    Features:
    - Anti-windup: Integral is clamped and only accumulates when
      output is not saturated
    - Derivative on PV: Uses rate of change of temperature, not error,
      to avoid derivative kick on setpoint changes
    - Outdoor compensation: Multiplicative factor increases output
      when it's colder outside

    Attributes:
        kp: Proportional gain
        ki: Integral gain
        kd: Derivative gain
        ke: Outdoor compensation gain
        integral: Accumulated integral value
        last_pv: Previous process variable for derivative calculation
        last_time: Timestamp of last update
    """

    def __init__(
        self,
        kp: float = 30.0,
        ki: float = 0.5,
        kd: float = 10.0,
        ke: float = 0.02,
    ) -> None:
        """Initialize the PID controller.

        Args:
            kp: Proportional gain (default: 30.0)
            ki: Integral gain (default: 0.5)
            kd: Derivative gain (default: 10.0)
            ke: Outdoor compensation gain (default: 0.02)
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.ke = ke

        # State variables
        self.integral: float = 0.0
        self.last_pv: float | None = None
        self.last_time: float | None = None
        self._last_output: float = 0.0

    def update(
        self,
        setpoint: float,
        process_variable: float,
        outdoor_temp: float | None = None,
        dt: float | None = None,
    ) -> float:
        """Calculate PID output for current state.

        Args:
            setpoint: Target temperature (°C)
            process_variable: Current temperature (°C)
            outdoor_temp: Current outdoor temperature (°C), optional
            dt: Time delta since last update (seconds), or None to calculate

        Returns:
            Demand value between 0 and 100 (%)
        """
        current_time = time.monotonic()

        # Calculate time delta
        if dt is None:
            if self.last_time is None:
                dt = 0.0
            else:
                dt = current_time - self.last_time

        # Calculate error
        error = setpoint - process_variable

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup
        # Only accumulate if not saturated or error would reduce saturation
        if dt > 0:
            potential_integral = self.integral + error * dt
            potential_output = p_term + self.ki * potential_integral

            # Anti-windup: only update integral if output not saturated
            # or if change would move away from saturation
            if MIN_OUTPUT < potential_output < MAX_OUTPUT:
                self.integral = potential_integral
            elif potential_output >= MAX_OUTPUT and error < 0:
                self.integral = potential_integral
            elif potential_output <= MIN_OUTPUT and error > 0:
                self.integral = potential_integral

        i_term = self.ki * self.integral

        # Derivative term (on process variable, not error)
        d_term = 0.0
        if self.last_pv is not None and dt > 0:
            # Negative because we want to resist rapid temperature changes
            d_term = -self.kd * (process_variable - self.last_pv) / dt

        # Base output before outdoor compensation
        output = p_term + i_term + d_term

        # Apply outdoor compensation
        if outdoor_temp is not None and self.ke > 0:
            # Reference temperature for compensation (typical: 15°C)
            reference_temp = 15.0
            if outdoor_temp < reference_temp:
                outdoor_factor = reference_temp - outdoor_temp
                compensation = 1.0 + self.ke * outdoor_factor
                output *= compensation
                _LOGGER.debug(
                    "Outdoor compensation: %.2f°C -> factor %.3f",
                    outdoor_temp,
                    compensation,
                )

        # Clamp output
        output = max(MIN_OUTPUT, min(MAX_OUTPUT, output))

        # Update state
        self.last_pv = process_variable
        self.last_time = current_time
        self._last_output = output

        _LOGGER.debug(
            "PID update: SP=%.1f, PV=%.1f, error=%.2f, "
            "P=%.2f, I=%.2f, D=%.2f, output=%.1f%%",
            setpoint,
            process_variable,
            error,
            p_term,
            i_term,
            d_term,
            output,
        )

        return output

    def reset(self) -> None:
        """Reset the controller state.

        Clears integral, derivative history, and timing.
        Called when zone is disabled or on significant setpoint changes.
        """
        self.integral = 0.0
        self.last_pv = None
        self.last_time = None
        self._last_output = 0.0
        _LOGGER.debug("PID controller reset")

    def set_gains(
        self,
        kp: float | None = None,
        ki: float | None = None,
        kd: float | None = None,
        ke: float | None = None,
    ) -> None:
        """Update PID gains.

        Allows live tuning of controller parameters.

        Args:
            kp: New proportional gain, or None to keep current
            ki: New integral gain, or None to keep current
            kd: New derivative gain, or None to keep current
            ke: New outdoor compensation gain, or None to keep current
        """
        if kp is not None:
            self.kp = kp
        if ki is not None:
            self.ki = ki
        if kd is not None:
            self.kd = kd
        if ke is not None:
            self.ke = ke
        _LOGGER.debug(
            "PID gains updated: Kp=%.2f, Ki=%.2f, Kd=%.2f, Ke=%.4f",
            self.kp,
            self.ki,
            self.kd,
            self.ke,
        )

    @property
    def last_output(self) -> float:
        """Return the last calculated output value."""
        return self._last_output

    @property
    def gains(self) -> dict[str, float]:
        """Return current gains as a dictionary."""
        return {
            "kp": self.kp,
            "ki": self.ki,
            "kd": self.kd,
            "ke": self.ke,
        }
