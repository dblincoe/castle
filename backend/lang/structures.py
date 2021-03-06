import math
import operator
import decimal
from abc import ABC, abstractmethod
from collections import Counter
from functools import reduce
from typing import List

import numpy as np
from scipy.special import comb
import sympy

from backend.lang.State import State
from backend.lang.Dicts import builtin_func_dict, inv_rel_dict
from backend.lang.LaTeXParser import LaTeXParser as parse


class Function(ABC):
    @abstractmethod
    def evaluate(self, state):
        pass

    def __add__(self, other):
        return Expression(operator.add, self, other)

    def __sub__(self, other):
        return Expression(operator.sub, self, other)

    def __mul__(self, other):
        return Expression(operator.mul, self, other)

    def __truediv__(self, other):
        return Expression(operator.truediv, self, other)

    def __floordiv__(self, other):
        return Expression(operator.floordiv, self, other)

    def __pow__(self, power, modulo=None):
        return Expression(operator.pow, self, power)

    @abstractmethod
    def __eq__(self, other):
        pass

    @abstractmethod
    def __ne__(self, other):
        pass

    @abstractmethod
    def derivative(self):
        pass

    @abstractmethod
    def integral(self):
        pass


class Expression(Function):
    op_str = {
        operator.mul: "*",
        operator.truediv: "/",  # divisions entered using '/'
        operator.floordiv: "//",  # divisions entered using '\frac'
        operator.add: "+",
        operator.sub: "-",
        operator.pow: "^",
    }

    def __init__(self, op: callable, *terms):
        # how should we handle expressions taken to powers?
        self.op = op
        self.terms = list(terms)
        assert (
            len(self.terms) == 2
            if self.op in [operator.truediv, operator.floordiv, operator.pow]
            else len(self.terms) >= 2
        )

    def evaluate(self, state: State):
        if (
            self.op == operator.pow
            and len(self.terms) == 2
            and (
                (isinstance(self.terms[0], Matrix) and self.terms[0].type != "vmatrix")
                or (
                    isinstance(self.terms[0], Variable)
                    and isinstance(self.terms[0].evaluate(state), Matrix)
                )
            )
            and isinstance(self.terms[1], Variable)
            and self.terms[1].name == "T"
        ):
            # transpose
            return self.terms[0].evaluate(state).transpose()
        if self.op != operator.floordiv:
            return reduce(
                self.op, [term.evaluate(state) for term in self.terms]
            ).evaluate(state)
        else:
            # floordiv indicates that this division was entered using \frac. If each side is a number make a fraction
            left_eval = self.terms[0].evaluate(state)
            right_eval = self.terms[1].evaluate(state)
            if isinstance(left_eval, Number) and isinstance(right_eval, Number):
                return Fraction.create(left_eval, right_eval).evaluate(state)
            else:
                # TODO: This is where we'd implement rational simplification - ie \frac{x}{2x} = \frac{1}{2}
                raise Exception(
                    "Fractions of things that aren't numbers not yet implemented"
                )

    def __eq__(self, other):
        return (
            isinstance(other, Expression)
            and other.op == self.op
            and Counter(other.terms) == Counter(self.terms)
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def derivative(self):
        # if addition or subtraction then we just add or subtract the derivatives
        if self.op in [operator.add, operator.sub]:
            return Expression(self.op, *[term.derivative() for term in self.terms])
        # recursive product rule for n terms
        elif self.op == operator.mul:
            # base case for standard product rule
            if len(self.terms) == 2:
                return (
                    self.terms[1] * self.terms[0].derivative()
                    + self.terms[0] * self.terms[1].derivative()
                )
            else:
                remaining_terms = Expression(self.op, *self.terms[1:])
                return (
                    self.terms[0].derivative() * remaining_terms
                    + self.terms[0] * remaining_terms.derivative()
                )
        # quotient rule
        elif self.op in [operator.truediv, operator.floordiv]:
            left, right = self.terms[0], self.terms[1]
            return (left.derivative() * right - right.derivative() * left) / (
                right ** 2
            )
        else:
            raise CastleException("bad quotient rule")

    # TODO: how tf do we do this
    def integral(self):
        pass

    def __repr__(self):
        if self.op == operator.floordiv:
            return f"\\frac{{{self.terms[0]}}}{{{self.terms[1]}}}"
        return Expression.op_str[self.op].join([str(term) for term in self.terms])


class Variable(Function):
    def __init__(self, state, base_var, subscript=None):
        self.base_var = base_var
        self.name = base_var
        self.subscript = subscript
        if subscript is not None:
            self.name += "_{" + str(subscript.evaluate(state)) + "}"

    def evaluate(self, state: State):
        # reevaluate subscript with current state
        if self.subscript is not None:
            new_name = self.base_var + "_{" + str(self.subscript.evaluate(state)) + "}"
        else:
            new_name = self.name

        if self.name in state or new_name in state:
            # replace this variable's key in state with new variable name
            if new_name != self.name and self.name in state:
                state.replace(self.name, new_name)
                self.name = new_name
            return state[new_name].evaluate(state)

        self.name = new_name
        return self.name

    def __eq__(self, f) -> bool:
        return isinstance(f, Variable) and f.name == self.name

    def __ne__(self, other):
        return not (isinstance(other, Variable) and other.name == self.name)

    def derivative(self):
        return 1

    def integral(self):
        return Monomial(coeff=1, var=self, power=2) / 2

    def __repr__(self) -> str:
        return self.name


class Monomial(Function):
    def __init__(self, coeff, var: Variable, power):
        self.coeff = coeff
        self.var = var
        self.power = power

    def __add__(self, other):
        if (
            isinstance(other, Monomial)
            and other.var == self.var
            and other.power == self.power
        ):
            return Monomial(self.coeff + other.coeff, self.var, self.power)
        else:
            return super().__add__(other)

    def __sub__(self, other):
        if (
            isinstance(other, Monomial)
            and other.var == self.var
            and other.power == self.power
        ):
            return Monomial(self.coeff - other.coeff, self.var, self.power)
        else:
            return super().__sub__(other)

    def __mul__(self, other):
        if isinstance(other, Monomial) and other.var == self.var:
            return Monomial(
                self.coeff * other.coeff, self.var, other.power + self.power
            )
        else:
            return super().__mul__(other)

    def __truediv__(self, other):
        if isinstance(other, Monomial) and other.var == self.var:
            return (
                Monomial(self.coeff, self.var, self.power - other.power) / other.coeff
            )
        else:
            return super().__truediv__(other)

    def evaluate(self, state: State):
        return self.coeff * (state[self.var.name] ** self.power)

    def __eq__(self, other):
        return (
            self.coeff == other.coeff
            and self.var == other.var
            and self.power == other.power
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def derivative(self):
        return Monomial(
            coeff=self.coeff * self.power, var=self.var, power=self.power - 1
        )

    def integral(self):
        return Monomial(coeff=self.coeff, var=self.var, power=self.power + 1) / (
            self.power + 1
        )

    def __repr__(self):
        if self.power == 0:
            return f"{self.coeff}"
        elif self.power == 1:
            return f"{self.coeff if self.coeff != 1 else ''}{self.var}"
        else:
            return f"{self.coeff}{self.var}^{{{self.power}}}"


class Polynomial(Expression):
    def __init__(self, *terms):
        super().__init__(op=operator.add, *terms)
        assert all(isinstance(term, Monomial) for term in self.terms)


class Number(Function, ABC):
    @staticmethod
    def number_init(value):
        if isinstance(value, (RealNumber, float, int)):
            return RealNumber(value)
        return None

    @abstractmethod
    def __add__(self, other):
        pass

    @abstractmethod
    def __sub__(self, other):
        pass

    @abstractmethod
    def __mul__(self, other):
        pass

    @abstractmethod
    def __truediv__(self, other):
        pass

    @abstractmethod
    def evaluate(self, state=None):
        pass

    @abstractmethod
    def true_value(self):
        pass

    @abstractmethod
    def __eq__(self, other):
        pass

    @abstractmethod
    def __ne__(self, other):
        pass

    @abstractmethod
    def __lt__(self, other):
        pass

    @abstractmethod
    def __gt__(self, other):
        pass

    @abstractmethod
    def __le__(self, other):
        pass

    @abstractmethod
    def __ge__(self, other):
        pass

    @abstractmethod
    def derivative(self):
        pass

    @abstractmethod
    def __repr__(self):
        pass


class RealNumber(Number):
    ZERO_CUTOFF = 1e-12

    def __init__(self, val):
        if isinstance(val, RealNumber):
            value = val.value
        elif isinstance(val, (int, float)):
            value = val
        else:
            raise CastleException("Improper instantiation of real number")

        if abs(np.round(value) - value) < RealNumber.ZERO_CUTOFF:
            # cast floats like 4.0 as ints
            self.value = int(np.round(value))
        else:
            self.value = value

    def __add__(self, other):
        if isinstance(other, RealNumber):
            return RealNumber(self.value + other.value)
        if isinstance(other, (int, float)):
            return RealNumber(self.value + other)
        else:
            # addition is commutative and we assume we've implemented other + RealNumber in other's class
            return other + self

    def __sub__(self, other):
        if isinstance(other, RealNumber):
            return RealNumber(self.value - other.value)
        if isinstance(other, (int, float)):
            return RealNumber(self.value - other)
        else:
            # subtraction is (almost) commutative and we assume we've already implemented other + RealNumber
            return RealNumber(-1) * other + self

    def __mul__(self, other):
        if isinstance(other, RealNumber):
            return RealNumber(self.value * other.value)
        if isinstance(other, (int, float)):
            return RealNumber(self.value * other)
        else:
            # multiplication is commutative and we assume we've implemented other * RealNumber in other's class
            return other * self

    def __truediv__(self, other):
        if isinstance(other, RealNumber):
            if other.value == 0:
                raise CastleException("Can't divide by zero")
            return RealNumber(self.value / other.value)
        if isinstance(other, (int, float)):
            return RealNumber(self.value / other)
        elif isinstance(other, Fraction):
            # divide real number by fraction: a/(b/c) = (ac)/b
            return Fraction.create(self * other.den, other.num)
        elif isinstance(other, ComplexNumber):
            # use ComplexNumber's division procedure
            return ComplexNumber(self, RealNumber(0)) / other
        else:
            # as of now we can't divide RealNumber by anything else
            raise CastleException(f"can't divide RealNumber {self} by {other}")

    def __floordiv__(self, other):
        """ Only for internal use to create a fraction from a // b """
        if isinstance(other, RealNumber):
            return Fraction.create(self, other).simplify()
        if isinstance(other, (int, float)):
            return Fraction.create(self, RealNumber(other)).simplify()
        if isinstance(other, Fraction):
            # __truediv__ already correctly creates a fraction in this case
            return (self / other).simplify()
        if isinstance(other, ComplexNumber):
            # just use the regular division procedure
            return self / other
        else:
            raise CastleException(
                f"__floordiv__ only supported for types {type(self)} and {type(other)}"
            )

    def __pow__(self, other):
        if isinstance(other, RealNumber):
            return RealNumber(self.value ** other.value)
        if isinstance(other, (int, float)):
            return RealNumber(self.value ** other)
        if isinstance(other, Fraction):
            return RealNumber(self ** other.true_value())
        if isinstance(other, ComplexNumber):
            # use ComplexNumber's power procedure
            return ComplexNumber(self, RealNumber(0)) ** other

    def evaluate(self, state=None):
        return self

    def true_value(self):
        """ Get the numerical value of this Number, not the object like evaluate()"""
        return self.value

    def simplify(self):
        """ just need this because fraction.create() can return a RealNumber,
        and we call fraction.create(...).simplify()"""
        return self

    def __eq__(self, other):
        RealNumber.ZERO_CUTOFF = 1e-12
        if isinstance(other, RealNumber):
            # equating floats doesn't work well since we don't use arbitrary precision.
            return abs(self.value - other.value) < RealNumber.ZERO_CUTOFF
        elif isinstance(other, (int, float)):
            return abs(self.value - other) < RealNumber.ZERO_CUTOFF
        else:
            return other.__eq__(self)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        if isinstance(other, RealNumber):
            return self.value < other.value
        elif isinstance(other, (int, float)):
            return self.true_value() < other
        else:
            return other.__gt__(self)

    def __gt__(self, other):
        if isinstance(other, RealNumber):
            return self.value > other.value
        elif isinstance(other, (int, float)):
            return self.true_value() > other
        else:
            return other.__lt__(self)

    def __le__(self, other):
        return self < other or self == other

    def __ge__(self, other):
        return self > other or self == other

    def derivative(self):
        return 0

    def integral(self):
        pass

    def __repr__(self):
        # if it's an integer, print as an integer
        if self.value == float("inf"):
            return "\\infty"
        if self.value == float("-inf"):
            return "-\\infty"
        if int(self.value) == self.value:
            return str(int(self.value))
        return str(self.value)


class Fraction(Number):
    """This class represents a numerical fraction at evaluation time, not a rational function, which would be stored
    as Expression with op.truediv/floordiv. For example, this class would hold \\frac{1}{2} but
    \\frac{x}{2} is an Expression"""

    @staticmethod
    def create(num, den):
        """return a fraction if num and den are both 'rational' and a RealNumber otherwise"""
        assert isinstance(num, Number) and isinstance(den, Number)

        if isinstance(num, ComplexNumber) or isinstance(den, ComplexNumber):
            return num / den

        if isinstance(num, RealNumber) and isinstance(num.value, float):
            # convert any float with less than 10 decimal places into a fraction.
            # Otherwise assume it's irrational and return a RealNumber
            str_value = str(num.value)
            dot_loc = str_value.find(".")
            num_decimal_places = len(str_value) - dot_loc - 1
            if num_decimal_places > 10:
                return num / den

            num = RealNumber(int(str_value[:dot_loc])) + Fraction(
                RealNumber(int(str_value[dot_loc + 1 :])),
                RealNumber(10 ** num_decimal_places),
            )

        if isinstance(den, RealNumber) and isinstance(den.value, float):
            # convert any float with less than 10 decimal places into a fraction.
            # Otherwise assume it's irrational and return a RealNumber
            str_value = str(den.value)
            dot_loc = str_value.find(".")
            num_decimal_places = len(str_value) - dot_loc - 1
            if num_decimal_places > 10:
                return num / den

            den = RealNumber(int(str_value[:dot_loc])) + Fraction(
                RealNumber(int(str_value[dot_loc + 1 :])),
                RealNumber(10 ** num_decimal_places),
            )

        return Fraction(num, den)

    def __init__(self, top, bottom):
        """don't initialize with Fraction() - use Fraction.create() factory instead"""
        assert isinstance(top, Number) and isinstance(bottom, Number)
        if isinstance(top, (RealNumber, ComplexNumber)) and isinstance(
            bottom, (RealNumber, ComplexNumber)
        ):
            self.num = top
            self.den = bottom
        else:
            # quotient will usually be a fraction since either top or bottom is a fraction
            # but quotient can also be an integer (\frac{\frac{3}{7}}{\frac{3}{7}}).
            # In this case since we're already in __init__ just do a/1
            quotient = top / bottom
            if isinstance(quotient, RealNumber):
                self.num = quotient
                self.den = RealNumber(1)
            else:
                self.num = quotient.num
                self.den = quotient.den

    def __add__(self, other):
        if isinstance(other, (RealNumber, int, float)):
            # a + (b/c) = (ac+b)/c
            return Fraction.create(self.den * other + self.num, self.den).simplify()
        if isinstance(other, Fraction):
            # (a/b) + (c/d) = (ad+bc)/(bd)
            return Fraction.create(
                self.num * other.den + self.den * other.num, self.den * other.den
            ).simplify()
        if isinstance(other, ComplexNumber):
            # ComplexNumber + Fraction is defined in ComplexNumber
            return other + self
        else:
            raise CastleException(
                f"operation {operator.add} not supported between {type(self)} and {type(other)}"
            )

    def __sub__(self, other):
        return RealNumber(-1) * other + self

    def __mul__(self, other):
        if isinstance(other, (RealNumber, int, float)):
            # multiply fraction by real number: (a/b)*c = (ac)/b
            return Fraction.create(self.num * other, self.den).simplify()
        if isinstance(other, Fraction):
            # multiply fraction by fraction: (a/b)(c/d) = (ac)/(bd)
            return Fraction.create(
                self.num * other.num, self.den * other.den
            ).simplify()
        if isinstance(other, ComplexNumber):
            # ComplexNumber * Fraction is defined in ComplexNumber
            return other * self
        else:
            raise CastleException(
                f"operation {operator.mul} not supported between {type(self)} and {type(other)}"
            )

    def __truediv__(self, other):
        if isinstance(other, (RealNumber, int, float)):
            # divide fraction by real number: (a/b)/c = a/(bc)
            return Fraction.create(self.num, other * self.den).simplify()
        if isinstance(other, Fraction):
            # divide fraction by fraction: (a/b)/(c/d) = (ad)/(bc)
            return Fraction.create(
                self.num * other.den, self.den * other.num
            ).simplify()
        if isinstance(other, ComplexNumber):
            # use ComplexNumber's division procedure
            return ComplexNumber(self, RealNumber(0)) / other
        else:
            return Fraction.create(RealNumber(1), other) * self

    def __floordiv__(self, other):
        """ Only for internal use and only needed because we defined __floordiv__ for RealNumber"""
        if isinstance(other, Number):
            return self / other
        else:
            raise CastleException(
                f"__floordiv__ only supported for types {type(self)} and {type(other)}"
            )

    def __pow__(self, other):
        if isinstance(other, ComplexNumber):
            # use ComplexNumber's power procedure
            return ComplexNumber(self, RealNumber(0)) ** other
        else:
            # (a/b)^c = (a^c)/(b^c). We have implemented RealNumber ** Fraction and RealNumber ** RealNumber above
            return Fraction.create(self.num ** other, self.den ** other)

    def evaluate(self, state=None):
        return self.simplify()

    def true_value(self):
        """ Get the float value of this Fraction, not the object like evaluate()"""
        val = (self.num / self.den).true_value()
        if abs(np.round(val) - val) < RealNumber.ZERO_CUTOFF:
            # cast floats like 4.0 as ints
            return int(np.round(val))
        return val

    def simplify(self):
        """reduce to lowest terms"""
        if self.num == 0:
            return RealNumber(0)
        if self.den == 0:
            raise CastleException("Can't divide by zero")
        gcd = RealNumber(numberGCD(self.num.value, self.den.value))
        if gcd == self.den:
            # reduces to an integer
            return RealNumber(self.num / gcd)
        return Fraction.create(self.num / gcd, self.den / gcd)

    def __eq__(self, other):
        if isinstance(other, Fraction):
            self_simplify = self.simplify()
            other_simplify = other.simplify()
            return (self_simplify.num, self_simplify.den) == (
                other_simplify.num,
                other_simplify.den,
            )
        elif isinstance(other, RealNumber):
            return self.num / self.den == other
        elif isinstance(other, (int, float)):
            return abs(self.true_value() - other) < RealNumber.ZERO_CUTOFF
        else:
            raise CastleException(
                f"Can't evaluate __eq__ on objects of type {type(self)} and {type(other)}"
            )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        if isinstance(other, Fraction):
            return self.num / self.den < other.num / other.den
        elif isinstance(other, RealNumber):
            return self.num / self.den < other
        elif isinstance(other, (int, float)):
            return self.true_value() < other
        else:
            raise CastleException(
                f"Can't evaluate __lt__ on objects of type {type(self)} and {type(other)}"
            )

    def __gt__(self, other):
        if isinstance(other, Fraction):
            return self.num / self.den > other.num / other.den
        elif isinstance(other, RealNumber):
            return self.num / self.den > other
        elif isinstance(other, (int, float)):
            return self.true_value() > other
        else:
            raise CastleException(
                f"Can't evaluate __gt__ on objects of type {type(self)} and {type(other)}"
            )

    def __le__(self, other):
        return self < other or self == other

    def __ge__(self, other):
        return self > other or self == other

    def derivative(self):
        return 0

    def integral(self):
        pass

    def __repr__(self):
        return f"\\frac{{{self.num}}}{{{self.den}}}"


class ComplexNumber(Number):
    """a + bi"""

    @staticmethod
    def create(a, b):
        """use this instead of __init__ to create ComplexNumber instances"""
        assert isinstance(a, (RealNumber, Fraction)) and isinstance(
            a, (RealNumber, Fraction)
        )

        if b == RealNumber(0):
            # a + 0i = a - no need for a ComplexNumber here
            return a

        return ComplexNumber(a, b)

    def __init__(self, a, b):
        """don't initialize with ComplexNumber() - use ComplexNumber.create() factory instead"""
        assert isinstance(a, (RealNumber, Fraction)) and isinstance(
            b, (RealNumber, Fraction)
        )
        self.a = a
        self.b = b

    def __add__(self, other):
        if isinstance(other, (Fraction, RealNumber)):
            # (a + bi) + c = (a + c) + bi
            return ComplexNumber.create(self.a + other, self.b)
        elif isinstance(other, ComplexNumber):
            # (a + bi) + (c + di) = (a + c) + (b + d)i
            return ComplexNumber.create(self.a + other.a, self.b + other.b)
        else:
            # use other's addition method, which we assume is defined
            return other + self

    def __sub__(self, other):
        return RealNumber(-1) * other + self

    def __mul__(self, other):
        if isinstance(other, (RealNumber, Fraction)):
            # c(a + bi) = ca + (cb)i
            return ComplexNumber.create(other * self.a, other * self.b)
        elif isinstance(other, ComplexNumber):
            # (a+bi)(c+di) = (ac-bd) + (ad+bc)i
            return ComplexNumber.create(
                (self.a * other.a) - (self.b * other.b),
                (self.a * other.b) + (self.b * other.a),
            )
        else:
            return other * self

    def __truediv__(self, other):
        if isinstance(other, (RealNumber, Fraction)):
            return self * (RealNumber(1) / other)
        if isinstance(other, ComplexNumber):
            # (a+bi)/(c+di) = ((a+bi)(c-di)) / ((c+di)(c-di)) = ((ac+bd)+(cb-ad)i) / (c^2+d^2)
            return Fraction.create(
                ComplexNumber.create(
                    (self.a * other.a) + (self.b * other.b),
                    (self.b * other.a) - (self.a * other.b),
                ),
                (other.a ** 2) + (other.b ** 2),
            )
        else:
            return Fraction.create(RealNumber(1), other) * self

    def __floordiv__(self, other):
        """ Only for internal use and only needed because we defined __floordiv__ for RealNumber"""
        if isinstance(other, Number):
            return self / other
        else:
            raise CastleException(
                f"__floordiv__ only supported for types {type(self)} and {type(other)}"
            )

    def __pow__(self, other):
        if isinstance(other, (RealNumber, Fraction)):
            # use DeMoivre's theorem
            r = (self.a ** 2 + self.b ** 2) ** (1 / 2)
            if self.a == 0:
                theta = np.sign(self.b.true_value()) * np.pi / 2
            else:
                theta = float(sympy.atan((self.b / self.a).true_value()))
            return ComplexNumber.create(
                (r ** other) * RealNumber(float(sympy.cos(theta * other.true_value()))),
                (r ** other) * RealNumber(float(sympy.sin(theta * other.true_value()))),
            )
        if isinstance(other, ComplexNumber):
            # use the closed-form expression for (a+bi)^(c+di) given at
            # https://mathworld.wolfram.com/ComplexExponentiation.html
            r = self.a ** 2 + self.b ** 2
            if self.a == 0:
                theta = np.sign(self.b.true_value()) * np.pi / 2
            # we need to consider b = 0 because RealNumber ** ComplexNumber and Fraction ** ComplexNumber get redirected here
            elif self.b == 0:
                theta = 0 if self.a > 0 else np.pi
            else:
                theta = float(sympy.atan((self.b / self.a).true_value()))
            c, d = other.a, other.b
            new_r = r ** (c / 2) * np.exp(-1 * d.true_value() * theta)
            new_theta = c * theta + d * np.log(r.true_value()) / 2
            return ComplexNumber.create(
                new_r * float(sympy.cos(new_theta)), new_r * float(sympy.sin(new_theta))
            )

    def evaluate(self, state=None):
        return ComplexNumber.create(self.a.evaluate(), self.b.evaluate())

    def true_value(self):
        """ Get the real, not the object like evaluate()"""
        return np.complex(self.a.true_value(), self.b.true_value())

    def __eq__(self, other):
        if isinstance(other, ComplexNumber):
            return self.a == other.a and self.b == other.b
        elif isinstance(other, (Number, int, float)):
            return self.a == other
        else:
            raise CastleException(
                f"Can't evaluate __eq__ on objects of type {type(self)} and {type(other)}"
            )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        raise CastleException(
            f"Can't evaluate __lt__ on objects of type {type(self)} and {type(other)}"
        )

    def __gt__(self, other):
        raise CastleException(
            f"Can't evaluate __gt__ on objects of type {type(self)} and {type(other)}"
        )

    def __le__(self, other):
        raise CastleException(
            f"Can't evaluate __le__ on objects of type {type(self)} and {type(other)}"
        )

    def __ge__(self, other):
        raise CastleException(
            f"Can't evaluate __le__ on objects of type {type(self)} and {type(other)}"
        )

    def derivative(self):
        return 0

    def integral(self):
        pass

    def __repr__(self):
        if self.a == 0:
            if self.b == -1:
                return "-i"
            if self.b == 1:
                return "i"
            return f"{self.b}i"
        if self.b == 0:
            return str(self.a)
        if self.b == -1:
            return f"{self.a}-i"
        if self.b == 1:
            return f"{self.a}+i"
        if self.b > 0:
            op = "+"
        elif isinstance(self.b, Fraction):
            return f"{self.a}-{RealNumber(-1)*self.b}i"
        else:
            op = ""
        return f"{self.a}{op}{self.b}i"


def numberGCD(a: int, b: int) -> int:
    if b == 0:
        return a
    else:
        return numberGCD(b, a % b)


def listGCD(values, gcd=numberGCD):
    """
    recursively apply a GCD function to a list of values

    Parameters:
    ----------
        values: the list of items over which we want to find the gcd
        gcd: the gcd function

    Returns:
    -------
        the gcd of all values in "values"
    """
    result = values.pop()
    while values:
        result = gcd(result, values.pop())
    return result


def monomialGCD(a, b) -> Function:
    if isinstance(a, Monomial) and isinstance(b, Monomial) and a.var != b.var:
        return 1
    if isinstance(a, (Number, int)) or isinstance(b, (Number, int)):
        get_value = (
            lambda v: v.coeff
            if isinstance(v, Monomial)
            else (v.value if isinstance(v, Number) else v)
        )
        a = get_value(a)
        b = get_value(b)
        return numberGCD(a, b)

    return Monomial(
        coeff=numberGCD(a.coeff, b.coeff), var=a.var, power=min(a.power, b.power)
    )


class Cases(Function):
    def __init__(self, cases_list):
        self.cases_list = cases_list

    def evaluate(self, state: State):
        for row in self.cases_list:
            if not isinstance(row[1], Relation):
                raise CastleException(f"Improper Cases: {row[1]} is not a relation")
            if row[1].evaluate(state):
                return row[0].evaluate(state)

        # no conditions were satisfied
        raise CastleException("Improper Cases: No case satisfied!")

    def __eq__(self, other):
        pass

    def __ne__(self, other):
        pass

    def derivative(self):
        pass

    def integral(self):
        pass

    def __repr__(self):
        rep = "\\begin{cases}\n"
        for row in self.cases_list:
            rep += str(row[0]) + "&" + str(row[1]) + "\\\\"
        rep += "\n\\end{cases}"
        return rep


class Matrix(Function):
    def __init__(self, mat, type: str):
        self.mat = mat if isinstance(mat, np.ndarray) else np.array(mat)
        self.type = type

    def evaluate(self, state: State):
        return Matrix(
            np.vectorize(lambda entry: entry.evaluate(state))(self.mat), self.type
        )

    def __add__(self, other):
        if not isinstance(other, Matrix):
            raise CastleException(
                f"Operation __add__ not supported between Matrix and {type(other)}"
            )
        if not other.mat.shape == self.mat.shape:
            raise CastleException(
                f"Operation __add__ not supported for matrices with shape {self.mat.shape} and {other.mat.shape}"
            )
        # take this matrix's type by default
        return Matrix(self.mat + other.mat, self.type)

    def __sub__(self, other):
        return self + RealNumber(-1) * other

    def __mul__(self, other):
        # scalar multiplication
        if isinstance(other, Number):
            return Matrix(self.mat * other, self.type)

        # matrix multiplication
        if isinstance(other, Matrix):
            # make sure matrices have correct shape (a,b), (b,a)
            if self.mat.shape[1] != other.mat.shape[0]:
                raise CastleException(
                    f"Can't multiply matrices of shapes {self.mat.shape} and {other.mat.shape}"
                )
            if self.mat.shape[0] == 1 and other.mat.shape[1] == 1:
                # row vector times a column vector, so a dot product
                return RealNumber(np.dot(self.mat, other.mat)[0][0])
            return Matrix(np.matmul(self.mat, other.mat), self.type)

        raise CastleException(
            f"Operation __mul__ not supported between Matrix and {type(other)}"
        )

    def __truediv__(self, other):
        # can only do scalar division
        if isinstance(other, Number):
            return self * Fraction.create(RealNumber(1), other)
        else:
            raise CastleException(
                f"Operation __div__ not supported between Matrix and {type(other)}"
            )

    def __pow__(self, other):
        # can only raise square matrices to powers
        if self.mat.shape[0] != self.mat.shape[1]:
            raise CastleException(
                f"Can't raise matrix with dimension {self.mat.shape} to power (matrix must be square)"
            )
        # can only take integer powers
        if not isinstance(other, RealNumber) or int(other.value) != other.value:
            raise CastleException(f"Can't raise matrix to non-integral power {other}")
        if other.value == 0:
            # return identity matrix
            return Matrix(np.identity(self.mat.shape[0]), self.type)
        if other.value > 0:
            # multiply by itself other.value times
            return reduce(operator.mul, [self] * int(other.value))
        if other.value < 0:
            inverse = self.invert()
            return reduce(operator.mul, [inverse] * (-int(other.value)))

    def __eq__(self, other):
        if not isinstance(other, Matrix) or self.mat.shape != other.mat.shape:
            return False
        return (self.mat == other.mat).all()

    def __ne__(self, other):
        return not self.__eq__(other)

    def derivative(self):
        pass

    def integral(self):
        pass

    def rref(self):
        """return this matrix in row-reduced echelon form"""

        def swap_rows(r1, r2, mat):
            if r1 != r2:
                mat[[r1, r2]] = mat[[r2, r1]]

        def leftmost_nonzero(mat, row):
            """Get index of leftmost nonzero entry in row"""
            for col in range(len(mat[row, :])):
                if mat[row][col] != RealNumber(0):
                    return col
            return float("inf")

        nrows = self.mat.shape[0]
        gmat = self.mat

        all_zero_counter = 0
        for row in range(nrows // 2):
            # if all columns are 0, move row to bottom
            if all(gmat[row, :] == RealNumber(0)):
                swap_rows(row, nrows - all_zero_counter - 1, gmat)
                all_zero_counter += 1

        # move row by row, repeat three steps:
        for row in range(nrows):
            # 1. swap row with leftmost nonzero entry with current row
            if row != nrows - 1:
                leftmost_nonzero_row, _ = min(
                    [(r, leftmost_nonzero(gmat, r)) for r in range(row, nrows)],
                    key=lambda t: t[1],
                )
                swap_rows(row, leftmost_nonzero_row, gmat)

            # 2. Divide this row by scalar so that its first nonzero entry is 1
            # still work at index row, although there could be a different actual row here now
            # use __floordiv__ to create fractions
            nonzero_index = leftmost_nonzero(gmat, row)
            if nonzero_index == float("inf"):
                # can't do any more
                return Matrix(gmat, self.type)
            gmat[row, :] = gmat[row, :] // gmat[row][nonzero_index]

            # 3. clear out other rows' values in column with this row's first nonzero entry
            for lrow in range(nrows):
                if lrow != row and gmat[lrow][nonzero_index] != RealNumber(0):
                    gmat[lrow, :] = (
                        gmat[lrow, :] - gmat[row, :] * gmat[lrow][nonzero_index]
                    )
        return Matrix(gmat, self.type)

    def invert(self):
        """Find inverse of matrix using Gauss-Jordan elimination"""
        # can't take inverse of non-square matrix
        if self.mat.shape[0] != self.mat.shape[1]:
            raise CastleException(
                f"Can't take inverse of matrix with dimensions {self.mat.shape}"
            )
        # can't take inverse if matrix is singular (determinant is 0)
        if self.determinant() == RealNumber(0):
            raise CastleException(f"Can't take inverse: matrix is singular")

        nrows = self.mat.shape[0]
        # append identity matrix to the right
        identity = np.vectorize(lambda v: RealNumber(v))(np.identity(nrows))
        gmat = Matrix(np.append(self.mat, identity, axis=1), self.type)

        # take rref. right nrows columns were originally identity, now they're the inverse
        return Matrix(gmat.rref().mat[:, nrows : 2 * nrows], self.type)

    def determinant(self):
        """ Calculate determinant using Laplace's formula:
        det(A) = \\sum{j=0}{n-1}{(-1)^j a_{0j} M_{0j}}
        where M_{0j} is the determinant of A without its first row and jth column """
        # matrix must be square
        if self.mat.shape[0] != self.mat.shape[1]:
            raise CastleException(
                f"Can't take determinant: Matrix of shape {self.mat.shape} is not square"
            )

        def determinant_recurse(mat):
            """ takes numpy array as an argument so we can recurse """
            # base case: dimension 2 determinant is ad - bc
            if mat.shape[0] == 2:
                return (mat[0][0] * mat[1][1]) - (mat[1][0] * mat[0][1])

            return reduce(
                operator.add,
                [
                    (RealNumber(-1) ** RealNumber(j))
                    * mat[0][j]
                    * determinant_recurse(np.delete(np.delete(mat, 0, 0), j, 1))
                    for j in range(mat.shape[0])
                ],
            )

        return determinant_recurse(self.mat)

    def transpose(self):
        # matrix must be square
        if self.mat.shape[0] != self.mat.shape[1]:
            raise CastleException(
                f"Can't take transpose of matrix of shape {self.mat.shape}"
            )
        return Matrix(np.transpose(self.mat), self.type)

    def __repr__(self):
        mat_string = ""
        for row in self.mat:
            for entry in row[:-1]:
                mat_string += str(entry) + "&"
            mat_string += str(row[-1]) + "\\\\"

        return f"\\begin{{{self.type}}}{mat_string}\\end{{{self.type}}}"


class Determinant:
    """ The determinant of a matrix.
    Determinants are indicated by a matrix created with the vmatrix environment"""

    def __init__(self, mat):
        self.matrix = Matrix(mat, "vmatrix")

    def evaluate(self, state: State):
        return self.matrix.evaluate(state).determinant()

    def __repr__(self):
        return str(self.matrix)


class Relation:
    def __init__(self, rel_chain):
        self.rel_chain = rel_chain

    def evaluate(self, state):
        for i in range(1, len(self.rel_chain) - 1, 2):
            rel = self.rel_chain[i]
            left = self.rel_chain[i - 1].evaluate(state)
            right = self.rel_chain[i + 1].evaluate(state)
            if isinstance(right, Number) and isinstance(left, Number):
                if not rel(left, right):
                    return False
            else:
                raise CastleException(
                    f"Cannot compute relation {rel} on {left} and {right}"
                )
        return True

    def __repr__(self):
        output = ""
        for ex in self.rel_chain:
            output += str(inv_rel_dict.get(ex, ex))
        return output


class UserDefinedFunc:
    def __init__(self, args: list, func_body: Expression):
        self.args = args
        self.func_body = func_body

    def evaluate(self, state: State):
        return None

    def __repr__(self):
        return str(tuple(self.args)) + "\\to" + str(self.func_body)


class FunctionCall:
    def __init__(self, function_name, passed_args: list):
        self.function_name = function_name
        self.passed_args = passed_args

    def evaluate(self, state: State):
        if self.function_name == parse.FUNC_GCD:
            eval_args = [arg.evaluate(state).true_value() for arg in self.passed_args]
            if all([isinstance(arg, int) for arg in eval_args]):
                return listGCD(eval_args)
            raise CastleException("All arguments to gcd must be integers")
        if self.function_name == parse.FUNC_RREF:
            if len(self.passed_args) != 1:
                raise CastleException("rref takes 1 argument")
            mat = self.passed_args[0].evaluate(state)
            if not isinstance(mat, Matrix):
                raise CastleException("rref argument must be matrix")
            return mat.rref()

        if self.function_name in builtin_func_dict:
            eval_args = [arg.evaluate(state).true_value() for arg in self.passed_args]
            return RealNumber(float(builtin_func_dict[self.function_name](*eval_args)))
        else:
            function = state[self.function_name]
            if self.passed_args:
                state.push_layer()
                for arg, value in zip(function.args, self.passed_args):
                    # evaluate args here to avoid bugs where passed variable has same name as function arg
                    value = Number.number_init(value.evaluate(state))
                    state[arg.name] = value
                result = function.func_body.evaluate(state)
                state.pop_layer()
            else:
                result = function.func_body.evaluate(state)
            return result


class SumFunc:
    def __init__(self, var: Variable, lower_bound_expr, upper_bound_expr, sum_expr):
        self.var = var
        self.sum_expr = sum_expr
        self.upper_bound_expr = upper_bound_expr
        self.lower_bound_expr = lower_bound_expr

    def evaluate(self, state: State):
        lower_bound = self.lower_bound_expr.evaluate(state)
        if (
            not isinstance(lower_bound, RealNumber)
            or int(lower_bound.value) != lower_bound.value
        ):
            raise CastleException("Sum lower bound must evaluate to integer")
        upper_bound = self.upper_bound_expr.evaluate(state)
        if upper_bound.value == float("inf"):
            # TODO
            pass
        if (
            not isinstance(upper_bound, RealNumber)
            or int(upper_bound.value) != upper_bound.value
        ):
            raise CastleException("Sum upper bound must evaluate to integer")

        state.push_layer()
        max_bound = int(max(upper_bound, lower_bound).value)
        min_bound = int(min(upper_bound, lower_bound).value)
        sum_val = RealNumber(0)
        for i in range(min_bound, max_bound + 1):
            state[self.var.name] = RealNumber(i)
            sum_val += self.sum_expr.evaluate(state)
        state.pop_layer()
        return sum_val

    def __repr__(self):
        return f"\\sum_{{{self.var.name} = {self.lower_bound_expr}}}^{{{self.upper_bound_expr}}}{{{self.sum_expr}}}"


class ProdFunc:
    def __init__(self, var: Variable, lower_bound_expr, upper_bound_expr, prod_expr):
        self.var = var
        self.prod_expr = prod_expr
        self.upper_bound_expr = upper_bound_expr
        self.lower_bound_expr = lower_bound_expr

    def evaluate(self, state: State):
        lower_bound = self.lower_bound_expr.evaluate(state)
        if (
            not isinstance(lower_bound, RealNumber)
            or int(lower_bound.value) != lower_bound.value
        ):
            raise CastleException("Prod lower bound must evaluate to integer")
        upper_bound = self.upper_bound_expr.evaluate(state)
        if upper_bound.value == float("inf"):
            # TODO
            pass
        if (
            not isinstance(upper_bound, RealNumber)
            or int(upper_bound.value) != upper_bound.value
        ):
            raise CastleException("Prod upper bound must evaluate to integer")

        state.push_layer()
        max_bound = int(max(upper_bound, lower_bound).value)
        min_bound = int(min(upper_bound, lower_bound).value)
        prod_val = RealNumber(1)
        for i in range(min_bound, max_bound + 1):
            state[self.var.name] = RealNumber(i)
            prod_val *= self.prod_expr.evaluate(state)
        state.pop_layer()
        return prod_val

    def __repr__(self):
        return f"\\prod_{{{self.var.name} = {self.lower_bound_expr}}}^{{{self.upper_bound_expr}}}{{{self.prod_expr}}}"


class Limit:
    def __init__(self, var: Variable, lim_to, expr):
        self.var = var
        self.lim_to = lim_to
        self.expr = expr

    def evaluate(self, state: State):
        # TODO
        pass

    def __repr__(self):
        return f"\\lim_{{{self.var} \\to {self.lim_to}}}{{{self.expr}}}"


class Integral:
    def __init__(self, lower, upper, expr, var):
        self.lower = lower
        self.upper = upper
        self.expr = expr
        self.var = var

    def evaluate(self, state: State):
        # TODO
        pass

    def __repr__(self):
        return f"\\int_{{{self.lower}}}^{{{self.upper}}}{{{self.expr}\\dd {self.var}}}"


class Floor:
    def __init__(self, expr):
        self.expr = expr

    def evaluate(self, state: State):
        return RealNumber(float(math.floor(self.expr.evaluate(state).true_value())))

    def __repr__(self):
        return f"\\lfloor {self.expr} \\rfloor"


class Ceiling:
    def __init__(self, expr):
        self.expr = expr

    def evaluate(self, state: State):
        return RealNumber(float(math.ceil(self.expr.evaluate(state).true_value())))

    def __repr__(self):
        return f"\\lceil {self.expr} \\rceil"


class Derivative:
    def __init__(self, cmd: str, order: RealNumber, expr, var):
        self.cmd = cmd
        self.order = order
        self.expr = expr
        self.var = var

    def evaluate(self, state: State):
        # TODO
        pass

    def __repr__(self):
        if self.order:
            return f"{self.cmd}[{self.order}]{{{self.expr}}}{{{self.var}}}"
        else:
            return f"{self.cmd}{{{self.expr}}}{{{self.var}}}"


class Root:
    def __init__(self, expr, n=None):
        self.expr = expr
        self.n = n

    def evaluate(self, state: State):
        if self.n is None:
            return RealNumber(float(math.sqrt(self.expr.evaluate(state).true_value())))
        n = self.n.evaluate(state).true_value()
        if n == 0:
            raise CastleException(f"Can't take 0th root of {self.expr}")
        return RealNumber(
            float(math.pow(self.expr.evaluate(state).true_value(), 1 / n))
        )

    def __repr__(self):
        if self.n is None:
            return f"\\sqrt{{{self.expr}}}"
        return f"\\sqrt[{self.n}]{{{self.expr}}}"


class Choose:
    def __init__(self, n, k):
        self.n = n
        self.k = k

    def evaluate(self, state: State):
        n = self.n.evaluate(state).true_value()
        k = self.k.evaluate(state).true_value()
        if int(n) != n or int(k) != k:
            raise CastleException(
                f"Inputs {self.n} and {self.k} to binom must be integers"
            )
        return RealNumber(int(comb(int(n), int(k))))

    def __repr__(self):
        return f"\\binom{{{self.n}}}{{{self.k}}}"


class CastleException(Exception):
    pass
