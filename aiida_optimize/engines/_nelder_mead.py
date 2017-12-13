# ******NOTICE***************
# optimize.py module by Travis E. Oliphant
#
# You may copy and use this module as you see fit with no
# guarantee implied provided you keep this notice in all copies.
# *****END NOTICE************
#
# The additional license terms given in ADDITIONAL_TERMS.txt apply to this
# file.
# pylint: disable=invalid-name
"""
Defines a Nelder-Mead optimization engine.
"""

from __future__ import division, print_function, unicode_literals

import numpy as np
import scipy.linalg as la
from fsc.export import export
from decorator import decorator

from aiida.orm.data.base import List

from ._base import OptimizationEngine

RHO = 1  # alpha in Wikipedia
CHI = 2
PSI = 0.5
SIGMA = 0.5

def update_method(next_submit=None):
    @decorator
    def inner(func, self, outputs):
        self.next_submit = next_submit
        self.next_update = None
        func(self, outputs)
    return inner

def submit_method(next_update=None):
    @decorator
    def inner(func, self):
        self.next_submit = None
        self.next_update = next_update
        return func(self)
    return inner

@export
class NelderMead(OptimizationEngine):
    """
    TODO
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        simplex,
        fun_simplex=None,
        xtol=1e-4,
        ftol=1e-4,
        num_iter=0,
        max_iter=1000,
        extra_points=None,
        result_key='cost_value',
        next_submit='submit_initialize',
        next_update=None,
        finished=False,
        result_state=None,
    ):
        super(NelderMead, self).__init__(result_state=result_state)

        self.simplex = np.array(simplex)
        assert len(self.simplex) == self.simplex.shape[1] + 1

        if fun_simplex is None:
            self.fun_simplex = None
        else:
            self.fun_simplex = np.array(fun_simplex)

        self.xtol = xtol
        self.ftol = ftol

        self.max_iter = max_iter
        self.num_iter = num_iter

        if extra_points is None:
            self.extra_points = {}
        else:
            self.extra_points = dict(extra_points)

        self.result_key = result_key

        self.next_submit = next_submit
        self.next_update = next_update

        self.finished = finished

    def _get_values(self, outputs):
        return [
            res[self.result_key].value for _, res in sorted(outputs.items())
        ]

    def _get_single_result(self, outputs):
        (idx, ) = outputs.keys()
        x = np.array(self._result_mapping[idx].input['x'].get_attr('list'))
        f = outputs[idx][self.result_key].value
        return x, f

    @submit_method(next_update='update_initialize')
    def submit_initialize(self):
        return [self._to_input_list(x) for x in self.simplex]

    @staticmethod
    def _to_input_list(x):
        l = List()
        l.extend(x)
        return {'x': l}

    @update_method(next_submit='new_iter')
    def update_initialize(self, outputs):
        self.fun_simplex = np.array(self._get_values(outputs))

    @submit_method()
    def new_iter(self):
        self.do_sort()
        self.check_finished()
        if self.finished:
            self.next_update = 'finalize'
            return []
        self.num_iter += 1
        xr = (1 + RHO) * self.xbar - RHO * self.simplex[-1]
        self.next_update = 'choose_step'
        return [self._to_input_list(xr)]

    @update_method()
    def finalize(self, outputs):
        pass

    @property
    def xbar(self):
        return np.average(self.simplex[:-1], axis=0)

    def do_sort(self):
        idx = np.argsort(self.fun_simplex)
        self.fun_simplex = np.take(self.fun_simplex, idx, axis=0)
        self.simplex = np.take(self.simplex, idx, axis=0)

    def check_finished(self):
        self.finished = (
            np.max(la.norm(self.simplex[1:] - self.simplex[0], axis=-1)
                   ) < self.xtol
            and np.max(np.abs(self.fun_simplex[1:] - self.fun_simplex[0])
                       ) < self.ftol
        )

    @update_method()
    def choose_step(self, outputs):
        xr, fxr = self._get_single_result(outputs)
        self.extra_points = {'xr': (xr, fxr)}
        if fxr < self.fun_simplex[0]:
            self.next_submit = 'submit_expansion'
        else:
            if fxr < self.fun_simplex[-2]:
                self._update_last(xr, fxr)
                self.next_submit = 'new_iter'
            else:
                if fxr < self.fun_simplex[-1]:
                    self.next_submit = 'submit_contraction'
                else:
                    self.next_submit = 'submit_inside_contraction'

    def _update_last(self, x, f):
        self.simplex[-1] = x
        self.fun_simplex[-1] = f

    @submit_method(next_update='update_expansion')
    def submit_expansion(self):
        xe = (1 + RHO * CHI) * self.xbar - RHO * CHI * self.simplex[-1]
        return [self._to_input_list(xe)]

    @update_method(next_submit='new_iter')
    def update_expansion(self, outputs):
        xe, fxe = self._get_single_result(outputs)
        xr, fxr = self.extra_points['xr']
        if fxe < fxr:
            self._update_last(xe, fxe)
        else:
            self._update_last(xr, fxr)

    @submit_method(next_update='update_contraction')
    def submit_contraction(self):
        xc = (1 + PSI * RHO) * self.xbar - PSI * RHO * self.simplex[-1]
        return [self._to_input_list(xc)]

    @update_method()
    def update_contraction(self, outputs):
        xc, fxc = self._get_single_result(outputs)
        _, fxr = self.extra_points['xr']
        if fxc < fxr:
            self._update_last(xc, fxc)
            self.next_submit = 'new_iter'
        else:
            self.next_submit = 'submit_shrink'

    @submit_method(next_update='update_inside_contraction')
    def submit_inside_contraction(self):
        xcc = ((1 - PSI) * self.xbar + PSI * self.simplex[-1])
        return [self._to_input_list(xcc)]

    @update_method()
    def update_inside_contraction(self, outputs):
        xcc, fxcc = self._get_single_result(outputs)
        if fxcc < self.fun_simplex[-1]:
            self._update_last(xcc, fxcc)
            self.next_submit = 'new_iter'
        else:
            self.next_submit = 'submit_shrink'

    @submit_method(next_update='update_shrink')
    def submit_shrink(self):
        self.simplex[
            1:
        ] = self.simplex[0] + SIGMA * (self.simplex[1:] - self.simplex[0])
        self.fun_simplex[1:] = np.nan
        return [self._to_input_list(x) for x in self.simplex[1:]]

    @update_method(next_submit='new_iter')
    def update_shrink(self, outputs):
        self.fun_simplex[1:] = self._get_values(outputs)

    @property
    def _state(self):
        return {
            k: v
            for k, v in self.__dict__.items() if k not in ['_result_mapping']
        }

    @property
    def is_finished(self):
        return self.finished

    def _create_inputs(self):
        return getattr(self, self.next_submit)()

    def _update(self, outputs):
        getattr(self, self.next_update)(outputs)

    @property
    def result_value(self):
        _, value = self._get_optimal_result()
        assert value.value == self.fun_simplex[0]
        return value

    @property
    def result_index(self):
        index, _ = self._get_optimal_result()
        return index

    def _get_optimal_result(self):
        """
        Return the index and optimizatin value of the best calculation workflow.
        """
        cost_values = {
            k: v.output[self.result_key]
            for k, v in self._result_mapping.items()
        }
        return min(cost_values.items(), key=lambda item: item[1].value)
