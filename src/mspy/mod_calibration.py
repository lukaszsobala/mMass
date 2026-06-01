# -------------------------------------------------------------------------
#     Copyright (C) 2005-2013 Martin Strohalm <www.mmass.org>

#     This program is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 3 of the License, or
#     (at your option) any later version.

#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.

#     Complete text of GNU GPL can be found in the file LICENSE.TXT in the
#     main directory of the program.
# -------------------------------------------------------------------------

# load libs
from typing import Callable

import numpy
from numpy.linalg import solve as solveLinEq

# DATA RE-CALIBRATION
# -------------------


def calibration(data, model="linear"):
    """Calculate calibration constants for given references.
    data (list or (measured mass, reference mass)) - calibration data
    model ('linear' or 'quadratic') - fitting model
    """

    # single point calibration
    if model == "linear" and len(data) == 1:
        shift = data[0][1] - data[0][0]
        return _linearModel, (1.0, shift), 1.0

    # set fitting model and initial values
    if model == "linear":
        model = _linearModel
        initials = (0.5, 0)
    elif model == "quadratic":
        model = _quadraticModel
        initials = (1.0, 0, 0)

    # calculate calibration constants
    params = _leastSquaresFit(model, initials, data)

    # fn, parameters, chi-square
    return model, params[0], params[1]


# ----


def _linearModel(params, x):
    """Function for linear model."""

    a, b = params
    return a * x + b


# ----


def _quadraticModel(params, x):
    """Function for quadratic model."""

    a, b, c = params
    return a * x * x + b * x + c


# ----


def _leastSquaresFit(model, parameters, data, maxIterations=None, limit=1e-7):
    """General non-linear least-squares fit using the
    Levenberg-Marquardt algorithm and automatic derivatives.
    Originally developed by Konrad Hinsen.
    """

    n_param = len(parameters)
    p = ()
    i = 0
    for param in parameters:
        p = p + (_DerivVar(param, i),)
        i = i + 1
    identity = numpy.identity(n_param)
    damping = 0.001
    chi_sq, alpha = _chiSquare(model, p, data)
    niter = 0

    while True:
        niter += 1

        delta = solveLinEq(
            alpha + damping * numpy.diagonal(alpha) * identity,
            -0.5 * numpy.array(chi_sq.deriv),
        )
        next_p = list(map(lambda a, b: a + b, p, delta))

        next_chi_sq, next_alpha = _chiSquare(model, next_p, data)
        if next_chi_sq > chi_sq:
            damping = 10.0 * damping
        elif chi_sq.value - next_chi_sq.value < limit:
            break
        else:
            damping = 0.1 * damping
            p = next_p
            chi_sq = next_chi_sq
            alpha = next_alpha

        if maxIterations and niter == maxIterations:
            break

    return [param.value for param in next_p], next_chi_sq.value


# ----


def _chiSquare(model, parameters, data):
    """Count chi-square."""

    n_param = len(parameters)
    alpha = numpy.zeros((n_param, n_param))

    chi_sq = _DerivVar(0.0, [0.0] * n_param)
    for point in data:
        f = model(parameters, point[0])
        chi_sq += (f - point[1]) ** 2
        d = numpy.array(f[1])
        alpha = alpha + d[:, numpy.newaxis] * d

    return chi_sq, alpha


# ----


class _DerivVar:
    """This module provides automatic differentiation for functions with any number of variables."""

    value: float
    deriv: list[float]

    def __init__(self, value: float, index: int | float | str | list[float] = 0):
        self.value = float(value)
        if isinstance(index, list):
            self.deriv = [float(x) for x in index]
        else:
            if isinstance(index, int):
                seed_index = index
            elif isinstance(index, float):
                seed_index = int(index)
            elif isinstance(index, str):
                seed_index = int(index)
            else:
                raise TypeError("index must be int-like or derivative list")
            self.deriv = [0.0] * seed_index + [1.0]

    def _mapderiv(
        self, func: Callable[[float, float], float], a: list[float], b: list[float]
    ) -> list[float]:
        nvars = max(len(a), len(b))
        a = a + (nvars - len(a)) * [0.0]
        b = b + (nvars - len(b)) * [0.0]
        return [func(x, y) for x, y in zip(a, b)]

    def __getitem__(self, item):
        if item == 0:
            return self.value
        elif item == 1:
            return self.deriv
        else:
            raise IndexError

    def __lt__(self, other):
        if isinstance(other, _DerivVar):
            return self.value < other.value
        else:
            return self.value < other

    def __eq__(self, other):
        if isinstance(other, _DerivVar):
            return self.value == other.value
        else:
            return self.value == other

    def __add__(self, other):
        if isinstance(other, _DerivVar):
            return _DerivVar(
                self.value + other.value,
                self._mapderiv(lambda a, b: a + b, self.deriv, other.deriv),
            )
        else:
            return _DerivVar(self.value + other, self.deriv)

    def __radd__(self, other):
        if isinstance(other, _DerivVar):
            self.value += other.value
            self.deriv = self._mapderiv(lambda a, b: a + b, self.deriv, other.deriv)
            return self
        else:
            self.value += other
            return self

    def __sub__(self, other):
        if isinstance(other, _DerivVar):
            return _DerivVar(
                self.value - other.value,
                self._mapderiv(lambda a, b: a - b, self.deriv, other.deriv),
            )
        else:
            return _DerivVar(self.value - other, self.deriv)

    def __rsub__(self, other):
        if isinstance(other, _DerivVar):
            self.value -= other.value
            self.deriv = self._mapderiv(lambda a, b: a - b, self.deriv, other.deriv)
            return self
        else:
            self.value -= other
            return self

    def __mul__(self, other):
        if isinstance(other, _DerivVar):
            return _DerivVar(
                self.value * other.value,
                self._mapderiv(
                    lambda a, b: a + b,
                    [self.value * x for x in other.deriv],
                    [other.value * x for x in self.deriv],
                ),
            )
        else:
            return _DerivVar(self.value * other, [other * x for x in self.deriv])

    def __div__(self, other):
        if isinstance(other, _DerivVar):
            inv = 1.0 / other.value
            return _DerivVar(
                self.value * inv,
                self._mapderiv(
                    lambda a, b: a - b,
                    [inv * x for x in self.deriv],
                    [self.value * inv * inv * x for x in other.deriv],
                ),
            )
        else:
            inv = 1.0 / other
            return _DerivVar(self.value * inv, [inv * x for x in self.deriv])

    def __pow__(self, other):
        val1 = pow(self.value, other - 1)
        deriv1 = [val1 * other * x for x in self.deriv]
        return _DerivVar(val1 * self.value, deriv1)

    def __abs__(self):
        absvalue = abs(self.value)
        return _DerivVar(absvalue, [self.value / absvalue * a for a in self.deriv])


# ----
